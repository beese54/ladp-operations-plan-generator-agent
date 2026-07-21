"""Deterministic schematic diagram of an SOP shutdown chain, for the PDF report.

A clean, generated left-to-right diagram of just the valves/pipes the isolation
touches — not a screenshot of the live Cytoscape graph — so it always renders
fast, with no browser dependency, and stays legible on paper. Colour language
mirrors the app (frontend/src/components/GraphCanvas.jsx): closed=red,
open=green.
"""
from __future__ import annotations

import io
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

_CLOSED_COLOR = "#dc2626"
_OPEN_COLOR = "#16a34a"
_TEXT_COLOR = "#0f172a"
_MUTED_COLOR = "#64748b"
_NODE_RADIUS = 0.16


def render_chain_diagram(chain: dict[str, Any]) -> bytes:
    """Render the isolation chain as a PNG (white background, print-friendly).

    Top row: forward shutdown chain (origin -> tail), each valve CLOSED —
    the isolation act itself. Bottom row (only when an alternate feed
    exists): the re-feed/reverse chain, each valve reopened, plus the
    alternate-feed valve branching in. A valve that is closed then later
    reopened appears once in each row — this mirrors the SOP walkthrough's
    own two-phase structure (downstream trace, then re-feed reversal), so
    the diagram reads the same way the step table above it is organised.
    """
    shutdown_valves = chain.get("shutdown_valves", [])
    shutdown_pipes = chain.get("shutdown_pipes", [])
    alt = chain.get("alternate_feed")
    reverse_checks = chain.get("reverse_checks", [])
    tail = chain.get("tail_valve_id", "")

    n = len(shutdown_valves)
    x_of = {vid: i for i, vid in enumerate(shutdown_valves)}

    fig_w = max(4.0, n * 1.6)
    fig_h = 5.0 if alt else 3.2
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=150)
    ax.set_facecolor("#ffffff")
    fig.patch.set_facecolor("#ffffff")

    def draw_node(x, y, label, color, tag=None):
        ax.add_patch(Circle((x, y), _NODE_RADIUS, facecolor=color, edgecolor="#0f172a",
                             linewidth=1.2, zorder=3))
        ax.text(x, y - 0.32, label, ha="center", va="top", fontsize=8.5,
                 color=_TEXT_COLOR, fontweight="bold", zorder=4)
        if tag:
            ax.text(x, y + 0.32, tag, ha="center", va="bottom", fontsize=7,
                    color=_MUTED_COLOR, zorder=4)

    def draw_edge(x0, y0, x1, y1, open_: bool, label=None, dotted=False):
        color = _OPEN_COLOR if open_ else _CLOSED_COLOR
        if dotted:
            linestyle = (0, (1, 2))
        elif open_:
            linestyle = "-"
        else:
            linestyle = (0, (5, 3))
        ax.plot([x0, x1], [y0, y1], color=color, linewidth=2.2, linestyle=linestyle,
                zorder=2, solid_capstyle="round")
        if label:
            ax.text((x0 + x1) / 2, (y0 + y1) / 2 + 0.14, label, ha="center", va="bottom",
                    fontsize=7, color=_MUTED_COLOR, zorder=4,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))

    # ── Top row: forward shutdown chain (Steps 1..n, all CLOSE) ──
    for i, vid in enumerate(shutdown_valves):
        tag = f"Step {i + 1}: CLOSE" + ("  (TAIL)" if vid == tail else "")
        draw_node(i, 1.0, vid, _CLOSED_COLOR, tag)
    for i, pid in enumerate(shutdown_pipes):
        if i + 1 < n:
            draw_edge(i, 1.0, i + 1, 1.0, open_=False, label=pid)

    if alt:
        # ── Bottom row: alternate feed + re-feed/reverse chain ──
        alt_seq = n + 1
        alt_x = (n - 1) + 0.9
        draw_node(alt_x, 0.0, alt["from_valve_id"], _OPEN_COLOR,
                  f"Step {alt_seq}: OPEN (alt. feed)")
        tail_x = x_of.get(tail)
        if tail_x is not None:
            draw_edge(alt_x, 0.0, tail_x, -1.0, open_=True, label=alt.get("pipe_id"), dotted=True)

        bottom_valves = {p["from_valve"] for p in reverse_checks}
        for j, pair in enumerate(reverse_checks):
            fx = x_of.get(pair["from_valve"])
            if fx is not None:
                draw_node(fx, -1.0, pair["from_valve"], _OPEN_COLOR, f"Step {alt_seq + 1 + j}: OPEN")

        for pair in reverse_checks:
            fx = x_of.get(pair["from_valve"])
            to_v = pair["to_valve"]
            tx = x_of.get(to_v)
            if fx is None or tx is None:
                continue
            if to_v in bottom_valves:
                draw_edge(fx, -1.0, tx, -1.0, open_=True, label=pair.get("pipe_id"))
            else:
                # Terminates at a valve with no bottom node — the origin, which
                # stays closed, so the pipe segment stays blocked at that end.
                draw_edge(fx, -1.0, tx, 1.0, open_=False, label=pair.get("pipe_id"))
    else:
        ax.text((max(n - 1, 0)) / 2, -0.2,
                "NO ALTERNATE FEED\nservice interrupted downstream",
                ha="center", va="top", fontsize=9, color=_CLOSED_COLOR, fontweight="bold")

    ax.plot([], [], color=_CLOSED_COLOR, linestyle=(0, (5, 3)), linewidth=2, label="Closed")
    ax.plot([], [], color=_OPEN_COLOR, linestyle="-", linewidth=2, label="Open")
    ax.plot([], [], color=_OPEN_COLOR, linestyle=(0, (1, 2)), linewidth=2, label="Alternate feed")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.02), ncol=3, frameon=False,
              fontsize=8, handlelength=2.2)

    legend_y = -1.9 if alt else -1.0
    ax.set_xlim(-0.6, max(n - 0.4, n + 0.4))
    ax.set_ylim(legend_y - 0.6, 1.7)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="#ffffff", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
