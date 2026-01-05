"""Database cloning service for PostgreSQL database replication.

This service handles cloning PostgreSQL databases from workspace to sandbox environments.
It uses pg_dump/pg_restore via Docker exec to clone databases between containers.
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
TEMP_DUMP_DIR = Path("/tmp/db_dumps")


def run_docker_cmd(args: list[str], check: bool = True, binary: bool = False) -> subprocess.CompletedProcess:
    """Run a docker command and return the result.

    Args:
        args: Docker command arguments
        check: Whether to raise on non-zero return code
        binary: If True, return raw bytes instead of decoded text
    """
    cmd = ["docker"] + args
    logger.debug(f"Running: {' '.join(cmd)}")
    if binary:
        return subprocess.run(cmd, capture_output=True, check=check)
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


class DatabaseCloner:
    """Service for cloning PostgreSQL databases between containers.

    This service is used to create sandbox databases by cloning from workspace databases.
    It supports full database cloning with all tables, sequences, and data.
    """

    def __init__(self):
        """Initialize the database cloner service."""
        self._ensure_temp_dir()

    def _ensure_temp_dir(self):
        """Ensure the temporary dump directory exists."""
        TEMP_DUMP_DIR.mkdir(parents=True, exist_ok=True)

    async def clone_database(
        self,
        source_container: str,
        source_db: str,
        target_container: str,
        target_db: str,
        postgres_user: str = None,
        postgres_password: str = None,
    ) -> bool:
        """Clone a PostgreSQL database from source to target container.

        This performs a full database clone using pg_dump and pg_restore:
        1. Dumps the source database to a SQL file
        2. Creates the target database
        3. Restores the dump to the target database
        4. Cleans up temporary files

        Args:
            source_container: Docker container name for the source PostgreSQL server
            source_db: Name of the source database to clone
            target_container: Docker container name for the target PostgreSQL server
            target_db: Name of the target database to create
            postgres_user: PostgreSQL user (default: from env or 'postgres')
            postgres_password: PostgreSQL password (default: from env or 'postgres')

        Returns:
            True if cloning succeeded, False otherwise

        Raises:
            RuntimeError: If any step of the cloning process fails
        """
        user = postgres_user or POSTGRES_USER
        password = postgres_password or POSTGRES_PASSWORD
        dump_file = TEMP_DUMP_DIR / f"{source_db}_{target_db}.sql"

        logger.info(f"Cloning database: {source_container}/{source_db} -> {target_container}/{target_db}")

        try:
            # Step 1: Dump source database
            logger.info(f"Step 1: Dumping source database {source_db}")
            await self._dump_database(source_container, source_db, dump_file, user, password)

            # Step 2: Create target database
            logger.info(f"Step 2: Creating target database {target_db}")
            await self._create_database(target_container, target_db, user, password)

            # Step 3: Restore to target database
            logger.info(f"Step 3: Restoring to target database {target_db}")
            await self._restore_database(target_container, target_db, dump_file, user, password)

            logger.info(f"Database cloned successfully: {target_db}")
            return True

        except Exception as e:
            logger.error(f"Database cloning failed: {e}")
            raise RuntimeError(f"Failed to clone database: {e}") from e

        finally:
            # Clean up dump file
            if dump_file.exists():
                dump_file.unlink()
                logger.debug(f"Cleaned up dump file: {dump_file}")

    async def _dump_database(
        self,
        container: str,
        db_name: str,
        dump_file: Path,
        user: str,
        password: str,
    ):
        """Dump a database to a SQL file using pg_dump.

        Args:
            container: Docker container name
            db_name: Database name to dump
            dump_file: Path to save the dump file
            user: PostgreSQL user
            password: PostgreSQL password
        """
        # pg_dump command to run inside container
        pg_dump_cmd = [
            "pg_dump",
            "-U", user,
            "-d", db_name,
            "--format=custom",  # Custom format for pg_restore
            "--no-owner",  # Don't include ownership commands
            "--no-acl",  # Don't include access control
        ]

        # Run pg_dump inside container and capture binary output
        # pg_dump --format=custom produces binary data, not text
        result = run_docker_cmd([
            "exec",
            "-e", f"PGPASSWORD={password}",
            container,
            *pg_dump_cmd,
        ], check=False, binary=True)

        if result.returncode != 0:
            # stderr is binary in binary mode, decode for error message
            stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
            raise RuntimeError(f"pg_dump failed: {stderr}")

        # Write dump to file (already bytes)
        dump_file.write_bytes(result.stdout)
        logger.debug(f"Database dumped to {dump_file}")

    async def _dump_database_to_stdout(
        self,
        container: str,
        db_name: str,
        user: str,
        password: str,
    ) -> bytes:
        """Dump a database and return the raw bytes.

        Args:
            container: Docker container name
            db_name: Database name to dump
            user: PostgreSQL user
            password: PostgreSQL password

        Returns:
            Raw dump bytes
        """
        pg_dump_cmd = [
            "exec",
            "-e", f"PGPASSWORD={password}",
            container,
            "pg_dump",
            "-U", user,
            "-d", db_name,
            "--format=custom",
            "--no-owner",
            "--no-acl",
        ]

        result = subprocess.run(
            ["docker"] + pg_dump_cmd,
            capture_output=True,
            check=False
        )

        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {result.stderr.decode()}")

        return result.stdout

    async def _create_database(
        self,
        container: str,
        db_name: str,
        user: str,
        password: str,
    ):
        """Create a new database in the target container.

        Args:
            container: Docker container name
            db_name: Database name to create
            user: PostgreSQL user
            password: PostgreSQL password
        """
        # First, check if database exists and drop it
        drop_cmd = f"DROP DATABASE IF EXISTS {db_name};"
        result = run_docker_cmd([
            "exec",
            "-e", f"PGPASSWORD={password}",
            container,
            "psql",
            "-U", user,
            "-c", drop_cmd,
        ], check=False)

        if result.returncode != 0:
            logger.warning(f"Drop database warning: {result.stderr}")

        # Create new database
        create_cmd = f"CREATE DATABASE {db_name};"
        result = run_docker_cmd([
            "exec",
            "-e", f"PGPASSWORD={password}",
            container,
            "psql",
            "-U", user,
            "-c", create_cmd,
        ], check=False)

        if result.returncode != 0:
            raise RuntimeError(f"Failed to create database: {result.stderr}")

        logger.debug(f"Database {db_name} created")

    async def _restore_database(
        self,
        container: str,
        db_name: str,
        dump_file: Path,
        user: str,
        password: str,
    ):
        """Restore a database from a dump file using pg_restore.

        Args:
            container: Docker container name
            db_name: Database name to restore to
            dump_file: Path to the dump file
            user: PostgreSQL user
            password: PostgreSQL password
        """
        # Copy dump file into container
        container_dump_path = f"/tmp/{dump_file.name}"

        result = run_docker_cmd([
            "cp",
            str(dump_file),
            f"{container}:{container_dump_path}",
        ], check=False)

        if result.returncode != 0:
            raise RuntimeError(f"Failed to copy dump file to container: {result.stderr}")

        try:
            # Run pg_restore
            result = run_docker_cmd([
                "exec",
                "-e", f"PGPASSWORD={password}",
                container,
                "pg_restore",
                "-U", user,
                "-d", db_name,
                "--no-owner",
                "--no-acl",
                container_dump_path,
            ], check=False)

            # pg_restore returns non-zero for warnings too, so check stderr
            if result.returncode != 0 and "error" in result.stderr.lower():
                raise RuntimeError(f"pg_restore failed: {result.stderr}")

            logger.debug(f"Database restored to {db_name}")

        finally:
            # Clean up dump file in container
            run_docker_cmd([
                "exec",
                container,
                "rm", "-f", container_dump_path,
            ], check=False)

    async def clone_database_direct(
        self,
        source_container: str,
        source_db: str,
        target_container: str,
        target_db: str,
        postgres_user: str = None,
        postgres_password: str = None,
    ) -> bool:
        """Clone a database using direct pipe (without intermediate file).

        This is more efficient for large databases as it streams directly
        from pg_dump to pg_restore without writing to disk.

        Args:
            source_container: Docker container name for source
            source_db: Source database name
            target_container: Docker container name for target
            target_db: Target database name
            postgres_user: PostgreSQL user
            postgres_password: PostgreSQL password

        Returns:
            True if cloning succeeded
        """
        user = postgres_user or POSTGRES_USER
        password = postgres_password or POSTGRES_PASSWORD

        logger.info(f"Cloning database (direct): {source_container}/{source_db} -> {target_container}/{target_db}")

        try:
            # Create target database first
            await self._create_database(target_container, target_db, user, password)

            # Pipe pg_dump directly to pg_restore
            dump_cmd = [
                "docker", "exec",
                "-e", f"PGPASSWORD={password}",
                source_container,
                "pg_dump",
                "-U", user,
                "-d", source_db,
                "--format=custom",
                "--no-owner",
                "--no-acl",
            ]

            restore_cmd = [
                "docker", "exec",
                "-i",
                "-e", f"PGPASSWORD={password}",
                target_container,
                "pg_restore",
                "-U", user,
                "-d", target_db,
                "--no-owner",
                "--no-acl",
            ]

            # Use shell pipe for direct streaming
            logger.debug(f"Dump cmd: {' '.join(dump_cmd)}")
            logger.debug(f"Restore cmd: {' '.join(restore_cmd)}")

            dump_proc = subprocess.Popen(
                dump_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            restore_proc = subprocess.Popen(
                restore_cmd,
                stdin=dump_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Allow dump_proc to receive a SIGPIPE if restore_proc exits
            dump_proc.stdout.close()

            # Wait for restore to complete
            _, restore_stderr = restore_proc.communicate()
            dump_proc.wait()

            if restore_proc.returncode != 0 and "error" in restore_stderr.decode().lower():
                raise RuntimeError(f"pg_restore failed: {restore_stderr.decode()}")

            logger.info(f"Database cloned successfully (direct): {target_db}")
            return True

        except Exception as e:
            logger.error(f"Database cloning failed: {e}")
            raise RuntimeError(f"Failed to clone database: {e}") from e

    async def delete_database(
        self,
        container: str,
        db_name: str,
        postgres_user: str = None,
        postgres_password: str = None,
    ) -> bool:
        """Delete a database from a container.

        Args:
            container: Docker container name
            db_name: Database name to delete
            postgres_user: PostgreSQL user
            postgres_password: PostgreSQL password

        Returns:
            True if deletion succeeded, False if database didn't exist
        """
        user = postgres_user or POSTGRES_USER
        password = postgres_password or POSTGRES_PASSWORD

        logger.info(f"Deleting database: {container}/{db_name}")

        # Terminate connections to the database
        terminate_cmd = f"""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = '{db_name}' AND pid <> pg_backend_pid();
        """

        run_docker_cmd([
            "exec",
            "-e", f"PGPASSWORD={password}",
            container,
            "psql",
            "-U", user,
            "-c", terminate_cmd,
        ], check=False)

        # Drop the database
        drop_cmd = f"DROP DATABASE IF EXISTS {db_name};"
        result = run_docker_cmd([
            "exec",
            "-e", f"PGPASSWORD={password}",
            container,
            "psql",
            "-U", user,
            "-c", drop_cmd,
        ], check=False)

        if result.returncode != 0:
            logger.error(f"Failed to delete database: {result.stderr}")
            return False

        logger.info(f"Database {db_name} deleted from {container}")
        return True

    async def database_exists(
        self,
        container: str,
        db_name: str,
        postgres_user: str = None,
        postgres_password: str = None,
    ) -> bool:
        """Check if a database exists in a container.

        Args:
            container: Docker container name
            db_name: Database name to check
            postgres_user: PostgreSQL user
            postgres_password: PostgreSQL password

        Returns:
            True if database exists
        """
        user = postgres_user or POSTGRES_USER
        password = postgres_password or POSTGRES_PASSWORD

        check_cmd = f"SELECT 1 FROM pg_database WHERE datname = '{db_name}';"
        result = run_docker_cmd([
            "exec",
            "-e", f"PGPASSWORD={password}",
            container,
            "psql",
            "-U", user,
            "-tAc", check_cmd,
        ], check=False)

        return result.returncode == 0 and result.stdout.strip() == "1"

    async def get_database_size(
        self,
        container: str,
        db_name: str,
        postgres_user: str = None,
        postgres_password: str = None,
    ) -> Optional[int]:
        """Get the size of a database in bytes.

        Args:
            container: Docker container name
            db_name: Database name
            postgres_user: PostgreSQL user
            postgres_password: PostgreSQL password

        Returns:
            Size in bytes, or None if database doesn't exist
        """
        user = postgres_user or POSTGRES_USER
        password = postgres_password or POSTGRES_PASSWORD

        size_cmd = f"SELECT pg_database_size('{db_name}');"
        result = run_docker_cmd([
            "exec",
            "-e", f"PGPASSWORD={password}",
            container,
            "psql",
            "-U", user,
            "-tAc", size_cmd,
        ], check=False)

        if result.returncode != 0:
            return None

        try:
            return int(result.stdout.strip())
        except ValueError:
            return None


# Singleton instance
database_cloner = DatabaseCloner()
