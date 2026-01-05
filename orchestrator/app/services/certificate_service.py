"""Certificate service for SSL certificate provisioning.

This service handles SSL certificate issuance for workspace apps and sandboxes
by executing certbot scripts in the certbot container.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration
CERTBOT_CONTAINER = os.getenv("CERTBOT_CONTAINER", "kanban-certbot")
CERT_MODE = os.getenv("CERT_MODE", "development")


def run_docker_cmd(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a docker command and return the result"""
    cmd = ["docker"] + args
    logger.debug(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


class CertificateService:
    """Service for managing SSL certificates via certbot container."""

    def __init__(self, certbot_container: str = None):
        self.certbot_container = certbot_container or CERTBOT_CONTAINER

    def _parse_cert_info(self, output: str) -> Optional[dict]:
        """Parse certificate info JSON from script output."""
        match = re.search(
            r"---CERT_INFO_START---\s*(\{.*?\})\s*---CERT_INFO_END---",
            output,
            re.DOTALL
        )
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                logger.warning("Failed to parse certificate info JSON")
        return None

    async def issue_team_certificate(self, team_slug: str) -> dict:
        """Issue certificate for a kanban team subdomain.

        Args:
            team_slug: Team identifier (e.g., "acme")

        Returns:
            Certificate info dict with paths and metadata
        """
        logger.info(f"Issuing certificate for team: {team_slug}")

        result = run_docker_cmd([
            "exec", self.certbot_container,
            "/scripts/issue-team-certificate.sh", team_slug
        ], check=False)

        if result.returncode != 0:
            logger.error(f"Certificate issuance failed: {result.stderr}")
            raise RuntimeError(f"Failed to issue certificate for team {team_slug}: {result.stderr}")

        cert_info = self._parse_cert_info(result.stdout)
        if cert_info:
            logger.info(f"Certificate issued for team {team_slug}: {cert_info.get('domain')}")
            return cert_info
        else:
            # Return basic info if parsing failed
            return {
                "team_slug": team_slug,
                "success": True,
                "mode": CERT_MODE,
            }

    async def issue_workspace_certificate(self, workspace_slug: str) -> dict:
        """Issue certificate for a workspace app subdomain.

        Args:
            workspace_slug: Workspace identifier (e.g., "acme")

        Returns:
            Certificate info dict with paths and metadata
        """
        logger.info(f"Issuing certificate for workspace app: {workspace_slug}")

        result = run_docker_cmd([
            "exec", self.certbot_container,
            "/scripts/issue-workspace-certificate.sh", workspace_slug
        ], check=False)

        if result.returncode != 0:
            logger.error(f"Certificate issuance failed: {result.stderr}")
            raise RuntimeError(f"Failed to issue certificate for workspace {workspace_slug}: {result.stderr}")

        cert_info = self._parse_cert_info(result.stdout)
        if cert_info:
            logger.info(f"Certificate issued for workspace {workspace_slug}: {cert_info.get('domain')}")
            return cert_info
        else:
            return {
                "workspace_slug": workspace_slug,
                "success": True,
                "mode": CERT_MODE,
            }

    async def issue_sandbox_certificate(self, full_slug: str) -> dict:
        """Issue certificate for a sandbox subdomain.

        Args:
            full_slug: Full sandbox identifier (e.g., "acme-feature-x")

        Returns:
            Certificate info dict with paths and metadata
        """
        logger.info(f"Issuing certificate for sandbox: {full_slug}")

        result = run_docker_cmd([
            "exec", self.certbot_container,
            "/scripts/issue-sandbox-certificate.sh", full_slug
        ], check=False)

        if result.returncode != 0:
            logger.error(f"Certificate issuance failed: {result.stderr}")
            raise RuntimeError(f"Failed to issue certificate for sandbox {full_slug}: {result.stderr}")

        cert_info = self._parse_cert_info(result.stdout)
        if cert_info:
            logger.info(f"Certificate issued for sandbox {full_slug}: {cert_info.get('domain')}")
            return cert_info
        else:
            return {
                "full_slug": full_slug,
                "success": True,
                "mode": CERT_MODE,
            }

    async def check_certificate_exists(self, domain: str) -> bool:
        """Check if a certificate exists for a domain.

        Args:
            domain: Full domain name

        Returns:
            True if certificate exists
        """
        result = run_docker_cmd([
            "exec", self.certbot_container,
            "test", "-f", f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        ], check=False)

        return result.returncode == 0

    async def get_certificate_info(self, domain: str) -> Optional[dict]:
        """Get certificate information for a domain.

        Args:
            domain: Full domain name

        Returns:
            Certificate info dict or None
        """
        result = run_docker_cmd([
            "exec", self.certbot_container,
            "openssl", "x509", "-in", f"/etc/letsencrypt/live/{domain}/fullchain.pem",
            "-noout", "-subject", "-dates", "-issuer"
        ], check=False)

        if result.returncode != 0:
            return None

        # Parse openssl output
        info = {"domain": domain}
        for line in result.stdout.split("\n"):
            if line.startswith("subject="):
                info["subject"] = line.split("=", 1)[1].strip()
            elif line.startswith("notBefore="):
                info["not_before"] = line.split("=", 1)[1].strip()
            elif line.startswith("notAfter="):
                info["not_after"] = line.split("=", 1)[1].strip()
            elif line.startswith("issuer="):
                info["issuer"] = line.split("=", 1)[1].strip()

        return info

    async def revoke_certificate(self, domain: str) -> bool:
        """Revoke and delete a certificate.

        Args:
            domain: Full domain name

        Returns:
            True if revoked successfully
        """
        logger.info(f"Revoking certificate for: {domain}")

        # In production, use certbot revoke
        if CERT_MODE == "production":
            result = run_docker_cmd([
                "exec", self.certbot_container,
                "certbot", "revoke",
                "--cert-name", domain,
                "--non-interactive",
                "--delete-after-revoke"
            ], check=False)

            if result.returncode != 0:
                logger.warning(f"Certificate revocation failed: {result.stderr}")
                return False
        else:
            # In development, just delete the files
            result = run_docker_cmd([
                "exec", self.certbot_container,
                "rm", "-rf", f"/etc/letsencrypt/live/{domain}"
            ], check=False)

        logger.info(f"Certificate revoked for: {domain}")
        return True


# Singleton instance
certificate_service = CertificateService()
