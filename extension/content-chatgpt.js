// AEO Insights — ChatGPT Content Script (v3 — single-prompt-at-a-time)
// Key fix: tracks message count at submission time so we wait for a NEW response,
// not accidentally capture the previous one.

(() => {
  // Remove old listener if re-injected
  if (window.__aeoCleanup) {
    window.__aeoCleanup();
  }

  let currentPromptId = null;
  let startTime = null;
  let messageCountAtSubmit = 0;

  function onMessage(msg, sender, sendResponse) {
    if (msg.type === 'submit-prompt') {
      currentPromptId = msg.promptId;
      submitPrompt(msg.text);
      sendResponse({ ok: true });
    }
  }

  chrome.runtime.onMessage.addListener(onMessage);

  // Store cleanup function so next injection can remove this listener
  window.__aeoCleanup = () => {
    chrome.runtime.onMessage.removeListener(onMessage);
  };

  async function submitPrompt(text) {
    startTime = Date.now();
    showNotification(`Prompt #${currentPromptId}: preparing...`);

    // Count existing assistant messages BEFORE submitting
    messageCountAtSubmit = document.querySelectorAll('[data-message-author-role="assistant"]').length;

    // Find the input field — ChatGPT uses ProseMirror contenteditable
    const input = await waitForElement('#prompt-textarea', 15000);
    if (!input) {
      reportError('Could not find ChatGPT input field');
      return;
    }

    // Focus and clear
    input.focus();
    await wait(500);

    // Select all and delete existing content
    document.execCommand('selectAll', false, null);
    await wait(100);
    document.execCommand('delete', false, null);
    await wait(300);

    // Type the prompt character-by-character would be too slow for long prompts.
    // Use insertText which ProseMirror handles correctly.
    document.execCommand('insertText', false, text);
    await wait(1000);

    // Verify text was inserted
    const insertedText = input.innerText || input.textContent || '';
    if (insertedText.trim().length === 0) {
      showNotification('Retrying text insertion...', true);
      // Fallback: set innerHTML directly then trigger input event
      input.innerHTML = `<p>${text}</p>`;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await wait(500);
    }

    showNotification('Clicking send...');

    // Find and click the send button
    const sent = await clickSendButton(input);
    if (!sent) {
      reportError('Could not find or click send button');
      return;
    }

    showNotification('Prompt sent, waiting for NEW response...');
    await waitForNewResponse();
  }

  async function clickSendButton(input) {
    // Try multiple selectors for the send button
    const selectors = [
      '[data-testid="send-button"]',
      'button[aria-label="Send prompt"]',
      'button[aria-label="Send"]',
    ];

    for (const sel of selectors) {
      const btn = document.querySelector(sel);
      if (btn && !btn.disabled) {
        btn.click();
        await wait(500);
        return true;
      }
    }

    // Fallback: press Enter on the input
    input.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true, cancelable: true,
    }));
    await wait(1000);

    // Check if it actually sent — a new assistant message or streaming indicator should appear
    const newCount = document.querySelectorAll('[data-message-author-role="assistant"]').length;
    const streaming = document.querySelector('[data-testid="stop-button"]') ||
      document.querySelector('button[aria-label="Stop generating"]');

    return newCount > messageCountAtSubmit || !!streaming;
  }

  async function waitForNewResponse() {
    // Phase 1: Wait for a NEW assistant message to appear (up to 30s)
    let newMessageFound = false;
    for (let i = 0; i < 60; i++) {
      const currentCount = document.querySelectorAll('[data-message-author-role="assistant"]').length;
      if (currentCount > messageCountAtSubmit) {
        newMessageFound = true;
        break;
      }
      // Also check for streaming indicator (response started but message element not yet counted)
      const streaming = document.querySelector('[data-testid="stop-button"]') ||
        document.querySelector('button[aria-label="Stop generating"]');
      if (streaming) {
        newMessageFound = true;
        break;
      }
      await wait(500);
      if (i % 10 === 0 && i > 0) {
        showNotification(`Waiting for response to start... (${i / 2}s)`);
      }
    }

    if (!newMessageFound) {
      reportError('No new response appeared after 30 seconds');
      return;
    }

    // Phase 2: Wait for streaming to FINISH
    showNotification('Response started, waiting for completion...');
    let stableCount = 0;
    const maxWait = 180; // 3 minutes max

    for (let i = 0; i < maxWait; i++) {
      const streaming = document.querySelector('[data-testid="stop-button"]') ||
        document.querySelector('button[aria-label="Stop generating"]') ||
        document.querySelector('button[aria-label="Stop streaming"]');

      if (!streaming) {
        stableCount++;
        // Need 3 consecutive non-streaming checks (3 seconds) to confirm done
        if (stableCount >= 3) {
          await wait(1000); // Final stabilization wait
          captureResponse();
          return;
        }
      } else {
        stableCount = 0; // Reset — still streaming
      }

      await wait(1000);
      if (i % 15 === 0 && i > 0) {
        showNotification(`Generating response... (${i}s)`);
      }
    }

    // Timeout — capture whatever we have
    showNotification('Response timeout — capturing partial', true);
    captureResponse();
  }

  function captureResponse() {
    const latency = Date.now() - startTime;

    // Get all assistant messages and take the LAST one (the newest)
    const messages = document.querySelectorAll('[data-message-author-role="assistant"]');
    const lastMsg = messages[messages.length - 1];

    if (!lastMsg) {
      reportError('No response element found');
      return;
    }

    // Get the text content from the markdown container
    const responseEl = lastMsg.querySelector('.markdown') || lastMsg;
    const response = responseEl.innerText || responseEl.textContent || '';

    if (response.trim().length === 0) {
      reportError('Response was empty');
      return;
    }

    // Extract any links/citations
    const links = [...(responseEl.querySelectorAll('a[href]') || [])].map(a => ({
      text: a.textContent,
      url: a.href,
    })).filter(l => l.url && !l.url.startsWith('javascript'));

    showNotification(`Captured! (${(latency / 1000).toFixed(1)}s, ${response.length} chars)`);

    try {
      chrome.runtime.sendMessage({
        type: 'result',
        llm: 'chatgpt',
        response: response.trim(),
        citations: links,
        latency_ms: latency,
      });
    } catch (e) {
      console.error('AEO: Failed to send result to background:', e);
    }
  }

  function reportError(msg) {
    showNotification(`Error: ${msg}`, true);
    try {
      chrome.runtime.sendMessage({
        type: 'result',
        llm: 'chatgpt',
        response: '',
        citations: [],
        latency_ms: 0,
        error: msg,
      });
    } catch (e) {
      console.error('AEO: Failed to send error to background:', e);
    }
  }

  function waitForElement(selector, timeout = 10000) {
    return new Promise((resolve) => {
      const el = document.querySelector(selector);
      if (el) return resolve(el);
      const observer = new MutationObserver(() => {
        const found = document.querySelector(selector);
        if (found) { observer.disconnect(); resolve(found); }
      });
      observer.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => { observer.disconnect(); resolve(null); }, timeout);
    });
  }

  function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

  function showNotification(text, isError = false) {
    document.querySelectorAll('.aeo-notification').forEach(el => el.remove());
    const el = document.createElement('div');
    el.className = 'aeo-notification';
    el.textContent = `AEO: ${text}`;
    el.style.cssText = `
      position: fixed; top: 10px; right: 10px; z-index: 99999;
      background: ${isError ? '#ef4444' : '#6366f1'}; color: white;
      padding: 8px 16px; border-radius: 8px; font-size: 13px;
      font-family: system-ui; box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    `;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 8000);
  }
})();
