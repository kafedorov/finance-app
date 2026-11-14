from sqlalchemy import select

from .categorization import EXPENSE_CATEGORIES
from .database import UserCategory


def category_names(db, user_id):
    custom = db.scalars(select(UserCategory.name).where(UserCategory.user_id == user_id).order_by(UserCategory.name))
    return [*EXPENSE_CATEGORIES, *custom]


def normalize_name(value):
    return " ".join(value.split())
