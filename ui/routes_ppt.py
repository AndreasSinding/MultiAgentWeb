# ui/routes_ppt.py
# -*- coding: utf-8 -*-
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

# ----- Model -----
class BuildPptRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=300)
    result: Dict[str, Any] = Field(...)
    filename: Optional[str] = Field(None, max_length=120)

    @property
    def approx_size_bytes(self) -> int:
        try:
            return len(json.dumps(self.result)) + len(self.topic)
        except Exception:
            return 0

# ----- Helpers -----
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

def _safe_filename(name: Optional[str]) -> str:
    base = (name or "report").strip().strip("._")
    base = _SAFE_NAME_RE.sub("_", base) or "report"
    return base[:120]

def _build_ppt_to_bytes(topic: str, result: Dict[str, Any], desired_name: Optional[str]) -> bytes:
    from ui.ppt_builder import create_multislide_pptx
    tmpdir = tempfile.mkdtemp(prefix="pptx_")
    try:
        stamp = int(time.time())
        base = _safe_filename(desired_name or topic or "report")
        out_path = os.path.join(tmpdir, f"{base}_{stamp}.pptx")
        create_multislide_pptx(result=result, topic=topic, file_path=out_path)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        try:
            for n in os.listdir(tmpdir):
                try:
                    os.remove(os.path.join(tmpdir, n))
                except Exception:
                    pass
            os.rmdir(tmpdir)
        except Exception:
            pass

# ----- Visible route -----
@router.get(
    "/from-latest",
    response_class=StreamingResponse,
    summary="Build a PPTX automatically from the latest saved run",
    description="Loads /runs/latest_output.json (written by /run) and generates a PPTX."
)
async def ppt_from_latest():
    import os, json

    # The PPT router lives under <APP_ROOT>/ui, while /run writes to <APP_ROOT>/runs.
    # So we must go one directory up (parent of ui) to reach the same BASE as main.py.
    app_root = os.path.dirname(os.path.dirname(__file__))   # <APP_ROOT>
    latest_path = os.path.join(app_root, "runs", "latest_output.json")

    # (Optional) helpful logging in App Service Log Stream:
    print("[/ppt/from-latest] app_root:", app_root)
    print("[/ppt/from-latest] latest_path:", latest_path, "exists:", os.path.exists(latest_path))

    if not os.path.exists(latest_path):
        raise HTTPException(status_code=404, detail="No latest_output.json found")

    with open(latest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    topic  = data.get("topic", "Untitled Report")
    result = data.get("result", {})

    blob: bytes = await run_in_threadpool(_build_ppt_to_bytes, topic, result, topic)
    download_name = _safe_filename(topic) + ".pptx"

    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "Cache-Control": "no-store",
        },
    )

# ----- Hidden/internal routes -----
@router.get("/ping", include_in_schema=False)
def ping() -> Dict[str, str]:
    return {"ok": "ppt-router-alive"}

@router.post("/build", include_in_schema=False, response_class=StreamingResponse)
async def build_ppt(req: BuildPptRequest):
    if req.approx_size_bytes and req.approx_size_bytes > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Payload too large for PPT build")
    try:
        blob = await run_in_threadpool(_build_ppt_to_bytes, req.topic, req.result, req.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PPT build failed: {e}")
    download_name = _safe_filename(req.filename or req.topic) + ".pptx"
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "Cache-Control": "no-store",
        },
    )
