# ui/schemas.py
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

class PptxRequest(BaseModel):
    topic: str = Field(..., example="Outlook for AI market in Nordic region 2026")
    # This is whatever your /run returns; we keep it open but give an example
    result: Dict[str, Any] = Field(
        ...,
        example={
            "result": {
                "raw": "Executive summary goes here...",
                "tasks_output": [
                    {
                        "raw": "{\"trends\":[{\"title\":\"Edge AI\",\"evidence\":\"IDC 2025\",\"why_it_matters\":\"Latency reduction\"}],"
                               "\"competitors\":[],\"numbers\":[],\"sources\":[\"https://example.com\"]}"
                    },
                    {
                        "raw": "{\"recommendations\":[{\"priority\":1,\"action\":\"Invest in MLOps\",\"rationale\":\"Faster time-to-market\"}]}"
                    }
                ]
            }
        },
    )
