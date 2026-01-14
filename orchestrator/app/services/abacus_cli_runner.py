"""Abacus CLI subprocess runner for on-demand AI agents.

This service executes Abacus CLI on the host machine via SSH,
allowing use of local Abacus authentication (API key or login).
"""

import asyncio
import logging
import os
import shlex
from typing import Callable

from app.services.claude_code_runner import AgentResult

logger = logging.getLogger(__name__)

# SSH configuration for executing Abacus CLI on host
SSH_HOST = os.getenv("SSH_HOST", "host.docker.internal")
SSH_USER = os.getenv("SSH_USER", "")
SSH_ABACUS_PATH = os.getenv("SSH_ABACUS_PATH", "~/.local/bin/abacus")
ABACUS_CLI_ARGS = os.getenv("ABACUS_CLI_ARGS", "exec")
ABACUS_MODEL_FLAG = os.getenv("ABACUS_MODEL_FLAG", "--model")


class AbacusCliRunner:
    """Runs Abacus CLI on host via SSH for agent tasks."""

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
        self.ssh_host = SSH_HOST
        self.ssh_user = SSH_USER
        self.abacus_path = SSH_ABACUS_PATH
        self.cli_args = ABACUS_CLI_ARGS
        self.model_flag = ABACUS_MODEL_FLAG

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

    def get_timeout_for_agent(self, agent_type: str) -> int:
        """Get timeout in seconds for an agent type."""
        return self.AGENT_TIMEOUTS.get(agent_type, 600)

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
        model: str = None,
    ) -> AgentResult:
        """Execute Abacus CLI on host via SSH."""
        import time
        start_time = time.time()

        if not self.ssh_user:
            logger.error("SSH_USER not configured for Abacus CLI execution")
            return AgentResult(
                success=False,
                output="",
                error="SSH_USER environment variable not set. Configure it to use Abacus CLI on host.",
                duration_seconds=time.time() - start_time,
            )

        timeout = timeout or self.get_timeout_for_agent(agent_type)

        escaped_prompt = prompt.replace("'", "'\\''")

        remote_cmd_parts = [self.abacus_path]
        if self.cli_args:
            remote_cmd_parts.extend(shlex.split(self.cli_args))
        if model and self.model_flag:
            remote_cmd_parts.extend([self.model_flag, model])
        remote_cmd_parts.append(f"'{escaped_prompt}'")

        env = dict(env or {})
        if "PATH" not in env and self.abacus_path.startswith("/"):
            cli_dir = os.path.dirname(self.abacus_path)
            if cli_dir:
                default_path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
                env["PATH"] = f"{cli_dir}:{default_path}"

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

        if working_dir and not working_dir.startswith("/app"):
            remote_cmd = f"cd '{working_dir}' && {remote_cmd_core}"
        else:
            remote_cmd = remote_cmd_core

        ssh_cmd = self._build_ssh_command(remote_cmd)

        logger.info(f"Executing Abacus via SSH: agent={agent_type}, host={self.ssh_host}")
        logger.info(f"SSH command: {' '.join(ssh_cmd[:5])}...")
        remote_cmd_log = " ".join(remote_cmd_parts)
        logger.debug(f"Remote command: {remote_cmd_log[:200]}...")

        output_lines = []
        error_lines = []
        files_modified = []

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

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
                    timeout=timeout,
                )

                await proc.wait()
            except asyncio.TimeoutError:
                logger.warning(f"Abacus CLI timed out after {timeout}s")
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
                    duration_seconds=time.time() - start_time,
                )

            success = proc.returncode == 0
            error_msg = "\n".join(error_lines) if error_lines else None

            if not success:
                logger.error(f"Abacus CLI failed with code {proc.returncode}")
                if error_lines:
                    logger.error(f"Stderr: {error_msg[:500]}")
                if output_lines:
                    logger.error(f"Stdout (first 500 chars): {' '.join(output_lines)[:500]}")
                if not error_msg:
                    error_msg = f"Abacus CLI exited with code {proc.returncode}"

            duration = time.time() - start_time
            logger.info(
                f"Abacus CLI completed: success={success}, "
                f"duration={duration:.1f}s"
            )

            return AgentResult(
                success=success,
                output="\n".join(output_lines),
                error=error_msg if not success else None,
                files_modified=files_modified,
                duration_seconds=duration,
            )
        except Exception as e:
            logger.error(f"Abacus CLI execution failed: {e}")
            return AgentResult(
                success=False,
                output="\n".join(output_lines),
                error=str(e),
                files_modified=files_modified,
                duration_seconds=time.time() - start_time,
            )


abacus_runner = AbacusCliRunner()
