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

