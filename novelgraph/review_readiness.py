"""Read-only integrity and review-completeness check for private fact worksheets.

This is NOT human authentication and does NOT promote candidates to gold.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


DECISIONS = frozenset({
    "accurate", "partially_accurate", "duplicate", "unsupported", "incorrect"
})


def _fail(message: str):
    raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _evidence(evidence, source, digest):
    if not isinstance(evidence, dict):
        _fail("missing evidence")
    start, end = evidence.get("start"), evidence.get("end")
    if (type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(source)
            or evidence.get("source_sha256") != digest):
        _fail("invalid evidence span or source hash")
    if evidence.get("text") != source[start:end]:
        _fail("evidence text mismatch")


def check_review_readiness(root: Path, document: dict) -> dict:
    """Report metadata readiness; NEVER assert independently verified human gold."""
    if not isinstance(document, dict) or document.get("schema_version") != 2:
        _fail("review worksheet schema_version must be 2")
    work = document.get("work_id")
    episodes = document.get("episodes")
    if not _text(work) or not isinstance(episodes, list) or not episodes:
        _fail("review worksheet needs work_id and episodes")
    seen_episodes, seen_reviews, seen_facts = set(), set(), set()
    verified_candidates = reviewed_candidates = verified_facts = blind_complete = 0

    for ep in episodes:
        if not isinstance(ep, dict):
            _fail("review episode must be an object")
        number = ep.get("episode")
        if type(number) is not int or number <= 0 or number in seen_episodes:
            _fail("review episode number invalid or duplicate")
        seen_episodes.add(number)

        filename = ep.get("source_file")
        if not _text(filename) or Path(filename).is_absolute():
            _fail("source path outside private root")
        source_file = (root / filename).resolve()
        if not source_file.is_relative_to(root):
            _fail("source path outside private root")
        if not source_file.is_file():
            _fail("source file is missing")
        contents = source_file.read_bytes()
        digest = hashlib.sha256(contents).hexdigest()
        if digest != ep.get("source_sha256"):
            _fail(f"source hash mismatch for episode {number}")
        source = contents.decode("utf-8")

        categories = ep.get("blind_review_categories")
        candidates = ep.get("candidates_second_pass")
        facts = ep.get("blind_fact_list")
        if (not isinstance(categories, dict) or not categories
                or not isinstance(candidates, list) or not isinstance(facts, list)):
            _fail("review episode missing categories, candidates or blind facts")

        for item in candidates:
            if not isinstance(item, dict) or not _text(item.get("review_id")):
                _fail("candidate is missing review_id")
            review_id = item["review_id"]
            if review_id in seen_reviews:
                _fail("duplicate review_id")
            seen_reviews.add(review_id)
            _evidence(item.get("evidence"), source, digest)
            verified_candidates += 1
            if (item.get("human_decision") in DECISIONS
                    and _text(item.get("human_reason"))
                    and _text(item.get("human_reviewer"))
                    and _text(item.get("reviewed_at"))):
                reviewed_candidates += 1

        fact_metadata_complete = bool(facts)
        for fact in facts:
            if not isinstance(fact, dict) or not _text(fact.get("fact_id")):
                _fail("blind fact requires fact_id")
            if fact["fact_id"] in seen_facts:
                _fail("duplicate fact_id")
            seen_facts.add(fact["fact_id"])
            if not _text(fact.get("claim")):
                _fail("blind fact requires claim")
            _evidence(fact.get("evidence"), source, digest)
            verified_facts += 1
            if not (_text(fact.get("reviewer")) and _text(fact.get("reviewed_at"))):
                fact_metadata_complete = False

        if (ep.get("blind_full_chapter_review") == "complete"
                and all(value == "complete" for value in categories.values())
                and _text(ep.get("reviewer"))
                and ep.get("independent_adjudication") is True
                and fact_metadata_complete):
            blind_complete += 1

    return {
        "work_id": work,
        "source_episodes_verified": len(seen_episodes),
        "candidate_evidence_verified": verified_candidates,
        "human_reviewed_candidates": reviewed_candidates,
        "pending_candidates": verified_candidates - reviewed_candidates,
        "blind_facts_with_evidence": verified_facts,
        "blind_review_complete_episodes": blind_complete,
        "ready_for_manual_signoff": (
            blind_complete == len(seen_episodes)
            and verified_candidates == reviewed_candidates
        ),
        "human_identity_authenticated": False,
        "gold_standard_verified": False,
        "source_text_included": False,
    }
