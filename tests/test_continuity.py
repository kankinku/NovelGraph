"""[6/9] Synthetic provenance-linked narrative continuity regression tests."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="novelgraph-continuity-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.documents = {}

    def cli(self, *args, expected=0):
        command = [sys.executable, "-m", "novelgraph", "--data-root",
                   str(self.root), *args]
        result = subprocess.run(command, capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, expected,
                         f"{command}\n{result.stderr}\n{result.stdout}")
        return json.loads(result.stdout) if expected == 0 else result.stderr

    def stage(self, episode, story, payload, *, kind="continuity_fact",
              approved=True):
        path = self.root / f"{episode:03d}.txt"
        if path.exists():
            self.assertEqual(path.read_text(encoding="utf-8"), story)
        else:
            path.write_text(story, encoding="utf-8")
        body = {
            "schema_version": 1, "work_id": "novel",
            "episode": episode,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "candidates": [
                {"kind": kind, "payload": payload,
                 "evidence": {"start": 0, "end": len(story.rstrip("\n")),
                              "text": story.rstrip("\n")}}
            ],
        }
        candidate_file = self.root / "candidate-batch.json"
        candidate_file.write_text(json.dumps(body, ensure_ascii=False),
                                  encoding="utf-8")
        self.cli("import-candidates", "--source", str(path),
                 "--input", str(candidate_file))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"))
            row = db.execute(
                "SELECT candidate_id FROM candidates "
                "WHERE work_id=? AND episode=? AND payload_json=?",
                ("novel", episode, payload_json)
            ).fetchone()
            self.assertIsNotNone(row)
            candidate_id = row[0]
        self.documents[candidate_id] = path
        if approved:
            self.review(candidate_id)
        return candidate_id

    def review(self, candidate_id, *, expected=0):
        return self.cli(
            "review-candidate", "--source", str(self.documents[candidate_id]),
            "--candidate-id", candidate_id, "--decision", "approve",
            "--reviewer", "human", "--reason", "synthetic source checked",
            expected=expected
        )

    def fact(self, episode, story, kind, subject, field, value,
             *, effective_episode=None, certainty="confirmed", currency=None,
             context_id=None, approved=True):
        payload = {"fact_type": kind, "subject_id": subject,
                   "field": field, "value": value}
        if effective_episode is not None:
            payload["effective_episode"] = effective_episode
        if certainty != "confirmed":
            payload["certainty"] = certainty
        if context_id is not None:
            payload["context_id"] = context_id
        if currency is not None:
            payload["currency"] = currency
        return self.stage(episode, story, payload, approved=approved)

    def change(self, episode, story, subject, field, before, after,
               *, reason="amended", currency=None):
        payload = {"fact_type": "change", "subject_id": subject, "field": field,
                   "from_value": before, "to_value": after,
                   "reason_code": reason}
        if currency is not None:
            payload["currency"] = currency
        return self.stage(episode, story, payload)

    def check(self, episode):
        return self.cli("check-continuity", "--work-id", "novel",
                        "--episode", str(episode))

    def test_forged_approved_continuity_without_review_log_is_rejected(self):
        cid = self.fact(1, "가상의 모임은 월요일이었다.\n", "time",
                        "meeting:forged", "weekday", "monday", approved=False)
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            db.execute("UPDATE candidates SET status='approved' WHERE candidate_id=?", (cid,))
        self.assertIn("approved review log", self.cli(
            "check-continuity", "--work-id", "novel", "--episode", "1", expected=2))

    def test_contract_proposal_ledger_evidence_exposes_wrong_signed_claim(self):
        proposal = self.stage(1, "투자 계약을 제안했다.\n", {
            "event_type": "contract_proposed", "actor_id": "investor",
            "contract_id": "proposal:alpha", "company_id": "alpha",
        }, kind="state_change")
        self.cli("apply-approved", "--source", str(self.documents[proposal]),
                 "--candidate-id", proposal)
        false_signed = self.fact(
            2, "아직 제안인데 이미 서명했다고 잘못 주장했다.\n",
            "contract", "proposal:alpha", "current_status", "signed",
            effective_episode=1,
        )
        out = self.check(2)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 1)
        finding = out["findings"][0]
        self.assertEqual(finding["reason_code"], "CONTRACT_LEDGER_STATUS_MISMATCH")
        self.assertEqual(finding["ledger_status"], "proposed")
        self.assertEqual({x["candidate_id"] for x in finding["evidence"]},
                         {proposal, false_signed})

    def test_contract_refused_fact_is_valid_and_matches_ledger(self):
        proposed = self.stage(1, "투자 제안이 있었다.\n", {
            "event_type": "contract_proposed", "actor_id": "investor",
            "contract_id": "proposal:alpha", "company_id": "alpha",
        }, kind="state_change")
        self.cli("apply-approved", "--source", str(self.documents[proposed]),
                 "--candidate-id", proposed)
        refused = self.stage(2, "투자 제안을 명시적으로 거절했다.\n", {
            "event_type": "contract_refused", "actor_id": "investor",
            "contract_id": "proposal:alpha",
        }, kind="state_change")
        self.cli("apply-approved", "--source", str(self.documents[refused]),
                 "--candidate-id", refused)
        self.fact(3, "해당 투자 제안은 거절 상태다.\n", "contract",
                  "proposal:alpha", "current_status", "refused",
                  effective_episode=2)
        out = self.check(3)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 0)
        self.assertEqual(out["counts"]["NEEDS_REVIEW"], 0)

    def test_uncertain_amendment_cannot_explain_confirmed_amount_jump(self):
        self.fact(1, "가상 계약 대금은 15만 달러였다.\n", "amount",
                  "contract:synthetic", "amount", "150000", currency="USD")
        self.stage(2, "대금이 30만 달러로 수정됐을지도 모른다.\n", {
            "fact_type": "change", "subject_id": "contract:synthetic",
            "field": "amount", "from_value": "150000", "to_value": "300000",
            "currency": "USD", "reason_code": "amended", "certainty": "uncertain",
        })
        self.fact(3, "가상 계약 대금은 30만 달러였다.\n", "amount",
                  "contract:synthetic", "amount", "300000", currency="USD")
        out = self.check(3)
        self.assertEqual(out["counts"]["EXPLAINED_CHANGE"], 0)
        self.assertTrue(any(
            f["category"] == "NEEDS_REVIEW" and
            f["reason_code"] == "UNEXPLAINED_STATE_CHANGE"
            for f in out["findings"]
        ))
        self.assertTrue(any(
            f["category"] == "INSUFFICIENT_EVIDENCE" and
            f["reason_code"] == "UNMATCHED_CHANGE_EVENT"
            for f in out["findings"]
        ))

    def test_uncertain_repeat_does_not_explain_duplicate_completed_action(self):
        self.fact(1, "문을 잠갔다.\n", "action",
                  "action:synthetic:lock", "action_state", "completed")
        self.stage(2, "다시 잠근 것일지도 모른다.\n", {
            "fact_type": "change", "subject_id": "action:synthetic:lock",
            "field": "action_state", "from_value": "completed",
            "to_value": "completed", "reason_code": "repeated",
            "certainty": "uncertain",
        })
        self.fact(3, "문을 또 잠갔다.\n", "action",
                  "action:synthetic:lock", "action_state", "completed")
        out = self.check(3)
        self.assertEqual(out["counts"]["EXPLAINED_CHANGE"], 0)
        self.assertTrue(any(f["reason_code"] == "REPEATED_COMPLETED_ACTION"
                            for f in out["findings"]))

    def test_late_discovered_past_signing_is_known_when_later_claim_is_checked(self):
        signed = self.stage(3, "3화에서 1화의 계약 서명 사실을 알게 됐다.\n", {
            "event_type": "contract_signed", "actor_id": "investor",
            "contract_id": "retro-contract", "company_id": "alpha",
            "equity_pct": "12", "effective_episode": 1,
        }, kind="state_change")
        self.cli("apply-approved", "--source", str(self.documents[signed]),
                 "--candidate-id", signed)
        self.assertEqual(self.cli("world-state", "--work-id", "novel",
                                  "--episode", "2")["event_count"], 0)
        claim = self.fact(4, "4화의 인물은 1화 계약이 미서명이라고 주장한다.\n",
                          "contract", "retro-contract", "current_status",
                          "pending", effective_episode=1)
        out = self.check(4)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 1)
        finding = out["findings"][0]
        self.assertEqual(finding["reason_code"], "CONTRACT_LEDGER_STATUS_MISMATCH")
        self.assertEqual(finding["ledger_status"], "signed")
        self.assertEqual({e["candidate_id"] for e in finding["evidence"]},
                         {signed, claim})

    def test_late_discovered_past_signing_does_not_retroactively_discredit_earlier_claim(self):
        self.fact(2, "2화 시점에는 1화 계약이 미서명이라고 알려졌다.\n",
                  "contract", "retro-contract", "current_status", "pending",
                  effective_episode=1)
        signed = self.stage(3, "3화에서 1화 서명 사실이 뒤늦게 공개됐다.\n", {
            "event_type": "contract_signed", "actor_id": "investor",
            "contract_id": "retro-contract", "company_id": "alpha",
            "equity_pct": "12", "effective_episode": 1,
        }, kind="state_change")
        self.cli("apply-approved", "--source", str(self.documents[signed]),
                 "--candidate-id", signed)
        out = self.check(3)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 0)
        self.assertEqual(out["counts"]["NEEDS_REVIEW"], 0)

    def test_amount_relation_qualifiers_prevent_false_exact_equality(self):
        self.stage(1, "잔액이 55만 달러를 넘었다.\n", {
            "fact_type": "amount", "subject_id": "trading:cash",
            "field": "amount", "currency": "USD", "value": "550000",
            "amount_relation": "greater_than",
        })
        self.fact(2, "잔액은 55만 달러라고 적었다.\n",
                  "amount", "trading:cash", "amount", "550000",
                  currency="USD", effective_episode=1)
        out = self.check(2)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 0)
        self.assertTrue(any(
            item["reason_code"] == "QUALIFIED_AMOUNT_COMPARISON"
            and item["category"] == "INSUFFICIENT_EVIDENCE"
            for item in out["findings"]
        ))

    def test_approximate_vs_exact_and_lower_bound_do_not_invent_precision(self):
        self.stage(1, "계약 비용은 약 38만 달러였다.\n", {
            "fact_type": "amount", "subject_id": "put:premium",
            "field": "amount", "currency": "USD", "value": "380000",
            "amount_relation": "approximate",
        })
        self.stage(2, "비용은 38만 달러 이상이었다.\n", {
            "fact_type": "amount", "subject_id": "put:premium",
            "field": "amount", "currency": "USD", "value": "380000",
            "amount_relation": "at_least",
        })
        out = self.check(2)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 0)
        self.assertTrue(any(f["reason_code"] == "QUALIFIED_AMOUNT_COMPARISON"
                            for f in out["findings"]))

    def test_invalid_amount_relation_fails_before_approval(self):
        for payload in (
            {"fact_type": "amount", "subject_id": "account",
             "field": "amount", "currency": "USD", "value": "500",
             "amount_relation": "about-ish"},
            {"fact_type": "time", "subject_id": "meeting",
             "field": "weekday", "value": "monday",
             "amount_relation": "approximate"},
            {"fact_type": "change", "subject_id": "account",
             "field": "amount", "currency": "USD", "from_value": "10",
             "to_value": "20", "reason_code": "amended",
             "amount_relation": "approximate"},
        ):
            cid = self.stage(1, "가상의 정보.\n", payload, approved=False)
            result = self.cli(
                "review-candidate", "--source", str(self.documents[cid]),
                "--candidate-id", cid, "--decision", "approve",
                "--reviewer", "synthetic", "--reason", "invalid qualifier",
                expected=2
            )
            self.assertIn("amount_relation", result)

    def test_confirmed_same_moment_amount_disagreement_is_conflict(self):
        one = self.fact(1, "같은 거래의 최종 가격은 15만 달러였다.\n",
                        "amount", "transaction:fixed", "amount", "150000",
                        currency="USD", context_id="deal:one")
        two = self.fact(2, "같은 거래의 최종 가격은 30만 달러였다.\n",
                        "amount", "transaction:fixed", "amount", "300000",
                        currency="USD", effective_episode=1,
                        context_id="deal:one")
        out = self.check(2)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 1)
        self.assertEqual({e["candidate_id"] for e in out["findings"][0]["evidence"]},
                         {one, two})

    def test_same_event_weekday_conflict_has_both_evidence_spans(self):
        a = self.fact(1, "회담은 월요일이었다.\n", "time",
                      "meeting:1", "weekday", "monday")
        b = self.fact(2, "회담은 화요일이었다.\n", "time",
                      "meeting:1", "weekday", "tuesday", effective_episode=1)
        result = self.check(2)
        self.assertEqual(result["counts"]["CONFIRMED_CONFLICT"], 1)
        finding = result["findings"][0]
        self.assertEqual(finding["reason_code"], "SAME_MOMENT_CONTRADICTION")
        self.assertEqual({x["candidate_id"] for x in finding["evidence"]}, {a, b})
        self.assertEqual([x["episode"] for x in finding["evidence"]], [1, 2])
        self.assertNotIn("회담은 월요일", json.dumps(result, ensure_ascii=False))

    def test_date_weekday_cross_validation_gregorian(self):
        self.fact(1, "회담 날짜는 2026년 11월 4일.\n", "time",
                  "meeting:1", "date", "2026-11-04")
        self.fact(2, "그 회담은 월요일이었다.\n", "time",
                  "meeting:1", "weekday", "monday", effective_episode=1)
        out = self.check(2)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 1)
        finding = out["findings"][0]
        self.assertEqual(finding["reason_code"], "DATE_WEEKDAY_MISMATCH")
        self.assertEqual(finding["calendar_weekday"], "wednesday")

    def test_different_moments_without_change_are_review_not_certain_error(self):
        self.fact(1, "창고 대금은 15만 달러였다.\n", "amount",
                  "deal:1", "amount", "150000", currency="USD")
        self.fact(3, "같은 창고의 대금은 30만 달러였다.\n", "amount",
                  "deal:1", "amount", "300000", currency="USD")
        result = self.check(3)
        self.assertEqual(result["counts"]["NEEDS_REVIEW"], 1)
        self.assertEqual(result["counts"]["CONFIRMED_CONFLICT"], 0)

    def test_approved_amendment_explains_amount_change(self):
        self.fact(1, "계약액은 15만 달러였다.\n", "amount",
                  "deal:1", "amount", "150000.00", currency="USD")
        change = self.change(2, "변경 합의로 대금이 30만 달러가 됐다.\n",
                             "deal:1", "amount", "150000", "300000",
                             currency="USD")
        self.fact(3, "수정 계약액은 30만 달러였다.\n", "amount",
                  "deal:1", "amount", "300000", currency="USD")
        out = self.check(3)
        self.assertEqual(out["counts"]["EXPLAINED_CHANGE"], 1)
        self.assertEqual(out["counts"]["NEEDS_REVIEW"], 0)
        self.assertIn(change, [x["candidate_id"] for x in out["findings"][0]["evidence"]])

    def test_pending_change_is_not_explanation(self):
        self.fact(1, "계약액은 15만 달러였다.\n", "amount",
                  "deal:1", "amount", "150000", currency="USD")
        self.stage(2, "합의로 30만 달러로 바뀌었다.\n", {
            "fact_type": "change", "subject_id": "deal:1", "field": "amount",
            "from_value": "150000", "to_value": "300000", "currency": "USD",
            "reason_code": "amended"}, approved=False)
        self.fact(3, "계약액은 30만 달러였다.\n", "amount",
                  "deal:1", "amount", "300000", currency="USD")
        out = self.check(3)
        self.assertEqual(out["counts"]["NEEDS_REVIEW"], 1)
        self.assertEqual(out["reviewed_change_events"], 0)

    def test_location_changes_need_movement_and_different_scene_no_conflict(self):
        self.fact(1, "에블린은 본사에 있었다.\n", "location",
                  "person:evelyn", "location_id", "hq")
        self.fact(2, "에블린은 창고에 있었다.\n", "location",
                  "person:evelyn", "location_id", "warehouse")
        self.fact(3, "월터는 항구에 있었다.\n", "location",
                  "person:walter", "location_id", "port")
        result = self.check(3)
        self.assertEqual(result["counts"]["NEEDS_REVIEW"], 1)
        self.assertEqual(result["counts"]["CONFIRMED_CONFLICT"], 0)

    def test_same_episode_different_locations_without_scene_context_are_review_only(self):
        self.fact(1, "에블린이 창고에 있었다.\n", "location",
                  "person:evelyn", "location_id", "warehouse")
        self.fact(2, "그때 에블린은 본사에 있었다.\n", "location",
                  "person:evelyn", "location_id", "hq", effective_episode=1)
        out = self.check(2)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 0)
        self.assertEqual(out["counts"]["NEEDS_REVIEW"], 1)

    def test_explicit_same_scene_location_contradiction_is_confirmed(self):
        self.fact(1, "에블린이 창고에 있었다.\n", "location",
                  "person:evelyn", "location_id", "warehouse", context_id="scene:17")
        self.fact(2, "그 장면에서 에블린은 본사에 있었다.\n", "location",
                  "person:evelyn", "location_id", "hq",
                  effective_episode=1, context_id="scene:17")
        out = self.check(2)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 1)

    def test_explicit_movement_explains_location_change(self):
        self.fact(1, "본사에서 회의를 마쳤다.\n", "location",
                  "person:evelyn", "location_id", "hq")
        self.change(2, "본사를 떠나 창고로 이동했다.\n",
                    "person:evelyn", "location_id", "hq", "warehouse",
                    reason="moved")
        self.fact(3, "에블린은 창고에 도착했다.\n", "location",
                  "person:evelyn", "location_id", "warehouse")
        self.assertEqual(self.check(3)["counts"]["EXPLAINED_CHANGE"], 1)

    def test_completed_action_repeated_without_new_attempt_needs_review(self):
        self.fact(1, "문에 자물쇠를 채웠다.\n", "action",
                  "action:lock-door:1", "action_state", "completed")
        self.fact(2, "그 문에 또 자물쇠를 채웠다.\n", "action",
                  "action:lock-door:1", "action_state", "completed")
        out = self.check(2)
        self.assertEqual(out["counts"]["NEEDS_REVIEW"], 1)
        self.assertEqual(out["findings"][0]["reason_code"],
                         "REPEATED_COMPLETED_ACTION")

    def test_uncertain_statement_yields_insufficient_evidence(self):
        self.fact(1, "회담은 월요일이었다.\n", "time",
                  "meeting:1", "weekday", "monday")
        self.fact(2, "회담은 화요일이었을 것이다.\n", "time",
                  "meeting:1", "weekday", "tuesday", effective_episode=1,
                  certainty="uncertain")
        result = self.check(2)
        self.assertEqual(result["counts"]["INSUFFICIENT_EVIDENCE"], 1)
        self.assertEqual(result["counts"]["CONFIRMED_CONFLICT"], 0)

    def test_wrong_currency_not_compared_as_same_amount(self):
        self.fact(1, "대금 5000달러.\n", "amount",
                  "deal:1", "amount", "5000", currency="USD")
        self.fact(2, "대금 5000파운드.\n", "amount",
                  "deal:1", "amount", "5000", currency="GBP")
        self.assertEqual(len(self.check(2)["findings"]), 0)

    def test_unmatched_approved_change_is_insufficient(self):
        self.change(1, "계약액을 변경한다.\n", "deal:1",
                    "amount", "150000", "300000", currency="USD")
        out = self.check(1)
        self.assertEqual(out["counts"]["INSUFFICIENT_EVIDENCE"], 1)
        self.assertEqual(out["findings"][0]["reason_code"],
                         "UNMATCHED_CHANGE_EVENT")

    def test_invalid_continuity_claim_cannot_be_approved(self):
        cid = self.stage(1, "투자 계획만 세웠다.\n", {
            "fact_type": "amount", "subject_id": "deal:1", "field": "amount",
            "value": "1e8", "currency": "USD"}, approved=False)
        self.assertIn("decimal string", self.review(cid, expected=2))
        self.assertEqual(self.check(1)["reviewed_facts"], 0)
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            status = db.execute(
                "SELECT status FROM candidates WHERE candidate_id=?", (cid,)
            ).fetchone()[0]
        self.assertEqual(status, "proposed")

    def test_contract_status_disagrees_with_applied_event_ledger(self):
        self.stage(1, "오로라 지분 계약에 서명했다.\n", {
            "event_type": "contract_signed", "actor_id": "evelyn",
            "contract_id": "aurora-15", "company_id": "aurora",
            "equity_pct": "15"
        }, kind="state_change", approved=True)
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            cid = db.execute(
                "SELECT candidate_id FROM candidates WHERE kind='state_change'"
            ).fetchone()[0]
        self.cli("apply-approved", "--source", str(self.documents[cid]),
                 "--candidate-id", cid)
        self.fact(2, "현재 계약은 아직 서명되지 않았다.\n", "contract",
                  "aurora-15", "current_status", "pending")
        out = self.check(2)
        self.assertEqual(out["counts"]["CONFIRMED_CONFLICT"], 1)
        finding = out["findings"][0]
        self.assertEqual(finding["reason_code"], "CONTRACT_LEDGER_STATUS_MISMATCH")
        self.assertEqual(finding["ledger_status"], "signed")
        self.assertEqual(len(finding["evidence"]), 2)

    def test_later_equity_transfer_does_not_rewrite_earlier_contract_status(self):
        sign = self.stage(1, "계약을 체결했다.\n", {
            "event_type": "contract_signed", "actor_id": "evelyn",
            "contract_id": "aurora-15", "company_id": "aurora",
            "equity_pct": "15"
        }, kind="state_change")
        self.cli("apply-approved", "--source", str(self.documents[sign]),
                 "--candidate-id", sign)
        transfer = self.stage(3, "지분 이전이 완료됐다.\n", {
            "event_type": "equity_transfer", "actor_id": "evelyn",
            "contract_id": "aurora-15"
        }, kind="state_change")
        self.cli("apply-approved", "--source", str(self.documents[transfer]),
                 "--candidate-id", transfer)
        self.fact(4, "당시 2화의 계약은 체결된 상태였다.\n", "contract",
                  "aurora-15", "current_status", "signed", effective_episode=2)
        self.assertEqual(self.check(4)["counts"]["CONFIRMED_CONFLICT"], 0)

    def test_as_of_never_uses_future_claims(self):
        self.fact(1, "본사는 시애틀이었다.\n", "location",
                  "company:1", "location_id", "seattle")
        first = self.check(1)
        self.fact(4, "본사는 뉴욕이었다.\n", "location",
                  "company:1", "location_id", "new-york")
        self.assertEqual(self.check(1), first)
        self.assertEqual(self.check(4)["counts"]["NEEDS_REVIEW"], 1)

    def test_unregistered_episode_is_not_reported_as_zero_conflicts(self):
        self.fact(1, "대화가 끝났다.\n", "action",
                  "scene:one", "action_state", "completed", approved=False)
        database = self.root / "novelgraph.sqlite"
        before = database.read_bytes()
        for work, episode in [("novel", 2), ("other-work", 1)]:
            error = self.cli(
                "check-continuity", "--work-id", work,
                "--episode", str(episode), expected=2,
            )
            self.assertIn("episode is not registered", error)
            self.assertEqual(before, database.read_bytes())
        self.assertEqual(self.check(1)["counts"]["CONFIRMED_CONFLICT"], 0)
        self.assertEqual(before, database.read_bytes())

    def test_check_is_deterministic_and_does_not_modify_candidates(self):
        self.fact(1, "만남은 월요일.\n", "time", "meeting:1", "weekday", "monday")
        self.fact(2, "만남은 화요일.\n", "time", "meeting:1", "weekday",
                  "tuesday", effective_episode=1)
        before = sqlite3.connect(self.root / "novelgraph.sqlite")
        try:
            table_counts = dict(
                before.execute("SELECT status, COUNT(*) FROM candidates GROUP BY status")
            )
        finally:
            before.close()
        first = self.check(2)
        self.assertEqual(first, self.check(2))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            new_counts = dict(db.execute(
                "SELECT status, COUNT(*) FROM candidates GROUP BY status"))
        self.assertEqual(table_counts, new_counts)


if __name__ == "__main__":
    unittest.main()
