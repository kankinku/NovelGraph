"""Read-only identity ambiguity audit for staged or approved entity candidates.

No implicit identity merge. Names and manuscript quotes stay in the private DB.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import sqlite3

from .graphify_bridge import ENTITY_TYPES, _text
from .world_state import _id


def audit_identities(db: sqlite3.Connection, work_id: str, episode: int) -> dict:
    db.row_factory = sqlite3.Row
    rows = db.execute(
        """SELECT c.*, e.source_sha256 FROM candidates c
           JOIN episodes e ON e.work_id=c.work_id AND e.episode=c.episode
           WHERE c.work_id=? AND c.episode<=? AND c.kind='entity'
             AND c.status IN ('proposed','approved')
           ORDER BY c.episode,c.evidence_start,c.candidate_id""",
        (work_id, episode),
    ).fetchall()
    by_id = defaultdict(list)
    by_name = defaultdict(list)
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
            encoded = json.dumps(
                [row["work_id"], row["episode"], row["source_sha256"],
                 row["kind"], payload, row["evidence_start"], row["evidence_end"],
                 row["evidence_text"]],
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("stored identity candidate contains invalid data") from exc
        if hashlib.sha256(encoded).hexdigest() != row["candidate_id"]:
            raise ValueError("stored identity candidate integrity hash mismatch")
        if not isinstance(payload, dict) or set(payload) != {
            "entity_id", "entity_type", "name"
        }:
            raise ValueError("entity candidate has invalid identity schema")
        ident = _id(payload["entity_id"], "entity_id")
        entity_type = payload["entity_type"]
        if not isinstance(entity_type, str) or entity_type not in ENTITY_TYPES:
            raise ValueError("entity candidate has unsupported entity_type")
        name = _text(payload["name"], "name")
        # The reader can locate evidence by episode/SHA/span; text is never printed.
        if (type(row["evidence_start"]) is not int
                or type(row["evidence_end"]) is not int
                or row["evidence_start"] < 0
                or row["evidence_end"] - row["evidence_start"]
                    != len(row["evidence_text"])):
            raise ValueError("entity evidence span is inconsistent")
        record = {
            "entity_id": ident, "entity_type": entity_type, "name": name,
            "candidate_id": row["candidate_id"], "status": row["status"],
            "episode": row["episode"], "source_sha256": row["source_sha256"],
            "start": row["evidence_start"], "end": row["evidence_end"],
        }
        by_id[ident].append(record)
        by_name[(entity_type, name)].append(record)

    findings = []

    def add(reason: str, members: list[dict]):
        unique = sorted(members, key=lambda x: (x["episode"], x["start"], x["candidate_id"]))
        findings.append({
            "reason_code": reason,
            "entity_ids": sorted({r["entity_id"] for r in unique}),
            "evidence": [{
                "candidate_id": r["candidate_id"], "episode": r["episode"],
                "source_sha256": r["source_sha256"],
                "start": r["start"], "end": r["end"],
                "status": r["status"],
            } for r in unique],
        })

    for entries in by_id.values():
        types = {r["entity_type"] for r in entries}
        names = {r["name"] for r in entries}
        if len(types) > 1:
            add("same_id_incompatible_types", entries)
        elif len(names) > 1:
            add("same_id_multiple_names", entries)
    for entries in by_name.values():
        if len({r["entity_id"] for r in entries}) > 1:
            add("same_name_distinct_ids", entries)
    findings.sort(key=lambda x: (x["reason_code"], x["entity_ids"]))

    return {
        "work_id": work_id, "as_of_episode": episode,
        "candidate_entities_checked": len(rows), "issues": findings,
        "needs_human_review": bool(findings),
        "auto_merged": False, "semantic_identity_verified": False,
        "source_quotes_included": False, "world_state_mutations": 0,
    }
