// AEO Insights — Gemini Content Script
// Tested against gemini.google.com as of March 2026

(() => {
  if (window.__aeoInsightsGemini) return;
  window.__aeoInsightsGemini = true;

  let currentPromptId = null;
  let startTime = null;

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === 'submit-prompt') {
      currentPromptId = msg.promptId;
      submitPrompt(msg.text);
      sendResponse({ ok: true });
    }
  });

  async function submitPrompt(text) {
    startTime = Date.now();
    showNotification('Preparing prompt...');

    // Start new chat
    const newChatBtn = document.querySelector('a[href="/app"]') ||
      document.querySelector('button[aria-label="New chat"]');
    if (newChatBtn) {
      newChatBtn.click();
      await wait(2000);
    }

    // Gemini uses Quill editor — a contenteditable div with class "ql-editor"
    const input = await waitForElement(
      '.ql-editor[contenteditable="true"], [aria-label="Enter a prompt for Gemini"]',
      10000
    );
    if (!input) {
      reportError('Could not find Gemini input field');
      return;
    }

    // Type into Quill contenteditable using execCommand
    input.focus();
    await wait(300);
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
    document.execCommand('insertText', false, text);
    // Remove blank class so Gemini recognizes content
    input.classList.remove('ql-blank');

    await wait(800);

    // Gemini send button: aria-label="Send message", class includes "send-button"
    const sendBtn = document.querySelector('button[aria-label="Send message"]') ||
      document.querySelector('button.send-button') ||
      document.querySelector('.send-button-container button');

    if (sendBtn && !sendBtn.disabled) {
      sendBtn.click();
      showNotification('Prompt sent, waiting for response...');
    } else {
      // Try Enter
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }));
      showNotification('Sent via Enter key...');
    }

    await waitForResponse();
  }

  async function waitForResponse() {
    await wait(3000);

    let attempts = 0;
    const maxAttempts = 120;

    while (attempts < maxAttempts) {
      // Gemini shows loading indicators while generating
      const isLoading = document.querySelector('mat-progress-bar') ||
        document.querySelector('.loading-indicator') ||
        document.querySelector('.response-container loading') ||
        document.querySelector('[data-test-id="loading"]');

      // Also check if the response is still being typed (last response element changing)
      if (!isLoading && attempts > 5) {
        await wait(1500);
        captureResponse();
        return;
      }

      await wait(1000);
      attempts++;
    }

    captureResponse();
  }

  function captureResponse() {
    const latency = Date.now() - startTime;

    // Gemini response selectors — try multiple patterns
    const responses = document.querySelectorAll(
      '.model-response-text .markdown, .model-response-text, .response-content, message-content[data-content-type="response"]'
    );

    let responseEl = responses[responses.length - 1];

    // Fallback: look for any markdown content in the conversation
    if (!responseEl) {
      const markdowns = document.querySelectorAll('.markdown-main-panel, .response-container .markdown');
      responseEl = markdowns[markdowns.length - 1];
    }

    // Fallback: conversation messages
    if (!responseEl) {
      const msgs = document.querySelectorAll('.conversation-container .message-content, [data-message-id] .text-content');
      responseEl = msgs[msgs.length - 1];
    }

    if (!responseEl) {
      reportError('No Gemini response found');
      return;
    }

    const responseText = responseEl.innerText || responseEl.textContent || '';
    const links = [...(responseEl.querySelectorAll('a[href]') || [])].map(a => ({
      text: a.textContent,
      url: a.href,
    }));

    chrome.runtime.sendMessage({
      type: 'result',
      llm: 'gemini',
      response: responseText.trim(),
      citations: links,
      latency_ms: latency,
    });

    showNotification(`Captured! (${(latency / 1000).toFixed(1)}s)`);
  }

  function reportError(msg) {
    chrome.runtime.sendMessage({
      type: 'result',
      llm: 'gemini',
      response: '',
      citations: [],
      latency_ms: 0,
      error: msg,
    });
    showNotification(`Error: ${msg}`, true);
  }

  function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function waitForElement(selector, timeout = 10000) {
    return new Promise((resolve) => {
      const el = document.querySelector(selector);
      if (el) return resolve(el);
      const observer = new MutationObserver(() => {
        const el = document.querySelector(selector);
        if (el) { observer.disconnect(); resolve(el); }
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
      background: ${isError ? '#ef4444' : '#10b981'}; color: white;
      padding: 8px 16px; border-radius: 8px; font-size: 13px;
      font-family: system-ui; box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    `;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }
})();
