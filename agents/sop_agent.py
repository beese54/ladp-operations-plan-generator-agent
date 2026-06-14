import json
import logging
from config.settings import get_settings, get_llm_client
from schemas.graph_state import OrchestratorState, SOPContext
from tools.chroma_tools import search_sop_documents

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a water network operations SOP specialist.
You will be given excerpts from Standard Operating Procedure documents.
Your task is to extract the key principles relevant to the operation described.
Return a JSON array of concise principle strings. Each principle should be one clear sentence.
Example output:
["Close the upstream isolation valve before the downstream valve.",
 "Allow 15 minutes after closing for pressure to equalise before opening any drain."]
Return ONLY the JSON array, no other text."""


def sop_agent_node(state: OrchestratorState) -> dict:
    topo = state.get("topology_context")
    op_type = state.get("operation_type", "SHUTDOWN")

    # Build a rich semantic query from topology context
    if topo:
        pipe_props = topo.get("pipe_props", {})
        diameter = pipe_props.get("diameter_mm", "")
        material = pipe_props.get("material", "")
        road = pipe_props.get("road_name", "")
        query = (
            f"{op_type.lower()} procedure for {diameter}mm {material} pipe "
            f"on {road}. valve isolation sequence and safety checks."
        )
    else:
        query = f"{op_type.lower()} procedure for water pipe valve isolation and safety checks"

    chunks = search_sop_documents(query, n_results=5)

    if not chunks:
        return {
            "sop_context": SOPContext(retrieved_chunks=[], relevant_principles=[]),
            "agents_completed": state.get("agents_completed", []) + ["sop"],
        }

    # Summarise principles via Together.ai (or Azure OpenAI if configured)
    principles = _summarise_principles(chunks, op_type)

    return {
        "sop_context": SOPContext(retrieved_chunks=chunks, relevant_principles=principles),
        "agents_completed": state.get("agents_completed", []) + ["sop"],
    }


def _summarise_principles(chunks: list[dict], op_type: str) -> list[str]:
    s = get_settings()
    client = get_llm_client("sop_agent")
    if client is None:
        return [c["text"][:200] for c in chunks[:3]]

    combined = "\n\n---\n\n".join(c["text"] for c in chunks)
    user_msg = f"Operation type: {op_type}\n\nSOP Excerpts:\n{combined}"

    try:
        provider = s.agent_providers.get("sop_agent", "together")
        model = (
            s.azure_openai_chat_deployment_name if provider == "azure"
            else s.together_model
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_completion_tokens=512,
            temperature=0.2,
        )
        raw = response.choices[0].message.content or "[]"

        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        logger.error("SOP principle summarisation failed: %s", e)
        return [c["text"][:200] for c in chunks[:3]]
