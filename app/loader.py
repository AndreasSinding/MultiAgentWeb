
# app/loader.py
from __future__ import annotations
import os
import glob
import yaml
from typing import Dict, Any, Optional

from crewai import Agent, Task, Crew, LLM, Process

# Import your tool classes
from app.exa_tool import ExaSearchAndContents

# Import your Pydantic schemas if needed
from app.models import ResearchOutput, AnalysisOutput

# ---------------------------------------------------------------------
# REGISTRIES
# ---------------------------------------------------------------------

# Map output_schema names → actual Pydantic classes
SCHEMA_REGISTRY = {
    "ResearchOutput": ResearchOutput,
    "AnalysisOutput": AnalysisOutput,
}

# Map YAML tool "type" → Python constructor
TOOL_REGISTRY = {
    "ExaSearchAndContents": lambda cfg: ExaSearchAndContents(**(cfg or {})),
}

# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------
def _read_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------
# LLM LOADER
# ---------------------------------------------------------------------
def load_llm(llm_yaml_path: str) -> LLM:
    data = _read_yaml(llm_yaml_path).get("llm", {})
    key = os.getenv("GROQ_API_KEY")
    return LLM(
        provider=data.get("provider", "groq"),
        model=data.get("model", "llama-3.3-70b-versatile"),
        api_key=key,
        base_url=data.get("base_url", "https://api.groq.com/openai/v1"),
        temperature=data.get("temperature", 0.2),
    )


# ---------------------------------------------------------------------
# TOOL LOADER
# ---------------------------------------------------------------------
def load_tools(tools_dir: str):
    tools = {}
    for path in glob.glob(os.path.join(tools_dir, "*.yaml")):
        y = _read_yaml(path).get("tool", {})
        name = y["name"]
        ttype = y["type"]
        constructor = TOOL_REGISTRY.get(ttype)
        if constructor is None:
            raise ValueError(f"Unsupported tool type '{ttype}' in {path}")
        tools[name] = constructor(y.get("config", {}))
    return tools


# ---------------------------------------------------------------------
# AGENT LOADER
# ---------------------------------------------------------------------
def load_agents(agents_dir: str, llm: LLM, tools_by_name: Dict[str, Any]):
    agents = {}
    for path in glob.glob(os.path.join(agents_dir, "*.yaml")):
        y = _read_yaml(path).get("agent", {})

        # Load tools assigned to the agent
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
            memory = false
            tools=tool_objs,
            llm=llm,
        )

        # IMPORTANT: CrewAI indexes agents by "role"
        agents[agent.role] = agent
    return agents


# ---------------------------------------------------------------------
# SCHEMA RESOLVER
# ---------------------------------------------------------------------
def _schema_from_name(name: Optional[str]):
    if not name:
        return None
    schema = SCHEMA_REGISTRY.get(name)
    if schema is None:
        raise ValueError(f"Unknown output_schema '{name}'. Add it to SCHEMA_REGISTRY.")
    return schema


# ---------------------------------------------------------------------
# TASK LOADER
# ---------------------------------------------------------------------
def load_tasks(tasks_dir: str, agents_by_name: Dict[str, Agent]):
    tasks = {}
    for path in glob.glob(os.path.join(tasks_dir, "*.yaml")):
        y = _read_yaml(path).get("task", {})

        agent_role = y["agent"]
        agent = agents_by_name[agent_role]

        schema = _schema_from_name(y.get("output_schema"))

        task = Task(
            name=y["name"],
            description=y["description"],
            agent=agent,
            expected_output=y.get("expected_output", ""),
            output_pydantic=schema,
        )

        tasks[y["name"]] = task
    return tasks


# ---------------------------------------------------------------------
# CREW LOADER
# ---------------------------------------------------------------------
def load_crew(crew_yaml_path: str, agents: Dict[str, Agent], tasks: Dict[str, Task]) -> Crew:
    y = _read_yaml(crew_yaml_path).get("crew", {})

    # Ordered list of task names
    order = y["order"]
    task_list = [tasks[name] for name in order]

    # Process type
    process = y.get("process", "sequential").lower()
    process_enum = Process.sequential if process == "sequential" else Process.parallel

    # Agent list (explicit or fallback to all)
    agent_list = [agents[a] for a in y.get("agents", agents.keys())]

    return Crew(
        name=y.get("name"),
        agents=agent_list,
        tasks=task_list,
        process=process_enum,
        verbose=True,
    )
