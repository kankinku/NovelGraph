"""Split private human review into an unbiased first pass and a candidate comparison.

Never writes to SQLite or changes approval status; model claims stay in pass two.
"""
from __future__ import annotations

from .privacy import private_path

import json
import os
from pathlib import Path

from .review_readiness import check_review_readiness


def _output_path(raw: str, root: Path) -> Path:
    output = Path(raw).absolute()
    parent = output.parent.resolve(strict=True)
    if (output.suffix != ".md" or not parent.is_relative_to(root)
            or not private_path(parent)):
        raise ValueError("review packet output outside private root or insecure directory")
    if output.exists() or output.is_symlink():
        raise ValueError("review packet output already exists")
    return parent / output.name


def prepare_review_packets(root: Path, doc: dict, blind_raw: str, compare_raw: str) -> dict:
    verified = check_review_readiness(root, doc)
    blind = _output_path(blind_raw, root)
    compare = _output_path(compare_raw, root)
    if blind == compare:
        raise ValueError("review packet output paths must be distinct")

    first = [
        "# 1차 독립 판독용 (모델 후보 미포함)",
        "",
        "**독립 검수 전용. 원고를 먼저 직접 읽고 중요 사실을 기록하세요.**",
        "2차 비교표는 본문 전체 독립 검토를 마치기 전에는 열지 마세요.",
        "",
    ]
    second = [
        "# 2차 기존 모델 후보 대조표",
        "",
        "**1차 블라인드 판독을 마친 후에만 열어보세요.**",
        "**모델 후보는 검수 확정 사실이 아니며 오류·누락·과잉 추출이 있을 수 있습니다.**",
        "",
    ]
    for ep in doc["episodes"]:
        number = ep["episode"]
        first += [
            f"## {number}화 — 원고 전체 독립 검토",
            "",
            "원고를 먼저 읽은 뒤 중요한 사실·상태 변화·장면 연결·오류 의심을 기록하세요.",
            "각 기록에는 회차, 근거 원문 범위, 주장 내용, 실제 확정·계획·추정 구분이 필요합니다.",
            "",
        ]
        for category in ep["blind_review_categories"]:
            first.append(f"- [ ] {category}")
        first += ["", "원문 독립 검토 기록:", "", "", "---", ""]

        second += [f"## {number}화 — 모델 후보 비교", ""]
        for item in ep["candidates_second_pass"]:
            evidence = item["evidence"]
            claim = item["claim"]
            if isinstance(claim, dict):
                claim = json.dumps(claim, ensure_ascii=False, sort_keys=True)
            second += [
                f"### {item['review_id']} — {item.get('category', 'unknown')}",
                "",
                f"- 출처 구분: `{item.get('origin', 'unknown')}`",
                f"- 추출 주장: {claim}",
                f"- 근거 위치: {number}화, 문자 [{evidence['start']},{evidence['end']})",
                f"- 인용: {evidence['text']}",
                "- 독립 검수: 정확 / 일부 정확 / 중복 / 근거 부족 / 부정확 / 보류",
                "- 정정 내용과 이유:",
                "",
            ]

    # Exclusive creation prevents overwriting any existing private reviews.
    created: list[Path] = []
    try:
        for output, lines in ((blind, first), (compare, second)):
            handle = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            created.append(output)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write("\n".join(lines))
    except (OSError, UnicodeError) as exc:
        for output in created:
            output.unlink()
        raise ValueError(f"review packet write failed: {exc}") from exc
    return {
        "work_id": verified["work_id"],
        "packets_created": len(created),
        "source_episodes_verified": verified["source_episodes_verified"],
        "candidate_evidence_verified": verified["candidate_evidence_verified"],
        "gold_standard_verified": False,
        "human_identity_authenticated": False,
        "source_text_included_in_stdout": False,
    }
