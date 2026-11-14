"""Shared import contract. Legacy defaults preserve T-Bank adapter compatibility.

The registry assigns the bank and adapter version from the selected adapter.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Transaction:
    occurred_at: str
    posted_at: str
    amount_minor: int
    currency: str
    original_amount_minor: int
    original_currency: str
    description: str
    card_last4: str | None
    source_page: int


@dataclass(frozen=True)
class BalanceSnapshot:
    account_key: str
    account_last4: str
    as_of: str
    amount_minor: int
    currency: str
    balance_type: str = "available"


@dataclass(frozen=True)
class ParsedCertificate:
    kind: str
    snapshots: tuple[BalanceSnapshot, ...]
    transactions: tuple[Transaction, ...] = ()
    period_start: str | None = None
    period_end: str | None = None
    credits_minor: int | None = None
    debits_minor: int | None = None
    adapter_version: str = "tbank-certificates-v1"
    bank: str = "tbank"
    account_kind: str | None = None
