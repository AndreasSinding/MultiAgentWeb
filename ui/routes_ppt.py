# ui/routes_ppt.py

from fastapi import APIRouter, BackgroundTasks, HTTPException, Body
from fastapi.responses import FileResponse
import os, tempfile

from .ppt_builder import create_multislide_pptx, _safe_filename
from app.pipeline import run_crew_pipeline  # direkte kall – ikke HTTP

router = APIRouter(prefix="/reports", tags=["PowerPoint"])


@router.post(
    "/pptx",
    response_class=FileResponse,
    responses={
        200: {
            "description": "Generated PowerPoint file",
            "content": {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
async def generate_pptx(
    topic: str = Body(None, embed=True),
    result: dict = Body(None, embed=True),
    background_tasks: BackgroundTasks = None,
):
    """
    ONE endpoint that supports:
    - topic -> pipeline -> PPTX
    - result -> PPTX
    """

    # 1) If topic is provided → run pipeline directly (no HTTP)
    if topic:
        try:
            result_json = await run_crew_pipeline(topic)
        except Exception as e:
            raise HTTPException(500, f"Pipeline failed: {e}")
    # 2) If raw result is provided → use it directly
    elif result:
        result_json = result
    else:
        raise HTTPException(400, "Provide either 'topic' or 'result'.")

    # 3) Build PPT
    fd, tmp_path = tempfile.mkstemp(suffix=".pptx")
    os.close(fd)

    create_multislide_pptx(result_json, topic or "report", tmp_path)

    # 4) Cleanup
    if background_tasks:
        background_tasks.add_task(
            lambda p=tmp_path: os.path.exists(p) and os.remove(p)
        )

    filename = f"{_safe_filename(topic or 'report')}_report.pptx"

    return FileResponse(
        path=tmp_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )
