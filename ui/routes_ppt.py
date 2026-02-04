# ui/routes_ppt.py
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import FileResponse
import os, tempfile

from .ppt_builder import create_multislide_pptx, _safe_filename
from .schemas import PptxRequest

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
async def generate_pptx(req: PptxRequest, background_tasks: BackgroundTasks):
    # Create a temp file (safe on App Service)
    fd, tmp_path = tempfile.mkstemp(suffix=".pptx")
    os.close(fd)

    create_multislide_pptx(result=req.result, topic=req.topic, file_name=tmp_path)

    # Delete temp file after response is sent
    background_tasks.add_task(lambda p=tmp_path: os.path.exists(p) and os.remove(p))

    filename = f"{_safe_filename(req.topic)}_report.pptx"
    return FileResponse(
        path=tmp_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )
