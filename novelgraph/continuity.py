"""Evidence-linked, conservative continuity checks over approved assertions.

The caller/LLM supplies normalized claims. This module does not infer that two
different names or events refer to the same thing. It does not change world state.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
import json
import sqlite3

from .world_state import _assert_approved_review, _id, _decimal, _replay

FACT_FIELDS = {
    "time": {"date", "weekday"},
    "location": {"location_id"},
    "action": {"action_state"},
    "amount": {"amount"},
    "contract": {"current_status"},
}
ALL_FIELDS = set().union(*FACT_FIELDS.values())
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday")
ACTION_STATES = {"planned", "started", "completed", "reopened", "cancelled"}
CONTRACT_STATES = {
    "pending", "proposed", "refused", "signed", "transferred",
    "cancelled", "expired",
}
REASONS = {"amended", "rescheduled", "moved", "corrected", "reopened",
           "repeated", "refinanced", "revalued"}
STATUSES = ("CONFIRMED_CONFLICT", "NEEDS_REVIEW",
            "EXPLAINED_CHANGE", "INSUFFICIENT_EVIDENCE")


def _reject(message: str):
    raise ValueError(message)


def _normalized_value(field: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        _reject("continuity assertion values must be nonempty strings")
    if field == "amount":
        return format(_decimal(value, "amount", can_be_zero=True).normalize(), "f")
    if field == "date":
        try:
            result = date.fromisoformat(value)
        except ValueError:
            _reject("date must be a valid ISO YYYY-MM-DD calendar date")
        if result.isoformat() != value:
            _reject("date must be canonical YYYY-MM-DD")
        return value
    if field == "weekday":
        if value not in WEEKDAYS:
            _reject("weekday must be a lowercase English weekday")
        return value
    if field == "location_id":
        return _id(value, "location_id")
    if field == "action_state":
        if value not in ACTION_STATES:
            _reject("unsupported action_state")
        return value
    if field == "current_status":
        if value not in CONTRACT_STATES:
            _reject("unsupported contract current_status")
        return value
    _reject("unsupported continuity fact field")


def validate_fact(row: sqlite3.Row) -> dict:
    """Validate schema and normalize one approved or to-be-approved candidate."""
    try:
        item = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        _reject("continuity payload is not valid JSON")
    if not isinstance(item, dict):
        _reject("continuity payload must be a JSON object")
    kind = item.get("fact_type")
    if not isinstance(kind, str) or (kind not in FACT_FIELDS and kind != "change"):
        _reject("invalid fact_type")
    subject = _id(item.get("subject_id"), "subject_id")
    field = item.get("field")
    if not isinstance(field, str) or field not in (
        ALL_FIELDS if kind == "change" else FACT_FIELDS[kind]
    ):
        _reject("field incompatible with fact_type")
    effective = item.get("effective_episode", row["episode"])
    if type(effective) is not int or not (1 <= effective <= row["episode"]):
        _reject("effective_episode must be between 1 and source episode")
    currency = item.get("currency")
    if field == "amount":
        if (not isinstance(currency, str) or len(currency) != 3
                or not currency.isascii() or not currency.isalpha()
                or currency.upper() != currency):
            _reject("amount assertions require three-letter currency")
    elif "currency" in item:
        _reject("currency only applies to amount assertions")
    certainty = item.get("certainty", "confirmed")
    if certainty not in ("confirmed", "uncertain"):
        _reject("certainty must be confirmed or uncertain")
    context_id = item.get("context_id")
    if context_id is not None:
        _id(context_id, "context_id")
    expected = {
        "fact_type", "subject_id", "field", "effective_episode",
        "currency", "certainty", "context_id"
    }
    normalized = {
        "fact_type": kind, "subject_id": subject, "field": field,
        "currency": currency, "certainty": certainty, "context_id": context_id,
        "effective_episode": effective, "source_episode": row["episode"],
        "candidate_id": row["candidate_id"],
        "evidence_start": row["evidence_start"], "evidence_end": row["evidence_end"],
        "source_sha256": row["source_sha256"],
    }
    if kind == "change":
        expected |= {"from_value", "to_value", "reason_code"}
        reason = item.get("reason_code")
        if reason not in REASONS:
            _reject("unsupported reason_code for explicit change")
        before = _normalized_value(field, item.get("from_value"))
        after = _normalized_value(field, item.get("to_value"))
        if before == after and reason != "repeated":
            _reject("unchanged values do not prove a transition")
        normalized.update(from_value=before, to_value=after, reason_code=reason)
    else:
        expected.add("value")
        normalized["value"] = _normalized_value(field, item.get("value"))
    if set(item) - expected:
        _reject("unsupported keys in continuity payload")
    return normalized


def _evidence(item: dict) -> dict:
    return {
        "candidate_id": item["candidate_id"],
        "episode": item["source_episode"],
        "effective_episode": item["effective_episode"],
        "start": item["evidence_start"], "end": item["evidence_end"],
        "source_sha256": item["source_sha256"],
    }


def _finding(category, reason_code, subject, field, evidence, **details):
    candidates = sorted({item["candidate_id"] for item in evidence})
    digest = hashlib.sha256(
        json.dumps([category, reason_code, subject, field, candidates],
                   separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "finding_id": digest, "category": category, "reason_code": reason_code,
        "subject_id": subject, "field": field,
        "evidence": [_evidence(item) for item in evidence],
        **details,
    }


def _matching_change(changes: list[dict], before: dict, after: dict):
    for item in changes:
        if (item["certainty"] == "confirmed"
                and item["subject_id"] == before["subject_id"]
                and item["field"] == before["field"]
                and item["currency"] == before["currency"]
                and item["from_value"] == before["value"]
                and item["to_value"] == after["value"]
                and before["effective_episode"] < item["effective_episode"]
                <= after["effective_episode"]):
            return item
    return None


def _contract_evidence(db: sqlite3.Connection, work: str, contract_id: str,
                       effective_episode: int, known_at_episode: int):
    rows = db.execute(
        """SELECT ae.candidate_id, ae.source_episode, ae.effective_episode,
                  ae.evidence_start, c.evidence_end, e.source_sha256,
                  ae.payload_json
           FROM applied_events ae
           JOIN candidates c ON c.candidate_id=ae.candidate_id
           JOIN episodes e ON e.work_id=c.work_id AND e.episode=c.episode
           WHERE ae.work_id=? AND ae.source_episode<=?
             AND ae.effective_episode<=?
             AND ae.event_type IN (
                 'contract_proposed','contract_refused',
                 'contract_signed','equity_transfer'
             )
           ORDER BY ae.source_episode DESC,ae.evidence_start DESC""",
        (work, known_at_episode, effective_episode),
    ).fetchall()
    for row in rows:
        payload = json.loads(row["payload_json"])
        if payload.get("contract_id") == contract_id:
            return {
                "candidate_id": row["candidate_id"],
                "source_episode": row["source_episode"],
                "effective_episode": row["effective_episode"],
                "evidence_start": row["evidence_start"],
                "evidence_end": row["evidence_end"],
                "source_sha256": row["source_sha256"],
            }
    return None


def check_continuity(db: sqlite3.Connection, work: str, as_of_episode: int) -> dict:
    """Compare only approved, source-grounded facts known by this episode."""
    _id(work, "work_id")
    if type(as_of_episode) is not int or as_of_episode < 1:
        _reject("as_of_episode must be a positive integer")
    db.row_factory = sqlite3.Row
    rows = db.execute(
        """SELECT c.*, e.source_sha256
           FROM candidates c
           JOIN episodes e ON e.work_id=c.work_id AND e.episode=c.episode
           WHERE c.work_id=? AND c.episode<=?
             AND c.kind='continuity_fact' AND c.status='approved'
           ORDER BY c.episode,c.evidence_start,c.candidate_id""",
        (work, as_of_episode),
    ).fetchall()
    for row in rows:
        _assert_approved_review(db, row["candidate_id"])
    parsed = [validate_fact(row) for row in rows]
    parsed = [item for item in parsed if item["effective_episode"] <= as_of_episode]
    assertions = [item for item in parsed if item["fact_type"] != "change"]
    changes = [item for item in parsed if item["fact_type"] == "change"]
    groups: dict[tuple, list[dict]] = {}
    for item in assertions:
        key = (item["subject_id"], item["field"], item["currency"])
        groups.setdefault(key, []).append(item)
    findings: list[dict] = []
    used_changes: set[str] = set()

    for (subject, field, currency), group in sorted(groups.items(),
                                                      key=lambda entry: repr(entry[0])):
        group.sort(key=lambda r: (r["effective_episode"], r["source_episode"],
                                  r["evidence_start"], r["candidate_id"]))
        for prior, current in zip(group, group[1:]):
            if prior["value"] == current["value"]:
                if (field == "action_state" and current["value"] == "completed"
                        and prior["effective_episode"] < current["effective_episode"]):
                    change = _matching_change(changes, prior, current)
                    if change and change["reason_code"] == "repeated":
                        used_changes.add(change["candidate_id"])
                        findings.append(_finding(
                            "EXPLAINED_CHANGE", "EXPLICIT_ACTION_REPEAT",
                            subject, field, [prior, current, change],
                            value=current["value"]))
                    else:
                        findings.append(_finding(
                            "NEEDS_REVIEW", "REPEATED_COMPLETED_ACTION",
                            subject, field, [prior, current],
                            value=current["value"]))
                continue

            if "uncertain" in (prior["certainty"], current["certainty"]):
                category, reason = "INSUFFICIENT_EVIDENCE", "UNCERTAIN_ASSERTION"
                evidence = [prior, current]
            elif (
                prior["effective_episode"] == current["effective_episode"]
                and (
                    # A time fact's subject_id must identify one specific event.
                    field in {"date", "weekday"}
                    or (
                        prior["context_id"] is not None
                        and prior["context_id"] == current["context_id"]
                    )
                )
            ):
                category, reason = "CONFIRMED_CONFLICT", "SAME_MOMENT_CONTRADICTION"
                evidence = [prior, current]
            else:
                change = _matching_change(changes, prior, current)
                if change:
                    category, reason = "EXPLAINED_CHANGE", "APPROVED_STATE_CHANGE"
                    evidence = [prior, current, change]
                    used_changes.add(change["candidate_id"])
                else:
                    category, reason = "NEEDS_REVIEW", "UNEXPLAINED_STATE_CHANGE"
                    evidence = [prior, current]
            findings.append(_finding(
                category, reason, subject, field, evidence,
                previous_value=prior["value"], current_value=current["value"],
                **({"currency": currency} if currency else {})
            ))

    # Gregorian calendar cross-check: the day named for a dated event must agree.
    times: dict[tuple, dict[str, list[dict]]] = {}
    for item in assertions:
        if item["fact_type"] == "time":
            key = (item["subject_id"], item["effective_episode"])
            times.setdefault(key, {}).setdefault(item["field"], []).append(item)
    for (subject, moment), fields in sorted(times.items()):
        for day in fields.get("date", []):
            for name in fields.get("weekday", []):
                expected = WEEKDAYS[date.fromisoformat(day["value"]).weekday()]
                if name["value"] != expected:
                    uncertain = "uncertain" in (day["certainty"], name["certainty"])
                    findings.append(_finding(
                        "INSUFFICIENT_EVIDENCE" if uncertain else "CONFIRMED_CONFLICT",
                        "DATE_WEEKDAY_MISMATCH" if not uncertain else "UNCERTAIN_CALENDAR_FACT",
                        subject, "date_weekday", [day, name],
                        date=day["value"], asserted_weekday=name["value"],
                        calendar_weekday=expected
                    ))

    for change in changes:
        if change["candidate_id"] not in used_changes:
            findings.append(_finding(
                "INSUFFICIENT_EVIDENCE", "UNMATCHED_CHANGE_EVENT",
                change["subject_id"], change["field"], [change],
                from_value=change["from_value"], to_value=change["to_value"]
            ))

    # Compare explicit 'current_status' assertions with the approved event ledger,
    # using only events that were already known at the assertion's source episode.
    ledger_exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='applied_events'"
    ).fetchone()
    if ledger_exists:
        for fact in assertions:
            if fact["fact_type"] != "contract" or fact["certainty"] != "confirmed":
                continue
            # Compare the historical moment described by the assertion, not
            # a later transfer that happened after that moment.
            known_state = _replay(db, work, fact["effective_episode"],
                                  known_at_episode=fact["source_episode"])
            contract = known_state["contracts"].get(fact["subject_id"])
            if contract is None or contract["status"] == fact["value"]:
                continue
            proof = _contract_evidence(db, work, fact["subject_id"],
                                       fact["effective_episode"], fact["source_episode"])
            if proof:
                findings.append(_finding(
                    "CONFIRMED_CONFLICT", "CONTRACT_LEDGER_STATUS_MISMATCH",
                    fact["subject_id"], "current_status", [fact, proof],
                    asserted_status=fact["value"], ledger_status=contract["status"]
                ))

    findings.sort(key=lambda item: (item["subject_id"], item["field"],
                                    item["reason_code"], item["finding_id"]))
    counts = {status: 0 for status in STATUSES}
    for finding in findings:
        counts[finding["category"]] += 1
    return {
        "work_id": work, "as_of_episode": as_of_episode,
        "reviewed_facts": len(assertions), "reviewed_change_events": len(changes),
        "counts": counts, "findings": findings,
        "source_quotes_included": False,
        "is_complete_novel_analysis": False,
    }
