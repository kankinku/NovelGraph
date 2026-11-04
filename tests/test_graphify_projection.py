"""[7/9] Graphify integration tests using only synthetic Korean story fragments."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from graphify.paths import load_node_link_graph


class GraphifyProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="novelgraph-graphify-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        self.graph_path = self.root / "graph.json"
        self.source_paths = {}

    def cli(self, *args, expected=0):
        cmd = [sys.executable, "-m", "novelgraph", "--data-root",
               str(self.root), *args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected,
                         f"{cmd}\nSTDERR: {result.stderr}\nSTDOUT: {result.stdout}")
        return json.loads(result.stdout) if expected == 0 else result.stderr

    def stage(self, episode, claims, *, approve=True, apply_states=False):
        """One story document per episode; each synthetic candidate has its own line."""
        story = "".join(f"{quote}\n" for quote, _, _ in claims)
        source = self.root / f"episode-{episode:03d}.txt"
        self.assertFalse(source.exists())
        source.write_bytes(story.encode("utf-8"))
        self.source_paths[episode] = source
        candidates = []
        offset = 0
        for quote, kind, payload in claims:
            candidates.append({
                "kind": kind, "payload": payload,
                "evidence": {"start": offset, "end": offset + len(quote),
                             "text": quote},
            })
            offset += len(quote) + 1
        candidate_file = self.root / "candidate-batch.json"
        candidate_file.write_text(json.dumps({
            "schema_version": 1, "work_id": "novel",
            "episode": episode,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "candidates": candidates,
        }, ensure_ascii=False), encoding="utf-8")
        self.cli("import-candidates", "--source", str(source),
                 "--input", str(candidate_file))
        candidate_ids = []
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            for item in candidates:
                encoded = json.dumps(item["payload"], sort_keys=True,
                                     ensure_ascii=False, separators=(",", ":"))
                candidate_id = db.execute(
                    "SELECT candidate_id FROM candidates WHERE work_id=? "
                    "AND episode=? AND payload_json=?",
                    ("novel", episode, encoded)
                ).fetchone()[0]
                candidate_ids.append(candidate_id)
        if approve:
            for candidate_id, candidate in zip(candidate_ids, candidates):
                self.cli("review-candidate", "--source", str(source),
                         "--candidate-id", candidate_id, "--decision", "approve",
                         "--reviewer", "human", "--reason", "synthetic evidence verified")
                if apply_states and candidate["kind"] == "state_change":
                    self.cli("apply-approved", "--source", str(source),
                             "--candidate-id", candidate_id)
        return candidate_ids

    def export(self, episode, *, overwrite=False, expected=0, output=None):
        args = [
            "graphify-export", "--work-id", "novel",
            "--episode", str(episode),
            "--output", str(output or self.graph_path),
        ]
        if overwrite:
            args.append("--overwrite")
        return self.cli(*args, expected=expected)

    def trace(self, episode, start="entity:evelyn",
              end="entity:aurora", *, expected=0):
        return self.cli("graphify-trace", "--work-id", "novel",
                        "--episode", str(episode), "--graph",
                        str(self.graph_path), "--from-node", start,
                        "--to-node", end, expected=expected)

    @staticmethod
    def entity(ident, name, kind):
        return {"entity_id": ident, "name": name, "entity_type": kind}

    def test_approved_entity_event_relation_graph_and_source_trace(self):
        a, b, e, r = self.stage(1, [
            ("에블린은 담당자였다.", "entity",
             self.entity("evelyn", "에블린", "person")),
            ("오로라 회사가 설립되었다.", "entity",
             self.entity("aurora", "오로라", "organization")),
            ("에블린이 오로라 회사를 방문했다.", "event",
             {"event_type": "visit", "actor_id": "evelyn", "target_id": "aurora"}),
            ("에블린은 오로라의 협력자다.", "relation",
             {"relation_type": "collaborates_with", "source_id": "evelyn",
              "target_id": "aurora"}),
        ])
        result = self.export(1)
        self.assertTrue(result["graphify_format"])
        self.assertFalse(result["source_quotes_included"])
        self.assertEqual(self.graph_path.stat().st_mode & 0o777, 0o600)
        graph = load_node_link_graph(self.graph_path)
        self.assertTrue(graph.is_directed())
        for node in ("entity:evelyn", "entity:aurora", f"event:{e}",
                     f"relation:{r}", f"evidence:{a}", f"evidence:{b}"):
            self.assertIn(node, graph)
        self.assertTrue(graph.has_edge(f"event:{e}", f"evidence:{e}"))
        self.assertTrue(graph.has_edge(f"relation:{r}", f"evidence:{r}"))
        trace = self.trace(1)
        self.assertEqual(trace["path"][0], "entity:evelyn")
        self.assertEqual(trace["path"][-1], "entity:aurora")
        self.assertTrue(all(x["source_sha256"] for x in trace["evidence"]))
        self.assertTrue(all(isinstance(x["start"], int) for x in trace["evidence"]))
        self.assertNotIn("방문했다", json.dumps(trace, ensure_ascii=False))
        self.assertNotIn("방문했다", self.graph_path.read_text(encoding="utf-8"))
        graphify_cmd = subprocess.run(
            [sys.executable, "-m", "graphify", "path", "에블린", "오로라",
             "--graph", str(self.graph_path)],
            capture_output=True, text=True, timeout=30
        )
        self.assertEqual(graphify_cmd.returncode, 0, graphify_cmd.stderr)
        self.assertIn("Shortest path", graphify_cmd.stdout)

    def test_unapproved_candidate_is_never_exported(self):
        self.stage(1, [("에블린은 등장한다.", "entity",
                        self.entity("evelyn", "에블린", "person"))])
        self.stage(2, [("오로라는 언급됐다.", "entity",
                        self.entity("aurora", "오로라", "organization"))],
                   approve=False)
        result = self.export(2)
        graph = load_node_link_graph(self.graph_path)
        self.assertIn("entity:evelyn", graph)
        self.assertNotIn("entity:aurora", graph)
        self.assertEqual(result["nodes"], 2)

    def test_state_change_appears_only_after_apply(self):
        self.stage(1, [
            ("에블린이 서명했다.", "state_change",
             {"event_type": "contract_signed", "actor_id": "evelyn",
              "contract_id": "aurora-15", "company_id": "aurora",
              "equity_pct": "15"})
        ])
        empty = self.export(1)
        self.assertEqual(empty["nodes"], 0)
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            cid = db.execute("SELECT candidate_id FROM candidates").fetchone()[0]
        self.cli("apply-approved", "--source", str(self.source_paths[1]),
                 "--candidate-id", cid)
        result = self.export(1, overwrite=True)
        self.assertGreater(result["nodes"], 0)
        g = load_node_link_graph(self.graph_path)
        self.assertIn(f"event:{cid}", g)
        self.assertEqual(g.nodes[f"event:{cid}"]["event_type"], "contract_signed")
        traced = self.trace(1, "entity:evelyn", "entity:aurora-15")
        self.assertIn(cid, [x["candidate_id"] for x in traced["evidence"]])
        self.assertEqual(self.cli("world-state", "--work-id", "novel",
                                  "--episode", "1")["contracts"]["aurora-15"]["status"],
                         "signed")

    def test_same_entities_support_multiple_distinct_relations(self):
        _, _, first, second = self.stage(1, [
            ("에블린이 등장한다.", "entity",
             self.entity("evelyn", "에블린", "person")),
            ("오로라가 등장한다.", "entity",
             self.entity("aurora", "오로라", "organization")),
            ("에블린은 오로라의 협력자이다.", "relation",
             {"source_id": "evelyn", "target_id": "aurora",
              "relation_type": "collaborates_with"}),
            ("에블린이 오로라에 투자하기로 합의했다.", "relation",
             {"source_id": "evelyn", "target_id": "aurora",
              "relation_type": "has_investment_agreement"}),
        ])
        self.export(1)
        g = load_node_link_graph(self.graph_path)
        self.assertIn(f"relation:{first}", g)
        self.assertIn(f"relation:{second}", g)
        self.assertEqual(g.nodes[f"relation:{first}"]["relation_type"],
                         "collaborates_with")
        self.assertEqual(g.nodes[f"relation:{second}"]["relation_type"],
                         "has_investment_agreement")
        self.assertTrue(g.has_edge(f"relation:{first}", f"evidence:{first}"))
        self.assertTrue(g.has_edge(f"relation:{second}", f"evidence:{second}"))

    def test_graph_must_be_regenerated_after_approval(self):
        self.stage(1, [("에블린이 등장했다.", "entity",
                        self.entity("evelyn", "에블린", "person"))])
        self.stage(2, [("오로라가 등장했다.", "entity",
                        self.entity("aurora", "오로라", "organization"))],
                   approve=False)
        self.export(2)
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            cid = db.execute("SELECT candidate_id FROM candidates "
                             "WHERE episode=2").fetchone()[0]
        self.cli("review-candidate", "--source", str(self.source_paths[2]),
                 "--candidate-id", cid, "--decision", "approve",
                 "--reviewer", "human", "--reason", "reviewed")
        self.assertIn("stale", self.trace(2, expected=2))
        self.export(2, overwrite=True)
        result = self.trace(2, start="entity:evelyn",
                            end="entity:aurora", expected=2)
        self.assertIn("no relationship path", result)

    def test_tampered_saved_graph_is_rejected(self):
        self.stage(1, [
            ("에블린은 담당자였다.", "entity",
             self.entity("evelyn", "에블린", "person"))
        ])
        self.export(1)
        data = json.loads(self.graph_path.read_text(encoding="utf-8"))
        data["nodes"][0]["kind"] = "forged"
        self.graph_path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIn("differ", self.trace(1, "entity:evelyn",
                                          "entity:evelyn", expected=2))

    def test_as_of_snapshot_has_no_future_approved_items(self):
        self.stage(1, [("에블린이 등장한다.", "entity",
                        self.entity("evelyn", "에블린", "person"))])
        self.stage(3, [("오로라는 늦게 등장한다.", "entity",
                        self.entity("aurora", "오로라", "organization"))])
        self.export(1)
        self.assertNotIn("entity:aurora", load_node_link_graph(self.graph_path))
        self.assertIn("stale", self.trace(3, expected=2))
        self.export(3, overwrite=True)
        self.assertIn("entity:aurora", load_node_link_graph(self.graph_path))

    def test_export_requires_private_target_and_explicit_overwrite(self):
        self.stage(1, [("에블린이 등장했다.", "entity",
                        self.entity("evelyn", "에블린", "person"))])
        self.export(1)
        self.assertIn("already exists", self.export(1, expected=2))
        outside = self.root.parent / "graph.json"
        self.assertIn("private data root", self.export(1, output=outside, expected=2))
        data_dir = self.root / "unsafe"
        data_dir.mkdir(mode=0o755)
        self.assertIn("private data root", self.export(
            1, output=data_dir / "graph.json", expected=2))
        self.assertFalse((data_dir / "graph.json").exists())

    def test_approved_invalid_relation_schema_fails_closed(self):
        self.stage(1, [("관계가 언급된다.", "relation",
                        {"source_id": "evelyn", "target_id": "aurora"})])
        self.assertIn("invalid payload schema", self.export(1, expected=2))
        self.assertFalse(self.graph_path.exists())

    def test_approved_continuity_assertion_has_provenance(self):
        _, f = self.stage(1, [
            ("에블린이 등장한다.", "entity",
             self.entity("evelyn", "에블린", "person")),
            ("에블린은 창고에 있었다.", "continuity_fact",
             {"fact_type": "location", "subject_id": "evelyn",
              "field": "location_id", "value": "warehouse"}),
        ])
        self.export(1)
        graph = load_node_link_graph(self.graph_path)
        self.assertIn(f"assertion:{f}", graph)
        self.assertTrue(graph.has_edge(f"assertion:{f}", f"evidence:{f}"))
        self.assertTrue(graph.has_edge("entity:evelyn", f"assertion:{f}"))

    def test_extra_graph_data_is_rejected_even_when_fingerprint_is_unchanged(self):
        self.stage(1, [("에블린이 등장했다.", "entity",
                        self.entity("evelyn", "에블린", "person"))])
        self.export(1)
        data = json.loads(self.graph_path.read_text(encoding="utf-8"))
        data["nodes"][0]["injected_quote"] = "private invented content"
        self.graph_path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIn("attributes differ", self.trace(
            1, "entity:evelyn", "entity:evelyn", expected=2))

    def test_malformed_entity_type_fails_closed(self):
        self.stage(1, [("불확실한 대상이 언급된다.", "entity",
                        {"entity_id": "unknown", "name": "미상",
                         "entity_type": ["person", "organization"]})])
        self.assertIn("unsupported entity_type", self.export(1, expected=2))
        self.assertFalse(self.graph_path.exists())

    def test_reverse_graph_path_preserves_direction(self):
        _, _, event = self.stage(1, [
            ("에블린이 등장했다.", "entity",
             self.entity("evelyn", "에블린", "person")),
            ("오로라가 등장했다.", "entity",
             self.entity("aurora", "오로라", "organization")),
            ("에블린이 오로라를 방문했다.", "event",
             {"event_type": "visit", "actor_id": "evelyn",
              "target_id": "aurora"}),
        ])
        self.export(1)
        out = self.trace(1, "entity:aurora", "entity:evelyn")
        self.assertEqual(out["path"], ["entity:aurora", f"event:{event}",
                                       "entity:evelyn"])
        self.assertTrue(all(not edge["traversed_forward"] for edge in out["hops"]))
        self.assertIn(event, [record["candidate_id"] for record in out["evidence"]])

    def test_export_does_not_change_sqlite_counts(self):
        self.stage(1, [("에블린이 등장한다.", "entity",
                        self.entity("evelyn", "에블린", "person"))])
        path = self.root / "novelgraph.sqlite"
        with sqlite3.connect(path) as db:
            before = [db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("episodes", "candidates", "review_log")]
        self.export(1)
        self.trace(1, "entity:evelyn", "entity:evelyn")
        with sqlite3.connect(path) as db:
            after = [db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("episodes", "candidates", "review_log")]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
