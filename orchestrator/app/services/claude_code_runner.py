"""Claude Code subprocess runner for on-demand AI agents.

This service spawns Claude Code CLI processes to handle card tasks,
streaming output for real-time progress updates.
"""

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result from a Claude Code agent execution."""
    success: bool
    output: str
    error: Optional[str] = None
    files_modified: list = None
    commits: list = None
    duration_seconds: float = 0

    def __post_init__(self):
        if self.files_modified is None:
            self.files_modified = []
        if self.commits is None:
            self.commits = []


class ClaudeCodeRunner:
    """Runs Claude Code CLI as subprocess for agent tasks.

    Uses Pro subscription via ~/.claude credentials.
    Runs in sandbox directory with restricted access.
    Streams output for real-time card updates.
    """

    # Default allowed tools per agent type
    DEFAULT_TOOLS = [
        "Read", "Write", "Edit", "Glob", "Grep", "Bash"
    ]

    # Agent-specific tool configurations
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

    # Default timeouts per agent type (seconds)
    AGENT_TIMEOUTS = {
        "developer": 900,  # 15 minutes for complex implementations
        "architect": 600,  # 10 minutes for design
        "reviewer": 300,   # 5 minutes for review
        "qa": 600,         # 10 minutes for testing
        "product_owner": 300,
        "release": 300,
        "triage": 180,
        "support_analyst": 300,
    }

    def __init__(self):
        """Initialize the Claude Code runner."""
        self.claude_binary = self._find_claude_binary()

    def _find_claude_binary(self) -> str:
        """Find the Claude Code CLI binary."""
        # Check common locations
        locations = [
            "/usr/local/bin/claude",
            "/opt/homebrew/bin/claude",
            os.path.expanduser("~/.local/bin/claude"),
            os.path.expanduser("~/.npm-global/bin/claude"),
        ]

        for path in locations:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

        # Try finding in PATH
        try:
            result = subprocess.run(
                ["which", "claude"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass

        # Fall back to assuming it's in PATH
        return "claude"

    def get_tools_for_agent(self, agent_type: str) -> list:
        """Get allowed tools for an agent type."""
        return self.AGENT_TOOLS.get(agent_type, self.DEFAULT_TOOLS)

    def get_timeout_for_agent(self, agent_type: str) -> int:
        """Get timeout in seconds for an agent type."""
        return self.AGENT_TIMEOUTS.get(agent_type, 600)

    async def run(
        self,
        prompt: str,
        working_dir: str,
        agent_type: str = "developer",
        allowed_tools: list = None,
        env: dict = None,
        on_output: Callable[[str], None] = None,
        timeout: int = None,
        system_prompt: str = None,
    ) -> AgentResult:
        """
        Spawn Claude Code CLI subprocess and run a prompt.

        Args:
            prompt: The task prompt for Claude Code
            working_dir: Directory to run in (sandbox project path)
            agent_type: Type of agent (determines tools and timeout)
            allowed_tools: Override allowed tools list
            env: Additional environment variables
            on_output: Callback for streaming output
            timeout: Override timeout in seconds
            system_prompt: Optional system prompt override

        Returns:
            AgentResult with success status and output
        """
        import time
        start_time = time.time()

        # Resolve tools and timeout
        tools = allowed_tools or self.get_tools_for_agent(agent_type)
        timeout = timeout or self.get_timeout_for_agent(agent_type)

        # Build command
        cmd = [self.claude_binary]

        # Add prompt
        cmd.extend(["-p", prompt])

        # Add allowed tools
        if tools:
            cmd.extend(["--allowedTools", ",".join(tools)])

        # Skip permission prompts in automated mode
        cmd.append("--dangerouslySkipPermissions")

        # Output format for parsing
        cmd.extend(["--output-format", "stream-json"])

        # Add system prompt if provided
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        # Prepare environment
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        # Ensure working directory exists
        work_path = Path(working_dir)
        if not work_path.exists():
            logger.error(f"Working directory does not exist: {working_dir}")
            return AgentResult(
                success=False,
                output="",
                error=f"Working directory does not exist: {working_dir}",
                duration_seconds=time.time() - start_time
            )

        logger.info(f"Starting Claude Code: agent={agent_type}, dir={working_dir}")
        logger.debug(f"Command: {' '.join(cmd)}")

        output_lines = []
        error_lines = []
        files_modified = []
        commits = []

        try:
            # Create subprocess
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(work_path),
                env=process_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Stream output with timeout
            async def read_stream(stream, callback, lines_list):
                async for line in stream:
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    lines_list.append(decoded)

                    # Parse JSON output for progress
                    if decoded.startswith("{"):
                        try:
                            data = json.loads(decoded)
                            if data.get("type") == "tool_use":
                                tool_name = data.get("tool", {}).get("name", "")
                                if tool_name in ("Write", "Edit"):
                                    file_path = data.get("tool", {}).get("input", {}).get("file_path")
                                    if file_path and file_path not in files_modified:
                                        files_modified.append(file_path)
                            elif data.get("type") == "text":
                                text = data.get("text", "")
                                if callback:
                                    callback(text)
                        except json.JSONDecodeError:
                            pass
                    elif callback:
                        callback(decoded)

            try:
                # Run with timeout
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

            if not success and not error_msg:
                error_msg = f"Claude Code exited with code {proc.returncode}"

            duration = time.time() - start_time
            logger.info(
                f"Claude Code completed: success={success}, "
                f"duration={duration:.1f}s, files={len(files_modified)}"
            )

            return AgentResult(
                success=success,
                output="\n".join(output_lines),
                error=error_msg if not success else None,
                files_modified=files_modified,
                commits=commits,
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

    async def run_with_progress(
        self,
        prompt: str,
        working_dir: str,
        agent_type: str,
        progress_callback: Callable[[str, int], None],
        **kwargs
    ) -> AgentResult:
        """
        Run Claude Code with progress reporting.

        Args:
            prompt: The task prompt
            working_dir: Directory to run in
            agent_type: Type of agent
            progress_callback: Callback(message, percentage)
            **kwargs: Additional arguments for run()
        """
        output_buffer = []
        total_lines = 0

        def on_output(line: str):
            nonlocal total_lines
            output_buffer.append(line)
            total_lines += 1

            # Estimate progress based on output
            # This is a rough heuristic
            estimated_progress = min(90, total_lines * 2)
            progress_callback(line[:100], estimated_progress)

        progress_callback("Starting agent...", 0)

        result = await self.run(
            prompt=prompt,
            working_dir=working_dir,
            agent_type=agent_type,
            on_output=on_output,
            **kwargs
        )

        if result.success:
            progress_callback("Completed successfully", 100)
        else:
            progress_callback(f"Failed: {result.error}", 100)

        return result


# Singleton instance
claude_runner = ClaudeCodeRunner()
