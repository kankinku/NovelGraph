"""Atomic, provenance-linked replacement of unapproved candidates.

Original candidate rows and model assessments remain immutable.  The lineage
relationship blocks later official review of a superseded candidate; it never
grants approval to the replacement or changes a world-state ledger.
"""
from __future__ import annotations

from pathlib import Path
import re

from .__main__ import (
    DB_NAME, _check_episode, _check_work_id, _connect, _read_json,
    _source, _valid_candidates, preflight_candidates,
)
from .world_state import _candidate

_HASH = re.compile(r"^[0-9a-f]{64}$")


def _mapping(document: dict, work: str, episode: int, new_ids: set[str]) -> list[tuple[str, str]]:
    if (set(document) != {"schema_version", "work_id", "episode", "revisions"}
            or type(document["schema_version"]) is not int
            or document["schema_version"] != 1
            or _check_work_id(document["work_id"]) != work
            or _check_episode(document["episode"]) != episode):
        raise ValueError("revision mapping work, episode or schema mismatch")
    records = document["revisions"]
    if not isinstance(records, list) or len(records) != len(new_ids):
        raise ValueError("revision mapping must be one-to-one with new candidates")
    pairs = []
    for item in records:
        if (not isinstance(item, dict) or
                set(item) != {"replaces_candidate_id", "new_candidate_id"}):
            raise ValueError("revision mapping entries require one-to-one old/new candidate IDs")
        old, new = item["replaces_candidate_id"], item["new_candidate_id"]
        if (not isinstance(old, str) or not _HASH.fullmatch(old)
                or not isinstance(new, str) or not _HASH.fullmatch(new)
                or old == new):
            raise ValueError("revision mapping must contain distinct SHA-256 candidate IDs")
        pairs.append((old, new))
    if (len({old for old, _ in pairs}) != len(pairs)
            or len({new for _, new in pairs}) != len(pairs)
            or {new for _, new in pairs} != new_ids):
        raise ValueError("revision mapping must be a one-to-one cover of the supplied candidates")
    return pairs


def import_revisions(root: Path, source: Path, input_file: Path, mapping_file: Path) -> dict:
    """Stage new proposed claims with immutable original→replacement lineage."""
    text, digest, _ = _source(source)
    document = _read_json(input_file)
    work, episode, records = _valid_candidates(document, text, digest)
    if not records:
        raise ValueError("revision batch must contain one or more candidates")
    # Validate every proposed payload, including exact cash and qualified facts,
    # before opening a writable SQLite connection.
    preflight = preflight_candidates(root, source, input_file)
    if preflight["duplicate_candidate_entries"]:
        raise ValueError("revision batch contains duplicate candidate entries")
    mappings = _mapping(
        _read_json(mapping_file), work, episode, {row[0] for row in records}
    )
    by_new = {row[0]: row for row in records}
    db_path = root / DB_NAME
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("existing candidate database is required for revisions")
    db = _connect(db_path)
    try:
        # Explicit BEGIN: even the initial CREATE TABLE is rolled back when a
        # later member of a batch fails. No partial supersession is possible.
        db.execute("BEGIN IMMEDIATE")
        with db:
            registered = db.execute(
                "SELECT source_sha256 FROM episodes WHERE work_id=? AND episode=?",
                (work, episode),
            ).fetchone()
            if not registered or registered[0] != digest:
                raise ValueError("revision source must match registered episode SHA")
            db.execute("""CREATE TABLE IF NOT EXISTS candidate_revisions (
                old_candidate_id TEXT PRIMARY KEY REFERENCES candidates(candidate_id),
                new_candidate_id TEXT NOT NULL UNIQUE REFERENCES candidates(candidate_id),
                revised_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            inserted = 0
            already = 0
            for old_id, new_id in mappings:
                old = _candidate(db, old_id, digest, text)
                if old["work_id"] != work or old["episode"] != episode:
                    raise ValueError("revision requires original candidate in same work and episode")
                prior = db.execute(
                    "SELECT new_candidate_id FROM candidate_revisions WHERE old_candidate_id=?",
                    (old_id,),
                ).fetchone()
                if prior:
                    if prior[0] != new_id:
                        raise ValueError("candidate already superseded by a different revision")
                    new = _candidate(db, new_id, digest, text)
                    if new["work_id"] != work or new["episode"] != episode:
                        raise ValueError("prior revision has a mismatched work or episode")
                    already += 1
                    continue
                if old["status"] != "proposed":
                    raise ValueError("only original proposed candidates may be revised")
                if db.execute(
                    "SELECT 1 FROM candidates WHERE candidate_id=?", (new_id,)
                ).fetchone():
                    raise ValueError("new revision candidate already exists without this lineage")
                db.execute(
                    "INSERT INTO candidates(candidate_id,work_id,episode,kind,"
                    "payload_json,evidence_start,evidence_end,evidence_text)"
                    "VALUES(?,?,?,?,?,?,?,?)", by_new[new_id]
                )
                db.execute(
                    "INSERT INTO candidate_revisions(old_candidate_id,new_candidate_id)"
                    " VALUES(?,?)", (old_id, new_id)
                )
                inserted += 1
        return {
            "work_id": work, "episode": episode, "submitted": len(mappings),
            "inserted": inserted, "supersessions_recorded": inserted,
            "already_recorded": already, "status": "proposed",
            "officially_reviewed": False, "world_state_mutations": 0,
            "original_candidates_preserved": True, "source_quotes_included": False,
        }
    finally:
        db.close()
