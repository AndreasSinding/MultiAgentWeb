# ui/routes_ppt.py
from fastapi import APIRouter, BackgroundTasks, HTTPException, Body
from fastapi.responses import FileResponse
import tempfile, uuid, os

from app.pipeline import run_crew_pipeline
from ui.ppt_builder import create_multislide_pptx, _safe_filename

router = APIRouter(prefix="/reports", tags=["PowerPoint"])

@router.post("/pptx", response_class=FileResponse)
async def generate_pptx(
    topic: str = Body(..., embed=True),
    background_tasks: BackgroundTasks = None
):
    """
    FINAL VERSION:
    - Only accepts 'topic'
    - Always runs the pipeline
    - Never accepts a 'result' field
    - Swagger UI can no longer insert invalid fields
    """

    # 1) Run the pipeline
    try:
        enriched = run_crew_pipeline(topic)
    except Exception as e:
        raise HTTPException(500, f"Pipeline failed: {type(e).__name__}: {e}")

    # 2) Create PPT file
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        create_multislide_pptx({"result": enriched}, topic, tmp_path)
    except Exception as e:
        raise HTTPException(500, f"PPT generation failed: {type(e).__name__}: {e}")

    # 3) Return file and schedule cleanup
    filename = f"{_safe_filename(topic)}_{uuid.uuid4().hex[:8]}.pptx"
    background_tasks.add_task(os.remove, tmp_path)

    return FileResponse(
        tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
