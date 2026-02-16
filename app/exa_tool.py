# app/exa_tool.py
from __future__ import annotations

import os
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

# --- CrewAI BaseTool: support both layouts (older/newer releases) ---
try:
    from crewai.tools import BaseTool  # e.g., CrewAI 1.8.x+
except Exception:
    from crewai_tools import BaseTool  # fallback for older setups

from pydantic import BaseModel, Field, PrivateAttr

# --- Optional Exa SDK import (guarded) ---
try:
    # pip install exa-py
    from exa_py import Exa  # correct import per Exa SDK
except Exception:  # ImportError or env issues
    Exa = None  # We'll check this at runtime

DEFAULT_RESULTS = 5     # default number of links to request from Exa
RETURN_LIMIT = 5        # cap how many items we emit to the agent
MAX_TOTAL_SEARCHES = 3  # budget safeguard


class ExaSearchAndContentsInput(BaseModel):
    """Input schema for queries to the tool."""
    query: str = Field(..., description="Natural-language search query")
    results: int = Field(DEFAULT_RESULTS, ge=1, le=50, description="Number of results to request")
    included_domains: Optional[List[str]] = None
    excluded_domains: Optional[List[str]] = None
    recency_days: Optional[int] = Field(None, ge=1, le=365, description="Only pages published within N days")


class ExaSearchAndContents(BaseTool):
    """
    CrewAI tool that runs Exa search and returns structured items with content.
    Uses exa-py client. If the SDK or API key is missing, returns a JSON error
    instead of raising, to avoid 500s in multi-agent flows.
    """

    name: str = "exasearchandcontents"
    description: str = (
        "Search the web via Exa and retrieve page contents (full text or summary). "
        "Returns a compact JSON array of items with title, url, published_date, and content."
    )

    # Exposed defaults (CrewAI can show them in tool schema)
    results: int = Field(default=DEFAULT_RESULTS, ge=1, le=50)

    # Private state
    _exa: Optional[Exa] = PrivateAttr(default=None)
    _search_calls: int = PrivateAttr(default=0)

    # CrewAI will validate inputs using this schema
    args_schema = ExaSearchAndContentsInput

    def __init__(self, results: int = DEFAULT_RESULTS, **kwargs: Any):
        super().__init__(results=max(1, min(50, int(results))), **kwargs)

    # -------------------- internal helpers --------------------
    def _guard_budget(self) -> None:
        if self._search_calls >= MAX_TOTAL_SEARCHES:
            raise RuntimeError(f"Search budget exceeded (max {MAX_TOTAL_SEARCHES}).")
        self._search_calls += 1

    @staticmethod
    def _iso_date_from_recency(days: Optional[int]) -> Optional[str]:
        if not days:
            return None
        dt = datetime.utcnow() - timedelta(days=int(days))
        return dt.date().isoformat()  # 'YYYY-MM-DD'

    @staticmethod
    def _contents_options() -> Dict[str, Any]:
        # Use text extraction with a sane cap. Switch to {"summary": True} if you prefer.
        return {"text": {"max_characters": 10000}}

    @staticmethod
    def _pack_result(r) -> Dict[str, Any]:
        # Exa SDK result fields: title, url, published_date, text/summary/highlights
        title = getattr(r, "title", "") or ""
        url = getattr(r, "url", "") or ""
        published = getattr(r, "published_date", None)
        text = getattr(r, "text", "") or ""
        summary = getattr(r, "summary", "") or ""
        highlights = getattr(r, "highlights", None)

        if text:
            content = text
        elif summary:
            content = summary
        elif highlights:
            content = "\n".join(highlights) if isinstance(highlights, list) else str(highlights)
        else:
            content = ""

        return {
            "title": title,
            "url": url,
            "published_date": published,
            "content": content[:10000],  # keep compact for the agent
        }

    def _ensure_client(self) -> Exa:
        # Defer heavy/optional checks until actually used
        if Exa is None:
            raise RuntimeError(
                "exa-py is not installed. Install with `pip install exa-py` "
                "and ensure it is included in your runtime/requirements."
            )
        if self._exa is None:
            api_key = os.getenv("EXA_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("Missing EXA_API_KEY environment variable.")
            self._exa = Exa(api_key=api_key)
        return self._exa

    # -------------------- CrewAI sync execution path --------------------
    def _run(
        self,
        query: str,
        results: Optional[int] = None,
        included_domains: Optional[List[str]] = None,
        excluded_domains: Optional[List[str]] = None,
        recency_days: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute search and return a JSON string: {"items": [...]} or {"error": "..."}.
        """
        try:
            self._guard_budget()
        except Exception as e:
            return json.dumps({"error": f"budget-guard: {e}"})

        if not query or not isinstance(query, str):
            return json.dumps({"items": [], "note": "empty or invalid 'query'"})

        # Effective knobs
        num_results = max(1, min(50, int(results if results is not None else self.results)))
        start_published_date = self._iso_date_from_recency(recency_days)

        # Build search kwargs for Exa
        search_kwargs: Dict[str, Any] = {
            "num_results": int(num_results),
            "contents": self._contents_options(),  # include text by default
        }
        if included_domains:
            search_kwargs["include_domains"] = included_domains
        if excluded_domains:
            search_kwargs["exclude_domains"] = excluded_domains
        if start_published_date:
            search_kwargs["start_published_date"] = start_published_date

        try:
            exa = self._ensure_client()
            response = exa.search(query, **search_kwargs)
            items: List[Dict[str, Any]] = []
            for r in getattr(response, "results", [])[:RETURN_LIMIT]:
                items.append(self._pack_result(r))
            return json.dumps({"items": items})
        except Exception as e:
            # Surface a structured error string rather than raising
            return json.dumps({"error": f"exa.search failed: {type(e).__name__}: {e}"})

    # -------------------- CrewAI async path --------------------
    async def _arun(self, **kwargs: Any) -> str:
        # Call the sync path for simplicity; adapt to an async SDK if available
        return self._run(**kwargs)
    
