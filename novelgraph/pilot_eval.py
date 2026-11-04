"""Evidence-grounded pilot evaluation against human-labelled continuity cases.

This utility never extracts meaning from novel text. It measures the output of
check-continuity against an independently prepared adjudicated answer key.
Everything it reads belongs in the private data root, never public Git.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re


CATEGORIES = frozenset({
    "CONFIRMED_CONFLICT", "NEEDS_REVIEW", "EXPLAINED_CHANGE",
    "INSUFFICIENT_EVIDENCE",
})
SHA = re.compile(r"^[0-9a-f]{64}$")


def _fail(message: str):
    raise ValueError(message)


def _strict_object(value, required: set[str], label: str):
    if not isinstance(value, dict) or not required <= set(value):
        _fail(f"{label} must contain {sorted(required)}")
    return value


def _manifest(root: Path, document: dict) -> tuple[str, dict[int, tuple[str, str]]]:
    _strict_object(document, {"work_id", "episodes"}, "manifest")
    work_id = document["work_id"]
    if not isinstance(work_id, str) or not work_id:
        _fail("manifest has invalid work_id")
    episodes = document["episodes"]
    if not isinstance(episodes, dict) or not episodes:
        _fail("manifest episodes must be a nonempty mapping")
    verified: dict[int, tuple[str, str]] = {}
    for key, entry in episodes.items():
        if not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key:
            _fail("manifest episode keys must be canonical decimal strings")
        number = int(key)
        if number < 1:
            _fail("manifest episode must be positive")
        _strict_object(entry, {"source", "source_sha256"}, "manifest episode")
        relative = entry["source"]
        digest = entry["source_sha256"]
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            _fail("manifest source must be a relative private path")
        if not isinstance(digest, str) or not SHA.fullmatch(digest):
            _fail("manifest source hash must be a SHA-256 hex string")
        source = (root / relative).resolve(strict=True)
        if not source.is_file() or not source.is_relative_to(root):
            _fail("manifest source must resolve within private data root")
        payload = source.read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            _fail(f"source hash mismatch for episode {number}")
        text = payload.decode("utf-8")
        verified[number] = (digest, text)
    return work_id, verified


def _evidence_key(item: dict, episodes: dict, *, require_valid: bool) -> tuple | None:
    if not isinstance(item, dict):
        if require_valid:
            _fail("gold evidence item must be an object")
        return None
    number, start, end, digest = (
        item.get("episode"), item.get("start"), item.get("end"),
        item.get("source_sha256"),
    )
    valid = (
        type(number) is int and number in episodes
        and type(start) is int and type(end) is int
        and 0 <= start < end <= len(episodes[number][1])
        and digest == episodes[number][0]
    )
    if not valid:
        if require_valid:
            _fail("gold evidence reference has invalid episode, span or hash")
        return None
    return (number, start, end, digest)


def _key(item: dict, episodes: dict, *, gold: bool):
    if not isinstance(item, dict):
        if gold:
            _fail("gold finding must be an object")
        return None
    category, subject, field = (
        item.get("category"), item.get("subject_id"), item.get("field"),
    )
    ev = item.get("evidence")
    if (
        not isinstance(category, str) or category not in CATEGORIES
        or not isinstance(subject, str) or not subject.strip()
        or not isinstance(field, str) or not field.strip()
        or not isinstance(ev, list) or not ev
    ):
        if gold:
            _fail("gold finding has invalid category, subject, field or evidence")
        return None
    evidence = [_evidence_key(ref, episodes, require_valid=gold) for ref in ev]
    if any(key is None for key in evidence):
        return None
    if len(set(evidence)) != len(evidence):
        if gold:
            _fail("gold finding repeats one evidence reference")
        return None
    return category, subject, field, tuple(sorted(evidence))


def _ratio(numerator: int, denominator: int):
    return round(numerator / denominator, 4) if denominator else None


def _scores(tp: int, fp: int, fn: int):
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = (
        round(2 * precision * recall / (precision + recall), 4)
        if precision is not None and recall is not None
        and precision + recall > 0 else None
    )
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
    }


def evaluate_pilot(root: Path, manifest: dict, gold: dict, predicted: dict) -> dict:
    """Compare predicted findings with human labels by category and evidence span."""
    work, episodes = _manifest(root, manifest)
    _strict_object(gold, {"work_id", "as_of_episode", "findings"}, "gold document")
    _strict_object(predicted, {"work_id", "as_of_episode", "findings"},
                   "predictions")
    if (
        gold["work_id"] != work or predicted["work_id"] != work
        or type(gold["as_of_episode"]) is not int
        or gold["as_of_episode"] < 1
        or predicted["as_of_episode"] != gold["as_of_episode"]
    ):
        _fail("gold, predictions and manifest must refer to the same work/time")
    episode = gold["as_of_episode"]
    if episode not in episodes:
        _fail("gold as-of episode is not included in the manifest")
    gold_rows = gold["findings"]
    predicted_rows = predicted["findings"]
    if not isinstance(gold_rows, list) or not isinstance(predicted_rows, list):
        _fail("gold and predictions findings must be lists")
    gold_keys = [_key(item, episodes, gold=True) for item in gold_rows]
    if len(set(gold_keys)) != len(gold_keys):
        _fail("gold findings contain duplicate labels")
    predicted_keys = [_key(item, episodes, gold=False) for item in predicted_rows]
    valid_prediction_count = sum(key is not None for key in predicted_keys)
    gold_counts = Counter(gold_keys)
    pred_counts = Counter(key for key in predicted_keys if key is not None)
    matches = gold_counts & pred_counts
    tp = sum(matches.values())
    total_gold = len(gold_keys)
    total_pred = len(predicted_keys)
    per_category = {}
    for category in sorted(CATEGORIES):
        g = Counter(key for key in gold_keys if key[0] == category)
        p = Counter(key for key in predicted_keys
                    if key is not None and key[0] == category)
        valid_matched = sum((g & p).values())
        invalid_by_category = sum(
            key is None and isinstance(item, dict)
            and item.get("category") == category
            for key, item in zip(predicted_keys, predicted_rows)
        )
        per_category[category] = _scores(
            valid_matched, sum(p.values()) - valid_matched + invalid_by_category,
            sum(g.values()) - valid_matched,
        )
    false_positive = []
    for index, (item, key) in enumerate(zip(predicted_rows, predicted_keys)):
        if key is None:
            false_positive.append({
                "index": index, "finding_id": item.get("finding_id") if isinstance(item, dict) else None,
                "reason": "invalid_evidence_or_fields",
            })
        elif pred_counts[key] > gold_counts[key]:
            false_positive.append({
                "index": index, "finding_id": item.get("finding_id"),
                "reason": "not_in_adjudicated_gold_or_duplicate",
            })
            pred_counts[key] -= 1
    missed_gold = []
    for index, key in enumerate(gold_keys):
        if matches[key] < gold_counts[key]:
            missed_gold.append({"gold_index": index, "category": key[0],
                                "subject_id": key[1], "field": key[2]})
            gold_counts[key] -= 1
    return {
        "work_id": work,
        "as_of_episode": episode,
        "manifest_episodes_verified": len(episodes),
        "gold_findings": total_gold,
        "predicted_findings": total_pred,
        "invalid_prediction_evidence": total_pred - valid_prediction_count,
        "overall": _scores(tp, total_pred - tp, total_gold - tp),
        "per_category": per_category,
        "false_positive": false_positive,
        "missed_gold": missed_gold,
        "source_text_included": False,
        "gold_is_human_adjudicated": True,
    }
