from __future__ import annotations
from pathlib import Path
import re
import pandas as pd
import requests
import analytics
import config
try:
    import chromadb
except Exception:
    chromadb = None

def _norm(s: str) -> str:
    return re.sub('[^a-z0-9]+', ' ', str(s).lower()).strip()

def _chroma_collection():
    if chromadb is None:
        return None
    path = str(config.DATA_DIR / 'chroma')
    client = chromadb.PersistentClient(path=path)
    return client.get_or_create_collection('knowledge')

def knowledge_search(query: str, n: int=4) -> list[dict]:
    try:
        col = _chroma_collection()
        if col is None or col.count() == 0:
            return []
        result = col.query(query_texts=[query], n_results=n)
        docs = (result.get('documents') or [[]])[0]
        metas = (result.get('metadatas') or [[]])[0]
        distances = (result.get('distances') or [[]])[0]
        out = []
        for i, text in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            dist = distances[i] if i < len(distances) else None
            out.append({'source': meta.get('source', 'knowledge'), 'location': meta.get('location', ''), 'text': text, 'score': round(1 / (1 + dist), 3) if dist is not None else None})
        return out
    except Exception:
        return []

def _matching_incidents(df: pd.DataFrame, q: str) -> pd.DataFrame:
    if not q.strip():
        return df.copy()
    qn = _norm(q)
    tokens = [t for t in qn.split() if len(t) > 1]
    cols = [c for c in ['incident_id', 'ci_name', 'server', 'description', 'resolution', 'priority', 'route_case', 'closure_code'] if c in df.columns]
    text = df[cols].fillna('').astype(str).agg(' '.join, axis=1).str.lower()
    mask = text.str.contains(q.strip().lower(), regex=False, na=False)
    if not mask.any() and tokens:
        mask = pd.Series(True, index=df.index)
        for token in tokens:
            mask &= text.str.contains(re.escape(token), regex=True, na=False)
    return df[mask].copy()

def answer(question: str, df: pd.DataFrame) -> dict:
    q = str(question).strip()
    ql = q.lower()
    if not q:
        return {'answer': 'Please enter a question.', 'similar_incidents': [], 'knowledge_sources': [], 'proactive_actions': []}
    matches = _matching_incidents(df, q)
    actions = analytics.proactive_actions(matches if len(matches) else df)
    if len(matches):
        ci_counts = matches['ci_name'].value_counts().head(5) if 'ci_name' in matches else pd.Series(dtype=int)
        ci_text = ', '.join((f'{name} ({count})' for name, count in ci_counts.items() if str(name) != 'Unknown')) or '-'
        priority = matches['priority'].value_counts().to_dict()
        top_desc = matches['description'].value_counts().head(3).index.tolist() if 'description' in matches else []
        answer_lines = [f'I found **{len(matches):,} incident(s)** matching **{q}**.', f'**CI name(s):** {ci_text}', '**Priority:** ' + (', '.join((f'{k}={v}' for k, v in priority.items())) or '-')]
        if top_desc:
            answer_lines.append('**Common incident descriptions:** ' + '; '.join(map(str, top_desc)))
        if len(matches) == 1:
            r = matches.iloc[0]
            answer_lines.append(f"**Incident {r.get('incident_id', '-')}:** {r.get('description', '')} — {r.get('resolution', '')}")
        similar = matches.head(5).copy()
        display_cols = [c for c in ['incident_id', 'ci_name', 'priority', 'description', 'resolution', 'closure_code'] if c in similar.columns]
        similar = similar[display_cols].copy()
        for c in similar.columns:
            similar[c] = similar[c].map(lambda x: x.isoformat() if hasattr(x, 'isoformat') and (not isinstance(x, str)) else x)
        return {'answer': '\n\n'.join(answer_lines), 'similar_incidents': similar.to_dict('records'), 'knowledge_sources': knowledge_search(q), 'proactive_actions': actions}
    kb = knowledge_search(q)
    if kb:
        return {'answer': 'I could not find an exact incident match. I found the following relevant knowledge content:\n\n' + kb[0]['text'], 'similar_incidents': [], 'knowledge_sources': kb, 'proactive_actions': actions}
    if any((word in ql for word in ['how many', 'count', 'total', 'number of'])):
        return {'answer': f'The current filtered dataset contains **{len(df):,} incidents**.', 'similar_incidents': [], 'knowledge_sources': [], 'proactive_actions': actions}
    return {'answer': 'I could not find a matching incident or indexed knowledge document. Try an incident number, CI name, server name, or a distinctive part of the incident description.', 'similar_incidents': [], 'knowledge_sources': [], 'proactive_actions': actions}

def _ollama_generate(prompt: str) -> str:
    """Generate text using the locally running Ollama model."""
    url = config.OLLAMA_URL.rstrip('/') + '/api/generate'
    payload = {'model': config.OLLAMA_MODEL, 'prompt': prompt, 'stream': False, 'options': {'temperature': config.OLLAMA_TEMPERATURE, 'num_predict': config.OLLAMA_NUM_PREDICT}}
    r = requests.post(url, json=payload, timeout=config.OLLAMA_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return str(data.get('response', '')).strip()

def ci_proactive_measure(df: pd.DataFrame, ci_name: str) -> dict:
    """AI-only proactive analysis. Facts are calculated by Python; Ollama only reasons over them."""
    incidents = analytics.ci_incidents(df, ci_name)
    if incidents.empty:
        return {'recommendation': f'No historical incidents were found for {ci_name}.', 'risk_level': 'LOW', 'immediate_actions': [], 'preventive_measures': [], 'monitoring_recommendations': [], 'long_term_remediation': [], 'knowledge': []}
    route = analytics.top_route_causes(incidents, 5)
    route_text = ', '.join((f"{r['name']} ({int(r['count'])})" for _, r in route.iterrows())) or '-'
    k = analytics.kpis(incidents)
    mttr = analytics.mttr_hours(incidents)
    kb = knowledge_search(f'{ci_name} recurring incident root cause prevention remediation monitoring {route_text}', n=4)
    knowledge_text = '\n\n'.join((f"SOURCE: {x['source']}\n{x['text']}" for x in kb))[:7000] or 'No indexed knowledge was found.'
    incident_rows = []
    cols = ['incident_id', 'opened_at', 'closed_at', 'priority', 'ci_name', 'route_case', 'closure_code', 'description', 'resolution']
    for _, r in incidents.head(50).iterrows():
        incident_rows.append({c: r.get(c).isoformat() if hasattr(r.get(c), 'isoformat') else str(r.get(c, '')) for c in cols})
    prompt = f"You are an IT operations problem-management expert. Generate proactive remediation steps for CI '{ci_name}'.\n\nSTRICT RULES:\n- Use only the supplied incident facts and retrieved knowledge.\n- Do not invent incident IDs, dates, counts, root causes, products, or historical events.\n- Python-calculated numbers are authoritative.\n- Clearly label a recommendation as a validation step when evidence is insufficient.\n- Give concrete, operational steps that an IT operations team can execute.\n- Return concise sections: Risk level, Summary, Immediate actions, Preventive measures, Monitoring recommendations, Long-term remediation.\n\nPYTHON FACTS:\nTotal incidents: {len(incidents)}\nCritical/High: {k['critical_high']} ({k['critical_high_pct']:.1f}%)\nAverage MTTR hours: {mttr:.1f} ({k['mttr_valid_incidents']} valid durations)\nTop route causes: {route_text}\nTop closure code: {k['top_closure']}\nDate range: {k['date_from']} to {k['date_to']}\n\nHISTORICAL INCIDENTS:\n{incident_rows}\n\nRETRIEVED KNOWLEDGE:\n{knowledge_text}\n"
    try:
        generated = _ollama_generate(prompt)
        recommendation = generated or 'The AI engine returned an empty response.'
    except Exception as exc:
        recommendation = f'AI engine unavailable ({type(exc).__name__}: {exc}). Review the recurring route causes ({route_text}), validate recent changes and resource health, and create a problem record for repeated incidents.'
    return {'recommendation': recommendation, 'risk_level': 'HIGH' if k['critical_high_pct'] >= 30 or len(incidents) >= 10 else 'MEDIUM', 'immediate_actions': [], 'preventive_measures': [], 'monitoring_recommendations': [], 'long_term_remediation': [], 'knowledge': kb}
