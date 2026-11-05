"""Staging-only candidate intake for NovelGraph.

No LLM calls, approvals, or world-state mutations occur here.
All real inputs must stay outside the public Git repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

DEFAULT_ROOT = Path("/shared/NovelGraph-data")
DB_NAME = "novelgraph.sqlite"
MAX_INPUT_BYTES = 4 * 1024 * 1024
WORK_ID = re.compile(r"^[\w.-]{1,100}$", re.UNICODE)
KINDS = {"entity", "event", "relation", "state_change", "continuity_fact"}


def _fatal(message: str) -> None:
    raise ValueError(message)


def _data_root(raw: str) -> Path:
    root = Path(raw).resolve(strict=True)
    if not root.is_dir():
        _fatal("data root must be a directory")
    if root.stat().st_mode & 0o077:
        _fatal("private data root must deny access to group and others")
    code_root = Path(__file__).resolve().parents[1]
    if root.is_relative_to(code_root):
        _fatal("data root must be outside the public source tree")
    return root


def _private_file(raw: str, root: Path) -> Path:
    path = Path(raw).resolve(strict=True)
    code_root = Path(__file__).resolve().parents[1]
    if not path.is_file() or not path.is_relative_to(root) or path.is_relative_to(code_root):
        _fatal("input must be a regular file under the private data root")
    if path.stat().st_size > MAX_INPUT_BYTES:
        _fatal("input file exceeds 4 MiB limit")
    return path


def _source(path: Path) -> tuple[str, str, int]:
    data = path.read_bytes()
    if not data:
        _fatal("source is empty")
    text = data.decode("utf-8")
    return text, hashlib.sha256(data).hexdigest(), len(data)


def _read_json(path: Path) -> dict:
    def forbidden_constant(value: str) -> None:
        _fatal(f"non-finite JSON value: {value}")

    result = json.loads(path.read_bytes().decode("utf-8"), parse_constant=forbidden_constant)
    if not isinstance(result, dict):
        _fatal("candidate document must be a JSON object")
    return result


def _check_work_id(value: object) -> str:
    if not isinstance(value, str) or not WORK_ID.fullmatch(value):
        _fatal("work_id must be 1-100 letters, numbers, dot, hyphen or underscore")
    return value


def _check_episode(value: object) -> int:
    if type(value) is not int or value <= 0:
        _fatal("episode must be a positive integer")
    return value


def _valid_candidates(document: dict, text: str, digest: str) -> tuple[str, int, list[tuple]]:
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        _fatal("schema_version must be 1")
    work = _check_work_id(document.get("work_id"))
    episode = _check_episode(document.get("episode"))
    if document.get("source_sha256") != digest:
        _fatal("source_sha256 does not match source bytes")
    records = document.get("candidates")
    if not isinstance(records, list):
        _fatal("candidates must be a list")
    results: list[tuple] = []
    for index, candidate in enumerate(records):
        if not isinstance(candidate, dict):
            _fatal(f"candidate {index}: must be an object")
        kind = candidate.get("kind")
        payload = candidate.get("payload")
        evidence = candidate.get("evidence")
        if not isinstance(kind, str) or kind not in KINDS:
            _fatal(f"candidate {index}: unsupported kind")
        if not isinstance(payload, dict) or not payload:
            _fatal(f"candidate {index}: payload must be a nonempty object")
        if not isinstance(evidence, dict):
            _fatal(f"candidate {index}: evidence is required")
        start, end, quote = evidence.get("start"), evidence.get("end"), evidence.get("text")
        if type(start) is not int or type(end) is not int or not (0 <= start < end <= len(text)):
            _fatal(f"candidate {index}: invalid Unicode character span")
        if not isinstance(quote, str) or text[start:end] != quote:
            _fatal(f"candidate {index}: evidence does not match original source")
        payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":"), allow_nan=False)
        canonical = json.dumps(
            [work, episode, digest, kind, json.loads(payload_json), start, end, quote],
            sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        candidate_id = hashlib.sha256(canonical).hexdigest()
        results.append((candidate_id, work, episode, kind, payload_json, start, end, quote))
    return work, episode, results


def _connect(path: Path) -> sqlite3.Connection:
    if path.is_symlink():
        _fatal("database symlinks are forbidden")
    if path.exists() and (not path.is_file() or path.stat().st_mode & 0o077):
        _fatal("database must be a private regular file")
    previous = os.umask(0o077)
    try:
        db = sqlite3.connect(path)
    finally:
        os.umask(previous)
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _init_tables(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS episodes ("
        "work_id TEXT NOT NULL, episode INTEGER NOT NULL, source_sha256 TEXT NOT NULL,"
        "source_bytes INTEGER NOT NULL, PRIMARY KEY (work_id, episode))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS candidates ("
        "candidate_id TEXT PRIMARY KEY, work_id TEXT NOT NULL, episode INTEGER NOT NULL,"
        "kind TEXT NOT NULL, payload_json TEXT NOT NULL, evidence_start INTEGER NOT NULL,"
        "evidence_end INTEGER NOT NULL, evidence_text TEXT NOT NULL,"
        "status TEXT NOT NULL DEFAULT 'proposed'"
        " CHECK(status IN ('proposed','approved','rejected')),"
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "FOREIGN KEY (work_id, episode) REFERENCES episodes(work_id,episode))"
    )


def import_candidates(root: Path, source_path: Path, candidate_path: Path) -> dict:
    text, digest, byte_count = _source(source_path)
    work, episode, records = _valid_candidates(_read_json(candidate_path), text, digest)
    db_path = root / DB_NAME
    db = _connect(db_path)
    try:
        with db:
            _init_tables(db)
            stored = db.execute(
                "SELECT source_sha256 FROM episodes WHERE work_id=? AND episode=?",
                (work, episode),
            ).fetchone()
            if stored and stored[0] != digest:
                _fatal("episode source changed: original is immutable until versioning is implemented")
            if not stored:
                db.execute(
                    "INSERT INTO episodes(work_id,episode,source_sha256,source_bytes) "
                    "VALUES(?,?,?,?)", (work, episode, digest, byte_count)
                )
            inserted = 0
            for record in records:
                cursor = db.execute(
                    "INSERT INTO candidates(candidate_id,work_id,episode,kind,payload_json,"
                    "evidence_start,evidence_end,evidence_text) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(candidate_id) DO NOTHING", record
                )
                inserted += cursor.rowcount
        return {"work_id": work, "episode": episode, "submitted": len(records),
                "inserted": inserted, "duplicates": len(records) - inserted,
                "status": "proposed", "world_state_mutations": 0}
    finally:
        db.close()


def preflight_candidates(root: Path, source: Path, input_file: Path) -> dict:
    """Validate a proposed extraction without registering or approving anything."""
    text, digest, _ = _source(source)
    work, episode, records = _valid_candidates(_read_json(input_file), text, digest)
    from .world_state import _payload
    from .continuity import validate_fact

    counts = {kind: 0 for kind in sorted(KINDS)}
    for record in records:
        counts[record[3]] += 1
        if record[3] == "state_change":
            _payload({"payload_json": record[4], "episode": episode})
        elif record[3] == "continuity_fact":
            validate_fact({
                "payload_json": record[4], "episode": episode,
                "candidate_id": record[0], "evidence_start": record[5],
                "evidence_end": record[6], "source_sha256": digest,
            })

    return {
        "work_id": work, "episode": episode, "source_sha256": digest,
        "candidate_count": len(records), "kind_counts": counts,
        "duplicate_candidate_entries": len(records) - len({r[0] for r in records}),
        "state_change_payloads_checked": counts["state_change"],
        "continuity_fact_payloads_checked": counts["continuity_fact"],
        "read_only": True, "semantic_accuracy_measured": False,
        "human_review_completed": False, "source_text_included": False,
    }


def audit_source_version(root: Path, work: str, episode: int, source: Path) -> dict:
    """Compare current private source bytes to its immutable registered version."""
    _, observed_sha, _ = _source(source)
    db_path = root / DB_NAME
    if db_path.is_symlink() or not db_path.is_file():
        _fatal("candidate database does not exist or is not a regular file")
    if db_path.stat().st_mode & 0o077:
        _fatal("candidate database must be private")
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
        registered = db.execute(
            "SELECT source_sha256 FROM episodes WHERE work_id=? AND episode=?",
            (work, episode),
        ).fetchone()
        if not registered:
            _fatal("episode is not registered")
        rows = db.execute(
            "SELECT candidate_id,status FROM candidates "
            "WHERE work_id=? AND episode=? ORDER BY candidate_id",
            (work, episode),
        ).fetchall()
        has_applied_table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='applied_events'"
        ).fetchone()
        applied = []
        if has_applied_table:
            applied = [row[0] for row in db.execute(
                "SELECT candidate_id FROM applied_events "
                "WHERE work_id=? AND source_episode=? ORDER BY candidate_id",
                (work, episode),
            ).fetchall()]
    same = observed_sha == registered[0]
    counts = {key: 0 for key in ("proposed", "approved", "rejected")}
    for _, state in rows:
        counts[state] += 1
    return {
        "work_id": work, "episode": episode,
        "registered_source_sha256": registered[0],
        "observed_source_sha256": observed_sha,
        "source_matches_registered": same,
        "requires_new_version_workflow": not same,
        "candidate_counts": counts,
        "affected_approved_ids": [] if same else sorted(
            cid for cid, state in rows if state == "approved"
        ),
        "affected_applied_ids": [] if same else applied,
        "read_only": True, "source_quotes_included": False,
        "human_review_completed": False, "world_state_mutations": 0,
    }


def status(root: Path, work: str, episode: int) -> dict:
    db_path = root / DB_NAME
    if not db_path.is_file():
        _fatal("candidate database does not exist")
    db = _connect(db_path)
    try:
        episode_row = db.execute(
            "SELECT source_sha256 FROM episodes WHERE work_id=? AND episode=?",
            (work, episode)
        ).fetchone()
        if not episode_row:
            _fatal("episode is not registered")
        counts = {name: 0 for name in ("proposed", "approved", "rejected")}
        for state, count in db.execute(
            "SELECT status,COUNT(*) FROM candidates WHERE work_id=? AND episode=? "
            "GROUP BY status", (work, episode)
        ):
            counts[state] = count
        return {"work_id": work, "episode": episode,
                "source_sha256": episode_row[0], "candidate_counts": counts}
    finally:
        db.close()


def list_candidates(root: Path, work: str, episode: int) -> dict:
    db_path = root / DB_NAME
    if not db_path.is_file():
        _fatal("candidate database does not exist")
    db = _connect(db_path)
    try:
        rows = db.execute(
            "SELECT candidate_id, kind, status, evidence_start, evidence_end "
            "FROM candidates WHERE work_id=? AND episode=? ORDER BY evidence_start, candidate_id",
            (work, episode),
        ).fetchall()
        return {"work_id": work, "episode": episode,
                "candidates": [
                    {"candidate_id": row[0], "kind": row[1], "status": row[2],
                     "evidence_start": row[3], "evidence_end": row[4]}
                    for row in rows
                ]}
    finally:
        db.close()


def _graph_output_path(raw: str, root: Path, *, allow_existing: bool = False) -> Path:
    output = Path(raw).absolute()
    if output.name != "graph.json" or output.is_symlink():
        _fatal("Graphify output must be a regular file named graph.json")
    parent = output.parent.resolve(strict=True)
    if not parent.is_relative_to(root) or parent.stat().st_mode & 0o077:
        _fatal("Graphify output parent must be under the private data root")
    resolved = parent / output.name
    if resolved.exists():
        if not resolved.is_file() or resolved.stat().st_mode & 0o077:
            _fatal("existing graph output must be a private regular file")
        if not allow_existing:
            _fatal("graph.json already exists; use --overwrite to regenerate")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m novelgraph")
    parser.add_argument("--data-root", default=str(DEFAULT_ROOT))
    commands = parser.add_subparsers(dest="command", required=True)
    source_info = commands.add_parser("source-info", help="read private source hash and length")
    source_info.add_argument("--source", required=True)
    intake = commands.add_parser("import-candidates", help="validate and stage proposed claims")
    intake.add_argument("--source", required=True)
    intake.add_argument("--input", required=True)

    revision_intake = commands.add_parser(
        "import-revisions",
        help="stage provenance-linked proposed corrections without approving originals"
    )
    revision_intake.add_argument("--source", required=True)
    revision_intake.add_argument("--input", required=True)
    revision_intake.add_argument("--mapping", required=True)

    preflight = commands.add_parser(
        "preflight-candidates", help="check evidence and state-event structure without storing candidates"
    )
    preflight.add_argument("--source", required=True)
    preflight.add_argument("--input", required=True)
    version = commands.add_parser(
        "source-version-audit", help="read-only source SHA drift and candidate impact audit"
    )
    version.add_argument("--work-id", required=True)
    version.add_argument("--episode", required=True, type=int)
    version.add_argument("--source", required=True)

    workflow = commands.add_parser(
        "workflow-status", help="read-only source and approval checkpoint for manual resume"
    )
    workflow.add_argument("--work-id", required=True)
    workflow.add_argument("--episode", required=True, type=int)
    workflow.add_argument("--source", required=True)
    backup_cmd = commands.add_parser(
        "backup-database", help="create a private, verified SQLite snapshot without overwriting"
    )
    backup_cmd.add_argument("--output", required=True)
    restore_cmd = commands.add_parser(
        "restore-database", help="verify private backup and restore only to a new SQLite file"
    )
    restore_cmd.add_argument("--backup", required=True)
    restore_cmd.add_argument("--output", required=True)
    get_status = commands.add_parser("status", help="view candidate counts without leaking excerpts")
    get_status.add_argument("--work-id", required=True)
    get_status.add_argument("--episode", required=True, type=int)

    listing = commands.add_parser("list-candidates", help="list candidate IDs without source text")
    listing.add_argument("--work-id", required=True)
    listing.add_argument("--episode", required=True, type=int)

    reviewer = commands.add_parser("review-candidate", help="explicitly review one candidate")
    reviewer.add_argument("--source", required=True)
    reviewer.add_argument("--candidate-id", required=True)
    reviewer.add_argument("--decision", choices=("approve", "reject"), required=True)
    reviewer.add_argument("--reviewer", required=True)
    reviewer.add_argument("--reason", required=True)

    assessment = commands.add_parser(
        "assess-candidate", help="record a model opinion without reviewing or approving"
    )
    assessment.add_argument("--source", required=True)
    assessment.add_argument("--candidate-id", required=True)
    assessment.add_argument("--assessment", choices=(
        "supports", "needs_review", "unsupported"
    ), required=True)
    assessment.add_argument("--model-label", required=True)
    assessment.add_argument("--reason", required=True)

    review_audit = commands.add_parser(
        "review-audit", help="read-only summary of model assessments and approval trails"
    )
    review_audit.add_argument("--work-id", required=True)
    review_audit.add_argument("--episode", required=True, type=int)

    apply_cmd = commands.add_parser("apply-approved", help="apply approved state-change event")
    apply_cmd.add_argument("--source", required=True)
    apply_cmd.add_argument("--candidate-id", required=True)

    state_cmd = commands.add_parser("world-state", help="replay events as known at an episode")
    state_cmd.add_argument("--work-id", required=True)
    state_cmd.add_argument("--episode", required=True, type=int)
    continuity = commands.add_parser(
        "check-continuity", help="compare approved narrative facts with source references"
    )
    continuity.add_argument("--work-id", required=True)
    continuity.add_argument("--episode", required=True, type=int)
    continuity_report = commands.add_parser(
        "continuity-report", help="read-only Markdown review of approved continuity findings"
    )
    continuity_report.add_argument("--work-id", required=True)
    continuity_report.add_argument("--episode", required=True, type=int)
    export_cmd = commands.add_parser(
        "graphify-export", help="materialize reviewed facts as a private Graphify snapshot"
    )
    export_cmd.add_argument("--work-id", required=True)
    export_cmd.add_argument("--episode", required=True, type=int)
    export_cmd.add_argument("--output", required=True)
    export_cmd.add_argument("--overwrite", action="store_true")

    trace_cmd = commands.add_parser(
        "graphify-trace", help="trace a verified graph path back to episode evidence"
    )
    trace_cmd.add_argument("--work-id", required=True)
    trace_cmd.add_argument("--episode", required=True, type=int)
    trace_cmd.add_argument("--graph", required=True)
    trace_cmd.add_argument("--from-node", required=True)
    trace_cmd.add_argument("--to-node", required=True)

    pilot = commands.add_parser(
        "pilot-evaluate", help="score predictions against independently reviewed gold cases"
    )
    pilot.add_argument("--manifest", required=True)
    pilot.add_argument("--gold", required=True)
    pilot.add_argument("--predictions", required=True)

    batch = commands.add_parser(
        "batch-readiness", help="check private 1..N source manifest and registration coverage"
    )
    batch.add_argument("--manifest", required=True)
    batch.add_argument("--target", type=int, default=43)

    review_readiness = commands.add_parser(
        "review-readiness", help="verify private fact worksheet integrity and review completeness"
    )
    review_readiness.add_argument("--worksheet", required=True)

    packets = commands.add_parser(
        "prepare-review-packets", help="generate separate blind and candidate review packets"
    )
    packets.add_argument("--worksheet", required=True)
    packets.add_argument("--blind-output", required=True)
    packets.add_argument("--comparison-output", required=True)

    identity = commands.add_parser(
        "identity-audit", help="report possible staged identity collisions without merging"
    )
    identity.add_argument("--work-id", required=True)
    identity.add_argument("--episode", required=True, type=int)

    args = parser.parse_args(argv)
    try:
        root = _data_root(args.data_root)
        if args.command == "source-info":
            text, digest, size = _source(_private_file(args.source, root))
            value = {"source_sha256": digest, "unicode_characters": len(text),
                     "bytes": size, "span_format": "0-based Unicode [start,end)"}
        elif args.command == "import-candidates":
            value = import_candidates(
                root, _private_file(args.source, root), _private_file(args.input, root)
            )
        elif args.command == "import-revisions":
            from .candidate_revisions import import_revisions
            value = import_revisions(
                root, _private_file(args.source, root),
                _private_file(args.input, root),
                _private_file(args.mapping, root),
            )
        elif args.command == "preflight-candidates":
            value = preflight_candidates(
                root, _private_file(args.source, root), _private_file(args.input, root)
            )
        elif args.command == "backup-database":
            from .recovery import backup_database
            value = backup_database(root, args.output)
        elif args.command == "restore-database":
            from .recovery import restore_database
            value = restore_database(root, args.backup, args.output)
        elif args.command == "workflow-status":
            from .workflow import workflow_status
            source = _private_file(args.source, root)
            _, observed_sha, _ = _source(source)
            value = workflow_status(
                root, _check_work_id(args.work_id), _check_episode(args.episode),
                observed_sha,
            )
        elif args.command == "source-version-audit":
            value = audit_source_version(
                root, _check_work_id(args.work_id), _check_episode(args.episode),
                _private_file(args.source, root),
            )
        elif args.command == "status":
            value = status(root, _check_work_id(args.work_id),
                           _check_episode(args.episode))
        elif args.command == "list-candidates":
            value = list_candidates(root, _check_work_id(args.work_id),
                                    _check_episode(args.episode))
        elif args.command == "batch-readiness":
            from .batch_readiness import check_batch
            value = check_batch(
                root, _read_json(_private_file(args.manifest, root)), args.target
            )
        elif args.command == "review-readiness":
            from .review_readiness import check_review_readiness
            value = check_review_readiness(
                root, _read_json(_private_file(args.worksheet, root))
            )
        elif args.command == "prepare-review-packets":
            from .review_packets import prepare_review_packets
            value = prepare_review_packets(
                root, _read_json(_private_file(args.worksheet, root)),
                args.blind_output, args.comparison_output,
            )
        elif args.command == "review-audit":
            from .world_state import audit_reviews
            db_path = root / DB_NAME
            if db_path.is_symlink() or not db_path.is_file():
                _fatal("candidate database does not exist or is not a regular file")
            if db_path.stat().st_mode & 0o077:
                _fatal("candidate database must be private")
            with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
                value = audit_reviews(
                    db, _check_work_id(args.work_id),
                    _check_episode(args.episode),
                )
        elif args.command == "identity-audit":
            from .identity_audit import audit_identities
            db_path = root / DB_NAME
            if db_path.is_symlink() or not db_path.is_file():
                _fatal("candidate database does not exist or is not a regular file")
            if db_path.stat().st_mode & 0o077:
                _fatal("candidate database must be private")
            with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
                value = audit_identities(
                    db, _check_work_id(args.work_id),
                    _check_episode(args.episode),
                )
        elif args.command == "pilot-evaluate":
            from .pilot_eval import evaluate_pilot
            value = evaluate_pilot(
                root,
                _read_json(_private_file(args.manifest, root)),
                _read_json(_private_file(args.gold, root)),
                _read_json(_private_file(args.predictions, root)),
            )
        elif args.command in ("graphify-export", "graphify-trace"):
            from .graphify_bridge import export_graph, trace_graph
            db_path = root / DB_NAME
            if not db_path.is_file():
                _fatal("candidate database does not exist")
            db = _connect(db_path)
            try:
                work = _check_work_id(args.work_id)
                episode = _check_episode(args.episode)
                if args.command == "graphify-export":
                    path = _graph_output_path(
                        args.output, root, allow_existing=args.overwrite
                    )
                    value = export_graph(db, work, episode, path)
                    os.chmod(path, 0o600)
                else:
                    graph = _graph_output_path(
                        args.graph, root, allow_existing=True
                    )
                    if not graph.is_file():
                        _fatal("graph.json does not exist")
                    value = trace_graph(
                        db, work, episode, graph, args.from_node, args.to_node
                    )
            finally:
                db.close()
        elif args.command in ("continuity-report", "check-continuity"):
            from .continuity import check_continuity
            db_path = root / DB_NAME
            if db_path.is_symlink() or not db_path.is_file():
                _fatal("candidate database does not exist or is not a regular file")
            if db_path.stat().st_mode & 0o077:
                _fatal("candidate database must be private")
            work = _check_work_id(args.work_id)
            episode = _check_episode(args.episode)
            with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
                registered = db.execute(
                    "SELECT 1 FROM episodes WHERE work_id=? AND episode=?",
                    (work, episode),
                ).fetchone()
                if not registered:
                    _fatal("episode is not registered")
                result = check_continuity(db, work, episode)
            if args.command == "continuity-report":
                from .report import render_continuity_report
                value = render_continuity_report(result)
            else:
                value = result
        else:
            from .world_state import (
                approve_and_apply, assess_candidate, review_candidate, world_state
            )
            db_path = root / DB_NAME
            if not db_path.is_file():
                _fatal("candidate database does not exist")
            db = _connect(db_path)
            try:
                if args.command == "world-state":
                    value = world_state(
                        db, _check_work_id(args.work_id), _check_episode(args.episode)
                    )
                else:
                    text, digest, _ = _source(_private_file(args.source, root))
                    if args.command == "review-candidate":
                        value = review_candidate(
                            db, args.candidate_id, digest, text,
                            args.decision, args.reviewer, args.reason,
                        )
                    elif args.command == "assess-candidate":
                        value = assess_candidate(
                            db, args.candidate_id, digest, text,
                            args.assessment, args.model_label, args.reason,
                        )
                    else:
                        value = approve_and_apply(db, args.candidate_id, digest, text)
            finally:
                db.close()
        if args.command == "continuity-report":
            print(value, end="")
        else:
            print(json.dumps(value, ensure_ascii=False))
        return 0
    except (OSError, ValueError, UnicodeError, sqlite3.Error) as exc:
        print(f"novelgraph: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
