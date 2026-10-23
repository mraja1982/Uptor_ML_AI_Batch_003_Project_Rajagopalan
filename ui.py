"""Local Incident Knowledge Copilot. Streamlit UI backed by FastAPI; LLM is used only for proactive analysis."""
from __future__ import annotations
import datetime as dt
import pandas as pd
import streamlit as st
import requests
import analytics
import config
import dashboard
import chat_engine
st.set_page_config(page_title='Incident Knowledge Copilot', page_icon='🤖', layout='wide')

# Persist AI results across Streamlit reruns.
st.session_state.setdefault('proactive_result', None)
st.session_state.setdefault('proactive_ci', '')
st.session_state.setdefault('forecast_result', None)
st.session_state.setdefault('forecast_ci', '')
st.session_state.setdefault('approval_result', None)

def forecast_api_url() -> str:
    return getattr(config, "API_CI_RISK_FORECAST_URL", "http://127.0.0.1:8000/api/ci-risk-forecast")


def approval_api_url() -> str:
    return getattr(config, "API_APPROVAL_URL", "http://127.0.0.1:8000/api/agents/approval")


def proactive_agent_api_url() -> str:
    return getattr(
        config,
        "API_AGENT_PROACTIVE_URL",
        "http://127.0.0.1:8000/api/agents/proactive",
    )

def display_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return a display-only DataFrame with every cell normalized to plain text.

    This is intentionally separate from analytics data. Streamlit/PyArrow can fail
    when an object column contains a mixture of strings, floats, timestamps, dicts,
    lists or None. Converting every displayed cell to a Python string removes that
    entire class of Arrow serialization errors without changing calculations.
    """
    if df is None:
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)
    out = df.copy().reset_index(drop=True)

    def safe_text(v):
        if v is None:
            return ""
        if isinstance(v, (dict, list, tuple, set)):
            try:
                import json
                return json.dumps(v, ensure_ascii=False, default=str)
            except Exception:
                return str(v)
        if isinstance(v, pd.Timestamp):
            return v.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(v, dt.datetime):
            return v.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(v, dt.date):
            return v.isoformat()
        try:
            if pd.isna(v):
                return ""
        except (TypeError, ValueError):
            pass
        return str(v)

    out.columns = [str(c) for c in out.columns]
    for col in out.columns:
        out[col] = out[col].map(safe_text).astype(str)
    return out


def safe_markdown(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return str(value)


def render_evidence(evidence: dict, title="Grounding evidence"):
    """Render nested evidence as management-readable tables instead of raw JSON."""
    if not isinstance(evidence, dict) or not evidence:
        return
    st.markdown(f"#### {title}")
    rows=[]
    for key, value in evidence.items():
        label=str(key).replace('_',' ').title()
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            text='; '.join(', '.join(f"{k}: {v}" for k,v in x.items()) for x in value[:10])
        elif isinstance(value, (dict,list)):
            text=safe_markdown(value)
        else:
            text=safe_markdown(value)
        rows.append({"Evidence item":label,"Observed evidence":text})
    st.dataframe(display_df(pd.DataFrame(rows)), hide_index=True, width='stretch')


@st.cache_data(show_spinner='Loading incident files...')
def get_data(signature: tuple) -> pd.DataFrame:
    return analytics.load_all()
sig = analytics.data_signature()
df_all = get_data(sig)
with st.sidebar:
    st.subheader('Local data')
    st.caption(f'CSV/Excel files: {len(analytics.list_data_files())}')
    st.caption(f"Knowledge index: {config.DATA_DIR / 'chroma'}")
    if st.button('Refresh data', width='stretch'):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.subheader('Analytics Filters')
    priorities_avail = [p for p in config.PRIORITY_ORDER if p in set(df_all['priority'])] if len(df_all) else []
    ci_avail = ['All'] + sorted(df_all.loc[df_all['ci_name'] != 'Unknown', 'ci_name'].astype(str).unique().tolist()) if len(df_all) else ['All']
    sources_avail = sorted(df_all['source_file'].unique()) if len(df_all) else []

    def reset_filters():
        st.session_state.update(f_start_on=False, f_end_on=False, f_prio=priorities_avail, f_ci='All', f_src=sources_avail)
    if st.session_state.get('_sig') != sig:
        st.session_state['_sig'] = sig
        reset_filters()
    d = df_all['opened_at'].dropna() if len(df_all) else pd.Series(dtype='datetime64[ns]')
    dmin = d.min().date() if len(d) else dt.date.today()
    dmax = d.max().date() if len(d) else dt.date.today()
    start_on = st.checkbox('Enable Start Date', key='f_start_on')
    start = st.date_input('Start Date', dmin, min_value=dmin, max_value=dmax) if start_on else None
    end_on = st.checkbox('Enable End Date', key='f_end_on')
    end = st.date_input('End Date', dmax, min_value=dmin, max_value=dmax) if end_on else None
    prio = st.multiselect('Priority', priorities_avail, key='f_prio')
    ci_filter = st.selectbox('CI name', ci_avail, key='f_ci')
    src = st.multiselect('Source File', sources_avail, key='f_src')
    st.button('Reset Filters', on_click=reset_filters, width='stretch')

    def clear_chat():
        st.session_state['messages'] = []
    st.button('Clear Chat', on_click=clear_chat, width='stretch')
df = analytics.apply_filters(df_all, start, end, prio, ci_filter, src)
dash = dashboard.build_dashboard(df)
fig = dash['figures']
st.title('🤖 Incident Knowledge Copilot')
if df_all.empty:
    st.warning('No incident data found. Put CSV/Excel files in data/csv and run: python ingest.py')
tab_chat, tab_dash, tab_server, tab_inc, tab_ai = st.tabs(['💬 Chat', '📊 Dashboard', '🖥️ Server Analysis', '🗂️ Incident Analysis', '🤖 AI Proactive & RCA'])
with tab_chat:
    st.session_state.setdefault('messages', [])
    for m in st.session_state['messages']:
        with st.chat_message(m['role']):
            st.markdown(m['content'])
            if m.get('actions'):
                with st.expander('🛡️ Proactive actions', expanded=True):
                    for a in m['actions']:
                        st.markdown(f"**[{a['severity']}] {a['area']}** - {a['finding']}  \n➡️ {a['action']}")
            if m.get('knowledge'):
                with st.expander('📚 Knowledge sources'):
                    for k in m['knowledge']:
                        st.markdown(f"**{k['source']}** — {k['location']} (match {k['score']})")
                        st.caption(k['text'])
            if m.get('similar'):
                with st.expander('Similar past incidents'):
                    st.dataframe(display_df(pd.DataFrame(m['similar'])), hide_index=True, width='stretch')
    if (q := st.chat_input('Ask about incidents, CI names, servers, or knowledge...')):
        st.session_state['messages'].append({'role': 'user', 'content': q})
        with st.chat_message('user'):
            st.markdown(q)
        with st.chat_message('assistant'):
            with st.spinner('Searching local incident data...'):
                try:
                    res = chat_engine.answer(q, df)
                    msg = {'role': 'assistant', 'content': res['answer'], 'actions': res.get('proactive_actions', []), 'similar': res.get('similar_incidents', []), 'knowledge': res.get('knowledge_sources', [])}
                except Exception as exc:
                    msg = {'role': 'assistant', 'content': f'Local search failed: `{type(exc).__name__}: {exc}`'}
        st.session_state['messages'].append(msg)
        st.rerun()
with tab_dash:
    k = dash['kpis']
    c = st.columns(4)
    c[0].metric('Total incidents', f"{k['total']:,}")
    c[1].metric('Critical + High', f"{k['critical_high']:,}", f"{k['critical_high_pct']:.0f}% of total", delta_color='off')
    c[2].metric('Average MTTR', k.get('mttr_display', '-'), f"{k.get('mttr_valid_incidents', 0):,} incidents with valid resolution time", delta_color='off')
    c[3].metric('Top closure code', k['top_closure'])
    st.caption(f"Period: {k['date_from']} -> {k['date_to']} | Files: {k['files']}")
    a, b = st.columns(2)
    a.altair_chart(fig['monthly_trend'], width='stretch')
    b.altair_chart(fig['priority_trend'], width='stretch')
    a, b = st.columns(2)
    a.altair_chart(fig['mttr_trend'], width='stretch')
    b.altair_chart(fig['mttr_priority'], width='stretch')
    st.altair_chart(fig['top_route_cases'], width='stretch')
    a, b = st.columns(2)
    a.altair_chart(fig['top_closure_codes'], width='stretch')
    b.altair_chart(fig['top_servers'], width='stretch')
with tab_server:
    st.subheader('Search by server / CI name')

    ci_search = st.text_input(
        'Search ci_name',
        placeholder='e.g. APP-PAYMENTS-PROD or srv-web-prod-01',
        key='server_ci_search',
    )

    server_view = pd.DataFrame()

    if ci_search.strip():
        try:
            response = requests.get(
                getattr(
                    config,
                    'API_SERVER_ANALYSIS_URL',
                    'http://localhost:8000/api/server-analysis',
                ),
                params={
                    'ci_name': ci_search.strip(),
                },
                timeout=config.API_TIMEOUT,
            )

            response.raise_for_status()

            server_payload = response.json()

            server_view = pd.DataFrame(
                server_payload.get(
                    'items',
                    [],
                )
            )

        except Exception as exc:
            st.error(
                f'Server Analysis API unavailable: '
                f'{type(exc).__name__}: {exc}'
            )

    st.markdown(
        f'**Recent incidents returned:** '
        f'{len(server_view):,} '
        f'(maximum 10)'
    )

    if not ci_search.strip():
        st.info(
            'Enter a server / CI name to search.'
        )

    elif server_view.empty:
        st.info(
            'No matching CI incidents. Verify that the CSV contains '
            'a `ci_name` column and run `python ingest.py`.'
        )

    else:
        chart_df = df[
            df['ci_name']
            .astype(str)
            .str.contains(
                ci_search,
                case=False,
                na=False,
            )
        ]

        st.altair_chart(
            dashboard.top_servers(chart_df),
            width='stretch',
        )

        st.dataframe(
            display_df(server_view),
            hide_index=True,
            width='stretch',
        )

        st.divider()

        st.subheader(
            'Past 10 incidents for the searched CI'
        )

        st.caption(
            f'{len(server_view):,} recent incident(s) shown.'
        )

        for _, row in server_view.iterrows():
            incident_id = str(
                row.get(
                    'incident_id',
                    'Unknown',
                )
            )

            opened = row.get(
                'opened_at',
                '',
            )

            opened_text = (
                opened.strftime(
                    '%Y-%m-%d %H:%M:%S'
                )
                if hasattr(
                    opened,
                    'strftime',
                )
                else str(opened)
            )

            label = (
                f"{incident_id} | "
                f"{row.get('ci_name', 'Unknown')} | "
                f"{opened_text} | "
                f"{row.get('description', '')}"
            )

            with st.expander(label):
                details = row.drop(
                    labels=[
                        'search_text',
                    ],
                    errors='ignore',
                ).to_frame(
                    'value'
                )

                st.dataframe(
                    display_df(details),
                    width='stretch',
                )

        st.subheader(
            'AI-assisted proactive analysis'
        )

        st.caption(
            'LLM is called only when you request proactive analysis. '
            'All calculations above are deterministic Python/Pandas.'
        )

        if st.button(
            '🤖 Generate Proactive Measures',
            key='generate_proactive',
            width='stretch',
        ):
            requested_ci = ci_search.strip()
            if not requested_ci:
                st.warning('Enter a server / CI name before generating proactive measures.')
            else:
                with st.spinner('Generating proactive measures with the local AI engine...'):
                    try:
                        response = requests.post(
                            proactive_agent_api_url(),
                            json={"ci_name": ci_search.strip()},
                            timeout=config.API_TIMEOUT,
                        )
                        response.raise_for_status()
                        payload = response.json()

                        # IMPORTANT: persist the API response in session state.
                        # Streamlit reruns the script after every widget interaction;
                        # a local variable would otherwise disappear on the next run.
                        st.session_state.proactive_result = payload
                        st.session_state.proactive_ci = requested_ci
                        try:
                            fr = requests.get(forecast_api_url(), params={"ci_name": requested_ci}, timeout=30)
                            fr.raise_for_status()
                            st.session_state.forecast_result = fr.json()
                            st.session_state.forecast_ci = requested_ci
                        except Exception as forecast_exc:
                            st.session_state.forecast_result = {"error": f"Forecast unavailable: {type(forecast_exc).__name__}: {forecast_exc}"}
                            st.session_state.forecast_ci = requested_ci
                    except requests.HTTPError as exc:
                        body = ''
                        try:
                            body = response.text[:1000]
                        except Exception:
                            pass
                        st.session_state.proactive_result = {
                            'error': f'AI service returned HTTP {getattr(response, "status_code", "error")}: {body or exc}'
                        }
                        st.session_state.proactive_ci = requested_ci
                    except Exception as exc:
                        st.session_state.proactive_result = {
                            'error': f'AI service unavailable: {type(exc).__name__}: {exc}'
                        }
                        st.session_state.proactive_ci = requested_ci

        # Render persisted result OUTSIDE the button block so it survives reruns.
        ai_plan = st.session_state.get('proactive_result')
        saved_ci = st.session_state.get('proactive_ci', '')
        current_ci = ci_search.strip()

        if ai_plan and saved_ci.lower() == current_ci.lower():
            if ai_plan.get('error'):
                st.error(ai_plan['error'])
            else:
                st.markdown('### 🛡️ AI-Assisted Proactive Analysis')

                # Management summary
                answer = str(ai_plan.get('answer') or '').strip()
                if answer:
                    st.markdown('#### Executive recommendation')
                    st.markdown(answer)
                else:
                    st.info('The AI service completed successfully but did not return a recommendation.')

                # Grounding / evidence in readable management format.
                grounded = ai_plan.get('grounded_assessment') or {}
                if grounded:
                    st.markdown('#### Grounding evidence')
                    risk = grounded.get('key_risk') or grounded.get('risk')
                    confidence = grounded.get('confidence')
                    basis = grounded.get('evidence_basis')

                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric('Evidence confidence', str(confidence or 'Not stated'))
                    with c2:
                        if risk:
                            st.metric('Primary recurring risk', str(risk)[:120])
                        else:
                            st.metric('Historical incidents', f"{ai_plan.get('incident_count', 0):,}")

                    if risk:
                        st.info(f'**Primary risk:** {risk}')

                    if basis:
                        if isinstance(basis, dict):
                            rows = []
                            for key, value in basis.items():
                                if isinstance(value, (list, dict)):
                                    if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                                        value_text = '; '.join(
                                            ', '.join(f'{k}: {v}' for k, v in x.items())
                                            for x in value[:10]
                                        )
                                    else:
                                        value_text = str(value)
                                else:
                                    value_text = str(value)
                                rows.append({'Evidence item': key.replace('_', ' ').title(), 'Observed evidence': value_text})
                            if rows:
                                st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
                        else:
                            st.markdown(str(basis))

                # API responses from different versions may expose evidence directly.
                evidence = ai_plan.get('evidence') or {}
                if evidence:
                    with st.expander('Detailed evidence used by the agent', expanded=False):
                        def _flatten_evidence(value, prefix=''):
                            rows = []
                            if isinstance(value, dict):
                                for k, v in value.items():
                                    label = f'{prefix} > {k}' if prefix else str(k)
                                    rows.extend(_flatten_evidence(v, label))
                            elif isinstance(value, list):
                                if value and all(isinstance(x, dict) for x in value):
                                    for idx, item in enumerate(value[:10], 1):
                                        rows.extend(_flatten_evidence(item, f'{prefix} #{idx}'))
                                else:
                                    rows.append({'Evidence item': prefix, 'Observed evidence': str(value)})
                            else:
                                rows.append({'Evidence item': prefix, 'Observed evidence': str(value)})
                            return rows
                        ev_rows = _flatten_evidence(evidence)
                        if ev_rows:
                            st.dataframe(pd.DataFrame(ev_rows), hide_index=True, width='stretch')

                # Knowledge sources are readable, not raw JSON.
                knowledge = ai_plan.get('knowledge_sources') or []
                if knowledge:
                    with st.expander('📚 Knowledge sources used by AI', expanded=False):
                        for idx, item in enumerate(knowledge, 1):
                            if not isinstance(item, dict):
                                st.markdown(f'**Source {idx}:** {item}')
                                continue
                            source = item.get('source', f'Knowledge source {idx}')
                            kind = item.get('kind', '')
                            st.markdown(f'**{source}**' + (f' — {kind}' if kind else ''))
                            content = str(item.get('content') or '').strip()
                            if content:
                                st.caption(content)
                            if idx < len(knowledge):
                                st.divider()

                timing = ai_plan.get('timing') or {}
                if timing:
                    ollama_seconds = timing.get('ollama_seconds')
                    total_seconds = timing.get('total_seconds')
                    timing_text = []
                    if isinstance(ollama_seconds, (int, float)):
                        timing_text.append(f'Ollama: {ollama_seconds:.1f}s')
                    if isinstance(total_seconds, (int, float)):
                        timing_text.append(f'Total: {total_seconds:.1f}s')
                    if timing_text:
                        st.caption(' | '.join(timing_text))

                if ai_plan.get('requires_human_approval', True):
                    st.warning('Human approval required. No production action was executed.')

                    st.markdown('### ✅ Human Approval / Governance Decision')
                    st.caption('Approval records the reviewer decision only. Incident Copilot does not execute production changes.')
                    approval_decision = st.radio(
                        'Decision',
                        ['Approved', 'Rejected', 'Needs Review'],
                        horizontal=True,
                        key='server_approval_decision',
                    )
                    approval_action = st.text_area(
                        'Action being approved',
                        value=str(ai_plan.get('answer') or '').strip(),
                        key='server_approval_action',
                        height=100,
                    )
                    approval_reviewer = st.text_input('Reviewer', value='Human reviewer', key='server_approval_reviewer')
                    approval_comments = st.text_area('Approval comments', key='server_approval_comments')
                    if st.button('Submit Approval Decision', key='submit_server_approval', width='stretch'):
                        try:
                            ar = requests.post(
                                approval_api_url(),
                                json={
                                    'ci_name': current_ci,
                                    'incident_id': '',
                                    'decision': approval_decision,
                                    'approved_action': approval_action,
                                    'reviewer': approval_reviewer,
                                    'comments': approval_comments,
                                },
                                timeout=30,
                            )
                            ar.raise_for_status()
                            st.session_state.approval_result = ar.json()
                            st.success('Human approval decision submitted and recorded. No production change was executed.')
                        except requests.HTTPError:
                            st.error(f'Approval API returned HTTP {ar.status_code}: {ar.text[:1000]}')
                        except Exception as approval_exc:
                            st.error(f'Approval submission failed: {type(approval_exc).__name__}: {approval_exc}')

                approval_saved = st.session_state.get('approval_result')
                if approval_saved and isinstance(approval_saved, dict):
                    saved = approval_saved.get('approval') or {}
                    if saved.get('ci_name') == current_ci:
                        st.success(f"Governance status: {saved.get('governance_status', saved.get('decision', 'Recorded'))}")

                # Deterministic CI forecast and risk score.
                forecast = st.session_state.get('forecast_result')
                if forecast and st.session_state.get('forecast_ci', '').lower() == current_ci.lower():
                    if forecast.get('error'):
                        st.warning(forecast['error'])
                    else:
                        st.markdown('### 📈 CI Incident Forecast & Risk Score')
                        fc1, fc2, fc3, fc4 = st.columns(4)
                        fc1.metric('Risk score', f"{forecast.get('risk_score', 0)}/100")
                        fc2.metric('Risk level', str(forecast.get('risk_level', 'Low')))
                        fc3.metric('Avg monthly incidents', str(forecast.get('average_monthly_incidents', '-')))
                        fc4.metric('90-day incidents', str(forecast.get('recent_90_day_incidents', '-')))
                        history_rows = forecast.get('monthly_history') or []
                        forecast_rows = forecast.get('forecast') or []
                        if history_rows or forecast_rows:
                            hist_df = pd.DataFrame(history_rows).rename(columns={'month':'Month','incident_count':'Actual incidents'})
                            pred_df = pd.DataFrame(forecast_rows).rename(columns={'month':'Month','forecast_incidents':'Forecast incidents'})
                            if not hist_df.empty:
                                st.markdown('#### Historical incident trend')
                                st.dataframe(display_df(hist_df), hide_index=True, width='stretch')
                            if not pred_df.empty:
                                st.markdown('#### Next 3-month forecast')
                                st.dataframe(display_df(pred_df), hide_index=True, width='stretch')
                        comps = forecast.get('risk_components') or {}
                        if comps:
                            st.caption('Risk score components: ' + ', '.join(f"{str(k).replace('_',' ').title()}={v}" for k,v in comps.items()))
                        st.caption(forecast.get('forecast_method', 'Deterministic forecast based on incident history.'))

                # Optional clear action for the current result.
                if st.button('Clear proactive result', key='clear_server_proactive', width='stretch'):
                    st.session_state.proactive_result = None
                    st.session_state.proactive_ci = ''
                    st.rerun()

with tab_inc:
    st.subheader('Search incidents')
    incident_search = st.text_input('Search incident', placeholder='Incident number, description, resolution, CI name...', key='incident_search')
    incident_view = analytics.search_incidents(df, incident_search)
    total = len(incident_view)
    ci_names = sorted([x for x in incident_view['ci_name'].dropna().astype(str).unique() if x and x != 'Unknown'])
    st.markdown(f'**Total incidents count:** {total}')
    st.markdown(f"**CI name:** {(', '.join(ci_names) if ci_names else '-')}")
    if total == 0:
        st.info('No incidents found for the search.')
    else:
        for _, row in incident_view.head(100).iterrows():
            incident_id = str(row.get('incident_id', 'Unknown'))
            label = f"{incident_id} | {row.get('ci_name', 'Unknown')} | {row.get('description', '')}"
            with st.expander(label):
                details = row.drop(labels=['search_text'], errors='ignore').to_frame('value')
                st.dataframe(display_df(details), width='stretch')


with tab_ai:
    st.subheader('🤖 AI Proactive Analysis & RCA')
    st.caption('Management view of grounded RCA and proactive remediation. AI recommendations are advisory only; no production action is executed.')

    incident_id = st.text_input('Incident number for RCA', placeholder='e.g. 101483', key='agent_incident_id').strip()
    ci_for_proactive = st.text_input('CI name for proactive remediation', placeholder='e.g. srv-web-prod-01', key='agent_proactive_ci_tab').strip()

    b1, b2, b3 = st.columns(3)
    with b1:
        run_rca = st.button('🔎 Generate Grounded RCA', key='ai_generate_rca', width='stretch')
    with b2:
        run_proactive = st.button('🛡️ Generate Proactive Recommendations', key='ai_generate_proactive', width='stretch')
    with b3:
        if st.button('Clear AI Results', key='ai_clear_results', width='stretch'):
            st.session_state['agent_rca_result'] = None
            st.session_state['agent_proactive_result'] = None
            st.rerun()

    if run_rca:
        if not incident_id:
            st.warning('Enter an incident number first.')
        else:
            with st.spinner('Agent 2 is generating the grounded RCA...'):
                try:
                    r=requests.post(getattr(config,'API_AGENT_ROOT_CAUSE_URL','http://127.0.0.1:8000/api/agents/root-cause'), json={'incident_id':incident_id}, timeout=getattr(config,'API_TIMEOUT',120))
                    r.raise_for_status()
                    st.session_state['agent_rca_result']=r.json()
                except requests.HTTPError:
                    st.session_state['agent_rca_result']={'error':f'RCA API returned HTTP {r.status_code}: {r.text[:1000]}'}
                except Exception as exc:
                    st.session_state['agent_rca_result']={'error':f'RCA service unavailable: {type(exc).__name__}: {exc}'}

    if run_proactive:
        if not ci_for_proactive:
            st.warning('Enter a CI name first.')
        else:
            with st.spinner('Agent 3 is generating grounded proactive recommendations...'):
                try:
                    r=requests.post(getattr(config,'API_AGENT_PROACTIVE_URL','http://127.0.0.1:8000/api/agents/proactive'), json={'ci_name':ci_for_proactive}, timeout=getattr(config,'API_TIMEOUT',120))
                    r.raise_for_status()
                    st.session_state['agent_proactive_result']=r.json()
                    try:
                        fr=requests.get(forecast_api_url(), params={'ci_name':ci_for_proactive}, timeout=30)
                        fr.raise_for_status()
                        st.session_state['forecast_result']=fr.json()
                        st.session_state['forecast_ci']=ci_for_proactive
                    except Exception as forecast_exc:
                        st.session_state['forecast_result']={'error':f'Forecast unavailable: {type(forecast_exc).__name__}: {forecast_exc}'}
                        st.session_state['forecast_ci']=ci_for_proactive
                except requests.HTTPError:
                    st.session_state['agent_proactive_result']={'error':f'Proactive API returned HTTP {r.status_code}: {r.text[:1000]}'}
                except Exception as exc:
                    st.session_state['agent_proactive_result']={'error':f'Proactive service unavailable: {type(exc).__name__}: {exc}'}

    rca=st.session_state.get('agent_rca_result')
    if rca:
        st.divider()
        st.markdown('### 🔎 Executive RCA')
        if rca.get('error'):
            st.error(rca['error'])
        else:
            inc=rca.get('incident') or {}
            if inc:
                c=st.columns(4)
                c[0].metric('Incident',str(inc.get('incident_id','-')))
                c[1].metric('CI',str(inc.get('ci_name','-')))
                c[2].metric('Priority',str(inc.get('priority','-')))
                c[3].metric('Closure',str(inc.get('closure_code','-')))
            ga=rca.get('grounded_assessment') or {}
            c=st.columns(3)
            c[0].metric('RCA confidence',str(ga.get('confidence','Low')))
            c[1].metric('Technical cause proven','Yes' if ga.get('technical_cause_proven') else 'No')
            c[2].metric('CI incident history',f"{rca.get('historical_incident_count',0):,}")
            st.markdown('#### Executive summary')
            st.markdown(rca.get('answer') or 'Root cause remains unconfirmed; additional technical validation is required.')
            if ga.get('evidence_basis'):
                st.info(str(ga.get('evidence_basis')))
            ev=rca.get('evidence') or {}
            if ev:
                render_evidence(ev)
            similar=rca.get('similar_incidents') or []
            if similar:
                with st.expander('Historical incidents used as supporting evidence', expanded=False):
                    st.dataframe(display_df(pd.DataFrame(similar)), hide_index=True, width='stretch')
            knowledge=rca.get('knowledge_sources') or []
            if knowledge:
                with st.expander('Knowledge references used by the agent', expanded=False):
                    for i,k in enumerate(knowledge,1):
                        if isinstance(k,dict):
                            st.markdown(f"**{k.get('source','Knowledge source')}**")
                            st.caption(str(k.get('content','')))
                        else:
                            st.markdown(str(k))

    pro=st.session_state.get('agent_proactive_result')
    if pro:
        st.divider()
        st.markdown('### 🛡️ Executive Proactive Recommendation')
        if pro.get('error'):
            st.error(pro['error'])
        else:
            c=st.columns(3)
            c[0].metric('CI',str(pro.get('ci_name','-')))
            c[1].metric('Incident history',f"{pro.get('incident_count',0):,}")
            c[2].metric('AI status',str(pro.get('ai_status','Unknown')).title())
            st.markdown('#### Management recommendation')
            st.markdown(pro.get('answer') or 'No recommendation was returned.')
            ga=pro.get('grounded_assessment') or {}
            if ga:
                risk=ga.get('key_risk')
                if risk: st.info(f"**Primary operational risk:** {risk}")
                basis=ga.get('evidence_basis')
                if isinstance(basis,dict): render_evidence(basis)
            recent_items=pro.get('recent_incidents') or []
            if recent_items:
                with st.expander('Recent incidents considered by the agent', expanded=False):
                    st.dataframe(display_df(pd.DataFrame(recent_items)), hide_index=True, width='stretch')
            knowledge=pro.get('knowledge_sources') or []
            if knowledge:
                with st.expander('Knowledge references used by the agent', expanded=False):
                    for k in knowledge:
                        if isinstance(k,dict):
                            st.markdown(f"**{k.get('source','Knowledge source')}**")
                            st.caption(str(k.get('content','')))
            st.warning('Human approval required. No production action was executed.')

            st.markdown('### ✅ Human Approval / Governance Decision')
            st.caption('Record the reviewer decision before any operational implementation. This application does not execute production changes.')
            ai_decision = st.radio('Decision', ['Approved', 'Rejected', 'Needs Review'], horizontal=True, key='ai_approval_decision')
            ai_action = st.text_area('Action being approved', value=str(pro.get('answer') or ''), key='ai_approval_action', height=100)
            ai_reviewer = st.text_input('Reviewer', value='Human reviewer', key='ai_approval_reviewer')
            ai_comments = st.text_area('Approval comments', key='ai_approval_comments')
            if st.button('Submit Approval Decision', key='ai_submit_approval', width='stretch'):
                try:
                    ar = requests.post(
                        approval_api_url(),
                        json={
                            'ci_name': str(pro.get('ci_name', ci_for_proactive)),
                            'incident_id': str(incident_id),
                            'decision': ai_decision,
                            'approved_action': ai_action,
                            'reviewer': ai_reviewer,
                            'comments': ai_comments,
                        },
                        timeout=30,
                    )
                    ar.raise_for_status()
                    saved = ar.json()
                    st.session_state.approval_result = saved
                    status = (saved.get('approval') or {}).get('governance_status', 'Recorded')
                    st.success(f'Approval decision recorded: {status}. No production change was executed.')
                except requests.HTTPError:
                    st.error(f'Approval API returned HTTP {ar.status_code}: {ar.text[:1000]}')
                except Exception as exc:
                    st.error(f'Approval submission failed: {type(exc).__name__}: {exc}')
