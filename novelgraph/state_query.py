"""Read-only, precisely scoped current world-state retrieval."""
from __future__ import annotations

from decimal import Decimal
import json
import sqlite3

from .world_state import _id, _number, world_state

ASSET_TYPES = ("liquid", "stock", "bond", "real_estate")
SCOPES = {
    "assets": ASSET_TYPES,
    "net_assets": (*ASSET_TYPES, "liability"),
    "liquid_assets": ("liquid",),
    "cash": (),
    "stock": ("stock",),
    "bond": ("bond",),
    "real_estate": ("real_estate",),
    "liabilities": ("liability",),
    "relationships": ("relationship",),
    "knowledge": ("knowledge",),
    "threads": ("thread",),
    "narrative": ("narrative",),
    "status": ("status",),
    "time": (),
    "ownership": (),
    "contracts": (),
}


def _evidence(row: sqlite3.Row) -> dict:
    return {
        "source_episode": row["source_episode"],
        "effective_episode": row["effective_episode"],
        "candidate_id": row["candidate_id"],
        "certainty": "approved",
        "evidence": {
            "text": row["evidence_text"],
            "start": row["evidence_start"],
            "end": row["evidence_end"],
            "source_sha256": row["source_sha256"],
        },
    }


def _ledger(db: sqlite3.Connection, work_id: str, episode: int) -> list[sqlite3.Row]:
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='applied_events'"
    ).fetchone() is None:
        return []
    return db.execute(
        """SELECT ae.*, c.evidence_text, c.evidence_end, e.source_sha256
           FROM applied_events ae
           JOIN candidates c ON c.candidate_id=ae.candidate_id
           JOIN episodes e ON e.work_id=c.work_id AND e.episode=c.episode
           WHERE ae.work_id=? AND ae.source_episode<=? AND ae.effective_episode<=?
           ORDER BY ae.effective_episode, ae.source_episode,
                    ae.evidence_start, ae.candidate_id""",
        (work_id, episode, episode),
    ).fetchall()


def _cash(ledger: list[sqlite3.Row], subject_id: str, balances: dict) -> dict:
    latest = {}
    for row in ledger:
        if row["event_type"] not in ("cash_opening", "cash_payment", "cash_receipt"):
            continue
        event = json.loads(row["payload_json"])
        if event["actor_id"] == subject_id:
            latest[event["currency"]] = row
    return {
        currency: {"value": value, "unit": currency, **_evidence(latest[currency])}
        for currency, value in balances.items()
        if currency in latest
    }


def _ownership(ledger: list[sqlite3.Row], subject_id: str,
               contracts: dict, holdings: dict) -> dict:
    latest = {}
    for row in ledger:
        if row["event_type"] != "equity_transfer":
            continue
        event = json.loads(row["payload_json"])
        if event["actor_id"] == subject_id:
            company_id = contracts[event["contract_id"]]["company_id"]
            latest[company_id] = row
    result = {}
    for company_id, value in holdings.items():
        if company_id not in latest:
            raise ValueError("ownership value lacks an applied transfer source")
        result[company_id] = {"value": value, "unit": "percent",
                              **_evidence(latest[company_id])}
    return result


def _contracts(ledger: list[sqlite3.Row], subject_id: str, contracts: dict) -> dict:
    latest = {}
    for row in ledger:
        if row["event_type"] not in (
            "contract_proposed", "contract_refused", "contract_signed", "equity_transfer"
        ):
            continue
        event = json.loads(row["payload_json"])
        if event["actor_id"] == subject_id:
            latest[event["contract_id"]] = row
    result = {}
    for key, value in contracts.items():
        if value["actor_id"] != subject_id:
            continue
        if key not in latest:
            raise ValueError("contract status lacks an applied event source")
        result[key] = {**value, **_evidence(latest[key])}
    return result


def _totals(data: dict, ownership: dict) -> dict:
    assets, debts = {}, {}
    unpriced = bool(ownership)
    # Cash is currency-aggregated; an untagged liquid item may refer to it.
    # Omit a potentially duplicated currency total rather than invent a sum.
    cash_currencies = set(data.get("cash", {}))
    ambiguous = {
        entry["unit"]
        for entry in data.get("liquid", {}).values()
        if entry.get("unit") in cash_currencies
        and entry.get("separate_from_cash") is not True
    }
    unpriced = unpriced or bool(ambiguous)
    for category, entries in data.items():
        if category not in (*ASSET_TYPES, "liability", "cash"):
            continue
        for entry in entries.values():
            unit, value = entry.get("unit"), entry["value"]
            if value is None or unit in ("shares", "percent"):
                unpriced = True
                continue
            if unit is None or len(unit) != 3 or not unit.isupper():
                unpriced = True
                continue
            if category != "liability" and unit in ambiguous:
                continue
            bucket = debts if category == "liability" else assets
            bucket[unit] = bucket.get(unit, Decimal(0)) + Decimal(value)
    net = {currency: assets.get(currency, Decimal(0)) + debts.get(currency, Decimal(0))
           for currency in (assets.keys() | debts.keys()) - ambiguous}
    return {
        "valued_assets_by_currency": {k: _number(v) for k, v in sorted(assets.items())},
        "liabilities_by_currency": {k: _number(v) for k, v in sorted(debts.items())},
        "net_valued_by_currency": {k: _number(v) for k, v in sorted(net.items())},
        "has_unpriced_holdings": unpriced,
        "ambiguous_cash_liquid_currencies": sorted(ambiguous),
        "note": "known values only; unmentioned assets are not assumed absent",
    }


def query_state(db: sqlite3.Connection, work_id: str, episode: int,
                subject_id: str, scope: str, *, history: bool = False) -> dict:
    """Retrieve only the explicitly selected subtree; no DB mutations."""
    _id(subject_id, "subject_id")
    if scope not in SCOPES:
        raise ValueError("unsupported query scope")
    snapshot = world_state(db, work_id, episode)  # validates applied/approved ledger
    categories = SCOPES[scope]
    data = {}
    subject_facts = snapshot["facts"].get(subject_id, {})
    for category in categories:
        if subject_facts.get(category):
            data[category] = subject_facts[category]

    ledger = _ledger(db, work_id, episode)
    include_cash = scope in ("cash", "assets", "net_assets", "liquid_assets")
    if include_cash:
        cash = _cash(ledger, subject_id, snapshot["cash"].get(subject_id, {}))
        if cash:
            data["cash"] = cash
    if scope == "time" and snapshot["current_time"] is not None:
        data["time"] = snapshot["current_time"]
    if scope in ("ownership", "stock", "assets", "net_assets"):
        holdings = snapshot["ownership"].get(subject_id, {})
        if holdings:
            data["ownership_pct"] = _ownership(
                ledger, subject_id, snapshot["contracts"], holdings
            )
    if scope == "contracts":
        data["contracts"] = _contracts(ledger, subject_id, snapshot["contracts"])

    result = {
        "work_id": work_id, "as_of_episode": episode,
        "subject_id": subject_id, "scope": scope,
        "current_time": (snapshot["current_time"] or {}).get("value"),
        "data": data,
    }
    if scope in ("assets", "net_assets"):
        result["totals"] = _totals(data, snapshot["ownership"].get(subject_id, {}))
    if history:
        selected = []
        for row in ledger:
            event = json.loads(row["payload_json"])
            if row["event_type"] == "state_set":
                if event["category"] == "time":
                    matched = scope == "time" and event["actor_id"] == work_id
                else:
                    matched = (event["actor_id"] == subject_id
                               and event["category"] in categories)
                if matched:
                    selected.append({
                        "category": event["category"], "item_id": event["item_id"],
                        "value": event["value"], **_evidence(row),
                    })
            elif (include_cash and row["event_type"].startswith("cash_")
                  and event["actor_id"] == subject_id):
                signed = (-Decimal(event["amount"])
                          if row["event_type"] == "cash_payment"
                          else Decimal(event["amount"]))
                selected.append({
                    "event_type": row["event_type"],
                    "category": "cash", "item_id": event["currency"],
                    "value": _number(signed), **_evidence(row),
                })
        result["history"] = selected
    return result
