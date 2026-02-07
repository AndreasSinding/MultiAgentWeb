# ui/routes_ppt.py
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Any
import os
import time
import tempfile
import json

# Import your pipeline and the PPT builder
# - run_crew_pipeline must return a dict that contains {"result": {"tasks_output": [...]}}
# - create_multislide_pptx(topic, file_path) generates the PPT
from app.pipeline import run_crew_pipeline
from ppt_builder import create_multislide_pptx  # <-- adjust if your module name differs

router = APIRouter(prefix="/reports", tags=["Reports"])

class RunRequest(BaseModel):
    topic: str

def _safe_filename(base: str) -> str:
    import re
    if not base:
        return "report"
    return re.sub(r'[^A-Za-z0-9._-]+', '_', base).strip('_') or "report"

# --- 1) One-shot: run crew now -> build PPTX -> return file
@router.post("/pptx")
def create_pptx_from_run(req: RunRequest):
    """
    Runs the crew for the provided topic and returns a generated PPTX file.
    """
    try:
        result: Dict[str, Any] = run_crew_pipeline(req.topic)
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
def create_pptx_from_latest(topic: str = Query(..., description="Title shown on the Title slide")):
    """
    Reads runs/latest_output.json (written by your pipeline) and returns a PPTX file.
    """
    try:
        # Resolve project root (ui/ -> project)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        latest_path = os.path.join(project_root, "runs", "latest_output.json")
        if not os.path.exists(latest_path):
            raise HTTPException(status_code=404, detail="No previous run stored (runs/latest_output.json missing).")

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
