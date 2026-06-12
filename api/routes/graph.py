from fastapi import APIRouter, HTTPException
from tools.neo4j_tools import get_full_graph, get_pipe_trace

router = APIRouter()


@router.get("/graph")
def graph_data():
    return get_full_graph()


@router.get("/trace/{pipe_id}")
def pipe_trace(pipe_id: str):
    result = get_pipe_trace(pipe_id)
    if not result["found"]:
        raise HTTPException(status_code=404, detail=f"Pipe '{pipe_id}' not found")
    return result
