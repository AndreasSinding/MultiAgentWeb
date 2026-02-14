# app/exa_tool.py
from __future__ import annotations
import os
import json
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field

# --- Import the correct BaseTool from the agent framework ---
# Prefer CrewAI; fall back to LangChain if CrewAI isn't installed.
try:
    from crewai.tools import BaseTool  # CrewAI
    _FRAMEWORK = "crewai"
except Exception:  # pragma: no cover
    try:
        # Newer LangChain splits BaseTool under langchain_core
        from langchain_core.tools import BaseTool  # type: ignore
        _FRAMEWORK = "langchain_core"
    except Exception:  # pragma: no cover
        from langchain.tools import BaseTool  # Legacy LC import
        _FRAMEWORK = "langchain"

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
    args_schema = ExaSearchAndContentsInput

    # Construction-time config (kept light)
    def __init__(
        self,
        results: int = DEFAULT_RESULTS,
        pages: int = DEFAULT_PAGES,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.results = max(1, min(25, int(results)))
        self.pages = max(1, min(25, int(pages)))
        self._search_calls = 0

    # --- internal helpers ---
    def _guard_budget(self) -> None:
        if self._search_calls >= MAX_TOTAL_SEARCHES:
            raise RuntimeError(f"Search budget exceeded (max {MAX_TOTAL_SEARCHES}).")
        self._search_calls += 1

    def _ensure_exa_ready(self):
        """
        Import Exa and set API key at call time to avoid module-level side effects.
        """
        import exa  # local import
        api_key = os.getenv("EXA_API_KEY", "")
        if not api_key:
            raise RuntimeError("Missing EXA_API_KEY environment variable.")
        exa.api_key = api_key
        return exa

    # --- sync execution path required by BaseTool ---
    def _run(self, **kwargs: Any) -> str:
        """
        Execute search and return a JSON string with items.
        Accepts kwargs to be compatible across frameworks.
        """
        self._guard_budget()
        exa = self._ensure_exa_ready()

        # Normalize/merge defaults with provided args
        query: str = kwargs.get("query") or ""
        if not query or not isinstance(query, str):
            return json.dumps({"items": [], "note": "empty or invalid 'query'"})

        results = kwargs.get("results", self.results)
        pages = kwargs.get("pages", self.pages)
        included_domains = kwargs.get("included_domains")
        excluded_domains = kwargs.get("excluded_domains")
        recency_days = kwargs.get("recency_days")

        # Effective parameters
        r = max(1, min(25, int(results)))
        p = max(1, min(25, int(pages)))

        opts: Dict[str, Any] = {"num_results": int(r)}
        if included_domains:
            opts["include_domains"] = included_domains
        if excluded_domains:
            opts["exclude_domains"] = excluded_domains
        if recency_days:
            # Exa accepts ISO/relative; adjust if your SDK expects a different field
            opts["start_published_date"] = f"now-{int(recency_days)}d"

        # Perform search
        try:
            response = exa.search_and_contents(query, **opts)
        except Exception as e:
            return json.dumps({"items": [], "note": f"exa.search_and_contents failed: {e}"})

        items = []
        # Cap number of returned items to 'pages'
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

            items.append(
                {
                    "title": title,
                    "url": url,
                    "published_date": published,
                    "snippet": snippet,
                    "content": content[:5000],  # safety truncation
                }
            )

        # IMPORTANT: return a string, not a tuple
        return json.dumps({"items": items})

    # Optional async variant (some frameworks may call this)
    async def _arun(self, **kwargs: Any) -> str:  # pragma: no cover
        # Delegate to sync path to keep behavior identical
        return self._run(**kwargs)
