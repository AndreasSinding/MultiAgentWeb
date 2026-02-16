# app/exa_tool.py
from __future__ import annotations
import os
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple

from pydantic import BaseModel, Field, PrivateAttr
from crewai.tools import BaseTool  # CrewAI 1.8.x+

# Exa SDK (Python). Docs: https://exa.ai/docs/sdks/python-sdk
# pip install exa-py
from exa_py import Exa  # ← correct import per SDK

DEFAULT_RESULTS = 5    # default number of links to request from Exa
RETURN_LIMIT    = 5    # cap how many items we emit to the agent
MAX_TOTAL_SEARCHES = 3 # budget safeguard


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
    Uses exa-py (client methods), not deprecated top-level calls.
    """
    # Keep the name aligned with your crew/task prompts
    name: str = "exasearchandcontents"
    description: str = (
        "Search the web via Exa and retrieve page contents (full text or summary). "
        "Returns a compact JSON array of items with title, url, published_date, and content."
    )

    # Exposed defaults (CrewAI can show them in tool schema)
    results: int = Field(default=DEFAULT_RESULTS, ge=1, le=50)

    # Private budget counter
    _search_calls: int = PrivateAttr(default=0)

    # CrewAI will validate inputs using this schema
    args_schema = ExaSearchAndContentsInput

    # Lazily initialized Exa client
    _exa: Optional[Exa] = PrivateAttr(default=None)

    def __init__(self, results: int = DEFAULT_RESULTS, **kwargs: Any):
        super().__init__(results=max(1, min(50, int(results))), **kwargs)

    # -------------------- internal helpers --------------------

    def _guard_budget(self) -> None:
        if self._search_calls >= MAX_TOTAL_SEARCHES:
            raise RuntimeError(f"Search budget exceeded (max {MAX_TOTAL_SEARCHES}).")
        self._search_calls += 1

    def _ensure_client(self) -> Exa:
        """
        Create (or reuse) an Exa client. The SDK will read EXA_API_KEY from env
        or you can pass it explicitly.
        """
        if self._exa is None:
            api_key = os.getenv("EXA_API_KEY", "").strip()
            if not api_key:
                # Exa() also reads EXA_API_KEY from env; we just warn early.
                raise RuntimeError("Missing EXA_API_KEY environment variable.")
            self._exa = Exa(api_key=api_key)  # per SDK usage
        return self._exa

    @staticmethod
    def _iso_date_from_recency(days: Optional[int]) -> Optional[str]:
        if not days:
            return None
        dt = datetime.utcnow() - timedelta(days=int(days))
        return dt.date().isoformat()  # 'YYYY-MM-DD' per SDK spec

    @staticmethod
    def _contents_options() -> Dict[str, Any]:
        """
        Contents config: text extraction with a sane cap. You can switch to summary
        by returning {"summary": True} or mix both:
        {"text": {"max_characters": 12000}, "summary": True}
        """
        return {"text": {"max_characters": 10000}}

    @staticmethod
    def _pack_result(r) -> Dict[str, Any]:
        # Exa SDK result fields: title, url, published_date, text/summary/highlights depending on 'contents'
        title = getattr(r, "title", "") or ""
        url = getattr(r, "url", "") or ""
        published = getattr(r, "published_date", None)
        text = getattr(r, "text", "") or ""
        summary = getattr(r, "summary", "") or ""
        highlights = getattr(r, "highlights", None)

        # Prefer text, then summary, then highlights (joined)
        if text:
            content = text
        elif summary:
            content = summary
        elif highlights:
            # highlights may be list[str] or structured; stringify defensively
            content = "\n".join(highlights) if isinstance(highlights, list) else str(highlights)
        else:
            content = ""

        return {
            "title": title,
            "url": url,
            "published_date": published,
            "content": content[:10000],  # keep things compact for the agent
        }

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
        Execute search and return a JSON string with {"items": [...]}.
        """
        self._guard_budget()
        exa = self._ensure_client()

        if not query or not isinstance(query, str):
            return json.dumps({"items": [], "note": "empty or invalid 'query'"})

        # Effective knobs
        num_results = max(1, min(50, int(results if results is not None else self.results)))
        start_published_date = self._iso_date_from_recency(recency_days)

        # Build search kwargs per Exa SDK
        search_kwargs: Dict[str, Any] = {
            "num_results": int(num_results),
            # contents included by default, but we pass explicit options for clarity
            "contents": self._contents_options(),  # returns text unless you change it
        }
        if included_domains:
            search_kwargs["include_domains"] = included_domains
        if excluded_domains:
            search_kwargs["exclude_domains"] = excluded_domains
        if start_published_date:
            search_kwargs["start_published_date"] = start_published_date

        try:
            # Correct call per SDK: exa.search(...) returns results with contents
            # Docs: https://exa.ai/docs/sdks/python-sdk ; Spec: https://exa.ai/docs/sdks/python-sdk-specification
            response = exa.search(query, **search_kwargs)
        except Exception as e:
            return json.dumps({"items": [], "note": f"exa.search failed: {e}"})

        # Compact items for the agent
        items: List[Dict[str, Any]] = []
        for r in getattr(response, "results", [])[:RETURN_LIMIT]:
            items.append(self._pack_result(r))

        return json.dumps({"items": items})

    async def _arun(self, **kwargs: Any) -> str:
        # CrewAI synchronous path is typically used, but this keeps API parity.
        return self._run(**kwargs)
