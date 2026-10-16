"""Altair-only dashboard charts. All calculations come from analytics.py."""
from __future__ import annotations
import pandas as pd
import altair as alt
import analytics
import config

def _empty(title: str, msg: str='No data for the selected filters') -> alt.Chart:
    data = pd.DataFrame({'message': [msg]})
    return alt.Chart(data).mark_text(size=16).encode(text='message:N').properties(title=title, width='container', height=260).configure_view(strokeOpacity=0)

def _base(chart: alt.Chart, title: str, subtitle: str='', height: int=320) -> alt.Chart:
    return chart.properties(title=alt.TitleParams(text=title, subtitle=subtitle or None, anchor='start'), width='container', height=height).configure_axis(labelFontSize=11, titleFontSize=11).configure_title(fontSize=17, anchor='start').configure_legend(titleFontSize=11, labelFontSize=11).configure_view(strokeOpacity=0).configure_concat(spacing=8)

def monthly_incident_trend(df) -> alt.Chart:
    data, gran = analytics.monthly_trend(df)
    title = 'Daily Incident Trend' if gran == 'day' else 'Monthly Incident Trend'
    if data.empty:
        return _empty(title)
    d = data.copy()
    peak = int(d['count'].max())
    x = alt.X('period:T', title=None, axis=alt.Axis(format='%d %b' if gran == 'day' else '%b %Y', labelOverlap=True))
    line = alt.Chart(d).mark_line(point=True, strokeWidth=2.5).encode(x=x, y=alt.Y('count:Q', title='Incidents', scale=alt.Scale(zero=True)), tooltip=[alt.Tooltip('period:T', title='Period'), alt.Tooltip('count:Q', title='Incidents')])
    return _base(line, title, f"{int(d['count'].sum()):,} incidents | Peak: {peak:,}")

def priority_trend(df) -> alt.Chart:
    data, gran = analytics.priority_trend(df)
    if data.empty:
        return _empty('Priority Trend')
    d = data.copy()
    d['label'] = d['period'].dt.strftime('Wk of %d %b' if gran == 'week' else '%b %Y')
    order = d.sort_values('period')['label'].drop_duplicates().tolist()
    chart = alt.Chart(d).mark_bar().encode(x=alt.X('label:N', title=None, sort=order), xOffset=alt.XOffset('priority:N'), y=alt.Y('count:Q', title='Incidents', scale=alt.Scale(zero=True)), color=alt.Color('priority:N', sort=config.PRIORITY_ORDER, title='Priority'), tooltip=[alt.Tooltip('label:N', title='Period'), alt.Tooltip('priority:N', title='Priority'), alt.Tooltip('count:Q', title='Incidents')])
    return _base(chart, 'Priority Trend', 'per week' if gran == 'week' else 'per month')

def _hbar(data: pd.DataFrame, title: str, subtitle: str='') -> alt.Chart:
    if data.empty:
        return _empty(title)
    d = data.copy().sort_values('count', ascending=True).tail(config.TOP_N)
    chart = alt.Chart(d).mark_bar().encode(x=alt.X('count:Q', title='Incidents', scale=alt.Scale(zero=True)), y=alt.Y('name:N', title=None, sort=None, axis=alt.Axis(labelLimit=240)), tooltip=[alt.Tooltip('name:N', title='Name'), alt.Tooltip('count:Q', title='Incidents'), alt.Tooltip('share:Q', title='Share', format='.1f')])
    return _base(chart, title, subtitle, 330)

def top_route_cases(df):
    return _hbar(analytics.top_route_causes(df), 'Top 10 Route Causes', 'Based on route case / assignment group / category')

def top_closure_codes(df):
    return _hbar(analytics.top_n(df, 'closure_code'), 'Top 10 Closure Codes', 'Share of incidents')

def top_servers(df):
    return _hbar(analytics.top_n(df, 'ci_name'), 'Top 10 CI Names', 'Based on ci_name')

def mttr_trend(df) -> alt.Chart:
    d = analytics.mttr_trend(df)
    if d.empty:
        return _empty('MTTR Trend', 'No incidents with both opened and closed timestamps')
    chart = alt.Chart(d).mark_line(point=True, strokeWidth=2.5).encode(x=alt.X('period:T', title=None, axis=alt.Axis(format='%b %Y', labelOverlap=True)), y=alt.Y('mttr_hours:Q', title='MTTR (hours)', scale=alt.Scale(zero=True)), tooltip=[alt.Tooltip('period:T', title='Month', format='%b %Y'), alt.Tooltip('mttr_hours:Q', title='MTTR (hours)', format='.1f'), alt.Tooltip('incident_count:Q', title='Resolved incidents')])
    return _base(chart, 'MTTR Trend', 'Mean time to resolve by month', 320)

def mttr_priority(df) -> alt.Chart:
    d = analytics.mttr_by_priority(df)
    if d.empty:
        return _empty('MTTR by Priority', 'No valid resolution durations')
    chart = alt.Chart(d).mark_bar().encode(x=alt.X('priority:N', title=None, sort=config.PRIORITY_ORDER), y=alt.Y('mttr_hours:Q', title='MTTR (hours)', scale=alt.Scale(zero=True)), tooltip=[alt.Tooltip('priority:N', title='Priority'), alt.Tooltip('mttr_hours:Q', title='MTTR (hours)', format='.1f'), alt.Tooltip('incident_count:Q', title='Resolved incidents')])
    return _base(chart, 'MTTR by Priority', 'Average resolution time', 320)

def build_dashboard(df: pd.DataFrame) -> dict:
    return {'kpis': analytics.kpis(df), 'figures': {'monthly_trend': monthly_incident_trend(df), 'priority_trend': priority_trend(df), 'top_route_cases': top_route_cases(df), 'top_closure_codes': top_closure_codes(df), 'top_servers': top_servers(df), 'mttr_trend': mttr_trend(df), 'mttr_priority': mttr_priority(df)}}
