"""Bounded, evidence-linked context from approved facts and applied state only."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import deque

from .graphify_bridge import project_graph
from .state_query import SCOPES, query_state
from .world_state import _id

SCOPES_CONTEXT = set(SCOPES) | {"relations", "events", "facts"}
MIDDLE_KINDS = {"relation", "event", "assertion", "state_event", "current_state"}


def _identity(graph, name):
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError("subject or target must be an ID or verified name")
    ident = f"entity:{name}"
    if ident in graph:
        # A link to an unregistered entity is only an unresolved reference,
        # not an approved identity the writer may treat as a fact.
        return (ident, "ok") if graph.nodes[ident].get("kind") == "entity" else (None, "not_found")
    matches = [node for node, attributes in graph.nodes(data=True)
               if node.startswith("entity:") and attributes.get("kind") == "entity"
               and attributes.get("label") == name]
    if len(matches) > 1:
        return None, "ambiguous"
    if not matches:
        return None, "not_found"
    return matches[0], "ok"


def _category_match(scope, kind, info):
    if scope == "facts":
        return kind in MIDDLE_KINDS
    if scope == "relations":
        return kind == "relation"
    if scope == "events":
        return kind in ("event", "state_event")
    if scope == "relationships":
        return kind == "relation" or (kind == "current_state" and info.get("category") == "relationship")
    if scope == "contracts":
        return (kind in ("event", "state_event") and "contract" in info.get("event_type", ""))
    if scope in SCOPES:
        return kind == "current_state" and info.get("category") in SCOPES[scope]
    return False


def _matches_field(field, kind, info):
    if field is None:
        return True
    return field in (info.get("relation_type"), info.get("event_type"),
                     info.get("field"), info.get("item_id"), info.get("category"))


def _neighbors(graph, entity):
    # A relationship is stored as entity -> relation/event -> entity.
    # Count the semantic relationship once, not the underlying two graph edges.
    for middle in set(graph.successors(entity)) | set(graph.predecessors(entity)):
        if graph.nodes[middle].get("kind") not in MIDDLE_KINDS:
            continue
        adjacent = set(graph.successors(middle)) | set(graph.predecessors(middle))
        targets = [node for node in adjacent if node.startswith("entity:") and node != entity]
        yield middle, sorted(targets)


def _fact(graph, middle, route, depth):
    item = graph.nodes[middle]
    evidence_nodes = [node for node in graph.successors(middle)
                      if graph.nodes[node].get("kind") == "evidence"]
    if item.get("kind") == "current_state":
        # A current-state node points to its immutable state event, which
        # in turn links to the original evidence node.
        changed = [node for node in graph.successors(middle)
                   if graph.nodes[node].get("kind") == "state_event"]
        if len(changed) != 1:
            raise ValueError("current state lacks its change event")
        evidence_nodes = [node for node in graph.successors(changed[0])
                          if graph.nodes[node].get("kind") == "evidence"]
    if len(evidence_nodes) != 1:
        raise ValueError("graph fact lacks unique approved evidence")
    evidence = graph.nodes[evidence_nodes[0]]
    ident = evidence["candidate_id"]
    if item.get("candidate_id", ident) != ident:
        raise ValueError("graph fact and source candidate disagree")
    kind = item["kind"]
    value = item.get("value")
    if value is None:
        value = item.get("relation_type", item.get("event_type", item.get("field")))
    if isinstance(value, dict) or isinstance(value, list):
        raise ValueError("graph fact has unsupported value")
    status = ("current" if kind == "current_state" and item.get("relation_status") != "ended"
              else "historical")
    return {
        "kind": kind, "path": route, "semantic_hops": depth,
        "field": item.get("item_id", item.get("field", item.get("relation_type", item.get("event_type")))),
        "value": value, "current_or_historical": status,
        "source_episode": evidence["episode"],
        "effective_episode": item.get("effective_episode", evidence["episode"]),
        "source_sha256": evidence["source_sha256"],
        "candidate_id": ident, "certainty": "approved",
        "evidence": {"episode": evidence["episode"], "start": evidence["start"],
                     "end": evidence["end"]},
    }


def query_context(db: sqlite3.Connection, work_id: str, episode: int,
                  subject: str, scope: str, *, field: str | None = None,
                  target: str | None = None, max_hops: int = 2,
                  max_facts: int = 25, cursor: str | None = None) -> dict:
    """Retrieve only approved graph context known at the given episode, without writes."""
    _id(work_id, "work_id")
    if type(episode) is not int or episode <= 0:
        raise ValueError("episode must be positive")
    if scope not in SCOPES_CONTEXT:
        raise ValueError("unsupported query scope")
    if field is not None:
        _id(field, "field")
    if type(max_hops) is not int or not 1 <= max_hops <= 2:
        raise ValueError("max_hops must be 1..2")
    if type(max_facts) is not int or not 1 <= max_facts <= 25:
        raise ValueError("max_facts must be 1..25")
    if db.execute('SELECT 1 FROM episodes WHERE work_id=? AND episode=?',
                  (work_id, episode)).fetchone() is None:
        raise ValueError("episode is not registered for the selected work")

    graph = project_graph(db, work_id, episode)
    graph_sha = graph.graph["projection_sha256"]
    source, status = _identity(graph, subject)
    target_id, target_status = _identity(graph, target) if target is not None else (None,"ok")
    if target_status != "ok" and status == "ok":
        status = target_status
    result = {"status": status, "work_id": work_id, "as_of_episode": episode,
              "subject_id": source[7:] if source else None,
              "scope": scope, "graph_sha256": graph_sha,
              "facts": [], "truncated": False, "next_cursor": None}
    if status != "ok":
        return result

    records = {}
    queue = deque([(source, [source], 0)])
    seen = {source: 0}
    while queue:
        entity, route, distance = queue.popleft()
        if distance >= max_hops:
            continue
        for middle, adjacent in _neighbors(graph, entity):
            item = graph.nodes[middle]
            kind = item["kind"]
            if _category_match(scope, kind, item) and _matches_field(field, kind, item):
                related = [node for node in adjacent if node != source]
                if target_id is None or target_id == source or target_id in adjacent or (
                    kind == "current_state" and field is not None and distance == 0
                ):
                    path = [*route, middle]
                    if adjacent:
                        path.append(target_id if target_id in adjacent else adjacent[0])
                    record = _fact(graph, middle, path, distance + 1)
                    if record["effective_episode"] <= episode:
                        records.setdefault(middle, record)
            for next_node in adjacent:
                if (next_node not in seen or seen[next_node] > distance+1) and distance+1 < max_hops:
                    seen[next_node] = distance+1
                    queue.append((next_node, [*route, middle, next_node], distance+1))

    # Ledger-derived contract/cash/ownership state is not always represented by
    # an entity->state node; reuse the existing validated state reader for it.
    if scope in SCOPES and scope not in ("facts", "relations", "events"):
        state = query_state(db, work_id, episode, source[7:], scope)
        for category, entries in state["data"].items():
            if not isinstance(entries, dict):
                continue
            for item_id, entry in entries.items():
                if field is not None and field not in (category, item_id):
                    continue
                if not isinstance(entry, dict) or not entry.get("candidate_id"):
                    continue
                if entry.get("effective_episode", episode) > episode:
                    continue
                key = "state:" + entry["candidate_id"]
                if any(r["candidate_id"] == entry["candidate_id"] for r in records.values()):
                    continue
                records[key] = {"kind":"current_state", "path":[source,key],
                    "semantic_hops":1,"field":item_id,"value":entry.get("value",entry),
                    "current_or_historical": "historical" if entry.get("relation_status") == "ended" else "current",
                    "source_episode":entry["source_episode"],
                    "effective_episode":entry["effective_episode"],
                    "source_sha256":entry["evidence"]["source_sha256"],
                    "candidate_id":entry["candidate_id"],"certainty":"approved",
                    "evidence":{"episode":entry["source_episode"],"start":entry["evidence"]["start"],
                                "end":entry["evidence"]["end"]}}

    ordered = sorted(records.values(), key=lambda r:(r["semantic_hops"],r["kind"],r["candidate_id"]))
    signature = hashlib.sha256(json.dumps([work_id,episode,source,target_id,scope,field,
                                            max_hops,max_facts,graph_sha],separators=(',',':')).encode()).hexdigest()
    offset = 0
    if cursor is not None:
        match = re.fullmatch(r"([0-9a-f]{64}):([0-9]{1,8})",cursor)
        if not match or match[1] != signature or int(match[2]) >= len(ordered):
            raise ValueError("invalid or stale context cursor")
        offset = int(match[2])
    result["facts"] = ordered[offset:offset+max_facts]
    next_offset = offset+len(result["facts"])
    result["truncated"] = next_offset < len(ordered)
    if result["truncated"]:
        result["next_cursor"] = f"{signature}:{next_offset}"
    return result
