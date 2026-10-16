"""
analytics.py - the ONLY place where numbers are calculated.
dashboard.py and ui.py just display what is returned here.
"""
from __future__ import annotations
import re
from pathlib import Path
import pandas as pd
import config
CANON_COLS = list(config.COLUMN_ALIASES.keys())

def _norm(s) -> str:
    return re.sub('[^a-z0-9]', '', str(s).lower())
_ALIAS_LOOKUP = {_norm(a): canon for canon, aliases in config.COLUMN_ALIASES.items() for a in aliases}

def list_data_files(data_dir: Path=config.CSV_DIR) -> list[Path]:
    return sorted((p for p in Path(data_dir).glob('*') if p.suffix.lower() in config.SUPPORTED_EXTENSIONS))

def data_signature(data_dir: Path=config.CSV_DIR) -> tuple:
    """Changes whenever a file is added / removed / modified (used for cache invalidation)."""
    return tuple(((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in list_data_files(data_dir)))

def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in ('.xlsx', '.xls'):
        return pd.read_excel(path)
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f'Cannot decode {path.name}')

def _std_priority(v) -> str:
    s = str(v).strip().lower()
    for label, pattern in config.PRIORITY_PATTERNS:
        if re.search(pattern, s):
            return label
    return 'Unknown'

def load_file(path: Path) -> pd.DataFrame:
    raw = _read(Path(path))
    rename = {}
    for col in raw.columns:
        canon = _ALIAS_LOOKUP.get(_norm(col))
        if canon and canon not in rename.values():
            rename[col] = canon
    df = raw.rename(columns=rename)
    df = df[[c for c in df.columns if c in CANON_COLS]].copy()
    for c in CANON_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    df['source_file'] = Path(path).name
    return df

def load_all(data_dir: Path=config.CSV_DIR) -> pd.DataFrame:
    frames = []
    for p in list_data_files(data_dir):
        try:
            frames.append(load_file(p))
        except Exception as exc:
            print(f'[analytics] skipped {p.name}: {exc}')
    cols = CANON_COLS + ['source_file']
    if not frames:
        return pd.DataFrame(columns=cols + ['search_text'])
    df = pd.concat(frames, ignore_index=True)
    df['opened_at'] = pd.to_datetime(df['opened_at'], errors='coerce', dayfirst=config.DATE_DAYFIRST)
    df['closed_at'] = pd.to_datetime(df['closed_at'], errors='coerce', dayfirst=config.DATE_DAYFIRST)
    df['priority'] = df['priority'].map(_std_priority)
    for c in ('incident_id', 'route_case', 'closure_code', 'server', 'ci_name'):
        df[c] = df[c].fillna('Unknown').astype(str).str.strip().replace({'': 'Unknown', 'nan': 'Unknown'})
        df["incident_id"] = (
            df["incident_id"]
            .map(_normalize_search_value)
            .replace("", "Unknown")
        )
    for c in ('description', 'resolution'):
        df[c] = df[c].fillna('').astype(str).str.strip()
    if config.DEDUPE_BY_INCIDENT_ID:
        has_id = df['incident_id'].ne('Unknown')
        df = pd.concat([df[has_id].drop_duplicates('incident_id', keep='last'), df[~has_id]]).sort_index()
    df = df.reset_index(drop=True)
    df['ci_name'] = df['ci_name'].where(df['ci_name'] != 'Unknown', df['server'])
    if 'it service' in df.columns:
        df['ci_name'] = df['ci_name'].where(df['ci_name'] != 'Unknown', df['it service'])
    duration = (df['closed_at'] - df['opened_at']).dt.total_seconds() / 3600.0
    df['mttr_hours'] = duration.where(duration >= 0)
    df['search_text'] = (df['description'] + '. ' + df['resolution'] + '. CI: ' + df['ci_name'] + '. Closure: ' + df['closure_code']).str[:config.MAX_TEXT_CHARS]
    return df

def apply_filters(df, start=None, end=None, priorities=None, server=None, sources=None, ci_name=None) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if start:
        m &= df['opened_at'] >= pd.Timestamp(start)
    if end:
        m &= df['opened_at'] < pd.Timestamp(end) + pd.Timedelta(days=1)
    if priorities:
        m &= df['priority'].isin(priorities)
    if server and server != 'All':
        m &= df['ci_name'] == server
    if ci_name and ci_name != 'All':
        m &= df['ci_name'].str.contains(str(ci_name), case=False, na=False)
    if sources:
        m &= df['source_file'].isin(sources)
    return df[m]

def is_single_month(df: pd.DataFrame) -> bool:
    d = df['opened_at'].dropna()
    return d.dt.to_period('M').nunique() <= 1

def monthly_trend(df: pd.DataFrame):
    """One month of data -> daily points. Several months -> monthly points."""
    d = df.dropna(subset=['opened_at'])
    if d.empty:
        return (pd.DataFrame(columns=['period', 'count']), 'month')
    if is_single_month(d):
        per = d['opened_at'].min().to_period('M')
        idx = pd.date_range(per.start_time, per.end_time.normalize())
        s = d['opened_at'].dt.normalize().value_counts().reindex(idx, fill_value=0).sort_index()
        return (pd.DataFrame({'period': s.index, 'count': s.values}), 'day')
    g = d.groupby(d['opened_at'].dt.to_period('M')).size()
    g = g.reindex(pd.period_range(g.index.min(), g.index.max(), freq='M'), fill_value=0)
    return (pd.DataFrame({'period': g.index.to_timestamp(), 'count': g.values}), 'month')

def priority_trend(df: pd.DataFrame):
    """Counts per priority per period (month; weeks when only one month is loaded)."""
    d = df.dropna(subset=['opened_at']).copy()
    if d.empty:
        return (pd.DataFrame(columns=['period', 'priority', 'count']), 'month')
    if is_single_month(d):
        d['period'] = d['opened_at'].dt.to_period('W-SUN').dt.start_time
        gran = 'week'
    else:
        d['period'] = d['opened_at'].dt.to_period('M').dt.to_timestamp()
        gran = 'month'
    out = d.groupby(['period', 'priority']).size().reset_index(name='count')
    return (out.sort_values('period'), gran)

def top_n(df: pd.DataFrame, col: str, n: int=config.TOP_N, exclude_unknown: bool=True) -> pd.DataFrame:
    s = df[col]
    if exclude_unknown:
        s = s[s != 'Unknown']
    vc = s.value_counts().head(n)
    total = max(len(df), 1)
    return pd.DataFrame({'name': vc.index, 'count': vc.values, 'share': vc.values / total * 100})

def mttr_hours(df: pd.DataFrame) -> float:
    """Mean time to resolve in hours. Uses opened_at -> closed_at only for valid durations."""
    if 'mttr_hours' not in df.columns:
        return 0.0
    s = pd.to_numeric(df['mttr_hours'], errors='coerce').dropna()
    return float(s.mean()) if len(s) else 0.0

def mttr_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly MTTR trend. Excludes incidents without valid resolution duration."""
    d = df.dropna(subset=['opened_at', 'mttr_hours']).copy()
    if d.empty:
        return pd.DataFrame(columns=['period', 'mttr_hours', 'incident_count'])
    d['period'] = d['opened_at'].dt.to_period('M').dt.to_timestamp()
    out = d.groupby('period').agg(mttr_hours=('mttr_hours', 'mean'), incident_count=('incident_id', 'size')).reset_index()
    return out.sort_values('period')

def mttr_by_priority(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=['mttr_hours']).copy()
    if d.empty:
        return pd.DataFrame(columns=['priority', 'mttr_hours', 'incident_count'])
    out = d.groupby('priority').agg(mttr_hours=('mttr_hours', 'mean'), incident_count=('incident_id', 'size')).reset_index()
    order = {p: i for i, p in enumerate(config.PRIORITY_ORDER)}
    out['_order'] = out['priority'].map(order).fillna(999)
    return out.sort_values('_order').drop(columns='_order')

def kpis(df: pd.DataFrame) -> dict:
    total = len(df)
    ch = int(df['priority'].isin(['Critical', 'High']).sum())
    tc = top_n(df, 'closure_code', 1)
    d = df['opened_at'].dropna()
    valid_mttr = int(df['mttr_hours'].notna().sum()) if 'mttr_hours' in df.columns else 0
    avg_mttr = mttr_hours(df)
    return {'total': total, 'critical_high': ch, 'critical_high_pct': ch / total * 100 if total else 0, 'mttr_hours': avg_mttr, 'mttr_display': f'{avg_mttr:.1f} h' if valid_mttr else '-', 'mttr_valid_incidents': valid_mttr, 'top_closure': tc['name'].iloc[0] if len(tc) else '-', 'date_from': d.min().date().isoformat() if len(d) else '-', 'date_to': d.max().date().isoformat() if len(d) else '-', 'files': int(df['source_file'].nunique())}

def _mode(s: pd.Series) -> str:
    s = s[s != 'Unknown']
    return s.mode().iloc[0] if len(s) else '-'

def server_analysis(df: pd.DataFrame, n: int=25, search: str='') -> pd.DataFrame:
    d = df[df['ci_name'] != 'Unknown']
    if search:
        d = d[d['ci_name'].str.contains(str(search), case=False, na=False)]
    if d.empty:
        return pd.DataFrame(columns=['ci_name', 'total', 'critical', 'high', 'top_closure_code', 'top_route_case'])
    g = d.groupby('ci_name')
    out = pd.DataFrame({'total': g.size(), 'critical': g['priority'].apply(lambda s: (s == 'Critical').sum()), 'high': g['priority'].apply(lambda s: (s == 'High').sum()), 'top_closure_code': g['closure_code'].apply(_mode), 'top_route_case': g['route_case'].apply(_mode)}).sort_values('total', ascending=False).head(n)
    return out.reset_index()

def _normalize_search_value(value) -> str:
    """
    Convert dataframe values into searchable strings.
    """

    if pd.isna(value):
        return ""

    text = str(value).strip()

    # Handle values such as 12345.0
    if text.endswith(".0"):
        try:
            numeric = float(text)

            if numeric.is_integer():
                text = str(int(numeric))

        except (ValueError, TypeError):
            pass

    return text


def search_incidents(
    df: pd.DataFrame,
    query: str = "",
) -> pd.DataFrame:
    """
    Search incidents by incident number, CI name, server,
    route cause, closure code, description, resolution and priority.

    Incident-number matching is normalized so values such as
    INC0012345, inc0012345 and INC0012345.0 can be found.
    """

    if not query or not str(query).strip():
        return df.copy()

    query_text = str(query).strip()
    query_normalized = query_text.lower()

    # Search fields
    search_columns = [
        "incident_id",
        "ci_name",
        "server",
        "route_case",
        "closure_code",
        "description",
        "resolution",
        "priority",
    ]

    mask = pd.Series(False, index=df.index)

    for column in search_columns:
        if column not in df.columns:
            continue

        values = df[column].map(_normalize_search_value)

        mask |= (
            values
            .str.lower()
            .str.contains(
                query_normalized,
                regex=False,
                na=False,
            )
        )

    return df.loc[mask].copy()

def recurring_issues(df: pd.DataFrame, n: int=10) -> pd.DataFrame:
    d = df[df['description'] != ''].copy()
    if d.empty:
        return pd.DataFrame(columns=['issue', 'count', 'servers_affected', 'top_closure_code'])
    d['key'] = d['description'].str.lower().str.replace('\\d+|0x[0-9a-f]+', '#', regex=True).str.replace('\\s+', ' ', regex=True).str.strip().str[:80]
    g = d.groupby('key')
    out = pd.DataFrame({'count': g.size(), 'servers_affected': g['ci_name'].nunique(), 'top_closure_code': g['closure_code'].apply(_mode)}).sort_values('count', ascending=False).head(n).reset_index().rename(columns={'key': 'issue'})
    return out[['issue', 'count', 'servers_affected', 'top_closure_code']]

def peak_times(df: pd.DataFrame) -> dict:
    d = df['opened_at'].dropna()
    if d.empty or (d.dt.hour == 0).all():
        return {}
    return {'weekday': d.dt.day_name().mode().iloc[0], 'hour': int(d.dt.hour.mode().iloc[0])}

def top_route_causes(df: pd.DataFrame, n: int=config.TOP_N) -> pd.DataFrame:
    """Return the best available route-cause dimension for the dataset.

    Prefer route_case, then group, then incident type. This keeps older exports
    useful while making route_case the canonical field when it exists.
    """
    candidates = ['route_case', 'group', 'incident type']
    for col in candidates:
        if col in df.columns:
            s = df[col].fillna('Unknown').astype(str).str.strip()
            s = s[(s != '') & (s.str.lower() != 'unknown') & (s.str.lower() != 'nan')]
            if len(s):
                vc = s.value_counts().head(n)
                total = max(len(df), 1)
                return pd.DataFrame({'name': vc.index, 'count': vc.values, 'share': vc.values / total * 100})
    return pd.DataFrame(columns=['name', 'count', 'share'])

def ci_incidents(df: pd.DataFrame, ci_name: str) -> pd.DataFrame:
    """Return all past incidents for one searched CI name, newest first."""
    if not ci_name or 'ci_name' not in df.columns:
        return df.iloc[0:0].copy()
    m = df['ci_name'].astype(str).str.contains(str(ci_name), case=False, regex=False, na=False)
    return df[m].sort_values('opened_at', ascending=False, na_position='last').copy()

def ci_proactive_actions(df: pd.DataFrame, ci_name: str) -> list[dict]:
    """CI-specific proactive measures derived from incident patterns."""
    d = ci_incidents(df, ci_name)
    if d.empty:
        return []
    actions = proactive_actions(d)
    route = top_route_causes(d, 1)
    closure = top_n(d, 'closure_code', 1)
    priority = d['priority'].value_counts()
    critical_high = int(d['priority'].isin(['Critical', 'High']).sum())
    detail = []
    if len(route):
        detail.append(f"Most common route cause: {route.iloc[0]['name']} ({int(route.iloc[0]['count'])} incident(s)).")
    if len(closure):
        detail.append(f"Most common closure code: {closure.iloc[0]['name']} ({int(closure.iloc[0]['count'])} incident(s)).")
    if critical_high:
        detail.append(f'{critical_high} of {len(d)} incidents were Critical/High; prioritize resilience and monitoring checks.')
    if not actions:
        actions.append({'severity': 'Medium', 'area': 'CI proactive measure', 'finding': f'{ci_name} has {len(d)} historical incident(s). ' + ' '.join(detail), 'action': 'Use the recurring incident pattern to open a problem record, validate monitoring/alert thresholds, check recent changes and patch/resource health, and automate the most repeated recovery step.'})
    return actions

def proactive_actions(df: pd.DataFrame) -> list[dict]:
    """Rule-based, explainable recommendations. Each: severity / area / finding / action."""
    R, acts, total = (config.RULES, [], len(df))
    if total == 0:
        return acts
    trend, gran = monthly_trend(df)
    if gran == 'month' and len(trend) >= 2:
        last, prev = (trend['count'].iloc[-1], trend['count'].iloc[-2])
        if prev > 0 and (last - prev) / prev * 100 >= R['trend_increase_pct']:
            acts.append(dict(severity='High', area='Trend', finding=f'Incidents rose {(last - prev) / prev * 100:.0f}% in the latest month ({prev} -> {last}).', action='Hold a trend review: compare changes/releases of the last 30 days and add capacity or monitoring where volume grew.'))
    ts = top_n(df, 'ci_name', 3)
    for _, r in ts.iterrows():
        if r['share'] >= R['top_server_share_pct']:
            acts.append(dict(severity='High', area='Server', finding=f"{r['name']} generates {r['share']:.0f}% of all incidents ({r['count']}).", action=f"Open a problem record for {r['name']}: run root-cause analysis, check patch level / resource utilisation, plan remediation or replacement."))
    ch = df['priority'].isin(['Critical', 'High']).mean() * 100
    if ch >= R['critical_high_share_pct']:
        acts.append(dict(severity='High', area='Priority', finding=f'{ch:.0f}% of incidents are Critical/High.', action='Review monitoring thresholds, auto-escalation and resilience (failover, redundancy) for services behind Critical/High tickets.'))
    noisy = df['closure_code'].str.contains(config.NOISE_CLOSURE_PATTERN, case=False, regex=True)
    if noisy.mean() * 100 >= R['noise_closure_share_pct']:
        acts.append(dict(severity='Medium', area='Closure codes', finding=f'{noisy.mean() * 100:.0f}% of incidents closed as no-fault / duplicate / self-healed / false alarm.', action='Tune alert rules, add de-duplication and suppression windows to cut alert noise and analyst effort.'))
    tr = top_n(df, 'route_case', 1)
    if len(tr) and tr['share'].iloc[0] >= R['top_route_share_pct']:
        acts.append(dict(severity='Medium', area='Route case', finding=f"'{tr['name'].iloc[0]}' carries {tr['share'].iloc[0]:.0f}% of incidents.", action='Check team capacity and runbooks for this route; automate frequent resolutions (self-service / scripts).'))
    ri = recurring_issues(df, 3)
    for _, r in ri.iterrows():
        if r['count'] >= R['recurring_min_count']:
            acts.append(dict(severity='Medium', area='Recurring issue', finding=f"'{r['issue']}' occurred {r['count']} times across {r['servers_affected']} server(s).", action='Create a known-error / problem ticket, document a permanent fix and automate the standard resolution.'))
    pk = peak_times(df)
    if pk:
        acts.append(dict(severity='Low', area='Staffing', finding=f"Incidents peak on {pk['weekday']}s around {pk['hour']:02d}:00.", action='Align on-call cover and avoid scheduling changes in that window.'))
    return acts

def summary_text(df: pd.DataFrame) -> str:
    """Compact fact sheet handed to the LLM so it answers from real numbers."""
    k = kpis(df)
    trend, gran = monthly_trend(df)
    lines = [f"Incidents: {k['total']} ({k['date_from']} to {k['date_to']}), files: {k['files']}", f"Critical/High: {k['critical_high']} ({k['critical_high_pct']:.0f}%)", 'Priority split: ' + ', '.join((f'{p}={n}' for p, n in df['priority'].value_counts().items()))]
    for label, col in (('Top CI names', 'ci_name'), ('Top route cases', 'route_case'), ('Top closure codes', 'closure_code')):
        t = top_route_causes(df, 5) if col == 'route_case' else top_n(df, col, 5)
        lines.append(f'{label}: ' + '; '.join((f"{r['name']} ({r['count']})" for _, r in t.iterrows())))
    if len(trend):
        lines.append(f'{gran.capitalize()} trend: ' + ', '.join((f'{p:%d %b}={c}' if gran == 'day' else f'{p:%b %Y}={c}' for p, c in zip(trend['period'], trend['count'])))[:600])
    return '\n'.join(lines)
