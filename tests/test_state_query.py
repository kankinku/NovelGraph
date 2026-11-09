"""Read-only, scope-exact current-state lookups over synthetic episodes."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class StateQueryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="novelgraph-query-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def cli(self, *args, expected=0):
        process = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root), *args],
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(process.returncode, expected, process.stderr + process.stdout)
        return json.loads(process.stdout) if expected == 0 else process.stderr

    def record(self, episode, passage, payload, *, apply=True):
        path = self.root / f"{episode}.txt"
        path.write_text(passage, encoding="utf-8")
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        candidates = self.root / "input.json"
        candidates.write_text(json.dumps({
            "schema_version": 1, "work_id": "fixture", "episode": episode,
            "source_sha256": source_hash, "candidates": [{
                "kind": "state_change", "payload": payload,
                "evidence": {"start": 0, "end": len(passage), "text": passage}
            }],
        }, ensure_ascii=False), encoding="utf-8")
        self.cli("import-candidates", "--source", str(path), "--input", str(candidates))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            cid = db.execute("SELECT candidate_id FROM candidates WHERE episode=?",
                             (episode,)).fetchone()[0]
        if apply:
            self.cli("review-candidate", "--source", str(path), "--candidate-id", cid,
                     "--decision", "approve", "--reviewer", "human",
                     "--reason", "verified evidence")
            self.cli("apply-approved", "--source", str(path), "--candidate-id", cid)
        return cid

    @staticmethod
    def change(category, item, value, *, actor="evelyn", **kw):
        return {"event_type": "state_set", "actor_id": actor, "category": category,
                "item_id": item, "value": value, **kw}

    def query(self, scope, *, episode=7, subject="evelyn", history=False):
        args = ["query-state", "--work-id", "fixture", "--episode", str(episode),
                "--subject", subject, "--scope", scope]
        if history:
            args.append("--history")
        return self.cli(*args)

    def fixture(self):
        self.record(1, "현금 2000달러를 보유했다.", {
            "event_type": "cash_opening", "actor_id": "evelyn",
            "currency": "USD", "amount": "2000"})
        self.record(2, "주식 평가액은 3000달러다.",
                    self.change("stock", "company-a", "3000", unit="USD"))
        self.record(3, "대출 잔액은 500달러다.",
                    self.change("liability", "loan-a", "-500", unit="USD"))
        self.record(4, "채권 수량은 100개다.",
                    self.change("bond", "bond-a", "100", unit="shares"))
        self.record(5, "프랭클린과 친구가 되었다.",
                    self.change("relationship", "franklin", "friend",
                                relation_status="active"))
        self.record(6, "1893년 11월 5일이 되었다.",
                    self.change("time", "current", "1893-11-05", actor="fixture"))
        self.record(7, "주식 평가액이 3200달러로 변경되었다.",
                    self.change("stock", "company-a", "3200", unit="USD"))

    def test_asset_scope_returns_all_current_asset_children_without_history(self):
        self.fixture()
        result = self.query("assets")
        self.assertEqual(result["data"]["cash"]["USD"]["value"], "2000")
        self.assertEqual(result["data"]["stock"]["company-a"]["value"], "3200")
        self.assertEqual(result["data"]["bond"]["bond-a"]["unit"], "shares")
        self.assertNotIn("liability", result["data"])
        self.assertNotIn("relationship", result["data"])
        self.assertNotIn("history", result)
        self.assertEqual(result["totals"]["valued_assets_by_currency"]["USD"], "5200")
        self.assertTrue(result["totals"]["has_unpriced_holdings"])
        self.assertEqual(result["data"]["stock"]["company-a"]["source_episode"], 7)

    def test_explicit_scope_and_history_only_when_requested(self):
        self.fixture()
        stock = self.query("stock")
        self.assertEqual(list(stock["data"]), ["stock"])
        self.assertEqual(stock["data"]["stock"]["company-a"]["value"], "3200")
        self.assertNotIn("history", stock)
        with_history = self.query("stock", history=True)
        self.assertEqual([item["value"] for item in with_history["history"]],
                         ["3000", "3200"])
        self.assertEqual(with_history["history"][0]["source_episode"], 2)
        liquid = self.query("liquid_assets")
        self.assertEqual(list(liquid["data"]), ["cash"])
        relationships = self.query("relationships")
        self.assertEqual(relationships["data"]["relationship"]["franklin"]["value"],
                         "friend")
        self.assertEqual(self.query("time")["data"]["time"]["value"], "1893-11-05")

    def test_liabilities_are_separate_from_gross_and_net_uses_signed_values(self):
        self.fixture()
        debt = self.query("liabilities")
        self.assertEqual(debt["data"]["liability"]["loan-a"]["value"], "-500")
        net = self.query("net_assets")
        self.assertEqual(net["totals"]["valued_assets_by_currency"]["USD"], "5200")
        self.assertEqual(net["totals"]["liabilities_by_currency"]["USD"], "-500")
        self.assertEqual(net["totals"]["net_valued_by_currency"]["USD"], "4700")
        self.assertTrue(net["totals"]["has_unpriced_holdings"])

    def test_cash_history_distinguishes_opening_and_outgoing_payment(self):
        self.record(1, "계좌의 현금은 2000달러다.", {
            "event_type": "cash_opening", "actor_id": "evelyn",
            "currency": "USD", "amount": "2000"})
        self.record(2, "500달러를 실제 지급했다.", {
            "event_type": "cash_payment", "actor_id": "evelyn",
            "currency": "USD", "amount": "500", "transaction_id": "tx-01"})
        current = self.query("cash", episode=2)
        self.assertEqual(current["data"]["cash"]["USD"]["value"], "1500")
        details = self.query("cash", episode=2, history=True)["history"]
        self.assertEqual([(x["event_type"], x["value"]) for x in details],
                         [("cash_opening", "2000"), ("cash_payment", "-500")])

    def test_corrupt_candidate_evidence_blocks_read_only_query(self):
        self.record(1, "계좌의 현금은 2000달러다.", {
            "event_type": "cash_opening", "actor_id": "evelyn",
            "currency": "USD", "amount": "2000"})
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            db.execute("UPDATE candidates SET evidence_text='X' || evidence_text")
        failure = self.cli(
            "query-state", "--work-id", "fixture", "--episode", "1",
            "--subject", "evelyn", "--scope", "cash", expected=2)
        self.assertIn("integrity", failure.lower())

    def test_unapplied_candidates_are_excluded_and_query_is_read_only(self):
        self.record(1, "현금은 2000달러다.", {
            "event_type": "cash_opening", "actor_id": "evelyn",
            "currency": "USD", "amount": "2000"})
        self.record(2, "소문에 따르면 친구가 되었다.",
                    self.change("relationship", "franklin", "friend",
                                relation_status="active"), apply=False)
        path = self.root / "novelgraph.sqlite"
        before = path.read_bytes()
        self.assertEqual(self.query("relationships", episode=2)["data"], {})
        self.assertEqual(self.query("cash", episode=2)["data"]["cash"]["USD"]["value"],
                         "2000")
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("unsupported", self.cli(
            "query-state", "--work-id", "fixture", "--episode", "2",
            "--subject", "evelyn", "--scope", "random", expected=2).lower())

    def test_ownership_and_contracts_include_source_provenance(self):
        self.fixture()
        self.record(8, "오로라 지분 15퍼센트 계약에 서명했다.", {
            "event_type": "contract_signed", "actor_id": "evelyn",
            "contract_id": "deal-a", "company_id": "aurora",
            "equity_pct": "15"})
        cid = self.record(9, "오로라 지분이 공식 이전됐다.", {
            "event_type": "equity_transfer", "actor_id": "evelyn",
            "contract_id": "deal-a"})
        ownership = self.query("ownership", episode=9)
        item = ownership["data"]["ownership_pct"]["aurora"]
        self.assertEqual(item["value"], "15")
        self.assertEqual(item["unit"], "percent")
        self.assertEqual(item["source_episode"], 9)
        self.assertEqual(item["candidate_id"], cid)
        contracts = self.query("contracts", episode=9)
        deal = contracts["data"]["contracts"]["deal-a"]
        self.assertEqual(deal["status"], "transferred")
        self.assertEqual(deal["candidate_id"], cid)
