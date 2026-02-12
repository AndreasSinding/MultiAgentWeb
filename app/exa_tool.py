from __future__ import annotations
import os
import json
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from crewai_tools import BaseTool  # correct import
# Note: we do not import `exa` at module top to keep import-time light

DEFAULT_RESULTS = 5
DEFAULT_PAGES = 5
MAX_TOTAL_SEARCHES = 3

class ExaSearchAndContentsInput(BaseModel):
    """Input schema for queries to the tool."""
    query: str = Field(..., description="Natural‑language search query")
    results: int = Field(DEFAULT_RESULTS, ge=1, le=25)
    pages: int = Field(DEFAULT_PAGES, ge=1, le=25)
    included_domains: Optional[List[str]] = None
    excluded_domains: Optional[List[str]] = None
    recency_days: Optional[int] = None

class ExaSearchAndContents(BaseTool):
    """
    CrewAI tool for performing Exa search + content extraction.
    Enforces a strict search‑budget per agent run.

    Lazy‑loading: We defer importing/initializing the Exa SDK until `_run`.
    """
    name: str = "exasearchandcontents"
    description: str = (
        "Performs targeted Exa web searches and retrieves page contents. "
        "Budget‑limited and returns structured JSON."
    )
    args_schema = ExaSearchAndContentsInput

    def __init__(
        self,
        results: int = DEFAULT_RESULTS,
        pages: int = DEFAULT_PAGES,
        **kwargs,
    ):
        super().__init__(**kwargs)
        # Store config only; no SDK/init work at construction time
        self.results = max(1, min(25, int(results)))
        self.pages = max(1, min(25, int(pages)))
        self._search_calls = 0

    def _guard_budget(self):
        if self._search_calls >= MAX_TOTAL_SEARCHES:
            raise RuntimeError(f"Search budget exceeded (max {MAX_TOTAL_SEARCHES}).")
        self._search_calls += 1

    def _ensure_exa_ready(self):
        """
        Import Exa and set API key right before first call.
        Keeps import/construct time side‑effect‑free.
        """
        import exa  # local import to avoid module‑level side effects
        api_key = os.getenv("EXA_API_KEY", "")
        if not api_key:
            raise RuntimeError("Missing EXA_API_KEY environment variable.")
        exa.api_key = api_key
        return exa

    def _run(
        self,
        query: str,
        results: Optional[int] = None,
        pages: Optional[int] = None,
        included_domains: Optional[List[str]] = None,
        excluded_domains: Optional[List[str]] = None,
        recency_days: Optional[int] = None,
    ) -> str:
        """
        Executes the Exa search and returns JSON‑encoded results.
        """
        self._guard_budget()

        # Lazy-load and configure Exa
        exa = self._ensure_exa_ready()

        # Effective parameters
        r = int(results) if results is not None else self.results
        p = int(pages) if pages is not None else self.pages

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
            return json.dumps({
                "items": [],
                "note": f"exa.search_and_contents failed: {e}"
            })

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
                "content": content[:5000],  # safety truncation
            })
        return json.dumps({"items": items})
