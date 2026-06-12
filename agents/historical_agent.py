import logging
from schemas.graph_state import OrchestratorState, HistoricalContext
from tools.chroma_tools import search_historical_plans

logger = logging.getLogger(__name__)


def historical_agent_node(state: OrchestratorState) -> dict:
    topo = state.get("topology_context")
    op_type = state.get("operation_type", "SHUTDOWN")
    pipe_id = state.get("pipe_id", "")

    if topo:
        pipe_props = topo.get("pipe_props", {})
        diameter = pipe_props.get("diameter_mm", "")
        material = pipe_props.get("material", "")
        road = pipe_props.get("road_name", "")
        query = (
            f"historical operations plan {op_type.lower()} {diameter}mm {material} pipe "
            f"{road} valve isolation sequence steps"
        )
    else:
        query = f"historical operations plan {op_type.lower()} pipe {pipe_id} valve sequence"

    chunks = search_historical_plans(query, n_results=3)

    # Format chunks into similar_plans for the ops plan generator
    plan_groups: dict[str, list[str]] = {}
    for c in chunks:
        meta = c.get("metadata", {})
        plan_id = meta.get("plan_id", c["id"])
        plan_groups.setdefault(plan_id, []).append(c["text"])

    similar_plans = []
    for plan_id, texts in plan_groups.items():
        # Find representative metadata from first chunk
        rep_chunk = next((c for c in chunks if c.get("metadata", {}).get("plan_id") == plan_id), chunks[0])
        meta = rep_chunk.get("metadata", {})
        similar_plans.append({
            "plan_id": plan_id,
            "plan_title": meta.get("plan_title", plan_id),
            "pipe_id": meta.get("pipe_id", ""),
            "outcome": meta.get("outcome", ""),
            "combined_text": "\n".join(texts),
            "similarity_score": rep_chunk.get("similarity_score", 0.0),
        })

    return {
        "historical_context": HistoricalContext(
            retrieved_chunks=chunks,
            similar_plans=similar_plans,
        ),
        "agents_completed": state.get("agents_completed", []) + ["historical"],
    }
