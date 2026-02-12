print("LOADING app.models.py...")

from pydantic import BaseModel, Field
from typing import List

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
    trends: List[Trend]
    competitors: List[Competitor]
    numbers: List[NumberItem] = Field(default_factory=list)
    sources: List[str]

class Recommendation(BaseModel):
    priority: int  # 1–5
    action: str
    rationale: str

class AnalysisOutput(BaseModel):
    insights: List[str]
    opportunities: List[str]
    risks: List[str]
    recommendations: List[Recommendation]

class LLM(BaseModel):
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    api_key: Optional[str] = None
    base_url: Optional[str] = "https://api.groq.com/openai/v1"
    temperature: float = 0.2

import requests

class LLM(BaseModel):
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    api_key: Optional[str] = None
    base_url: Optional[str] = "https://api.groq.com/openai/v1"
    temperature: float = 0.2

    def __call__(self, prompt: str) -> str:
        """
        Minimal Groq/OpenAI call wrapper.
        NO memory, NO embeddings, NO Chroma.
        Matches old branch behavior.
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
