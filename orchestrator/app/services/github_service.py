"""GitHub service for repository and branch management in orchestrator.

This service handles GitHub API operations for workspace and sandbox provisioning,
including repository creation from templates and branch management.
"""

import logging
import os
from typing import Optional
import httpx

from .keyvault_service import keyvault_service

logger = logging.getLogger(__name__)

# Configuration
GITHUB_DEFAULT_ORG = os.getenv("GITHUB_DEFAULT_ORG", "hckmseduardo")


class GitHubService:
    """Service for GitHub API operations in the orchestrator."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str = None):
        self._token = token
        self._cached_token = None

    @property
    def token(self) -> str:
        """Get GitHub token from environment or Key Vault."""
        if self._token:
            return self._token
        if self._cached_token:
            return self._cached_token

        # Prefer environment variable (more easily updated than Key Vault)
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            # Fall back to Key Vault
            token = keyvault_service.get_github_token()
        if not token:
            raise ValueError(
                "GitHub token not configured. "
                "Set GITHUB_TOKEN environment variable or 'github-pat' in Azure Key Vault."
            )
        self._cached_token = token
        return token

    @property
    def headers(self) -> dict:
        """Get request headers with authorization (uses default token)"""
        return self._get_headers()

    def _get_headers(self, token: str = None) -> dict:
        """Get request headers with authorization.

        Args:
            token: Optional token to use. If not provided, uses default token.
        """
        auth_token = token if token else self.token
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"token {auth_token}",
        }

    def get_effective_token(self, custom_token: str = None) -> str:
        """Get the effective token to use.

        Args:
            custom_token: Optional custom token. If provided, uses this.
                         Otherwise falls back to default token.

        Returns:
            The token to use for GitHub API operations.
        """
        return custom_token if custom_token else self.token

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

    async def get_repository(
        self, owner: str, repo: str, token: str = None
    ) -> Optional[dict]:
        """Get repository details. Returns None if not found.

        Args:
            owner: Repository owner
            repo: Repository name
            token: Optional custom token. If not provided, uses default.
        """
        url = f"{self.BASE_URL}/repos/{owner}/{repo}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self._get_headers(token),
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

    async def get_branch(self, owner: str, repo: str, branch: str, token: str = None) -> Optional[dict]:
        """Get branch details. Returns None if not found.

        Args:
            token: Optional custom token. Uses default if not provided.
        """
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/branches/{branch}"
        headers = self._get_headers(token)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=headers,
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
        token: str = None,
    ) -> dict:
        """Create a new branch from an existing branch.

        Args:
            owner: Repository owner
            repo: Repository name
            branch_name: Name for the new branch
            source_branch: Branch to create from (default: main)
            token: Optional custom token. Uses default if not provided.

        Returns:
            Reference data from GitHub API
        """
        # First, get the SHA of the source branch
        source = await self.get_branch(owner, repo, source_branch, token=token)
        if not source:
            raise Exception(f"Source branch '{source_branch}' not found")

        source_sha = source["commit"]["sha"]

        # Create the new branch reference
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/git/refs"
        headers = self._get_headers(token)

        payload = {
            "ref": f"refs/heads/{branch_name}",
            "sha": source_sha,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
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

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        head: Optional[str] = None,
        base: Optional[str] = None,
    ) -> list:
        """List pull requests with optional filters."""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls"
        params = {"state": state}
        if head:
            params["head"] = head if ":" in head else f"{owner}:{head}"
        if base:
            params["base"] = base

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self.headers,
                params=params,
                timeout=30.0
            )

            if response.status_code == 200:
                return response.json()
            error_detail = response.json().get("message", response.text)
            raise Exception(f"Failed to list pull requests: {error_detail}")

    async def get_open_pull_request(
        self,
        owner: str,
        repo: str,
        head: str,
        base: str = "main",
    ) -> Optional[dict]:
        """Get an open PR for the head/base pair if it exists."""
        prs = await self.list_pull_requests(owner=owner, repo=repo, state="open", head=head, base=base)
        return prs[0] if prs else None

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        head: str,
        base: str = "main",
        title: str = None,
        body: str = None,
    ) -> dict:
        """Create a pull request (or return existing open PR)."""
        existing = await self.get_open_pull_request(owner, repo, head, base)
        if existing:
            return existing

        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls"
        payload = {
            "title": title or f"Merge {head} into {base}",
            "head": head,
            "base": base,
            "body": body or "",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=30.0
            )

            if response.status_code == 201:
                return response.json()
            if response.status_code == 422:
                # PR may already exist, re-check open PRs
                existing = await self.get_open_pull_request(owner, repo, head, base)
                if existing:
                    return existing
            error_detail = response.json().get("message", response.text)
            raise Exception(f"Failed to create pull request: {error_detail}")

    async def approve_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str = None,
    ) -> dict:
        """Approve a pull request via review."""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls/{pull_number}/reviews"
        payload = {"event": "APPROVE"}
        if body:
            payload["body"] = body

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=30.0
            )

            if response.status_code in [200, 201]:
                return response.json()
            error_detail = response.json().get("message", response.text)
            raise Exception(f"Failed to approve pull request: {error_detail}")

    async def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        merge_method: str = "merge",
    ) -> dict:
        """Merge a pull request."""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls/{pull_number}/merge"
        payload = {"merge_method": merge_method}

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers=self.headers,
                json=payload,
                timeout=30.0
            )

            if response.status_code == 200:
                return response.json()
            error_detail = response.json().get("message", response.text)
            raise Exception(f"Failed to merge pull request: {error_detail}")

    async def clone_repository_url(
        self,
        owner: str,
        repo: str,
        use_ssh: bool = False,
        token: str = None,
    ) -> str:
        """Get the clone URL for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            use_ssh: Use SSH URL instead of HTTPS (default: False)
            token: Optional custom token for authentication.
                   If not provided, uses default token.

        Returns:
            Clone URL string with token authentication for HTTPS
        """
        effective_token = self.get_effective_token(token)
        repo_data = await self.get_repository(owner, repo, token=token)
        if not repo_data:
            raise Exception(f"Repository not found: {owner}/{repo}")

        if use_ssh:
            return repo_data["ssh_url"]
        else:
            # For HTTPS with token auth
            return repo_data["clone_url"].replace(
                "https://",
                f"https://x-access-token:{effective_token}@"
            )


# Singleton instance
github_service = GitHubService()
