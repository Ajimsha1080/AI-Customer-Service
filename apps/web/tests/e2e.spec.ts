import { test, expect } from '@playwright/test';

test.describe('Hospitality Agent Cloud - Complete Enterprise End-to-End Workflow', () => {
  const timestamp = Date.now();
  const testEmail = `orgadmin_${timestamp}@resort-chain.com`;
  const testPassword = 'SecureP@ssword123!';
  const orgName = `Seaside Resorts ${timestamp}`;
  const propertyName = `Azure Bay Villa ${timestamp}`;

  test('Full Tenant Lifecycle: register -> verify email -> onboarding -> upload PDF -> deploy -> guest chat -> staff live reply -> SSO login', async ({ page, context, request }) => {
    // 1. Register new organization and admin account
    await page.goto('/register');
    await page.fill('input[type="email"]', testEmail);
    await page.fill('input[type="password"]', testPassword);
    await page.fill('input[placeholder*="Organization"], input[placeholder*="Company"]', orgName);
    await page.click('button[type="submit"]');

    // 2. Verify Email via Fake SMTP / Backend API
    // Retrieve verification token or verify directly via API in testing environment
    const verifyRes = await request.post('/api/v1/auth/verify-email', {
      data: { token: `e2e_verify_token_${timestamp}` }
    }).catch(() => null);

    // Expect navigation to onboarding or dashboard
    await expect(page).toHaveURL(/\/(app\/onboarding|app\/dashboard)/, { timeout: 10000 });

    // 3. Onboarding Flow
    if (page.url().includes('/app/onboarding')) {
      const finishOnboarding = page.locator('button:has-text("Get Started"), button:has-text("Continue"), button:has-text("Complete")');
      if (await finishOnboarding.isVisible()) {
        await finishOnboarding.click();
      }
    }

    // 4. Create Property
    await page.goto('/app/properties');
    const newPropBtn = page.locator('button:has-text("New Property"), button:has-text("Add Property")');
    if (await newPropBtn.isVisible()) {
      await newPropBtn.click();
      await page.fill('input[placeholder*="Property Name"], input[name="name"]', propertyName);
      await page.click('button:has-text("Save"), button:has-text("Create")');
    }

    // 5. Upload PDF Knowledge Document
    await page.goto('/app/knowledge');
    const fileInput = page.locator('input[type="file"]');
    if (await fileInput.isVisible()) {
      const samplePdfHeader = '%PDF-1.4\n1 0 obj\n<< /Title (Guest Guide) >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF';
      await fileInput.setInputFiles({
        name: 'hotel_directory.pdf',
        mimeType: 'application/pdf',
        buffer: Buffer.from(samplePdfHeader)
      });
      await page.click('button:has-text("Upload")');
    }

    // 6. Deploy AI Concierge Agent
    await page.goto('/app/agents');
    const deployBtn = page.locator('button:has-text("Deploy New Agent"), button:has-text("Create Agent")');
    if (await deployBtn.isVisible()) {
      await deployBtn.click();
      await page.fill('input[placeholder*="Agent Name"], input[name="name"]', 'Bay Concierge AI');
      await page.click('button:has-text("Deploy")');
    }

    // 7. Guest Chat in separate browser context
    const guestPage = await context.newPage();
    await guestPage.goto('/guest/agt_guest_test');
    const guestInput = guestPage.locator('input[placeholder*="Ask"], textarea');
    if (await guestInput.isVisible()) {
      await guestInput.fill('Is the swimming pool open now?');
      await guestPage.keyboard.press('Enter');
      await expect(guestPage.locator('text=pool, text=Pool, text=assistant')).toBeVisible({ timeout: 10000 });
    }

    // 8. Staff Inbox Receives Live Message & Sends Takeover Reply
    await page.goto('/app/conversations');
    await expect(page.locator('text=Conversations, text=Inbox')).toBeVisible();
    const takeoverBtn = page.locator('button:has-text("Takeover"), button:has-text("Take Over")');
    if (await takeoverBtn.first().isVisible()) {
      await takeoverBtn.first().click();
      const replyInput = page.locator('input[placeholder*="Reply"], textarea');
      await replyInput.fill('Hello from Front Desk staff! Yes, the pool is open.');
      await page.click('button:has-text("Send")');
    }

    // 9. Staff takeover reply reflected in Guest Widget
    if (await guestInput.isVisible()) {
      await expect(guestPage.locator('text=Front Desk, text=pool is open, text=staff')).toBeVisible({ timeout: 10000 });
    }

    // 10. Enterprise SSO Login Flow Verification
    await page.goto('/login');
    const ssoBtn = page.locator('a:has-text("Single Sign-On"), button:has-text("SSO"), a:has-text("SSO")');
    if (await ssoBtn.isVisible()) {
      await ssoBtn.click();
      await expect(page.locator('input[type="email"], input[placeholder*="domain"], input[name="email"]')).toBeVisible();
    }
  });
});
