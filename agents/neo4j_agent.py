import logging
from schemas.graph_state import OrchestratorState, TopologyContext
from tools.neo4j_tools import (
    get_pipe_and_valves,
    get_partner_pipe,
    get_neighborhood_pipes,
    get_downstream_pipes,
    check_alternative_path,
)

logger = logging.getLogger(__name__)


def neo4j_agent_node(state: OrchestratorState) -> dict:
    pipe_id = state.get("pipe_id", "")
    if not pipe_id:
        return {
            "error_messages": state.get("error_messages", []) + ["No pipe_id provided to Neo4j agent."],
            "agents_completed": state.get("agents_completed", []) + ["neo4j"],
        }

    try:
        pipe_data = get_pipe_and_valves(pipe_id)
    except Exception as e:
        logger.error("Neo4j agent failed to fetch pipe %s: %s", pipe_id, e)
        pipe_data = {}

    if not pipe_data:
        return {
            "topology_context": None,
            "error_messages": state.get("error_messages", []) + [
                f"Pipe '{pipe_id}' was not found in the water network. Please verify the pipe ID."
            ],
            "agents_completed": state.get("agents_completed", []) + ["neo4j"],
        }

    from_valve = pipe_data["from_valve"]
    to_valve = pipe_data["to_valve"]
    pipe_props = pipe_data["pipe_props"]
    from_id = from_valve.get("id", "")
    to_id = to_valve.get("id", "")

    # Bidirectional partner
    try:
        partner_id = get_partner_pipe(pipe_id, from_id, to_id)
    except Exception:
        partner_id = None

    exclude_ids = [pid for pid in [pipe_id, partner_id] if pid]

    # Neighborhood
    try:
        neighborhood = get_neighborhood_pipes(from_id) + get_neighborhood_pipes(to_id)
        seen = set()
        unique_neighborhood = []
        for p in neighborhood:
            pid = p.get("pipe_id")
            if pid and pid not in seen and pid not in exclude_ids:
                seen.add(pid)
                unique_neighborhood.append(dict(p))
    except Exception as e:
        logger.warning("Neighborhood fetch error: %s", e)
        unique_neighborhood = []

    # Downstream pipes
    try:
        downstream_pipes = get_downstream_pipes(to_id, exclude_ids)
        downstream_pipes = [dict(p) for p in downstream_pipes]
    except Exception as e:
        logger.warning("Downstream pipe fetch error: %s", e)
        downstream_pipes = []

    # Alternative path
    try:
        alt_path = check_alternative_path(from_id, to_id, exclude_ids)
    except Exception:
        alt_path = False

    context = TopologyContext(
        pipe_id=pipe_id,
        partner_pipe_id=partner_id,
        from_valve=from_valve,
        to_valve=to_valve,
        pipe_props=pipe_props,
        downstream_pipes=downstream_pipes,
        alternative_path_exists=alt_path,
        neighborhood_pipes=unique_neighborhood,
    )

    return {
        "topology_context": context,
        "agents_completed": state.get("agents_completed", []) + ["neo4j"],
    }
