"""GitHub service for repository and branch management in orchestrator.

This service handles GitHub API operations for workspace and sandbox provisioning,
including repository creation from templates and branch management.
"""

import logging
import os
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_DEFAULT_ORG = os.getenv("GITHUB_DEFAULT_ORG", "hckmseduardo")


class GitHubService:
    """Service for GitHub API operations in the orchestrator."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str = None):
        self._token = token or GITHUB_TOKEN

    @property
    def token(self) -> str:
        """Get GitHub token"""
        if not self._token:
            raise ValueError("GitHub token not configured. Set GITHUB_TOKEN environment variable.")
        return self._token

    @property
    def headers(self) -> dict:
        """Get request headers"""
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def auth(self) -> tuple:
        """Get auth tuple for requests (username, token)"""
        return ("", self.token)

    async def create_repo_from_template(
        self,
        template_owner: str,
        template_repo: str,
        new_owner: str,
        new_repo: str,
        description: str = None,
        private: bool = True,
        include_all_branches: bool = False,
    ) -> dict:
        """Create a new repository from a template.

        Args:
            template_owner: Owner of the template repository
            template_repo: Name of the template repository
            new_owner: Owner (user or org) for the new repository
            new_repo: Name for the new repository
            description: Optional description
            private: Whether the repo should be private (default: True)
            include_all_branches: Whether to include all branches (default: False)

        Returns:
            Repository data from GitHub API

        Raises:
            Exception: If repository creation fails
        """
        url = f"{self.BASE_URL}/repos/{template_owner}/{template_repo}/generate"

        payload = {
            "owner": new_owner,
            "name": new_repo,
            "private": private,
            "include_all_branches": include_all_branches,
        }

        if description:
            payload["description"] = description

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self.headers,
                auth=self.auth,
                json=payload,
                timeout=60.0
            )

            if response.status_code == 201:
                repo_data = response.json()
                logger.info(
                    f"Repository created from template: {new_owner}/{new_repo} "
                    f"(from {template_owner}/{template_repo})"
                )
                return repo_data
            else:
                error_detail = response.json().get("message", response.text)
                logger.error(
                    f"Failed to create repository from template: {response.status_code} - {error_detail}"
                )
                raise Exception(f"Failed to create repository: {error_detail}")

    async def get_repository(self, owner: str, repo: str) -> Optional[dict]:
        """Get repository details. Returns None if not found."""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self.headers,
                auth=self.auth,
                timeout=30.0
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                error_detail = response.json().get("message", response.text)
                raise Exception(f"Failed to get repository: {error_detail}")

    async def delete_repository(self, owner: str, repo: str) -> bool:
        """Delete a repository. Returns True if deleted, False if not found."""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers=self.headers,
                auth=self.auth,
                timeout=30.0
            )

            if response.status_code == 204:
                logger.info(f"Repository deleted: {owner}/{repo}")
                return True
            elif response.status_code == 404:
                logger.warning(f"Repository not found for deletion: {owner}/{repo}")
                return False
            else:
                error_detail = response.json().get("message", response.text)
                raise Exception(f"Failed to delete repository: {error_detail}")

    async def get_branch(self, owner: str, repo: str, branch: str) -> Optional[dict]:
        """Get branch details. Returns None if not found."""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/branches/{branch}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self.headers,
                auth=self.auth,
                timeout=30.0
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                error_detail = response.json().get("message", response.text)
                raise Exception(f"Failed to get branch: {error_detail}")

    async def create_branch(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        source_branch: str = "main",
    ) -> dict:
        """Create a new branch from an existing branch.

        Args:
            owner: Repository owner
            repo: Repository name
            branch_name: Name for the new branch
            source_branch: Branch to create from (default: main)

        Returns:
            Reference data from GitHub API
        """
        # First, get the SHA of the source branch
        source = await self.get_branch(owner, repo, source_branch)
        if not source:
            raise Exception(f"Source branch '{source_branch}' not found")

        source_sha = source["commit"]["sha"]

        # Create the new branch reference
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/git/refs"

        payload = {
            "ref": f"refs/heads/{branch_name}",
            "sha": source_sha,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self.headers,
                auth=self.auth,
                json=payload,
                timeout=30.0
            )

            if response.status_code == 201:
                ref_data = response.json()
                logger.info(
                    f"Branch created: {owner}/{repo}:{branch_name} "
                    f"(from {source_branch})"
                )
                return ref_data
            elif response.status_code == 422:
                # Branch already exists
                error_detail = response.json().get("message", response.text)
                if "Reference already exists" in error_detail:
                    logger.warning(f"Branch already exists: {owner}/{repo}:{branch_name}")
                    return {"ref": f"refs/heads/{branch_name}", "already_exists": True}
                raise Exception(f"Failed to create branch: {error_detail}")
            else:
                error_detail = response.json().get("message", response.text)
                raise Exception(f"Failed to create branch: {error_detail}")

    async def delete_branch(
        self,
        owner: str,
        repo: str,
        branch_name: str,
    ) -> bool:
        """Delete a branch. Returns True if deleted, False if not found."""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/git/refs/heads/{branch_name}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers=self.headers,
                auth=self.auth,
                timeout=30.0
            )

            if response.status_code == 204:
                logger.info(f"Branch deleted: {owner}/{repo}:{branch_name}")
                return True
            elif response.status_code == 404:
                logger.warning(f"Branch not found for deletion: {owner}/{repo}:{branch_name}")
                return False
            else:
                error_detail = response.json().get("message", response.text)
                raise Exception(f"Failed to delete branch: {error_detail}")

    async def clone_repository_url(
        self,
        owner: str,
        repo: str,
        use_ssh: bool = False,
    ) -> str:
        """Get the clone URL for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            use_ssh: Use SSH URL instead of HTTPS (default: False)

        Returns:
            Clone URL string with token authentication for HTTPS
        """
        repo_data = await self.get_repository(owner, repo)
        if not repo_data:
            raise Exception(f"Repository not found: {owner}/{repo}")

        if use_ssh:
            return repo_data["ssh_url"]
        else:
            # For HTTPS with token auth
            return repo_data["clone_url"].replace(
                "https://",
                f"https://x-access-token:{self.token}@"
            )


# Singleton instance
github_service = GitHubService()
