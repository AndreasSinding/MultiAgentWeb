# app/exa_tool.py
from __future__ import annotations
import os
import json
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, PrivateAttr
# IMPORTANT: import the BaseTool from the same framework as your Agent (CrewAI)
from crewai.tools import BaseTool  # CrewAI 1.8.x

DEFAULT_RESULTS = 5
DEFAULT_PAGES = 5
MAX_TOTAL_SEARCHES = 3


class ExaSearchAndContentsInput(BaseModel):
    """Input schema for queries to the tool."""
    query: str = Field(..., description="Natural-language search query")
    results: int = Field(DEFAULT_RESULTS, ge=1, le=25)
    pages: int = Field(DEFAULT_PAGES, ge=1, le=25)
    included_domains: Optional[List[str]] = None
    excluded_domains: Optional[List[str]] = None
    recency_days: Optional[int] = None


class ExaSearchAndContents(BaseTool):
    """
    Tool for performing Exa search + content extraction with a simple budget.
    The Exa SDK is lazy-loaded on first call.
    """
    name: str = "exa_search_and_contents"
    description: str = (
        "Searches the web via Exa and retrieves page contents/snippets. "
        "Returns structured JSON with a capped number of items."
    )

    # IMPORTANT: declare fields so Pydantic knows about them
    results: int = Field(default=DEFAULT_RESULTS, ge=1, le=25)
    pages: int = Field(default=DEFAULT_PAGES, ge=1, le=25)

    # Private (non-serializable) internal counter
    _search_calls: int = PrivateAttr(default=0)

    # CrewAI/LangChain will use this to validate inputs
    args_schema = ExaSearchAndContentsInput

    def __init__(self, results: int = DEFAULT_RESULTS, pages: int = DEFAULT_PAGES, **kwargs: Any):
        # Normalize & clamp, then pass to Pydantic's initializer
        r = max(1, min(25, int(results)))
        p = max(1, min(25, int(pages)))
        super().__init__(results=r, pages=p, **kwargs)

    # --- internal helpers ---
    def _guard_budget(self) -> None:
        if self._search_calls >= MAX_TOTAL_SEARCHES:
            raise RuntimeError(f"Search budget exceeded (max {MAX_TOTAL_SEARCHES}).")
        self._search_calls += 1

    def _ensure_exa_ready(self):
        """Import Exa and set API key at call time."""
        import exa  # local import
        api_key = os.getenv("EXA_API_KEY", "")
        if not api_key:
            raise RuntimeError("Missing EXA_API_KEY environment variable.")
        exa.api_key = api_key
        return exa

    # --- sync execution path required by BaseTool ---
    def _run(
        self,
        query: str,
        results: Optional[int] = None,
        pages: Optional[int] = None,
        included_domains: Optional[List[str]] = None,
        excluded_domains: Optional[List[str]] = None,
        recency_days: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Execute search and return a JSON string with items."""
        self._guard_budget()
        exa = self._ensure_exa_ready()

        if not query or not isinstance(query, str):
            return json.dumps({"items": [], "note": "empty or invalid 'query'"})

        # Effective parameters (override defaults if provided)
        r = max(1, min(25, int(results if results is not None else self.results)))
        p = max(1, min(25, int(pages if pages is not None else self.pages)))

        opts: Dict[str, Any] = {"num_results": int(r)}
        if included_domains:
            opts["include_domains"] = included_domains
        if excluded_domains:
            opts["exclude_domains"] = excluded_domains
        if recency_days:
            opts["start_published_date"] = f"now-{int(recency_days)}d"

        # Perform search
        try:
            response = exa.search_and_contents(query, **opts)
        except Exception as e:
            return json.dumps({"items": [], "note": f"exa.search_and_contents failed: {e}"})

        items = []
        for item in getattr(response, "results", [])[:p]:
            title = getattr(item, "title", "") or ""
            url = getattr(item, "url", "") or ""
            snippet = (getattr(item, "highlight", "") or getattr(item, "description", "") or "")
            content = (getattr(item, "text", "") or getattr(item, "content", "") or "")
            published = getattr(item, "published_date", None)
            items.append(
                {
                    "title": title,
                    "url": url,
                    "published_date": published,
                    "snippet": snippet,
                    "content": content[:5000],
                }
            )

        return json.dumps({"items": items})

    async def _arun(self, **kwargs: Any) -> str:  # optional async path
        return self._run(**kwargs)
