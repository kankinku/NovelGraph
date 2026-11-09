"""Stage-03 extraction preflight: only synthetic private source text."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class CandidatePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="novelgraph-stage03-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.story = (
            "서진은 솔라 회사 주식 15%를 사기로 제안했다.\n"
            "상대가 거절해 계약서를 서명하지 않았다.\n"
            "서진은 2만 달러를 다음 달에 송금할 계획이다.\n"
            "어제 회사가 자문료로 3만 달러를 이미 송금했다고 기록됐다.\n"
        )
        self.source = self.root / "001.txt"
        self.source.write_text(self.story, encoding="utf-8")
        self.input = self.root / "001.candidates.json"

    def candidate(self, quote, *, kind="event", payload=None):
        start = self.story.index(quote)
        return {
            "kind": kind,
            "payload": payload or {
                "actor_id": "seojin", "event_type": "payment_planned", "target_id": "sola",
            },
            "evidence": {"start": start, "end": start + len(quote), "text": quote},
        }

    def document(self, candidates, digest=None):
        return {
            "schema_version": 1, "work_id": "synthetic",
            "episode": 1,
            "source_sha256": digest or hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "candidates": candidates,
        }

    def run_cli(self, candidates, *, digest=None, expected=0):
        self.input.write_text(
            json.dumps(self.document(candidates, digest), ensure_ascii=False),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root),
             "preflight-candidates", "--source", str(self.source),
             "--input", str(self.input)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout) if expected == 0 else result.stderr

    def test_valid_proposal_reports_read_only_without_inventing_state_changes(self):
        proposal = self.candidate("서진은 2만 달러를 다음 달에 송금할 계획이다.")
        result = self.run_cli([proposal])
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["kind_counts"]["event"], 1)
        self.assertEqual(result["state_change_payloads_checked"], 0)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["semantic_accuracy_measured"])
        self.assertFalse(result["human_review_completed"])
        self.assertFalse(result["source_text_included"])
        self.assertFalse((self.root / "novelgraph.sqlite").exists())
        self.assertNotIn("다음 달", json.dumps(result, ensure_ascii=False))

    def test_valid_continuity_fact_checked_without_db(self):
        fact = self.candidate(
            "상대가 거절해 계약서를 서명하지 않았다.",
            kind="continuity_fact",
            payload={"fact_type": "contract", "subject_id": "sola_proposal",
                     "field": "current_status", "value": "pending"},
        )
        result = self.run_cli([fact])
        self.assertEqual(result["continuity_fact_payloads_checked"], 1)
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_current_time_preflight_accepts_work_scoped_state_without_writing(self):
        quote = "현재 시각은 1893년 11월 5일이다."
        self.story += quote + "\n"
        self.source.write_text(self.story, encoding="utf-8")
        event = self.candidate(quote, kind="state_change", payload={
            "event_type": "state_set", "actor_id": "synthetic",
            "category": "time", "item_id": "current", "value": "1893-11-05",
        })
        result = self.run_cli([event])
        self.assertEqual(result["state_change_payloads_checked"], 1)
        self.assertTrue(result["read_only"])
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_invalid_continuity_status_is_rejected(self):
        fact = self.candidate(
            "상대가 거절해 계약서를 서명하지 않았다.",
            kind="continuity_fact",
            payload={"fact_type": "contract", "subject_id": "sola_proposal",
                     "field": "current_status", "value": "disputed"},
        )
        self.assertIn("unsupported contract current_status",
                      self.run_cli([fact], expected=2))
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_refused_contract_status_passes_schema_without_creating_state(self):
        fact = self.candidate(
            "상대가 거절해 계약서를 서명하지 않았다.",
            kind="continuity_fact",
            payload={"fact_type": "contract", "subject_id": "sola_proposal",
                     "field": "current_status", "value": "refused"},
        )
        result = self.run_cli([fact])
        self.assertEqual(result["continuity_fact_payloads_checked"], 1)
        self.assertFalse(result["semantic_accuracy_measured"])
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_paid_cash_event_schema_validated_without_applying(self):
        actual = self.candidate(
            "어제 회사가 자문료로 3만 달러를 이미 송금했다고 기록됐다.",
            kind="state_change",
            payload={"event_type": "cash_payment", "actor_id": "sola",
                     "currency": "USD", "amount": "30000",
                     "transaction_id": "sola-2026-payout-1"},
        )
        result = self.run_cli([actual])
        self.assertEqual(result["state_change_payloads_checked"], 1)
        self.assertEqual(result["kind_counts"]["state_change"], 1)
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_invalid_state_change_payload_rejected_before_storage(self):
        malformed = self.candidate(
            "어제 회사가 자문료로 3만 달러를 이미 송금했다고 기록됐다.",
            kind="state_change",
            payload={"event_type": "cash_payment", "actor_id": "sola",
                     "currency": "USD", "amount": "30000"},
        )
        self.assertIn("transaction_id", self.run_cli([malformed], expected=2))
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_future_effective_episode_rejected(self):
        future = self.candidate(
            "어제 회사가 자문료로 3만 달러를 이미 송금했다고 기록됐다.",
            kind="state_change",
            payload={"event_type": "cash_payment", "actor_id": "sola",
                     "currency": "USD", "amount": "30000",
                     "transaction_id": "sola-2026-payout-1",
                     "effective_episode": 2},
        )
        self.assertIn("effective_episode", self.run_cli([future], expected=2))

    def test_wrong_source_sha_fails_closed(self):
        candidate = self.candidate("서진은 2만 달러를 다음 달에 송금할 계획이다.")
        self.assertIn("source_sha256", self.run_cli([candidate], digest="0" * 64, expected=2))
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_modified_quote_fails_closed(self):
        candidate = self.candidate("서진은 2만 달러를 다음 달에 송금할 계획이다.")
        candidate["evidence"]["text"] = "당장 송금했다"
        self.assertIn("evidence does not match", self.run_cli([candidate], expected=2))

    def test_duplicate_proposals_are_not_inferred_as_two_transactions(self):
        cand = self.candidate("서진은 2만 달러를 다음 달에 송금할 계획이다.")
        report = self.run_cli([cand, cand])
        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(report["duplicate_candidate_entries"], 1)
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_dry_run_does_not_change_existing_database_bytes(self):
        db_path = self.root / "novelgraph.sqlite"
        with sqlite3.connect(db_path) as db:
            db.execute("CREATE TABLE sentinel(value TEXT)")
            db.execute("INSERT INTO sentinel VALUES('untouched')")
            db.commit()
        db_path.chmod(0o600)
        before = db_path.read_bytes()
        proposal = self.candidate("서진은 2만 달러를 다음 달에 송금할 계획이다.")
        self.run_cli([proposal])
        self.assertEqual(db_path.read_bytes(), before)

    def test_rejected_contract_in_story_is_not_semantically_certified(self):
        # A syntactically valid but untruthful interpretation MUST NOT score as verified.
        misleading = self.candidate(
            "상대가 거절해 계약서를 서명하지 않았다.",
            kind="event",
            payload={"event_type": "contract_signed", "actor_id": "seojin",
                     "target_id": "sola"},
        )
        output = self.run_cli([misleading])
        self.assertFalse(output["semantic_accuracy_measured"])
        self.assertEqual(output["state_change_payloads_checked"], 0)
        self.assertFalse((self.root / "novelgraph.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
