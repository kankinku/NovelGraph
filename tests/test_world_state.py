"""[5/9] End-to-end synthetic tests for explicit reviews and historical state.

All files and databases live in temporary private directories. No API calls.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class WorldStateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="novelgraph-world-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.sources = {}

    def cli(self, *args, expected=0):
        run = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root), *args],
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(run.returncode, expected, run.stderr + run.stdout)
        return json.loads(run.stdout) if expected == 0 else run.stderr

    def stage(self, episode, story, payload, *, kind="state_change"):
        path = self.root / f"episode-{episode:03d}.txt"
        if path.exists():
            self.assertEqual(path.read_text(encoding="utf-8"), story)
        else:
            path.write_text(story, encoding="utf-8")
        candidate_file = self.root / "candidates.json"
        evidence = story.rstrip("\n")
        body = {
            "schema_version": 1, "work_id": "fixture", "episode": episode,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "candidates": [
                {"kind": kind, "payload": payload,
                 "evidence": {"start": 0, "end": len(evidence), "text": evidence}}
            ]
        }
        candidate_file.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        self.cli("import-candidates", "--source", str(path),
                 "--input", str(candidate_file))
        db = sqlite3.connect(self.root / "novelgraph.sqlite")
        try:
            candidate_id = db.execute(
                "SELECT candidate_id FROM candidates WHERE work_id='fixture' AND episode=? "
                "ORDER BY rowid DESC LIMIT 1", (episode,)
            ).fetchone()[0]
        finally:
            db.close()
        self.sources[candidate_id] = path
        return candidate_id

    def review(self, candidate_id, decision="approve", *, expected=0):
        return self.cli(
            "review-candidate", "--source", str(self.sources[candidate_id]),
            "--candidate-id", candidate_id, "--decision", decision,
            "--reviewer", "human-reviewer", "--reason", "checked source evidence",
            expected=expected
        )

    def apply(self, candidate_id, *, expected=0):
        return self.cli(
            "apply-approved", "--source", str(self.sources[candidate_id]),
            "--candidate-id", candidate_id, expected=expected
        )

    def state(self, episode):
        return self.cli("world-state", "--work-id", "fixture",
                        "--episode", str(episode))

    @staticmethod
    def opening(amount="100000"):
        return {"event_type": "cash_opening", "actor_id": "evelyn",
                "currency": "USD", "amount": amount}

    @staticmethod
    def sign():
        return {"event_type": "contract_signed", "actor_id": "evelyn",
                "contract_id": "aurora-15", "company_id": "aurora",
                "equity_pct": "15"}

    @staticmethod
    def payment(transaction_id="transfer-001", amount="25000"):
        return {"event_type": "cash_payment", "actor_id": "evelyn",
                "currency": "USD", "amount": amount,
                "transaction_id": transaction_id, "contract_id": "aurora-15"}

    def approved_event(self, episode, story, payload):
        cid = self.stage(episode, story, payload)
        self.review(cid)
        self.apply(cid)
        return cid

    def test_list_candidates_exposes_ids_not_private_excerpts(self):
        cid = self.stage(1, "계약서에 서명했다.\n", self.sign())
        listing = self.cli("list-candidates", "--work-id", "fixture", "--episode", "1")
        self.assertEqual(len(listing["candidates"]), 1)
        self.assertEqual(listing["candidates"][0]["candidate_id"], cid)
        self.assertEqual(listing["candidates"][0]["status"], "proposed")
        self.assertNotIn("계약서에 서명했다.", json.dumps(listing, ensure_ascii=False))

    def test_explicit_review_required_and_audited(self):
        cid = self.stage(1, "현금은 100000달러였다.\n", self.opening())
        self.assertIn("explicit approval", self.apply(cid, expected=2))
        s = self.state(1)
        self.assertEqual(s["event_count"], 0)
        answer = self.review(cid)
        self.assertEqual(answer["decision"], "approved")
        self.assertFalse(answer["applied"])
        self.assertIn("already been reviewed", self.review(cid, expected=2))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM review_log").fetchone()[0], 1)
        self.assertEqual(self.state(1)["event_count"], 0)
        self.apply(cid)
        self.assertEqual(self.state(1)["event_count"], 1)

    def test_rejected_and_non_state_candidate_cannot_change_state(self):
        reject = self.stage(1, "돈의 용도를 검토했다.\n",
                            {"kind": "investment_plan"}, kind="entity")
        self.review(reject, "reject")
        self.assertIn("state_change", self.apply(reject, expected=2))
        self.assertEqual(self.state(1)["event_count"], 0)

    def test_contract_payment_equity_are_distinct_point_in_time(self):
        self.approved_event(1, "현금 100000달러 보유.\n", self.opening())
        self.approved_event(2, "오로라 지분 15% 계약 서명.\n", self.sign())
        self.approved_event(3, "오로라 계약 대금 25000달러 송금.\n", self.payment())
        self.approved_event(4, "오로라 지분 15%가 정식 이전.\n",
                            {"event_type": "equity_transfer", "actor_id": "evelyn",
                             "contract_id": "aurora-15"})
        a, b, c, d = [self.state(i) for i in range(1, 5)]
        self.assertEqual(a["cash"]["evelyn"]["USD"], "100000")
        self.assertEqual(b["cash"]["evelyn"]["USD"], "100000")
        self.assertEqual(b["contracts"]["aurora-15"]["status"], "signed")
        self.assertEqual(b["ownership"], {})
        self.assertEqual(c["cash"]["evelyn"]["USD"], "75000")
        self.assertEqual(c["ownership"], {})
        self.assertEqual(d["ownership"]["evelyn"]["aurora"], "15")
        self.assertEqual(d["contracts"]["aurora-15"]["status"], "transferred")
        self.assertIsNone(d["total_assets"])
        self.assertEqual([x["event_count"] for x in (a, b, c, d)], [1, 2, 3, 4])

    def test_delegate_signature_preserves_economic_holder_during_payment_and_transfer(self):
        opening = {"event_type": "cash_opening", "actor_id": "child_trust",
                   "currency": "USD", "amount": "100000"}
        self.approved_event(1, "미성년자 신탁 장부의 현금은 10만 달러.\n", opening)
        signature = {"event_type": "contract_signed", "actor_id": "child_trust",
                     "signer_id": "grandfather_guardian",
                     "contract_id": "coca_cola_1891", "company_id": "coca_cola",
                     "equity_pct": "15"}
        self.approved_event(2, "조부가 신탁을 대신해 15% 지분 계약에 서명했다.\n",
                            signature)
        self.approved_event(3, "신탁이 대금 25000달러를 지급했다.\n", {
            "event_type": "cash_payment", "actor_id": "child_trust",
            "currency": "USD", "amount": "25000",
            "transaction_id": "coca_1892_payment", "contract_id": "coca_cola_1891",
        })
        self.approved_event(4, "신탁으로 지분 15%가 이전됐다.\n", {
            "event_type": "equity_transfer", "actor_id": "child_trust",
            "contract_id": "coca_cola_1891",
        })
        before = self.state(2)
        after = self.state(4)
        self.assertEqual(before["contracts"]["coca_cola_1891"]["signer_id"],
                         "grandfather_guardian")
        self.assertEqual(before["cash"]["child_trust"]["USD"], "100000")
        self.assertEqual(before["ownership"], {})
        self.assertEqual(after["cash"]["child_trust"]["USD"], "75000")
        self.assertEqual(after["ownership"]["child_trust"]["coca_cola"], "15")
        self.assertEqual(after["contracts"]["coca_cola_1891"]["actor_id"], "child_trust")
        self.assertEqual(after["event_count"], 4)
        self.assertIsNone(after["total_assets"])

    def test_invalid_delegate_signer_id_is_rejected(self):
        payload = {"event_type": "contract_signed", "actor_id": "child_trust",
                   "signer_id": "invalid signer with spaces",
                   "contract_id": "coca_cola_1891", "company_id": "coca_cola",
                   "equity_pct": "15"}
        cid = self.stage(1, "가상의 계약 초안.\n", payload)
        self.assertIn("signer_id", self.review(cid, expected=2))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(db.execute("select status from candidates where candidate_id=?",
                                        (cid,)).fetchone()[0], "proposed")

    def test_world_state_rejects_applied_event_payload_drift(self):
        cid = self.approved_event(1, "초기 현금 100000달러.\n", self.opening())
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            stored = json.loads(db.execute(
                "SELECT payload_json FROM applied_events WHERE candidate_id=?",
                (cid,),
            ).fetchone()[0])
            stored["amount"] = "900000"
            db.execute(
                "UPDATE applied_events SET payload_json=? WHERE candidate_id=?",
                (json.dumps(stored, sort_keys=True, separators=(",", ":")), cid),
            )
        self.assertIn(
            "applied event does not match approved candidate",
            self.cli("world-state", "--work-id", "fixture", "--episode", "1",
                     expected=2),
        )

    def test_world_state_rejects_applied_event_metadata_drift(self):
        cid = self.approved_event(1, "초기 현금 100000달러.\n", self.opening())
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            db.execute(
                "UPDATE applied_events SET event_key='balance:other:USD' "
                "WHERE candidate_id=?", (cid,),
            )
        self.assertIn(
            "applied event does not match approved candidate",
            self.cli("world-state", "--work-id", "fixture", "--episode", "1",
                     expected=2),
        )

    def test_idempotent_apply_and_duplicate_transaction_id_rejected(self):
        self.approved_event(1, "초기자금 100000달러.\n", self.opening())
        self.approved_event(2, "지분 계약 서명.\n", self.sign())
        cid = self.approved_event(3, "25000달러 지급.\n", self.payment())
        self.assertTrue(self.apply(cid)["already_applied"])
        duplicate = self.stage(4, "같은 송금 사실 재언급.\n", self.payment())
        self.review(duplicate)
        self.assertIn("event key already used", self.apply(duplicate, expected=2))
        self.assertEqual(self.state(4)["cash"]["evelyn"]["USD"], "75000")
        self.assertEqual(self.state(4)["event_count"], 3)

    def test_invalid_payment_and_known_overdraft_roll_back(self):
        self.approved_event(1, "현금 100달러.\n", self.opening("100"))
        self.approved_event(2, "계약 서명.\n", self.sign())
        cid = self.stage(3, "대금 200달러 지급.\n", self.payment(amount="200"))
        self.review(cid)
        self.assertIn("cannot become negative", self.apply(cid, expected=2))
        self.assertEqual(self.state(3)["cash"]["evelyn"]["USD"], "100")
        self.assertEqual(self.state(3)["event_count"], 2)

    def test_invalid_amount_prevents_approval(self):
        bad = self.stage(1, "이상한 금액.\n", self.opening("2e5"))
        self.assertIn("decimal string", self.review(bad, expected=2))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(db.execute("SELECT status FROM candidates WHERE candidate_id=?",
                                        (bad,)).fetchone()[0], "proposed")

    def test_transfer_requires_matching_signed_contract(self):
        cid = self.stage(1, "권리 이전 주장.\n",
                         {"event_type": "equity_transfer", "actor_id": "evelyn",
                          "contract_id": "missing"})
        self.review(cid)
        self.assertIn("requires matching signed contract", self.apply(cid, expected=2))
        self.assertEqual(self.state(1)["event_count"], 0)

    def test_unknown_opening_balance_is_not_invented(self):
        cid = self.stage(1, "500달러 수령.\n",
                         {"event_type": "cash_receipt", "actor_id": "evelyn",
                          "currency": "USD", "amount": "500",
                          "transaction_id": "income-1"})
        self.review(cid)
        self.apply(cid)
        state = self.state(1)
        self.assertIsNone(state["cash"]["evelyn"]["USD"])
        self.assertEqual(state["cash_movement"]["evelyn"]["USD"], "500")
        self.assertIsNone(state["total_assets"])

    def test_retroactive_discovery_preserves_earlier_known_state(self):
        self.approved_event(1, "초기자금 100000달러.\n", self.opening())
        early = self.state(3)
        event = {"event_type": "cash_receipt", "actor_id": "evelyn",
                 "currency": "USD", "amount": "1000",
                 "transaction_id": "late-report", "effective_episode": 2}
        self.approved_event(5, "2화에 받은 돈이 뒤늦게 밝혀졌다.\n", event)
        self.assertEqual(self.state(3), early)
        self.assertEqual(self.state(5)["cash"]["evelyn"]["USD"], "101000")

    def test_model_assessment_cannot_approve_or_apply(self):
        cid = self.stage(1, "계약서 서명 가능성만 검토했다.\n", self.sign())
        self.assertIn("explicit approval", self.apply(cid, expected=2))
        result = self.cli(
            "assess-candidate", "--source", str(self.sources[cid]),
            "--candidate-id", cid, "--assessment", "supports",
            "--model-label", "synthetic_model", "--reason", "tentative model interpretation"
        )
        self.assertEqual(result["assessment"], "supports")
        self.assertFalse(result["official_status_changed"])
        self.assertFalse(result["authenticated_human_approval"])
        self.assertIn("explicit approval", self.apply(cid, expected=2))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(
                db.execute("SELECT status FROM candidates WHERE candidate_id=?", (cid,)).fetchone()[0],
                "proposed"
            )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM model_assessments").fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='review_log'"
            ).fetchone()[0], 0)
        self.assertEqual(self.state(1)["event_count"], 0)

    def test_model_assessment_and_official_review_are_distinct(self):
        cid = self.stage(1, "현금 100000달러.\n", self.opening())
        self.cli("assess-candidate", "--source", str(self.sources[cid]),
                 "--candidate-id", cid, "--assessment", "needs_review",
                 "--model-label", "synthetic_model", "--reason", "verify actual cash")
        listing = self.cli("review-audit", "--work-id", "fixture", "--episode", "1")
        self.assertEqual(listing["model_assessments"], 1)
        self.assertEqual(listing["official_approved"], 0)
        self.assertEqual(listing["official_proposed"], 1)
        self.assertFalse(listing["human_identity_authenticated"])
        self.review(cid)
        audit = self.cli("review-audit", "--work-id", "fixture", "--episode", "1")
        self.assertEqual(audit["model_assessments"], 1)
        self.assertEqual(audit["official_approved"], 1)
        self.assertEqual(audit["approved_with_review_log"], 1)
        self.assertEqual(audit["approved_missing_review_log"], [])
        self.assertFalse(audit["human_identity_authenticated"])
        self.assertEqual(self.state(1)["event_count"], 0)
        self.apply(cid)
        self.assertEqual(self.state(1)["event_count"], 1)

    def test_forged_approved_status_without_review_log_cannot_apply(self):
        cid = self.stage(1, "100000달러 현금이 있다.\n", self.opening())
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            db.execute("UPDATE candidates SET status='approved' WHERE candidate_id=?", (cid,))
        warning = self.cli("review-audit", "--work-id", "fixture", "--episode", "1")
        self.assertEqual(warning["approved_missing_review_log"], [cid])
        self.assertIn("approved review log", self.apply(cid, expected=2))
        self.assertEqual(self.state(1)["event_count"], 0)

    def test_model_assessment_bad_source_fails_without_logging(self):
        cid = self.stage(1, "현금 100000달러.\n", self.opening())
        self.sources[cid].write_text("현금 900000달러.\n", encoding="utf-8")
        problem = self.cli(
            "assess-candidate", "--source", str(self.sources[cid]),
            "--candidate-id", cid, "--assessment", "supports",
            "--model-label", "synthetic_model", "--reason", "should reject wrong SHA",
            expected=2,
        )
        self.assertIn("source hash differs", problem)
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='model_assessments'"
            ).fetchone()[0], 0)

    def test_model_assessment_invalid_verdict_rejected(self):
        cid = self.stage(1, "현금 100000달러.\n", self.opening())
        bad = self.cli(
            "assess-candidate", "--source", str(self.sources[cid]),
            "--candidate-id", cid, "--assessment", "approve",
            "--model-label", "synthetic_model", "--reason", "model tries to approve",
            expected=2,
        )
        self.assertIn("invalid choice", bad)
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(
                db.execute("SELECT status FROM candidates WHERE candidate_id=?", (cid,)).fetchone()[0],
                "proposed"
            )

    def test_model_assessment_cannot_change_rejected_candidate(self):
        cid = self.stage(1, "현금 100000달러.\n", self.opening())
        self.review(cid, "reject")
        problem = self.cli(
            "assess-candidate", "--source", str(self.sources[cid]),
            "--candidate-id", cid, "--assessment", "supports",
            "--model-label", "synthetic_model", "--reason", "too late",
            expected=2,
        )
        self.assertIn("proposed", problem)
        self.assertEqual(self.state(1)["event_count"], 0)

    def test_stored_candidate_payload_tampering_rejected_before_review(self):
        cid = self.stage(1, "현금은 100000달러였다.\n", self.opening())
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            payload = dict(self.opening(), amount="900000")
            db.execute("UPDATE candidates SET payload_json=? WHERE candidate_id=?",
                       (json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                   separators=(",", ":")), cid))
        self.assertIn("integrity hash mismatch", self.review(cid, expected=2))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(
                db.execute("SELECT status FROM candidates WHERE candidate_id=?",
                           (cid,)).fetchone()[0], "proposed"
            )

    def test_source_modification_blocks_review_or_apply(self):
        cid = self.stage(1, "현금 100000달러.\n", self.opening())
        self.sources[cid].write_text("현금 200000달러.\n", encoding="utf-8")
        self.assertIn("source hash differs", self.review(cid, expected=2))
        self.sources[cid].write_text("현금 100000달러.\n", encoding="utf-8")
        self.review(cid)
        self.sources[cid].write_text("현금 200000달러.\n", encoding="utf-8")
        self.assertIn("source hash differs", self.apply(cid, expected=2))
        self.assertEqual(self.state(1)["event_count"], 0)


if __name__ == "__main__":
    unittest.main()
