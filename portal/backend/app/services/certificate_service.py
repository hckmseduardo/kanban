"""Certificate management service for team provisioning"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from app.config import settings
from app.services.redis_service import redis_service

logger = logging.getLogger(__name__)


class CertificateService:
    """Service for managing SSL certificates for team subdomains"""

    def __init__(self):
        self.cert_base_path = Path("/app/certs")
        self.certbot_script = "/scripts/issue-team-certificate.sh"

    async def issue_certificate(
        self,
        team_slug: str,
        task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Issue a certificate for a team subdomain.

        In development mode: generates self-signed certificate
        In production mode: requests Let's Encrypt certificate

        Args:
            team_slug: The team's URL slug
            task_id: Optional task ID for progress updates

        Returns:
            Dict with certificate info or error
        """
        team_domain = f"{team_slug}.{settings.domain}"
        logger.info(f"Issuing certificate for {team_domain}")

        if task_id:
            await redis_service.update_task_progress(
                task_id=task_id,
                current_step=1,
                total_steps=3,
                step_name="Preparing certificate request",
                message=f"Preparing to issue certificate for {team_domain}"
            )

        try:
            if settings.cert_mode == "development":
                result = await self._issue_self_signed(team_slug, team_domain)
            else:
                result = await self._issue_letsencrypt(team_slug, team_domain, task_id)

            if task_id:
                await redis_service.update_task_progress(
                    task_id=task_id,
                    current_step=3,
                    total_steps=3,
                    step_name="Certificate issued",
                    message=f"Certificate ready for {team_domain}"
                )

            return result

        except Exception as e:
            logger.error(f"Certificate issuance failed for {team_domain}: {e}")
            if task_id:
                await redis_service.fail_task(task_id, str(e))
            return {
                "success": False,
                "error": str(e),
                "team_slug": team_slug,
                "domain": team_domain
            }

    async def _issue_self_signed(
        self,
        team_slug: str,
        team_domain: str
    ) -> Dict[str, Any]:
        """Generate self-signed certificate for development"""
        import os

        cert_dir = self.cert_base_path / "live" / team_domain
        cert_dir.mkdir(parents=True, exist_ok=True)

        cert_path = cert_dir / "fullchain.pem"
        key_path = cert_dir / "privkey.pem"

        # Check if valid certificate already exists
        if cert_path.exists() and key_path.exists():
            if self._is_cert_valid(cert_path, days=30):
                logger.info(f"Valid self-signed certificate exists for {team_domain}")
                return {
                    "success": True,
                    "team_slug": team_slug,
                    "domain": team_domain,
                    "cert_path": str(cert_path),
                    "key_path": str(key_path),
                    "mode": "development",
                    "cached": True
                }

        # Generate new self-signed certificate
        logger.info(f"Generating self-signed certificate for {team_domain}")

        # Generate private key
        key_cmd = ["openssl", "genrsa", "-out", str(key_path), "2048"]
        subprocess.run(key_cmd, check=True, capture_output=True)

        # Generate certificate
        cert_cmd = [
            "openssl", "req", "-new", "-x509", "-days", "365",
            "-key", str(key_path),
            "-out", str(cert_path),
            "-subj", f"/CN={team_domain}",
            "-addext", f"subjectAltName=DNS:{team_domain}"
        ]
        subprocess.run(cert_cmd, check=True, capture_output=True)

        logger.info(f"Self-signed certificate generated for {team_domain}")

        return {
            "success": True,
            "team_slug": team_slug,
            "domain": team_domain,
            "cert_path": str(cert_path),
            "key_path": str(key_path),
            "mode": "development",
            "issued_at": datetime.utcnow().isoformat()
        }

    async def _issue_letsencrypt(
        self,
        team_slug: str,
        team_domain: str,
        task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Request Let's Encrypt certificate via certbot"""

        if task_id:
            await redis_service.update_task_progress(
                task_id=task_id,
                current_step=2,
                total_steps=3,
                step_name="Requesting Let's Encrypt certificate",
                message=f"Contacting Let's Encrypt for {team_domain}"
            )

        # Execute certbot via the certbot container
        # This sends a command to the certificate queue
        cert_task = {
            "type": "cert.issue",
            "task_id": task_id or f"cert-{team_slug}-{datetime.utcnow().timestamp()}",
            "payload": {
                "team_slug": team_slug,
                "domain": team_domain,
                "email": settings.certbot_email,
                "staging": settings.letsencrypt_staging
            }
        }

        # Queue the certificate request
        await redis_service.enqueue_task(
            task_id=cert_task["task_id"],
            task_type="cert.issue",
            payload=cert_task["payload"],
            queue="queue:certificates:high"
        )

        # Wait for certificate to be issued (with timeout)
        timeout = 120  # 2 minutes
        poll_interval = 2

        for _ in range(timeout // poll_interval):
            await asyncio.sleep(poll_interval)

            # Check if certificate file exists
            cert_path = self.cert_base_path / "live" / team_domain / "fullchain.pem"
            key_path = self.cert_base_path / "live" / team_domain / "privkey.pem"

            if cert_path.exists() and key_path.exists():
                logger.info(f"Let's Encrypt certificate ready for {team_domain}")
                return {
                    "success": True,
                    "team_slug": team_slug,
                    "domain": team_domain,
                    "cert_path": str(cert_path),
                    "key_path": str(key_path),
                    "mode": "production",
                    "issued_at": datetime.utcnow().isoformat()
                }

        # Timeout - certificate not ready
        raise TimeoutError(f"Certificate issuance timed out for {team_domain}")

    def _is_cert_valid(self, cert_path: Path, days: int = 30) -> bool:
        """Check if certificate is valid and not expiring soon"""
        try:
            result = subprocess.run(
                ["openssl", "x509", "-checkend", str(days * 86400), "-noout", "-in", str(cert_path)],
                capture_output=True
            )
            return result.returncode == 0
        except Exception:
            return False

    async def revoke_certificate(self, team_slug: str) -> Dict[str, Any]:
        """Revoke and delete certificate for a team"""
        team_domain = f"{team_slug}.{settings.domain}"
        cert_dir = self.cert_base_path / "live" / team_domain

        logger.info(f"Revoking certificate for {team_domain}")

        try:
            if settings.cert_mode == "production":
                # Revoke via certbot
                result = subprocess.run(
                    ["certbot", "revoke", "--cert-name", team_domain, "--non-interactive"],
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    logger.warning(f"Certbot revoke failed: {result.stderr}")

            # Delete certificate files
            if cert_dir.exists():
                import shutil
                shutil.rmtree(cert_dir)
                logger.info(f"Certificate files deleted for {team_domain}")

            return {
                "success": True,
                "team_slug": team_slug,
                "domain": team_domain,
                "revoked": True
            }

        except Exception as e:
            logger.error(f"Certificate revocation failed for {team_domain}: {e}")
            return {
                "success": False,
                "error": str(e),
                "team_slug": team_slug,
                "domain": team_domain
            }

    async def get_certificate_status(self, team_slug: str) -> Dict[str, Any]:
        """Get certificate status for a team"""
        team_domain = f"{team_slug}.{settings.domain}"
        cert_path = self.cert_base_path / "live" / team_domain / "fullchain.pem"

        if not cert_path.exists():
            return {
                "exists": False,
                "team_slug": team_slug,
                "domain": team_domain
            }

        try:
            result = subprocess.run(
                ["openssl", "x509", "-in", str(cert_path), "-noout", "-subject", "-dates", "-issuer"],
                capture_output=True,
                text=True,
                check=True
            )

            lines = result.stdout.strip().split("\n")
            info = {}
            for line in lines:
                if "=" in line:
                    key, value = line.split("=", 1)
                    info[key.strip().lower()] = value.strip()

            return {
                "exists": True,
                "team_slug": team_slug,
                "domain": team_domain,
                "subject": info.get("subject"),
                "issuer": info.get("issuer"),
                "not_before": info.get("notbefore"),
                "not_after": info.get("notafter"),
                "valid": self._is_cert_valid(cert_path, days=1)
            }

        except Exception as e:
            return {
                "exists": True,
                "team_slug": team_slug,
                "domain": team_domain,
                "error": str(e)
            }


# Singleton instance
certificate_service = CertificateService()
