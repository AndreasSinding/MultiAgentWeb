# app/pipeline.py
from __future__ import annotations
import os
import json
import threading
import importlib
import traceback
from typing import Dict, Any
from fastapi import HTTPException

# Root dir
BASE = os.path.dirname(os.path.dirname(__file__))

# Paths (from env or defaults)
TOOLS_DIR = os.getenv("TOOLS_DIR", "crew/tools")
AGENTS_DIR = os.getenv("AGENTS_DIR", "crew/agents")
TASKS_DIR = os.getenv("TASKS_DIR", "crew/tasks")
CREW_YAML_PATH = os.getenv("CREW_YAML_PATH", "crew/crews/market_insights.yaml")
LLM_YAML_PATH = os.getenv("LLM_YAML_PATH", "config/llm.yaml")

# Shared state
CREW_STATE: Dict[str, Any] = {"ready": False, "error": None, "crew": None, "llm": None}


# ---------------------------------------------------------------------
# BUILD CREW (one-time)
# ---------------------------------------------------------------------
def build_llm_and_crew_once() -> Dict[str, Any]:
    if CREW_STATE["ready"] and CREW_STATE["crew"] is not None:
        return CREW_STATE

    try:
        loader = importlib.import_module("app.loader")

        required = ("load_llm", "load_tools", "load_agents", "load_tasks", "load_crew")
        missing = [name for name in required if not hasattr(loader, name)]
        if missing:
            CREW_STATE.update(
                {"ready": False, "error": f"Missing in app.loader: {', '.join(missing)}"}
            )
            return CREW_STATE

        llm = loader.load_llm(LLM_YAML_PATH)
        tools = loader.load_tools(TOOLS_DIR)
        agents = loader.load_agents(AGENTS_DIR, llm, tools)
        tasks = loader.load_tasks(TASKS_DIR, agents)
        crew = loader.load_crew(CREW_YAML_PATH, agents, tasks)

        CREW_STATE.update({"llm": llm, "crew": crew, "ready": True, "error": None})

    except Exception as e:
                
        tb = traceback.format_exc()
        CREW_STATE.update(
            {"ready": False, "error": f"{type(e).__name__}: {e}\nTRACE:\n{tb}"}
        )


    return CREW_STATE


# ---------------------------------------------------------------------
# BACKGROUND WARMUP
# ---------------------------------------------------------------------
def warm_async():
    def _warm():
        try:
            build_llm_and_crew_once()
        except Exception as e:
            CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})

    threading.Thread(target=_warm, daemon=True).start()


# ---------------------------------------------------------------------
# ENV CHECK
# ---------------------------------------------------------------------
def ensure_keys():
    required = ["GROQ_API_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing environment variables: {', '.join(missing)}",
        )


# ---------------------------------------------------------------------
# PIPELINE EXECUTION
# ---------------------------------------------------------------------
def run_crew_pipeline(topic: str) -> Dict[str, Any]:
    ensure_keys()
    state = build_llm_and_crew_once()

    if not state["ready"] or state.get("crew") is None:
        raise HTTPException(
            status_code=500,
            detail=f"Crew not ready: {state['error']}"
        )

    crew = state["crew"]
    llm = state.get("llm")

    # -----------------------------------------------------
    # 1) Run the crew and KEEP STRUCTURE
    # -----------------------------------------------------
    result = crew.kickoff({"topic": topic})

    # If the crew returned a string, wrap it
    if isinstance(result, str):
        result = {"summary": result}

    # -----------------------------------------------------
    # 2) Add a best-effort summary IF the agents did not provide one
    # -----------------------------------------------------
    summary = result.get("summary")
    if not summary and llm:
        try:
            prompt = (
                "Summarize the following content from a multi-agent pipeline "
                "in 5–7 bullet points.\nAvoid headings.\n\n"
                f"TEXT:\n{json.dumps(result, ensure_ascii=False)}\n"
            )
            summary_text = llm(prompt)
            if isinstance(summary_text, str) and summary_text.strip():
                result["summary"] = summary_text.strip()
        except Exception:
            pass

    # Fallback if summary still missing
    if "summary" not in result or not str(result["summary"]).strip():
        try:
            raw = json.dumps(result, ensure_ascii=False)
            first_lines = [
                f"- {ln.strip()[:200]}"
                for ln in raw.splitlines()
                if ln.strip()
            ]
            result["summary"] = "\n".join(first_lines[:7]) or "- (no summary)"
        except Exception:
            result["summary"] = "- (no summary)"

    # -----------------------------------------------------
    # 3) This is the FINAL structure used by PPT builder
    # -----------------------------------------------------
    enriched = {
        "topic": topic,
        "result": result,
        "tasks_output": [
            {"content": json.dumps(result, ensure_ascii=False)}
        ]
    }

    # -----------------------------------------------------
    # 4) Persist output
    # -----------------------------------------------------
    runs_dir = os.path.join(BASE, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    outfile = os.path.join(runs_dir, "latest_output.json")
    tmpfile = outfile + ".tmp"

    with open(tmpfile, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    os.replace(tmpfile, outfile)

    return enriched
