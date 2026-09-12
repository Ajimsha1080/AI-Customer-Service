/**
 * Hospitality Agent Cloud - Embeddable Web Chat & Voice Widget
 * Premium zero-dependency widget snippet for hotel/resort guest websites.
 */
(function () {
  const currentScript = document.currentScript || Array.from(document.querySelectorAll('script')).pop();
  const agentId = currentScript ? (currentScript.getAttribute('data-agent-id') || 'agt_hostel_01') : 'agt_hostel_01';
  const apiBase = currentScript ? (currentScript.getAttribute('data-api-base') || 'http://localhost:8000') : 'http://localhost:8000';
  const orgId = currentScript ? (currentScript.getAttribute('data-org-id') || 'org_azure_group') : 'org_azure_group';
  const propertyId = currentScript ? (currentScript.getAttribute('data-property-id') || 'prop_azure_palm_resort') : 'prop_azure_palm_resort';

  let widgetState = {
    isOpen: false,
    messages: [
      { sender: 'agent', text: 'Welcome to Azure Hostel! I am your Hostel AI Assistant. Ask me anything about mess menu, timings, rules, or room maintenance.' }
    ],
    isListening: false
  };

  // Inject Stylesheet
  const styleTag = document.createElement('style');
  styleTag.innerHTML = `
    .hac-widget-launcher {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #ffffff;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 10px 25px rgba(15, 23, 42, 0.4);
      cursor: pointer;
      z-index: 999999;
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      font-size: 24px;
    }
    .hac-widget-launcher:hover {
      transform: scale(1.05);
      box-shadow: 0 14px 30px rgba(15, 23, 42, 0.5);
    }
    .hac-widget-window {
      position: fixed;
      bottom: 96px;
      right: 24px;
      width: 380px;
      max-width: calc(100vw - 32px);
      height: 580px;
      max-height: calc(100vh - 120px);
      background: #ffffff;
      border-radius: 20px;
      box-shadow: 0 16px 48px rgba(15, 23, 42, 0.22);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      border: 1px solid #e2e8f0;
    }
    .hac-widget-header {
      background: #0f172a;
      color: #ffffff;
      padding: 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .hac-widget-header-title {
      font-weight: 600;
      font-size: 15px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .hac-widget-status-dot {
      width: 8px;
      height: 8px;
      background: #10b981;
      border-radius: 50%;
    }
    .hac-widget-messages {
      flex: 1;
      padding: 16px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: #f8fafc;
    }
    .hac-message-bubble {
      max-width: 82%;
      padding: 10px 14px;
      border-radius: 14px;
      font-size: 13.5px;
      line-height: 1.45;
      word-wrap: break-word;
    }
    .hac-message-agent {
      background: #ffffff;
      color: #0f172a;
      align-self: flex-start;
      border: 1px solid #e2e8f0;
      border-bottom-left-radius: 2px;
    }
    .hac-message-user {
      background: #0f172a;
      color: #ffffff;
      align-self: flex-end;
      border-bottom-right-radius: 2px;
    }
    .hac-tool-activity {
      align-self: flex-start;
      font-size: 11px;
      color: #10b981;
      font-style: italic;
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .hac-quick-actions {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding: 8px 12px;
      background: #ffffff;
      border-top: 1px solid #f1f5f9;
    }
    .hac-quick-btn {
      white-space: nowrap;
      background: #f1f5f9;
      color: #0f172a;
      border: 1px solid #cbd5e1;
      border-radius: 16px;
      padding: 4px 10px;
      font-size: 11.5px;
      font-weight: 500;
      cursor: pointer;
    }
    .hac-quick-btn:hover {
      background: #e2e8f0;
    }
    .hac-widget-input-area {
      padding: 12px;
      background: #ffffff;
      border-top: 1px solid #e2e8f0;
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .hac-widget-input {
      flex: 1;
      border: 1px solid #cbd5e1;
      border-radius: 20px;
      padding: 8px 14px;
      font-size: 13.5px;
      outline: none;
    }
    .hac-widget-send-btn, .hac-widget-voice-btn {
      background: #0f172a;
      color: white;
      border: none;
      border-radius: 50%;
      width: 36px;
      height: 36px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
  `;
  document.head.appendChild(styleTag);

  // Render Launcher Button
  const launcherEl = document.createElement('div');
  launcherEl.className = 'hac-widget-launcher';
  launcherEl.innerHTML = `💬`;
  document.body.appendChild(launcherEl);

  // Render Window Container
  const windowEl = document.createElement('div');
  windowEl.className = 'hac-widget-window';
  windowEl.style.display = 'none';
  windowEl.innerHTML = `
    <div class="hac-widget-header">
      <div class="hac-widget-header-title">
        <span class="hac-widget-status-dot"></span>
        <span>Hostel AI Assistant</span>
      </div>
      <button id="hac-close-btn" style="background:none;border:none;color:white;cursor:pointer;font-size:18px;">✕</button>
    </div>
    <div class="hac-widget-messages" id="hac-messages-container"></div>
    <div class="hac-quick-actions">
      <button class="hac-quick-btn" data-query="🍽️ What's for dinner today?">🍽️ Dinner Menu</button>
      <button class="hac-quick-btn" data-query="⏰ What time is dinner?">⏰ Timings</button>
      <button class="hac-quick-btn" data-query="📜 Visitor Rules">📜 Rules</button>
      <button class="hac-quick-btn" data-query="🔧 My fan isn't working.">🔧 Maintenance</button>
    </div>
    <div class="hac-widget-input-area">
      <input type="text" class="hac-widget-input" id="hac-input-field" placeholder="Ask about hostel menu, timings, rules..." />
      <button class="hac-widget-voice-btn" id="hac-voice-btn" title="Voice Input">🎙️</button>
      <button class="hac-widget-send-btn" id="hac-send-btn" title="Send Message">➔</button>
    </div>
  `;
  document.body.appendChild(windowEl);

  const messagesContainer = document.getElementById('hac-messages-container');
  const inputField = document.getElementById('hac-input-field');

  function renderMessages() {
    messagesContainer.innerHTML = '';
    widgetState.messages.forEach(msg => {
      const msgBubble = document.createElement('div');
      if (msg.isActivity) {
        msgBubble.className = 'hac-tool-activity';
        msgBubble.innerText = `⚡ ${msg.text}`;
      } else {
        msgBubble.className = `hac-message-bubble ${msg.sender === 'user' ? 'hac-message-user' : 'hac-message-agent'}`;
        msgBubble.innerText = msg.text;
      }
      messagesContainer.appendChild(msgBubble);
    });
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  async function sendMessage(text) {
    if (!text.trim()) return;
    widgetState.messages.push({ sender: 'user', text: text });
    renderMessages();
    inputField.value = '';

    let toolNotice = 'Hostel AI processing...';
    const lower = text.toLowerCase();
    if (lower.includes('food') || lower.includes('dinner') || lower.includes('menu')) {
      toolNotice = 'Checking today\'s mess menu & timings...';
    } else if (lower.includes('rule') || lower.includes('visitor') || lower.includes('gate')) {
      toolNotice = 'Checking hostel rules & policies...';
    } else if (lower.includes('fan') || lower.includes('maintenance') || lower.includes('repair')) {
      toolNotice = 'Creating maintenance ticket...';
    }

    widgetState.messages.push({ sender: 'agent', text: toolNotice, isActivity: true });
    renderMessages();

    try {
      const res = await fetch(`${apiBase}/api/v1/agents/${agentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          organization_id: orgId,
          property_id: propertyId,
          message: text,
          channel: 'web_widget'
        })
      });
      const data = await res.json();
      widgetState.messages.pop(); // Remove activity notice
      widgetState.messages.push({ sender: 'agent', text: data.response || 'Thank you for reaching out.' });
    } catch (e) {
      widgetState.messages.pop();
      widgetState.messages.push({ sender: 'agent', text: 'Apologies, I encountered a temporary connection issue. Connecting you with hostel office.' });
    }
    renderMessages();
  }

  // Event Listeners
  launcherEl.addEventListener('click', () => {
    widgetState.isOpen = !widgetState.isOpen;
    windowEl.style.display = widgetState.isOpen ? 'flex' : 'none';
    if (widgetState.isOpen) {
      renderMessages();
      inputField.focus();
    }
  });

  document.getElementById('hac-close-btn').addEventListener('click', () => {
    widgetState.isOpen = false;
    windowEl.style.display = 'none';
  });

  document.getElementById('hac-send-btn').addEventListener('click', () => sendMessage(inputField.value));
  inputField.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage(inputField.value);
  });

  document.querySelectorAll('.hac-quick-btn').forEach(btn => {
    btn.addEventListener('click', () => sendMessage(btn.getAttribute('data-query')));
  });

  document.getElementById('hac-voice-btn').addEventListener('click', () => {
    alert("Voice Gateway active: Listening on browser microphone...");
  });
})();
