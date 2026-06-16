"""Restore the water network into Neo4j Aura from a table-data JSON export.

Idempotent / augment-only: uses MERGE, never deletes. Rebuilds Valve nodes and
PIPE relationships from a Neo4j Browser "table data" export (one row per pipe,
with from/to valve properties).

Source export: neo4j_query_table_data_2026-4-29 (1).json (140 pipes, 57 valves).
Known gap: Tank nodes and tank-connected pipes (pipe_001/pipe_002) are NOT in a
valve->valve export and are not restored here.

Usage:
    PYTHONPATH=. python scripts/restore_network_from_export.py [path/to/export.json] [--dry-run]
"""
import json
import sys
from pathlib import Path

from config.settings import get_settings
from neo4j import GraphDatabase

DEFAULT_EXPORT = "neo4j_query_table_data_2026-4-29 (1).json"

VALVE_MERGE = """
MERGE (v:Valve {id: $id})
SET v.road_name = $road,
    v.status    = $status,
    v.elevation = $elevation,
    v.diameter_mm = $diameter
"""

PIPE_MERGE = """
MATCH (a:Valve {id: $from_id}), (b:Valve {id: $to_id})
MERGE (a)-[p:PIPE {pipe_id: $pipe_id}]->(b)
SET p.from_id = $from_id,
    p.to_id   = $to_id,
    p.diameter_mm   = $diameter_mm,
    p.length_m      = $length_m,
    p.material      = $material,
    p.pressure_mRL  = $pressure_mRL,
    p.status        = $status,
    p.road_name     = $road_name,
    p.year_installed = $year_installed
"""


def collect_valves(rows):
    """One row per pipe carries both endpoints' valve properties; dedupe by id."""
    valves = {}
    for r in rows:
        for side in ("from", "to"):
            vid = r[f"{side}_valve_id"]
            valves[vid] = {
                "id": vid,
                "road": r[f"{side}_valve_road"],
                "status": r[f"{side}_valve_status"],
                "elevation": r[f"{side}_valve_elevation"],
                "diameter": r[f"{side}_valve_diameter"],
            }
    return list(valves.values())


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    export_path = Path(args[0]) if args else Path(DEFAULT_EXPORT)

    rows = json.loads(export_path.read_text(encoding="utf-8"))
    valves = collect_valves(rows)
    print(f"Loaded export: {export_path.name}")
    print(f"  valves to MERGE: {len(valves)}")
    print(f"  pipes  to MERGE: {len(rows)}")
    if dry_run:
        print("--dry-run: no writes performed.")
        return

    s = get_settings()
    driver = GraphDatabase.driver(
        s.neo4j_uri, auth=(s.neo4j_username, s.neo4j_password)
    )
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT valve_id_unique IF NOT EXISTS "
            "FOR (v:Valve) REQUIRE v.id IS UNIQUE"
        )
        for v in valves:
            session.run(VALVE_MERGE, **v)
        for r in rows:
            session.run(
                PIPE_MERGE,
                pipe_id=r["pipe_id"],
                from_id=r["p_from_id"],
                to_id=r["p_to_id"],
                diameter_mm=r["pipe_diameter_mm"],
                length_m=r["pipe_length_m"],
                material=r["pipe_material"],
                pressure_mRL=r["pipe_pressure_mRL"],
                status=r["pipe_status"],
                road_name=r["pipe_road_name"],
                year_installed=r["pipe_year_installed"],
            )
        n_v = session.run("MATCH (v:Valve) RETURN count(v) AS c").single()["c"]
        n_p = session.run("MATCH ()-[p:PIPE]->() RETURN count(p) AS c").single()["c"]
    driver.close()
    print(f"Done. Neo4j now has {n_v} valves and {n_p} pipes.")


if __name__ == "__main__":
    main()
