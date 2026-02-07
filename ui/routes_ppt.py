# ui/routes_ppt.py
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Any
import os
import time
import tempfile
import json

import inspect, logging, ui.ppt_builder as _ppt_b
logging.warning("PPT builder loaded from: %s", inspect.getsourcefile(_ppt_b))

# Import your pipeline and builder
from app.pipeline import run_crew_pipeline
from ui.ppt_builder import create_multislide_pptx   # adjust module name if different

router = APIRouter(prefix="/reports", tags=["Reports"])

class RunRequest(BaseModel):
    topic: str

def _safe_filename(base: str) -> str:
    import re
    if not base:
        return "report"
    return re.sub(r'[^A-Za-z0-9._-]+', '_', base).strip('_') or "report"

# --- 1) One-shot: run crew now -> build PPTX -> return file
@router.get("/diag/from-latest")
def diag_from_latest():
    import json, inspect
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    latest_path = os.path.join(project_root, "runs", "latest_output.json")
    if not os.path.exists(latest_path):
        raise HTTPException(status_code=404, detail="No runs/latest_output.json")
    with open(latest_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    # extract
    from ui.ppt_builder import _extract_all_json_blocks  # type: ignore
    data = result.get("result", {}) or result
    sections = _extract_all_json_blocks(data.get("tasks_output", []), also_consider=[
        data.get("summary"), data.get("final_output"), data.get("raw"), data.get("content"), data.get("text")
    ])

    # show counts and one sample
    preview = {k: (len(v) if isinstance(v, list) else (len(v) if isinstance(v, str) else 0)) for k, v in sections.items()}
    return {
        "builder_loaded": inspect.getsourcefile(_extract_all_json_blocks),
        "section_counts": preview,
        "sample": {
            "summary": sections["summary"][:200] if isinstance(sections["summary"], str) else "",
            "trends_0": sections["trends"][0] if sections["trends"] else "",
            "insights_0": sections["insights"][0] if sections["insights"] else "",
            "opportunities_0": sections["opportunities"][0] if sections["opportunities"] else "",
            "risks_0": sections["risks"][0] if sections["risks"] else "",
            "competitors_0": sections["competitors"][0] if sections["competitors"] else "",
            "numbers_0": sections["numbers"][0] if sections["numbers"] else "",
            "recommendations_0": sections["recommendations"][0] if sections["recommendations"] else "",
            "sources_0": sections["sources"][0] if sections["sources"] else "",
        }
    }
    
@router.post("/pptx")
def create_pptx_from_run(req: RunRequest):
    try:
        # Kick off your crew
        result: Dict[str, Any] = run_crew_pipeline(req.topic)   # must return {"result": {...}}
        # Build PPT into a temp file
        safe = _safe_filename(req.topic)
        ts = time.strftime("%Y%m%d-%H%M%S")
        tmp_dir = tempfile.mkdtemp(prefix="ppt_")
        out_path = os.path.join(tmp_dir, f"{safe}_{ts}.pptx")

        create_multislide_pptx(result, req.topic, out_path)
        return FileResponse(
            out_path,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=os.path.basename(out_path),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create PPTX: {e}")

# --- 2) Convenience: reuse the "latest" stored JSON -> build PPTX
@router.get("/pptx/from-latest")
def create_pptx_from_latest(topic: str = Query(..., description="Title/topic shown on the Title slide")):
    """
    Reads runs/latest_output.json (written by your pipeline) and builds a PPTX.
    """
    try:
        base_dir = os.path.dirname(__file__)
        project_root = os.path.abspath(os.path.join(base_dir, ".."))  # adjust if needed
        latest_path = os.path.join(project_root, "runs", "latest_output.json")
        if not os.path.exists(latest_path):
            raise HTTPException(status_code=404, detail="No previous run stored (runs/latest_output.json missing).")

        import json
        with open(latest_path, "r", encoding="utf-8") as f:
            result = json.load(f)

        safe = _safe_filename(topic)
        ts = time.strftime("%Y%m%d-%H%M%S")
        tmp_dir = tempfile.mkdtemp(prefix="ppt_")
        out_path = os.path.join(tmp_dir, f"{safe}_{ts}.pptx")

        create_multislide_pptx(result, topic, out_path)
        return FileResponse(
            out_path,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=os.path.basename(out_path),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create PPTX from latest: {e}")
