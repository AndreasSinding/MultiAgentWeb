# ui/routes_ppt.py
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import os
import uuid
import tempfile

from app.pipeline import run_crew_pipeline
from ui.ppt_builder import create_multislide_pptx, _safe_filename

router = APIRouter(prefix="/reports", tags=["PowerPoint"])


class PPTRequest(BaseModel):
    topic: Optional[str] = Field(None, description="Topic to analyze")
    result: Optional[Dict[str, Any]] = Field(None, description="Raw result (advanced use). Leave empty for normal usage.")


@router.post("/pptx", response_class=FileResponse)
async def generate_pptx(req: PPTRequest, background_tasks: BackgroundTasks):

    # 🔥 FIX: If topic is provided, ALWAYS run pipeline. Ignore result.
    if req.topic:
        try:
            enriched = run_crew_pipeline(req.topic)
        except Exception as e:
            raise HTTPException(500, f"Pipeline failed: {e}")

    # If no topic but user supplied a result manually
    elif req.result:
        enriched = req.result

    else:
        raise HTTPException(400, "You must provide either topic or result.")

    # Create a temporary file
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        create_multislide_pptx(enriched, req.topic or "report", tmp_path)
    except Exception as e:
        raise HTTPException(500, f"PPT generation failed: {e}")

    filename = f"{_safe_filename(req.topic or 'report')}_{uuid.uuid4().hex[:8]}.pptx"

    # Cleanup after response
    background_tasks.add_task(os.remove, tmp_path)

    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

