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
    ensure_keys()
    state = build_llm_and_crew_once()

    if not state["ready"] or state["crew"] is None:
        raise HTTPException(status_code=500, detail=f"Crew not ready: {state['error']}")

    crew = state["crew"]
    raw_result = crew.kickoff({"topic": topic})

    # --- BEGIN: enrich result into desired report format ---
    # Extract summary (model-independent)
    # If the crew already provides a summary, keep it; otherwise generate a lightweight one.
    def extract_summary(r: Any) -> str:
        if isinstance(r, dict) and "summary" in r:
            return r["summary"]

        # Generate a lightweight bullet summary from task outputs
        bullets = []
        if isinstance(r, dict) and "tasks_output" in r:
            for item in r["tasks_output"]:
                if isinstance(item, dict) and "content" in item:
                    line = item["content"].strip().replace("\n", " ")
                    bullets.append(f"- {line[:200]}...")  # safe truncate
        return "\n".join(bullets[:7])  # 5–7 punkter

    # Extract tasks output as‑is
    def extract_tasks(r: Any):
        if isinstance(r, dict) and "tasks_output" in r:
            return r["tasks_output"]
        return [{"raw": r}]

    enriched = {
        "result": {
            "summary": extract_summary(raw_result),
            "tasks_output": extract_tasks(raw_result)
        }
    }


    runs_dir = os.path.join(BASE, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    outfile = os.path.join(runs_dir, "latest_output.json")
    try:
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except TypeError:
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(str(result))
    return result
