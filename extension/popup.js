// AEO Insights — Popup Controller (v2 — cleaner state management)

const $ = (s) => document.querySelector(s);
let pollInterval = null;

// Load saved settings
chrome.storage.local.get(['apiBase', 'platforms'], (data) => {
  if (data.apiBase) $('#apiBase').value = data.apiBase;
  // Restore platform checkboxes (default: only ChatGPT)
  const plats = data.platforms || ['chatgpt'];
  $('#plat-chatgpt').checked = plats.includes('chatgpt');
  $('#plat-gemini').checked = plats.includes('gemini');
  $('#plat-perplexity').checked = plats.includes('perplexity');
});

// Save platform selection whenever changed
document.querySelectorAll('[id^="plat-"]').forEach(cb => {
  cb.addEventListener('change', () => {
    chrome.storage.local.set({ platforms: getSelectedPlatforms() });
  });
});

function getSelectedPlatforms() {
  const p = [];
  if ($('#plat-chatgpt').checked) p.push('chatgpt');
  if ($('#plat-gemini').checked) p.push('gemini');
  if ($('#plat-perplexity').checked) p.push('perplexity');
  return p;
}

// Connect & Load Queue
$('#connectBtn').addEventListener('click', async () => {
  const apiBase = $('#apiBase').value.trim() || 'http://localhost:8000';
  const platforms = getSelectedPlatforms();

  if (platforms.length === 0) {
    $('#connectStatus').innerHTML = '<div class="error">Select at least one platform</div>';
    return;
  }

  // Save settings
  chrome.runtime.sendMessage({ type: 'set-api-base', apiBase });
  chrome.storage.local.set({ platforms });

  $('#connectStatus').innerHTML = '<span style="color:#6b7280;font-size:12px">Connecting...</span>';
  $('#connectBtn').disabled = true;

  const result = await sendMessage({ type: 'load-queue', platforms });
  $('#connectBtn').disabled = false;

  if (result.error) {
    $('#connectStatus').innerHTML = `<div class="error">${result.error}</div>`;
  } else {
    $('#connectStatus').innerHTML = `<div class="success">Loaded ${result.count} prompts for [${platforms.join(', ')}]</div>`;
    updateStatus();
  }
});

// Start
$('#startBtn').addEventListener('click', async () => {
  const result = await sendMessage({ type: 'start' });
  if (result.error) {
    $('#connectStatus').innerHTML = `<div class="error">${result.error}</div>`;
  } else {
    startPolling();
    updateStatus();
  }
});

// Pause
$('#pauseBtn').addEventListener('click', async () => {
  await sendMessage({ type: 'pause' });
  stopPolling();
  updateStatus();
});

// Skip
$('#skipBtn').addEventListener('click', async () => {
  await sendMessage({ type: 'skip' });
  updateStatus();
});

// Poll status
function startPolling() {
  stopPolling();
  pollInterval = setInterval(updateStatus, 2000);
}
function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

async function updateStatus() {
  const status = await sendMessage({ type: 'get-status' });
  if (!status || status.error) return;

  // Status badge
  const badgeEl = $('#statusBadge');
  if (status.isRunning) {
    const extra = status.isProcessing ? ' (waiting for response)' : ' (preparing next)';
    badgeEl.innerHTML = `<span class="badge badge-running">Running${extra}</span>`;
    startPolling();
  } else if (status.currentIndex > 0 && status.currentIndex < status.queueLength) {
    badgeEl.innerHTML = '<span class="badge badge-paused">Paused</span>';
  } else if (status.currentIndex >= status.queueLength && status.queueLength > 0) {
    badgeEl.innerHTML = '<span class="badge badge-idle">Complete</span>';
    stopPolling();
  } else {
    badgeEl.innerHTML = '<span class="badge badge-idle">Idle</span>';
  }

  // Progress
  $('#progressText').textContent = `${status.currentIndex} / ${status.queueLength}`;
  const pct = status.queueLength > 0 ? (status.currentIndex / status.queueLength * 100) : 0;
  $('#progressFill').style.width = `${pct}%`;

  // Current prompt
  const promptEl = $('#currentPrompt');
  if (status.currentPrompt) {
    const llmClass = {
      chatgpt: 'platform-chatgpt',
      gemini: 'platform-gemini',
      perplexity: 'platform-perplexity',
    }[status.currentPrompt.target_llm] || '';
    promptEl.innerHTML = `
      <div class="current-prompt">
        <div class="label">
          <span class="platform ${llmClass}" style="margin-right:4px">${status.currentPrompt.target_llm}</span>
          #${status.currentIndex + 1}
        </div>
        ${escapeHtml(status.currentPrompt.text.substring(0, 120))}${status.currentPrompt.text.length > 120 ? '...' : ''}
      </div>
    `;
  } else {
    promptEl.innerHTML = '';
  }
}

function sendMessage(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || {});
    });
  });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Initial status check
updateStatus();
