

import os
import glob
import yaml
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from crewai import Agent, Task, Crew, LLM, Process
from crewai_tools import TavilySearchTool, SerperDevTool
from app.exatool import ExaSearchAndContents

# Pydantic schemas
from app.models import ResearchOutput, AnalysisOutput

load_dotenv()
exa_api_key = os.getenv("EXA_API_KEY")

# Map YAML schema names -> actual Pydantic classes
SCHEMA_REGISTRY = {
    "ResearchOutput": ResearchOutput,
    "AnalysisOutput": AnalysisOutput,
}

# Map YAML tool 'type' -> constructor
TOOL_REGISTRY = {
    "TavilySearchTool": lambda cfg: TavilySearchTool(**(cfg or {})),
    "SerperDevTool": lambda cfg: SerperDevTool(**(cfg or {})),
    "ExaSearchAndContents": lamda cfg: ExaSearchAndContents (**(cfg or {})
}


def _read_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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


def load_tools(tools_dir: str):
    tools = {}
    for path in glob.glob(os.path.join(tools_dir, "*.yaml")):
        y = _read_yaml(path).get("tool", {})
        name = y["name"]
        ttype = y["type"]

        constructor = TOOL_REGISTRY.get(ttype)
        if constructor is None:
            raise ValueError(f"Unsupported tool type: {ttype} in {path}")

        tools[name] = constructor(y.get("config", {}))

    return tools



def load_agents(agents_dir: str, llm: LLM, tools_by_name: Dict[str, Any]):
    agents = {}
    for path in glob.glob(os.path.join(agents_dir, "*.yaml")):
        y = _read_yaml(path).get("agent", {})

        tool_objs = [
            tools_by_name[t] for t in y.get("tools", []) if t in tools_by_name
        ]

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

        # Use .role instead of .name (CrewAI 1.8.x requirement)
        agents[agent.role] = agent

    return agents



def _schema_from_name(name: Optional[str]):
    if not name:
        return None

    schema = SCHEMA_REGISTRY.get(name)
    if schema is None:
        raise ValueError(f"Unknown output_schema '{name}'. Add it to SCHEMA_REGISTRY.")

    return schema


def load_tasks(tasks_dir: str, agents_by_name: Dict[str, Agent]):
    tasks = {}
    for path in glob.glob(os.path.join(tasks_dir, "*.yaml")):
        y = _read_yaml(path).get("task", {})

        agent_name = y["agent"]
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
