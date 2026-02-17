# app/models.py
from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field


# -------------------------------
# Task output models (Pydantic v2)
# -------------------------------
class Trend(BaseModel):
    title: str
    evidence: str
    why_it_matters: str


class Competitor(BaseModel):
    name: str
    position: str
    notes: str


class NumberItem(BaseModel):
    metric: str
    value: str
    source: str


class ResearchOutput(BaseModel):
    """
    Used by tasks that set: output_schema: ResearchOutput
    """
    trends: List[Trend]
    competitors: List[Competitor]
    numbers: List[NumberItem] = Field(default_factory=list)
    sources: List[str]


class Recommendation(BaseModel):
    priority: int  # 1–5
    action: str
    rationale: str


class AnalysisOutput(BaseModel):
    """
    If any task uses: output_schema: AnalysisOutput
    """
    insights: List[str]
    opportunities: List[str]
    risks: List[str]
    recommendations: List[Recommendation]


# -------------------------------
# Minimal LLM wrapper (kept same API)
# -------------------------------
import requests


class LLM(BaseModel):
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    api_key: Optional[str] = None
    base_url: Optional[str] = "https://api.groq.com/openai/v1"
    temperature: float = 0.2

    def __call__(self, prompt: str) -> str:
        """
        Minimal Groq/OpenAI Chat Completions wrapper.
        No memory/embeddings; mirrors previous behavior.
        """
        if not self.api_key:
            raise RuntimeError("Missing GROQ_API_KEY")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

print("LOADING app.models.py...")
# -------------------------------
# Registry for loader._schema_from_name()
# -------------------------------
SCHEMA_REGISTRY = {
    "ResearchOutput": ResearchOutput,
    "AnalysisOutput": AnalysisOutput,  # keep available; some tasks referenced it earlier
}
