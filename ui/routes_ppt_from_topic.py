# ui/routes_ppt_from_topic.py
from fastapi import APIRouter, BackgroundTasks, Body, HTTPException
from fastapi.responses import FileResponse
import os, tempfile, requests
from .ppt_builder import create_multislide_pptx, _safe_filename

router = APIRouter(prefix="/reports", tags=["PowerPoint"])

RUN_ENDPOINT = os.getenv("RUN_ENDPOINT", "http://localhost:8787/run")

@router.post(
    "/pptx/from-topic",
    response_class=FileResponse,
    responses={
        200: {
            "description": "PPT generated from topic",
            "content": {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
async def pptx_from_topic(
    topic: str = Body(..., embed=True),
    background_tasks: BackgroundTasks = None,
):
    # 1) Call your CrewAI run endpoint
    try:
        r = requests.post(RUN_ENDPOINT, json={"topic": topic}, timeout=120)
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(500, f"Backend /run failed: {e}")

    result_json = r.json()

    # 2) Build PPT
    fd, tmp = tempfile.mkstemp(suffix=".pptx")
    os.close(fd)
    create_multislide_pptx(result_json, topic, tmp)

    # 3) Cleanup
    if background_tasks:
        background_tasks.add_task(lambda p=tmp: os.path.exists(p) and os.remove(p))

    return FileResponse(
        tmp,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"{_safe_filename(topic)}_report.pptx"
    )
