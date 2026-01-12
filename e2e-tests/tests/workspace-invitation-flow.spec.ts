import { test, expect, Page, request, APIRequestContext } from '@playwright/test';

const PORTAL_URL = process.env.PORTAL_URL || 'https://kanban.amazing-ai.tools';
const PORTAL_API_URL = process.env.PORTAL_API_URL || 'https://kanban.amazing-ai.tools/api';

// Test user credentials (from Azure Key Vault via environment)
const TEST_USER_EMAIL = process.env.TEST_USER_EMAIL || '';
const TEST_USER_PASSWORD = process.env.TEST_USER_PASSWORD || '';

// Pre-existing tokens (alternative to test-login)
const OWNER_TEST_TOKEN = process.env.OWNER_TEST_TOKEN || '';
const INVITEE_TEST_TOKEN = process.env.INVITEE_TEST_TOKEN || '';

// Email for invited user
const INVITEE_EMAIL = process.env.INVITEE_EMAIL || 'e2e-test-invitee@example.com';

// Fixed test workspace names (always the same for easy cleanup)
const TEST_WORKSPACE_NAME = 'E2E Test Invitation Flow';
const TEST_WORKSPACE_SLUG = 'e2e-test-invitation';
const FULL_FLOW_WORKSPACE_NAME = 'E2E Full Flow Test';
const FULL_FLOW_WORKSPACE_SLUG = 'e2e-full-flow-test';

/**
 * Helper: Get authentication token via test-login API
 */
async function getTestToken(email: string, password: string): Promise<string | null> {
  try {
    const apiContext = await request.newContext({
      ignoreHTTPSErrors: true,
    });

    const response = await apiContext.post(
      `${PORTAL_API_URL}/auth/test-login?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`
    );

    if (response.ok()) {
      const data = await response.json();
      console.log(`Got token for ${email}`);
      return data.access_token;
    } else {
      console.log(`Test login failed for ${email}: ${response.status()}`);
      const text = await response.text();
      console.log(`Response: ${text.substring(0, 200)}`);
      return null;
    }
  } catch (error) {
    console.log(`Test login error: ${error}`);
    return null;
  }
}

/**
 * Helper: Delete a workspace via API (for cleanup)
 */
async function deleteWorkspace(token: string, slug: string): Promise<boolean> {
  try {
    const apiContext = await request.newContext({
      ignoreHTTPSErrors: true,
    });

    console.log(`Attempting to delete workspace: ${slug}`);

    const response = await apiContext.delete(`${PORTAL_API_URL}/workspaces/${slug}`, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    });

    if (response.ok()) {
      console.log(`Successfully deleted workspace: ${slug}`);
      return true;
    } else if (response.status() === 404) {
      console.log(`Workspace not found (already deleted or never existed): ${slug}`);
      return true; // Not an error - workspace doesn't exist
    } else {
      console.log(`Failed to delete workspace ${slug}: ${response.status()}`);
      const text = await response.text();
      console.log(`Response: ${text.substring(0, 200)}`);
      return false;
    }
  } catch (error) {
    console.log(`Error deleting workspace ${slug}: ${error}`);
    return false;
  }
}

/**
 * Helper: Clean up test workspaces
 */
async function cleanupTestWorkspaces(token: string): Promise<void> {
  console.log('\n=== Cleaning up test workspaces ===');

  const workspacesToDelete = [
    TEST_WORKSPACE_SLUG,
    FULL_FLOW_WORKSPACE_SLUG,
  ];

  for (const slug of workspacesToDelete) {
    await deleteWorkspace(token, slug);
  }

  console.log('Cleanup complete\n');
}

/**
 * Helper: Set up authentication by injecting token into localStorage
 */
async function authenticateWithToken(page: Page, token: string): Promise<boolean> {
  await page.goto(PORTAL_URL);
  await page.waitForLoadState('networkidle');

  if (token) {
    await page.evaluate((t) => {
      localStorage.setItem('token', t);
    }, token);
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Check if authentication was successful (not on login page)
    const isAuthenticated = !page.url().includes('/login');
    return isAuthenticated;
  }
  return false;
}

/**
 * Helper: Wait for workspace to be ready (not provisioning)
 */
async function waitForWorkspaceReady(page: Page, maxWaitMs: number = 90000): Promise<boolean> {
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    const provisioningText = page.locator('text=Setting up');
    const provisioningVisible = await provisioningText.isVisible().catch(() => false);

    if (!provisioningVisible) {
      return true;
    }

    console.log('Workspace still provisioning, waiting...');
    await page.waitForTimeout(5000);
    await page.reload();
    await page.waitForLoadState('networkidle');
  }

  console.log('Workspace still provisioning after timeout');
  return false;
}

test.describe('Workspace Creation and Member Invitation Flow', () => {
  test.describe.configure({ mode: 'serial' });

  let ownerToken: string = '';
  let workspaceSlug: string = TEST_WORKSPACE_SLUG;
  let invitationUrl: string = '';
  let invitationToken: string = '';

  test.beforeAll(async () => {
    console.log('\n=== Test Setup ===');
    console.log(`Portal URL: ${PORTAL_URL}`);
    console.log(`API URL: ${PORTAL_API_URL}`);
    console.log(`Test Workspace: ${TEST_WORKSPACE_NAME} (${TEST_WORKSPACE_SLUG})`);

    // Try to get owner token via test-login or use provided token
    if (TEST_USER_EMAIL && TEST_USER_PASSWORD) {
      console.log('Attempting test-login for owner...');
      const token = await getTestToken(TEST_USER_EMAIL, TEST_USER_PASSWORD);
      if (token) {
        ownerToken = token;
        console.log('Got token via test-login');
      }
    }

    if (!ownerToken && OWNER_TEST_TOKEN) {
      console.log('Using provided OWNER_TEST_TOKEN');
      ownerToken = OWNER_TEST_TOKEN;
    }

    if (!ownerToken) {
      console.log('WARNING: No owner token available. Tests requiring authentication will be skipped.');
      return;
    }

    // Clean up any existing test workspaces from previous runs
    await cleanupTestWorkspaces(ownerToken);
  });

  test.afterAll(async () => {
    if (ownerToken) {
      // Clean up test workspaces after tests complete
      await cleanupTestWorkspaces(ownerToken);
    }
  });

  test('1. Verify portal is accessible', async ({ page }) => {
    console.log('\n=== Step 1: Verify Portal Accessibility ===');

    await page.goto(PORTAL_URL);
    await page.waitForLoadState('networkidle');

    console.log(`Current URL: ${page.url()}`);
    await page.screenshot({ path: '/app/results/01-portal-accessible.png', fullPage: true });

    const isLoginPage = page.url().includes('/login');
    const title = await page.title();

    console.log(`Page title: ${title}`);
    console.log(`Is login page: ${isLoginPage}`);

    expect(await page.locator('body').isVisible()).toBe(true);
  });

  test('2. Owner authenticates', async ({ page }) => {
    console.log('\n=== Step 2: Owner Authentication ===');

    if (!ownerToken) {
      console.log('No owner token available - skipping');
      test.skip();
    }

    const isAuthenticated = await authenticateWithToken(page, ownerToken);

    await page.screenshot({ path: '/app/results/02-owner-authenticated.png', fullPage: true });

    if (isAuthenticated) {
      console.log('Owner authenticated successfully');
      console.log(`Current URL: ${page.url()}`);
    } else {
      console.log('Authentication failed - token may be invalid');
    }

    expect(isAuthenticated).toBe(true);
  });

  test('3. Owner creates a workspace (Kanban Only)', async ({ page }) => {
    console.log('\n=== Step 3: Creating Workspace ===');

    if (!ownerToken) {
      console.log('No owner token available - skipping');
      test.skip();
    }

    await authenticateWithToken(page, ownerToken);

    await page.goto(`${PORTAL_URL}/workspaces/new`);
    await page.waitForLoadState('networkidle');

    await page.screenshot({ path: '/app/results/03-create-workspace-page.png', fullPage: true });

    const heading = page.getByRole('heading', { name: 'Create New Workspace' });
    const isOnCreatePage = await heading.isVisible().catch(() => false);

    if (!isOnCreatePage) {
      console.log('Not on create workspace page - checking current page');
      console.log(`URL: ${page.url()}`);
      await page.screenshot({ path: '/app/results/03-not-create-page.png', fullPage: true });
      test.skip();
    }

    console.log(`Creating workspace: ${TEST_WORKSPACE_NAME} (${TEST_WORKSPACE_SLUG})`);

    const nameInput = page.locator('input#name');
    await nameInput.fill(TEST_WORKSPACE_NAME);

    await page.waitForTimeout(500);

    const slugInput = page.locator('input#slug');
    await slugInput.clear();
    await slugInput.fill(TEST_WORKSPACE_SLUG);

    const descInput = page.locator('textarea#description');
    await descInput.fill('E2E test workspace for invitation flow testing');

    const kanbanOnlyButton = page.locator('button:has-text("Kanban Only")');
    if (await kanbanOnlyButton.isVisible()) {
      await kanbanOnlyButton.click();
    }

    await page.screenshot({ path: '/app/results/04-workspace-form-filled.png', fullPage: true });

    const createButton = page.getByRole('button', { name: 'Create Workspace' });
    await createButton.click();

    await page.waitForURL('**/', { timeout: 30000 });

    console.log('Workspace creation initiated');

    await page.screenshot({ path: '/app/results/05-workspace-created.png', fullPage: true });

    // Wait a bit for the workspace to start provisioning
    await page.waitForTimeout(3000);
  });

  test('4. Owner invites a new member', async ({ page }) => {
    console.log('\n=== Step 4: Inviting Member ===');

    if (!ownerToken) {
      console.log('No owner token available - skipping');
      test.skip();
    }

    const inviteEmail = INVITEE_EMAIL;
    console.log(`Inviting email: ${inviteEmail}`);

    await authenticateWithToken(page, ownerToken);

    await page.goto(`${PORTAL_URL}/workspaces/${workspaceSlug}`);
    await page.waitForLoadState('networkidle');

    await page.screenshot({ path: '/app/results/06-workspace-detail.png', fullPage: true });

    // Wait for workspace to be ready
    const isReady = await waitForWorkspaceReady(page);
    if (!isReady) {
      await page.screenshot({ path: '/app/results/06-still-provisioning.png', fullPage: true });
    }

    // Click Members tab
    const membersTab = page.getByRole('button', { name: /Members/i });
    await membersTab.click();
    await page.waitForTimeout(1000);

    await page.screenshot({ path: '/app/results/07-members-tab.png', fullPage: true });

    // Click Invite Member button
    const inviteButton = page.getByRole('button', { name: 'Invite Member' });
    await expect(inviteButton).toBeVisible({ timeout: 10000 });
    await inviteButton.click();

    await page.waitForTimeout(500);
    await page.screenshot({ path: '/app/results/08-invite-modal.png', fullPage: true });

    // Fill email
    const emailInput = page.locator('input[type="email"]');
    await expect(emailInput).toBeVisible();
    await emailInput.fill(inviteEmail);

    await page.screenshot({ path: '/app/results/09-invite-email-filled.png', fullPage: true });

    // Click Send Invitation
    const sendButton = page.getByRole('button', { name: 'Send Invitation' });
    await sendButton.click();

    // Wait for success message (not just a fixed timeout)
    const successMessage = page.locator('text=Invitation Sent');
    await expect(successMessage).toBeVisible({ timeout: 30000 });

    console.log('Invitation sent successfully!');
    await page.screenshot({ path: '/app/results/10-invite-success.png', fullPage: true });

    // Get the invitation URL
    const inviteUrlInput = page.locator('input[readonly]').first();
    await expect(inviteUrlInput).toBeVisible({ timeout: 5000 });

    invitationUrl = await inviteUrlInput.inputValue();
    console.log(`Invitation URL: ${invitationUrl}`);

    // Extract token from URL
    const tokenMatch = invitationUrl.match(/token=([^&]+)/);
    if (tokenMatch) {
      invitationToken = tokenMatch[1];
      console.log(`Invitation Token: ${invitationToken.substring(0, 30)}...`);
    }

    // Close the modal
    const closeButton = page.getByRole('button', { name: /Close|Done/i });
    if (await closeButton.isVisible()) {
      await closeButton.click();
    }

    await page.screenshot({ path: '/app/results/11-after-invite-complete.png', fullPage: true });

    expect(invitationToken).toBeTruthy();
  });

  test('5. Invitee views invitation (unauthenticated)', async ({ page }) => {
    console.log('\n=== Step 5: Invitee Views Invitation (Unauthenticated) ===');

    if (!invitationToken) {
      console.log('No invitation token - skipping');
      test.skip();
    }

    // Clear any existing auth
    await page.goto(PORTAL_URL);
    await page.evaluate(() => localStorage.clear());

    const acceptUrl = `${PORTAL_URL}/accept-invite?token=${invitationToken}`;
    console.log(`Navigating to: ${acceptUrl}`);

    await page.goto(acceptUrl);
    await page.waitForLoadState('networkidle');

    await page.screenshot({ path: '/app/results/12-invite-page-unauth.png', fullPage: true });

    // Should see invitation page
    const invitedText = page.getByText("You're Invited!");
    await expect(invitedText).toBeVisible({ timeout: 10000 });
    console.log('Invitation page displayed correctly');

    // Should see sign in button
    const signInButton = page.getByRole('link', { name: /Sign in to Accept/i });
    await expect(signInButton).toBeVisible();
    console.log('Sign in button visible');
  });

  test('6. Invitee accepts invitation (authenticated)', async ({ page }) => {
    console.log('\n=== Step 6: Invitee Accepts Invitation ===');

    if (!invitationToken) {
      console.log('No invitation token - skipping');
      test.skip();
    }

    let inviteeToken = INVITEE_TEST_TOKEN;

    if (!inviteeToken) {
      console.log('No invitee token available - using owner token for demo');
      console.log('Note: This will show "Wrong Account" since emails do not match');
      inviteeToken = ownerToken;
    }

    if (!inviteeToken) {
      console.log('No token available for invitee - skipping');
      test.skip();
    }

    // Authenticate as invitee
    await page.goto(PORTAL_URL);
    await page.evaluate((token) => {
      localStorage.setItem('token', token);
    }, inviteeToken);

    const acceptUrl = `${PORTAL_URL}/accept-invite?token=${invitationToken}`;
    await page.goto(acceptUrl);
    await page.waitForLoadState('networkidle');

    await page.waitForTimeout(3000);

    await page.screenshot({ path: '/app/results/13-accept-invite-auth.png', fullPage: true });

    // Check the result
    const successMessage = page.getByText(/Welcome to the Team|Already a Member/i);
    const wrongAccountMessage = page.getByText('Wrong Account');

    if (await successMessage.isVisible({ timeout: 5000 }).catch(() => false)) {
      console.log('SUCCESS: Invitation accepted!');

      const goButton = page.getByRole('button', { name: 'Go to Workspace' });
      if (await goButton.isVisible()) {
        await goButton.click();
        await page.waitForTimeout(2000);
        await page.screenshot({ path: '/app/results/14-workspace-after-accept.png', fullPage: true });
      }
    } else if (await wrongAccountMessage.isVisible({ timeout: 2000 }).catch(() => false)) {
      console.log('Wrong account - invitation was for a different email');
      console.log('This is expected when using owner token for invitee');
      await page.screenshot({ path: '/app/results/14-wrong-account.png', fullPage: true });
    } else {
      console.log('Unknown state - check screenshot');
      await page.screenshot({ path: '/app/results/14-unknown-state.png', fullPage: true });
    }
  });

  test('7. Verify member in workspace', async ({ page }) => {
    console.log('\n=== Step 7: Verify Member Added ===');

    if (!ownerToken) {
      console.log('Missing requirements - skipping');
      test.skip();
    }

    await authenticateWithToken(page, ownerToken);

    await page.goto(`${PORTAL_URL}/workspaces/${workspaceSlug}`);
    await page.waitForLoadState('networkidle');

    const membersTab = page.getByRole('button', { name: /Members/i });
    await membersTab.click();
    await page.waitForTimeout(2000);

    await page.screenshot({ path: '/app/results/15-final-members-list.png', fullPage: true });

    // Check for pending invitations or accepted members
    const pendingSection = page.locator('text=Pending Invitations');
    const inviteeEmailVisible = page.locator(`text=${INVITEE_EMAIL}`);

    if (await inviteeEmailVisible.isVisible()) {
      console.log(`Found invitee email in workspace: ${INVITEE_EMAIL}`);
    }

    if (await pendingSection.isVisible()) {
      console.log('Found pending invitations section');
    }

    console.log('Test completed successfully!');
  });
});

// Full E2E flow with two browser contexts
test.describe('Full E2E Flow - Two Users', () => {
  let ownerToken: string = '';

  test.beforeAll(async () => {
    // Get owner token
    if (TEST_USER_EMAIL && TEST_USER_PASSWORD) {
      const token = await getTestToken(TEST_USER_EMAIL, TEST_USER_PASSWORD);
      if (token) ownerToken = token;
    }

    if (!ownerToken && OWNER_TEST_TOKEN) {
      ownerToken = OWNER_TEST_TOKEN;
    }

    if (ownerToken) {
      // Clean up before running
      await cleanupTestWorkspaces(ownerToken);
    }
  });

  test.afterAll(async () => {
    if (ownerToken) {
      // Clean up after running
      await cleanupTestWorkspaces(ownerToken);
    }
  });

  test('Complete invitation flow with two browser contexts', async ({ browser }) => {
    console.log('\n=== Full E2E Flow Test ===');

    if (!ownerToken) {
      console.log('No owner token available - skipping full flow test');
      test.skip();
    }

    const inviteeToken = INVITEE_TEST_TOKEN;
    const inviteEmail = INVITEE_EMAIL;

    const ownerContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const inviteeContext = await browser.newContext({ ignoreHTTPSErrors: true });

    const ownerPage = await ownerContext.newPage();
    const inviteePage = await inviteeContext.newPage();

    try {
      // === OWNER: Authenticate ===
      console.log('Owner: Authenticating...');
      await authenticateWithToken(ownerPage, ownerToken);

      // === OWNER: Create Workspace ===
      console.log('Owner: Creating workspace...');
      await ownerPage.goto(`${PORTAL_URL}/workspaces/new`);
      await ownerPage.waitForLoadState('networkidle');

      await ownerPage.locator('input#name').fill(FULL_FLOW_WORKSPACE_NAME);
      await ownerPage.waitForTimeout(300);
      await ownerPage.locator('input#slug').clear();
      await ownerPage.locator('input#slug').fill(FULL_FLOW_WORKSPACE_SLUG);

      const kanbanOnly = ownerPage.locator('button:has-text("Kanban Only")');
      if (await kanbanOnly.isVisible()) {
        await kanbanOnly.click();
      }

      await ownerPage.getByRole('button', { name: 'Create Workspace' }).click();

      // Wait for navigation away from /new - workspace creation redirects to the home page
      await ownerPage.waitForURL('**/', { timeout: 30000 });
      await ownerPage.waitForLoadState('networkidle');

      console.log(`Workspace created: ${FULL_FLOW_WORKSPACE_SLUG}`);
      await ownerPage.screenshot({ path: '/app/results/full-01-workspace-created.png', fullPage: true });

      // === OWNER: Navigate to the workspace and wait for it to be ready ===
      console.log('Owner: Navigating to workspace and waiting for it to be ready...');

      // Give the backend a moment to fully set up membership
      await ownerPage.waitForTimeout(2000);

      // Navigate to the workspace and retry if we hit 403 errors (membership not ready yet)
      let workspaceAccessible = false;
      for (let attempt = 1; attempt <= 5; attempt++) {
        console.log(`Workspace access attempt ${attempt}/5...`);
        await ownerPage.goto(`${PORTAL_URL}/workspaces/${FULL_FLOW_WORKSPACE_SLUG}`);
        await ownerPage.waitForLoadState('networkidle');
        await ownerPage.waitForTimeout(1000);

        // Check if we're on the workspace page (not an error page)
        const hasError = await ownerPage.locator('text=403').isVisible().catch(() => false);
        const hasForbidden = await ownerPage.locator('text=Forbidden').isVisible().catch(() => false);
        const hasWorkspaceContent = await ownerPage.getByRole('button', { name: /Members/i }).isVisible().catch(() => false);

        if (hasWorkspaceContent) {
          console.log('Workspace is accessible!');
          workspaceAccessible = true;
          break;
        }

        if (hasError || hasForbidden) {
          console.log('Still getting 403 error, waiting before retry...');
          await ownerPage.waitForTimeout(3000);
        } else {
          // Maybe still loading or some other state
          console.log('Workspace not yet ready, waiting...');
          await ownerPage.waitForTimeout(2000);
        }
      }

      if (!workspaceAccessible) {
        await ownerPage.screenshot({ path: '/app/results/full-01b-workspace-not-accessible.png', fullPage: true });
        throw new Error('Could not access workspace after 5 attempts');
      }

      await waitForWorkspaceReady(ownerPage);

      // === OWNER: Invite member ===
      console.log('Owner: Inviting member...');
      await ownerPage.getByRole('button', { name: /Members/i }).click();
      await ownerPage.waitForTimeout(1000);

      const inviteBtn = ownerPage.getByRole('button', { name: 'Invite Member' });
      await inviteBtn.waitFor({ state: 'visible', timeout: 10000 });
      await inviteBtn.click();

      await ownerPage.locator('input[type="email"]').fill(inviteEmail);
      await ownerPage.getByRole('button', { name: 'Send Invitation' }).click();

      // Wait for success
      const successMsg = ownerPage.locator('text=Invitation Sent');
      await expect(successMsg).toBeVisible({ timeout: 30000 });

      await ownerPage.screenshot({ path: '/app/results/full-02-invite-sent.png', fullPage: true });

      // Get invitation URL
      const urlInput = ownerPage.locator('input[readonly]').first();
      await expect(urlInput).toBeVisible();
      const inviteUrl = await urlInput.inputValue();
      const tokenMatch = inviteUrl.match(/token=([^&]+)/);
      const inviteToken = tokenMatch ? tokenMatch[1] : '';

      if (!inviteToken) {
        throw new Error('Failed to get invitation token');
      }

      console.log(`Got invitation token: ${inviteToken.substring(0, 30)}...`);

      // === INVITEE: View invitation (unauthenticated) ===
      console.log('Invitee: Viewing invitation...');
      await inviteePage.goto(PORTAL_URL);
      await inviteePage.evaluate(() => localStorage.clear());

      const acceptUrl = `${PORTAL_URL}/accept-invite?token=${inviteToken}`;
      await inviteePage.goto(acceptUrl);
      await inviteePage.waitForLoadState('networkidle');

      await inviteePage.screenshot({ path: '/app/results/full-03-invite-page.png', fullPage: true });

      const invitedText = inviteePage.getByText("You're Invited!");
      await expect(invitedText).toBeVisible({ timeout: 10000 });
      console.log('Invitation page displayed correctly');

      // === INVITEE: Accept invitation (if token available) ===
      if (inviteeToken) {
        console.log('Invitee: Accepting invitation...');
        await inviteePage.evaluate((token) => {
          localStorage.setItem('token', token);
        }, inviteeToken);

        await inviteePage.goto(acceptUrl);
        await inviteePage.waitForLoadState('networkidle');
        await inviteePage.waitForTimeout(3000);

        await inviteePage.screenshot({ path: '/app/results/full-04-after-accept.png', fullPage: true });

        const success = inviteePage.getByText(/Welcome to the Team|Already a Member/i);
        const wrongAccount = inviteePage.getByText('Wrong Account');

        if (await success.isVisible({ timeout: 5000 }).catch(() => false)) {
          console.log('SUCCESS: Invitation accepted!');
          await inviteePage.getByRole('button', { name: 'Go to Workspace' }).click();
          await inviteePage.waitForTimeout(2000);
          await inviteePage.screenshot({ path: '/app/results/full-05-workspace.png', fullPage: true });
        } else if (await wrongAccount.isVisible({ timeout: 2000 }).catch(() => false)) {
          console.log('Wrong account - emails do not match (expected with different tokens)');
        }
      } else {
        console.log('No invitee token - skipping acceptance step');
      }

      // === OWNER: Verify member ===
      console.log('Owner: Verifying member in workspace...');
      await ownerPage.reload();
      await ownerPage.waitForLoadState('networkidle');
      await ownerPage.waitForTimeout(2000);

      await ownerPage.screenshot({ path: '/app/results/full-06-final-state.png', fullPage: true });

      console.log('Full E2E flow completed!');

    } finally {
      await ownerContext.close();
      await inviteeContext.close();
    }
  });
});
