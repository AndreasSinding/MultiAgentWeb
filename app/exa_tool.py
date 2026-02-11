import os
from future import annotations
from pydantic import BaseModel, Field
from crewaitools import BaseTool
import exa
DEFAULTRESULTS = 5
DEFAULTPAGES = 5

class ExaSearchAndContentsInput(BaseModel):
    query: str = Field(…, description="Natural-language query")
    results: int = Field(DEFAULTRESULTS, ge=1, le=25)
    pages: int = Field(DEFAULTPAGES, ge=1, le=25)
    includedomains: Optional[List[str]] = None
    excludedomains: Optional[List[str]] = None
    recencydays: Optional[int] = None

class ExaSearchAndContents(BaseTool):
    name: str = "exasearchandcontents"
    description: str = (
        "Lightweight Exa search+contents tool with strict per-task budget. "
        "Returns compact JSON items: title, url, snippet, content (truncated)."
    )
    argsschema: type = ExaSearchAndContentsInput

maxtotal_searches: int = 3
    _searchcalls: int = 0

    def init(self, results: int = DEFAULTRESULTS, pages: int = DEFAULTPAGES, kwargs):
        super().init(kwargs)
        exa.apikey = os.environ.get("EXAAPIKEY", "")
        if not exa.apikey:
            raise RuntimeError("Missing EXAAPIKEY")
        self.results = max(1, min(25, results))
        self.pages = max(1, min(25, pages))
        self.search_calls = 0

    def _guardbudget(self):
        if self.searchcalls >= self.maxtotalsearches:
            raise RuntimeError(f"Search budget exceeded (max {self.maxtotalsearches}).")
        self.search_calls += 1

    def _run(self,
             query: str,
             results: int = None,
             pages: int = None,
             includedomains: Optional[List[str]] = None,
             excludedomains: Optional[List[str]] = None,
             recencydays: Optional[int] = None) -> str:

        self.guardbudget()
        r = results or self.results
        p = pages or self.pages

        opts: Dict[str, Any] = {"numresults": int(r)}
        if includedomains:
            opts["includedomains"] = includedomains
        if excludedomains:
            opts["excludedomains"] = excludedomains
        if recencydays:
            opts["startpublisheddate"] = f"now-{int(recencydays)}d"

        try:
            resp = exa.searchandcontents(query, **opts)
        except Exception as e:
            return '{"items": [], "note": "exa.searchandcontents failed: %s"}' % str(e)

        items = []
        for it in getattr(resp, "results", [])[:p]:
            title = getattr(it, "title", "") or ""
            url = getattr(it, "url", "") or ""
            snippet = getattr(it, "highlight", "") or getattr(it, "description", "") or ""
            content = getattr(it, "text", "") or getattr(it, "content", "") or ""
            published = getattr(it, "publisheddate", None)
            items.append({
                "title": title,
                "url": url,
                "publisheddate": published,
                "snippet": snippet,
                "content": content[:5000]
            })

        import json
        return json.dumps({"items": items})


