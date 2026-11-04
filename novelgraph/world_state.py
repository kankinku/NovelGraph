"""Approved, evidence-linked story events and point-in-time world state.

Only explicitly reviewed 'state_change' candidates can be applied.
An applied event is an immutable fact; the visible state is always replayed.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re
import sqlite3

IDENT = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
MONEY = re.compile(r"^(0|[1-9][0-9]{0,14})(\\.[0-9]{1,4})?$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
EVENT_TYPES = {
    "cash_opening", "contract_signed", "cash_payment", "cash_receipt", "equity_transfer"
}


def _fail(message: str):
    raise ValueError(message)


def _id(value, label):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        _fail(f"{label} must be a stable 1-100 character identifier")
    return value


def _decimal(value, label, *, can_be_zero=False):
    if not isinstance(value, str) or not MONEY.fullmatch(value):
        _fail(f"{label} must be a nonnegative decimal string (max 4 fractional digits)")
    try:
        result = Decimal(value)
    except InvalidOperation:
        _fail(f"invalid {label}")
    if result < 0 or (not can_be_zero and result == 0):
        _fail(f"{label} must be positive")
    return result


def _number(value):
    return format(value, "f")


def _payload(row):
    try:
        value = json.loads(row["payload_json"])
    except (ValueError, TypeError):
        _fail("stored event payload is invalid")
    if not isinstance(value, dict):
        _fail("event payload must be a JSON object")
    source_episode = row["episode"]
    effective_episode = value.get("effective_episode", source_episode)
    if type(effective_episode) is not int or not (1 <= effective_episode <= source_episode):
        _fail("effective_episode must be an integer from 1 to the source episode")
    event_type = value.get("event_type")
    if event_type not in EVENT_TYPES:
        _fail("unsupported event_type; use an explicit state-change event")
    actor = _id(value.get("actor_id"), "actor_id")
    allowed = {
        "cash_opening": {"event_type", "actor_id", "currency", "amount", "effective_episode"},
        "cash_payment": {"event_type", "actor_id", "currency", "amount",
                         "transaction_id", "contract_id", "effective_episode"},
        "cash_receipt": {"event_type", "actor_id", "currency", "amount",
                         "transaction_id", "contract_id", "effective_episode"},
        "contract_signed": {"event_type", "actor_id", "contract_id", "company_id",
                            "equity_pct", "effective_episode"},
        "equity_transfer": {"event_type", "actor_id", "contract_id", "effective_episode"},
    }[event_type]
    if set(value) - allowed:
        _fail(f"unexpected fields for {event_type}")
    value = {**value, "effective_episode": effective_episode}
    if event_type.startswith("cash_"):
        currency = value.get("currency")
        if not isinstance(currency, str) or not CURRENCY.fullmatch(currency):
            _fail("currency must be a three-letter uppercase ISO currency code")
        value["amount"] = _number(_decimal(value.get("amount"), "amount",
                                  can_be_zero=event_type == "cash_opening"))
    if event_type in ("cash_payment", "cash_receipt"):
        transaction = _id(value.get("transaction_id"), "transaction_id")
        if "contract_id" in value:
            _id(value["contract_id"], "contract_id")
        key = f"cash:{transaction}"
    elif event_type == "cash_opening":
        key = f"balance:{actor}:{value['currency']}"
    elif event_type == "contract_signed":
        contract = _id(value.get("contract_id"), "contract_id")
        _id(value.get("company_id"), "company_id")
        pct = _decimal(value.get("equity_pct"), "equity_pct")
        if pct > 100:
            _fail("equity_pct must be <= 100")
        value["equity_pct"] = _number(pct)
        key = f"contract:{contract}"
    else:
        contract = _id(value.get("contract_id"), "contract_id")
        key = f"transfer:{contract}"
    return event_type, key, json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ), effective_episode


def _init_tables(db: sqlite3.Connection):
    db.execute("""CREATE TABLE IF NOT EXISTS review_log (
        review_id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
        decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
        reviewer TEXT NOT NULL, reason TEXT NOT NULL,
        reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS applied_events (
        candidate_id TEXT PRIMARY KEY REFERENCES candidates(candidate_id),
        work_id TEXT NOT NULL, source_episode INTEGER NOT NULL,
        effective_episode INTEGER NOT NULL, evidence_start INTEGER NOT NULL,
        event_type TEXT NOT NULL, event_key TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(work_id, event_key)
    )""")


def _candidate(db, candidate_id, sha, text):
    _id(candidate_id, "candidate_id")
    db.row_factory = sqlite3.Row
    row = db.execute("""SELECT c.*, e.source_sha256
        FROM candidates c JOIN episodes e
          ON c.work_id=e.work_id AND c.episode=e.episode
        WHERE c.candidate_id=?""", (candidate_id,)).fetchone()
    if row is None:
        _fail("candidate not found")
    if row["source_sha256"] != sha:
        _fail("source hash differs from registered candidate episode")
    start, end, quote = row["evidence_start"], row["evidence_end"], row["evidence_text"]
    if not (0 <= start < end <= len(text)) or text[start:end] != quote:
        _fail("candidate evidence is no longer valid against source")
    return row


def review_candidate(db, candidate_id, sha, text, decision, reviewer, reason):
    if decision not in ("approve", "reject"):
        _fail("decision must be approve or reject")
    reviewer = _id(reviewer, "reviewer")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        _fail("review reason must be nonempty and at most 1000 characters")
    db.execute("PRAGMA foreign_keys=ON")
    with db:
        row = _candidate(db, candidate_id, sha, text)
        if row["status"] != "proposed":
            _fail("candidate has already been reviewed; reviews are immutable")
        if decision == "approve" and row["kind"] == "state_change":
            _payload(row)
        _init_tables(db)
        state = "approved" if decision == "approve" else "rejected"
        db.execute("UPDATE candidates SET status=? WHERE candidate_id=?",
                   (state, candidate_id))
        db.execute("INSERT INTO review_log(candidate_id,decision,reviewer,reason) "
                   "VALUES(?,?,?,?)", (candidate_id, state, reviewer, reason.strip()))
    return {"candidate_id": candidate_id, "decision": state,
            "applied": False, "reviewer_label_is_not_authentication": True}


def _replay(db, work_id, as_of_episode):
    state = {"work_id": work_id, "as_of_episode": as_of_episode,
             "cash": {}, "cash_movement": {}, "contracts": {},
             "ownership": {}, "total_assets": None, "event_count": 0}
    db.row_factory = sqlite3.Row
    rows = db.execute("""SELECT * FROM applied_events
        WHERE work_id=? AND source_episode<=? AND effective_episode<=?
        ORDER BY effective_episode, source_episode, evidence_start, candidate_id""",
        (work_id, as_of_episode, as_of_episode)
    ).fetchall()
    movement_started = set()
    for row in rows:
        event = json.loads(row["payload_json"])
        kind = row["event_type"]
        actor = event["actor_id"]
        if kind == "contract_signed":
            contract = event["contract_id"]
            if contract in state["contracts"]:
                _fail("contract has already been signed")
            state["contracts"][contract] = {
                "actor_id": actor, "company_id": event["company_id"],
                "equity_pct": event["equity_pct"], "status": "signed"
            }
        elif kind == "equity_transfer":
            contract = state["contracts"].get(event["contract_id"])
            if not contract or contract["actor_id"] != actor:
                _fail("equity transfer requires matching signed contract")
            if contract["status"] != "signed":
                _fail("equity was already transferred for this contract")
            company = contract["company_id"]
            ownership = state["ownership"].setdefault(actor, {})
            current = Decimal(ownership.get(company, "0"))
            pct = current + Decimal(contract["equity_pct"])
            if pct > 100:
                _fail("equity holdings exceed 100 percent")
            ownership[company] = _number(pct)
            contract["status"] = "transferred"
        else:
            currency = event["currency"]
            amount = Decimal(event["amount"])
            cash = state["cash"].setdefault(actor, {})
            movements = state["cash_movement"].setdefault(actor, {})
            if kind == "cash_opening":
                if currency in cash or (actor, currency) in movement_started:
                    _fail("cash opening balance must precede all movements for this account")
                cash[currency] = _number(amount)
                movements.setdefault(currency, "0")
            else:
                if event.get("contract_id"):
                    contract = state["contracts"].get(event["contract_id"])
                    if not contract or contract["actor_id"] != actor:
                        _fail("cash transaction refers to an unsigned or foreign contract")
                movement_started.add((actor, currency))
                change = -amount if kind == "cash_payment" else amount
                movements[currency] = _number(
                    Decimal(movements.get(currency, "0")) + change
                )
                if currency not in cash:
                    cash[currency] = None  # unknown baseline; never fabricate a balance
                else:
                    balance = Decimal(cash[currency]) + change
                    if balance < 0:
                        _fail("known cash balance cannot become negative")
                    cash[currency] = _number(balance)
        state["event_count"] += 1
    return state


def approve_and_apply(db, candidate_id, sha, text):
    """Apply a previously approved event, atomically including a full replay."""
    db.execute("PRAGMA foreign_keys=ON")
    with db:
        row = _candidate(db, candidate_id, sha, text)
        if row["kind"] != "state_change":
            _fail("only state_change candidates can be applied")
        if row["status"] != "approved":
            _fail("candidate must have an explicit approval before applying")
        _init_tables(db)
        existing = db.execute(
            "SELECT 1 FROM applied_events WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        if existing:
            return {"candidate_id": candidate_id, "already_applied": True,
                    "new_world_state_mutations": 0}
        event_type, event_key, payload_json, effective = _payload(row)
        collision = db.execute(
            "SELECT candidate_id FROM applied_events WHERE work_id=? AND event_key=?",
            (row["work_id"], event_key)
        ).fetchone()
        if collision:
            _fail("economic event key already used by a different candidate")
        db.execute("""INSERT INTO applied_events
            (candidate_id, work_id, source_episode, effective_episode,
             evidence_start, event_type, event_key, payload_json)
            VALUES(?,?,?,?,?,?,?,?)""",
            (candidate_id, row["work_id"], row["episode"], effective,
             row["evidence_start"], event_type, event_key, payload_json)
        )
        # Fail and rollback rather than persist a ledger with invalid replay.
        max_episode = db.execute(
            "SELECT MAX(source_episode) FROM applied_events WHERE work_id=?",
            (row["work_id"],)
        ).fetchone()[0]
        _replay(db, row["work_id"], max_episode)
    return {"candidate_id": candidate_id, "already_applied": False,
            "new_world_state_mutations": 1, "event_type": event_type}


def world_state(db, work_id, as_of_episode):
    _id(work_id, "work_id")
    if type(as_of_episode) is not int or as_of_episode < 1:
        _fail("as_of_episode must be a positive integer")
    _init_tables(db)
    return _replay(db, work_id, as_of_episode)
