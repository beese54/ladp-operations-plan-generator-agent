import time
from uuid import uuid4
import httpx
import streamlit as st

API_BASE = "http://localhost:8000/api/v1"

st.set_page_config(
    page_title="Water Network Ops Generator",
    page_icon="💧",
    layout="wide",
)

st.title("💧 Water Network Operations Plan Generator")
st.caption("Ask about pipe shutdowns, maintenance windows, or general network questions.")

# ─── Session state ────────────────────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

# Sidebar
with st.sidebar:
    st.header("Session")
    st.code(st.session_state.session_id[:8] + "...")
    if st.button("New Session"):
        st.session_state.session_id = str(uuid4())
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.subheader("API Health")
    if st.button("Check Health"):
        try:
            resp = httpx.get(f"{API_BASE}/health", timeout=10)
            data = resp.json()
            for svc, status in data.items():
                if svc in ("neo4j", "chromadb", "sqlite", "anthropic"):
                    icon = "✅" if status == "OK" else "❌"
                    st.write(f"{icon} **{svc}**: {status}")
        except Exception as e:
            st.error(f"API unreachable: {e}")

# ─── Chat history ─────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("plan_meta"):
            meta = msg["plan_meta"]
            verdict = meta.get("feasibility")
            if verdict:
                colour = {"FEASIBLE": "green", "NOT_FEASIBLE": "red", "CONDITIONAL": "orange"}.get(verdict, "grey")
                st.markdown(
                    f'<span style="background:{colour};color:white;padding:2px 8px;'
                    f'border-radius:4px;font-weight:bold">{verdict}</span>',
                    unsafe_allow_html=True,
                )

# ─── Input ────────────────────────────────────────────────────────────────────
if user_input := st.chat_input("e.g. Can I shut down pipe_151 on 2026-06-01 from 08:00 to 16:00?"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Analysing network, checking schedule, generating plan..."):
            t0 = time.monotonic()
            try:
                response = httpx.post(
                    f"{API_BASE}/chat",
                    json={
                        "session_id": st.session_state.session_id,
                        "message": user_input,
                    },
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as e:
                data = {"message": f"API error {e.response.status_code}: {e.response.text}"}
            except Exception as e:
                data = {"message": f"Could not reach API: {e}"}

        elapsed = time.monotonic() - t0
        message = data.get("message", "")
        st.markdown(message)

        plan_meta = {}
        feasibility = data.get("feasibility")
        if feasibility:
            colour = {"FEASIBLE": "green", "NOT_FEASIBLE": "red", "CONDITIONAL": "orange"}.get(feasibility, "grey")
            st.markdown(
                f'<span style="background:{colour};color:white;padding:2px 8px;'
                f'border-radius:4px;font-weight:bold">{feasibility}</span>',
                unsafe_allow_html=True,
            )
            plan_meta["feasibility"] = feasibility

        # Expandable raw plan JSON
        if data.get("has_plan") and data.get("operations_plan"):
            with st.expander("📋 Full Plan JSON", expanded=False):
                st.json(data["operations_plan"])

        st.caption(f"⏱ {elapsed:.1f}s | Pipe: {data.get('pipe_id', '—')} | Date: {data.get('target_date', '—')}")

    st.session_state.messages.append({
        "role": "assistant",
        "content": message,
        "plan_meta": plan_meta,
    })
