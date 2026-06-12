from db.neo4j_client import execute_read


def q(cypher, params):
    try:
        return execute_read(cypher, params)
    except Exception as e:
        return []


# ── Steps 1–9: find tail-end valve ───────────────────────────────────────────

origin = q(
    "MATCH (v1)-[p:PIPE {pipe_id: $pid}]->(v2) "
    "RETURN v1.id AS from_id, v2.id AS to_id, p.road_name AS road, p.status AS status LIMIT 1",
    {"pid": "pipe_084"},
)
if not origin:
    print("pipe_084 not found")
    raise SystemExit(1)

row = origin[0]
from_id = row["from_id"]
to_id = row["to_id"]
road = row["road"]
status = row["status"]

print("SOP Walkthrough -- pipe_084")
print("-" * 60)
print(f"Origin pipe : pipe_084  ({from_id} -> {to_id})")
print(f"Road name   : {road}")
print(f"Pipe status : {status}")
print()
print("-- Steps 1-9: Trace downstream to tail-end valve --")

pipes_in_chain = ["pipe_084"]
valves_in_chain = [from_id, to_id]
step = 1
current_valve = to_id

while True:
    nxt = q(
        "MATCH (v:Valve {id: $vid})-[p:PIPE]->(v2:Valve) "
        "WHERE toLower(p.road_name) = toLower($road) AND p.status = 'open' "
        "RETURN p.pipe_id AS pipe_id, v2.id AS next_valve, "
        "p.road_name AS road_name, p.status AS pstatus LIMIT 1",
        {"vid": current_valve, "road": road},
    )
    if not nxt:
        print(f"Step {step}  Current valve: {current_valve}  ->  no further open same-road pipe")
        print(f"       *** TAIL-END VALVE: {current_valve} ***")
        tail_valve = current_valve
        break
    r = nxt[0]
    print(
        f"Step {step}  Current valve: {current_valve}  ->  pipe: {r['pipe_id']}  "
        f"->  next valve: {r['next_valve']}  "
        f"(road: {r['road_name']}, status: {r['pstatus']})"
    )
    pipes_in_chain.append(r["pipe_id"])
    valves_in_chain.append(r["next_valve"])
    current_valve = r["next_valve"]
    step += 1

# ── Step 9: Alternate feed check at tail-end valve ───────────────────────────

print()
print("-- Step 9: Alternate feed check --")

# All pipes touching the tail-end valve
all_touching = q(
    "MATCH ()-[p:PIPE]->(v:Valve {id: $vid}) "
    "RETURN p.pipe_id AS pipe_id, p.from_id AS from_id, p.to_id AS to_id, p.status AS status",
    {"vid": tail_valve},
)

# Exclude pipes whose from_id is already in the shutdown chain
visited_valves = set(valves_in_chain)
candidates = [
    r for r in all_touching
    if r["from_id"] not in visited_valves
]

alternate_feed = None
if not candidates:
    print(f"  No pipes feeding into {tail_valve} from outside the shutdown chain.")
    print("  Result: NO alternate feed available. Stopping at step 9.")
else:
    for r in candidates:
        pstatus = r["status"] or "unknown"
        print(f"  Candidate pipe: {r['pipe_id']}  from_id: {r['from_id']}  status: {pstatus}")
        if pstatus == "open" and alternate_feed is None:
            alternate_feed = r["pipe_id"]

    if alternate_feed:
        print(f"  Result: Alternate feed AVAILABLE via pipe {alternate_feed}")
    else:
        print("  Result: All candidate pipes are closed. NO alternate feed available. Stopping at step 9.")

# ── Step 10: Record sequential shutdown chain ─────────────────────────────────

print()
print("-- Step 10: Sequential shutdown chain --")
print(f"  Pipes  : {' -> '.join(pipes_in_chain)}")
print(f"  Valves : {' -> '.join(dict.fromkeys(valves_in_chain))}")
print(f"  Tail-end valve: {tail_valve}")

# ── Step 11: Branch on alternate feed ────────────────────────────────────────

print()
print("-- Step 11: Branch --")
if not alternate_feed:
    print("  No alternate feed found in step 9. Stopping here.")
    raise SystemExit(0)
print(f"  Alternate feed exists ({alternate_feed}). Proceeding to step 12.")

# ── Step 12: Backwards trace — verify reverse pipes are closed ────────────────

print()
print("-- Step 12: Backwards trace (isolation verification) --")

# Reverse the valve chain: tail_valve -> ... -> from_id
reverse_chain = list(dict.fromkeys(valves_in_chain))[::-1]

all_ok = True
for i in range(len(reverse_chain) - 1):
    current = reverse_chain[i]
    nxt_valve = reverse_chain[i + 1]
    rows = q(
        "MATCH (v1:Valve {id: $from_id})-[p:PIPE]->(v2:Valve {id: $to_id}) "
        "RETURN p.pipe_id AS pipe_id, p.status AS status LIMIT 1",
        {"from_id": current, "to_id": nxt_valve},
    )
    if not rows:
        print(f"  {current} -> {nxt_valve}  : no reverse pipe found")
        all_ok = False
    else:
        r = rows[0]
        ok = r["status"] == "closed"
        mark = "OK" if ok else "FAIL"
        print(f"  {current} -> {nxt_valve}  pipe: {r['pipe_id']}  status: {r['status']}  [{mark}]")
        if not ok:
            all_ok = False
            print(f"    *** Pipe {r['pipe_id']} is NOT closed. Stopping — inform user. ***")

print()
if all_ok:
    print("  All reverse pipes are closed. Isolation verified.")
else:
    print("  One or more reverse pipes are NOT closed. Isolation incomplete.")

print()
print("-" * 60)
print("Walkthrough complete.")
