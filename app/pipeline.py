# app/pipeline.py
from __future__ import annotations
import os
import json
import threading
import importlib
import traceback
from typing import Any, Dict, List, Tuple
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

import json
from typing import Any, Dict, List, Tuple

def _safe_to_dict(obj: Any) -> Dict[str, Any]:
    """
    Best-effort conversion of a Pydantic/BaseModel-ish object to a plain dict.
    Tries .model_dump(), .dict(), .to_dict(), .json_dict(), and JSON parsing of .json()/.model_dump_json()
    Returns {} if nothing works.
    """
    if obj is None:
        return {}

    # Try common Pydantic / model APIs in a safe order
    for meth in ("model_dump", "dict", "to_dict"):
        if hasattr(obj, meth):
            try:
                d = getattr(obj, meth)()
                if isinstance(d, dict):
                    return d
            except Exception:
                pass

    # Some libs expose .json_dict or .model_dump_json
    for meth in ("json_dict",):
        if hasattr(obj, meth):
            try:
                d = getattr(obj, meth)
                # json_dict can be an attribute OR a method
                d = d() if callable(d) else d
                if isinstance(d, dict):
                    return d
            except Exception:
                pass

    for meth in ("model_dump_json", "json"):
        if hasattr(obj, meth):
            try:
                s = getattr(obj, meth)()
                if isinstance(s, str):
                    return json.loads(s)
            except Exception:
                pass

    # Last resort: try to JSON-load a 'raw' attribute if present
    if hasattr(obj, "raw"):
        raw = getattr(obj, "raw")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return {"summary": raw}

    # Give up
    try:
        return dict(obj)  # if it's already mapping-like
    except Exception:
        return {}

def _merge_into(agg: Dict[str, Any], piece: Dict[str, Any]) -> None:
    """
    Merge a piece of structured output into the aggregate 'agg' dict.
    Preserves lists (extends), strings (uses latest if longer), and nested sections.
    """
    if not isinstance(piece, dict):
        return

    # Single-string fields
    if "summary" in piece and isinstance(piece["summary"], str):
        # Prefer the longest summary we’ve seen so far
        prev = agg.get("summary", "")
        if len(piece["summary"]) > len(prev):
            agg["summary"] = piece["summary"]

    # Simple list sections
    for key in ("key_points", "insights", "opportunities", "risks", "sources"):
        val = piece.get(key)
        if isinstance(val, list):
            agg.setdefault(key, []).extend(v for v in val if isinstance(v, str) and v.strip())

    # Structured list sections
    for key in ("trends", "competitors", "numbers", "recommendations"):
        val = piece.get(key)
        if isinstance(val, list):
            agg.setdefault(key, [])
            for item in val:
                if isinstance(item, dict):
                    agg[key].append(item)

def normalize_crew_output(output: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Normalizes your CrewAI output (CrewOutput class) to a single plain dict.
    Also returns a list of per-task dicts (for tasks_output echo).
    """
    merged: Dict[str, Any] = {}
    task_dicts: List[Dict[str, Any]] = []

    # 1) Try top-level pydantic/final summary first
    if hasattr(output, "pydantic") and output.pydantic is not None:
        top = _safe_to_dict(output.pydantic)
        _merge_into(merged, top)

    # 2) Try top-level raw JSON string
    if hasattr(output, "raw") and isinstance(output.raw, str):
        try:
            top_raw = json.loads(output.raw)
            _merge_into(merged, top_raw)
        except Exception:
            # keep as-is; builder can still parse links from text later
            pass

    # 3) Merge each task’s structured payload
    if hasattr(output, "tasks_output") and isinstance(output.tasks_output, list):
        for t in output.tasks_output:
            td: Dict[str, Any] = {}
            if hasattr(t, "pydantic") and t.pydantic is not None:
                td = _safe_to_dict(t.pydantic)

            if not td and hasattr(t, "raw") and isinstance(t.raw, str):
                try:
                    td = json.loads(t.raw)
                except Exception:
                    td = {}

            if td:
                _merge_into(merged, td)
                task_dicts.append(td)

    # 4) Ensure at least a summary is present
    if "summary" not in merged or not str(merged["summary"]).strip():
        if hasattr(output, "raw") and isinstance(output.raw, str) and output.raw.strip():
            merged["summary"] = output.raw.strip()
        else:
            merged["summary"] = "- (no summary)"

    return merged, task_dicts
    
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

#-------------------------------------------------------------------
# Helper for normalizing into dict
#-------------------------------------------------------------------
def normalize_crew_output(output):
    """
    Takes a CrewOutput or a dict or a string and normalizes it into a dict.
    """
    # Case 1: Already a dict
    if isinstance(output, dict):
        return output

    # Case 2: CrewOutput-like object (has attributes)
    if hasattr(output, "pydantic_output"):
        pod = output.pydantic_output
        if isinstance(pod, dict):
            return pod

    if hasattr(output, "raw_output"):
        # Try to parse the raw_output as JSON
        raw = output.raw_output
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                # fallback to wrapping string
                return {"summary": raw}

    # Case 3: String fallback
    if isinstance(output, str):
        try:
            return json.loads(output)
        except Exception:
            return {"summary": output}

    # Last resort
    return {"summary": str(output)}
    
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

    # -------------------------------------------------
    # 1) Run crew and normalize output safely
    # -------------------------------------------------
    raw_output = crew.kickoff({"topic": topic})
    
    print("DEBUG CREW OUTPUT DIR:", dir(raw_output))
    print("DEBUG CREW OUTPUT:", raw_output)
    print("DEBUG CREW OUTPUT __dict__:", getattr(raw_output, "__dict__", None))

    result = normalize_crew_output(raw_output)

    # -------------------------------------------------
    # 2) Ensure summary exists
    # -------------------------------------------------
    if not isinstance(result, dict):
        result = {"summary": str(result)}

    if "summary" not in result or not result["summary"]:
        # Use LLM summary fallback
        if llm:
            try:
                prompt = (
                    "Summarize the following content from a multi-agent pipeline "
                    "in 5–7 bullet points. Avoid headings.\n\n"
                    f"TEXT:\n{json.dumps(result, ensure_ascii=False)}\n"
                )
                summary_text = llm(prompt)
                if isinstance(summary_text, str) and summary_text.strip():
                    result["summary"] = summary_text.strip()
            except Exception:
                pass

        # Final fallback summary
        if "summary" not in result or not result["summary"]:
            try:
                raw = json.dumps(result, ensure_ascii=False)
                lines = [
                    f"- {ln.strip()[:200]}"
                    for ln in raw.splitlines()
                    if ln.strip()
                ]
                result["summary"] = "\n".join(lines[:7]) or "- (no summary)"
            except Exception:
                result["summary"] = "- (no summary)"

    # -------------------------------------------------
    # 3) Final enriched structure for /run and PPT builder
    # -------------------------------------------------
    enriched = {
        "topic": topic,
        "result": result,
        "tasks_output": [
            {"content": json.dumps(result, ensure_ascii=False)}
        ]
    }

    # -------------------------------------------------
    # 4) Persist to /latest
    # -------------------------------------------------
    runs_dir = os.path.join(BASE, "runs")
    os.makedirs(runs_dir, exist_ok=True)

    outfile = os.path.join(runs_dir, "latest_output.json")
    tmpfile = outfile + ".tmp"

    with open(tmpfile, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    os.replace(tmpfile, outfile)

    return enriched
