# ui/routes_ppt.py
# -*- coding: utf-8 -*-
"""
PPT routes for FastAPI.

- StreamingResponse for binary download (no response_model).
- Threadpool offload for python-pptx + file I/O.
- Filenames are sanitized; temp files are cleaned up.
"""

from __future__ import annotations
import io
import json
import os
import re
import tempfile
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

router = APIRouter(prefix="/ppt", tags=["ppt"])

# ----------------------------- Models -----------------------------
class BuildPptRequest(BaseModel):
    """Payload expected from your multi-agent pipeline output."""
    topic: str = Field(..., min_length=1, max_length=300, description="Report topic/title")
    result: Dict[str, Any] = Field(..., description="Crew/pipeline result (JSON dict)")
    filename: Optional[str] = Field(
        None,
        description="Optional base file name without extension; defaults to sanitized topic",
        max_length=120,
    )

    # Optional guard to prevent accidental huge payloads (adjust as needed)
    @property
    def approx_size_bytes(self) -> int:
        try:
            return len(json.dumps(self.result)) + len(self.topic)
        except Exception:
            return 0

# ----------------------------- Helpers -----------------------------
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9.\_-]+")

def _safe_filename(name: Optional[str]) -> str:
    base = (name or "report").strip().strip("._")
    base = _SAFE_NAME_RE.sub("_", base) or "report"
    return base[:120]  # OS/zip-safe

def _build_ppt_to_bytes(topic: str, result: Dict[str, Any], desired_name: Optional[str]) -> bytes:
    """
    Work function executed in a threadpool:
    - lazy-imports python-pptx and your builder
    - writes to a temp file, returns its bytes, and cleans up
    """
    # Lazy import to avoid heavy deps at import-time
    from ui.ppt_builder import create_multislide_pptx

    tmpdir = tempfile.mkdtemp(prefix="pptx_")
    try:
        # Compose a temp filename
        stamp = int(time.time())
        base = _safe_filename(desired_name or topic or "report")
        out_path = os.path.join(tmpdir, f"{base}_{stamp}.pptx")

        # Build and read
        create_multislide_pptx(result=result, topic=topic, file_path=out_path)
        with open(out_path, "rb") as f:
            data = f.read()
        return data
    finally:
        # Best-effort cleanup
        try:
            for name in os.listdir(tmpdir):
                try:
                    os.remove(os.path.join(tmpdir, name))
                except Exception:
                    pass
            os.rmdir(tmpdir)
        except Exception:
            pass

# ----------------------------- Routes -----------------------------
@router.get("/ping", summary="Lightweight PPT router health")
def ping() -> Dict[str, str]:
    return {"ok": "ppt-router-alive"}

@router.get(
    "/from-latest",
    response_class=StreamingResponse,
    summary="Build a PPTX automatically from the latest saved run",
    description="Loads /runs/latest_output.json and generates a PPTX without requiring a POST body."
)
async def ppt_from_latest():
    import os
    import json
    from starlette.responses import StreamingResponse
    from starlette.concurrency import run_in_threadpool

    # Path to latest_output.json
    base = os.path.dirname(os.path.dirname(__file__))  # adjust if needed
    latest_path = os.path.join(base, "runs/latest_output.json")

    # Ensure file exists
    if not os.path.exists(latest_path):
        raise HTTPException(status_code=404, detail="No latest_output.json found")

    # Load the latest output
    with open(latest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    topic = data.get("topic", "Untitled Report")
    result = data.get("result", {})

    # Build the PPT using the same internal code as /ppt/build
    blob: bytes = await run_in_threadpool(
        _build_ppt_to_bytes, topic, result, topic
    )

    download_name = _safe_filename(topic) + ".pptx"

    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "Cache-Control": "no-store",
        },
    )

@router.post(
    "/build",
    response_class=StreamingResponse,
    summary="Build a PPTX from a multi-agent result",
    description=(
        "Creates a multi-slide PPTX using the server-side builder. "
        "Returns a binary stream with the correct PPTX content type and a safe download filename."
    ),
)
async def build_ppt(req: BuildPptRequest):
    # Optional payload size guard
    if req.approx_size_bytes and req.approx_size_bytes > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Payload too large for PPT build")

    # CPU/file-bound work off the event loop
    try:
        blob: bytes = await run_in_threadpool(_build_ppt_to_bytes, req.topic, req.result, req.filename)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PPT build failed: {e}")

    # Compose a user-facing filename
    download_name = _safe_filename(req.filename or req.topic) + ".pptx"
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "Cache-Control": "no-store",
        },
    )
