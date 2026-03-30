// AEO Insights — Background Service Worker (v3 — strict sequencing)
// Key changes from v2:
// - processingPromptId tracks WHICH prompt we're waiting for, not just a boolean
// - Ignores stale results from previous prompts
// - Longer response timeout (3 minutes for ChatGPT thinking models)
// - Delay between prompts increased to 8-15 seconds

const DEFAULT_API = 'http://localhost:8000';

// State (also persisted to chrome.storage.local)
let queue = [];
let currentIndex = 0;
let isRunning = false;
let apiBase = DEFAULT_API;
let batchId = null;
let isProcessing = false; // MUTEX: prevents concurrent processNext()
let processingPromptId = null; // Which prompt we're actively waiting on

// Restore state on worker restart
chrome.storage.local.get(['apiBase', 'queue', 'currentIndex', 'isRunning', 'batchId'], (data) => {
  if (data.apiBase) apiBase = data.apiBase;
  if (data.queue) queue = data.queue;
  if (data.currentIndex !== undefined) currentIndex = data.currentIndex;
  if (data.batchId) batchId = data.batchId;
  // Don't auto-resume — user must click Start again after worker restart
  isRunning = false;
});

function persistState() {
  chrome.storage.local.set({ queue, currentIndex, isRunning, batchId });
}

// Keep service worker alive while running
function startKeepAlive() {
  chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
}
function stopKeepAlive() {
  chrome.alarms.clear('keepalive');
}
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepalive' && !isRunning) stopKeepAlive();
});

// Response timeout — if content script doesn't report back in 90s, skip
let responseTimer = null;
function startResponseTimeout() {
  clearResponseTimeout();
  responseTimer = setTimeout(() => {
    console.warn('AEO: Response timeout — skipping prompt', currentIndex);
    isProcessing = false;
    currentIndex++;
    persistState();
    if (isRunning && currentIndex < queue.length) {
      setTimeout(() => processNext(), 3000);
    } else if (currentIndex >= queue.length) {
      finishBatch();
    }
  }, 180000); // 3 minutes (ChatGPT thinking models can take a while)
}
function clearResponseTimeout() {
  if (responseTimer) { clearTimeout(responseTimer); responseTimer = null; }
}

// Message handler
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const handler = handlers[msg.type];
  if (!handler) return false;

  try {
    const result = handler(msg, sender);
    if (result instanceof Promise) {
      result
        .then(r => sendResponse(r))
        .catch(e => sendResponse({ error: e.message }));
      return true;
    }
    sendResponse(result);
  } catch (e) {
    sendResponse({ error: e.message });
  }
  return false;
});

const handlers = {
  'get-status': () => ({
    isRunning,
    isProcessing,
    processingPromptId,
    queueLength: queue.length,
    currentIndex,
    currentPrompt: queue[currentIndex] || null,
    batchId,
  }),

  'set-api-base': (msg) => {
    apiBase = msg.apiBase || DEFAULT_API;
    chrome.storage.local.set({ apiBase });
    return { ok: true };
  },

  'load-queue': async (msg) => {
    try {
      const platforms = msg.platforms || ['chatgpt'];
      const llmsParam = `?llms=${platforms.join(',')}`;
      const res = await fetch(`${apiBase}/api/extension/queue${llmsParam}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      queue = data.prompts || [];
      currentIndex = 0;
      batchId = data.batch_id || null;
      isRunning = false;
      isProcessing = false;
      persistState();
      return { ok: true, count: queue.length, batchId };
    } catch (e) {
      return { error: `Cannot reach backend: ${e.message}` };
    }
  },

  'start': () => {
    if (queue.length === 0) return { error: 'Queue is empty. Load prompts first.' };
    if (currentIndex >= queue.length) return { error: 'Queue complete. Reload to run again.' };
    isRunning = true;
    isProcessing = false;
    startKeepAlive();
    persistState();
    processNext();
    return { ok: true };
  },

  'pause': () => {
    isRunning = false;
    isProcessing = false;
    clearResponseTimeout();
    stopKeepAlive();
    persistState();
    return { ok: true };
  },

  'skip': () => {
    clearResponseTimeout();
    isProcessing = false;
    if (currentIndex < queue.length - 1) {
      currentIndex++;
      persistState();
      if (isRunning) processNext();
    }
    return { ok: true };
  },

  // Content script reports a captured result
  'result': async (msg) => {
    clearResponseTimeout();

    const prompt = queue[currentIndex];
    if (!prompt) {
      isProcessing = false;
      processingPromptId = null;
      return { error: 'No current prompt' };
    }

    // Ignore stale results from a previous prompt
    if (!isProcessing) {
      console.warn('AEO: Ignoring result — not currently processing');
      return { error: 'Not processing' };
    }

    const payload = {
      batch_id: batchId,
      prompt_id: prompt.id,
      llm: msg.llm,
      raw_response: msg.response || '',
      citations: msg.citations || [],
      latency_ms: msg.latency_ms || 0,
      source: 'web_portal',
      error: msg.error || null,
    };

    try {
      await fetch(`${apiBase}/api/extension/result`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (e) {
      console.error('Failed to send result to backend:', e);
    }

    // Advance — AFTER releasing mutex
    currentIndex++;
    isProcessing = false;
    processingPromptId = null;
    persistState();

    if (isRunning && currentIndex < queue.length) {
      // Human-like delay 8-15 seconds between prompts (prevents rushing)
      const delay = 8000 + Math.random() * 7000;
      setTimeout(() => processNext(), delay);
    } else if (currentIndex >= queue.length) {
      finishBatch();
    }

    return { ok: true, remaining: queue.length - currentIndex };
  },
};

async function finishBatch() {
  isRunning = false;
  isProcessing = false;
  stopKeepAlive();
  clearResponseTimeout();
  persistState();
  try {
    await fetch(`${apiBase}/api/extension/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_id: batchId }),
    });
  } catch (e) { /* ignore */ }
}

function processNext() {
  // MUTEX: prevent concurrent calls
  if (isProcessing) {
    console.log('AEO: processNext blocked by mutex');
    return;
  }
  if (!isRunning || currentIndex >= queue.length) return;

  isProcessing = true; // LOCK

  const prompt = queue[currentIndex];
  processingPromptId = prompt.id; // Track which prompt we're working on
  const llm = prompt.target_llm;

  const urlMap = {
    chatgpt: 'https://chatgpt.com/',
    gemini: 'https://gemini.google.com/app',
    perplexity: 'https://www.perplexity.ai/',
  };

  const targetUrl = urlMap[llm];
  if (!targetUrl) {
    console.error('Unknown LLM:', llm);
    isProcessing = false;
    currentIndex++;
    persistState();
    if (isRunning) processNext();
    return;
  }

  // Start response timeout
  startResponseTimeout();

  // Find existing tab for this platform
  chrome.tabs.query({ url: `${targetUrl}*` }, (tabs) => {
    if (chrome.runtime.lastError) {
      console.error('Tab query error:', chrome.runtime.lastError);
      isProcessing = false;
      return;
    }

    if (tabs && tabs.length > 0) {
      const tab = tabs[0];
      chrome.tabs.update(tab.id, { active: true }, () => {
        // Wait for tab to be active before sending
        setTimeout(() => {
          sendPromptToTab(tab.id, prompt);
        }, 1000);
      });
    } else {
      chrome.tabs.create({ url: targetUrl }, (tab) => {
        if (chrome.runtime.lastError) {
          console.error('Tab create error:', chrome.runtime.lastError);
          isProcessing = false;
          return;
        }
        // Wait for page to fully load
        const listener = (tabId, info) => {
          if (tabId === tab.id && info.status === 'complete') {
            chrome.tabs.onUpdated.removeListener(listener);
            setTimeout(() => {
              sendPromptToTab(tab.id, prompt);
            }, 5000); // Extra time for first load
          }
        };
        chrome.tabs.onUpdated.addListener(listener);
      });
    }
  });
}

const CONTENT_SCRIPTS = {
  chatgpt: 'content-chatgpt.js',
  gemini: 'content-gemini.js',
  perplexity: 'content-perplexity.js',
};

async function sendPromptToTab(tabId, prompt) {
  const scriptFile = CONTENT_SCRIPTS[prompt.target_llm];

  // Always inject the content script first
  if (scriptFile) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: [scriptFile],
      });
    } catch (e) {
      console.warn(`Script injection failed for tab ${tabId}:`, e.message);
      // Release mutex and skip
      isProcessing = false;
      clearResponseTimeout();
      currentIndex++;
      persistState();
      if (isRunning && currentIndex < queue.length) {
        setTimeout(() => processNext(), 3000);
      }
      return;
    }
    await new Promise(r => setTimeout(r, 500));
  }

  // Send the message
  try {
    await chrome.tabs.sendMessage(
      tabId,
      { type: 'submit-prompt', text: prompt.text, promptId: prompt.id }
    );
    // NOTE: isProcessing stays true — it will be released when
    // the content script sends back a 'result' message or the timeout fires
  } catch (e) {
    console.warn(`Message send failed for tab ${tabId}:`, e.message);
    isProcessing = false;
    clearResponseTimeout();
    currentIndex++;
    persistState();
    if (isRunning && currentIndex < queue.length) {
      setTimeout(() => processNext(), 3000);
    } else if (currentIndex >= queue.length) {
      finishBatch();
    }
  }
}
