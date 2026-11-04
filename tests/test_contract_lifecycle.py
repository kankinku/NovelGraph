"""Stage-06 synthetic contract lifecycle regression tests.

No private manuscripts and no user approvals are touched. All authorization
in these tests is a synthetic fixture, not proof of a human identity.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class ContractLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="novelgraph-contract-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        self.sources = {}

    def cli(self, *args, expected=0):
        proc = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root), *args],
            capture_output=True, text=True, timeout=25,
        )
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        return json.loads(proc.stdout) if expected == 0 else proc.stderr

    def stage(self, episode, story, payload):
        src = self.root / f"{episode:03}.txt"
        src.write_text(story, encoding="utf-8")
        draft = self.root / "candidates.json"
        draft.write_text(json.dumps({
            "schema_version": 1, "work_id": "synthetic", "episode": episode,
            "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
            "candidates": [{
                "kind": "state_change", "payload": payload,
                "evidence": {"start": 0, "end": len(story),
                             "text": story},
            }],
        }, ensure_ascii=False), encoding="utf-8")
        self.cli("import-candidates", "--source", str(src),
                 "--input", str(draft))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            candidate_id = db.execute(
                "SELECT candidate_id FROM candidates WHERE work_id=? AND episode=? "
                "ORDER BY rowid DESC LIMIT 1", ("synthetic", episode),
            ).fetchone()[0]
        self.sources[candidate_id] = src
        return candidate_id

    def review(self, cid, *, expected=0):
        return self.cli("review-candidate", "--source", str(self.sources[cid]),
                        "--candidate-id", cid, "--decision", "approve",
                        "--reviewer", "synthetic-reviewer",
                        "--reason", "synthetic scenario checked", expected=expected)

    def apply(self, cid, *, expected=0):
        return self.cli("apply-approved", "--source", str(self.sources[cid]),
                        "--candidate-id", cid, expected=expected)

    def confirmed(self, episode, story, payload):
        cid = self.stage(episode, story, payload)
        self.review(cid)
        self.apply(cid)
        return cid

    def world(self, episode):
        return self.cli("world-state", "--work-id", "synthetic",
                        "--episode", str(episode))

    @staticmethod
    def proposal(**updates):
        return {
            "event_type": "contract_proposed",
            "actor_id": "investor",
            "contract_id": "agreement-001",
            "company_id": "alpha",
            **updates,
        }

    @staticmethod
    def refusal(**updates):
        return {
            "event_type": "contract_refused",
            "actor_id": "investor",
            "contract_id": "agreement-001",
            **updates,
        }

    @staticmethod
    def signing(**updates):
        return {
            "event_type": "contract_signed",
            "actor_id": "investor",
            "contract_id": "agreement-001",
            "company_id": "alpha",
            "equity_pct": "15",
            **updates,
        }

    @staticmethod
    def payment(**updates):
        return {
            "event_type": "cash_payment",
            "actor_id": "investor",
            "currency": "USD",
            "amount": "25000",
            "transaction_id": "cash-001",
            "contract_id": "agreement-001",
            **updates,
        }

    def test_proposal_then_refusal_are_distinct_from_signed_or_paid(self):
        self.confirmed(1, "투자 제안을 했다.\n", self.proposal())
        proposed = self.world(1)
        self.assertEqual(proposed["contracts"]["agreement-001"]["status"], "proposed")
        self.assertEqual(proposed["cash"], {})
        self.assertEqual(proposed["ownership"], {})
        self.assertIsNone(proposed["total_assets"])
        self.confirmed(2, "투자 제안을 거절했다.\n", self.refusal())
        refused = self.world(2)
        self.assertEqual(refused["contracts"]["agreement-001"]["status"], "refused")
        self.assertEqual(refused["event_count"], 2)
        self.assertEqual(refused["cash"], {})
        self.assertEqual(refused["ownership"], {})
        self.assertIsNone(refused["total_assets"])
        self.assertEqual(self.world(1), proposed)

    def test_payment_against_only_proposed_contract_is_rejected(self):
        self.confirmed(1, "투자 제안이 도착했다.\n", self.proposal())
        cid = self.stage(2, "계약을 체결하기 전에 지급한다는 잘못된 후보.\n",
                         self.payment())
        self.review(cid)
        self.assertIn("signed contract", self.apply(cid, expected=2))
        self.assertEqual(self.world(2)["event_count"], 1)
        self.assertEqual(self.world(2)["cash"], {})
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM applied_events").fetchone()[0], 1)

    def test_refusal_without_a_proposal_is_rejected_atomically(self):
        cid = self.stage(1, "지나간 제안을 거절했다고 주장했다.\n", self.refusal())
        self.review(cid)
        self.assertIn("requires matching proposal", self.apply(cid, expected=2))
        self.assertEqual(self.world(1)["contracts"], {})
        self.assertEqual(self.world(1)["event_count"], 0)

    def test_signing_after_refusal_is_rejected_atomically(self):
        self.confirmed(1, "첫 번째 투자 제안.\n", self.proposal())
        self.confirmed(2, "그 투자 제안을 거절했다.\n", self.refusal())
        cid = self.stage(3, "동일한 거절 제안에 뒤늦게 서명했다고 잘못 주장했다.\n",
                         self.signing())
        self.review(cid)
        self.assertIn("refused contract", self.apply(cid, expected=2))
        self.assertEqual(self.world(3)["contracts"]["agreement-001"]["status"], "refused")
        self.assertEqual(self.world(3)["event_count"], 2)

    def test_matching_proposal_signing_payment_transfer_are_separate(self):
        self.confirmed(1, "초기 현금 100000달러.\n",
                       {"event_type": "cash_opening", "actor_id": "investor",
                        "currency": "USD", "amount": "100000"})
        self.confirmed(2, "지분 매수 제안을 제출했다.\n", self.proposal())
        self.assertEqual(self.world(2)["cash"]["investor"]["USD"], "100000")
        self.assertEqual(self.world(2)["ownership"], {})
        self.confirmed(3, "제안을 수락해 지분 15% 계약서에 서명했다.\n",
                       self.signing())
        self.assertEqual(self.world(3)["contracts"]["agreement-001"]["status"], "signed")
        self.assertEqual(self.world(3)["ownership"], {})
        self.assertEqual(self.world(3)["cash"]["investor"]["USD"], "100000")
        self.confirmed(4, "계약 대금 25000달러를 실제로 송금했다.\n", self.payment())
        self.assertEqual(self.world(4)["cash"]["investor"]["USD"], "75000")
        self.assertEqual(self.world(4)["ownership"], {})
        self.confirmed(5, "지분 15%가 정식 이전됐다.\n", {
            "event_type": "equity_transfer", "actor_id": "investor",
            "contract_id": "agreement-001",
        })
        final = self.world(5)
        self.assertEqual(final["ownership"]["investor"]["alpha"], "15")
        self.assertEqual(final["contracts"]["agreement-001"]["status"], "transferred")
        self.assertIsNone(final["total_assets"])
        self.assertEqual([self.world(n)["event_count"] for n in range(1, 6)],
                         [1, 2, 3, 4, 5])

    def test_proposal_signing_must_match_actor_and_target_company(self):
        self.confirmed(1, "투자자가 알파사 지분 계약을 제안했다.\n", self.proposal())
        incorrect = self.stage(2, "다른 회사 계약으로 서명하려 했다.\n",
                               self.signing(company_id="beta"))
        self.review(incorrect)
        self.assertIn("proposal company", self.apply(incorrect, expected=2))
        self.assertEqual(self.world(2)["contracts"]["agreement-001"]["status"],
                         "proposed")
        other = self.stage(3, "다른 사람 명의로 같은 제안에 서명하려 했다.\n",
                           self.signing(actor_id="other"))
        self.review(other)
        self.assertIn("proposal actor", self.apply(other, expected=2))
        self.assertEqual(self.world(3)["event_count"], 1)

    def test_same_proposal_repeated_with_same_contract_id_not_applied_twice(self):
        self.confirmed(1, "첫 투자 제안을 했다.\n", self.proposal())
        duplicate = self.stage(2, "같은 투자 제안을 다시 언급했다.\n",
                               self.proposal())
        self.review(duplicate)
        self.assertIn("event key already used", self.apply(duplicate, expected=2))
        self.assertEqual(self.world(2)["event_count"], 1)

    def test_proposal_without_target_company_cannot_be_approved(self):
        invalid = self.stage(1, "대상 회사가 없는 제안 주장.\n", {
            "event_type": "contract_proposed",
            "actor_id": "investor", "contract_id": "agreement-001",
        })
        self.assertIn("company_id", self.review(invalid, expected=2))
        self.assertEqual(self.world(1)["event_count"], 0)

    def test_investment_income_does_not_fabricate_total_asset_value(self):
        self.confirmed(1, "계약서 서명으로 주식 매수 계약이 성립했다.\n",
                       self.signing())
        self.confirmed(2, "지분이 투자자에게 이전됐다.\n", {
            "event_type": "equity_transfer", "actor_id": "investor",
            "contract_id": "agreement-001",
        })
        self.confirmed(3, "별도의 배당금 125.25달러를 받았다.\n", {
            "event_type": "cash_receipt", "actor_id": "investor",
            "currency": "USD", "amount": "125.25",
            "transaction_id": "dividend-001",
        })
        final = self.world(3)
        self.assertIsNone(final["cash"]["investor"]["USD"])
        self.assertEqual(final["cash_movement"]["investor"]["USD"], "125.25")
        self.assertEqual(final["ownership"]["investor"]["alpha"], "15")
        self.assertIsNone(final["total_assets"])


if __name__ == "__main__":
    unittest.main()
