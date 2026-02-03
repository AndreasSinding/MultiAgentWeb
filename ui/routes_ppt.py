# ui/routes_ppt.py
from fastapi import APIRouter, Body
from fastapi.responses import FileResponse
from typing import Any, Dict
import os, tempfile, json

from .app import create_multislide_pptx   # <- relative import from ui/app.py

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

    tmpdir = tempfile.gettempdir()
    file_path = os.path.join(tmpdir, f"{topic.replace(' ', '_')}_report.pptx")

    create_multislide_pptx(result=result, topic=topic, file_name=file_path)

    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=os.path.basename(file_path),
    )
