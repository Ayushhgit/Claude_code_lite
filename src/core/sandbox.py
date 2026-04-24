"""
sandbox.py — Docker Workspace Sandboxing

Provides an optional Docker-based execution environment for safely running
agent-generated commands without risking the host machine.

Features:
- Automatic Docker container lifecycle management
- Workspace mounted as a volume (changes persist)
- Falls back gracefully to local execution if Docker unavailable
- Configurable via SANDBOX_ENABLED=true in .env
- Resource limits (CPU, memory) to prevent runaway processes
- Container reuse for performance (kept alive between commands)
"""

import os
import subprocess
import json
import time
import atexit
from utils.ui import console


# ─── Configuration ───────────────────────────────────────────────────────────

DEFAULT_IMAGE = "python:3.11-slim"
CONTAINER_PREFIX = "revi_sandbox"
CONTAINER_TIMEOUT = 300  # 5 min max per command
MEMORY_LIMIT = "512m"
CPU_LIMIT = "1.0"

# Track active containers for cleanup
_active_containers = {}


# ─── Docker Availability ────────────────────────────────────────────────────

def is_docker_available() -> bool:
    """Check if Docker is installed and running."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def is_sandbox_enabled() -> bool:
    """Check if sandboxing is enabled in the configuration."""
    from dotenv import load_dotenv
    load_dotenv()
    return os.getenv("SANDBOX_ENABLED", "false").lower() in ("true", "1", "yes")


# ─── Container Management ───────────────────────────────────────────────────

def _get_container_name(workspace_path: str) -> str:
    """Generate a deterministic container name for a workspace."""
    import hashlib
    path_hash = hashlib.md5(workspace_path.encode()).hexdigest()[:8]
    return f"{CONTAINER_PREFIX}_{path_hash}"


def ensure_container(workspace_path: str, image: str = None) -> str:
    """
    Ensure a sandbox container is running for the given workspace.
    Creates one if it doesn't exist, reuses if already running.

    Returns:
        str: Container name, or None if Docker unavailable
    """
    if not is_docker_available():
        return None

    container_name = _get_container_name(workspace_path)
    image = image or os.getenv("SANDBOX_IMAGE", DEFAULT_IMAGE)

    # Check if container already exists and is running
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and "true" in result.stdout.lower():
            return container_name
    except Exception:
        pass

    # Remove stale container if it exists but isn't running
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, timeout=10
        )
    except Exception:
        pass

    # Create and start a new container
    # Convert Windows path to Docker-compatible mount
    mount_path = workspace_path.replace('\\', '/')
    if ':' in mount_path:
        # Windows path: C:\path -> /c/path for Docker
        drive, rest = mount_path.split(':', 1)
        mount_path = f"/{drive.lower()}{rest}"

    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "--memory", MEMORY_LIMIT,
        "--cpus", CPU_LIMIT,
        "-v", f"{workspace_path}:/workspace",
        "-w", "/workspace",
        "--network", "bridge",
        image,
        "tail", "-f", "/dev/null"  # Keep container alive
    ]

    console.print(f"  [dim]🐳 Creating sandbox container ({image})...[/dim]")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            _active_containers[container_name] = workspace_path
            console.print(f"  [green]✓ Sandbox ready: {container_name}[/green]")
            return container_name
        else:
            console.print(f"  [red]✗ Failed to create sandbox: {result.stderr[:200]}[/red]")
            return None
    except Exception as e:
        console.print(f"  [red]✗ Docker error: {e}[/red]")
        return None


def stop_container(workspace_path: str):
    """Stop and remove the sandbox container for a workspace."""
    container_name = _get_container_name(workspace_path)
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, timeout=10
        )
        _active_containers.pop(container_name, None)
        console.print(f"  [dim]🐳 Sandbox stopped: {container_name}[/dim]")
    except Exception:
        pass


# ─── Sandboxed Command Execution ────────────────────────────────────────────

def run_in_sandbox(command: str, workspace_path: str = None, timeout: int = None) -> dict:
    """
    Execute a command inside the Docker sandbox.

    If Docker is unavailable or sandbox is disabled, falls back to local execution.

    Args:
        command: Shell command to execute
        workspace_path: Project root directory
        timeout: Max seconds to wait

    Returns:
        dict: {
            "stdout": str,
            "stderr": str,
            "exit_code": int,
            "sandboxed": bool,
            "error": str or None
        }
    """
    if not workspace_path:
        workspace_path = os.getenv("FOLDER_PATH", ".")

    timeout = timeout or CONTAINER_TIMEOUT

    # Check if sandbox is available and enabled
    if not is_sandbox_enabled() or not is_docker_available():
        return _run_local(command, workspace_path, timeout)

    container_name = ensure_container(workspace_path)
    if not container_name:
        console.print("  [yellow]⚠ Sandbox unavailable, falling back to local execution[/yellow]")
        return _run_local(command, workspace_path, timeout)

    # Execute command in container
    docker_cmd = [
        "docker", "exec", container_name,
        "bash", "-c", command
    ]

    try:
        result = subprocess.run(
            docker_cmd, capture_output=True, text=True, timeout=timeout
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "sandboxed": True,
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "", "stderr": f"Command timed out after {timeout}s",
            "exit_code": -1, "sandboxed": True, "error": "timeout"
        }
    except Exception as e:
        console.print(f"  [yellow]⚠ Sandbox exec failed, falling back to local: {e}[/yellow]")
        return _run_local(command, workspace_path, timeout)


def _run_local(command: str, workspace_path: str, timeout: int) -> dict:
    """Fallback: run command locally without Docker."""
    try:
        result = subprocess.run(
            command, shell=True, cwd=workspace_path,
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "sandboxed": False,
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "", "stderr": f"Command timed out after {timeout}s",
            "exit_code": -1, "sandboxed": False, "error": "timeout"
        }
    except Exception as e:
        return {
            "stdout": "", "stderr": str(e),
            "exit_code": -1, "sandboxed": False, "error": str(e)
        }


# ─── Container Setup (install deps) ─────────────────────────────────────────

def setup_sandbox_environment(workspace_path: str = None):
    """
    Install project dependencies inside the sandbox container.
    Auto-detects requirements.txt or package.json.
    """
    if not workspace_path:
        workspace_path = os.getenv("FOLDER_PATH", ".")

    container_name = ensure_container(workspace_path)
    if not container_name:
        return "Sandbox not available."

    results = []

    # Python dependencies
    if os.path.exists(os.path.join(workspace_path, "requirements.txt")):
        console.print("  [dim]🐳 Installing Python dependencies in sandbox...[/dim]")
        res = run_in_sandbox("pip install -r /workspace/requirements.txt", workspace_path)
        results.append(f"pip install: exit code {res['exit_code']}")

    # Node dependencies
    if os.path.exists(os.path.join(workspace_path, "package.json")):
        console.print("  [dim]🐳 Installing Node dependencies in sandbox...[/dim]")
        res = run_in_sandbox("npm install", workspace_path)
        results.append(f"npm install: exit code {res['exit_code']}")

    return "\n".join(results) if results else "No dependency files found."


# ─── Cleanup on exit ─────────────────────────────────────────────────────────

def _cleanup_containers():
    """Stop all sandbox containers when the agent exits."""
    for container_name in list(_active_containers.keys()):
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True, timeout=5
            )
        except Exception:
            pass

atexit.register(_cleanup_containers)


# ─── Tool Interface ──────────────────────────────────────────────────────────

def sandbox_status_tool() -> str:
    """Get the current sandbox status."""
    if not is_sandbox_enabled():
        return "Sandbox is DISABLED. Set SANDBOX_ENABLED=true in .env to enable."
    if not is_docker_available():
        return "Sandbox is ENABLED but Docker is not available. Install Docker to use sandboxing."

    active = len(_active_containers)
    lines = [
        f"Sandbox: ENABLED",
        f"Docker: Available",
        f"Active containers: {active}",
        f"Image: {os.getenv('SANDBOX_IMAGE', DEFAULT_IMAGE)}",
        f"Memory limit: {MEMORY_LIMIT}",
        f"CPU limit: {CPU_LIMIT}",
    ]
    for name, path in _active_containers.items():
        lines.append(f"  - {name}: {path}")
    return "\n".join(lines)
