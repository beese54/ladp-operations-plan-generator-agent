"""Assemble the confirmed-operation PDF isolation report.

Generated on demand from an operation_id: fetches the booked window from the
calendar (data/calendar.db), rebuilds the SOP shutdown chain fresh from Neo4j,
lays the valve actions out against the booked start (reporting/timeline.py),
renders a schematic diagram (reporting/network_diagram.py), and assembles the
result as a PDF via reportlab. Nothing is cached at booking time — the report
always reflects the current network topology, consistent with how the chat's
"show the steps" reply already works.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from prompts.sop_walkthrough_prompt import build_sop_chain_data
from reporting.network_diagram import render_chain_diagram
from reporting.timeline import build_step_schedule
from tools.calendar_tools import get_operation

_HEADER_BG = colors.HexColor("#0f172a")
_OPEN_COLOR = colors.HexColor("#15803d")
_CLOSED_COLOR = colors.HexColor("#b91c1c")
_MUTED_COLOR = colors.HexColor("#64748b")
_ROW_ALT_BG = colors.HexColor("#f1f5f9")


class ReportNotFoundError(Exception):
    """The operation or its pipe could not be found — maps to HTTP 404."""


class ReportGenerationError(Exception):
    """The report could not be rendered — maps to HTTP 500."""


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def build_operation_report_pdf(operation_id: str) -> bytes:
    op = get_operation(operation_id)
    if op is None:
        raise ReportNotFoundError(f"Operation '{operation_id}' not found.")

    pipe_id = op.get("pipe_id") or ""
    try:
        chain = build_sop_chain_data(pipe_id)
    except ValueError as e:
        raise ReportNotFoundError(str(e)) from e
    except Exception as e:
        raise ReportGenerationError(f"Failed to rebuild SOP chain for '{pipe_id}': {e}") from e

    try:
        steps, start_dt, end_dt, working_days = build_step_schedule(chain, op["scheduled_start"])
        diagram_png = render_chain_diagram(chain)
        return _assemble_pdf(op, chain, steps, start_dt, end_dt, working_days, diagram_png)
    except (ReportNotFoundError, ReportGenerationError):
        raise
    except Exception as e:
        raise ReportGenerationError(f"Failed to render report for '{operation_id}': {e}") from e


def _assemble_pdf(
    op: dict[str, Any],
    chain: dict[str, Any],
    steps: list,
    start_dt: datetime,
    end_dt: datetime,
    working_days: list,
    diagram_png: bytes,
) -> bytes:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=16, spaceAfter=2,
    )
    meta_style = ParagraphStyle(
        "ReportMeta", parent=styles["Normal"], fontSize=9.5, textColor=_MUTED_COLOR,
        spaceAfter=2,
    )
    heading_style = ParagraphStyle(
        "ReportHeading", parent=styles["Heading2"], fontSize=12.5, spaceBefore=14,
        spaceAfter=6,
    )
    note_style = ParagraphStyle(
        "ReportNote", parent=styles["Normal"], fontSize=9, textColor=_MUTED_COLOR,
    )
    warn_style = ParagraphStyle(
        "ReportWarn", parent=styles["Normal"], fontSize=9.5, textColor=_CLOSED_COLOR,
    )
    cell_style = ParagraphStyle(
        "ReportCell", parent=styles["Normal"], fontSize=8.5, leading=10.5,
    )
    open_cell_style = ParagraphStyle(
        "ReportOpenCell", parent=cell_style, textColor=_OPEN_COLOR, fontName="Helvetica-Bold",
    )
    closed_cell_style = ParagraphStyle(
        "ReportClosedCell", parent=cell_style, textColor=_CLOSED_COLOR, fontName="Helvetica-Bold",
    )

    pipe_id = chain.get("pipe_id", "")
    road = chain.get("pipe_road_name", "")
    op_class = (op.get("operation_class") or "PLANNED").upper()
    db_start = op.get("scheduled_start", "")
    db_end = op.get("scheduled_end", "")

    story: list = []
    story.append(Paragraph(f"Pipe Isolation Report — {pipe_id}", title_style))
    story.append(Paragraph(
        f"Operation <b>{op.get('operation_id', '')}</b> &middot; {op_class} &middot; "
        f"{road or 'road unknown'}", meta_style,
    ))
    story.append(Paragraph(
        f"Booked window: {db_start} &rarr; {db_end}  "
        f"({len(working_days)} working day{'s' if len(working_days) != 1 else ''})", meta_style,
    ))

    try:
        recomputed_end = _fmt_dt(end_dt)
        db_end_fmt = datetime.fromisoformat(db_end).strftime("%Y-%m-%d %H:%M") if db_end else ""
        if db_end_fmt and recomputed_end != db_end_fmt:
            story.append(Paragraph(
                f"Note: the live network topology now computes a step schedule ending "
                f"{recomputed_end}, which differs from the booked end {db_end_fmt} — "
                f"the operation may have been rescheduled or the network has since changed.",
                warn_style,
            ))
    except (ValueError, TypeError):
        pass

    story.append(Paragraph(
        "Day 1 begins with SOP setup/mobilisation before the first valve action below.",
        note_style,
    ))

    # ── Network diagram ──
    story.append(Paragraph("Network Diagram", heading_style))
    img = Image(io.BytesIO(diagram_png), width=170 * mm, height=90 * mm, kind="proportional")
    story.append(img)

    # ── Step-by-step table ──
    # Body cells use Paragraph (not plain strings) so long content — e.g. the
    # "(spans overnight)" time suffix — wraps within the column instead of
    # overflowing into the next cell (plain strings in reportlab Tables don't wrap).
    story.append(Paragraph("Step-by-Step Isolation Walkthrough", heading_style))
    header = ["#", "Date", "Time", "Action", "Valve", "Pipe"]
    rows = [header]
    for s in steps:
        time_cell = f"{s.start.strftime('%H:%M')}-{s.end.strftime('%H:%M')}"
        if s.day_split:
            time_cell += " (spans overnight)"
        action_style = open_cell_style if s.action == "OPEN" else closed_cell_style
        rows.append([
            Paragraph(str(s.seq), cell_style),
            Paragraph(_fmt_date(s.start), cell_style),
            Paragraph(time_cell, cell_style),
            Paragraph(s.action, action_style),
            Paragraph(s.valve_id, cell_style),
            Paragraph(s.pipe_id or "—", cell_style),
        ])

    table = Table(rows, colWidths=[12 * mm, 24 * mm, 34 * mm, 22 * mm, 26 * mm, 26 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT_BG]),
    ]))
    story.append(table)

    # ── Customer impact ──
    tail = chain.get("tail_valve_id", "")
    alt = chain.get("alternate_feed")
    downstream = chain.get("downstream_valves_with_roads", [])
    affected = [v for v in downstream if v["valve_id"] != tail] if alt else list(downstream)
    story.append(Paragraph("Customer Impact", heading_style))
    if affected:
        rows = [["Valve", "Road"]] + [
            [Paragraph(v["valve_id"], cell_style), Paragraph(v.get("road_name", ""), cell_style)]
            for v in affected
        ]
        impact_table = Table(rows, colWidths=[40 * mm, 100 * mm], repeatRows=1)
        impact_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT_BG]),
        ]))
        story.append(impact_table)
        if alt:
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                f"`{tail}` is spared — supplied by alternate feed `{alt['pipe_id']}`.",
                note_style,
            ))
    else:
        story.append(Paragraph("No downstream consumers are affected.", note_style))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} &middot; "
        f"{op.get('operation_id', '')} &middot; for authorized field operations use.",
        note_style,
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
        title=f"Isolation Report — {pipe_id}",
    )
    doc.build(story)
    return buf.getvalue()
