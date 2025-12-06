import { test, expect, Page } from '@playwright/test';

const PORTAL_URL = process.env.PORTAL_URL || 'https://app.localhost:4443';
const PORTAL_API_URL = process.env.PORTAL_API_URL || 'https://api.localhost:4443';

// Test JWT token - replace with a valid one or get it from login
const TEST_TOKEN = process.env.TEST_TOKEN || '';

test.describe('SSO Flow Debug', () => {

  test('Debug: Check portal login page', async ({ page }) => {
    console.log('\n=== Starting Portal Login Page Test ===');
    console.log(`Portal URL: ${PORTAL_URL}`);

    // Enable detailed logging
    page.on('console', msg => console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`));
    page.on('pageerror', error => console.log(`[Page Error] ${error.message}`));
    page.on('request', req => console.log(`[Request] ${req.method()} ${req.url()}`));
    page.on('response', res => console.log(`[Response] ${res.status()} ${res.url()}`));

    await page.goto(PORTAL_URL);
    await page.waitForLoadState('networkidle');

    console.log(`\nPage URL: ${page.url()}`);
    console.log(`Page Title: ${await page.title()}`);

    // Check if we're on login page
    const isLoginPage = page.url().includes('/login');
    console.log(`Is Login Page: ${isLoginPage}`);

    // Take screenshot
    await page.screenshot({ path: '/app/results/01-portal-initial.png', fullPage: true });

    // Check localStorage
    const token = await page.evaluate(() => localStorage.getItem('token'));
    console.log(`Token in localStorage: ${token ? 'EXISTS' : 'NULL'}`);
  });

  test('Debug: Simulate authenticated user and click team', async ({ page }) => {
    console.log('\n=== Starting Authenticated Flow Test ===');

    // Enable detailed logging
    page.on('console', msg => console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`));
    page.on('pageerror', error => console.log(`[Page Error] ${error.message}`));

    // Log all network requests
    const requests: string[] = [];
    page.on('request', req => {
      const log = `[Request] ${req.method()} ${req.url()}`;
      console.log(log);
      requests.push(log);
    });
    page.on('response', res => {
      const log = `[Response] ${res.status()} ${res.url()}`;
      console.log(log);
      requests.push(log);
    });

    // First, let's get a valid token by calling the API
    console.log('\n--- Step 1: Setting up authentication ---');

    // Go to portal and inject a token
    await page.goto(PORTAL_URL);
    await page.waitForLoadState('networkidle');

    // If we have a test token, inject it
    if (TEST_TOKEN) {
      console.log('Injecting test token...');
      await page.evaluate((token) => {
        localStorage.setItem('token', token);
      }, TEST_TOKEN);

      // Reload to apply token
      await page.reload();
      await page.waitForLoadState('networkidle');
    }

    await page.screenshot({ path: '/app/results/02-after-token-inject.png', fullPage: true });

    console.log(`\nCurrent URL: ${page.url()}`);

    // Check if we're authenticated
    const isAuthenticated = !page.url().includes('/login');
    console.log(`Is Authenticated: ${isAuthenticated}`);

    if (!isAuthenticated) {
      console.log('\n!!! NOT AUTHENTICATED - Token might be invalid !!!');
      console.log('Checking what happened...');

      // Check localStorage again
      const storedToken = await page.evaluate(() => localStorage.getItem('token'));
      console.log(`Token after reload: ${storedToken ? storedToken.substring(0, 50) + '...' : 'NULL'}`);

      return;
    }

    // Wait for teams to load
    console.log('\n--- Step 2: Waiting for teams page ---');
    await page.waitForTimeout(2000);
    await page.screenshot({ path: '/app/results/03-teams-page.png', fullPage: true });

    // Try to find team links
    const teamLinks = await page.locator('button:has-text("Open Board")').all();
    console.log(`Found ${teamLinks.length} team links`);

    if (teamLinks.length > 0) {
      console.log('\n--- Step 3: Clicking first team link ---');

      // Get the team card text before clicking
      const teamCard = teamLinks[0].locator('..').locator('..');
      console.log('Team card HTML:', await teamCard.innerHTML().catch(() => 'Could not get HTML'));

      // Click the team link
      await teamLinks[0].click();

      // Wait and see what happens
      await page.waitForTimeout(3000);
      await page.waitForLoadState('networkidle');

      console.log(`\nAfter click URL: ${page.url()}`);
      await page.screenshot({ path: '/app/results/04-after-team-click.png', fullPage: true });

      // Check if we ended up on login page
      if (page.url().includes('/login')) {
        console.log('\n!!! REDIRECT TO LOGIN DETECTED !!!');
        console.log('This confirms the bug - user is being redirected back to login');

        // Check what's in localStorage
        const tokenAfter = await page.evaluate(() => localStorage.getItem('token'));
        console.log(`Token after redirect: ${tokenAfter ? 'EXISTS' : 'NULL'}`);
      }
    }

    // Print all requests for debugging
    console.log('\n=== All Network Requests ===');
    requests.forEach(r => console.log(r));
  });

  test('Debug: Test token in URL handling', async ({ page }) => {
    console.log('\n=== Testing Token in URL Handling ===');

    page.on('console', msg => console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`));

    // Simulate OAuth callback - go to portal with token in URL
    const testToken = TEST_TOKEN || 'test-token-123';
    const urlWithToken = `${PORTAL_URL}/?token=${testToken}`;

    console.log(`Going to: ${urlWithToken}`);
    await page.goto(urlWithToken);
    await page.waitForLoadState('networkidle');

    // Check if token was saved
    const savedToken = await page.evaluate(() => localStorage.getItem('token'));
    console.log(`Token saved to localStorage: ${savedToken ? 'YES' : 'NO'}`);
    console.log(`Saved token value: ${savedToken ? savedToken.substring(0, 50) + '...' : 'NULL'}`);

    // Check current URL - token should be removed
    console.log(`Current URL: ${page.url()}`);
    console.log(`Token removed from URL: ${!page.url().includes('token=')}`);

    await page.screenshot({ path: '/app/results/05-token-url-test.png', fullPage: true });
  });

  test('Debug: Test SSO redirect flow', async ({ page }) => {
    console.log('\n=== Testing SSO Redirect Flow ===');

    page.on('console', msg => console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`));
    page.on('request', req => console.log(`[Request] ${req.method()} ${req.url()}`));
    page.on('response', res => console.log(`[Response] ${res.status()} ${res.url()}`));

    // Go directly to team with SSO token
    const teamUrl = 'https://teste.localhost:4443';

    // First, get a real SSO token from the API
    console.log('Getting SSO token from portal API...');

    const apiResponse = await page.request.get(
      `${PORTAL_API_URL}/auth/cross-domain-token?team_slug=teste&user_id=83a80128-7e96-4416-952f-166ebb4345ec`,
      {
        headers: {
          'Authorization': `Bearer ${TEST_TOKEN}`
        }
      }
    );

    if (apiResponse.ok()) {
      const data = await apiResponse.json();
      const ssoToken = data.token;
      console.log(`Got SSO token: ${ssoToken.substring(0, 50)}...`);

      // Go to team with SSO token
      const teamWithSso = `${teamUrl}?sso_token=${ssoToken}`;
      console.log(`\nNavigating to team: ${teamWithSso}`);

      await page.goto(teamWithSso);
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(3000);

      console.log(`\nFinal URL: ${page.url()}`);

      // Check localStorage on team domain
      const teamToken = await page.evaluate(() => localStorage.getItem('token'));
      console.log(`Token on team domain: ${teamToken ? 'EXISTS' : 'NULL'}`);

      await page.screenshot({ path: '/app/results/06-team-sso-flow.png', fullPage: true });
    } else {
      console.log(`Failed to get SSO token: ${apiResponse.status()}`);
      console.log(await apiResponse.text());
    }
  });
});
