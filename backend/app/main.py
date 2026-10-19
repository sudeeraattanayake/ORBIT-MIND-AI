"""ORBIT-MIND AI — simulated mission control. No real spacecraft control."""
import json
import math
import os
import random
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END

load_dotenv()
DB = Path(__file__).resolve().parent.parent / "missions.sqlite3"
app = FastAPI(title="ORBIT-MIND AI", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","), allow_methods=["GET", "POST"], allow_headers=["*"])


def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

with connect() as c:
    c.execute("CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, created_at TEXT, telemetry TEXT, result TEXT)")


class Telemetry(BaseModel):
    satellite: str = "OM-1"
    battery: float = Field(ge=0, le=100)
    temperature: float = Field(ge=-200, le=250)
    fuel: float = Field(ge=0, le=100)
    signal: float = Field(ge=0, le=100)
    altitude: float = Field(ge=100, le=100000)


class AnalysisState(TypedDict, total=False):
    telemetry: dict
    anomalies: list[dict]
    actions: list[str]
    safety: dict
    summary: str


def detect(state: AnalysisState):
    t = state["telemetry"]
    issues = []
    limits = {"battery": (20, None), "temperature": (-20, 65), "fuel": (15, None), "signal": (30, None), "altitude": (250, 2000)}
    for key, (low, high) in limits.items():
        value = t[key]
        if (low is not None and value < low) or (high is not None and value > high):
            issues.append({"sensor": key, "value": value, "severity": "critical" if key in ("battery", "temperature", "altitude") else "warning"})
    return {"anomalies": issues}


def plan(state: AnalysisState):
    advice = {
        "battery": "Reduce nonessential payload load and evaluate power budget.",
        "temperature": "Review thermal telemetry and investigate heater/radiator configuration.",
        "fuel": "Suspend discretionary maneuvers and assess remaining propellant.",
        "signal": "Check antenna orientation and schedule a communication window.",
        "altitude": "Request orbital dynamics review; do not command a burn automatically.",
    }
    return {"actions": [advice[i["sensor"]] for i in state["anomalies"]] or ["Continue monitoring nominal simulated telemetry."]}


def validate(state: AnalysisState):
    return {"safety": {"approved_for_real_spacecraft": False, "requires_human_review": True, "mode": "SIMULATION_ONLY", "note": "All recommendations are advisory; no commands are sent."}}


def summarize(state: AnalysisState):
    n = len(state["anomalies"])
    summary = f"Detected {n} threshold anomaly{'ies' if n != 1 else ''} in simulated telemetry." if n else "All monitored simulated telemetry values are within demonstration thresholds."
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=12)
            response = client.chat.completions.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), messages=[{"role": "system", "content": "You are a space mission simulation analyst. Explain provided deterministic findings concisely. Never claim access to a real spacecraft. Never invent measurements or recommend executing commands without human review."}, {"role": "user", "content": json.dumps({"telemetry": state["telemetry"], "anomalies": state["anomalies"], "recommendations": state["actions"]})}], max_tokens=180)
            summary = response.choices[0].message.content or summary
        except Exception:
            pass
    return {"summary": summary}


graph = StateGraph(AnalysisState)
for name, fn in [("anomaly_detection", detect), ("mission_planner", plan), ("safety_gate", validate), ("briefing", summarize)]:
    graph.add_node(name, fn)
graph.set_entry_point("anomaly_detection")
graph.add_edge("anomaly_detection", "mission_planner")
graph.add_edge("mission_planner", "safety_gate")
graph.add_edge("safety_gate", "briefing")
graph.add_edge("briefing", END)
workflow = graph.compile()


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "SIMULATION_ONLY"}


@app.get("/api/telemetry", response_model=Telemetry)
def telemetry():
    t = time.time()
    return Telemetry(battery=round(79 + 9 * math.sin(t / 23), 1), temperature=round(22 + 11 * math.sin(t / 17), 1), fuel=round(67 + 3 * math.sin(t / 47), 1), signal=round(85 + 9 * math.sin(t / 13), 1), altitude=round(550 + 4 * math.sin(t / 61), 1))


@app.post("/api/analyze")
def analyze(data: Telemetry):
    result = workflow.invoke({"telemetry": data.model_dump()})
    ident = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with connect() as c:
        c.execute("INSERT INTO analyses VALUES (?, ?, ?, ?)", (ident, now, data.model_dump_json(), json.dumps(result)))
    return {"id": ident, "created_at": now, **result}


@app.get("/api/history")
def history():
    with connect() as c:
        rows = c.execute("SELECT id, created_at, result FROM analyses ORDER BY created_at DESC LIMIT 20").fetchall()
    return [{"id": r["id"], "created_at": r["created_at"], "summary": json.loads(r["result"]).get("summary", "")} for r in rows]

from .research import router as research_router
app.include_router(research_router)

from .classification import router as classification_router
app.include_router(classification_router)

from .space_objects import router as space_router
app.include_router(space_router)
