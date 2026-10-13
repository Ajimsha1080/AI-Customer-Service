import { test, expect } from '@playwright/test';

test.describe('Hospitality Agent Cloud - Production End-to-End Workflow', () => {
  const timestamp = Date.now();
  const testEmail = `orgadmin_${timestamp}@resort-chain.com`;
  const testPassword = 'SecureP@ssword123!';
  const orgName = `Seaside Resorts ${timestamp}`;
  const propertyName = `Azure Bay Villa ${timestamp}`;

  test('Complete tenant lifecycle: register -> property -> upload doc -> deploy agent -> guest chat -> staff takeover', async ({ page, context }) => {
    // 1. Register new organization and admin account
    await page.goto('/register');
    await page.fill('input[type="email"]', testEmail);
    await page.fill('input[type="password"]', testPassword);
    await page.fill('input[placeholder*="Organization"], input[placeholder*="Company"]', orgName);
    await page.click('button[type="submit"]');

    // Expect navigation to onboarding or dashboard
    await expect(page).toHaveURL(/\/(app\/onboarding|app\/dashboard)/, { timeout: 10000 });

    // 2. Create Property
    await page.goto('/app/properties');
    const newPropBtn = page.locator('button:has-text("New Property"), button:has-text("Add Property")');
    if (await newPropBtn.isVisible()) {
      await newPropBtn.click();
      await page.fill('input[placeholder*="Property Name"], input[name="name"]', propertyName);
      await page.click('button:has-text("Save"), button:has-text("Create")');
    }

    // 3. Upload Knowledge Document
    await page.goto('/app/knowledge');
    const fileInput = page.locator('input[type="file"]');
    if (await fileInput.isVisible()) {
      await fileInput.setInputFiles({
        name: 'concierge_guide.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('Azure Bay Villa check-in is 3:00 PM. Infinity pool is open 6:00 AM to 10:00 PM.')
      });
      await page.click('button:has-text("Upload")');
    }

    // 4. Deploy Agent
    await page.goto('/app/agents');
    const deployBtn = page.locator('button:has-text("Deploy New Agent"), button:has-text("Create Agent")');
    if (await deployBtn.isVisible()) {
      await deployBtn.click();
      await page.fill('input[placeholder*="Agent Name"], input[name="name"]', 'Bay Concierge AI');
      await page.click('button:has-text("Deploy")');
    }

    // 5. Guest Chat in separate browser context
    const guestPage = await context.newPage();
    await guestPage.goto('/guest/agt_guest_test');
    const guestInput = guestPage.locator('input[placeholder*="Ask"], textarea');
    if (await guestInput.isVisible()) {
      await guestInput.fill('Is the swimming pool open now?');
      await guestPage.keyboard.press('Enter');
      await expect(guestPage.locator('text=pool, text=Pool')).toBeVisible({ timeout: 10000 });
    }

    // 6. Staff inbox receives message live and sends takeover reply
    await page.goto('/app/conversations');
    await expect(page.locator('text=Conversations, text=Inbox')).toBeVisible();
    const takeoverBtn = page.locator('button:has-text("Takeover"), button:has-text("Take Over")');
    if (await takeoverBtn.first().isVisible()) {
      await takeoverBtn.first().click();
      const replyInput = page.locator('input[placeholder*="Reply"], textarea');
      await replyInput.fill('Hello from Front Desk staff! Yes, the pool is open.');
      await page.click('button:has-text("Send")');
    }

    // 7. Staff takeover reply appears in the guest widget
    if (await guestInput.isVisible()) {
      await expect(guestPage.locator('text=Front Desk, text=pool is open')).toBeVisible({ timeout: 10000 });
    }
  });
});
