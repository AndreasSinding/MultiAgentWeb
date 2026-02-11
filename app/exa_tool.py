from __future__ import annotations
import os
import json
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field
from crewai_tools import BaseTool  # corrected module name
import exa  # Exa official python SDK


# Default limits (safe/cost‑controlled)
DEFAULT_RESULTS = 5     # max results per search
DEFAULT_PAGES = 5       # max documents to fetch content for
MAX_TOTAL_SEARCHES = 3  # strict safety budget


# -----------------------------
# Pydantic input schema
# -----------------------------
class ExaSearchAndContentsInput(BaseModel):
    query: str = Field(..., description="Natural‑language query")
    results: int = Field(DEFAULT_RESULTS, ge=1, le=25)
    pages: int = Field(DEFAULT_PAGES, ge=1, le=25)
    included_domains: Optional[List[str]] = None
    excluded_domains: Optional[List[str]] = None
    recency_days: Optional[int] = None


# -----------------------------
# Tool Implementation
# -----------------------------
class ExaSearchAndContents(BaseTool):
    """
    CrewAI tool: lightweight Exa search+contents fetcher
    Returns compact JSON: title, url, snippet, content.
    """

    name: str = "exasearchandcontents"
    description: str = (
        "Performs a web search using Exa and fetches page contents. "
        "Respects strict per‑task usage limits. Returns JSON with items[]."
    )

    args_schema = ExaSearchAndContentsInput

    def __init__(
        self,
        results: int = DEFAULT_RESULTS,
        pages: int = DEFAULT_PAGES,
        **kwargs,
    ):
        super().__init__(**kwargs)

        # API key
        exa.api_key = os.getenv("EXA_API_KEY", "")
        if not exa.api_key:
            raise RuntimeError("Missing EXA_API_KEY environment variable")

        # Safety limits
        self.results = max(1, min(25, results))
        self.pages = max(1, min(25, pages))
        self._search_calls = 0

    # -------------------------------------
    # Budget guard
    # -------------------------------------
    def _guard_budget(self):
        if self._search_calls >= MAX_TOTAL_SEARCHES:
            raise RuntimeError(
                f"Search budget exceeded (max {MAX_TOTAL_SEARCHES})."
            )
        self._search_calls += 1

    # -------------------------------------
    # Main execution handler
    # -------------------------------------
    def _run(
        self,
        query: str,
        results: Optional[int] = None,
        pages: Optional[int] = None,
        included_domains: Optional[List[str]] = None,
        excluded_domains: Optional[List[str]] = None,
        recency_days: Optional[int] = None,
    ) -> str:

        self._guard_budget()

        # prefer input overrides
        r = results or self.results
        p = pages or self.pages

        opts: Dict[str, Any] = {"num_results": int(r)}

        if included_domains:
            opts["include_domains"] = included_domains
        if excluded_domains:
            opts["exclude_domains"] = excluded_domains
        if recency_days:
            opts["start_published_date"] = f"now-{int(recency_days)}d"

        # Run the search
        try:
            response = exa.search_and_contents(query, **opts)
        except Exception as e:
            return json.dumps({
                "items": [],
                "note": f"exa.search_and_contents failed: {e}"
            })

        # Normalize items
        items = []
        for item in getattr(response, "results", [])[:p]:
            title = getattr(item, "title", "") or ""
            url = getattr(item, "url", "") or ""
            snippet = (
                getattr(item, "highlight", "")
                or getattr(item, "description", "")
                or ""
            )
            content = (
                getattr(item, "text", "")
                or getattr(item, "content", "")
                or ""
            )
            published = getattr(item, "published_date", None)

            items.append({
                "title": title,
                "url": url,
                "published_date": published,
                "snippet": snippet,
                "content": content[:5000],  # truncate for safety
            })

        return json.dumps({"items": items})

