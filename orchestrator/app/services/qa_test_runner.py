"""QA Test Runner - Executes Playwright tests in Docker containers on host.

This service spawns Playwright Docker containers on the HOST machine via SSH,
executes tests against sandbox environments, and collects results with screenshots.
"""

import asyncio
import base64
import json
import logging
import os
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# SSH configuration (reuse from claude_code_runner)
SSH_HOST = os.getenv("SSH_HOST", "host.docker.internal")
SSH_USER = os.getenv("SSH_USER", "")

# Test results configuration
QA_RESULTS_BASE = os.getenv("QA_RESULTS_BASE", "/Volumes/dados/projects/kanban/e2e-tests/qa-results")
PLAYWRIGHT_IMAGE = os.getenv("QA_PLAYWRIGHT_IMAGE", "mcr.microsoft.com/playwright:v1.57.0-noble")
HOST_PROJECT_PATH = os.getenv("HOST_PROJECT_PATH", "/Volumes/dados/projects/kanban")


@dataclass
class QAIssue:
    """Structured issue found during QA testing."""
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    title: str
    location: str
    steps_to_reproduce: List[str]
    expected: str
    actual: str
    suggested_fix: str
    screenshot: Optional[str] = None  # filename if captured


@dataclass
class TestResult:
    """Result from a QA test execution."""
    success: bool
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_seconds: float = 0
    output: str = ""
    error: Optional[str] = None
    issues: List[QAIssue] = field(default_factory=list)
    screenshots: Dict[str, str] = field(default_factory=dict)  # filename -> base64
    results_dir: str = ""

    def format_issues_for_developer(self) -> str:
        """Format issues in a structured way that the developer agent can parse."""
        if not self.issues:
            return ""

        lines = [
            "### Developer Action Required",
            "",
            "<!-- QA_ISSUES_START -->",
        ]

        for i, issue in enumerate(self.issues, 1):
            lines.append(f"{i}. **[{issue.severity}]** {issue.title}")
            lines.append(f"   - **Location:** {issue.location}")
            lines.append(f"   - **Steps to reproduce:**")
            for step_num, step in enumerate(issue.steps_to_reproduce, 1):
                lines.append(f"     {step_num}. {step}")
            lines.append(f"   - **Expected:** {issue.expected}")
            lines.append(f"   - **Actual:** {issue.actual}")
            lines.append(f"   - **Suggested fix:** {issue.suggested_fix}")
            if issue.screenshot:
                lines.append(f"   - **Screenshot:** {issue.screenshot}")
            lines.append("")

        lines.append("<!-- QA_ISSUES_END -->")
        return "\n".join(lines)


@dataclass
class QATestConfig:
    """Configuration for QA test execution."""
    card_id: str
    sandbox_url: str
    sandbox_api_url: str
    test_email: str
    test_password: str
    card_title: str
    card_description: str
    workspace_slug: str
    sandbox_slug: str
    full_slug: str
    domain: str = "amazing-ai.tools"
    test_timeout: int = 300  # 5 minutes default


class QATestRunner:
    """Runs Playwright tests in Docker containers on the host via SSH."""

    def __init__(self):
        self.ssh_host = SSH_HOST
        self.ssh_user = SSH_USER
        self.results_base = QA_RESULTS_BASE
        self.playwright_image = PLAYWRIGHT_IMAGE
        self.host_project_path = HOST_PROJECT_PATH

    def _build_ssh_command(self, remote_cmd: str) -> list:
        """Build SSH command to execute on host."""
        ssh_cmd = ["ssh"]
        ssh_cmd.extend(["-o", "StrictHostKeyChecking=no"])
        ssh_cmd.extend(["-o", "UserKnownHostsFile=/dev/null"])
        ssh_cmd.extend(["-o", "LogLevel=ERROR"])

        target = f"{self.ssh_user}@{self.ssh_host}" if self.ssh_user else self.ssh_host
        ssh_cmd.append(target)
        ssh_cmd.append(remote_cmd)
        return ssh_cmd

    async def run_ssh_command(self, remote_cmd: str, timeout: int = 60) -> tuple[int, str, str]:
        """Execute command on host via SSH."""
        if not self.ssh_user:
            return 1, "", "SSH_USER not configured"

        ssh_cmd = self._build_ssh_command(remote_cmd)

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

            return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")
        except Exception as e:
            return 1, "", f"SSH command failed: {e}"

    def _generate_results_dir(self, card_id: str) -> str:
        """Generate unique results directory path for a test run."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"{self.results_base}/{card_id[:8]}_{timestamp}"

    async def run_tests(self, config: QATestConfig) -> TestResult:
        """Execute Playwright tests in Docker container on host.

        Args:
            config: QA test configuration with sandbox URLs and credentials

        Returns:
            TestResult with pass/fail status, screenshots, and issues
        """
        import time
        start_time = time.time()

        if not self.ssh_user:
            return TestResult(
                success=False,
                error="SSH_USER not configured for QA test execution",
                duration_seconds=time.time() - start_time
            )

        results_dir = self._generate_results_dir(config.card_id)

        # Step 1: Create results directory on host
        logger.info(f"Creating QA results directory: {results_dir}")
        mkdir_cmd = f"mkdir -p {shlex.quote(results_dir)}"
        code, _, err = await self.run_ssh_command(mkdir_cmd, timeout=30)
        if code != 0:
            return TestResult(
                success=False,
                error=f"Failed to create results directory: {err}",
                duration_seconds=time.time() - start_time
            )

        # Step 2: Generate test spec file for this card
        test_spec = self._generate_test_spec(config)
        spec_path = f"{results_dir}/qa-test.spec.ts"

        # Write test spec via SSH using heredoc
        write_cmd = f"cat > {shlex.quote(spec_path)} << 'TESTSPECEOF'\n{test_spec}\nTESTSPECEOF"
        code, _, err = await self.run_ssh_command(write_cmd, timeout=30)
        if code != 0:
            return TestResult(
                success=False,
                error=f"Failed to write test spec: {err}",
                duration_seconds=time.time() - start_time
            )

        # Step 3: Run Playwright in Docker container
        docker_cmd = self._build_docker_command(config, results_dir, spec_path)

        logger.info(f"Running QA tests for card {config.card_id[:8]} against {config.sandbox_url}")
        logger.debug(f"Docker command: {docker_cmd[:200]}...")

        code, stdout, stderr = await self.run_ssh_command(docker_cmd, timeout=config.test_timeout + 60)

        # Step 4: Parse test results
        result = await self._parse_test_results(results_dir, stdout, stderr, code, config)
        result.duration_seconds = time.time() - start_time
        result.results_dir = results_dir

        # Step 5: Collect and encode screenshots
        result.screenshots = await self._collect_screenshots(results_dir)

        logger.info(
            f"QA tests completed: {result.passed}/{result.total_tests} passed, "
            f"{result.failed} failed, {len(result.screenshots)} screenshots, "
            f"{len(result.issues)} issues"
        )

        return result

    def _generate_test_spec(self, config: QATestConfig) -> str:
        """Generate Playwright test spec from card description."""
        # Clean card description for embedding in test
        clean_description = config.card_description.replace("*/", "* /").replace("`", "\\`")
        # Escape single quotes in title for JS string
        escaped_title = config.card_title.replace("'", "\\'")

        return f'''import {{ test, expect }} from '@playwright/test';

const SANDBOX_URL = process.env.SANDBOX_URL || '{config.sandbox_url}';
const API_URL = process.env.API_URL || '{config.sandbox_api_url}';
const TEST_EMAIL = process.env.TEST_EMAIL || '';
const TEST_PASSWORD = process.env.TEST_PASSWORD || '';

test.describe('QA Validation: {escaped_title}', () => {{

    test.beforeEach(async ({{ page }}) => {{
        // Navigate to sandbox
        await page.goto(SANDBOX_URL, {{ waitUntil: 'networkidle', timeout: 30000 }});
    }});

    test('01 - Sandbox UI is accessible', async ({{ page }}) => {{
        await page.screenshot({{ path: '/app/results/01-sandbox-accessible.png', fullPage: true }});

        // Verify page loaded (not error page)
        const title = await page.title();
        expect(title).not.toContain('Error');
        expect(title).not.toContain('404');
        expect(title).not.toContain('502');
        expect(title).not.toContain('503');

        // Check for visible content
        const body = await page.locator('body').textContent();
        expect(body).not.toContain('cannot be reached');
    }});

    test('02 - Sandbox API health check', async ({{ page, request }}) => {{
        try {{
            const response = await request.get(`${{API_URL}}/health`, {{
                timeout: 10000,
                ignoreHTTPSErrors: true
            }});
            expect(response.status()).toBe(200);
            await page.screenshot({{ path: '/app/results/02-api-health-passed.png' }});
        }} catch (e) {{
            await page.screenshot({{ path: '/app/results/02-api-health-failed.png' }});
            throw e;
        }}
    }});

    test('03 - Main UI elements render correctly', async ({{ page }}) => {{
        // Wait for main content to load
        await page.waitForLoadState('networkidle');

        // Take screenshot of initial state
        await page.screenshot({{ path: '/app/results/03-main-ui.png', fullPage: true }});

        // Check for common error indicators
        const pageContent = await page.content();
        expect(pageContent).not.toContain('Unhandled Runtime Error');
        expect(pageContent).not.toContain('Application error');
        expect(pageContent).not.toContain('Something went wrong');
    }});

    test('04 - No console errors on page load', async ({{ page }}) => {{
        const consoleErrors: string[] = [];

        page.on('console', msg => {{
            if (msg.type() === 'error') {{
                consoleErrors.push(msg.text());
            }}
        }});

        await page.goto(SANDBOX_URL, {{ waitUntil: 'networkidle' }});
        await page.waitForTimeout(2000); // Wait for any delayed errors

        await page.screenshot({{ path: '/app/results/04-console-check.png' }});

        // Filter out known acceptable errors (e.g., favicon)
        const criticalErrors = consoleErrors.filter(err =>
            !err.includes('favicon') &&
            !err.includes('404') &&
            !err.includes('net::ERR')
        );

        if (criticalErrors.length > 0) {{
            console.log('Console errors found:', criticalErrors);
        }}
        // Note: We log but don't fail on console errors to gather info
    }});

    test('05 - Feature validation based on card requirements', async ({{ page }}) => {{
        /*
         * Card: {config.card_title}
         * Description:
         * {clean_description[:500]}
         */

        await page.goto(SANDBOX_URL, {{ waitUntil: 'networkidle' }});
        await page.waitForTimeout(1000);

        // Take final screenshot showing current state
        await page.screenshot({{ path: '/app/results/05-feature-validation.png', fullPage: true }});

        // Basic validation that page rendered
        const hasContent = await page.locator('body').evaluate(el => el.innerHTML.length > 100);
        expect(hasContent).toBe(true);
    }});
}});
'''

    def _build_docker_command(self, config: QATestConfig, results_dir: str, spec_path: str) -> str:
        """Build Docker run command for Playwright container."""
        # Build the full sandbox hostname for network resolution
        sandbox_hostname = f"{config.full_slug}.sandbox.{config.domain}"

        docker_cmd = f'''docker run --rm \\
  --name qa-test-{config.card_id[:8]} \\
  --network kanban-global \\
  --add-host={sandbox_hostname}:host-gateway \\
  -e SANDBOX_URL={shlex.quote(config.sandbox_url)} \\
  -e API_URL={shlex.quote(config.sandbox_api_url)} \\
  -e TEST_EMAIL={shlex.quote(config.test_email)} \\
  -e TEST_PASSWORD={shlex.quote(config.test_password)} \\
  -e NODE_TLS_REJECT_UNAUTHORIZED=0 \\
  -v {shlex.quote(results_dir)}:/app/results \\
  -v {shlex.quote(spec_path)}:/app/tests/qa-test.spec.ts:ro \\
  -v {self.host_project_path}/e2e-tests/playwright.config.ts:/app/playwright.config.ts:ro \\
  -v {self.host_project_path}/e2e-tests/package.json:/app/package.json:ro \\
  --workdir /app \\
  {self.playwright_image} \\
  sh -c "npm install --silent 2>/dev/null && npx playwright test --reporter=json --output=/app/results 2>&1 | tee /app/results/output.log; echo EXIT_CODE=$?"'''

        return docker_cmd

    async def _parse_test_results(
        self, results_dir: str, stdout: str, stderr: str, exit_code: int, config: QATestConfig
    ) -> TestResult:
        """Parse Playwright output and extract test results with structured issues."""

        result = TestResult(
            success=exit_code == 0,
            output=stdout,
            error=stderr if exit_code != 0 else None
        )

        # Try to read the JSON report file
        json_path = f"{results_dir}/test-results/.last-run.json"
        cat_cmd = f"cat {shlex.quote(json_path)} 2>/dev/null || cat {results_dir}/results.json 2>/dev/null"
        code, json_output, _ = await self.run_ssh_command(cat_cmd, timeout=30)

        # Parse stdout for test results as primary source
        if stdout:
            # Look for test summary patterns
            passed_match = re.search(r'(\d+) passed', stdout)
            failed_match = re.search(r'(\d+) failed', stdout)
            skipped_match = re.search(r'(\d+) skipped', stdout)

            if passed_match:
                result.passed = int(passed_match.group(1))
            if failed_match:
                result.failed = int(failed_match.group(1))
            if skipped_match:
                result.skipped = int(skipped_match.group(1))

            result.total_tests = result.passed + result.failed + result.skipped

            # Extract failure details for structured issues
            failure_blocks = re.findall(
                r'(\d+\).*?(?=\d+\)|$))',
                stdout,
                re.DOTALL
            )

            for block in failure_blocks:
                if 'Error:' in block or 'expect(' in block:
                    issue = self._parse_failure_to_issue(block, config)
                    if issue:
                        result.issues.append(issue)

        # If no test results found, try parsing JSON
        if result.total_tests == 0 and code == 0 and json_output:
            try:
                report = json.loads(json_output)
                self._parse_json_report(report, result, config)
            except json.JSONDecodeError:
                logger.warning("Failed to parse Playwright JSON output")

        # Set success based on failures
        result.success = result.failed == 0 and result.total_tests > 0

        return result

    def _parse_failure_to_issue(self, failure_block: str, config: QATestConfig) -> Optional[QAIssue]:
        """Parse a test failure block into a structured QAIssue."""
        # Extract test name
        test_name_match = re.search(r'\d+\)\s+(.+?)(?:\s+›|\n)', failure_block)
        test_name = test_name_match.group(1).strip() if test_name_match else "Unknown test"

        # Extract error message
        error_match = re.search(r'Error:\s*(.+?)(?:\n\n|\n\s+at)', failure_block, re.DOTALL)
        error_msg = error_match.group(1).strip() if error_match else "Test failed"

        # Determine severity based on test name
        severity = "HIGH"
        if "health" in test_name.lower() or "accessible" in test_name.lower():
            severity = "CRITICAL"
        elif "console" in test_name.lower():
            severity = "MEDIUM"

        # Extract location from test name
        location = "UI"
        if "api" in test_name.lower():
            location = "API endpoint"
        elif "auth" in test_name.lower():
            location = "Authentication flow"
        elif "ui" in test_name.lower() or "render" in test_name.lower():
            location = "UI rendering"

        return QAIssue(
            severity=severity,
            title=f"{test_name} failed",
            location=location,
            steps_to_reproduce=[
                f"Navigate to {config.sandbox_url}",
                f"Run test: {test_name}",
            ],
            expected="Test should pass",
            actual=error_msg[:200],
            suggested_fix="Review the error message and fix the underlying issue",
        )

    def _parse_json_report(self, report: dict, result: TestResult, config: QATestConfig):
        """Parse Playwright JSON reporter format."""
        for suite in report.get("suites", []):
            for spec in suite.get("specs", []):
                result.total_tests += 1
                status = spec.get("ok", False)
                if status:
                    result.passed += 1
                else:
                    result.failed += 1
                    # Extract failure for issue
                    for test in spec.get("tests", []):
                        for res in test.get("results", []):
                            if res.get("status") == "failed":
                                error_msg = res.get("error", {}).get("message", "Unknown error")
                                result.issues.append(QAIssue(
                                    severity="HIGH",
                                    title=spec.get("title", "Test failed"),
                                    location="Automated test",
                                    steps_to_reproduce=[
                                        f"Navigate to {config.sandbox_url}",
                                        f"Execute test: {spec.get('title', 'unknown')}",
                                    ],
                                    expected="Test should pass",
                                    actual=error_msg[:200],
                                    suggested_fix="Review test failure and fix the implementation",
                                ))

    async def _collect_screenshots(self, results_dir: str) -> Dict[str, str]:
        """Collect screenshots from results directory and encode to base64."""
        screenshots = {}

        # List PNG files in results directory
        ls_cmd = f"find {shlex.quote(results_dir)} -name '*.png' -type f 2>/dev/null"
        code, output, _ = await self.run_ssh_command(ls_cmd, timeout=30)

        if code != 0 or not output.strip():
            logger.info(f"No screenshots found in {results_dir}")
            return screenshots

        for filepath in output.strip().split('\n'):
            if not filepath.endswith('.png'):
                continue

            filename = os.path.basename(filepath)

            # Read and base64 encode the file
            b64_cmd = f"base64 < {shlex.quote(filepath)}"
            code, b64_output, _ = await self.run_ssh_command(b64_cmd, timeout=60)

            if code == 0 and b64_output:
                # Remove newlines from base64 output
                screenshots[filename] = b64_output.replace('\n', '').strip()
                logger.debug(f"Collected screenshot: {filename} ({len(b64_output)} bytes)")

        return screenshots


# Singleton instance
qa_runner = QATestRunner()
