"""
scratchpad.py — Persistent Task Tracker & Scratchpad

Markdown-based task management that the agent uses to stay oriented
across multiple turns. Prevents the agent from losing track of what
it has done vs. what it still needs to do.

Stored at .revi/scratchpad.md — auto-injected into context.
"""

import os
import json
import time
import datetime
from utils.ui import console


SCRATCHPAD_DIR = ".revi"
SCRATCHPAD_FILE = "scratchpad.md"
TASKS_FILE = "tasks.json"


# ─── Task Data Layer ─────────────────────────────────────────────────────────

def _get_tasks_path(directory=None):
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")
    tasks_dir = os.path.join(directory, SCRATCHPAD_DIR)
    os.makedirs(tasks_dir, exist_ok=True)
    return os.path.join(tasks_dir, TASKS_FILE)


def _load_tasks(directory=None):
    path = _get_tasks_path(directory)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"tasks": [], "notes": [], "session_goal": ""}


def _save_tasks(data, directory=None):
    path = _get_tasks_path(directory)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


# ─── Task Operations ─────────────────────────────────────────────────────────

def create_task(title: str, description: str = "", priority: str = "normal", directory=None) -> str:
    """Create a new task in the scratchpad."""
    data = _load_tasks(directory)

    task_id = len(data["tasks"]) + 1
    task = {
        "id": task_id,
        "title": title,
        "description": description,
        "priority": priority,
        "status": "pending",
        "created": datetime.datetime.now().isoformat(),
        "completed_at": None,
        "subtasks": [],
    }
    data["tasks"].append(task)
    _save_tasks(data, directory)
    _regenerate_scratchpad(data, directory)

    return f"Created task #{task_id}: {title}"


def complete_task(task_id: int, directory=None) -> str:
    """Mark a task as complete."""
    data = _load_tasks(directory)

    for task in data["tasks"]:
        if task["id"] == task_id:
            task["status"] = "complete"
            task["completed_at"] = datetime.datetime.now().isoformat()
            _save_tasks(data, directory)
            _regenerate_scratchpad(data, directory)
            return f"Completed task #{task_id}: {task['title']}"

    return f"Error: Task #{task_id} not found."


def add_subtask(task_id: int, subtask: str, directory=None) -> str:
    """Add a subtask to an existing task."""
    data = _load_tasks(directory)

    for task in data["tasks"]:
        if task["id"] == task_id:
            sub_id = len(task.get("subtasks", [])) + 1
            task.setdefault("subtasks", []).append({
                "id": sub_id,
                "title": subtask,
                "status": "pending"
            })
            _save_tasks(data, directory)
            _regenerate_scratchpad(data, directory)
            return f"Added subtask {task_id}.{sub_id}: {subtask}"

    return f"Error: Task #{task_id} not found."


def complete_subtask(task_id: int, subtask_id: int, directory=None) -> str:
    """Mark a subtask as complete."""
    data = _load_tasks(directory)

    for task in data["tasks"]:
        if task["id"] == task_id:
            for sub in task.get("subtasks", []):
                if sub["id"] == subtask_id:
                    sub["status"] = "complete"
                    _save_tasks(data, directory)
                    _regenerate_scratchpad(data, directory)
                    return f"Completed subtask {task_id}.{subtask_id}: {sub['title']}"

    return f"Error: Subtask not found."


def set_session_goal(goal: str, directory=None) -> str:
    """Set the high-level goal for the current session."""
    data = _load_tasks(directory)
    data["session_goal"] = goal
    _save_tasks(data, directory)
    _regenerate_scratchpad(data, directory)
    return f"Session goal set: {goal}"


def add_note(note: str, directory=None) -> str:
    """Add a free-form note to the scratchpad."""
    data = _load_tasks(directory)
    data.setdefault("notes", []).append({
        "text": note,
        "timestamp": datetime.datetime.now().isoformat(),
    })
    # Keep only last 20 notes
    data["notes"] = data["notes"][-20:]
    _save_tasks(data, directory)
    _regenerate_scratchpad(data, directory)
    return f"Note added."


def clear_completed(directory=None) -> str:
    """Remove all completed tasks."""
    data = _load_tasks(directory)
    before = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["status"] != "complete"]
    # Re-number remaining tasks
    for i, task in enumerate(data["tasks"]):
        task["id"] = i + 1
    after = len(data["tasks"])
    _save_tasks(data, directory)
    _regenerate_scratchpad(data, directory)
    return f"Cleared {before - after} completed tasks. {after} remaining."


# ─── Scratchpad Rendering ────────────────────────────────────────────────────

def _regenerate_scratchpad(data, directory=None):
    """Regenerate the human-readable scratchpad.md from the task data."""
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")

    lines = ["# REVI Agent Scratchpad", ""]

    # Session goal
    if data.get("session_goal"):
        lines.append(f"## Current Goal")
        lines.append(f"**{data['session_goal']}**")
        lines.append("")

    # Tasks
    pending = [t for t in data.get("tasks", []) if t["status"] == "pending"]
    completed = [t for t in data.get("tasks", []) if t["status"] == "complete"]

    if pending:
        lines.append(f"## Pending Tasks ({len(pending)})")
        for task in pending:
            priority_icon = {"high": "🔴", "normal": "🟡", "low": "🟢"}.get(task.get("priority", ""), "🟡")
            lines.append(f"- [ ] {priority_icon} **#{task['id']}**: {task['title']}")
            if task.get("description"):
                lines.append(f"  - {task['description']}")
            for sub in task.get("subtasks", []):
                check = "x" if sub["status"] == "complete" else " "
                lines.append(f"  - [{check}] {task['id']}.{sub['id']}: {sub['title']}")
        lines.append("")

    if completed:
        lines.append(f"## Completed ({len(completed)})")
        for task in completed[-5:]:
            lines.append(f"- [x] **#{task['id']}**: {task['title']}")
        if len(completed) > 5:
            lines.append(f"  _...and {len(completed)-5} more_")
        lines.append("")

    # Notes
    notes = data.get("notes", [])
    if notes:
        lines.append("## Notes")
        for note in notes[-5:]:
            ts = note.get("timestamp", "")[:16]
            lines.append(f"- [{ts}] {note['text']}")
        lines.append("")

    # Write scratchpad
    scratchpad_path = os.path.join(directory, SCRATCHPAD_DIR, SCRATCHPAD_FILE)
    try:
        with open(scratchpad_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass


def get_scratchpad_context(directory=None) -> str:
    """
    Get the current scratchpad content for injection into the agent's context.
    Returns a compact string. Returns empty string if no active tasks.
    """
    data = _load_tasks(directory)

    pending = [t for t in data.get("tasks", []) if t["status"] == "pending"]
    if not pending and not data.get("session_goal"):
        return ""

    lines = []
    if data.get("session_goal"):
        lines.append(f"SESSION GOAL: {data['session_goal']}")

    if pending:
        lines.append(f"ACTIVE TASKS ({len(pending)}):")
        for task in pending:
            lines.append(f"  [ ] #{task['id']}: {task['title']}")
            for sub in task.get("subtasks", []):
                check = "✓" if sub["status"] == "complete" else " "
                lines.append(f"      [{check}] {sub['title']}")

    return "\n".join(lines)


# ─── Tool Interfaces ─────────────────────────────────────────────────────────

def get_tasks_tool() -> str:
    """Tool: Get all current tasks."""
    data = _load_tasks()
    if not data["tasks"] and not data.get("session_goal"):
        return "No tasks or goals set. Use create_task to add tasks."

    lines = []
    if data.get("session_goal"):
        lines.append(f"Goal: {data['session_goal']}")

    for task in data["tasks"]:
        status = "✓" if task["status"] == "complete" else "○"
        priority = task.get("priority", "normal")
        lines.append(f"  {status} #{task['id']} [{priority}]: {task['title']}")
        for sub in task.get("subtasks", []):
            sub_status = "✓" if sub["status"] == "complete" else "○"
            lines.append(f"      {sub_status} {task['id']}.{sub['id']}: {sub['title']}")

    return "\n".join(lines)


def create_task_tool(title: str, description: str = "", priority: str = "normal") -> str:
    return create_task(title, description, priority)


def complete_task_tool(task_id: int) -> str:
    return complete_task(task_id)


def add_subtask_tool(task_id: int, subtask: str) -> str:
    return add_subtask(task_id, subtask)


def add_note_tool(note: str) -> str:
    return add_note(note)


def set_goal_tool(goal: str) -> str:
    return set_session_goal(goal)
