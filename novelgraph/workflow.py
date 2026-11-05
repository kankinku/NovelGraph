"""Read-only, restart-safe operator hints derived from immutable NovelGraph records.

This is a diagnostic snapshot, never a proof of complete manuscript extraction.
"""
from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from .world_state import _assert_approved_review

_SHA = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = ("proposed", "approved", "rejected")
_KINDS = ("entity", "event", "relation", "state_change", "continuity_fact")


def workflow_status(root: Path, work: str, episode: int, observed_sha: str) -> dict:
    """Describe the safe next manual step without storing a checkpoint or editing DB."""
    if (not isinstance(work, str) or not re.fullmatch(r"[\w.-]{1,100}", work)
            or type(episode) is not int or episode < 1
            or not isinstance(observed_sha, str) or not _SHA.fullmatch(observed_sha)):
        raise ValueError("invalid workflow work, episode or source SHA")

    counts = {status: 0 for status in _STATUSES}
    kinds = {kind: 0 for kind in _KINDS}
    path = root / "novelgraph.sqlite"
    result = {
        "work_id": work,
        "episode": episode,
        "observed_source_sha256": observed_sha,
        "registered_source_sha256": None,
        "source_status": "database_missing",
        "candidate_counts": counts,
        "candidate_kind_counts": kinds,
        "model_review": {"supports": 0, "needs_review": 0,
                         "unsupported": 0, "unassessed": 0},
        "revision_summary": {"superseded_proposed": 0, "active_proposed": 0},
        "approved_state_changes_pending_apply": [],
        "applied_state_change_ids": [],
        "next_actions": ["EXTRACT_AND_PREFLIGHT"],
        "halt_mutations": False,
        "read_only": True,
        "source_quotes_included": False,
        "extraction_completeness_verified": False,
        "human_identity_authenticated": False,
        "semantic_accuracy_measured": False,
    }

    if path.is_symlink():
        raise ValueError("candidate database symlinks are forbidden")
    if not path.exists():
        return result
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("candidate database must be a private regular file")

    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        registered = db.execute(
            "SELECT source_sha256 FROM episodes WHERE work_id=? AND episode=?",
            (work, episode),
        ).fetchone()
        if not registered:
            result["source_status"] = "episode_unregistered"
            return result

        result["registered_source_sha256"] = registered[0]
        result["source_status"] = (
            "matches_registered" if registered[0] == observed_sha
            else "source_mismatch"
        )
        rows = db.execute(
            "SELECT candidate_id, kind, status FROM candidates "
            "WHERE work_id=? AND episode=? ORDER BY candidate_id",
            (work, episode),
        ).fetchall()

        approved_changes = set()
        proposed_ids = set()
        for cid, kind, status in rows:
            if status not in counts or kind not in kinds:
                raise ValueError("unexpected stored candidate kind or status")
            counts[status] += 1
            kinds[kind] += 1
            if status == "proposed":
                proposed_ids.add(cid)
            if status == "approved":
                _assert_approved_review(db, cid)
                if kind == "state_change":
                    approved_changes.add(cid)

        superseded_ids = set()
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidate_revisions'"
        ).fetchone():
            revision_rows = db.execute(
                "SELECT r.old_candidate_id,r.new_candidate_id,"
                " old.status,new.work_id,new.episode FROM candidate_revisions r"
                " JOIN candidates old ON old.candidate_id=r.old_candidate_id"
                " JOIN candidates new ON new.candidate_id=r.new_candidate_id"
                " WHERE old.work_id=? AND old.episode=?", (work, episode)
            ).fetchall()
            for old_id, new_id, old_status, new_work, new_episode in revision_rows:
                if (old_status != "proposed" or old_id not in proposed_ids
                        or new_work != work or new_episode != episode):
                    raise ValueError("candidate revision lineage is inconsistent")
                superseded_ids.add(old_id)
        active_ids = proposed_ids - superseded_ids
        result["revision_summary"] = {
            "superseded_proposed": len(superseded_ids),
            "active_proposed": len(active_ids),
        }

        opinions = {}
        if active_ids and db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_assessments'"
        ).fetchone():
            for cid, assessment in db.execute(
                "SELECT ma.candidate_id, ma.assessment FROM model_assessments ma "
                "JOIN candidates c ON c.candidate_id=ma.candidate_id "
                "WHERE c.work_id=? AND c.episode=? AND c.status='proposed' "
                "ORDER BY ma.assessment_id", (work, episode)
            ):
                if assessment not in ("supports", "needs_review", "unsupported"):
                    raise ValueError("unexpected model assessment")
                if cid in active_ids:
                    opinions[cid] = assessment
        for assessment in opinions.values():
            result["model_review"][assessment] += 1
        result["model_review"]["unassessed"] = len(active_ids) - len(opinions)

        has_applied = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='applied_events'"
        ).fetchone()
        applied = set()
        if has_applied:
            events = db.execute(
                "SELECT candidate_id FROM applied_events "
                "WHERE work_id=? AND source_episode=? ORDER BY candidate_id",
                (work, episode),
            ).fetchall()
            applied = {row[0] for row in events}
            if not applied.issubset(approved_changes):
                raise ValueError("applied events do not match approved source candidates")

        result["applied_state_change_ids"] = sorted(applied)
        result["approved_state_changes_pending_apply"] = sorted(
            approved_changes - applied
        )

    if result["source_status"] == "source_mismatch":
        result["halt_mutations"] = True
        result["next_actions"] = ["SOURCE_VERSION_AUDIT"]
        return result

    actions = []
    if not rows:
        actions.append("EXTRACT_AND_PREFLIGHT")
    else:
        if result["revision_summary"]["active_proposed"]:
            actions.append("HUMAN_REVIEW")
        if result["approved_state_changes_pending_apply"]:
            actions.append("APPLY_APPROVED")
    if not actions:
        actions.append("READ_ONLY_CHECKS")
    result["next_actions"] = actions
    return result
