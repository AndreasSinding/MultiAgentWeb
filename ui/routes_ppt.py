# ui/routes_ppt.py
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import os
import uuid
import tempfile

from app.pipeline import run_crew_pipeline  # synchronous
from ui.ppt_builder import create_multislide_pptx, _safe_filename

router = APIRouter(prefix="/reports", tags=["PowerPoint"])


class PPTRequest(BaseModel):
    """
    Provide EITHER:
      - topic: str                 -> pipeline will run and generate 'result'
      - result: dict (enriched)    -> use existing pipeline output directly
    """
    topic: Optional[str] = Field(
        default=None,
        description="Topic to feed into the pipeline (preferred)."
    )
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Already computed pipeline result (fallback/advanced)."
    )


@router.post(
    "/pptx",
    summary="Generate a PowerPoint (.pptx) from a topic or an existing pipeline result",
    response_class=FileResponse,
    responses={
        200: {
            "description": "Generated PowerPoint file",
            "content": {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        },
        400: {"description": "Bad Request"},
        500: {"description": "Internal Server Error"},
    },
)
async def generate_pptx(req: PPTRequest, background_tasks: BackgroundTasks):
    """
    Primary flow:
      1) If 'topic' is provided:
           - run the pipeline synchronously to get an enriched result
           - build the PPT from that result
      2) Else if 'result' is provided:
           - use it directly to build the PPT

    Returns the PPTX file as a binary response.
    """

    # 1) Determine source of 'enriched_result'
    if req.topic:
        try:
            # NOTE: run_crew_pipeline is synchronous — DO NOT 'await' here
            enriched_result = run_crew_pipeline(req.topic)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Pipeline failed: {type(e).__name__}: {e}",
            )
    elif req.result:
        enriched_result = req.result
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'topic' or 'result' in the request body."
        )

    # 2) Build PPT to a temporary file
    try:
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
            tmp_path = tmp.name

        # Your builder should write the PPTX to 'tmp_path'
        # Signature: create_multislide_pptx(result_json: dict, topic: str, outfile: str)
        create_multislide_pptx(
            enriched_result,
            req.topic or "report",
            tmp_path
        )

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise RuntimeError("PPT builder produced no file or an empty file.")
    except Exception as e:
        # Clean up if something failed during build
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"PPT building failed: {type(e).__name__}: {e}",
        )

    # 3) Return the file and schedule deletion
    safe_base = _safe_filename(req.topic or "report")
    filename = f"{safe_base}_{uuid.uuid4().hex[:8]}.pptx"

    # Schedule deletion after response is sent
    background_tasks.add_task(os.remove, tmp_path)

    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

