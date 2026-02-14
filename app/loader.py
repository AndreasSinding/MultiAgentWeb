# app/loader.py
import os
import glob
from typing import Dict, Any, Optional

import yaml
from dotenv import load_dotenv

# <-- NEW: import your custom tool
from app.exa_tool import ExaSearchAndContents

# Pydantic schemas
from app.models import ResearchOutput, AnalysisOutput

load_dotenv()

# app/loader.py

# 1) sqlite shim to satisfy chromadb (must be before crewai_tools import)
try:
    import pysqlite3  # provides sqlite3 >= 3.35
    import sys
    sys.modules["sqlite3"] = pysqlite3
    sys.modules["sqlite"] = pysqlite3
except Exception:
    pass

from crewai import Agent, Task, Crew, LLM, Process
from crewai_tools import TavilySearchTool, SerperDevTool  # safe now


# Map YAML schema names -> actual Pydantic classes
SCHEMA_REGISTRY = {
    "ResearchOutput": ResearchOutput,
    "AnalysisOutput": AnalysisOutput,
}

# Map YAML tool 'type' -> constructor
# NOTE: keys are the 'type' values you'll put in the tool YAML.
TOOL_REGISTRY = {
    "TavilySearchTool": lambda cfg: TavilySearchTool(**(cfg or {})),
    "SerperDevTool": lambda cfg: SerperDevTool(**(cfg or {})),
    # NEW: Exa tool (two aliases for convenience)
    "ExaSearchAndContents": lambda cfg: ExaSearchAndContents(**(cfg or {})),
    "exa_search_and_contents": lambda cfg: ExaSearchAndContents(**(cfg or {})),
}


def _read_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_llm(llm_yaml_path: str) -> LLM:
    data = _read_yaml(llm_yaml_path).get("llm", {})
    api_key = os.getenv("GROQ_API_KEY")  # from .env
    return LLM(
        provider=data.get("provider", "groq"),
        model=data.get("model", "llama-3.3-70b-versatile"),
        api_key=api_key,
        base_url=data.get("base_url", "https://api.groq.com/openai/v1"),
        temperature=data.get("temperature", 0.2),
    )


def load_tools(tools_dir: str) -> Dict[str, Any]:
    """
    Loads tool YAMLs of the form:

    tool:
      name: exa            # <--- this is the key you'll use in agent YAML
      type: ExaSearchAndContents
      config:
        results: 5
        pages: 5
    """
    tools: Dict[str, Any] = {}
    for path in glob.glob(os.path.join(tools_dir, "*.yaml")):
        y = _read_yaml(path).get("tool", {})
        name = y.get("name")
        ttype = y.get("type")

        if not name or not ttype:
            raise ValueError(f"Tool YAML missing 'name' or 'type': {path}")

        constructor = TOOL_REGISTRY.get(ttype)
        if constructor is None:
            raise ValueError(f"Unsupported tool type '{ttype}' in {path}")

        if name in tools:
            raise ValueError(f"Duplicate tool name '{name}' in {path}")

        tools[name] = constructor(y.get("config", {}))

    return tools


def load_agents(agents_dir: str, llm: LLM, tools_by_name: Dict[str, Any]) -> Dict[str, Agent]:
    """
    Agent YAML example:

    agent:
      name: Web Researcher
      role: researcher
      goal: "Find the best sources"
      backstory: "Expert web sleuth"
      verbose: true
      memory: false
      allow_delegation: false
      tools: [exa, tavily]
    """
    agents: Dict[str, Agent] = {}

    for path in glob.glob(os.path.join(agents_dir, "*.yaml")):
        y = _read_yaml(path).get("agent", {})

        tool_names = y.get("tools", []) or []
        # Fail fast on unknown tools to avoid silent drops
        missing = [t for t in tool_names if t not in tools_by_name]
        if missing:
            raise ValueError(
                f"Unknown tool(s) {missing} referenced by agent YAML {path}. "
                f"Available: {list(tools_by_name.keys())}"
            )

        tool_objs = [tools_by_name[t] for t in tool_names]

        agent = Agent(
            name=y["name"],
            role=y["role"],
            goal=y["goal"],
            backstory=y.get("backstory", ""),
            verbose=y.get("verbose", False),
            allow_delegation=y.get("allow_delegation", False),
            tools=tool_objs,  # must be BaseTool instances (now ensured by TOOL_REGISTRY)
            llm=llm,
        )

        # Use .role instead of .name (CrewAI 1.8.x expectation in some flows)
        agents[agent.role] = agent

    return agents


def _schema_from_name(name: Optional[str]):
    if not name:
        return None
    schema = SCHEMA_REGISTRY.get(name)
    if schema is None:
        raise ValueError(f"Unknown output_schema '{name}'. Add it to SCHEMA_REGISTRY.")
    return schema


def load_tasks(tasks_dir: str, agents_by_name: Dict[str, Agent]) -> Dict[str, Task]:
    """
    Task YAML example:

    task:
      name: Do research
      agent: researcher
      description: "Search and summarize"
      expected_output: "Bulleted list"
      output_schema: ResearchOutput
    """
    tasks: Dict[str, Task] = {}

    for path in glob.glob(os.path.join(tasks_dir, "*.yaml")):
        y = _read_yaml(path).get("task", {})

        agent_name = y["agent"]
        if agent_name not in agents_by_name:
            raise ValueError(
                f"Task YAML {path} references unknown agent '{agent_name}'. "
                f"Available agents: {list(agents_by_name.keys())}"
            )
        agent = agents_by_name[agent_name]
        schema = _schema_from_name(y.get("output_schema"))

        task = Task(
            name=y.get("name"),
            description=y["description"],
            agent=agent,
            expected_output=y.get("expected_output", ""),
            output_pydantic=schema,
        )
        tasks[y["name"]] = task

    return tasks


def load_crew(
    crew_yaml_path: str,
    agents_by_name: Dict[str, Agent],
    tasks_by_name: Dict[str, Task],
) -> Crew:
    """
    Crew YAML example:

    crew:
      name: MarketAlt
      agents: [researcher, analyst]
      order: ["Do research", "Write analysis"]
      process: sequential  # or parallel
    """
    y = _read_yaml(crew_yaml_path).get("crew", {})

    order = y["order"]
    task_list = [tasks_by_name[name] for name in order]

    process = y.get("process", "sequential").lower()
    process_enum = Process.sequential if process == "sequential" else Process.parallel

    agent_list = [agents_by_name[a] for a in y.get("agents", agents_by_name.keys())]

    # IMPORTANT: return the Crew object, not a tuple
    return Crew(
        name=y.get("name"),
        agents=agent_list,
        tasks=task_list,
        process=process_enum,
        verbose=True,
    )
