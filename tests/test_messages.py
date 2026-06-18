"""Transcript accumulation: the messages channel appends and survives fresh turns."""
import operator
import sqlite3
from typing import Annotated

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver


class _M(TypedDict):
    messages: Annotated[list, operator.add]


def _noop(state):
    return {}


def _app(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "m.db"), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    g = StateGraph(_M)
    g.add_node("n", _noop)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=saver)


def test_messages_append_and_persist_across_turns(tmp_path):
    app = _app(tmp_path)
    cfg = {"configurable": {"thread_id": "s"}}

    # Turn 1: run with empty input, then record the exchange (mirrors _record_turn).
    app.invoke({"messages": []}, config=cfg)
    app.update_state(cfg, {"messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]})

    # Turn 2: a *fresh* run passes messages=[] — operator.add appends nothing, so
    # the prior transcript must be preserved, then the new turn is recorded.
    app.invoke({"messages": []}, config=cfg)
    app.update_state(cfg, {"messages": [
        {"role": "user", "content": "bye"},
        {"role": "assistant", "content": "cya"},
    ]})

    msgs = app.get_state(cfg).values["messages"]
    assert [m["content"] for m in msgs] == ["hi", "hello", "bye", "cya"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
