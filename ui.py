"""Incident Copilot Streamlit UI. Deterministic analytics + grounded Agent 2/3 workflow."""
from __future__ import annotations
import datetime as dt
import pandas as pd, requests, streamlit as st
import analytics, config, dashboard

st.set_page_config(page_title="Incident Knowledge Copilot",page_icon="🤖",layout="wide")
API_BASE=getattr(config,"API_BASE_URL","http://127.0.0.1:8000")

def get(path,params=None,timeout=30):
 r=requests.get(API_BASE+path,params=params,timeout=timeout); r.raise_for_status(); return r.json()
def post(path,payload,timeout=90):
 r=requests.post(API_BASE+path,json=payload,timeout=timeout); r.raise_for_status(); return r.json()
def safe_df(x):
 out=x.copy()
 for c in out.columns:
  if pd.api.types.is_datetime64_any_dtype(out[c]): out[c]=out[c].dt.strftime("%Y-%m-%d %H:%M:%S")
  elif out[c].dtype=="object": out[c]=out[c].map(lambda v:v.isoformat() if isinstance(v,pd.Timestamp) else v)
 return out

def sort_recent(x):
 y=x.copy()
 if "opened_at" in y.columns:
  y["_d"]=pd.to_datetime(y.opened_at,errors="coerce"); y=y.sort_values("_d",ascending=False,na_position="last").drop(columns="_d")
 return y

def incident_label(r): return f"{r.get('incident_id','')} | {r.get('ci_name','')} | {r.get('opened_at','')} | {r.get('description','')}"

def expander(r,prefix):
    with st.expander(incident_label(r), key=f"{prefix}_{r.get('incident_id','')}"):
        data = r.drop(labels=["search_text"], errors="ignore").to_frame("value")
        st.dataframe(safe_df(data), width="stretch")


def _fmt(v, default="-"):
    return default if v is None or v == "" else str(v)


def _safe_list(v):
    return v if isinstance(v, list) else []


def _pattern_table(patterns, label="Pattern"):
    rows = []
    for x in _safe_list(patterns):
        if isinstance(x, dict):
            rows.append({label: x.get("name", "-"), "Occurrences": x.get("count", 0)})
    return pd.DataFrame(rows)


def _incident_table(items):
    rows = []
    for x in _safe_list(items):
        if isinstance(x, dict):
            rows.append({
                "Incident": x.get("incident_id", "-"), "CI": x.get("ci_name", "-"),
                "Priority": x.get("priority", "-"), "Closure": x.get("closure_code", "-"),
                "Description": x.get("description", "-"), "Resolution": x.get("resolution", "-"),
                "Opened": x.get("opened_at", "-"),
            })
    return pd.DataFrame(rows)


def render_rca(r):
    inc = r.get("incident", {})
    g = r.get("grounded_assessment", {})
    e = r.get("evidence", {})
    st.markdown("## 🛡️ Grounded RCA Summary")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Incident", _fmt(inc.get("incident_id"))); c2.metric("CI", _fmt(inc.get("ci_name")))
    c3.metric("Priority", _fmt(inc.get("priority"))); c4.metric("Closure", _fmt(inc.get("closure_code")))
    st.markdown("### Executive Assessment")
    root=g.get("root_cause") or "Root cause unconfirmed; additional technical validation is required."
    (st.success if g.get("technical_cause_proven") else st.warning)(root)
    c1,c2,c3=st.columns(3)
    c1.metric("Confidence", _fmt(g.get("confidence"),"Low"))
    c2.metric("Technical cause proven", "Yes" if g.get("technical_cause_proven") else "No")
    c3.metric("Evidence status", _fmt(e.get("root_cause_support_level","inconclusive").title()))
    st.markdown("### Incident Facts")
    st.dataframe(pd.DataFrame([{
        "Description":inc.get("description","-"),"Resolution":inc.get("resolution","-"),
        "Opened":inc.get("opened_at","-"),"Historical CI incidents":e.get("historical_incident_count",0),
        "Same-description incidents":e.get("same_description_count_in_ci",0),
    }]), width="stretch", hide_index=True)
    st.markdown("### Historical Evidence")
    a,b=st.columns(2)
    with a:
        st.caption("Closure patterns for exact description")

        t = _pattern_table(
            e.get("same_description_closure_patterns")
        )

        if not t.empty:
            st.dataframe(
                t,
                width="stretch",
                hide_index=True
            )
        else:
            st.info("No closure pattern available.")

    with b:
        st.caption("Resolution patterns for exact description")

        t = _pattern_table(
            e.get("same_description_resolution_patterns"),
            "Resolution"
        )

        if not t.empty:
            st.dataframe(
                t,
                width="stretch",
                hide_index=True
            )
        else:
            st.info("No resolution pattern available.")
    sims=e.get("same_description_incidents") or []
    if sims:
        st.markdown("### Comparable Historical Incidents")
        st.dataframe(_incident_table(sims),width="stretch",hide_index=True)
    st.markdown("### AI Interpretation — Advisory")
    st.markdown(r.get("ai_interpretation") or r.get("answer") or "No additional AI interpretation was returned.")
    with st.expander("🔍 Technical evidence",expanded=False):
        st.caption(e.get("grounding_rule","Historical patterns indicate what happened, not necessarily why."))
        st.write(g.get("evidence_basis") or e.get("fact_based_observation") or "No evidence summary available.")
    sources=r.get("knowledge_sources") or []
    if sources:
        with st.expander("📚 Knowledge sources",expanded=False):
            for x in sources:
                if isinstance(x,dict):
                    st.markdown(f"**{x.get('source','Knowledge source')}** · {x.get('kind','')}")
                    st.caption((x.get("content") or "")[:2500])


def _humanize_key(value):
    """Convert API field names into readable management labels."""
    if value is None:
        return ""

    text = str(value).replace("_", " ").strip()

    replacements = {
        "ci": "CI",
        "mttr": "MTTR",
        "rto": "RTO",
        "rpo": "RPO",
        "rca": "RCA",
        "sla": "SLA",
        "ai": "AI",
    }

    words = text.split()
    return " ".join(
        replacements.get(word.lower(), word.capitalize())
        for word in words
    )


def _format_evidence_value(value):
    """Convert nested API evidence into readable text."""
    if value is None:
        return "-"

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, dict):
        parts = []

        for key, val in value.items():
            label = _humanize_key(key)

            if isinstance(val, (dict, list)):
                formatted = _format_evidence_value(val)
            else:
                formatted = _fmt(val)

            parts.append(f"**{label}:** {formatted}")

        return "<br>".join(parts)

    if isinstance(value, list):
        if not value:
            return "-"

        # List of dictionaries
        if all(isinstance(x, dict) for x in value):
            rows = []

            for item in value:
                parts = []

                for key, val in item.items():
                    label = _humanize_key(key)
                    parts.append(f"{label}: {_fmt(val)}")

                rows.append(" • ".join(parts))

            return "<br>".join(
                f"{idx}. {row}"
                for idx, row in enumerate(rows, 1)
            )

        return "<br>".join(
            f"{idx}. {_fmt(item)}"
            for idx, item in enumerate(value, 1)
        )

    return str(value)


def _management_evidence_rows(evidence):
    """
    Convert Agent 3 grounding evidence into management-readable rows.
    Technical/raw evidence remains available separately.
    """
    if not isinstance(evidence, dict):
        return []

    rows = []

    label_map = {
        "incident_count": (
            "Historical Incident Volume",
            "Number of historical incidents associated with the CI."
        ),
        "historical_incident_count": (
            "Historical Incident Volume",
            "Number of historical incidents associated with the CI."
        ),
        "same_description_count_in_ci": (
            "Recurring Incident Pattern",
            "Number of incidents with the same description for this CI."
        ),
        "same_closure_count_in_ci": (
            "Closure Pattern",
            "Frequency of the current closure pattern."
        ),
        "same_route_count_in_ci": (
            "Routing Pattern",
            "Frequency of the current routing pattern."
        ),
        "fact_based_observation": (
            "Fact-Based Observation",
            "Direct observation derived from the incident history."
        ),
        "grounding_rule": (
            "Grounding Rule",
            "Rule used to prevent unsupported technical conclusions."
        ),
        "root_cause_support_level": (
            "RCA Support Level",
            "Strength of the available evidence for a technical cause."
        ),
        "technical_cause_proven": (
            "Technical Cause Proven",
            "Whether the available evidence proves a technical cause."
        ),
        "confidence": (
            "AI Confidence",
            "Confidence level assigned to the assessment."
        ),
        "evidence_basis": (
            "Evidence Basis",
            "Historical evidence used to support the assessment."
        ),
        "recurring_patterns": (
            "Recurring Patterns",
            "Patterns detected across the historical incidents."
        ),
        "top_patterns": (
            "Top Historical Patterns",
            "Most significant recurring patterns identified."
        ),
        "risk_level": (
            "Risk Level",
            "Overall operational risk indicated by the evidence."
        ),
        "risk": (
            "Operational Risk",
            "Risk identified from the available incident evidence."
        ),
    }

    for key, value in evidence.items():

        if key in {
            "grounding_rule",
            "fact_based_observation",
            "evidence_basis",
            "root_cause_support_level",
            "technical_cause_proven",
            "confidence",
            "recurring_patterns",
            "top_patterns",
            "risk_level",
            "risk",
            "incident_count",
            "historical_incident_count",
            "same_description_count_in_ci",
            "same_closure_count_in_ci",
            "same_route_count_in_ci",
        }:

            title, meaning = label_map.get(
                key,
                (_humanize_key(key), "Evidence returned by the AI grounding process.")
            )

            rows.append({
                "Evidence Area": title,
                "Finding": _format_evidence_value(value),
                "Management Relevance": meaning,
            })

    return rows


def render_proactive(p):
    """
    Management-friendly Agent 3 presentation.

    The API remains the source of truth.
    This function only transforms structured API evidence into
    readable operational / management presentation.
    """

    g = p.get("grounded_assessment", {}) or {}

    raw_evidence = (
        g.get("evidence_basis")
        or p.get("evidence")
        or {}
    )

    ci_name = p.get("ci_name", "-")
    incident_count = p.get("incident_count", 0)

    st.markdown("## 🛡️ Proactive Risk Assessment")

    # ------------------------------------------------------------------
    # Executive KPI section
    # ------------------------------------------------------------------

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "CI",
        _fmt(ci_name)
    )

    c2.metric(
        "Historical Incidents",
        f"{incident_count:,}"
        if isinstance(incident_count, (int, float))
        else _fmt(incident_count)
    )

    c3.metric(
        "AI Confidence",
        _fmt(g.get("confidence"), "Low")
    )

    c4.metric(
        "Technical Cause",
        "Proven"
        if g.get("technical_cause_proven")
        else "Not Proven"
    )

    # ------------------------------------------------------------------
    # Executive risk
    # ------------------------------------------------------------------

    st.markdown("### Executive Risk Assessment")

    risk = (
        g.get("key_risk")
        or g.get("risk")
        or "No single recurring technical risk has been proven."
    )

    if g.get("technical_cause_proven"):
        st.success(risk)
    else:
        st.warning(risk)

    # ------------------------------------------------------------------
    # Management summary
    # ------------------------------------------------------------------

    st.markdown("### Management Summary")

    support_level = (
        g.get("root_cause_support_level")
        or g.get("evidence_status")
        or "Inconclusive"
    )

    management_summary = []

    management_summary.append(
        f"**CI:** {ci_name}"
    )

    management_summary.append(
        f"**Historical incident volume:** "
        f"{incident_count:,}"
        if isinstance(incident_count, (int, float))
        else f"**Historical incident volume:** {incident_count}"
    )

    management_summary.append(
        f"**Evidence strength:** {_humanize_key(support_level)}"
    )

    if g.get("technical_cause_proven"):
        management_summary.append(
            "**Technical cause:** Supported by the available evidence."
        )
    else:
        management_summary.append(
            "**Technical cause:** Not conclusively established from the available evidence."
        )

    st.markdown(
        "\n\n".join(management_summary)
    )

    # ------------------------------------------------------------------
    # Grounding evidence - management view
    # ------------------------------------------------------------------

    st.markdown("### 📊 Grounding Evidence")

    evidence_rows = _management_evidence_rows(raw_evidence)

    if evidence_rows:

        evidence_df = pd.DataFrame(evidence_rows)

        st.dataframe(
            evidence_df,
            width="stretch",
            hide_index=True,
            column_config={
                "Evidence Area": st.column_config.TextColumn(
                    "Evidence Area",
                    width="medium"
                ),
                "Finding": st.column_config.TextColumn(
                    "Finding",
                    width="large"
                ),
                "Management Relevance": st.column_config.TextColumn(
                    "Management Relevance",
                    width="large"
                ),
            },
        )

    else:
        st.info(
            "No structured grounding evidence was returned by Agent 3."
        )

    # ------------------------------------------------------------------
    # Recurring patterns
    # ------------------------------------------------------------------

    patterns = []

    if isinstance(raw_evidence, dict):

        patterns = (
            raw_evidence.get("recurring_patterns")
            or raw_evidence.get("top_patterns")
            or []
        )

    if patterns:

        st.markdown("### 🔁 Recurring Incident Patterns")

        pattern_df = _pattern_table(patterns)

        if not pattern_df.empty:

            st.dataframe(
                pattern_df,
                width="stretch",
                hide_index=True
            )

        else:
            st.info(
                "No recurring incident pattern was identified."
            )

    # ------------------------------------------------------------------
    # Preventive recommendations
    # ------------------------------------------------------------------

    st.markdown("### 🛠️ Preventive Recommendations")

    recommendation = (
        p.get("answer")
        or p.get("recommendations")
        or "No proactive recommendations were returned."
    )

    if isinstance(recommendation, list):

        for idx, item in enumerate(recommendation, 1):
            st.markdown(
                f"**{idx}.** {_fmt(item)}"
            )

    elif isinstance(recommendation, dict):

        for key, value in recommendation.items():

            st.markdown(
                f"**{_humanize_key(key)}**"
            )

            if isinstance(value, list):

                for item in value:
                    st.markdown(
                        f"- {_fmt(item)}"
                    )

            else:
                st.markdown(
                    _fmt(value)
                )

    else:
        st.markdown(str(recommendation))

    # ------------------------------------------------------------------
    # Recent incidents
    # ------------------------------------------------------------------

    recent = p.get("recent_incidents") or []

    if recent:

        st.markdown("### 🕒 Recent Incidents Considered")

        rows = []

        for x in recent:

            if not isinstance(x, dict):
                continue

            rows.append({
                "Incident": x.get("incident_id", "-"),
                "Priority": x.get("priority", "-"),
                "Description": x.get("description", "-"),
                "Resolution": x.get("resolution", "-"),
            })

        if rows:

            recent_df = pd.DataFrame(rows)

            st.dataframe(
                recent_df,
                width="stretch",
                hide_index=True
            )

        else:
            st.info(
                "No recent incident details were returned."
            )

    # ------------------------------------------------------------------
    # Knowledge sources
    # ------------------------------------------------------------------

    sources = p.get("knowledge_sources") or []

    if sources:

        with st.expander(
            "📚 Reference Knowledge Used",
            expanded=False
        ):

            for x in sources:

                if not isinstance(x, dict):
                    continue

                st.markdown(
                    f"**{x.get('source', 'Knowledge source')}** "
                    f"· {x.get('kind', '')}"
                )

                content = x.get("content") or ""

                if content:
                    st.caption(content[:2500])

    # ------------------------------------------------------------------
    # Raw evidence for technical users
    # ------------------------------------------------------------------

    with st.expander(
        "🔧 Technical / Raw Grounding Evidence",
        expanded=False
    ):

        st.caption(
            "This section contains the structured evidence returned by "
            "Agent 3. It is retained for engineering review and auditability."
        )

        if raw_evidence:

            st.json(raw_evidence)

        else:

            st.info(
                "No raw grounding evidence was returned."
            )

    # ------------------------------------------------------------------
    # Governance / human approval
    # ------------------------------------------------------------------

    st.warning(
        "⚠️ Human approval required. "
        "No production action was executed."
    )


for k,v in {"messages":[],"investigation":None,"rca":None,"proactive":None}.items(): st.session_state.setdefault(k,v)

@st.cache_data(show_spinner="Loading incident data...")
def load(sig): return analytics.load_all()
df_all=load(analytics.data_signature())

with st.sidebar:
 st.subheader("Local data"); st.caption(f"Incidents: {len(df_all):,}"); st.caption(f"Knowledge: {config.DATA_DIR/'chroma'}")
 if st.button("Refresh data",width="stretch"): st.cache_data.clear(); st.rerun()
 st.divider(); st.subheader("Filters")
 priorities=[p for p in getattr(config,"PRIORITY_ORDER",[]) if p in set(df_all.priority)] if len(df_all) else []
 cis=["All"]+sorted(df_all.loc[df_all.ci_name!="Unknown","ci_name"].astype(str).unique()) if len(df_all) else ["All"]
 sources=sorted(df_all.source_file.astype(str).unique()) if len(df_all) and "source_file" in df_all.columns else []
 start=st.date_input("Start date",df_all.opened_at.min().date() if len(df_all) else dt.date.today(),disabled=not st.checkbox("Enable start"))
 end=st.date_input("End date",df_all.opened_at.max().date() if len(df_all) else dt.date.today(),disabled=not st.checkbox("Enable end"))
 prio=st.multiselect("Priority",priorities,default=priorities); ci=st.selectbox("CI name",cis); src=st.multiselect("Source file",sources,default=sources)
 if st.button("Reset filters",width="stretch"): st.rerun()
 if st.button("Clear chat",width="stretch"): st.session_state.messages=[]; st.rerun()

filtered=analytics.apply_filters(df_all,None if 'start' not in locals() else start,None if 'end' not in locals() else end,prio,ci,src)
dash=dashboard.build_dashboard(filtered); fig=dash["figures"]
st.title("🤖 Incident Knowledge Copilot")

tab_chat,tab_dash,tab_server,tab_inc,tab_ai=st.tabs(["💬 Chat","📊 Dashboard","🖥️ Server Analysis","🗂️ Incident Analysis","🤖 AI Proactive & RCA"])

with tab_chat:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])
    q=st.chat_input("Ask about incidents, CI names, servers, or knowledge...")
    if q:
        st.session_state.messages.append({"role":"user","content":q})
        try: msg=__import__("chat_engine").answer(q,filtered).get("answer","")
        except Exception as e: msg=f"Local search failed: `{type(e).__name__}: {e}`"
        st.session_state.messages.append({"role":"assistant","content":msg}); st.rerun()


with tab_dash:
 k=dash["kpis"]; c=st.columns(4); c[0].metric("Total incidents",f"{k['total']:,}"); c[1].metric("Critical + High",f"{k['critical_high']:,}"); c[2].metric("Average MTTR",k.get("mttr_display","-")); c[3].metric("Top closure code",k.get("top_closure","-"))
 a,b=st.columns(2); a.altair_chart(fig["monthly_trend"],width="stretch"); b.altair_chart(fig["priority_trend"],width="stretch")
 a,b=st.columns(2); a.altair_chart(fig["mttr_trend"],width="stretch"); b.altair_chart(fig["mttr_priority"],width="stretch")
 st.altair_chart(fig["top_route_cases"],width="stretch"); a,b=st.columns(2); a.altair_chart(fig["top_closure_codes"],width="stretch"); b.altair_chart(fig["top_servers"],width="stretch")

with tab_server:
 st.subheader("Server / CI Analysis"); s=st.text_input("Search ci_name",placeholder="srv-web-prod-01 or APP-PAYMENTS-PROD").strip()
 if s:
  local=sort_recent(analytics.ci_incidents(filtered,s)); st.caption(f"Matching historical incidents: {len(local):,}. Showing 10 most recent.")
  for _,r in local.head(10).iterrows(): expander(r,"srv")
  if st.button("🤖 Generate Proactive Measures",width="stretch"):
   try: st.session_state.proactive=post("/api/agents/proactive",{"ci_name":s},120)
   except Exception as e: st.error(f"Agent 3 failed: {e}")
  p=st.session_state.proactive
  if p and p.get("ci_name")==s:
   g=p.get("grounded_assessment",{}); st.markdown("### 🛡️ Grounded Proactive Risk"); st.info(g.get("key_risk","No specific recurring risk proven.")); st.json(g.get("evidence_basis",{})); st.markdown("### AI Recommendations"); st.markdown(p.get("answer","")); st.warning("Human approval required. No production action executed.")
 else: st.info("Enter a CI name to analyze.")

with tab_inc:
 st.subheader("Incident Analysis"); q=st.text_input("Incident number / description / CI",placeholder="101483").strip(); v=analytics.search_incidents(filtered,q); st.markdown(f"**Total incidents count:** {len(v):,}"); st.markdown("**CI name:** "+(", ".join(sorted(v.ci_name.dropna().astype(str).unique())) if len(v) else "-"))
 for _,r in v.head(100).iterrows(): expander(r,"inc")

with tab_ai:
    st.subheader("🤖 Human Feedback → Incident Record → RCA Summary")
    iid=st.text_input("Incident number",placeholder="101483").strip()
    c1,c2,c3=st.columns(3)
    with c1: run2=st.button("2️⃣ Generate Grounded RCA",width="stretch")
    with c2: run3=st.button("3️⃣ Proactive Remediation",width="stretch")
    with c3:
        if st.button("Clear AI results",width="stretch"):
            st.session_state.rca=None; st.session_state.proactive=None; st.rerun()
    if run2 and iid:
        try:
            with st.spinner("Agent 2 is generating a grounded RCA..."): st.session_state.rca=post("/api/agents/root-cause",{"incident_id":iid},120)
        except Exception as e: st.error(f"Agent 2 failed: {type(e).__name__}: {e}")
    r=st.session_state.rca
    if r:
        render_rca(r)
        st.divider(); st.markdown("### 4️⃣ Human Feedback")
        st.caption("Validate or correct the AI assessment before it becomes part of the incident record.")
        decision=st.radio("RCA assessment",["Approved","Modified","Rejected"],horizontal=True,key="decision")
        root=st.text_area("Validated / corrected root cause",key="human_root")
        corr=st.text_area("Validated corrective action",key="human_corr")
        prev=st.text_area("Validated preventive action",key="human_prev")
        comments=st.text_area("Reviewer comments",key="human_comments")
        if st.button("💾 Submit Human Feedback",width="stretch"):
            try:
                inc=r.get("incident",{}); saved=post("/api/agents/feedback",{"incident_id":inc.get("incident_id",iid),"decision":decision,"corrected_root_cause":root,"corrective_action":corr,"preventive_action":prev,"comments":comments},30)
                st.success("Human feedback saved to the incident record.")
                with st.expander("Saved feedback response",expanded=False): st.json(saved)
            except Exception as e: st.error(f"Feedback save failed: {type(e).__name__}: {e}")
    # Agent 3 CI input must be rendered BEFORE the button action.
    # Previously the input was created inside `if run3`, so the first click
    # only created the widget and no request was sent.
    incident_ci = (r.get("incident", {}).get("ci_name", "") if r else "").strip()
    ci3 = st.text_input(
        "CI for Proactive Remediation",
        value=incident_ci,
        key="ci3",
        placeholder="srv-web-prod-01 or APP-PAYMENTS-PROD",
        help="Enter the CI name. If Agent 2 RCA has already run, its CI is pre-filled."
    ).strip()

    if run3:
        if not ci3:
            st.warning("Enter a CI name before running Agent 3 Proactive Remediation.")
        else:
            try:
                with st.spinner("Agent 3 is generating grounded proactive recommendations..."):
                    st.session_state.proactive = post(
                        "/api/agents/proactive",
                        {"ci_name": ci3},
                        120
                    )
            except Exception as e:
                st.error(f"Agent 3 failed: {type(e).__name__}: {e}")

    p = st.session_state.proactive
    if p:
        st.divider(); render_proactive(p)

