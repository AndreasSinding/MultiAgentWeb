# ui/routes_ppt.py
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import tempfile
import os
import uuid

from app.pipeline import run_crew_pipeline
from ui.ppt_builder import create_multislide_pptx, _safe_filename

router = APIRouter(prefix="/reports", tags=["PowerPoint"])

class PPTRequest(BaseModel):
    topic: str


@router.post("/pptx", response_class=FileResponse)
async def generate_pptx(req: PPTRequest, background_tasks: BackgroundTasks):
    """
    Simplified endpoint:
    - ALWAYS runs the pipeline using req.topic
    - ALWAYS generates PPT from pipeline summary + tasks_output
    - NO 'result' input anymore
    """

    # 1) Run pipeline (guarantees enriched summary + tasks_output)
    try:
        enriched = run_crew_pipeline(req.topic)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline failed: {type(e).__name__}: {e}"
        )

    # 2) Create temporary PPTX file
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        create_multislide_pptx(
            enriched,
            req.topic,
            tmp_path
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PPT generation failed: {type(e).__name__}: {e}"
        )

    # 3) Prepare file for download
    filename = f"{_safe_filename(req.topic)}_{uuid.uuid4().hex[:8]}.pptx"

    background_tasks.add_task(os.remove, tmp_path)

    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
