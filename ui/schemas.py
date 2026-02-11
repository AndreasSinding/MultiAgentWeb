# ui/schemas.py
from typing import Any, Dict
from pydantic import BaseModel, Field

class PptxRequest(BaseModel):
    topic: str = Field(..., example="Outlook for AI market in Nordic region 2026")
    # This mirrors what your /run returns; keep it open but give a helpful example.
    result: Dict[str, Any] = Field(
        ...,
        example={
            "result": {
                "raw": "Executive summary – key growth pockets in edge AI and responsible AI in the Nordics.",
                "tasks_output": [
                    {
                        "raw": "{\"trends\":[{\"title\":\"Edge AI\",\"evidence\":\"IDC 2025\",\"why_it_matters\":\"Latency & privacy\"}],"
                               "\"competitors\":[{\"name\":\"Contoso AI\",\"position\":\"Nordic scale-up\",\"notes\":\"Strong in MLOps\"}],"
                               "\"numbers\":[{\"metric\":\"Nordic AI market CAGR\",\"value\":\"18%\",\"source\":\"IDC 2025\"}],"
                               "\"sources\":[\"https://example.com/idc-2025\"]}"
                    },
                    {
                        "raw": "{\"recommendations\":["
                               "{\"priority\":1,\"action\":\"Invest in MLOps\",\"rationale\":\"Reduce time-to-production\"},"
                               "{\"priority\":2,\"action\":\"Launch Responsible AI framework\",\"rationale\":\"Prepare for EU AI Act\"}"
                               "]}"
                    }
                ]
            }
        },
    )
