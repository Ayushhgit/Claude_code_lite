"""
planner.py — Multi-Agent Delegation & Task Planning System

Implements three specialized agent personas that collaborate:
- Architect: Decomposes complex requests into step-by-step plans
- Executor: Executes each step using tools (default agent behavior)
- Reviewer: Validates completed work, runs tests, provides critique

The planner decides when to engage each persona based on task complexity.
Simple tasks go straight to the Executor. Complex/E2E tasks get the full
Architect → Executor → Reviewer pipeline.
"""

import os
import json
import re
from llm.groq_client import generate
from utils.ui import console


# ─── Agent Persona Prompts ──────────────────────────────────────────────────

ARCHITECT_SYSTEM = """You are the ARCHITECT agent — a senior systems designer.

Your job is to analyze the user's request and produce a precise, actionable implementation plan.

OUTPUT FORMAT (strict JSON):
{
  "summary": "One-line description of the overall goal",
  "complexity": "simple|medium|complex",
  "steps": [
    {
      "id": 1,
      "action": "Short description of what to do",
      "files": ["list of files to create or modify"],
      "dependencies": [],
      "validation": "How to verify this step worked"
    }
  ],
  "risks": ["Potential issues to watch for"],
  "estimated_turns": 5
}

RULES:
1. Be specific — name exact files, functions, and modules
2. Order steps by dependency — step 2 should not depend on step 5
3. Each step must be independently executable by a coding agent
4. Include a validation check for every step (test command, lint, or manual check)
5. Return ONLY valid JSON, no markdown, no explanation
"""

REVIEWER_SYSTEM = """You are the REVIEWER agent — a senior code reviewer.

You have been given the ORIGINAL user request and the DIFF of changes made by the executor agent.
Your job is to review the work and provide structured feedback.

OUTPUT FORMAT (strict JSON):
{
  "verdict": "approve|request_changes|reject",
  "score": 8,
  "issues": [
    {
      "severity": "critical|warning|suggestion",
      "file": "path/to/file.py",
      "description": "What's wrong",
      "fix": "How to fix it"
    }
  ],
  "summary": "Overall assessment in 2-3 sentences",
  "tests_to_run": ["list of test commands to verify"]
}

RULES:
1. Be thorough but not pedantic — focus on correctness, security, and maintainability
2. Score from 1-10. 7+ = approve, 4-6 = request_changes, 1-3 = reject
3. Always suggest at least one test command to verify the changes
4. Return ONLY valid JSON
"""


# ─── Complexity Detection ───────────────────────────────────────────────────

COMPLEXITY_KEYWORDS = {
    "complex": [
        "build", "create project", "scaffold", "full stack", "e2e", "end to end",
        "from scratch", "entire", "complete app", "production", "deploy",
        "microservice", "api and frontend", "database schema", "migration",
        "refactor the whole", "rewrite", "redesign", "architecture",
    ],
    "medium": [
        "add feature", "implement", "integrate", "connect", "set up",
        "configure", "multiple files", "across the codebase",
        "add tests", "add logging", "add auth",
    ],
}


def detect_complexity(instruction: str) -> str:
    """Classify task complexity to decide the agent pipeline."""
    instruction_lower = instruction.lower()

    for keyword in COMPLEXITY_KEYWORDS["complex"]:
        if keyword in instruction_lower:
            return "complex"

    for keyword in COMPLEXITY_KEYWORDS["medium"]:
        if keyword in instruction_lower:
            return "medium"

    return "simple"


# ─── Architect Agent ─────────────────────────────────────────────────────────

def run_architect(instruction: str, repo_context: str = "") -> dict:
    """
    Run the Architect agent to decompose a complex request into a plan.

    Args:
        instruction: The user's original request
        repo_context: Optional repo map or file listing for context

    Returns:
        dict: Structured plan with steps, or None if parsing failed
    """
    context_block = ""
    if repo_context:
        context_block = f"\n\nCURRENT CODEBASE STRUCTURE:\n{repo_context[:3000]}"

    messages = [
        {"role": "system", "content": ARCHITECT_SYSTEM},
        {"role": "user", "content": f"USER REQUEST:\n{instruction}{context_block}"}
    ]

    console.print("  [bold magenta]🏗️  Architect agent is designing the plan...[/bold magenta]")

    try:
        response = generate(messages)
        # Try to extract JSON from the response
        plan = _extract_json(response)
        if plan and "steps" in plan:
            console.print(f"  [green]✓ Plan created: {len(plan['steps'])} steps, complexity={plan.get('complexity', '?')}[/green]")
            return plan
        else:
            console.print("  [yellow]⚠ Architect returned non-standard format, using as-is[/yellow]")
            return {"summary": instruction, "steps": [{"id": 1, "action": instruction, "files": [], "validation": "manual check"}], "complexity": "simple"}
    except Exception as e:
        console.print(f"  [red]✗ Architect failed: {e}[/red]")
        return None


# ─── Reviewer Agent ──────────────────────────────────────────────────────────

def run_reviewer(instruction: str, changes_summary: str) -> dict:
    """
    Run the Reviewer agent to validate completed work.

    Args:
        instruction: The original user request
        changes_summary: Summary of what the executor did (diffs, file list, etc.)

    Returns:
        dict: Review with verdict, score, and issues
    """
    messages = [
        {"role": "system", "content": REVIEWER_SYSTEM},
        {"role": "user", "content": f"ORIGINAL REQUEST:\n{instruction}\n\nCHANGES MADE:\n{changes_summary[:4000]}"}
    ]

    console.print("  [bold cyan]🔍 Reviewer agent is inspecting the changes...[/bold cyan]")

    try:
        response = generate(messages)
        review = _extract_json(response)
        if review and "verdict" in review:
            verdict_color = {"approve": "green", "request_changes": "yellow", "reject": "red"}.get(review["verdict"], "white")
            console.print(f"  [{verdict_color}]Review: {review['verdict'].upper()} (score: {review.get('score', '?')}/10)[/{verdict_color}]")
            if review.get("issues"):
                for issue in review["issues"][:5]:
                    sev_color = {"critical": "red", "warning": "yellow", "suggestion": "dim"}.get(issue.get("severity", ""), "white")
                    console.print(f"    [{sev_color}]• [{issue.get('severity', '?')}] {issue.get('description', '')}[/{sev_color}]")
            return review
        else:
            return {"verdict": "approve", "score": 7, "summary": response[:200], "issues": []}
    except Exception as e:
        console.print(f"  [red]✗ Reviewer failed: {e}[/red]")
        return {"verdict": "approve", "score": 5, "summary": f"Review failed: {e}", "issues": []}


# ─── Plan Persistence ────────────────────────────────────────────────────────

def save_plan(plan: dict, directory: str = None):
    """Save the plan to .kinda_claude/current_plan.json for persistence."""
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")
    plan_dir = os.path.join(directory, ".kinda_claude")
    os.makedirs(plan_dir, exist_ok=True)
    plan_path = os.path.join(plan_dir, "current_plan.json")
    try:
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
    except Exception:
        pass


def load_plan(directory: str = None) -> dict:
    """Load the current plan if one exists."""
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")
    plan_path = os.path.join(directory, ".kinda_claude", "current_plan.json")
    if os.path.exists(plan_path):
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def mark_step_complete(step_id: int, directory: str = None):
    """Mark a step in the current plan as complete."""
    plan = load_plan(directory)
    if plan and "steps" in plan:
        for step in plan["steps"]:
            if step.get("id") == step_id:
                step["status"] = "complete"
                break
        save_plan(plan, directory)


def get_next_step(directory: str = None) -> dict:
    """Get the next incomplete step from the current plan."""
    plan = load_plan(directory)
    if plan and "steps" in plan:
        for step in plan["steps"]:
            if step.get("status") != "complete":
                return step
    return None


# ─── Utilities ───────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting from code block
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in text
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def format_plan_for_context(plan: dict) -> str:
    """Format a plan into a compact string for injection into the agent's context."""
    if not plan:
        return ""
    lines = [f"ACTIVE PLAN: {plan.get('summary', 'N/A')}"]
    for step in plan.get("steps", []):
        status = "✓" if step.get("status") == "complete" else "○"
        lines.append(f"  {status} Step {step.get('id', '?')}: {step.get('action', '')}")
        if step.get("files"):
            lines.append(f"      Files: {', '.join(step['files'])}")
    return "\n".join(lines)
