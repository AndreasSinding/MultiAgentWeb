class BaseTool:
    """
    Minimal BaseTool replacement to avoid importing crewai_tools
    and therefore avoid pulling in Chroma.
    """

    name: str = "tool"
    description: str = ""
    args_schema = None

    def __call__(self, **kwargs):
        return self._run(**kwargs)
