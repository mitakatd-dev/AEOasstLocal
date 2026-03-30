// AEO Insights — Perplexity Content Script
// Tested against perplexity.ai as of March 2026

(() => {
  if (window.__aeoInsightsPerplexity) return;
  window.__aeoInsightsPerplexity = true;

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

    // Navigate to home for a fresh search if not already there
    if (!window.location.pathname.match(/^\/($|\?)/) && !window.location.pathname.match(/^\/search/)) {
      const homeLink = document.querySelector('a[href="/"]');
      if (homeLink) {
        homeLink.click();
        await wait(2000);
      }
    }

    // Perplexity uses a contenteditable div with id="ask-input"
    const input = await waitForElement(
      '#ask-input, textarea[placeholder*="Ask"], textarea[placeholder*="ask"]',
      10000
    );
    if (!input) {
      reportError('Could not find Perplexity input field');
      return;
    }

    // Type into the input using execCommand for proper framework recognition
    input.focus();
    await wait(300);
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
    document.execCommand('insertText', false, text);

    await wait(800);

    // Find submit button — Perplexity's submit button appears after typing
    // It's typically the last button in the input container with an arrow/send icon
    let sendBtn = document.querySelector('button[aria-label="Submit"]') ||
      document.querySelector('button[aria-label="Ask"]');

    // Fallback: find button near the input that has an SVG (arrow icon)
    if (!sendBtn) {
      const inputContainer = input.closest('form') || input.parentElement?.parentElement;
      if (inputContainer) {
        const btns = inputContainer.querySelectorAll('button');
        for (const btn of btns) {
          const svg = btn.querySelector('svg');
          const label = (btn.getAttribute('aria-label') || '').toLowerCase();
          // Skip known non-submit buttons
          if (label.includes('file') || label.includes('model') || label.includes('dictation') || label.includes('voice')) continue;
          if (svg && !btn.disabled) {
            sendBtn = btn;
            // Don't break — we want the last qualifying button (usually the submit)
          }
        }
      }
    }

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
    await wait(5000); // Perplexity searches the web first

    let attempts = 0;
    const maxAttempts = 150; // 2.5 min max

    while (attempts < maxAttempts) {
      // Check if still loading/streaming
      const isLoading = document.querySelector('.animate-pulse') ||
        document.querySelector('[data-testid="loading"]') ||
        document.querySelector('.streaming-animation') ||
        isStreamingActive();

      if (!isLoading && attempts > 5) {
        await wait(2000); // Extra buffer for citations
        captureResponse();
        return;
      }

      await wait(1000);
      attempts++;
    }

    captureResponse();
  }

  function isStreamingActive() {
    // Check for typing animation cursor
    return !!document.querySelector('.cursor-blink, .typing-cursor, .animate-blink');
  }

  function captureResponse() {
    const latency = Date.now() - startTime;

    // Perplexity answer — look for prose/markdown content
    const answerBlocks = document.querySelectorAll(
      '[class*="prose"], .markdown-content, [data-testid="answer-content"], .answer-text'
    );

    let responseText = '';
    let allLinks = [];

    if (answerBlocks.length > 0) {
      const answer = answerBlocks[answerBlocks.length - 1];
      responseText = answer.innerText || answer.textContent || '';
      allLinks = extractLinks(answer);
    } else {
      // Fallback: grab text from main content area
      const main = document.querySelector('main') || document.querySelector('[role="main"]');
      if (main) {
        const blocks = main.querySelectorAll('div > div > div');
        const lastFew = [...blocks].slice(-5);
        responseText = lastFew.map(b => b.innerText).join('\n');
        allLinks = lastFew.flatMap(b => extractLinks(b));
      }
    }

    // Extract Perplexity citation sources
    const citations = extractCitations();
    const allCitations = [...citations, ...allLinks.filter(l =>
      !citations.some(c => c.url === l.url)
    )];

    if (!responseText.trim()) {
      reportError('No Perplexity response found');
      return;
    }

    chrome.runtime.sendMessage({
      type: 'result',
      llm: 'perplexity',
      response: responseText.trim(),
      citations: allCitations,
      latency_ms: latency,
    });

    showNotification(`Captured! + ${allCitations.length} citations (${(latency / 1000).toFixed(1)}s)`);
  }

  function extractCitations() {
    const sources = document.querySelectorAll(
      '[data-testid="source-card"] a, .source-card a, a[class*="source"], .citation-link a'
    );

    const citations = [];
    sources.forEach(link => {
      if (link.href && !link.href.startsWith('javascript')) {
        try {
          citations.push({
            text: (link.textContent || '').trim(),
            url: link.href,
            domain: new URL(link.href).hostname.replace('www.', ''),
          });
        } catch (e) {}
      }
    });

    // Numbered [1] [2] citation links
    const numCitations = document.querySelectorAll('a[class*="citation"], sup a[href]');
    numCitations.forEach(a => {
      if (a.href && !citations.some(c => c.url === a.href)) {
        try {
          citations.push({
            text: a.textContent.trim(),
            url: a.href,
            domain: new URL(a.href).hostname.replace('www.', ''),
          });
        } catch (e) {}
      }
    });

    return citations;
  }

  function extractLinks(el) {
    return [...(el.querySelectorAll('a[href]') || [])].map(a => ({
      text: (a.textContent || '').trim(),
      url: a.href,
    })).filter(l => l.url && !l.url.startsWith('javascript'));
  }

  function reportError(msg) {
    chrome.runtime.sendMessage({
      type: 'result',
      llm: 'perplexity',
      response: '',
      citations: [],
      latency_ms: 0,
      error: msg,
    });
    showNotification(`Error: ${msg}`, true);
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
      background: ${isError ? '#ef4444' : '#f59e0b'}; color: white;
      padding: 8px 16px; border-radius: 8px; font-size: 13px;
      font-family: system-ui; box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    `;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }
})();
