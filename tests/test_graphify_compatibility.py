"""Reproducible Graphify compatibility checks with synthetic story data only.

Run: .venv/bin/python -m unittest discover -s tests -v
No real manuscript, external LLM API or server is used.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import networkx as nx
from graphify.export import to_json
from graphify.paths import load_node_link_graph


class GraphifyCompatibilityTests(unittest.TestCase):
    def test_structured_story_graph_roundtrip_and_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            graph_path = Path(temp) / "graph.json"
            G = nx.DiGraph()
            story_line = "에블린이 월요일에 오로라 회사의 지분 15% 계약에 서명했다."
            nodes = [
                ("char:evelyn", "에블린", "person"),
                ("event:sign", "지분 계약 서명", "event"),
                ("contract:aurora", "오로라 지분 15% 계약", "contract"),
                ("company:aurora", "오로라 회사", "organization"),
                ("evidence:line1", "1화 1행 근거", "evidence"),
            ]
            for node_id, label, kind in nodes:
                G.add_node(node_id, label=label, kind=kind,
                           source_file="synthetic-001.txt", source_location="L1",
                           file_type="document")
            G.nodes["evidence:line1"]["quote"] = story_line
            links = [
                ("char:evelyn", "event:sign", "participated_in"),
                ("event:sign", "contract:aurora", "signed"),
                ("contract:aurora", "company:aurora", "about"),
                ("event:sign", "evidence:line1", "supported_by"),
            ]
            for source, target, relation in links:
                G.add_edge(source, target, relation=relation,
                           confidence="EXTRACTED", evidence_id="evidence:line1",
                           source_file="synthetic-001.txt", source_location="L1",
                           _src=source, _tgt=target)

            self.assertTrue(to_json(G, {}, str(graph_path),
                                    built_at_commit="synthetic-test"))
            raw = json.loads(graph_path.read_text(encoding="utf-8"))
            self.assertEqual(len(raw["nodes"]), 5)
            self.assertEqual(len(raw["links"]), 4)
            self.assertEqual(raw["graph"]["schema_version"], 1)
            self.assertEqual(
                {(e["source"], e["target"], e["relation"]) for e in raw["links"]},
                set(links),
            )
            loaded = load_node_link_graph(graph_path)
            self.assertEqual(loaded.nodes["evidence:line1"]["quote"], story_line)

            for command, expected in [
                (["path", "에블린", "오로라 회사"], "Shortest path (3 hops)"),
                (["explain", "지분 계약 서명"], "synthetic-001.txt L1"),
                (["query", "에블린 오로라 계약"], "5 nodes found"),
            ]:
                with self.subTest(command=command[0]):
                    result = subprocess.run(
                        [sys.executable, "-m", "graphify", *command,
                         "--graph", str(graph_path)],
                        text=True, capture_output=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(expected, result.stdout)

    def test_text_file_does_not_receive_unassisted_semantic_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            source_dir = Path(temp) / "source"
            source_dir.mkdir()
            (source_dir / "001.txt").write_text(
                "에블린이 계약에 서명했다. 대금 지급은 아직 하지 않았다.\n",
                encoding="utf-8",
            )
            output_dir = Path(temp) / "graph-output"
            result = subprocess.run(
                [sys.executable, "-m", "graphify", "update",
                 str(source_dir), "--no-cluster"],
                env={**os.environ, "GRAPHIFY_OUT": str(output_dir)},
                text=True, capture_output=True, timeout=50,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            raw = json.loads((output_dir / "graph.json").read_text(encoding="utf-8"))
            self.assertEqual(len(raw["nodes"]), 0)
            self.assertEqual(len(raw.get("links", raw.get("edges", []))), 0)


if __name__ == "__main__":
    unittest.main()
