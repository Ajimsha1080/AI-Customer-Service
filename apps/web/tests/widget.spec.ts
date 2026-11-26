import { test, expect } from '@playwright/test';

test.describe('Hospitality Agent Cloud - Embeddable Widget 2-Turn Conversation', () => {
  test('Widget on a blank page completes a 2-turn conversation against the API', async ({ page }) => {
    // Mock the backend API endpoints to simulate the real API behavior in the browser environment
    let turns = 0;
    const agentId = 'agt_e2e_widget_test';
    const fakeConvId = 'conv_e2e_123456';
    const fakeGuestToken = 'gst_token_signed_xyz987';

    await page.route(`**/api/v1/public/agents/${agentId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: agentId,
          name: 'Grand Bay Concierge',
          display_name: 'Grand Bay Concierge',
          greeting: 'Welcome to Grand Bay Resort! How can I assist your stay?',
          languages: ['English', 'Spanish'],
          branding: { name: 'Grand Bay Concierge', tone: 'Helpful' }
        })
      });
    });

    await page.route(`**/api/v1/agents/${agentId}/chat`, async (route) => {
      turns += 1;
      const postData = JSON.parse(route.request().postData() || '{}');
      expect(postData.channel).toBe('web_widget');

      if (turns === 1) {
        expect(postData.message).toBe('Hello, what time is check-in?');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            conversation_id: fakeConvId,
            guest_token: fakeGuestToken,
            response: 'Check-in begins at 3:00 PM.'
          })
        });
      } else {
        expect(postData.conversation_id).toBe(fakeConvId);
        expect(postData.guest_token).toBe(fakeGuestToken);
        expect(postData.message).toBe('Is late check-out available?');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            conversation_id: fakeConvId,
            guest_token: fakeGuestToken,
            response: 'Late check-out can be requested subject to room availability.'
          })
        });
      }
    });

    // Load blank HTML page with widget script injected
    await page.setContent(`
      <!DOCTYPE html>
      <html>
        <head>
          <title>Guest Partner Website</title>
        </head>
        <body>
          <h1>Welcome to Hotel Partner Website</h1>
          <script src="/widget.js" data-agent-key="${agentId}" data-api-base="http://localhost:8000"></script>
        </body>
      </html>
    `, { waitUntil: 'domcontentloaded' });

    // Inject the actual widget.js script directly into the page
    await page.addScriptTag({
      path: './public/widget.js'
    });

    // 1. Verify launcher is present and open it
    const launcher = page.locator('#hac-launcher');
    await expect(launcher).toBeVisible({ timeout: 5000 });
    await launcher.click();

    // 2. Verify widget window is open and initial greeting is displayed
    const windowEl = page.locator('#hac-window');
    await expect(windowEl).toBeVisible();

    // 3. Turn 1: Send "Hello, what time is check-in?"
    const input = page.locator('#hac-input-field');
    const sendBtn = page.locator('#hac-send-btn');
    await input.fill('Hello, what time is check-in?');
    await sendBtn.click();

    // Verify Agent reply for turn 1
    await expect(page.locator('.hac-message-agent:has-text("Check-in begins at 3:00 PM.")')).toBeVisible({ timeout: 5000 });

    // Verify sessionStorage has stored conversation_id and guest_token
    const storedConv = await page.evaluate((id) => sessionStorage.getItem(`hac_conv_${id}`), agentId);
    const storedToken = await page.evaluate((id) => sessionStorage.getItem(`hac_token_${id}`), agentId);
    expect(storedConv).toBe(fakeConvId);
    expect(storedToken).toBe(fakeGuestToken);

    // 4. Turn 2: Send "Is late check-out available?"
    await input.fill('Is late check-out available?');
    await sendBtn.click();

    // Verify Agent reply for turn 2
    await expect(page.locator('.hac-message-agent:has-text("Late check-out can be requested")')).toBeVisible({ timeout: 5000 });
    expect(turns).toBe(2);
  });
});
