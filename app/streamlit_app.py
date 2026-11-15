"""Streamlit UI:  streamlit run app/streamlit_app.py"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from finagent import AnalystAgent
from finagent.llm import PROVIDERS

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
st.set_page_config(page_title="10-K Analyst Agent", page_icon="📊", layout="wide")


@st.cache_resource(show_spinner="Reading the filing…")
def load_agent(data: bytes, name: str, provider: str, model: str | None) -> AnalystAgent:
    return AnalystAgent.from_bytes(data, name, provider=provider, model=model or None)


with st.sidebar:
    st.title("📊 10-K Analyst Agent")
    st.caption("Ask questions about an SEC filing. Answers cite pages; every number is checked against the filing.")
    provider = st.selectbox("Model", PROVIDERS, index=0)
    model = st.text_input("Model name (optional)")
    if provider == "claude" and not os.getenv("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = st.text_input("Anthropic API key", type="password")
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = st.text_input("OpenAI API key", type="password")
    samples = sorted(p.name for p in SAMPLES.glob("*_10K.*"))
    sample = st.selectbox("…or use a sample filing", ["—", *samples])
    st.caption("Sample companies are fictional. Not investment advice.")

up = st.file_uploader("Upload a 10-K / 10-Q (PDF or EDGAR .htm)", type=["pdf", "htm", "html", "txt"])
src = (up.getvalue(), up.name) if up else ((SAMPLES / sample).read_bytes(), sample) if sample != "—" else None
if src is None:
    st.info("Upload a filing or pick a sample from the sidebar.")
    st.stop()

try:
    agent = load_agent(src[0], src[1], provider, model)
except Exception as e:
    st.error(f"Could not load the filing: {e}")
    st.stop()

st.caption(agent.tools.overview())
tab_chat, tab_fin, tab_pages = st.tabs(["Ask", "Financial statements", "Pages"])

with tab_chat:
    key = f"chat::{src[1]}::{provider}"
    st.session_state.setdefault(key, [])
    examples = ["What is the FY2025 operating margin?", "What was revenue growth from FY2024 to FY2025?",
                "What is the current ratio?", "What share of sales came from the largest customer?"]
    cols = st.columns(len(examples))
    clicked = next((ex for c, ex in zip(cols, examples) if c.button(ex, use_container_width=True)), None)
    for role, content in st.session_state[key]:
        st.chat_message(role).markdown(content)
    q = st.chat_input("Ask about revenue, margins, cash flow, debt, risks…") or clicked
    if q:
        st.chat_message("user").markdown(q)
        with st.spinner("Analysing…"):
            ans = agent.ask(q)
        badge = "✅ verified against the filing" if ans.grounded else "⚠️ unverified"
        src_txt = ", ".join(c.label for c in ans.citations) or "none"
        body = f"{ans.answer}\n\n**Sources:** {src_txt} · {badge}"
        if ans.warnings:
            body += "\n\n" + "\n".join(f"- _{w}_" for w in ans.warnings)
        with st.chat_message("assistant"):
            st.markdown(body)
            with st.expander(f"Agent trace ({len(ans.steps)} tool calls)"):
                for i, s in enumerate(ans.steps, 1):
                    st.markdown(f"**{i}. `{s.tool}`** `{s.args}`")
                    st.code(s.output[:1500])
            for c in ans.citations:
                with st.expander(f"Source {c.label}"):
                    st.text(agent.filing.pages[c.page].text[:3000])
        st.session_state[key] += [("user", q), ("assistant", body)]

with tab_fin:
    items = agent.tools.items
    if not items:
        st.warning("No financial tables detected.")
    else:
        years = sorted({y for it in items for y in it.values}, reverse=True)
        df = pd.DataFrame([{"Statement": (it.statement or "other").replace("_", " "), "Line item": it.label,
                            **{f"FY{y}": it.values.get(y) for y in years}, "Unit": it.unit, "Page": it.page + 1}
                           for it in items])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("Download CSV", df.to_csv(index=False), "line_items.csv", "text/csv")

with tab_pages:
    n = st.number_input("Page", 1, len(agent.filing.pages), 1)
    pg = agent.filing.pages[n - 1]
    st.caption(pg.section or "")
    st.text(pg.text)
