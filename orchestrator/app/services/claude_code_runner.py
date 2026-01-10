"""Claude Code subprocess runner for on-demand AI agents.

This service executes Claude Code CLI on the host machine via SSH,
allowing use of the Pro subscription for reduced costs.
"""

import asyncio
import json
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# SSH configuration for executing Claude CLI on host
SSH_HOST = os.getenv("SSH_HOST", "host.docker.internal")
SSH_USER = os.getenv("SSH_USER", "")
SSH_CLAUDE_PATH = os.getenv("SSH_CLAUDE_PATH", "~/.local/bin/claude")


@dataclass
class AgentResult:
    """Result from a Claude Code agent execution."""
    success: bool
    output: str
    error: Optional[str] = None
    files_modified: list = None
    commits: list = None
    git_dirty: bool = False
    commit_hash: Optional[str] = None
    push_attempted: bool = False
    push_success: bool = False
    commit_error: Optional[str] = None
    push_error: Optional[str] = None
    push_needed: bool = False
    ahead_count: int = 0
    duration_seconds: float = 0

    def __post_init__(self):
        if self.files_modified is None:
            self.files_modified = []
        if self.commits is None:
            self.commits = []


class ClaudeCodeRunner:
    """Runs Claude Code CLI on host via SSH for agent tasks.

    Uses Pro subscription via host's ~/.claude credentials.
    Executes commands via SSH to the host machine.
    """

    # Tool profiles for simplified configuration
    TOOL_PROFILES = {
        "readonly": ["Read", "Glob", "Grep"],
        "developer": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        "full-access": ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Task", "WebFetch"],
    }

    # Legacy: Agent-specific tool configurations
    AGENT_TOOLS = {
        "developer": ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Task"],
        "architect": ["Read", "Glob", "Grep", "Bash", "Task"],
        "reviewer": ["Read", "Glob", "Grep", "Bash"],
        "qa": ["Read", "Glob", "Grep", "Bash"],
        "product_owner": ["Read", "Glob", "Grep"],
        "release": ["Read", "Glob", "Grep", "Bash"],
        "triage": ["Read", "Glob", "Grep"],
        "support_analyst": ["Read", "Glob", "Grep", "Bash"],
    }

    DEFAULT_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]

    AGENT_TIMEOUTS = {
        "developer": 900,
        "architect": 600,
        "reviewer": 300,
        "qa": 600,
        "product_owner": 300,
        "release": 300,
        "triage": 180,
        "support_analyst": 300,
    }

    def __init__(self):
        """Initialize the Claude Code runner."""
        self.ssh_host = SSH_HOST
        self.ssh_user = SSH_USER
        self.claude_path = SSH_CLAUDE_PATH

    def _build_ssh_command(self, remote_cmd: str) -> list:
        """Build SSH command to execute on host."""
        ssh_cmd = ["ssh"]

        # Add strict host key checking disable for development
        ssh_cmd.extend(["-o", "StrictHostKeyChecking=no"])
        ssh_cmd.extend(["-o", "UserKnownHostsFile=/dev/null"])
        ssh_cmd.extend(["-o", "LogLevel=ERROR"])

        # Build target
        if self.ssh_user:
            target = f"{self.ssh_user}@{self.ssh_host}"
        else:
            target = self.ssh_host

        ssh_cmd.append(target)
        ssh_cmd.append(remote_cmd)

        return ssh_cmd

    def get_tools_for_profile(self, tool_profile: str) -> list:
        """Get allowed tools for a tool profile."""
        return self.TOOL_PROFILES.get(tool_profile, self.DEFAULT_TOOLS)

    def get_tools_for_agent(self, agent_type: str) -> list:
        """Legacy: Get allowed tools for an agent type."""
        return self.AGENT_TOOLS.get(agent_type, self.DEFAULT_TOOLS)

    def get_timeout_for_agent(self, agent_type: str) -> int:
        """Legacy: Get timeout in seconds for an agent type."""
        return self.AGENT_TIMEOUTS.get(agent_type, 600)

    async def run_ssh_command(self, remote_cmd: str, timeout: int = 60) -> tuple[int, str, str]:
        """Run a shell command on the host via SSH."""
        if not self.ssh_user:
            return 1, "", "SSH_USER environment variable not set."

        ssh_cmd = self._build_ssh_command(remote_cmd)
        logger.debug(f"SSH command: {' '.join(ssh_cmd[:5])}...")

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                return 1, "", f"SSH command timed out after {timeout}s"

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            return proc.returncode, stdout_text, stderr_text
        except Exception as e:
            return 1, "", f"SSH command failed: {e}"

    async def run(
        self,
        prompt: str,
        working_dir: str,
        agent_type: str = "developer",
        tool_profile: str = None,
        allowed_tools: list = None,
        env: dict = None,
        on_output: Callable[[str], None] = None,
        timeout: int = None,
        system_prompt: str = None,
        session_id: str = None,
    ) -> AgentResult:
        """
        Execute Claude Code CLI on host via SSH.

        Args:
            prompt: The task prompt for Claude Code
            working_dir: Directory to run in on the host
            agent_type: Type of agent (legacy fallback for tools/timeout)
            tool_profile: Tool profile from agent config
            allowed_tools: Override allowed tools list
            env: Additional environment variables
            on_output: Callback for streaming output
            timeout: Override timeout in seconds
            system_prompt: Optional system prompt override
            session_id: Optional Claude session ID to reuse across runs

        Returns:
            AgentResult with success status and output
        """
        import time
        start_time = time.time()

        # Check SSH configuration
        if not self.ssh_user:
            logger.error("SSH_USER not configured for Claude CLI execution")
            return AgentResult(
                success=False,
                output="",
                error="SSH_USER environment variable not set. Configure it to use Claude CLI on host.",
                duration_seconds=time.time() - start_time
            )

        # Resolve tools
        if allowed_tools:
            tools = allowed_tools
        elif tool_profile:
            tools = self.get_tools_for_profile(tool_profile)
        else:
            tools = self.get_tools_for_agent(agent_type)

        # Resolve timeout
        timeout = timeout or self.get_timeout_for_agent(agent_type)

        # Escape the prompt for shell
        escaped_prompt = prompt.replace("'", "'\\''")

        # Build the remote Claude command
        remote_cmd_parts = [self.claude_path]
        remote_cmd_parts.extend(["-p", f"'{escaped_prompt}'"])

        if tools:
            remote_cmd_parts.extend(["--allowedTools", ",".join(tools)])

        if session_id:
            remote_cmd_parts.extend(["--session-id", session_id])

        remote_cmd_parts.append("--dangerously-skip-permissions")

        # Use text output for simpler parsing
        remote_cmd_parts.extend(["--output-format", "text"])

        if system_prompt:
            escaped_system = system_prompt.replace("'", "'\\''")
            remote_cmd_parts.extend(["--system-prompt", f"'{escaped_system}'"])

        env_prefix = ""
        if env:
            env_parts = []
            for key, value in env.items():
                if value is None or value == "":
                    continue
                env_parts.append(f"{key}={shlex.quote(str(value))}")
            if env_parts:
                env_prefix = " ".join(env_parts) + " "

        remote_cmd_core = env_prefix + " ".join(remote_cmd_parts)

        # If working directory specified, cd into it first
        if working_dir and not working_dir.startswith("/app"):
            remote_cmd = f"cd '{working_dir}' && {remote_cmd_core}"
        else:
            remote_cmd = remote_cmd_core

        # Build SSH command
        ssh_cmd = self._build_ssh_command(remote_cmd)

        logger.info(f"Executing Claude via SSH: agent={agent_type}, host={self.ssh_host}")
        logger.info(f"SSH command: {' '.join(ssh_cmd[:5])}...")
        remote_cmd_log = " ".join(remote_cmd_parts)
        logger.debug(f"Remote command: {remote_cmd_log[:200]}...")

        output_lines = []
        error_lines = []
        files_modified = []

        try:
            # Create subprocess
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Stream output with timeout
            async def read_stream(stream, callback, lines_list):
                async for line in stream:
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    lines_list.append(decoded)
                    if callback:
                        callback(decoded)

            try:
                stdout_task = asyncio.create_task(
                    read_stream(proc.stdout, on_output, output_lines)
                )
                stderr_task = asyncio.create_task(
                    read_stream(proc.stderr, None, error_lines)
                )

                await asyncio.wait_for(
                    asyncio.gather(stdout_task, stderr_task),
                    timeout=timeout
                )

                await proc.wait()

            except asyncio.TimeoutError:
                logger.warning(f"Claude Code timed out after {timeout}s")
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()

                return AgentResult(
                    success=False,
                    output="\n".join(output_lines),
                    error=f"Agent timed out after {timeout} seconds",
                    files_modified=files_modified,
                    duration_seconds=time.time() - start_time
                )

            # Check result
            success = proc.returncode == 0
            error_msg = "\n".join(error_lines) if error_lines else None

            if not success:
                # Log detailed error info
                logger.error(f"Claude Code failed with code {proc.returncode}")
                if error_lines:
                    logger.error(f"Stderr: {error_msg[:500]}")
                if output_lines:
                    logger.error(f"Stdout (first 500 chars): {' '.join(output_lines)[:500]}")
                if not error_msg:
                    error_msg = f"Claude Code exited with code {proc.returncode}"

            duration = time.time() - start_time
            logger.info(
                f"Claude Code completed: success={success}, "
                f"duration={duration:.1f}s"
            )

            return AgentResult(
                success=success,
                output="\n".join(output_lines),
                error=error_msg if not success else None,
                files_modified=files_modified,
                duration_seconds=duration
            )

        except Exception as e:
            logger.error(f"Claude Code execution failed: {e}")
            return AgentResult(
                success=False,
                output="\n".join(output_lines),
                error=str(e),
                files_modified=files_modified,
                duration_seconds=time.time() - start_time
            )


# Singleton instance
claude_runner = ClaudeCodeRunner()
