# app/pipeline.py
import os, json, threading, inspect
from typing import Dict, Any, Optional
from fastapi import HTTPException

BASE = os.path.dirname(os.path.dirname(__file__))  # adjust if needed

TOOLS_DIR      = os.getenv("TOOLS_DIR", "crew/tools")
AGENTS_DIR     = os.getenv("AGENTS_DIR", "crew/agents")
TASKS_DIR      = os.getenv("TASKS_DIR", "crew/tasks")
CREW_YAML_PATH = os.getenv("CREW_YAML_PATH", "crew/crews/market_insights.yaml")
LLM_YAML_PATH  = os.getenv("LLM_YAML_PATH", "config/llm.yaml")

CREW_STATE: Dict[str, Any] = {"ready": False, "error": None, "crew": None, "llm": None}

def build_llm_and_crew_once() -> Dict[str, Any]:
    if CREW_STATE["ready"] and CREW_STATE["crew"] is not None:
        return CREW_STATE
    try:
        from app.loader import load_llm, load_tools, load_agents, load_tasks, load_crew
        llm    = load_llm(LLM_YAML_PATH)
        tools  = load_tools(TOOLS_DIR)
        agents = load_agents(AGENTS_DIR, llm, tools)
        tasks  = load_tasks(TASKS_DIR, agents)
        crew   = load_crew(CREW_YAML_PATH, agents, tasks)
        CREW_STATE.update({"llm": llm, "crew": crew, "ready": True, "error": None})
    except Exception as e:
        CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
        print("Crew init failed:", e)
    return CREW_STATE

def warm_async():
    def _warm():
        try:
            build_llm_and_crew_once()
        except Exception as e:
            CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
    threading.Thread(target=_warm, daemon=True).start()

def ensure_keys():
    required = ["GROQ_API_KEY"]  # add OPENAI_API_KEY, etc.
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing environment variables: {', '.join(missing)}")

def run_crew_pipeline(topic: str) -> dict:
    import json, os
    ensure_keys()
    state = build_llm_and_crew_once()

    if not state["ready"] or state["crew"] is None:
        raise HTTPException(status_code=500, detail=f"Crew not ready: {state['error']}")

    crew = state["crew"]

    # ---- 1) Run CrewAI ----
    raw_result = crew.kickoff({"topic": topic})

    # CrewAI usually returns a single long string
    if not isinstance(raw_result, str):
        raw_text = str(raw_result)
    else:
        raw_text = raw_result.strip()

    # ---- 2) Split text into blocks for tasks_output ----
    paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]
    tasks_output = [{"content": p} for p in paragraphs]

    # ---- 3) Create summary via LLM ----
    llm = state.get("llm")
    if llm:
        prompt = (
            "Summarize the following text (from a multi-agent research pipeline) in exactly 5–7 bullets.\n"
            "Avoid headings. Only bullet points.\n\n"
            f"TEXT:\n{raw_text}\n"
        )
        try:
            summary = llm(prompt)
            summary = summary if isinstance(summary, str) else str(summary)
        except Exception:
            summary = None
    else:
        summary = None

    # Fallback if LLM summary fails
    if not summary or not summary.strip():
        summary = "\n".join([f"- {p[:200]}" for p in paragraphs[:7]])

    enriched = {
        "summary": summary.strip(),
        "tasks_output": tasks_output
    }

    # ---- 4) Save to disk for /latest ----
    runs_dir = os.path.join(BASE, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    outfile = os.path.join(runs_dir, "latest_output.json")
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    return enriched
