"""Read-only, source-reference-only Markdown summaries of continuity findings.

Never reconstruct quotes or treat unreviewed prose as a confirmed inconsistency.
"""
from __future__ import annotations

import json
import re

from .continuity import STATUSES

LABELS = {
    "CONFIRMED_CONFLICT": "확정 충돌",
    "NEEDS_REVIEW": "추가 검토",
    "EXPLAINED_CHANGE": "설명된 변화",
    "INSUFFICIENT_EVIDENCE": "근거 부족",
}
ORDER = ("CONFIRMED_CONFLICT", "NEEDS_REVIEW",
         "INSUFFICIENT_EVIDENCE", "EXPLAINED_CHANGE")
ADVICE = {
    "SAME_MOMENT_CONTRADICTION": "동일 사건·시점인지 원문을 재확인하고, 상충하는 날짜·위치·수치 중 수정할 대목을 결정하세요.",
    "DATE_WEEKDAY_MISMATCH": "날짜와 요일을 달력으로 대조하고 사건의 발생 연도를 확인하세요.",
    "UNCERTAIN_CALENDAR_FACT": "날짜·요일 중 추정인 근거를 확인한 뒤 확정 여부를 다시 검토하세요.",
    "CONTRACT_LEDGER_STATUS_MISMATCH": "계약 제안·서명·지급·권리 이전의 실제 시점과 뒤늦게 밝혀진 정보를 대조하세요.",
    "UNEXPLAINED_STATE_CHANGE": "서로 다른 값 사이의 이동·계약 수정·수익 발생 등 변경 근거가 있는지 확인하세요.",
    "REPEATED_COMPLETED_ACTION": "앞서 끝낸 행동을 실제로 다시 수행했는지, 서술만 반복했는지 확인하세요.",
    "UNCERTAIN_ASSERTION": "불확실한 진술을 확정 설정으로 취급하지 말고 원문 근거를 추가로 확인하세요.",
    "UNMATCHED_CHANGE_EVENT": "변경 전후 사실과 발생 시점이 서로 연결되는지 원문을 확인하세요.",
    "APPROVED_STATE_CHANGE": "승인된 변경 근거가 연결되어 있으므로 원문 일치 여부만 확인하세요.",
    "EXPLICIT_ACTION_REPEAT": "반복 행위가 승인된 사건으로 연결되어 있으므로 중복 기록 여부를 점검하세요.",
}
HEX20 = re.compile(r"^[0-9a-f]{20}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENT = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


def _evidence_lines(item: dict) -> list[str]:
    entries = item.get("evidence")
    if not isinstance(entries, list) or not entries:
        raise ValueError("report finding requires nonempty evidence")
    lines = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("report finding has invalid evidence item")
        cid = entry.get("candidate_id")
        sha = entry.get("source_sha256")
        episode = entry.get("episode")
        effective = entry.get("effective_episode")
        start = entry.get("start")
        end = entry.get("end")
        if (not isinstance(cid, str) or not HEX64.fullmatch(cid)
                or not isinstance(sha, str) or not HEX64.fullmatch(sha)
                or type(episode) is not int or episode < 1
                or type(effective) is not int or not 1 <= effective <= episode
                or type(start) is not int or type(end) is not int
                or not 0 <= start < end):
            raise ValueError("report finding has invalid evidence provenance")
        lines.append(
            f"  - {episode}화 (사건 시점 {effective}화), "
            f"원문 문자 [{start}, {end}), 후보 `{cid}`, 등록 SHA-256 `{sha}`"
        )
    return lines


def _compare(item: dict) -> str:
    currency = item.get("currency")
    suffix = f" {currency}" if currency else ""
    if "date" in item and "asserted_weekday" in item and "calendar_weekday" in item:
        return (f"날짜 {item['date']}, 원고 요일 {item['asserted_weekday']} "
                f"↔ 달력 요일 {item['calendar_weekday']}")
    if "asserted_status" in item and "ledger_status" in item:
        return f"원고 주장 {item['asserted_status']} ↔ 승인 원장 {item['ledger_status']}"
    if "previous_value" in item and "current_value" in item:
        return f"이전 {item['previous_value']}{suffix} → 이후 {item['current_value']}{suffix}"
    if "from_value" in item and "to_value" in item:
        return f"변경 주장 {item['from_value']}{suffix} → {item['to_value']}{suffix}"
    if "value" in item:
        return f"반복/상태 값 {item['value']}{suffix}"
    raise ValueError("report finding is missing comparable values")


def render_continuity_report(result: dict) -> str:
    """Render existing check_continuity output; this function never accesses source files."""
    if not isinstance(result, dict):
        raise ValueError("report input must be a continuity result")
    work = result.get("work_id")
    episode = result.get("as_of_episode")
    facts = result.get("reviewed_facts")
    changes = result.get("reviewed_change_events")
    findings = result.get("findings")
    if (not isinstance(work, str) or not IDENT.fullmatch(work)
            or type(episode) is not int or episode < 1
            or type(facts) is not int or facts < 0
            or type(changes) is not int or changes < 0
            or not isinstance(findings, list)):
        raise ValueError("report input has invalid metadata")

    unique: dict[str, dict] = {}
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("report finding is not an object")
        finding_id = finding.get("finding_id")
        category = finding.get("category")
        subject = finding.get("subject_id")
        field = finding.get("field")
        reason = finding.get("reason_code")
        if (not isinstance(finding_id, str) or not HEX20.fullmatch(finding_id)
                or category not in LABELS
                or not isinstance(subject, str) or not IDENT.fullmatch(subject)
                or not isinstance(field, str) or not IDENT.fullmatch(field)
                or not isinstance(reason, str) or not IDENT.fullmatch(reason)):
            raise ValueError("report finding has invalid identifiers")
        _evidence_lines(finding)
        _compare(finding)
        if finding_id in unique:
            if json.dumps(unique[finding_id], sort_keys=True) != json.dumps(finding, sort_keys=True):
                raise ValueError("report contains conflicting duplicate finding_id")
            continue
        unique[finding_id] = finding

    buckets = {key: [] for key in STATUSES}
    for item in unique.values():
        buckets[item["category"]].append(item)
    for group in buckets.values():
        group.sort(key=lambda x: (min(e["episode"] for e in x["evidence"]),
                                  x["subject_id"], x["field"], x["finding_id"]))

    lines = [
        f"# NovelGraph 연속성 검토 보고 — {work} / {episode}화까지",
        "",
        f"검토 대상: 승인된 연속성 사실 {facts}건, 승인된 변경 근거 {changes}건.",
        "",
        "| 판정 | 건수 |",
        "| --- | ---: |",
    ]
    lines += [f"| {LABELS[key]} (`{key}`) | {len(buckets[key])}건 |" for key in ORDER]
    lines += [
        "",
        "> 이 결과는 승인된 정규화 주장에 대한 기계적 비교이며, 원고 전체의 오류·무오류 판정이 아닙니다.",
        "> 인간 독립 정답표가 없어 정밀도·재현율은 미측정입니다. 승인자 문자열은 본인 인증이 아닙니다.",
        "> 근거는 등록 판본의 0부터 시작하는 Unicode 문자 위치 [시작, 끝)입니다. 현재 원고의 수정 여부는 별도 source-version-audit로 확인하세요.",
        "> 원문 인용 없이 후보 ID와 등록 SHA-256만 표시합니다.",
        "",
    ]
    if facts == 0 and changes == 0:
        lines += [
            "**승인된 연속성 사실이 없습니다.** 분석 범위가 비어 있으며 원고 전체에 오류가 없다는 뜻이 아닙니다.",
            "",
        ]
    elif not unique:
        lines += [
            "**현재 승인·구조화된 사실 사이에서 검출된 항목이 없습니다.** 누락된 사실이나 원고 전체의 오류 부재를 뜻하지 않습니다.",
            "",
        ]
    for category in ORDER:
        group = buckets[category]
        if not group:
            continue
        lines.append(f"## {LABELS[category]} ({category}) — {len(group)}건")
        lines.append("")
        for index, finding in enumerate(group, 1):
            lines += [
                f"### {index}. {finding['subject_id']} / {finding['field']}",
                f"- 판정: **{LABELS[category]}** (`{category}`), 이유 `{finding['reason_code']}`",
                f"- 비교값: {_compare(finding)}",
                f"- 조치 권고: {ADVICE.get(finding['reason_code'], '원문을 확인해 판정 근거와 상황 변화를 검토하세요.')}",
                f"- 식별자: `{finding['finding_id']}`",
                "- 근거 위치:",
                *_evidence_lines(finding),
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"
