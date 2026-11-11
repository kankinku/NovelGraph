"""Read-only 1..43 episode coverage check; no source text in results."""
from pathlib import Path
from .privacy import private_path
import sqlite3
from urllib.parse import quote
from .pilot_eval import _manifest
from .world_state import _id


def check_batch(root: Path, manifest: dict, target: int = 43) -> dict:
    if type(target) is not int or not 1 <= target <= 10000:
        raise ValueError("target must be a positive episode number")
    work, episodes = _manifest(root, manifest)
    _id(work, "work_id")
    if any(n > target for n in episodes):
        raise ValueError("manifest episode exceeds target")
    registered = {}
    pending = {}
    dbfile = root / "novelgraph.sqlite"
    if dbfile.is_symlink():
        raise ValueError("database symlinks are forbidden")
    if dbfile.exists():
        if not dbfile.is_file() or not private_path(dbfile):
            raise ValueError("database must be a private regular file")
        uri = "file:" + quote(str(dbfile)) + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            for n, digest in db.execute(
                "SELECT episode,source_sha256 FROM episodes WHERE work_id=?",
                (work,),
            ):
                registered[n] = digest
            for n, count in db.execute(
                "SELECT episode,COUNT(*) FROM candidates WHERE work_id=? "
                "AND status='proposed' GROUP BY episode", (work,)
            ):
                pending[n] = count
    for n, (digest, _) in episodes.items():
        if n in registered and registered[n] != digest:
            raise ValueError(f"registered source hash mismatch: episode {n}")
    missing = [n for n in range(1, target + 1) if n not in episodes]
    unregistered = [n for n in range(1, target + 1)
                    if n in episodes and n not in registered]
    result = {
        "work_id": work, "target_episode": target,
        "verified_source_files": len(episodes),
        "missing_episodes": missing,
        "unregistered_episodes": unregistered,
        "pending_candidate_count": sum(pending.values()),
        "readiness_to_begin_full_review": not missing and not unregistered,
        "review_queue_clear": not any(pending.values()),
        "semantic_accuracy_measured": False,
        "source_text_included": False,
    }
    return result
