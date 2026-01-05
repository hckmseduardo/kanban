"""Agent factory service for provisioning sandbox agents.

This service handles the creation and management of dedicated kanban-agents
for sandbox environments. Each sandbox gets its own agent container with
unique webhook credentials.
"""

import asyncio
import logging
import os
import secrets
import subprocess
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

# Configuration
DOMAIN = os.getenv("DOMAIN", "localhost")
PORT = os.getenv("PORT", "4443")
HOST_PROJECT_PATH = os.getenv("HOST_PROJECT_PATH", "/Volumes/dados/projects/kanban")
KANBAN_AGENTS_IMAGE = os.getenv("KANBAN_AGENTS_IMAGE", "kanban-agents:latest")
NETWORK_NAME = os.getenv("NETWORK_NAME", "kanban-global")

# Agent defaults
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
DEFAULT_LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

# Template directory - agents compose templates
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def run_docker_cmd(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a docker command and return the result"""
    cmd = ["docker"] + args
    logger.debug(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def generate_webhook_secret(length: int = 32) -> str:
    """Generate a secure random webhook secret.

    Args:
        length: Length of the secret in bytes (will be hex-encoded to 2x length)

    Returns:
        Hex-encoded random secret string
    """
    return secrets.token_hex(length)


class AgentFactory:
    """Factory for creating and managing sandbox agent containers.

    Each sandbox gets a dedicated agent container that:
    - Connects to the workspace's kanban API
    - Works on a specific git branch
    - Has its own webhook secret for authentication
    """

    def __init__(self):
        """Initialize the agent factory."""
        self.jinja = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))

    async def provision_agent(
        self,
        agent_id: str,
        kanban_api_url: str,
        target_project_path: str,
        sandbox_branch: str,
        webhook_secret: Optional[str] = None,
        llm_provider: str = None,
        llm_model: str = None,
        extra_env: dict = None,
    ) -> dict:
        """Provision a new agent container for a sandbox.

        Args:
            agent_id: Unique identifier for the agent (usually full_slug)
            kanban_api_url: URL of the kanban API for this workspace
            target_project_path: Path to the project directory on the host
            sandbox_branch: Git branch the agent should work on
            webhook_secret: Pre-generated webhook secret (generates new if None)
            llm_provider: LLM provider to use (default: from env)
            llm_model: LLM model to use (default: from env)
            extra_env: Additional environment variables for the agent

        Returns:
            Dict with agent info including webhook_secret and container_name
        """
        container_name = f"kanban-agent-{agent_id}"
        secret = webhook_secret or generate_webhook_secret()

        logger.info(f"Provisioning agent: {container_name}")

        # Prepare environment variables
        env_vars = {
            "KANBAN_API_URL": kanban_api_url,
            "KANBAN_WEBHOOK_SECRET": secret,
            "TARGET_PROJECT_PATH": "/app/target-project",
            "GIT_BRANCH": sandbox_branch,
            "LLM_PROVIDER": llm_provider or DEFAULT_LLM_PROVIDER,
            "LLM_MODEL": llm_model or DEFAULT_LLM_MODEL,
            "OLLAMA_BASE_URL": OLLAMA_BASE_URL,
            "HOST": "0.0.0.0",
            "PORT": "8001",
            "DEBUG": os.getenv("DEBUG", "false"),
        }

        # Add extra environment variables
        if extra_env:
            env_vars.update(extra_env)

        # Build docker run command
        docker_args = [
            "run", "-d",
            "--name", container_name,
            "--network", NETWORK_NAME,
            "--restart", "unless-stopped",
        ]

        # Add environment variables
        for key, value in env_vars.items():
            docker_args.extend(["-e", f"{key}={value}"])

        # Mount volumes
        # Mount target project
        docker_args.extend([
            "-v", f"{target_project_path}:/app/target-project:rw",
        ])

        # Mount Claude CLI credentials from host (for Pro subscription)
        home_dir = os.path.expanduser("~")
        claude_dir = f"{home_dir}/.claude"
        if os.path.exists(claude_dir):
            docker_args.extend(["-v", f"{claude_dir}:/root/.claude:ro"])

        # Mount SSH key for host command execution
        ssh_key_path = f"{home_dir}/.ssh/id_ed25519"
        if os.path.exists(ssh_key_path):
            docker_args.extend(["-v", f"{ssh_key_path}:/root/.ssh/id_ed25519:ro"])

        # Add labels for identification
        docker_args.extend([
            "--label", f"kanban.agent.id={agent_id}",
            "--label", f"kanban.agent.branch={sandbox_branch}",
            "--label", "kanban.type=sandbox-agent",
        ])

        # Add image name
        docker_args.append(KANBAN_AGENTS_IMAGE)

        try:
            # Remove existing container if it exists
            await self.destroy_agent(agent_id)

            # Start the new container
            result = run_docker_cmd(docker_args, check=True)

            if result.returncode != 0:
                raise RuntimeError(f"Failed to start agent container: {result.stderr}")

            container_id = result.stdout.strip()
            logger.info(f"Agent container started: {container_name} ({container_id[:12]})")

            # Wait for container to be healthy
            await self._wait_for_agent_health(container_name)

            return {
                "agent_id": agent_id,
                "container_name": container_name,
                "container_id": container_id,
                "webhook_secret": secret,
                "webhook_url": f"http://{container_name}:8001/webhook",
                "status": "running",
            }

        except Exception as e:
            logger.error(f"Failed to provision agent {agent_id}: {e}")
            raise RuntimeError(f"Agent provisioning failed: {e}") from e

    async def destroy_agent(self, agent_id: str) -> bool:
        """Destroy an agent container.

        Args:
            agent_id: The agent identifier

        Returns:
            True if agent was destroyed, False if it didn't exist
        """
        container_name = f"kanban-agent-{agent_id}"

        logger.info(f"Destroying agent: {container_name}")

        # Stop container
        result = run_docker_cmd(["stop", container_name], check=False)

        # Remove container
        result = run_docker_cmd(["rm", "-f", container_name], check=False)

        if result.returncode == 0:
            logger.info(f"Agent destroyed: {container_name}")
            return True
        else:
            logger.debug(f"Agent {container_name} may not have existed: {result.stderr}")
            return False

    async def restart_agent(
        self,
        agent_id: str,
        regenerate_secret: bool = False,
        kanban_api_url: str = None,
        target_project_path: str = None,
        sandbox_branch: str = None,
    ) -> dict:
        """Restart an agent container.

        Args:
            agent_id: The agent identifier
            regenerate_secret: Whether to generate a new webhook secret
            kanban_api_url: Updated kanban API URL (if changed)
            target_project_path: Updated project path (if changed)
            sandbox_branch: Updated git branch (if changed)

        Returns:
            Dict with updated agent info
        """
        container_name = f"kanban-agent-{agent_id}"

        # Get existing container config
        existing_config = await self.get_agent_info(agent_id)

        if not existing_config:
            raise RuntimeError(f"Agent {agent_id} not found")

        # Determine new secret
        if regenerate_secret:
            new_secret = generate_webhook_secret()
        else:
            # Try to get existing secret from environment
            new_secret = existing_config.get("webhook_secret")
            if not new_secret:
                new_secret = generate_webhook_secret()

        # Re-provision with updated config
        return await self.provision_agent(
            agent_id=agent_id,
            kanban_api_url=kanban_api_url or existing_config.get("kanban_api_url", ""),
            target_project_path=target_project_path or existing_config.get("target_project_path", ""),
            sandbox_branch=sandbox_branch or existing_config.get("sandbox_branch", "main"),
            webhook_secret=new_secret,
        )

    async def get_agent_info(self, agent_id: str) -> Optional[dict]:
        """Get information about an agent container.

        Args:
            agent_id: The agent identifier

        Returns:
            Dict with agent info, or None if agent doesn't exist
        """
        container_name = f"kanban-agent-{agent_id}"

        result = run_docker_cmd([
            "inspect",
            "--format",
            '{"status": "{{.State.Status}}", "running": {{.State.Running}}}',
            container_name,
        ], check=False)

        if result.returncode != 0:
            return None

        try:
            import json
            info = json.loads(result.stdout.strip())
            info["agent_id"] = agent_id
            info["container_name"] = container_name
            return info
        except Exception:
            return None

    async def list_agents(self, workspace_slug: str = None) -> list:
        """List all sandbox agent containers.

        Args:
            workspace_slug: Optional filter by workspace

        Returns:
            List of agent container info dicts
        """
        filter_args = ["--filter", "label=kanban.type=sandbox-agent"]

        if workspace_slug:
            filter_args.extend(["--filter", f"name=kanban-agent-{workspace_slug}-"])

        result = run_docker_cmd([
            "ps", "-a",
            *filter_args,
            "--format", '{"name": "{{.Names}}", "status": "{{.Status}}", "state": "{{.State}}"}',
        ], check=False)

        if result.returncode != 0:
            return []

        agents = []
        for line in result.stdout.strip().split("\n"):
            if line:
                try:
                    import json
                    agent = json.loads(line)
                    # Extract agent_id from container name
                    name = agent.get("name", "")
                    if name.startswith("kanban-agent-"):
                        agent["agent_id"] = name[len("kanban-agent-"):]
                    agents.append(agent)
                except Exception:
                    continue

        return agents

    async def _wait_for_agent_health(
        self,
        container_name: str,
        timeout: int = 30,
        interval: float = 1.0,
    ):
        """Wait for an agent container to become healthy.

        Args:
            container_name: Name of the container to check
            timeout: Maximum seconds to wait
            interval: Seconds between checks

        Raises:
            RuntimeError: If container doesn't become healthy in time
        """
        logger.info(f"Waiting for agent {container_name} to become healthy...")

        for i in range(int(timeout / interval)):
            result = run_docker_cmd([
                "inspect",
                "--format", "{{.State.Status}}",
                container_name,
            ], check=False)

            if result.returncode == 0:
                status = result.stdout.strip()
                if status == "running":
                    logger.info(f"Agent {container_name} is running")
                    return
                elif status in ("exited", "dead"):
                    # Get logs for debugging
                    logs = run_docker_cmd(["logs", "--tail", "50", container_name], check=False)
                    logger.error(f"Agent container exited. Logs: {logs.stdout}")
                    raise RuntimeError(f"Agent container {container_name} exited unexpectedly")

            await asyncio.sleep(interval)

        raise RuntimeError(f"Agent {container_name} failed to start within {timeout}s")

    async def provision_agent_from_template(
        self,
        agent_id: str,
        workspace_slug: str,
        sandbox_slug: str,
        kanban_api_url: str,
        target_project_path: str,
        sandbox_branch: str,
        webhook_secret: Optional[str] = None,
    ) -> dict:
        """Provision an agent using a Docker Compose template.

        This method uses Jinja2 templates for more complex agent configurations.

        Args:
            agent_id: Unique identifier for the agent
            workspace_slug: Workspace this agent belongs to
            sandbox_slug: Sandbox this agent is for
            kanban_api_url: URL of the kanban API
            target_project_path: Path to the project on the host
            sandbox_branch: Git branch to work on
            webhook_secret: Pre-generated webhook secret

        Returns:
            Dict with agent info
        """
        secret = webhook_secret or generate_webhook_secret()
        container_name = f"kanban-agent-{agent_id}"

        # Render template
        try:
            template = self.jinja.get_template("agent-compose.yml.j2")
        except Exception:
            # Fall back to direct provisioning if template not found
            logger.warning("Agent template not found, using direct provisioning")
            return await self.provision_agent(
                agent_id=agent_id,
                kanban_api_url=kanban_api_url,
                target_project_path=target_project_path,
                sandbox_branch=sandbox_branch,
                webhook_secret=secret,
            )

        compose_content = template.render(
            agent_id=agent_id,
            workspace_slug=workspace_slug,
            sandbox_slug=sandbox_slug,
            container_name=container_name,
            kanban_api_url=kanban_api_url,
            webhook_secret=secret,
            target_project_path=target_project_path,
            sandbox_branch=sandbox_branch,
            network_name=NETWORK_NAME,
            kanban_agents_image=KANBAN_AGENTS_IMAGE,
            llm_provider=DEFAULT_LLM_PROVIDER,
            llm_model=DEFAULT_LLM_MODEL,
            ollama_base_url=OLLAMA_BASE_URL,
        )

        # Write compose file
        compose_file = Path(f"/tmp/agent-{agent_id}-compose.yml")
        compose_file.write_text(compose_content)

        try:
            # Stop existing agent if any
            await self.destroy_agent(agent_id)

            # Start using docker compose
            project_name = f"kanban-agent-{agent_id}"
            result = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "-p", project_name, "up", "-d"],
                capture_output=True,
                text=True,
                check=True,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Failed to start agent: {result.stderr}")

            # Wait for health
            await self._wait_for_agent_health(container_name)

            return {
                "agent_id": agent_id,
                "container_name": container_name,
                "webhook_secret": secret,
                "webhook_url": f"http://{container_name}:8001/webhook",
                "status": "running",
            }

        finally:
            # Clean up compose file
            if compose_file.exists():
                compose_file.unlink()

    async def get_agent_logs(
        self,
        agent_id: str,
        tail: int = 100,
    ) -> str:
        """Get logs from an agent container.

        Args:
            agent_id: The agent identifier
            tail: Number of lines to retrieve

        Returns:
            Log output string
        """
        container_name = f"kanban-agent-{agent_id}"

        result = run_docker_cmd([
            "logs",
            "--tail", str(tail),
            container_name,
        ], check=False)

        if result.returncode != 0:
            return f"Failed to get logs: {result.stderr}"

        return result.stdout + result.stderr


# Singleton instance
agent_factory = AgentFactory()
