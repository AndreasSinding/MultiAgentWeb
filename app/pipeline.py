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

    # 1) Run CrewAI
    raw_result = crew.kickoff({"topic": topic})
    raw_text = raw_result if isinstance(raw_result, str) else str(raw_result)
    raw_text = raw_text.strip()

    # 2) Keep whole content (do NOT split), so JSON blocks stay intact
    tasks_output = [{"content": raw_text}]

    # 3) Summary via LLM (unchanged)
    llm = state.get("llm")
    summary = None
    if llm:
        prompt = (
            "Summarize the following text (from a multi-agent research pipeline) "
            "in exactly 5–7 bullets.\nAvoid headings. Only bullet points.\n\n"
            f"TEXT:\n{raw_text}\n"
        )
        try:
            summary = llm(prompt)
            summary = summary if isinstance(summary, str) else str(summary)
        except Exception:
            summary = None

    # 4) Fallback summary if LLM fails
    if not summary or not summary.strip():
        first_lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        summary = "\n".join([f"- {ln[:200]}" for ln in first_lines[:7]]) or "- (no summary)"

    # ---------- NEW: JSON repair/expand step ----------
    def _looks_structured_json(s: str) -> bool:
        try:
            obj = json.loads(s)
            return isinstance(obj, dict) and any(
                k in obj for k in (
                    "trends", "insights", "opportunities", "risks",
                    "competitors", "numbers", "recommendations", "sources"
                )
            )
        except Exception:
            return False

    # If current content isn't a full structured JSON, try to repair/expand
    need_repair = True
    try:
        if _looks_structured_json(raw_text):
            need_repair = False
    except Exception:
        need_repair = True

    if need_repair and llm:
        repair_prompt = (
            "You are a strict JSON formatter. Convert the following research text into ONE valid JSON object "
            "with this exact schema (all keys required; use [] for empty lists):\n"
            "{\n"
            '  "summary": "string",\n'
            '  "trends": ["string", ...],\n'
            '  "insights": ["string", ...],\n'
            '  "opportunities": ["string", ...],\n'
            '  "risks": ["string", ...],\n'
            '  "competitors": [ {"name": "string", "position": "string", "notes": "string"} ],\n'
            '  "numbers": [ {"metric": "string", "value": "string", "source": "string"} ],\n'
            '  "recommendations": [ {"priority": 1, "action": "string", "rationale": "string"} ],\n'
            '  "sources": ["string", ...]\n'
            "}\n\n"
            "Rules:\n"
            "- Output ONLY valid JSON. No markdown, no comments, no code fences.\n"
            "- Fill what you can from the text. If information is missing, use empty arrays.\n\n"
            f"RAW TEXT:\n{raw_text}\n"
        )
        try:
            repaired = llm(repair_prompt)
            fixed = repaired.strip()
            if fixed.startswith("```"):
                fixed = fixed.strip("`").strip()
                if fixed.lower().startswith("json"):
                    fixed = fixed[4:].strip()
            # Validate JSON
            json.loads(fixed)
            tasks_output = [{"content": fixed}]
        except Exception:
            # Keep original content if repair fails
            pass
    # ---------- end JSON repair ----------

    enriched = {
        "summary": summary.strip(),
        "tasks_output": tasks_output
    }

    # 5) Persist for /latest
    runs_dir = os.path.join(BASE, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    outfile = os.path.join(runs_dir, "latest_output.json")
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    return enriched
