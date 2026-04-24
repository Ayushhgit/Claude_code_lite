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
from llm.client import generate
from utils.ui import console


# ─── Agent Persona Prompts ──────────────────────────────────────────────────

ARCHITECT_SYSTEM = """You are the ARCHITECT agent — a senior systems designer who plans like an elite engineer.

YOUR METHODOLOGY (follow this EXACTLY):

PHASE 1 — DEEP UNDERSTANDING:
Before writing a single line of the plan, you MUST first internalize the existing codebase.
You have been given the codebase structure (AST map). Study it carefully:
- What modules already exist? What patterns do they use?
- What is the dependency graph between files?
- Where are the integration points (imports, function calls, shared state)?
- What naming conventions, coding style, and patterns does this project follow?

PHASE 2 — PLAN DESIGN:
Now design the implementation plan. Think about it like building a house:
- Foundation first (data models, config, types)
- Then walls (core logic modules)
- Then wiring (integration into existing code)
- Then finishing (tests, polish, documentation)

PHASE 3 — OUTPUT:
Return a structured JSON plan.

OUTPUT FORMAT (strict JSON):
{
  "summary": "One-line description of the overall goal",
  "complexity": "simple|medium|complex",
  "understanding": "2-3 sentences proving you understood the existing architecture",
  "new_files": ["list of NEW files to create"],
  "modified_files": ["list of EXISTING files that need changes"],
  "steps": [
    {
      "id": 1,
      "phase": "foundation|implementation|integration|verification",
      "action": "Detailed description of what to do — be specific about function names, class names, and exact behavior",
      "files": ["exact file paths to create or modify"],
      "details": "Implementation specifics: what functions to add, what to import, what patterns to follow",
      "dependencies": [0],
      "validation": "Exact command or check to verify this step worked (e.g. 'python -m py_compile src/module.py' or 'run_tests')"
    }
  ],
  "integration_points": ["Exact places in existing code where new code must be wired in"],
  "risks": ["Potential issues to watch for"],
  "estimated_turns": 5
}

CRITICAL RULES:
1. NEVER suggest vague steps like "implement the feature". Every step must name EXACT files, functions, and classes.
2. Order steps by dependency — foundation before implementation, implementation before integration.
3. Each step must be independently executable and verifiable.
4. Include a `validation` for EVERY step — prefer automated checks (py_compile, lint_check, run_tests) over "manual check".
5. The `integration_points` field must list the exact existing files + functions where new code needs to be wired in (imports added, functions called, etc.).
6. Study the codebase structure you were given. Do NOT suggest creating files that already exist. Do NOT rename things that are already named.
7. Match the existing project's patterns. If they use `snake_case`, you use `snake_case`. If they put tools in `tools.py`, you register tools in `tools.py`.
8. Return ONLY valid JSON, no markdown, no explanation outside the JSON.
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
    
    The Architect first deeply understands the codebase:
    1. Reads the AST map (all classes, functions, imports)
    2. Reads key project files (requirements, config, entry points)
    3. Reads .agent_memory.md for historical context
    Then designs a comprehensive, phased implementation plan.

    Args:
        instruction: The user's original request
        repo_context: AST repo map string

    Returns:
        dict: Structured plan with steps, or None if parsing failed
    """
    # ── Phase 1: Gather deep context ──
    path = os.getenv("FOLDER_PATH", ".")
    
    context_parts = []
    
    # 1. AST map (architecture skeleton)
    if repo_context:
        context_parts.append(f"CODEBASE ARCHITECTURE (AST Map):\n{repo_context[:4000]}")
    
    # 2. Key project files (entry points, config, manifests)
    key_files = [
        "requirements.txt", "package.json", "pyproject.toml",
        ".env", "README.md", "Makefile", "Dockerfile",
    ]
    for kf in key_files:
        kf_path = os.path.join(path, kf)
        if os.path.exists(kf_path):
            try:
                with open(kf_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()[:800]
                context_parts.append(f"FILE: {kf}\n{content}")
            except Exception:
                pass
    
    # 3. Agent memory (historical context)
    memory_path = os.path.join(path, ".agent_memory.md")
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r", encoding="utf-8") as f:
                memory = f.read()[:500]
            context_parts.append(f"AGENT MEMORY (past sessions):\n{memory}")
        except Exception:
            pass
    
    # 4. Existing scratchpad (in-progress work)
    try:
        from core.scratchpad import get_scratchpad_context
        scratchpad = get_scratchpad_context(path)
        if scratchpad:
            context_parts.append(f"ACTIVE SCRATCHPAD:\n{scratchpad}")
    except Exception:
        pass
    
    full_context = "\n\n---\n\n".join(context_parts)
    
    # ── Phase 2: Send to Architect LLM ──
    messages = [
        {"role": "system", "content": ARCHITECT_SYSTEM},
        {"role": "user", "content": f"USER REQUEST:\n{instruction}\n\n---\n\n{full_context}"}
    ]

    console.print("  [bold magenta]🏗️  Architect agent is designing the plan...[/bold magenta]")
    console.print("  [dim]  -> Analyzed AST map, key files, and memory[/dim]")

    try:
        response = generate(messages)
        plan = _extract_json(response)
        if plan and "steps" in plan:
            step_count = len(plan['steps'])
            understanding = plan.get('understanding', '')
            console.print(f"  [green]✓ Plan created: {step_count} steps, complexity={plan.get('complexity', '?')}[/green]")
            if understanding:
                console.print(f"  [dim]  Understanding: {understanding[:120]}...[/dim]")
            # Log integration points
            integration = plan.get("integration_points", [])
            if integration:
                console.print(f"  [dim]  Integration: {', '.join(integration[:5])}[/dim]")
            return plan
        else:
            console.print("  [yellow]⚠ Architect returned non-standard format, using as-is[/yellow]")
            return {
                "summary": instruction,
                "complexity": "simple",
                "steps": [{"id": 1, "phase": "implementation", "action": instruction, "files": [], "validation": "manual check"}],
            }
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
    """Save the plan to .revi/current_plan.json for persistence."""
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")
    plan_dir = os.path.join(directory, ".revi")
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
    plan_path = os.path.join(directory, ".revi", "current_plan.json")
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
    
    # Show understanding if available
    understanding = plan.get('understanding', '')
    if understanding:
        lines.append(f"UNDERSTANDING: {understanding[:200]}")
    
    for step in plan.get("steps", []):
        status = "✓" if step.get("status") == "complete" else "○"
        phase = f"[{step.get('phase', 'impl')}]" if step.get('phase') else ""
        lines.append(f"  {status} Step {step.get('id', '?')}: {phase} {step.get('action', '')}")
        if step.get("files"):
            lines.append(f"      Files: {', '.join(step['files'])}")
        if step.get("details") and step.get("status") != "complete":
            lines.append(f"      Details: {step['details'][:150]}")
        if step.get("validation") and step.get("status") != "complete":
            lines.append(f"      Verify: {step['validation']}")
    
    # Integration points
    integration = plan.get("integration_points", [])
    if integration:
        lines.append(f"\nINTEGRATION POINTS: {', '.join(integration[:8])}")
    
    return "\n".join(lines)
