"""Incident Copilot FastAPI API - production grounded agents."""
from __future__ import annotations
import json, os, re, threading, time
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import analytics, config

OLLAMA_URL=os.getenv("OLLAMA_URL","http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL=os.getenv("OLLAMA_MODEL","llama3.2:1b")
OLLAMA_TIMEOUT=int(os.getenv("OLLAMA_TIMEOUT","45"))
OLLAMA_TEMPERATURE=float(os.getenv("OLLAMA_TEMPERATURE","0.2"))
AGENT2_PREDICT=int(os.getenv("AGENT2_NUM_PREDICT","45"))
AGENT3_PREDICT=int(os.getenv("AGENT3_NUM_PREDICT","45"))
CHROMA_DIR=Path(os.getenv("CHROMA_DIR",str(config.DATA_DIR/"chroma")))
FEEDBACK_FILE=Path(config.DATA_DIR)/"incident_feedback.json"
FEEDBACK_LOCK=threading.Lock()
SERVER_LIMIT=10
DF: pd.DataFrame|None=None
COLLECTION=None

class IncidentRequest(BaseModel): incident_id:str
class ProactiveRequest(BaseModel): ci_name:str
class FeedbackRequest(BaseModel):
    incident_id:str
    decision:str
    corrected_root_cause:str=""
    corrective_action:str=""
    preventive_action:str=""
    comments:str=""
    reviewer:str="Human reviewer"

@asynccontextmanager
async def lifespan(app:FastAPI):
    global DF,COLLECTION
    DF=analytics.load_all()
    print(f"[startup] incidents={len(DF):,}")
    try:
        import chromadb
        client=chromadb.PersistentClient(path=str(CHROMA_DIR))
        COLLECTION=client.get_collection("knowledge")
        print(f"[startup] knowledge_chunks={COLLECTION.count():,}")
    except Exception as exc: print(f"[startup] knowledge unavailable: {exc}")
    print(f"[startup] model={OLLAMA_MODEL} timeout={OLLAMA_TIMEOUT}s")
    yield

app=FastAPI(title="Incident Copilot API",version="3.0.0",lifespan=lifespan)

def data()->pd.DataFrame:
    if DF is None: raise HTTPException(503,"Incident dataset is not initialized")
    return DF

def norm(v:Any)->str:
    if v is None: return ""
    try:
        if pd.isna(v): return ""
    except Exception: pass
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9\s_-]"," ",str(v).strip().lower())).strip()

def ci_filter(df,ci):
    q=norm(ci)
    if not q or "ci_name" not in df.columns: return df.iloc[0:0].copy()
    s=df["ci_name"].fillna("").astype(str).str.strip().str.lower()
    exact=df.loc[s==q]
    return exact.copy() if not exact.empty else df.loc[s.str.contains(q,regex=False,na=False)].copy()

def recent(df,limit):
    out=df.copy()
    if "opened_at" in out.columns:
        out["_d"]=pd.to_datetime(out["opened_at"],errors="coerce")
        out=out.sort_values("_d",ascending=False,na_position="last").drop(columns="_d")
    return out.head(limit)

def clean_records(df,limit=None):
    x=recent(df,limit or len(df)).fillna("")
    return x.astype(str).to_dict(orient="records")

def top(df,col,n=5):
    if col not in df.columns: return []
    s=df[col].fillna("Unknown").astype(str).str.strip(); s=s[s!=""]
    return [{"name":str(k),"count":int(v)} for k,v in s.value_counts().head(n).items()]

def incident(row):
    return {"incident_id":str(row.get("incident_id","")),"ci_name":str(row.get("ci_name","Unknown")),"priority":str(row.get("priority","Unknown")),"route_case":str(row.get("route_case",row.get("route_cause","Unknown"))),"closure_code":str(row.get("closure_code","Unknown")),"description":str(row.get("description",""))[:700],"resolution":str(row.get("resolution",""))[:700],"opened_at":str(row.get("opened_at",""))}

def by_id(df,i):
    if "incident_id" not in df.columns:return None
    m=df.loc[df["incident_id"].map(norm)==norm(i)]
    return None if m.empty else m.iloc[0]

def feedback_load():
    if not FEEDBACK_FILE.exists(): return {}
    try:
        with FEEDBACK_LOCK:return json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    except Exception:return {}

def feedback_save(x):
    FEEDBACK_FILE.parent.mkdir(parents=True,exist_ok=True); tmp=FEEDBACK_FILE.with_suffix(".tmp")
    with FEEDBACK_LOCK:
        tmp.write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding="utf-8"); tmp.replace(FEEDBACK_FILE)

def knowledge_for(row,limit=1):
    if COLLECTION is None:return []
    terms=" ".join(str(row.get(c,"")) for c in ("description","resolution","it service","category","incident type","route_case","priority") if c in row.index).strip()
    if not terms:return []
    try:
        r=COLLECTION.query(query_texts=[terms[:700]],n_results=limit,include=["documents","metadatas","distances"])
        docs=r.get("documents",[[]])[0]; metas=r.get("metadatas",[[]])[0]; dists=r.get("distances",[[]])[0]
        return [{"source":str(metas[i].get("source","knowledge") if i<len(metas) else "knowledge"),"kind":str(metas[i].get("kind","") if i<len(metas) else ""),"content":str(docs[i])[:900],"distance":float(dists[i]) if i<len(dists) else None} for i in range(len(docs))]
    except Exception as exc:
        print(f"[knowledge] {exc}"); return []

def exact_matches(history,row,limit=5):
    if "description" not in history.columns:return []
    q=norm(row.get("description","")); m=history.loc[history["description"].map(norm)==q].copy()
    m=m.loc[m["incident_id"].map(norm)!=norm(row.get("incident_id",""))] if "incident_id" in m.columns else m
    return [{"incident_id":str(x.get("incident_id","")),"ci_name":str(x.get("ci_name","")),"description":str(x.get("description",""))[:180],"priority":str(x.get("priority","")),"closure_code":str(x.get("closure_code","")),"resolution":str(x.get("resolution",""))[:180]} for _,x in recent(m,limit).iterrows()]

def rca_evidence(row,history):
    desc=norm(row.get("description","")); exact=history["description"].map(norm).eq(desc) if "description" in history.columns else pd.Series(False,index=history.index)
    route=next((c for c in ("route_case","route_cause","root_cause") if c in history.columns),None)
    same_route=int(history[route].map(norm).eq(norm(row.get(route,""))).sum()) if route else 0
    return {"incident_facts":incident(row),"historical_incident_count":len(history),"same_description_count_in_ci":int(exact.sum()),"same_closure_count_in_ci":int(history["closure_code"].map(norm).eq(norm(row.get("closure_code",""))).sum()) if "closure_code" in history.columns else 0,"same_route_count_in_ci":same_route,"top_route_values":top(history,route,5) if route else [],"top_priority_values":top(history,"priority",5),"top_closure_values":top(history,"closure_code",5),"same_description_incidents":exact_matches(history,row,5)}

def proven_feedback(fb):
    if not fb:return None
    if fb.get("decision") in ("Approved","Modified") and fb.get("corrected_root_cause"," ").strip(): return fb["corrected_root_cause"].strip()
    return None

def call_ollama(prompt,label,predict):
    payload={"model":OLLAMA_MODEL,"prompt":prompt,"stream":False,"keep_alive":"10m","options":{"temperature":OLLAMA_TEMPERATURE,"num_predict":predict}}
    print(f"[agent:{label}] model={OLLAMA_MODEL} prompt={len(prompt)} chars")
    start=time.perf_counter()
    try:
        r=requests.post(f"{OLLAMA_URL}/api/generate",json=payload,timeout=(5,OLLAMA_TIMEOUT)); r.raise_for_status()
    except requests.exceptions.Timeout as exc: raise HTTPException(504,f"{label} timed out after {OLLAMA_TIMEOUT}s") from exc
    except requests.exceptions.RequestException as exc: raise HTTPException(503,f"AI service unavailable: {exc}") from exc
    elapsed=time.perf_counter()-start; answer=str(r.json().get("response","")).strip()
    print(f"[agent:{label}] generation={elapsed:.3f}s")
    if not answer: raise HTTPException(502,f"{label} returned an empty response")
    return answer,elapsed

def safe_rca_answer(evidence,feedback):
    validated=proven_feedback(feedback)
    if validated:
        return f"Human-validated RCA: {validated}.\n\nThe human reviewer approved or corrected the RCA; use the recorded corrective and preventive actions as the authoritative incident record."
    return "Root cause unconfirmed. The available incident history establishes recurrence and closure/resolution patterns, but it does not prove a technical root cause. Additional technical validation is required."

def rca_prompt(evidence,knowledge,feedback):
    compact={"incident":evidence["incident_facts"],"historical_count":evidence["historical_incident_count"],"same_description_count":evidence["same_description_count_in_ci"],"same_description_incidents":evidence["same_description_incidents"],"closure_patterns":evidence["top_closure_values"][:4],"human_feedback":feedback or "None"}
    return f"""Agent 2 — evidence-grounded RCA.\nRules: historical closure/resolution is evidence of what was done, not proof of why. Generic knowledge cannot establish RCA. Do not invent a technical cause. If human feedback contains a validated corrected root cause, report it as human-validated. Otherwise state Root cause unconfirmed.\nEVIDENCE={json.dumps(compact,ensure_ascii=False,separators=(',',':'))}\nKNOWLEDGE_GUIDANCE={json.dumps(knowledge[:1],ensure_ascii=False,separators=(',',':'))}\nReturn concise: Executive RCA; Pattern; Most likely root cause; Evidence; Corrective action; Preventive action; Confidence."""

def proactive_evidence(history):
    recurring=[]
    if "description" in history.columns:
        s=history["description"].fillna("").astype(str).str.strip(); n=s.map(norm); counts=n.value_counts()
        for k,v in counts.head(5).items():
            if k: recurring.append({"description":s[n.eq(k)].iloc[0][:160],"count":int(v)})
    return {"incident_count":len(history),"recurring_descriptions":recurring,"priorities":top(history,"priority",5),"closures":top(history,"closure_code",5)}

def proactive_prompt(ci,evidence,knowledge,feedback):
    return f"""Agent 3 — proactive IT remediation.\nUse only RISK EVIDENCE. Do not invent a technical cause or recommend an infrastructure change unless the evidence supports that domain. Knowledge is guidance only. If evidence is insufficient, recommend validation. Every action requires human approval.\nCI={ci}\nRISK EVIDENCE={json.dumps(evidence,ensure_ascii=False,separators=(',',':'))}\nKNOWLEDGE={json.dumps(knowledge[:1],ensure_ascii=False,separators=(',',':'))}\nHUMAN FEEDBACK={json.dumps(feedback[-2:],ensure_ascii=False,separators=(',',':'))}\nReturn: Key operational risk; Immediate checks (3); Preventive remediation (3); Monitoring/alerting (3); Human approval required: Yes."""

@app.get("/health")
def health(): return {"status":"ok","service":"incident-copilot-api","incidents_loaded":len(DF) if DF is not None else 0,"knowledge_chunks":COLLECTION.count() if COLLECTION else 0,"ollama_model":OLLAMA_MODEL}

@app.get("/api/server-analysis")
def server_analysis(ci_name:str=""):
    if not ci_name.strip():return {"total":0,"matched":0,"items":[]}
    v=ci_filter(data(),ci_name); return {"total":min(len(v),SERVER_LIMIT),"matched":len(v),"items":clean_records(v,SERVER_LIMIT)}

@app.get("/api/incidents/search")
def incident_search(q:str=""):
    v=analytics.search_incidents(data(),q); items=clean_records(v,100)
    fb=feedback_load()
    for x in items:x["human_feedback"]=fb.get(str(x.get("incident_id","")))
    cis=sorted(v["ci_name"].dropna().astype(str).unique().tolist()) if "ci_name" in v.columns else []
    return {"total":len(v),"ci_names":cis,"items":items}

@app.post("/api/agents/root-cause")
def root_cause(req:IncidentRequest):
    df=data(); row=by_id(df,req.incident_id)
    if row is None:raise HTTPException(404,f"Incident not found: {req.incident_id}")
    history=ci_filter(df,str(row.get("ci_name",""))); evidence=rca_evidence(row,history); fb=feedback_load().get(str(req.incident_id)); knowledge=knowledge_for(row,1)
    authoritative=safe_rca_answer(evidence,fb)
    prompt=rca_prompt(evidence,knowledge,fb)
    try: llm,elapsed=call_ollama(prompt,"root-cause",AGENT2_PREDICT)
    except HTTPException as exc:
        return {"incident":incident(row),"historical_incident_count":len(history),"similar_incidents":evidence["same_description_incidents"],"knowledge_sources":knowledge,"human_feedback":fb,"answer":authoritative,"evidence":evidence,"grounded_assessment":{"incident_id":str(row.get("incident_id")),"ci_name":str(row.get("ci_name")),"root_cause":authoritative,"confidence":"High" if proven_feedback(fb) else "Low","technical_cause_proven":bool(proven_feedback(fb)),"evidence_basis":"Human validation" if proven_feedback(fb) else "Deterministic incident evidence is inconclusive."},"model":OLLAMA_MODEL,"timing":{"ollama_seconds":None},"ai_status":"timeout" if exc.status_code==504 else "unavailable","production_action_executed":False,"requires_human_approval":True}
    grounded={"incident_id":str(row.get("incident_id")),"ci_name":str(row.get("ci_name")),"root_cause":authoritative,"confidence":"High" if proven_feedback(fb) else "Low","technical_cause_proven":bool(proven_feedback(fb)),"evidence_basis":"Human validation" if proven_feedback(fb) else "Current incident and exact-description history do not prove a technical root cause."}
    return {"incident":incident(row),"historical_incident_count":len(history),"similar_incidents":evidence["same_description_incidents"],"knowledge_sources":knowledge,"human_feedback":fb,"answer":authoritative,"ai_interpretation":llm,"evidence":evidence,"grounded_assessment":grounded,"model":OLLAMA_MODEL,"timing":{"ollama_seconds":round(elapsed,3)},"ai_status":"completed","production_action_executed":False,"requires_human_approval":True}

@app.post("/api/agents/proactive")
def proactive(req:ProactiveRequest):
    ci=req.ci_name.strip(); history=ci_filter(data(),ci)
    if history.empty:raise HTTPException(404,f"No incidents found for CI: {ci}")
    ev=proactive_evidence(history); row=recent(history,1).iloc[0]; knowledge=knowledge_for(row,1); allfb=feedback_load(); fbs=[x for x in allfb.values() if norm(x.get("ci_name"))==norm(ci)]
    prompt=proactive_prompt(ci,ev,knowledge,fbs)
    try: llm,elapsed=call_ollama(prompt,"proactive",AGENT3_PREDICT); status="completed"
    except HTTPException as exc: llm="AI recommendation unavailable; deterministic risk evidence is still valid."; elapsed=None; status="timeout" if exc.status_code==504 else "unavailable"
    risk=ev["recurring_descriptions"][0] if ev["recurring_descriptions"] else None
    grounded={"key_risk":f"Recurring incident pattern: {risk['description']} ({risk['count']} occurrences)." if risk else "No single recurring description is sufficiently dominant.","evidence_basis":ev,"technical_cause_proven":False}
    return {"ci_name":ci,"incident_count":len(history),"recent_incidents":clean_records(history,10),"knowledge_sources":knowledge,"human_feedback_count":len(fbs),"answer":llm,"grounded_assessment":grounded,"model":OLLAMA_MODEL,"timing":{"ollama_seconds":round(elapsed,3) if elapsed is not None else None},"ai_status":status,"production_action_executed":False,"requires_human_approval":True}

@app.get("/api/agents/feedback")
def feedback_history(incident_id:str=""):
    d=feedback_load(); return {"incident_id":incident_id,"items":[d[incident_id]] if incident_id and incident_id in d else ([] if incident_id else list(d.values()))}

@app.post("/api/agents/feedback")
def save_feedback(req:FeedbackRequest):
    row=by_id(data(),req.incident_id)
    if row is None:raise HTTPException(404,f"Incident not found: {req.incident_id}")
    f={"incident_id":req.incident_id,"ci_name":str(row.get("ci_name","Unknown")),"decision":req.decision.strip(),"corrected_root_cause":req.corrected_root_cause.strip(),"corrective_action":req.corrective_action.strip(),"preventive_action":req.preventive_action.strip(),"comments":req.comments.strip(),"reviewer":req.reviewer.strip() or "Human reviewer","recorded_at":time.strftime("%Y-%m-%dT%H:%M:%S"),"production_action_executed":False}
    d=feedback_load(); d[req.incident_id]=f; feedback_save(d); return {"status":"saved","feedback":f,"production_action_executed":False}

if __name__=="__main__":
 import uvicorn; uvicorn.run("api:app",host="0.0.0.0",port=8000,reload=False)
