// neo4j_seed.cypher
// AUGMENT-ONLY seed script for the Water Network Operations Plan Generator.
// Uses MERGE to avoid duplicates. Does NOT delete any existing nodes or relationships.
//
// Run this in Neo4j Aura Browser or via cypher-shell:
//   cypher-shell -u neo4j -p <password> -a neo4j+s://xxxx.databases.neo4j.io < data/seed/neo4j_seed.cypher
//
// Before running, inspect the existing schema:
//   CALL db.schema.visualization()
//   CALL db.labels()
//   CALL db.relationshipTypes()

// ─── Constraints (safe to re-run) ─────────────────────────────────────────────
CREATE CONSTRAINT valve_id_unique IF NOT EXISTS FOR (v:Valve) REQUIRE v.id IS UNIQUE;
CREATE CONSTRAINT junction_id_unique IF NOT EXISTS FOR (j:Junction) REQUIRE j.junction_id IS UNIQUE;
CREATE CONSTRAINT tank_id_unique IF NOT EXISTS FOR (t:Tank) REQUIRE t.id IS UNIQUE;

// ─── Tank (Water Source) Nodes ────────────────────────────────────────────────
MERGE (t1:Tank {id: "TANK-001"})
SET t1.capacity_mgd = 5.0;

MERGE (t2:Tank {id: "TANK-002"})
SET t2.capacity_mgd = 3.5;

// ─── Valve Nodes ──────────────────────────────────────────────────────────────
MERGE (va:Valve {id: "V-TEST-001"})
SET va.road_name = "Main Street",
    va.status = "OPEN",
    va.pressure_mRL = 45.2,
    va.year_installed = 2005;

MERGE (vb:Valve {id: "V-TEST-002"})
SET vb.road_name = "Main Street",
    vb.status = "OPEN",
    vb.pressure_mRL = 44.8,
    vb.year_installed = 2005;

MERGE (vc:Valve {id: "V-TEST-003"})
SET vc.road_name = "Oak Avenue",
    vc.status = "OPEN",
    vc.pressure_mRL = 43.5,
    vc.year_installed = 2010;

MERGE (vd:Valve {id: "V-TEST-004"})
SET vd.road_name = "Oak Avenue",
    vd.status = "OPEN",
    vd.pressure_mRL = 43.1,
    vd.year_installed = 2010;

MERGE (ve:Valve {id: "V-TEST-005"})
SET ve.road_name = "River Road",
    ve.status = "OPEN",
    ve.pressure_mRL = 42.0,
    ve.year_installed = 2015;

// ─── Pipe Relationships (bidirectional pairs) ──────────────────────────────────
// Pair 1: V-TEST-001 ↔ V-TEST-002 (Main Street trunk)
MERGE (va:Valve {id: "V-TEST-001"})-[p151:PIPE {pipe_id: "pipe_test_151"}]->(vb:Valve {id: "V-TEST-002"})
SET p151.from_id = "V-TEST-001",
    p151.to_id = "V-TEST-002",
    p151.diameter_mm = 300,
    p151.length_m = 125.0,
    p151.material = "DI",
    p151.status = "ACTIVE",
    p151.road_name = "Main Street",
    p151.year_installed = 2005,
    p151.has_customer = false,
    p151.Number_of_customers = 0;

MERGE (vb:Valve {id: "V-TEST-002"})-[p152:PIPE {pipe_id: "pipe_test_152"}]->(va:Valve {id: "V-TEST-001"})
SET p152.from_id = "V-TEST-002",
    p152.to_id = "V-TEST-001",
    p152.diameter_mm = 300,
    p152.length_m = 125.0,
    p152.material = "DI",
    p152.status = "ACTIVE",
    p152.road_name = "Main Street",
    p152.year_installed = 2005,
    p152.has_customer = false,
    p152.Number_of_customers = 0;

// Pair 2: V-TEST-002 ↔ V-TEST-003 (Main St to Oak Ave junction — has customers)
MERGE (vb:Valve {id: "V-TEST-002"})-[p153:PIPE {pipe_id: "pipe_test_153"}]->(vc:Valve {id: "V-TEST-003"})
SET p153.from_id = "V-TEST-002",
    p153.to_id = "V-TEST-003",
    p153.diameter_mm = 150,
    p153.length_m = 80.0,
    p153.material = "PVC",
    p153.status = "ACTIVE",
    p153.road_name = "Junction Road",
    p153.year_installed = 2010,
    p153.has_customer = true,
    p153.Number_of_customers = 45;

MERGE (vc:Valve {id: "V-TEST-003"})-[p154:PIPE {pipe_id: "pipe_test_154"}]->(vb:Valve {id: "V-TEST-002"})
SET p154.from_id = "V-TEST-003",
    p154.to_id = "V-TEST-002",
    p154.diameter_mm = 150,
    p154.length_m = 80.0,
    p154.material = "PVC",
    p154.status = "ACTIVE",
    p154.road_name = "Junction Road",
    p154.year_installed = 2010,
    p154.has_customer = true,
    p154.Number_of_customers = 45;

// Pair 3: V-TEST-003 ↔ V-TEST-004 (Oak Avenue main)
MERGE (vc:Valve {id: "V-TEST-003"})-[p155:PIPE {pipe_id: "pipe_test_155"}]->(vd:Valve {id: "V-TEST-004"})
SET p155.from_id = "V-TEST-003",
    p155.to_id = "V-TEST-004",
    p155.diameter_mm = 150,
    p155.length_m = 200.0,
    p155.material = "PVC",
    p155.status = "ACTIVE",
    p155.road_name = "Oak Avenue",
    p155.year_installed = 2010,
    p155.has_customer = true,
    p155.Number_of_customers = 120;

MERGE (vd:Valve {id: "V-TEST-004"})-[p156:PIPE {pipe_id: "pipe_test_156"}]->(vc:Valve {id: "V-TEST-003"})
SET p156.from_id = "V-TEST-004",
    p156.to_id = "V-TEST-003",
    p156.diameter_mm = 150,
    p156.length_m = 200.0,
    p156.material = "PVC",
    p156.status = "ACTIVE",
    p156.road_name = "Oak Avenue",
    p156.year_installed = 2010,
    p156.has_customer = true,
    p156.Number_of_customers = 120;

// Pair 4: V-TEST-004 ↔ V-TEST-005 (River Road termination — dead end)
MERGE (vd:Valve {id: "V-TEST-004"})-[p157:PIPE {pipe_id: "pipe_test_157"}]->(ve:Valve {id: "V-TEST-005"})
SET p157.from_id = "V-TEST-004",
    p157.to_id = "V-TEST-005",
    p157.diameter_mm = 100,
    p157.length_m = 55.0,
    p157.material = "PVC",
    p157.status = "ACTIVE",
    p157.road_name = "River Road",
    p157.year_installed = 2015,
    p157.has_customer = true,
    p157.Number_of_customers = 12;

MERGE (ve:Valve {id: "V-TEST-005"})-[p158:PIPE {pipe_id: "pipe_test_158"}]->(vd:Valve {id: "V-TEST-004"})
SET p158.from_id = "V-TEST-005",
    p158.to_id = "V-TEST-004",
    p158.diameter_mm = 100,
    p158.length_m = 55.0,
    p158.material = "PVC",
    p158.status = "ACTIVE",
    p158.road_name = "River Road",
    p158.year_installed = 2015,
    p158.has_customer = true,
    p158.Number_of_customers = 12;

// ─── Verification ─────────────────────────────────────────────────────────────
// After running, verify with:
//   MATCH (v:Valve) WHERE v.id STARTS WITH 'V-TEST' RETURN count(v) AS test_valves;
//   // Expected: 5
//   MATCH ()-[p:PIPE]->() WHERE p.pipe_id STARTS WITH 'pipe_test' RETURN count(p) AS test_pipes;
//   // Expected: 8
