

# app/loader.py
import os
import glob
import yaml
from typing import Dict, Any, Optional

# CrewAI core
from crewai import Agent, Task, Crew, Process

# Your model/types
from app.models import LLM  # and optionally SCHEMA_REGISTRY if you have it

# Optional: output schemas registry
try:
    from app.models import SCHEMA_REGISTRY  # dict[str, pydantic.BaseModel subclass]
except Exception:
    SCHEMA_REGISTRY = {}

# Tools are optional; import defensively
try:
    from crewai_tools import TavilySearchTool, SerperDevTool
except Exception:
    TavilySearchTool = None
    SerperDevTool = None


def _read_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        return data

TOOL_REGISTRY = {}
if TavilySearchTool is not None:
    TOOL_REGISTRY["TavilySearchTool"] = lambda cfg: TavilySearchTool(**(cfg or {}))
if SerperDevTool is not None:
    TOOL_REGISTRY["SerperDevTool"] = lambda cfg: SerperDevTool(**(cfg or {}))
    
# Map YAML tool 'type' -> constructor (only include available tools)
TOOL_REGISTRY: Dict[str, Any] = {}
if TavilySearchTool is not None:
    TOOL_REGISTRY["TavilySearchTool"] = lambda cfg: TavilySearchTool(**(cfg or {}))
if SerperDevTool is not None:
    TOOL_REGISTRY["SerperDevTool"] = lambda cfg: SerperDevTool(**(cfg or {}))


def load_llm(llm_yaml_path: str) -> LLM:
    data = _read_yaml(llm_yaml_path).get("llm", {})
    api_key = os.getenv("GROQ_API_KEY")  # from .env or environment
    if not api_key and data.get("api_key"):
        # allow YAML override if you want (optional)
        api_key = data["api_key"]

    return LLM(
        provider=data.get("provider", "groq"),
        model=data.get("model", "llama-3.3-70b-versatile"),
        api_key=api_key,
        base_url=data.get("base_url", "https://api.groq.com/openai/v1"),
        temperature=data.get("temperature", 0.2),
    )


def load_tools(tools_dir: str) -> Dict[str, Any]:
    tools: Dict[str, Any] = {}
    if not os.path.isdir(tools_dir):
        return tools  # no tools folder -> fine

    for path in glob.glob(os.path.join(tools_dir, "*.yaml")):
        y = _read_yaml(path).get("tool", {})
        name = y["name"]
        ttype = y["type"]

        constructor = TOOL_REGISTRY.get(ttype)
        if constructor is None:
            # Helpful error when a tool type is referenced but not available
            raise ValueError(
                f"Unsupported or unavailable tool type '{ttype}' in {path}. "
                f"Ensure the corresponding package is installed and imported."
            )

        tools[name] = constructor(y.get("config", {}))

    return tools


def load_agents(agents_dir: str, llm: LLM, tools_by_name: Dict[str, Any]) -> Dict[str, Agent]:
    agents: Dict[str, Agent] = {}

    for path in glob.glob(os.path.join(agents_dir, "*.yaml")):
        y = _read_yaml(path).get("agent", {})

        tool_objs = [tools_by_name[t] for t in y.get("tools", []) if t in tools_by_name]

        agent = Agent(
            name=y["name"],
            role=y["role"],
            goal=y["goal"],
            backstory=y.get("backstory", ""),
            verbose=y.get("verbose", False),
            allow_delegation=y.get("allow_delegation", False),
            tools=tool_objs,
            llm=llm,
        )

        # CrewAI 1.8.x prefers .role as the key used in tasks
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
    tasks: Dict[str, Task] = {}

    for path in glob.glob(os.path.join(tasks_dir, "*.yaml")):
        y = _read_yaml(path).get("task", {})

        agent_name = y["agent"]  # should match Agent.role
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

    y = _read_yaml(crew_yaml_path).get("crew", {})

    order = y["order"]
    task_list = [tasks_by_name[name] for name in order]

    process = y.get("process", "sequential").lower()
    process_enum = Process.sequential if process == "sequential" else Process.parallel

    agent_list = [agents_by_name[a] for a in y.get("agents", agents_by_name.keys())]

    return Crew(
        name=y.get("name"),
        agents=agent_list,
        tasks=task_list,
        process=process_enum,
        verbose=True,
    )