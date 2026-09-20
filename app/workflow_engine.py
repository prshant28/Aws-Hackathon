"""
Workflow Engine — Tracks multi-agent workflow execution.
Each user request spawns a Workflow with named Steps assigned to specific agents.
"""

import uuid
import datetime
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# ─── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class WorkflowStep:
    id: str
    name: str
    agent: str
    tool: str
    status: str = "pending"
    input: Dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_ms: float = 0
    # Entity audit fields for the assistant's "done" chip — populated by the
    # coordinator after a tool returns. None when no count is meaningful (e.g.
    # stats lookups). The frontend renders "{verb} {count} {noun}" when present.
    entity_count: Optional[int] = None
    entity_noun: str = ""
    entity_verb: str = ""

    def start(self):
        self.status = "running"
        self.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._start_ts = time.time()

    def complete(self, output: Any):
        self.status = "completed"
        self.output = output
        self.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.duration_ms = (time.time() - getattr(self, "_start_ts", time.time())) * 1000

    def fail(self, error: str):
        self.status = "failed"
        self.error = error
        self.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.duration_ms = (time.time() - getattr(self, "_start_ts", time.time())) * 1000

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "agent": self.agent,
            "tool": self.tool,
            "status": self.status,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": round(self.duration_ms, 1),
            "entity_count": self.entity_count,
            "entity_noun": self.entity_noun,
            "entity_verb": self.entity_verb,
        }


@dataclass
class Workflow:
    id: str
    name: str
    description: str
    user_message: str
    session_id: str
    status: str = "pending"
    steps: List[WorkflowStep] = field(default_factory=list)
    created_at: str = ""
    completed_at: str = ""
    final_reply: str = ""
    agents_called: List[str] = field(default_factory=list)
    error: str = ""

    def add_step(self, name: str, agent: str, tool: str, input_data: dict = None) -> WorkflowStep:
        step = WorkflowStep(
            id=str(uuid.uuid4())[:8],
            name=name,
            agent=agent,
            tool=tool,
            input=input_data or {}
        )
        self.steps.append(step)
        if agent not in self.agents_called:
            self.agents_called.append(agent)
        return step

    def complete(self, reply: str):
        self.status = "completed"
        self.final_reply = reply
        self.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def fail(self, error: str):
        self.status = "failed"
        self.error = error
        self.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "user_message": self.user_message,
            "session_id": self.session_id,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "final_reply": self.final_reply,
            "agents_called": self.agents_called,
            "error": self.error
        }


# ─── In-Memory Store ──────────────────────────────────────────────────────────

_workflows: Dict[str, Workflow] = {}
MAX_WORKFLOWS = 50


def create_workflow(name: str, description: str, user_message: str, session_id: str) -> Workflow:
    wf = Workflow(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        user_message=user_message,
        session_id=session_id,
        status="running",
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    _workflows[wf.id] = wf
    # Trim old workflows
    if len(_workflows) > MAX_WORKFLOWS:
        oldest_key = min(_workflows, key=lambda k: _workflows[k].created_at)
        del _workflows[oldest_key]
    return wf


def get_workflow(workflow_id: str) -> Optional[Workflow]:
    return _workflows.get(workflow_id)


def list_workflows(limit: int = 20) -> List[dict]:
    sorted_wfs = sorted(_workflows.values(), key=lambda w: w.created_at, reverse=True)
    return [w.to_dict() for w in sorted_wfs[:limit]]


# ─── Agent Registry ───────────────────────────────────────────────────────────

AGENT_REGISTRY = {
    "Orchestrator": {
        "id": "orchestrator",
        "name": "Orchestrator",
        "role": "Primary coordinator. Plans and delegates tasks to sub-agents.",
        "color": "#00d4ff",
        "icon": "brain",
        "tools": ["plan_workflow", "delegate", "synthesize"]
    },
    "CaptureAgent": {
        "id": "capture",
        "name": "CaptureAgent",
        "role": "Captures and analyzes knowledge from YouTube, web, PDFs and notes.",
        "color": "#f43f5e",
        "icon": "youtube",
        "tools": ["capture_youtube", "capture_web", "capture_pdf", "capture_note"]
    },
    "RecallAgent": {
        "id": "recall",
        "name": "RecallAgent",
        "role": "Semantic search across saved memories with 3-tier recall strategy.",
        "color": "#8b5cf6",
        "icon": "search",
        "tools": ["semantic_search", "keyword_search", "domain_filter"]
    },
    "TaskAgent": {
        "id": "tasks",
        "name": "TaskAgent",
        "role": "Creates, manages and tracks tasks linked to learning goals.",
        "color": "#10b981",
        "icon": "check",
        "tools": ["create_task", "list_tasks", "complete_task", "prioritize"]
    },
    "CalendarAgent": {
        "id": "calendar",
        "name": "CalendarAgent",
        "role": "Schedules study sessions and manages calendar events.",
        "color": "#f59e0b",
        "icon": "calendar",
        "tools": ["schedule_event", "list_events", "suggest_time"]
    },
    "BriefingAgent": {
        "id": "briefing",
        "name": "BriefingAgent",
        "role": "Generates personalized daily briefings and study recommendations.",
        "color": "#06b6d4",
        "icon": "sparkles",
        "tools": ["generate_briefing", "suggest_review", "create_study_plan"]
    },
    "AnalyticsAgent": {
        "id": "analytics",
        "name": "AnalyticsAgent",
        "role": "Analyzes knowledge patterns, learning progress and productivity stats.",
        "color": "#3b82f6",
        "icon": "chart",
        "tools": ["get_stats", "knowledge_graph", "learning_velocity"]
    }
}
