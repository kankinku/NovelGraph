"""Read-only Graphify projection of reviewed NovelGraph records.

SQLite remains authoritative; graph.json is a derived snapshot that may be
recreated at any time. No quotes, manuscripts, or database files are published.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import networkx as nx
from graphify.export import to_json
from graphify.paths import load_node_link_graph

from .continuity import validate_fact
from .world_state import _id, _payload

ENTITY_TYPES = {"person", "organization", "place", "contract", "asset", "object"}
GRAPH_SCHEMA = 1


def _fail(message: str) -> None:
    raise ValueError(message)


def _strict_fields(data, required: set[str], optional: set[str] = frozenset()) -> None:
    if not isinstance(data, dict) or set(data) - required - optional or not required <= set(data):
        _fail("approved graph candidate has an invalid payload schema")


def _text(value: object, field: str, limit: int = 120) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _fail(f"{field} must be nonempty text of at most {limit} characters")
    return value


def _decode(row: sqlite3.Row) -> dict:
    try:
        data = json.loads(row["payload_json"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid approved JSON payload") from exc
    if not isinstance(data, dict):
        _fail("approved payload must be a JSON object")
    return data


def _evidence_id(candidate_id: str) -> str:
    return f"evidence:{candidate_id}"


def _reference_id(entity_id: str) -> str:
    return f"entity:{_id(entity_id, 'entity_id')}"


def _metadata(row: sqlite3.Row) -> dict:
    return {
        "candidate_id": row["candidate_id"],
        "episode": row["episode"],
        "source_sha256": row["source_sha256"],
        "start": row["evidence_start"],
        "end": row["evidence_end"],
        "source_file": f"{row['work_id']}:episode:{row['episode']}",
        "source_location": f"{row['episode']}:{row['evidence_start']}-{row['evidence_end']}",
    }


def _check_evidence(row: sqlite3.Row) -> None:
    # Integrity of stored evidence versus source-file bytes was established by
    # candidate intake and review; only hash/offset links can be proven here.
    if row["status"] != "approved" or not isinstance(row["source_sha256"], str):
        _fail("graph source must be an approved candidate")
    if not isinstance(row["evidence_text"], str):
        _fail("stored evidence is missing")
    if row["evidence_end"] - row["evidence_start"] != len(row["evidence_text"]):
        _fail("stored evidence span is inconsistent")
    # Candidate IDs were created from these exact fields at intake (stage 4).
    # Recompute them before exporting to catch edits to stored claims/quotes
    # that a same-length evidence span check would otherwise overlook.
    try:
        canonical = json.dumps(
            [row["work_id"], row["episode"], row["source_sha256"],
             row["kind"], json.loads(row["payload_json"]),
             row["evidence_start"], row["evidence_end"], row["evidence_text"]],
            sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise ValueError("stored candidate contains invalid JSON") from exc
    if hashlib.sha256(canonical).hexdigest() != row["candidate_id"]:
        _fail("stored candidate integrity hash mismatch")


def _node(g: nx.DiGraph, ident: str, label: str, kind: str, **attrs) -> None:
    if ident in g:
        # Strong identity conflicts cannot silently overwrite approved facts.
        existing = g.nodes[ident]
        if existing.get("kind") == "unresolved_reference":
            g.nodes[ident].update(label=label, kind=kind, **attrs)
            return
        if existing.get("label") != label or existing.get("kind") != kind:
            _fail("conflicting approved semantic node identity")
        for key, val in attrs.items():
            if key in existing and existing[key] != val:
                _fail("conflicting approved semantic node attributes")
        existing.update(attrs)
    else:
        g.add_node(ident, label=label, kind=kind, file_type="document", **attrs)


def _ref(g: nx.DiGraph, entity_id: str) -> str:
    ident = _reference_id(entity_id)
    if ident not in g:
        _node(g, ident, entity_id, "unresolved_reference")
    return ident


def _edge(g: nx.DiGraph, src: str, dst: str, relation: str, row: sqlite3.Row) -> None:
    if g.has_edge(src, dst):
        _fail("duplicate graph edge would overwrite a provenance relationship")
    g.add_edge(src, dst, relation=relation, confidence="EXTRACTED",
               candidate_id=row["candidate_id"], _src=src, _tgt=dst,
               source_file=f"{row['work_id']}:episode:{row['episode']}",
               source_location=f"{row['episode']}:{row['evidence_start']}-{row['evidence_end']}")


def _supported(g: nx.DiGraph, row: sqlite3.Row, target: str) -> None:
    eid = _evidence_id(row["candidate_id"])
    _node(g, eid, eid, "evidence",
          candidate_id=row["candidate_id"], work_id=row["work_id"],
          episode=row["episode"], source_sha256=row["source_sha256"],
          start=row["evidence_start"], end=row["evidence_end"],
          source_file=f"{row['work_id']}:episode:{row['episode']}",
          source_location=f"{row['episode']}:{row['evidence_start']}-{row['evidence_end']}")
    _edge(g, target, eid, "supported_by", row)


def _add_approved(g: nx.DiGraph, row: sqlite3.Row) -> None:
    _check_evidence(row)
    kind, data, candidate_id = row["kind"], _decode(row), row["candidate_id"]

    if kind == "entity":
        _strict_fields(data, {"entity_id", "entity_type", "name"})
        _id(data["entity_id"], "entity_id")
        if (not isinstance(data["entity_type"], str)
                or data["entity_type"] not in ENTITY_TYPES):
            _fail("unsupported entity_type")
        name = _text(data["name"], "name")
        node_id = _reference_id(data["entity_id"])
        _node(g, node_id, name, "entity", entity_type=data["entity_type"])
        _supported(g, row, node_id)

    elif kind == "relation":
        _strict_fields(data, {"source_id", "target_id", "relation_type"})
        source = _ref(g, data["source_id"])
        target = _ref(g, data["target_id"])
        relation_type = _id(data["relation_type"], "relation_type")
        mid = f"relation:{candidate_id}"
        _node(g, mid, relation_type, "relation", relation_type=relation_type)
        _edge(g, source, mid, "has_relation", row)
        _edge(g, mid, target, "relates_to", row)
        _supported(g, row, mid)

    elif kind == "event":
        _strict_fields(data, {"event_type", "actor_id"}, {"target_id"})
        event_type = _id(data["event_type"], "event_type")
        actor = _ref(g, data["actor_id"])
        mid = f"event:{candidate_id}"
        _node(g, mid, event_type, "event", event_type=event_type,
              effective_episode=row["episode"])
        _edge(g, actor, mid, "participated_in", row)
        if "target_id" in data:
            target = _ref(g, data["target_id"])
            _edge(g, mid, target, "targets", row)
        _supported(g, row, mid)

    elif kind == "continuity_fact":
        fact = validate_fact(row)
        subject = _ref(g, fact["subject_id"])
        mid = f"assertion:{candidate_id}"
        _node(g, mid, f"{fact['field']}:{fact['fact_type']}", "assertion",
              fact_type=fact["fact_type"], field=fact["field"],
              effective_episode=fact["effective_episode"])
        _edge(g, subject, mid, "has_assertion", row)
        _supported(g, row, mid)
    else:
        _fail("unexpected approved candidate kind")


def _add_applied(g: nx.DiGraph, row: sqlite3.Row) -> None:
    _check_evidence(row)
    if row["kind"] != "state_change":
        _fail("applied event must be a state_change")
    event_type, event_key, normalized, effective = _payload(row)
    if (event_type != row["event_type"] or effective != row["effective_episode"]
            or normalized != row["applied_payload"]):
        _fail("applied event ledger differs from approved candidate payload")
    value = json.loads(normalized)
    actor = _ref(g, value["actor_id"])
    event_id = f"event:{row['candidate_id']}"
    _node(g, event_id, event_type, "state_event",
          event_type=event_type, event_key=event_key,
          effective_episode=effective, source_episode=row["episode"])
    _edge(g, actor, event_id, "participated_in", row)
    for field, relation in (("contract_id", "concerns_contract"),
                            ("company_id", "concerns_company")):
        if field in value:
            target = _ref(g, value[field])
            _edge(g, event_id, target, relation, row)
    _supported(g, row, event_id)


def _digest(g: nx.DiGraph) -> str:
    # Deliberately exclude Graphify's generated norm_label/community metadata.
    nodes = [(str(node_id), attrs) for node_id, attrs in g.nodes(data=True)]
    edges = [(str(src), str(dst), attrs) for src, dst, attrs in g.edges(data=True)]
    obj = {"nodes": sorted(nodes, key=lambda x: x[0]),
           "edges": sorted(edges, key=lambda x: (x[0], x[1]))}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def project_graph(db: sqlite3.Connection, work_id: str, episode: int) -> nx.DiGraph:
    """Project only approved facts and *applied* state changes known at a turn."""
    _id(work_id, "work_id")
    if type(episode) is not int or episode <= 0:
        _fail("episode must be positive")
    db.row_factory = sqlite3.Row
    graph = nx.DiGraph()
    graph.graph.update(novelgraph_schema=GRAPH_SCHEMA, work_id=work_id,
                       as_of_episode=episode)
    rows = db.execute(
        """SELECT c.*, e.source_sha256 FROM candidates c
           JOIN episodes e ON e.work_id=c.work_id AND e.episode=c.episode
           WHERE c.work_id=? AND c.episode<=? AND c.status='approved'
             AND c.kind IN ('entity','relation','event','continuity_fact')
           ORDER BY c.episode,c.evidence_start,c.candidate_id""",
        (work_id, episode),
    ).fetchall()
    applied_table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='applied_events'"
    ).fetchone()
    applied = []
    if applied_table:
        applied = db.execute(
            """SELECT c.*, e.source_sha256, ae.event_type,
                      ae.effective_episode, ae.payload_json AS applied_payload
               FROM applied_events ae
               JOIN candidates c ON c.candidate_id=ae.candidate_id
               JOIN episodes e ON e.work_id=c.work_id AND e.episode=c.episode
               WHERE ae.work_id=? AND ae.source_episode<=?
                 AND ae.effective_episode<=? AND c.status='approved'
               ORDER BY ae.source_episode,c.evidence_start,c.candidate_id""",
            (work_id, episode, episode),
        ).fetchall()
    # Install all reviewed entity labels first so referenced identities do not
    # depend on the episode ordering of their approved relation/event candidates.
    for row in rows:
        if row["kind"] == "entity":
            _add_approved(graph, row)
    for row in rows:
        if row["kind"] != "entity":
            _add_approved(graph, row)
    for row in applied:
        _add_applied(graph, row)
    graph.graph["projection_sha256"] = _digest(graph)
    return graph


def _verify(loaded: nx.Graph, expected: nx.DiGraph) -> None:
    meta = loaded.graph
    for name in ("novelgraph_schema", "work_id", "as_of_episode",
                 "projection_sha256"):
        if meta.get(name) != expected.graph.get(name):
            _fail("graph snapshot is stale or belongs to a different work/episode")
    if not loaded.is_directed() or (set(loaded.nodes) != set(expected.nodes)
                                   or set(loaded.edges) != set(expected.edges)):
        _fail("graph snapshot nodes or directed edges do not match SQLite")
    for ident, attrs in expected.nodes(data=True):
        saved = loaded.nodes[ident]
        if (any(saved.get(k) != v for k, v in attrs.items())
                or set(saved) - set(attrs) - {"norm_label", "community",
                                               "community_name"}):
            _fail("graph node attributes differ from authoritative SQLite")
    for src, dst, attrs in expected.edges(data=True):
        saved = loaded.edges[src, dst]
        if (any(k not in ("_src", "_tgt") and saved.get(k) != v
                for k, v in attrs.items())
                or set(saved) - set(attrs) - {"confidence_score"}):
            _fail("graph edge attributes differ from authoritative SQLite")


def export_graph(db: sqlite3.Connection, work_id: str, episode: int,
                 output: Path) -> dict:
    graph = project_graph(db, work_id, episode)
    if not to_json(graph, {}, str(output), force=True):
        _fail("Graphify did not write a graph")
    loaded = load_node_link_graph(output)
    _verify(loaded, graph)
    return {
        "work_id": work_id, "as_of_episode": episode,
        "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
        "graph_sha256": graph.graph["projection_sha256"],
        "graphify_format": True, "source_quotes_included": False,
        "output": str(output),
    }


def trace_graph(db: sqlite3.Connection, work_id: str, episode: int,
                graph_path: Path, source: str, target: str) -> dict:
    expected = project_graph(db, work_id, episode)
    loaded = load_node_link_graph(graph_path)
    _verify(loaded, expected)
    if source not in loaded or target not in loaded:
        _fail("requested source or target node does not exist")
    # Relationship direction is retained even when traversing an inverse
    # route. Returning hop orientations prevents accidental semantic reversal.
    try:
        path = nx.shortest_path(loaded.to_undirected(as_view=True), source, target)
    except nx.NetworkXNoPath as exc:
        raise ValueError("no relationship path between requested nodes") from exc
    hops = []
    evidence_ids = set()
    for ident in path:
        if loaded.nodes[ident].get("kind") == "evidence":
            evidence_ids.add(ident)
        for next_id in loaded.successors(ident):
            if loaded.nodes[next_id].get("kind") == "evidence":
                evidence_ids.add(next_id)
    for src, dst in zip(path, path[1:]):
        forward = loaded.has_edge(src, dst)
        attrs = loaded.edges[src, dst] if forward else loaded.edges[dst, src]
        hops.append({
            "source": src if forward else dst, "target": dst if forward else src,
            "relation": attrs.get("relation"), "traversed_forward": forward,
            "candidate_id": attrs.get("candidate_id"),
        })
    evidence = []
    for ident in sorted(evidence_ids):
        item = loaded.nodes[ident]
        evidence.append({
            "candidate_id": item["candidate_id"], "episode": item["episode"],
            "source_sha256": item["source_sha256"],
            "start": item["start"], "end": item["end"],
        })
    return {
        "work_id": work_id, "as_of_episode": episode,
        "path": path, "hops": hops, "evidence": evidence,
        "graph_sha256": expected.graph["projection_sha256"],
        "source_quotes_included": False,
    }
