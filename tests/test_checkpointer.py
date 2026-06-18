"""Durable-checkpointer test: session state survives a 'restart' (new instance)."""
import sqlite3

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command


class _S(TypedDict):
    value: str


def _node(state):
    answer = interrupt({"q": "continue?"})
    return {"value": answer}


def _build(saver):
    g = StateGraph(_S)
    g.add_node("n", _node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=saver)


def test_pending_interrupt_survives_new_saver_instance(tmp_path):
    db = str(tmp_path / "ckpt.db")
    cfg = {"configurable": {"thread_id": "t1"}}

    # First "process": run until it interrupts, then drop the connection.
    conn1 = sqlite3.connect(db, check_same_thread=False)
    saver1 = SqliteSaver(conn1)
    saver1.setup()
    r1 = _build(saver1).invoke({"value": ""}, config=cfg)
    assert "__interrupt__" in r1
    conn1.close()

    # Second "process": brand-new saver/graph on the same file. The pending
    # interrupt must still be there and resumable.
    conn2 = sqlite3.connect(db, check_same_thread=False)
    saver2 = SqliteSaver(conn2)
    saver2.setup()
    g2 = _build(saver2)
    assert g2.get_state(cfg).next  # still paused after "restart"
    r2 = g2.invoke(Command(resume="done"), config=cfg)
    assert r2["value"] == "done"
    conn2.close()
