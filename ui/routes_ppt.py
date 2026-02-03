# ui/routes_ppt.py
from fastapi import APIRouter, Body
from fastapi.responses import FileResponse
from typing import Any, Dict
import os, tempfile

from .ppt_builder import create_multislide_pptx

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
async def generate_pptx(payload: Dict[str, Any] = Body(...)):
    result = payload.get("result", {})
    topic = payload.get("topic", "MultiAgent Report")

    # write to temp (safe on App Service)
    fd, tmp_path = tempfile.mkstemp(suffix=".pptx")
    os.close(fd)

    create_multislide_pptx(result=result, topic=topic, file_name=tmp_path)

    return FileResponse(
        path=tmp_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"{topic.replace(' ', '_')}_report.pptx",
    )
