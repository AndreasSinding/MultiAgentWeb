
from pydantic import BaseModel, Field
from typing import List, Optional

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
    
class SummaryOutput(BaseModel):
    topic: Optional[str] = None
    bullets: List[str] = []
    final_summary: Optional[str] = None    


class LLM(BaseModel):
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    api_key: Optional[str] = None
    base_url: Optional[str] = "https://api.groq.com/openai/v1"
    temperature: float = 0.2

# ---- Registry the loader uses ----
SCHEMA_REGISTRY = {
    "AnalysisOutput": AnalysisOutput,
    "ResearchOutput": ResearchOutput,
    "SummaryOutput": SummaryOutput,
}