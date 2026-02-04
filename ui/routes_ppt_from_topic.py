# ui/routes_ppt_from_topic.py
from fastapi import APIRouter, BackgroundTasks, Body, HTTPException
from fastapi.responses import FileResponse
import os, tempfile, requests

from .ppt_builder import create_multislide_pptx, _safe_filename

router = APIRouter(prefix="/reports", tags=["PowerPoint"])

# Configure this via env in real code
RUN_ENDPOINT = os.getenv("RUN_ENDPOINT", "http://127.0.0.1:8787/run")

@router.post(
    "/pptx/from-topic",
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
async def pptx_from_topic(
    background_tasks: BackgroundTasks,
    topic: str = Body(..., embed=True, example="Outlook for AI market in Nordic region 2026"),
):
    # 1) Call your existing /run endpoint to get JSON
    try:
        r = requests.post(RUN_ENDPOINT, json={"topic": topic}, timeout=120)
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Backend /run failed: {e}")

    result = r.json()  # must match what ppt_builder expects

    # 2) Build PPTX into a temp file
    fd, tmp_path = tempfile.mkstemp(suffix=".pptx")
    os.close(fd)
    create_multislide_pptx(result=result, topic=topic, file_name=tmp_path)

    # 3) Clean up after response
    background_tasks.add_task(lambda p=tmp_path: os.path.exists(p) and os.remove(p))

    filename = f"{_safe_filename(topic)}_report.pptx"
    return FileResponse(
        path=tmp_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )
