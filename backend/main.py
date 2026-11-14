from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated
from urllib.parse import unquote, urlparse

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import services, snowball
from .categories import category_names, normalize_name
from .categorization import EXPENSE_CATEGORIES, KINDS, requires_manual_review
from .database import Account, CategoryRule, Document, LoginAttempt, LoginSession, ROOT, Snapshot, Transaction, User, UserCategory, initialize, make_database
from .importers.registry import parse_document, supported_banks

PASSWORDS = PasswordHasher()
COOKIE = "svod_session"
MAX_PDF = 15 * 1024 * 1024


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def db_dep(request: Request):
    with request.app.state.sessions() as db:
        yield db


DB = Annotated[Session, Depends(db_dep)]


def require_user(request: Request, db: DB) -> str:
    token = request.cookies.get(COOKIE)
    session = db.get(LoginSession, digest(token)) if token else None
    if not session or session.expires < time.time():
        raise HTTPException(401, "Войдите в профиль.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session.csrf):
            raise HTTPException(403, "Обновите страницу и повторите действие.")
    request.state.login = session
    return session.user_id


UID = Annotated[str, Depends(require_user)]


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class Setup(Credentials):
    name: str = Field(min_length=1, max_length=80)


class EditTransaction(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    kind: str
    remember: bool = False


class ConnectPortfolio(BaseModel):
    url: str = Field(max_length=300)
    kind: str
    name: str = Field(default="", max_length=100)
    institution: str | None = Field(default=None, max_length=64)


class NewCategory(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class AccountVisibility(BaseModel):
    is_hidden: bool


def normalize_email(value):
    value = value.strip().casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise HTTPException(422, "Проверьте адрес электронной почты.")
    return value


def validate_classification(kind, category, amount, allowed_categories=None):
    if kind not in KINDS:
        raise HTTPException(422, "Неизвестный тип операции.")
    if kind == "expense" and amount >= 0 or kind in {"income", "refund"} and amount <= 0:
        raise HTTPException(422, "Тип операции не соответствует направлению движения денег.")
    if kind == "expense" and category not in (allowed_categories or EXPENSE_CATEGORIES):
        raise HTTPException(422, "Выберите категорию расхода из списка.")


def issue_session(db, user, response, production):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=digest(token), user_id=user.id, csrf=csrf, expires=int(time.time()) + 14 * 86400))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=production, samesite="strict", max_age=14 * 86400, path="/")
    return {"id": user.id, "name": user.name, "email": user.email, "csrf": csrf}


def create_app(database_url=None, production=None):
    production = (os.environ.get("APP_ENV") == "production") if production is None else production
    if production and not (database_url or os.environ.get("DATABASE_URL", "")).startswith("postgresql"):
        raise RuntimeError("Production requires an explicit PostgreSQL DATABASE_URL")
    engine, sessions = make_database(database_url)
    initialize(engine)
    app = FastAPI(title="Свод · личные финансы", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine, app.state.sessions = engine, sessions
    hosts = os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if production and ("*" in hosts or "testserver" in hosts):
        raise RuntimeError("Set ALLOWED_HOSTS to your actual domain in production")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def security(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = os.environ.get("APP_ORIGIN") or str(request.base_url).rstrip("/")
            if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Недопустимый источник запроса."}, 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path in {"/", "/index.html", "/app.js", "/styles.css", "/sw.js"}:
            response.headers["Cache-Control"] = "no-cache"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(IntegrityError)
    async def conflict(_, __):
        return JSONResponse({"detail": "Данные уже изменились. Обновите страницу и повторите действие."}, 409)

    @app.get("/health")
    def health(db: DB):
        db.execute(select(1))
        return {"status": "ok"}

    def setup_allowed(request, db):
        return not production and request.client and request.client.host in {"127.0.0.1", "::1", "testclient"} and db.scalar(select(func.count()).select_from(User)) == 0

    @app.get("/api/status")
    def status(request: Request, db: DB):
        return {"setup_allowed": bool(setup_allowed(request, db)), "categories": EXPENSE_CATEGORIES, "supported_banks": supported_banks()}

    @app.post("/api/setup")
    def setup(body: Setup, request: Request, response: Response, db: DB):
        if not setup_allowed(request, db):
            raise HTTPException(403, "Создание профиля доступно администратору сервера.")
        if len(body.password) < 6:
            raise HTTPException(422, "Пароль должен содержать не меньше 6 символов.")
        # Fixed initial ID also prevents a race creating two first profiles.
        user = User(id="00000000000000000000000000000001", email=normalize_email(body.email), name=body.name.strip(), password_hash=PASSWORDS.hash(body.password), created_at=services.now_iso())
        db.add(user)
        db.flush()
        return issue_session(db, user, response, production)

    @app.post("/api/login")
    def login(body: Credentials, request: Request, response: Response, db: DB):
        email = normalize_email(body.email)
        ip = request.client.host if request.client else "unknown"
        now = int(time.time())
        db.query(LoginAttempt).filter(LoginAttempt.at < now - 900).delete()
        attempts = list(db.scalars(select(LoginAttempt).where(or_(LoginAttempt.email == email, LoginAttempt.ip == ip))))
        if sum(a.email == email for a in attempts) >= 8 or sum(a.ip == ip for a in attempts) >= 40:
            db.commit()
            raise HTTPException(429, "Слишком много попыток входа. Попробуйте через 15 минут.")
        user = db.scalar(select(User).where(User.email == email))
        valid = False
        if user:
            try:
                valid = PASSWORDS.verify(user.password_hash, body.password)
            except VerificationError:
                pass
        else:
            # Keep unknown-user requests expensive too.
            PASSWORDS.hash(body.password)
        if not valid:
            db.add(LoginAttempt(email=email, ip=ip, at=now))
            db.commit()
            raise HTTPException(401, "Неверная почта или пароль.")
        db.query(LoginAttempt).filter(LoginAttempt.email == email).delete()
        db.query(LoginSession).filter(LoginSession.expires < now).delete()
        return issue_session(db, user, response, production)

    @app.get("/api/me")
    def me(request: Request, db: DB, uid: UID):
        user = db.get(User, uid)
        return {"id": uid, "name": user.name, "email": user.email, "csrf": request.state.login.csrf}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, db: DB, uid: UID):
        db.delete(request.state.login)
        db.commit()
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/dashboard")
    def dashboard(db: DB, uid: UID, start: str = "", end: str = "", bank: str = ""):
        today = date.today()
        start = start or today.replace(day=1).isoformat()
        end = end or today.isoformat()
        try:
            a, b = date.fromisoformat(start), date.fromisoformat(end)
            if a > b:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Проверьте период.")
        return services.dashboard(db, uid, start, end, bank=bank)

    @app.get("/api/categories")
    def categories(db: DB, uid: UID):
        return {"categories": category_names(db, uid)}

    @app.post("/api/categories")
    def create_category(body: NewCategory, db: DB, uid: UID):
        name = normalize_name(body.name)
        if not name:
            raise HTTPException(422, "Введите название категории.")
        existing = next((c for c in category_names(db, uid) if c.casefold() == name.casefold()), None)
        if not existing:
            db.add(UserCategory(user_id=uid, name=name, normalized_name=name.casefold()))
            db.commit()
        return {"name": existing or name, "categories": category_names(db, uid)}

    @app.get("/api/transactions")
    def transactions(db: DB, uid: UID, start: str = "", end: str = "", kind: str = "", q: str = "", category: str = "", page: int = 1, bank: str = "", account_id: str = ""):
        accounts = {a.id: a for a in services.scoped_accounts(db, uid, bank)}
        account_ids = list(accounts)
        query = select(Transaction).where(Transaction.user_id == uid, Transaction.account_id.in_(account_ids))
        if account_id:
            query = query.where(Transaction.account_id == account_id)
        if start:
            query = query.where(Transaction.occurred_at >= start)
        if end:
            query = query.where(Transaction.occurred_at < end + "T99")
        if kind:
            query = query.where(Transaction.kind == kind)
        if category:
            query = query.where(Transaction.category == category)
        if q:
            query = query.where(Transaction.description.ilike("%" + q[:100].replace("%", "").replace("_", "") + "%"))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        page = min(max(page, 1), max(1, (total + 39) // 40))
        items = db.scalars(query.order_by(Transaction.occurred_at.desc(), Transaction.id).offset((page - 1) * 40).limit(40))
        return {"items": [services.transaction_dict(t, accounts[t.account_id]) for t in items], "total": total, "page": page, "pages": max(1, (total + 39) // 40)}

    @app.post("/api/reviews/acknowledge")
    def acknowledge_reviews(db: DB, uid: UID, bank: str = ""):
        count = services.acknowledge_reviews(db, uid, bank)
        db.commit()
        return {"acknowledged": count}

    @app.patch("/api/accounts/{account_id}/visibility")
    def account_visibility(account_id: str, body: AccountVisibility, db: DB, uid: UID):
        account = db.scalar(select(Account).where(Account.id == account_id, Account.user_id == uid))
        if not account:
            raise HTTPException(404, "Счет не найден.")
        if account.kind not in {"deposit", "savings"}:
            raise HTTPException(422, "Сейчас скрытие доступно для вкладов и накопительных счетов.")
        account.is_hidden = body.is_hidden
        db.commit()
        return {"id": account.id, "is_hidden": account.is_hidden}

    @app.patch("/api/transactions/{transaction_id}")
    def edit_transaction(transaction_id: str, body: EditTransaction, db: DB, uid: UID):
        t = db.scalar(select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == uid))
        if not t:
            raise HTTPException(404, "Операция не найдена.")
        validate_classification(body.kind, body.category, t.amount_minor, category_names(db, uid))
        t.category, t.kind, t.manual, t.review_acknowledged = body.category, body.kind, True, False
        affected = 1
        account = db.get(Account, t.account_id)
        if body.remember and not requires_manual_review(account.bank, t.description, t.amount_minor):
            direction = -1 if t.amount_minor < 0 else 1
            rule = db.scalar(select(CategoryRule).where(CategoryRule.user_id == uid, CategoryRule.description == t.description, CategoryRule.direction == direction))
            if not rule:
                rule = CategoryRule(user_id=uid, description=t.description, direction=direction, category=body.category, kind=body.kind)
                db.add(rule)
            rule.category, rule.kind = body.category, body.kind
            # A sign filter keeps a refund from turning into an expense.
            sign = Transaction.amount_minor < 0 if t.amount_minor < 0 else Transaction.amount_minor > 0
            affected = db.query(Transaction).filter(Transaction.user_id == uid, Transaction.description == t.description, sign).update({"category": body.category, "kind": body.kind, "manual": True, "review_acknowledged": False}, synchronize_session=False)
        db.commit()
        return {"ok": True, "affected": affected}

    @app.post("/api/imports/preview")
    async def preview(request: Request, db: DB, uid: UID):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_PDF:
                raise HTTPException(413, "Максимальный размер справки — 15 МБ.")
        checksum = hashlib.sha256(content).hexdigest()
        old = db.scalar(select(Document).where(Document.user_id == uid, Document.sha256 == checksum))
        if old and old.status == "imported":
            return {"already_imported": True, "id": old.id, "summary": old.summary}
        if old and old.expires > time.time():
            return {"id": old.id, "summary": services.preview_summary(db, uid, old.payload)}
        try:
            parsed = await run_in_threadpool(parse_document, bytes(content))
        except Exception as exc:
            # Do not leak text from malformed private documents into logs or errors.
            if isinstance(exc, ValueError):
                message = str(exc)
                if not re.search("[А-Яа-я]", message):
                    message = "Не удалось сверить справку. Возможно, банк изменил формат документа; импорт не выполнен."
            else:
                message = "Не удалось прочитать PDF. Проверьте, что это исходная банковская справка с текстовым слоем."
            raise HTTPException(422, message)
        payload = asdict(parsed)
        summary = services.preview_summary(db, uid, payload)
        filename = unquote(request.headers.get("X-Filename", "Справка.pdf")).replace("\\", "/").split("/")[-1][:200]
        doc = old or Document(user_id=uid, sha256=checksum, filename=filename, adapter=parsed.adapter_version, status="pending", created_at=services.now_iso(), expires=int(time.time()) + 1800)
        doc.payload, doc.summary, doc.expires = payload, summary, int(time.time()) + 1800
        db.add(doc)
        # Expired unconfirmed data is removed when this user next uploads.
        db.query(Document).filter(Document.user_id == uid, Document.status == "pending", Document.expires < int(time.time()), Document.sha256 != checksum).delete()
        db.commit()
        return {"id": doc.id, "summary": summary}

    @app.post("/api/imports/{document_id}/confirm")
    def confirm(document_id: str, db: DB, uid: UID):
        doc = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == uid).with_for_update())
        if not doc:
            raise HTTPException(404, "Загрузка не найдена.")
        if doc.status == "imported":
            return {"already_imported": True, "summary": doc.summary}
        if doc.expires < time.time():
            raise HTTPException(410, "Время проверки истекло. Загрузите справку повторно.")
        try:
            result = services.persist_import(db, doc)
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(409, str(exc))
        return {"summary": result}

    @app.post("/api/portfolios")
    def connect(body: ConnectPortfolio, db: DB, uid: UID):
        if body.kind not in {"broker", "iis"}:
            raise HTTPException(422, "Выберите брокерский счет или ИИС.")
        available_banks = {b["id"] for b in supported_banks()}
        available_banks.update(a.institution for a in services.scoped_accounts(db, uid, include_hidden=True) if a.institution)
        institution = body.institution
        if not institution and len(available_banks) == 1:
            institution = next(iter(available_banks))
        if institution and institution not in available_banks:
            raise HTTPException(422, "Выберите банк из доступных вариантов.")
        try:
            key = snowball.public_key(body.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if db.scalar(select(Account).where(Account.user_id == uid, Account.bank == "snowball", Account.external_key == key)):
            raise HTTPException(409, "Этот портфель уже подключен.")
        if db.query(Account).filter(Account.user_id == uid, Account.bank == "snowball").count() >= 10:
            raise HTTPException(422, "Доступно до 10 портфелей на профиль.")
        try:
            amount, details = snowball.fetch_portfolio(body.url)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise HTTPException(502, "Не удалось получить показатели Snowball. Проверьте публичную ссылку и повторите позже.")
        account = Account(user_id=uid, bank="snowball", institution=institution, external_key=key, name=body.name.strip() or ("Брокерский счет" if body.kind == "broker" else "ИИС"), kind=body.kind, currency="RUB", source_url=f"https://snowball-income.com/public/portfolios/{key}", last_attempt=int(time.time()))
        db.add(account)
        db.flush()
        db.add(Snapshot(user_id=uid, account_id=account.id, as_of=services.now_iso(), amount_minor=amount, source="snowball", details=details))
        db.commit()
        return {"id": account.id, "ok": True}

    @app.post("/api/portfolios/{account_id}/refresh")
    def refresh(account_id: str, db: DB, uid: UID):
        account = db.scalar(select(Account).where(Account.user_id == uid, Account.id == account_id, Account.bank == "snowball").with_for_update())
        if not account:
            raise HTTPException(404, "Портфель не найден.")
        if account.last_attempt and time.time() - account.last_attempt < 60:
            raise HTTPException(429, "Показатели можно обновлять раз в минуту.")
        account.last_attempt = int(time.time())
        try:
            amount, details = snowball.fetch_portfolio(account.source_url)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            account.last_error = "Не удалось обновить Snowball. Показан последний успешный снимок."
            db.commit()
            raise HTTPException(502, account.last_error)
        account.last_error = None
        stamp = services.now_iso()
        db.add(Snapshot(user_id=uid, account_id=account.id, as_of=stamp, amount_minor=amount, source="snowball", details=details))
        db.commit()
        return {"ok": True}

    @app.get("/api/export")
    def export(db: DB, uid: UID):
        data = services.dashboard(db, uid, "1900-01-01", "2200-01-01", include_hidden=True)
        txs = [{**services.transaction_dict(t), "document_id": t.document_id} for t in db.scalars(select(Transaction).where(Transaction.user_id == uid))]
        snapshots = [{k: getattr(s, k) for k in ("id", "account_id", "as_of", "amount_minor", "source", "details")} for s in db.scalars(select(Snapshot).where(Snapshot.user_id == uid))]
        rules = [{k: getattr(r, k) for k in ("description", "direction", "category", "kind")} for r in db.scalars(select(CategoryRule).where(CategoryRule.user_id == uid))]
        documents = [{k: getattr(d, k) for k in ("id", "filename", "sha256", "adapter", "created_at", "summary")} for d in db.scalars(select(Document).where(Document.user_id == uid, Document.status == "imported"))]
        return JSONResponse({"format": "svod-export-v1", "exported_at": services.now_iso(), "accounts": data["accounts"], "transactions": txs, "snapshots": snapshots, "category_rules": rules, "custom_categories": list(db.scalars(select(UserCategory.name).where(UserCategory.user_id == uid))), "documents": documents}, headers={"Content-Disposition": 'attachment; filename="svod-export.json"'})

    app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
    return app
