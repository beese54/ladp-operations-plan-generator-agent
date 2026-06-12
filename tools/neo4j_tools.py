import logging
from typing import Any, Optional
from neo4j.exceptions import ServiceUnavailable, Neo4jError
from db.neo4j_client import execute_read, execute_write
from schemas.neo4j_models import ValveNode, PipeRelationship

logger = logging.getLogger(__name__)


def _safe_read(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return execute_read(query, params)
    except (ServiceUnavailable, Neo4jError) as e:
        logger.error("Neo4j read error: %s", e)
        return []


def _safe_write(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return execute_write(query, params)
    except (ServiceUnavailable, Neo4jError) as e:
        logger.error("Neo4j write error: %s", e)
        return []


def get_pipe_and_valves(pipe_id: str) -> dict[str, Any]:
    """Fetch the target pipe relationship and its two endpoint valves."""
    query = """
    MATCH (v1:Valve)-[p:PIPE {pipe_id: $pipe_id}]->(v2:Valve)
    RETURN
      properties(v1) AS from_valve,
      properties(p)  AS pipe_props,
      properties(v2) AS to_valve
    LIMIT 1
    """
    rows = _safe_read(query, {"pipe_id": pipe_id})
    if not rows:
        return {}
    r = rows[0]
    return {
        "from_valve": dict(r["from_valve"]),
        "pipe_props":  dict(r["pipe_props"]),
        "to_valve":   dict(r["to_valve"]),
    }


def get_partner_pipe(pipe_id: str, from_valve_id: str, to_valve_id: str) -> Optional[str]:
    """Return the pipe_id of the reverse-direction pair for a bidirectional pipe."""
    query = """
    MATCH (v1:Valve {id: $to_id})-[p:PIPE]->(v2:Valve {id: $from_id})
    WHERE p.pipe_id <> $pipe_id
    RETURN p.pipe_id AS partner_pipe_id
    LIMIT 1
    """
    rows = _safe_read(query, {"to_id": to_valve_id, "from_id": from_valve_id, "pipe_id": pipe_id})
    return rows[0]["partner_pipe_id"] if rows else None


def get_neighborhood_pipes(valve_id: str) -> list[dict[str, Any]]:
    """Return all pipes directly connected to a valve (outgoing + incoming)."""
    query = """
    MATCH (v:Valve {id: $valve_id})-[p:PIPE]->(v2:Valve)
    RETURN
      p.pipe_id            AS pipe_id,
      p.diameter_mm        AS diameter_mm,
      p.road_name          AS road_name,
      p.pressure_mRL       AS pressure_mRL,
      v2.id                AS neighbor_valve_id,
      v2.road_name         AS neighbor_road_name,
      'outgoing'           AS direction
    UNION
    MATCH (v2:Valve)-[p:PIPE]->(v:Valve {id: $valve_id})
    RETURN
      p.pipe_id            AS pipe_id,
      p.diameter_mm        AS diameter_mm,
      p.road_name          AS road_name,
      p.pressure_mRL       AS pressure_mRL,
      v2.id                AS neighbor_valve_id,
      v2.road_name         AS neighbor_road_name,
      'incoming'           AS direction
    """
    return _safe_read(query, {"valve_id": valve_id})


def get_downstream_pipes(to_valve_id: str, exclude_pipe_ids: list[str], depth: int = 8) -> list[dict[str, Any]]:
    """
    Traverse downstream from to_valve_id up to `depth` hops and return
    all PIPE relationships, excluding the target pipe pair.
    Depth must be a literal in the Cypher pattern — cannot be a parameter.
    """
    query = f"""
    MATCH (start:Valve {{id: $valve_id}})-[:PIPE*1..{depth}]->(vn:Valve)
    MATCH ()-[rn:PIPE]->(vn)
    WHERE NOT rn.pipe_id IN $exclude_ids
    RETURN DISTINCT
      rn.pipe_id   AS pipe_id,
      rn.road_name AS road_name,
      rn.status    AS status
    """
    return _safe_read(query, {
        "valve_id": to_valve_id,
        "exclude_ids": exclude_pipe_ids,
    })


def check_alternative_path(from_valve_id: str, to_valve_id: str, exclude_pipe_ids: list[str]) -> bool:
    """Return True if a path exists between the two valves that avoids the target pipe pair."""
    query = """
    MATCH (v1:Valve {id: $from_id}), (v2:Valve {id: $to_id})
    MATCH path = shortestPath((v1)-[:PIPE*1..12]-(v2))
    WHERE NONE(r IN relationships(path) WHERE r.pipe_id IN $exclude_ids)
    RETURN path
    LIMIT 1
    """
    rows = _safe_read(query, {
        "from_id": from_valve_id,
        "to_id": to_valve_id,
        "exclude_ids": exclude_pipe_ids,
    })
    return len(rows) > 0


def update_valve_status(valve_id: str, new_status: str) -> bool:
    """Update a valve's status in Neo4j. Returns True on success."""
    query = """
    MATCH (v:Valve {id: $valve_id})
    SET v.status = $new_status
    RETURN v.id AS id
    """
    rows = _safe_write(query, {"valve_id": valve_id, "new_status": new_status})
    return len(rows) > 0


def update_pipe_status(pipe_id: str, new_status: str) -> bool:
    """Update status on all PIPE relationships with this pipe_id."""
    query = """
    MATCH ()-[p:PIPE {pipe_id: $pipe_id}]->()
    SET p.status = $new_status
    RETURN p.pipe_id AS pipe_id
    """
    rows = _safe_write(query, {"pipe_id": pipe_id, "new_status": new_status})
    return len(rows) > 0


def get_pipe_trace(pipe_id: str, depth: int = 15) -> dict[str, Any]:
    """
    Return all pipe IDs and valve IDs on the downstream path to tail-end valves,
    following the SOP procedure: only traverse pipes on the same road_name (case-
    insensitive) with status='open'. Stop at valves with no further eligible pipes.
    """
    start_rows = _safe_read(
        "MATCH (v1)-[p:PIPE {pipe_id: $pipe_id}]->(v2) "
        "RETURN v1.id AS from_id, v2.id AS to_id, p.road_name AS road_name LIMIT 1",
        {"pipe_id": pipe_id},
    )
    if not start_rows:
        return {"found": False, "origin_pipe_id": pipe_id, "pipe_ids": [], "valve_ids": [], "tail_valve_ids": []}

    from_id = start_rows[0]["from_id"]
    to_id   = start_rows[0]["to_id"]
    road    = start_rows[0]["road_name"]

    params = {"valve_id": to_id, "road_name": road}

    # SOP Steps 5–7: downstream pipes on the same road, open status only
    pipe_rows = _safe_read(f"""
        MATCH path = (start {{id: $valve_id}})-[:PIPE*1..{depth}]->(v)
        WHERE ALL(rel IN relationships(path) WHERE
          toLower(rel.road_name) = toLower($road_name) AND rel.status = 'open')
        UNWIND relationships(path) AS rel
        RETURN DISTINCT rel.pipe_id AS pipe_id
    """, params)

    # Valves along the SOP path
    valve_rows = _safe_read(f"""
        MATCH path = (start {{id: $valve_id}})-[:PIPE*1..{depth}]->(v)
        WHERE ALL(rel IN relationships(path) WHERE
          toLower(rel.road_name) = toLower($road_name) AND rel.status = 'open')
        UNWIND nodes(path) AS n
        RETURN DISTINCT n.id AS node_id
    """, params)

    # SOP Step 8: tail-end valve — reachable via SOP path with no further open same-road pipe
    tail_rows = _safe_read(f"""
        MATCH path = (start {{id: $valve_id}})-[:PIPE*1..{depth}]->(v)
        WHERE ALL(rel IN relationships(path) WHERE
          toLower(rel.road_name) = toLower($road_name) AND rel.status = 'open')
        WITH DISTINCT v
        OPTIONAL MATCH (v)-[r_out:PIPE]->(next)
        WHERE toLower(r_out.road_name) = toLower($road_name) AND r_out.status = 'open'
        WITH v, r_out WHERE r_out IS NULL
        RETURN DISTINCT v.id AS valve_id
    """, params)

    return {
        "found": True,
        "origin_pipe_id": pipe_id,
        "pipe_ids": [pipe_id, *(r["pipe_id"] for r in pipe_rows)],
        "valve_ids": list({from_id, to_id, *(r["node_id"] for r in valve_rows)}),
        "tail_valve_ids": [r["valve_id"] for r in tail_rows],
    }


def get_full_graph() -> dict[str, Any]:
    """Return all nodes and edges as Cytoscape-compatible JSON for the web visualiser."""
    query = """
    MATCH (v1)-[p:PIPE]->(v2)
    RETURN
      v1.id                AS source_id,
      labels(v1)[0]        AS source_type,
      properties(v1)       AS source_props,
      v2.id                AS target_id,
      labels(v2)[0]        AS target_type,
      properties(v2)       AS target_props,
      properties(p)        AS pipe_props
    """
    rows = _safe_read(query, {})
    nodes: dict[str, Any] = {}
    edges: list[dict[str, Any]] = []
    for r in rows:
        for node_id, node_type, props in [
            (r["source_id"], r["source_type"], r["source_props"]),
            (r["target_id"], r["target_type"], r["target_props"]),
        ]:
            if node_id not in nodes:
                nodes[node_id] = {
                    "data": {"id": node_id, "label": node_id, "type": node_type, **dict(props)}
                }
        pipe = dict(r["pipe_props"])
        edges.append({
            "data": {
                "id": pipe["pipe_id"],
                "source": r["source_id"],
                "target": r["target_id"],
                **pipe,
            }
        })
    return {"nodes": list(nodes.values()), "edges": edges}


def get_schema_overview() -> list[dict[str, Any]]:
    """Return node labels and relationship types present in the graph."""
    query = "CALL db.labels() YIELD label RETURN label"
    labels = _safe_read(query, {})
    query2 = "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
    rel_types = _safe_read(query2, {})
    return {"labels": labels, "relationship_types": rel_types}
