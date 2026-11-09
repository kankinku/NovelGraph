"""Read-only structural draft conflicts against the last approved world state.

A non-conflicting draft still needs semantic review; this is not an approval API.
"""
from __future__ import annotations

from decimal import Decimal
import json
import sqlite3

from .continuity import validate_fact
from .world_state import _payload, world_state


def check_draft(db: sqlite3.Connection, work_id: str, episode: int,
                records: list[tuple], as_of_episode: int) -> dict:
    """Return blocking draft findings without registering or applying candidates."""
    if episode != as_of_episode + 1:
        raise ValueError("draft must be the next episode after as-of-episode")
    baseline = world_state(db, work_id, as_of_episode)
    cash = {
        actor: {currency: Decimal(value) if value is not None else None
                for currency, value in balances.items()}
        for actor, balances in baseline["cash"].items()
    }
    current_time = (baseline["current_time"] or {}).get("value")
    contracts = {key: value.copy() for key, value in baseline["contracts"].items()}
    findings = []

    for record in sorted(records, key=lambda item: (item[5], item[0])):
        candidate_id, _, _, kind, payload_json, *_ = record
        if kind == "continuity_fact":
            validate_fact({
                "payload_json": payload_json, "episode": episode,
                "candidate_id": candidate_id,
                "evidence_start": record[5], "evidence_end": record[6],
                "source_sha256": "",
            })
            continue
        if kind != "state_change":
            continue
        event_type, _, normalized, _ = _payload({
            "payload_json": payload_json, "episode": episode, "work_id": work_id,
            "candidate_id": candidate_id,
        })
        event = json.loads(normalized)
        actor = event["actor_id"]
        if event_type == "state_set":
            if event["category"] == "time":
                new_time = event["value"]
                if current_time is not None and new_time < current_time:
                    findings.append({"candidate_id": candidate_id,
                                     "reason_code": "time_backwards"})
                else:
                    current_time = new_time
            continue
        if event_type == "contract_proposed":
            contract_id = event["contract_id"]
            if contract_id in contracts:
                findings.append({"candidate_id": candidate_id,
                                 "reason_code": "contract_already_exists"})
            else:
                contracts[contract_id] = {
                    "status": "proposed", "actor_id": actor,
                    "company_id": event["company_id"],
                }
            continue
        if event_type == "contract_refused":
            contract = contracts.get(event["contract_id"])
            if not contract or contract["status"] != "proposed" or contract["actor_id"] != actor:
                findings.append({"candidate_id": candidate_id,
                                 "reason_code": "invalid_contract_refusal"})
            else:
                contract["status"] = "refused"
            continue
        if event_type == "contract_signed":
            contract_id = event["contract_id"]
            contract = contracts.get(contract_id)
            if contract and (
                contract["status"] != "proposed" or contract["actor_id"] != actor
                or contract["company_id"] != event["company_id"]
            ):
                findings.append({"candidate_id": candidate_id,
                                 "reason_code": "contract_already_finalized"})
            else:
                contracts[contract_id] = {
                    "status": "signed", "actor_id": actor,
                    "company_id": event["company_id"],
                }
            continue
        if event_type == "equity_transfer":
            contract = contracts.get(event["contract_id"])
            if not contract or contract["status"] != "signed" or contract["actor_id"] != actor:
                findings.append({"candidate_id": candidate_id,
                                 "reason_code": "equity_transfer_without_signed_contract"})
            else:
                contract["status"] = "transferred"
            continue
        if event_type not in ("cash_opening", "cash_receipt", "cash_payment"):
            continue
        if event.get("contract_id"):
            contract = contracts.get(event["contract_id"])
            if not contract or contract["actor_id"] != actor or contract["status"] not in (
                "signed", "transferred"
            ):
                findings.append({"candidate_id": candidate_id,
                                 "reason_code": "cash_transaction_without_signed_contract"})
        currency = event["currency"]
        balances = cash.setdefault(actor, {})
        if event_type == "cash_opening":
            if currency in balances:
                findings.append({"candidate_id": candidate_id,
                                 "reason_code": "duplicate_cash_opening"})
            else:
                balances[currency] = Decimal(event["amount"])
            continue
        if currency not in balances or balances[currency] is None:
            # Unknown opening balance cannot prove overdraft; human review remains required.
            continue
        amount = Decimal(event["amount"])
        if event_type == "cash_receipt":
            balances[currency] += amount
        elif amount > balances[currency]:
            findings.append({"candidate_id": candidate_id,
                             "reason_code": "known_cash_overdraft"})
        else:
            balances[currency] -= amount

    return {
        "work_id": work_id, "as_of_episode": as_of_episode,
        "draft_episode": episode,
        "status": "REJECTED" if findings else "NEEDS_REVIEW",
        "blocking": True,
        "findings": findings,
        "requesting_ai_review_required": bool(findings),
        "user_final_decision_required": bool(findings),
        "official_world_state_mutations": 0,
        "source_text_included": False,
        "semantic_accuracy_measured": False,
    }
