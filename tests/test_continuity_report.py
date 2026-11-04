"""Phase 09: writer-facing continuity reports using synthetic prose only."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class ContinuityReportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="novelgraph-report-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def cli(self, *args, expected=0):
        proc = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root), *args],
            capture_output=True, text=True, timeout=20
        )
        self.assertEqual(proc.returncode, expected, proc.stderr + proc.stdout)
        return proc.stdout if expected == 0 else proc.stderr

    def stage(self, episode, text, payload, *, approved=True):
        source = self.root / f"{episode:03d}.txt"
        source.write_text(text, encoding="utf-8")
        document = {
            "schema_version": 1, "work_id": "demo", "episode": episode,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "candidates": [{
                "kind": "continuity_fact", "payload": payload,
                "evidence": {"start": 0, "end": len(text),
                             "text": text},
            }],
        }
        input_file = self.root / f"{episode:03d}.json"
        input_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        self.cli("import-candidates", "--source", str(source), "--input", str(input_file))
        rows = json.loads(self.cli("list-candidates", "--work-id", "demo",
                                   "--episode", str(episode)))["candidates"]
        candidate_id = rows[0]["candidate_id"]
        if approved:
            self.cli("review-candidate", "--source", str(source),
                     "--candidate-id", candidate_id, "--decision", "approve",
                     "--reviewer", "synthetic-reviewer",
                     "--reason", "approved synthetic evidence")
        return candidate_id

    def fact(self, episode, text, subject, field, value, *, effective=None, currency=None,
             certainty="confirmed"):
        payload = {
            "fact_type": "amount" if field == "amount" else "location",
            "subject_id": subject, "field": field, "value": value,
            "certainty": certainty,
        }
        if effective is not None:
            payload["effective_episode"] = effective
        if currency:
            payload["currency"] = currency
        return self.stage(episode, text, payload)

    def report(self, episode):
        return self.cli("continuity-report", "--work-id", "demo", "--episode", str(episode))

    def test_conflict_report_links_both_evidence_locations_and_values(self):
        first = self.fact(1, "거래액 15만 달러", "deal:one", "amount",
                          "150000", currency="USD")
        second = self.fact(2, "거래액 30만 달러", "deal:one", "amount",
                           "300000", currency="USD", effective=1)
        result = self.report(2)
        self.assertIn("확정 충돌", result)
        self.assertIn("150000 USD", result)
        self.assertIn("300000 USD", result)
        self.assertIn("1화", result)
        self.assertIn("2화", result)
        self.assertIn("[0, 10)", result)
        self.assertIn(first, result)
        self.assertIn(second, result)
        self.assertIn("원문 인용", result)
        self.assertNotIn("거래액 15만 달러", result)
        self.assertIn("검토", result)

    def test_review_and_insufficient_are_not_reported_as_confirmed(self):
        self.fact(1, "선착장에 있었다", "character:a", "location_id", "harbor")
        self.fact(2, "창고에 있었다", "character:a", "location_id", "warehouse")
        result = self.report(2)
        self.assertIn("추가 검토", result)
        self.assertIn("NEEDS_REVIEW", result)
        self.assertIn("0건", result)
        self.assertNotIn("CONFIRMED_CONFLICT] (1건)", result)

    def test_explained_change_is_visible_as_information_not_error(self):
        self.fact(1, "15달러", "deal:a", "amount", "15", currency="USD")
        self.stage(2, "변경을 확정했다", {
            "fact_type": "change", "subject_id": "deal:a", "field": "amount",
            "from_value": "15", "to_value": "30", "currency": "USD",
            "reason_code": "amended",
        })
        self.fact(3, "30달러", "deal:a", "amount", "30", currency="USD")
        output = self.report(3)
        self.assertIn("설명된 변화", output)
        self.assertIn("EXPLAINED_CHANGE", output)
        self.assertIn("근거", output)

    def test_unmatched_change_shows_insufficient_evidence(self):
        self.stage(1, "변경을 추정했다", {
            "fact_type": "change", "subject_id": "deal:alone",
            "field": "amount", "from_value": "15", "to_value": "30",
            "currency": "USD", "reason_code": "amended", "certainty": "uncertain",
        })
        output = self.report(1)
        self.assertIn("근거 부족", output)
        self.assertIn("INSUFFICIENT_EVIDENCE", output)

    def test_unapproved_is_not_no_errors_claim(self):
        self.stage(1, "미승인 사건", {
            "fact_type": "location", "subject_id": "location:a",
            "field": "location_id", "value": "garden",
        }, approved=False)
        output = self.report(1)
        self.assertIn("승인된 연속성 사실이 없습니다", output)
        self.assertIn("원고 전체에 오류가 없다는 뜻이 아닙니다", output)

    def test_forged_approved_record_is_rejected(self):
        candidate = self.stage(1, "가짜 승인", {
            "fact_type": "location", "subject_id": "location:a",
            "field": "location_id", "value": "garden",
        }, approved=False)
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            db.execute("UPDATE candidates SET status='approved' WHERE candidate_id=?",
                       (candidate,))
        output = self.cli("continuity-report", "--work-id", "demo",
                          "--episode", "1", expected=2)
        self.assertIn("approved review log", output)

    def test_report_does_not_modify_database(self):
        self.fact(1, "기록된 위치", "person:a", "location_id", "room")
        path = self.root / "novelgraph.sqlite"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        self.report(1)
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_missing_db_and_unregistered_episode_fail_closed(self):
        result = self.cli("continuity-report", "--work-id", "demo",
                          "--episode", "1", expected=2)
        self.assertIn("database", result)
        self.assertFalse((self.root / "novelgraph.sqlite").exists())
        self.fact(1, "위치 확인", "person:a", "location_id", "room")
        result = self.cli("continuity-report", "--work-id", "demo",
                          "--episode", "2", expected=2)
        self.assertIn("episode is not registered", result)

    def test_renderer_rejects_missing_evidence_and_deduplicates_exact_findings(self):
        from novelgraph.report import render_continuity_report
        evidence = {
            "candidate_id": "a" * 64, "episode": 1, "effective_episode": 1,
            "start": 0, "end": 5, "source_sha256": "b" * 64,
        }
        finding = {
            "finding_id": "c" * 20, "category": "NEEDS_REVIEW",
            "reason_code": "UNEXPLAINED_STATE_CHANGE",
            "subject_id": "item:1", "field": "location_id",
            "previous_value": "house", "current_value": "station",
            "evidence": [evidence],
        }
        report = {"work_id": "demo", "as_of_episode": 1,
                  "reviewed_facts": 2, "reviewed_change_events": 0,
                  "findings": [finding, dict(finding)]}
        output = render_continuity_report(report)
        self.assertEqual(output.count("c" * 20), 1)
        with self.assertRaisesRegex(ValueError, "evidence"):
            render_continuity_report({**report, "findings": [
                {**finding, "evidence": []}
            ]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            render_continuity_report({**report, "findings": [
                finding, {**finding, "subject_id": "other"}
            ]})


if __name__ == "__main__":
    unittest.main()
