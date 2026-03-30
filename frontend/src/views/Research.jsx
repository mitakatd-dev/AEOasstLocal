import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '../api';
import { useAuth } from '../contexts/AuthContext';

// ── Constants ──────────────────────────────────────────────────────────────────
const PLATFORMS = [
  { id: 'openai',     label: 'ChatGPT',    bg: 'bg-indigo-50',  text: 'text-indigo-700',  border: 'border-indigo-200',  dot: 'bg-indigo-500'  },
  { id: 'gemini',     label: 'Gemini',     bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200', dot: 'bg-emerald-500' },
  { id: 'perplexity', label: 'Perplexity', bg: 'bg-amber-50',   text: 'text-amber-700',   border: 'border-amber-200',   dot: 'bg-amber-500'   },
];
const BROWSER_PLATFORM_MAP = { openai: 'chatgpt', gemini: 'gemini', perplexity: 'perplexity' };
const QUEUE_KEY  = { api: 'aeo_pending_api', browser: 'aeo_pending_browser' };
const RECENT_MS  = 30 * 60 * 1000;  // batches finished within 30 min are still shown as "active" in the UI
const FAST_MS    = 3000;
const IDLE_MS    = 15000;

// ── Helpers ────────────────────────────────────────────────────────────────────
const readQueue  = (m) => { try { return JSON.parse(localStorage.getItem(QUEUE_KEY[m]) || 'null'); } catch { return null; } };
const clearQueue = (m) => localStorage.removeItem(QUEUE_KEY[m]);

function batchIsRunning(b)  { return (b.completed + b.failed) < b.run_count; }
function batchIsRecent(b)   { return (Date.now() - new Date(b.started_at).getTime()) < RECENT_MS; }
function batchIsActive(b)   { return batchIsRunning(b) || batchIsRecent(b); }
function batchPct(b)        { return b.run_count > 0 ? Math.round((b.completed + b.failed) / b.run_count * 100) : 0; }

function fmtDuration(mins) {
  if (!mins || mins < 1) return '<1 min';
  if (mins < 60) return `${Math.round(mins)} min`;
  const h = Math.floor(mins / 60), m = Math.round(mins % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}
function fmtSecs(s) {
  if (!s || s < 1) return null;
  if (s < 60) return `${s}s`;
  return `${Math.round(s / 60)} min`;
}
function fmtMs(ms) {
  if (!ms || ms < 100) return null;
  return `${(ms / 1000).toFixed(1)}s`;
}

function timeAgo(iso) {
  const secs = Math.round((Date.now() - new Date(iso)) / 1000);
  if (secs < 60)    return `${secs}s ago`;
  if (secs < 3600)  return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}

// ── Shared atoms ───────────────────────────────────────────────────────────────
function ProgressBar({ pct, color = 'bg-indigo-500', thin = false }) {
  return (
    <div className={`w-full bg-gray-100 rounded-full ${thin ? 'h-1' : 'h-2'}`}>
      <div className={`${thin ? 'h-1' : 'h-2'} rounded-full transition-all duration-700 ${color}`}
        style={{ width: `${Math.min(pct || 0, 100)}%` }} />
    </div>
  );
}

function Badge({ status }) {
  const map = {
    running:       'bg-blue-100 text-blue-700',
    completed:     'bg-green-100 text-green-700',
    partial:       'bg-orange-100 text-orange-700',
    failed:        'bg-red-100 text-red-700',
    stopping:      'bg-red-100 text-red-600',
    waiting_login: 'bg-yellow-100 text-yellow-800',
    paused:        'bg-amber-100 text-amber-700',
    stale:         'bg-orange-100 text-orange-700',
    done:          'bg-green-100 text-green-700',
    idle:          'bg-gray-100 text-gray-500',
  };
  const labels = { waiting_login: 'Login needed', stopping: 'Stopping…' };
  const label = labels[status] || status;
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${map[status] || 'bg-gray-100 text-gray-500'}`}>{label}</span>;
}

function PlatformChip({ id }) {
  const p = PLATFORMS.find(pl => pl.id === id || BROWSER_PLATFORM_MAP[pl.id] === id);
  if (!p) return <span className="text-xs text-gray-400 border border-gray-200 px-2 py-0.5 rounded-full">{id}</span>;
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${p.bg} ${p.text}`}>{p.label}</span>;
}

function LiveDot({ active }) {
  if (!active) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-blue-500 text-xs">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
      </span>
      live
    </span>
  );
}

// ── Pending Job card ──────────────────────────────────────────────────────────
function PendingJob({ method, queue, onStarted, onBrowserLaunched }) {
  const [sel, setSel]           = useState(PLATFORMS.reduce((a, p) => ({ ...a, [p.id]: true }), {}));
  const [starting, setStarting] = useState(false);
  const [launched, setLaunched] = useState(false);  // browser: subprocess spawned, waiting for worker to register
  const [error, setError]       = useState(null);
  const [sessionId]             = useState(() => crypto.randomUUID());

  const active   = PLATFORMS.filter(p => sel[p.id]);
  const total    = queue.count * active.length;
  // Time estimates: API ~9s/prompt (0.15 min), browser ~2.5 min/prompt per platform
  const minsEst  = method === 'api' ? Math.ceil(total * 0.15) : Math.ceil(queue.count * 2.5);
  const costEst  = method === 'api' ? `~$${(total * 0.0008).toFixed(3)}` : 'free';
  const sentAgo  = timeAgo(queue.sent_at);

  const start = async () => {
    if (!active.length) return;
    setError(null);
    setStarting(true);
    try {
      if (method === 'api') {
        // API runs are created synchronously — safe to clear queue immediately on success
        await apiFetch('/api/runs/', {
          method: 'POST',
          body: JSON.stringify({
            prompt_ids: queue.prompt_ids,
            platforms: active.map(p => p.id),
            collection_method: 'api',
            session_id: sessionId,
          }),
        });
        clearQueue(method);
        onStarted();

      } else {
        // Browser runs: the subprocess takes 5–15 s to register.
        // DON'T clear the queue yet — keep this card visible as "Launching…"
        // The parent clears the queue once a worker actually appears.
        for (const p of active) {
          try {
            await apiFetch('/api/runner/launch', {
              method: 'POST',
              body: JSON.stringify({
                platform:   BROWSER_PLATFORM_MAP[p.id],
                name:       `${BROWSER_PLATFORM_MAP[p.id]}-1`,
                batch_size: queue.count,
                prompt_ids: queue.prompt_ids,
                session_id: sessionId,
              }),
            });
          } catch (launchErr) {
            // 409 = already running (show as info, not hard error)
            if (launchErr.status === 409) {
              setError(`Runner already active: ${launchErr.detail}`);
            } else {
              setError(launchErr.detail || launchErr.message);
            }
            return;
          }
        }
        setLaunched(true);
        onBrowserLaunched(); // tell parent to start polling aggressively
      }
    } catch (err) {
      setError(`Could not reach backend: ${err.message}`);
    } finally {
      setStarting(false);
    }
  };

  const icon   = method === 'api' ? '⚡' : '🌐';
  const accent = method === 'api'
    ? { border: 'border-indigo-200', bg: 'bg-indigo-50', btn: 'bg-indigo-600 hover:bg-indigo-700' }
    : { border: 'border-emerald-200', bg: 'bg-emerald-50', btn: 'bg-emerald-600 hover:bg-emerald-700' };

  // ── Launched state: Cloud Run Job triggered, waiting for worker to register ──
  // Three honest phases based on real Cloud Run start-up timing:
  //   0–59s   → "Starting"      — normal provisioning window
  //   60–179s → "Still starting" — cold start running long, still normal
  //   180s+   → true error       — something actually went wrong
  const [launchSecs, setLaunchSecs] = useState(0);
  useEffect(() => {
    if (!launched) return;
    const iv = setInterval(() => setLaunchSecs(s => s + 1), 1000);
    return () => clearInterval(iv);
  }, [launched]);

  if (launched) {
    const slowStart  = launchSecs >= 60;
    const realError  = launchSecs >= 180;
    const borderCls  = realError ? 'border-orange-200 bg-orange-50' : `${accent.border} ${accent.bg}`;

    const heading = realError
      ? 'Runner failed to start'
      : slowStart
        ? `Container initialising… (${launchSecs}s)`
        : `Starting runner job… (${launchSecs}s)`;

    const body = realError
      ? 'No worker registered after 3 minutes. The Cloud Run Job may have crashed — check Cloud Logging for errors.'
      : slowStart
        ? 'Still normal — cloud container start-up can take up to 2 minutes. The runner card will appear once it registers.'
        : 'Cloud Run is provisioning the runner container. This typically takes about 1 minute.';

    return (
      <div className={`rounded-xl border-2 p-5 space-y-3 ${borderCls}`}>
        <div className="flex items-center gap-3">
          {realError
            ? <span className="text-orange-500 text-lg">⚠</span>
            : <svg className="animate-spin h-4 w-4 text-emerald-600 flex-shrink-0" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
          }
          <div className="flex-1">
            <p className={`font-semibold text-sm ${realError ? 'text-orange-800' : 'text-gray-800'}`}>
              {heading}
            </p>
            <p className={`text-xs mt-0.5 ${realError ? 'text-orange-600' : 'text-gray-500'}`}>
              {body}
            </p>
          </div>
          {realError && (
            <button onClick={() => { setLaunched(false); setError('Runner did not register within 3 minutes — check Cloud Logging.'); }}
              className="text-xs text-orange-600 border border-orange-300 px-2 py-1 rounded-lg hover:bg-orange-100 flex-shrink-0">
              Dismiss
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-xl border-2 p-5 space-y-4 ${accent.border} ${accent.bg}`}>
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span>{icon}</span>
            <span className="font-semibold text-gray-800">{method === 'api' ? 'API Research' : 'Web Research'}</span>
            <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded-full">pending · {sentAgo}</span>
          </div>
          <p className="text-sm text-gray-600"><strong>{queue.count}</strong> prompt{queue.count !== 1 ? 's' : ''} queued</p>
        </div>
        <button onClick={() => { clearQueue(method); onStarted(); }} className="text-xs text-gray-400 hover:text-red-500">Discard</button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2.5 text-xs text-red-700">
          <strong>Launch failed:</strong> {error}
        </div>
      )}

      <div>
        <p className="text-xs text-gray-500 font-medium mb-2">Run on:</p>
        <div className="flex gap-2 flex-wrap">
          {PLATFORMS.map(p => (
            <button key={p.id} onClick={() => setSel(s => ({ ...s, [p.id]: !s[p.id] }))}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition ${sel[p.id] ? `${p.bg} ${p.text} ${p.border}` : 'bg-white text-gray-400 border-gray-200'}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${sel[p.id] ? p.dot : 'bg-gray-300'}`} />
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between pt-1">
        <div className="text-xs text-gray-500 space-y-0.5">
          <p>{queue.count} prompts × {active.length} platform{active.length !== 1 ? 's' : ''} = <strong>{total} responses</strong></p>
          <p>Est. {minsEst > 60 ? `${Math.floor(minsEst / 60)}h ${minsEst % 60}m` : `${minsEst}m`} · {costEst}</p>
        </div>
        <button onClick={start} disabled={starting || !active.length}
          className={`px-5 py-2.5 rounded-lg text-sm font-semibold text-white transition disabled:opacity-40 ${accent.btn}`}>
          {starting ? 'Starting…' : `Start ${method === 'api' ? 'API' : 'Web'} Research`}
        </button>
      </div>
    </div>
  );
}

// ── Batch card (active + history) ─────────────────────────────────────────────
const PLATFORM_LABELS = { openai: 'ChatGPT', gemini: 'Gemini', perplexity: 'Perplexity' };
const PLATFORM_COLORS = { openai: 'bg-indigo-500', gemini: 'bg-emerald-500', perplexity: 'bg-amber-500' };
const PLATFORM_TEXT   = { openai: 'text-indigo-600', gemini: 'text-emerald-600', perplexity: 'text-amber-600' };

function BatchCard({ batch, defaultOpen = false, onRefresh, isAdmin = false, onDelete }) {
  const [open,     setOpen]     = useState(defaultOpen);
  const [results,  setResults]  = useState(null);
  const [loading,  setLoading]  = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const running    = batchIsRunning(batch);
  const pct        = batchPct(batch);
  const wasRunning = useRef(running);

  // Auto-load results panel when batch transitions running → done
  useEffect(() => {
    if (wasRunning.current && !running) {
      fetchResults(); // silent, no loading spinner
    }
    wasRunning.current = running;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const fetchResults = async () => {
    try {
      const qs = `from_date=${encodeURIComponent(batch.from_dt)}&to_date=${encodeURIComponent(batch.to_dt)}`;
      const statsRes = await apiFetch(`/api/stats/?${qs}`);
      setResults({ stats: statsRes });
      setOpen(true);
    } catch {}
  };

  const loadResults = async () => {
    if (results) { setOpen(o => !o); return; }
    setLoading(true);
    try { await fetchResults(); } finally { setLoading(false); }
  };

  const retry = async () => {
    const ids = batch.failed_prompt_ids;
    if (!ids?.length) return;
    setRetrying(true);
    try {
      await apiFetch('/api/runs/', {
        method: 'POST',
        body: JSON.stringify({
          prompt_ids: ids,
          platforms:  batch.platforms.length ? batch.platforms : ['openai', 'gemini', 'perplexity'],
          collection_method: 'api',
          session_id: batch.primary_session_id,   // merge retried results into same session
        }),
      });
      if (onRefresh) onRefresh();
    } finally {
      setRetrying(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Delete this batch and all its runs and results? This cannot be undone.')) return;
    setDeleting(true);
    try {
      for (const sid of (batch.session_ids || [])) {
        await apiFetch(`/api/runs/sessions/${sid}`, { method: 'DELETE' });
      }
      if (onDelete) onDelete();
    } finally {
      setDeleting(false);
    }
  };

  const exportUrl      = `/api/runs/export/csv?from_date=${encodeURIComponent(batch.from_dt)}&to_date=${encodeURIComponent(batch.to_dt)}`;
  const platformProg   = batch.platform_progress || {};
  const hasPlatProg    = running && Object.keys(platformProg).length > 0;
  const canRetry       = !running && (batch.failed_prompt_ids?.length > 0);
  const canDelete      = isAdmin && !running && (batch.session_ids || []).length > 0;

  return (
    <div className={`bg-white rounded-xl border overflow-hidden ${running ? 'border-blue-200 shadow-sm shadow-blue-50' : 'border-gray-200'}`}>
      {/* Header */}
      <div className="flex items-center gap-4 px-5 py-4">
        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${running ? 'bg-blue-500 animate-pulse' : batch.failed > 0 && batch.completed === 0 ? 'bg-red-400' : batch.failed > 0 ? 'bg-orange-400' : 'bg-green-500'}`} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="font-semibold text-sm text-gray-800">{batch.label}</span>
            {running
              ? <Badge status="running" />
              : batch.failed > 0 && batch.completed === 0 ? <Badge status="failed" />
              : batch.failed > 0 ? <Badge status="partial" />
              : <Badge status="completed" />
            }
            {batch.platforms.map(p => <PlatformChip key={p} id={p} />)}
          </div>
          <div className="flex items-center gap-4 text-xs text-gray-400">
            <span>{timeAgo(batch.started_at)}</span>
            <span>
              <strong className="text-gray-600">{batch.completed}</strong> done
              {batch.failed > 0 && <span className="text-red-400 ml-1">· {batch.failed} failed</span>}
              {(batch.run_count - batch.completed - batch.failed) > 0 && (
                <span className="ml-1">· {batch.run_count - batch.completed - batch.failed} pending</span>
              )}
            </span>
            {!running && batch.duration_mins > 0 && (
              <span className="flex items-center gap-2">
                <span>⏱ {fmtDuration(batch.duration_mins)}</span>
                {batch.total_paused_s > 0 && <span className="text-amber-500">⏸ {fmtSecs(batch.total_paused_s)} paused</span>}
                {fmtMs(batch.avg_latency_ms) && <span>· avg {fmtMs(batch.avg_latency_ms)}/prompt</span>}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="text-sm font-bold text-gray-700">{pct}%</span>
          <span className="text-xs text-gray-400">{batch.completed + batch.failed}/{batch.run_count}</span>
          {isAdmin && canRetry && (
            <button onClick={retry} disabled={retrying}
              className="text-xs text-orange-500 hover:text-orange-700 font-medium border border-orange-200 hover:border-orange-400 px-2 py-1 rounded-lg transition disabled:opacity-40">
              {retrying ? 'Retrying…' : `↺ Retry ${batch.failed} failed`}
            </button>
          )}
          {canDelete && (
            <button onClick={handleDelete} disabled={deleting}
              className="text-xs text-red-400 hover:text-red-600 font-medium border border-red-200 hover:border-red-400 px-2 py-1 rounded-lg transition disabled:opacity-40">
              {deleting ? 'Deleting…' : 'Delete'}
            </button>
          )}
          <button onClick={loadResults} disabled={loading}
            className="text-xs text-indigo-500 hover:text-indigo-700 font-medium">
            {loading ? 'Loading…' : open ? 'Hide ▴' : 'Results ▾'}
          </button>
        </div>
      </div>

      {/* Progress bar + per-platform breakdown */}
      <div className="px-5 pb-4">
        <ProgressBar pct={pct} color={running ? 'bg-blue-500' : 'bg-green-500'} thin />

        {hasPlatProg && (
          <div className="mt-3 grid gap-2" style={{ gridTemplateColumns: `repeat(${Object.keys(platformProg).length}, 1fr)` }}>
            {Object.entries(platformProg).map(([llm, counts]) => {
              const platPct = counts.total > 0 ? Math.round(counts.completed / counts.total * 100) : 0;
              return (
                <div key={llm}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className={PLATFORM_TEXT[llm] || 'text-gray-500'}>{PLATFORM_LABELS[llm] || llm}</span>
                    <span className="text-gray-400">{counts.completed}/{counts.total}</span>
                  </div>
                  <ProgressBar pct={platPct} color={PLATFORM_COLORS[llm] || 'bg-gray-400'} thin />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Results panel — auto-opens when batch completes */}
      {open && results && (
        <div className="border-t bg-gray-50 px-5 py-4 space-y-4">

          {/* Timing breakdown */}
          {!running && batch.duration_mins > 0 && (
            <div className="bg-white rounded-lg border p-3">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Run Timing</p>
              <div className="flex gap-6">
                <div>
                  <p className="text-lg font-bold text-gray-800">{fmtDuration(batch.duration_mins)}</p>
                  <p className="text-xs text-gray-400">total wall time</p>
                </div>
                {batch.total_paused_s > 0 && (
                  <div>
                    <p className="text-lg font-bold text-amber-500">{fmtSecs(batch.total_paused_s)}</p>
                    <p className="text-xs text-gray-400">paused / idle</p>
                  </div>
                )}
                {batch.total_paused_s > 0 && (
                  <div>
                    <p className="text-lg font-bold text-emerald-600">
                      {fmtDuration(batch.duration_mins - batch.total_paused_s / 60)}
                    </p>
                    <p className="text-xs text-gray-400">active</p>
                  </div>
                )}
                {fmtMs(batch.avg_latency_ms) && (
                  <div>
                    <p className="text-lg font-bold text-blue-600">{fmtMs(batch.avg_latency_ms)}</p>
                    <p className="text-xs text-gray-400">avg per prompt</p>
                  </div>
                )}
                <div>
                  <p className="text-lg font-bold text-gray-700">{batch.completed + batch.failed}/{batch.run_count}</p>
                  <p className="text-xs text-gray-400">prompts</p>
                </div>
              </div>
            </div>
          )}

          {results.stats && (
            <div className="grid grid-cols-3 gap-4">
              {['openai', 'gemini', 'perplexity'].map(llm => {
                const d = results.stats.per_llm?.[llm];
                if (!d || d.total_calls === 0) return null;
                return (
                  <div key={llm} className="bg-white rounded-lg border p-3">
                    <p className="text-xs text-gray-400 mb-1">{d.model}</p>
                    <p className={`text-xl font-bold ${d.mention_rate >= 50 ? 'text-green-600' : d.mention_rate >= 20 ? 'text-amber-600' : 'text-red-500'}`}>
                      {d.mention_rate}%
                    </p>
                    <p className="text-xs text-gray-400">mention rate</p>
                    <p className="text-xs text-gray-500 mt-1">{d.successful} responses · {d.errors} err</p>
                  </div>
                );
              })}
            </div>
          )}
          <div className="flex justify-between items-center">
            {batch.primary_session_id && (
              <Link
                to={`/research/session/${encodeURIComponent(batch.primary_session_id)}`}
                className="text-xs text-indigo-600 font-medium hover:underline border border-indigo-200 hover:bg-indigo-50 px-3 py-1 rounded-lg transition">
                View Full Report →
              </Link>
            )}
            <a href={exportUrl} className="text-xs text-gray-400 hover:text-indigo-500 hover:underline ml-auto">Export CSV ↓</a>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Screenshot thumbnail with lightbox ────────────────────────────────────────
function ScreenshotThumb({ data, label }) {
  const [expanded, setExpanded] = useState(false);
  const src = `data:image/jpeg;base64,${data}`;
  return (
    <>
      {/* Thumbnail — fixed height, click to expand */}
      <button onClick={() => setExpanded(true)} className="block w-full text-left group relative">
        <img
          src={src}
          alt={label}
          className="h-24 w-auto rounded border border-gray-200 shadow-sm group-hover:opacity-90 transition-opacity"
        />
        <span className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="bg-black/50 text-white text-[10px] px-2 py-0.5 rounded">Click to expand</span>
        </span>
      </button>
      <p className="mt-1 text-[10px] text-gray-400 font-mono">{label}</p>

      {/* Lightbox */}
      {expanded && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          onClick={() => setExpanded(false)}
        >
          <div className="relative max-w-5xl w-full" onClick={e => e.stopPropagation()}>
            <button
              onClick={() => setExpanded(false)}
              className="absolute -top-8 right-0 text-white text-xs opacity-70 hover:opacity-100"
            >✕ Close</button>
            <img src={src} alt={label} className="w-full rounded shadow-xl border border-gray-700" />
            <p className="mt-2 text-[10px] text-gray-400 font-mono text-center">{label}</p>
          </div>
        </div>
      )}
    </>
  );
}

// ── Browser worker card ────────────────────────────────────────────────────────
function BrowserWorkerCard({ worker, onLoginReady, onStop, onReset, isAdmin = false }) {
  const [logs,       setLogs]       = useState([]);
  const [progress,   setProgress]   = useState(null);
  const [open,       setOpen]       = useState(true);
  const [stopping,   setStopping]   = useState(false);
  const [stopped,    setStopped]    = useState(false);   // confirmed dead
  const [stopFailed, setStopFailed] = useState(false);   // couldn't confirm death
  const [pausing,    setPausing]    = useState(false);
  const [resuming,   setResuming]   = useState(false);
  const [screenshot, setScreenshot] = useState(null);   // {data, label, timestamp}
  const [showShot,   setShowShot]   = useState(true);   // toggle screenshot panel
  const logContainerRef = useRef(null);
  const stopPollRef = useRef(null);

  const needLogin = worker.needs_login || worker.status === 'waiting_login';
  const isPaused  = worker.is_paused  || worker.status === 'paused';
  const platform  = PLATFORMS.find(p => BROWSER_PLATFORM_MAP[p.id] === worker.platform) || {};
  const isActive  = !['done', 'idle', 'stale'].includes(worker.status);

  const handlePause = async () => {
    setPausing(true);
    try {
      await apiFetch('/api/runner/pause', {
        method: 'POST',
        body: JSON.stringify({ name: worker.name, platform: worker.platform }),
      });
    } finally {
      setPausing(false);
    }
  };

  const handleResume = async () => {
    setResuming(true);
    try {
      await apiFetch('/api/runner/resume', {
        method: 'POST',
        body: JSON.stringify({ name: worker.name, platform: worker.platform }),
      });
    } finally {
      setResuming(false);
    }
  };

  // Stop poll cleanup on unmount
  useEffect(() => () => { if (stopPollRef.current) clearInterval(stopPollRef.current); }, []);

  // Log polling — independent of parent refresh cycle
  useEffect(() => {
    const load = () =>
      apiFetch(`/api/runner/logs/${worker.name}?platform=${worker.platform}&lines=80`)
        .then(d => {
          setLogs(d.lines || []);
          if (d.progress) setProgress(d.progress);
        })
        .catch(() => {});
    load();
    const iv = setInterval(load, 3000);
    return () => clearInterval(iv);
  }, [worker.name, worker.platform]);

  // Screenshot polling — check every 10s for new browser snapshots
  useEffect(() => {
    const load = () =>
      apiFetch(`/api/runner/screenshot/${worker.name}`)
        .then(d => { if (d.data) setScreenshot(d); })
        .catch(() => {});
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, [worker.name]);

  // Auto-scroll terminal — scroll only within the log box, never the page
  useEffect(() => {
    if (open && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, open]);

  const handleStop = async () => {
    if (!confirm(`Stop worker "${worker.name}"?\nThis will terminate the Chromium browser immediately.`)) return;
    setStopping(true);
    setStopFailed(false);
    await onStop(worker.name);

    // Poll until confirmed dead (max 10 s)
    let attempts = 0;
    stopPollRef.current = setInterval(async () => {
      attempts++;
      try {
        const data = await apiFetch(`/api/runner/alive/${worker.name}`);
        if (!data.alive) {
          clearInterval(stopPollRef.current);
          setStopping(false);
          setStopped(true);
        } else if (attempts >= 20) {
          clearInterval(stopPollRef.current);
          setStopping(false);
          setStopFailed(true);
        }
      } catch {
        clearInterval(stopPollRef.current);
        setStopping(false);
        setStopped(true); // unreachable → assume dead
      }
    }, 500);
  };

  // Progress — prefer log-parsed data (updates every 3 s) over 30 s heartbeat
  const logDone   = progress?.done    ?? worker.completed ?? 0;
  const logTotal  = progress?.total   ?? worker.total_prompts ?? 0;
  const logFailed = progress?.failed  ?? 0;
  const logPct    = logTotal > 0 ? Math.round((logDone + logFailed) / logTotal * 100) : (worker.progress_pct || 0);
  const curLabel  = progress?.current_label || '';
  const phase     = progress?.phase || 'setup';

  // ── Terminated state ──────────────────────────────────────────────────────
  if (stopped) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white px-5 py-4 flex items-center gap-4">
        <span className="text-2xl">⬛</span>
        <div>
          <p className="font-semibold text-sm text-gray-700">
            {platform.label || worker.platform} runner stopped
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            Collected <strong>{logDone}</strong> of {logTotal} prompts before stopping
            {logFailed > 0 && <span className="text-red-400 ml-1">· {logFailed} failed</span>}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-xl border overflow-hidden bg-white ${
      needLogin  ? 'border-yellow-300' :
      isPaused   ? 'border-amber-300 shadow-sm shadow-amber-50' :
      isActive   ? 'border-emerald-200 shadow-sm shadow-emerald-50' :
                   'border-gray-200'
    }`}>
      {/* Header */}
      <div className="px-5 py-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span>🌐</span>
            <span className="font-semibold text-sm">{platform.label || worker.platform}</span>
            <Badge status={stopping ? 'stopping' : worker.status} />
            {isActive && !needLogin && !stopping && !isPaused && <LiveDot active={phase === 'running'} />}
          </div>
          {/* Clear button — admin only, for stopped/stale/error workers */}
          {isAdmin && ['stopped', 'stale', 'error'].includes(worker.status) && (
            <button onClick={() => { if (confirm('Clear this worker? This removes it from the active view and lets you launch a fresh run. Run history is kept.')) onReset(); }}
              className="text-xs text-gray-500 hover:text-red-600 font-medium border border-gray-200 hover:border-red-300 bg-white hover:bg-red-50 px-2.5 py-1 rounded-lg transition">
              ✕ Clear
            </button>
          )}
          {isAdmin && isActive && (
            <div className="flex items-center gap-2">
              {/* Pause / Resume */}
              {!stopping && (
                isPaused ? (
                  <button onClick={handleResume} disabled={resuming}
                    className="text-xs text-amber-600 hover:text-amber-800 font-medium disabled:opacity-50 border border-amber-300 hover:border-amber-500 bg-amber-50 hover:bg-amber-100 px-2.5 py-1 rounded-lg transition">
                    {resuming ? 'Resuming…' : '▶ Resume'}
                  </button>
                ) : (
                  <button onClick={handlePause} disabled={pausing || needLogin}
                    className="text-xs text-gray-500 hover:text-amber-700 font-medium disabled:opacity-40 border border-gray-200 hover:border-amber-300 hover:bg-amber-50 px-2.5 py-1 rounded-lg transition">
                    {pausing ? 'Pausing…' : '⏸ Pause'}
                  </button>
                )
              )}
              {/* Stop */}
              <button onClick={handleStop} disabled={stopping}
                className="text-xs text-red-400 hover:text-red-600 font-medium disabled:opacity-50 border border-red-200 hover:border-red-400 px-2.5 py-1 rounded-lg transition flex items-center gap-1.5">
                {stopping
                  ? <><svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                    </svg> Stopping…</>
                  : '⬛ Stop'
                }
              </button>
            </div>
          )}
        </div>

        {/* Stop failed warning */}
        {stopFailed && (
          <div className="bg-orange-50 border border-orange-200 rounded-lg px-3 py-2 text-xs text-orange-700">
            ⚠ Process did not stop within 10 s. It may still be running.
            Try restarting the backend or killing the process manually.
          </div>
        )}

        {/* Paused banner */}
        {isPaused && !needLogin && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-center gap-3 justify-between">
            <div>
              <p className="text-xs font-semibold text-amber-800">⏸ Paused</p>
              <p className="text-xs text-amber-700 mt-0.5">
                Runner will finish the current prompt then wait. Progress is saved.
              </p>
            </div>
            <button onClick={handleResume} disabled={resuming}
              className="flex-shrink-0 bg-amber-500 hover:bg-amber-600 text-white text-xs font-semibold px-4 py-2 rounded-lg whitespace-nowrap transition disabled:opacity-50">
              {resuming ? 'Resuming…' : '▶ Resume'}
            </button>
          </div>
        )}

        {/* Login gate */}
        {needLogin && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 flex items-center gap-3 justify-between">
            <div>
              <p className="text-xs font-semibold text-yellow-800">Waiting for login</p>
              <p className="text-xs text-yellow-700 mt-0.5">
                Browser is open — sign in to <strong>{platform.label}</strong> then confirm.
              </p>
            </div>
            <button onClick={() => onLoginReady(worker.platform, worker.name)}
              className="flex-shrink-0 bg-yellow-500 hover:bg-yellow-600 text-white text-xs font-semibold px-4 py-2 rounded-lg whitespace-nowrap transition">
              Login Complete ✓
            </button>
          </div>
        )}

        {/* Progress */}
        <div>
          <div className="flex justify-between text-xs text-gray-500 mb-1.5">
            <span>
              {logDone > 0 || logTotal > 0
                ? <><strong>{logDone}</strong>/{logTotal} collected{logFailed > 0 && <span className="text-red-400 ml-1">· {logFailed} failed</span>}</>
                : <span className="text-gray-400 italic">
                    {phase === 'login' ? 'Waiting for login…' : 'Initialising runner…'}
                  </span>
              }
            </span>
            <span className="font-semibold">{logPct}%</span>
          </div>
          <ProgressBar pct={logPct} color={needLogin ? 'bg-yellow-400' : stopping ? 'bg-red-400' : isPaused ? 'bg-amber-400' : 'bg-emerald-500'} />
          {curLabel && phase === 'running' && (
            <p className="text-xs text-gray-400 mt-1 truncate">
              <span className="text-emerald-500 mr-1">▶</span>{curLabel}
            </p>
          )}
        </div>
      </div>

      {/* Log bar */}
      <div className="border-t px-5 py-2 flex items-center justify-between bg-gray-50">
        <button onClick={() => setOpen(o => !o)}
          className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1.5 font-medium">
          <span className="text-gray-300">{open ? '▾' : '▸'}</span>
          {open ? 'Hide' : 'Show'} runner log
        </button>
        <span className="text-xs text-gray-300 font-mono">{worker.name}</span>
      </div>

      {/* Log terminal */}
      {open && (
        <div ref={logContainerRef} className="bg-gray-950 max-h-64 overflow-y-auto font-mono text-xs leading-relaxed p-4 space-y-0.5">
          {logs.length === 0
            ? <span className="text-gray-500">No log output yet…</span>
            : logs.map((l, i) => (
                <div key={i} className={
                  l.includes('✓') ? 'text-green-400' :
                  l.includes('✗') ? 'text-red-400' :
                  l.includes('[login]') ? 'text-yellow-300' :
                  l.includes('[warn]') ? 'text-orange-300' :
                  l.includes('===') ? 'text-gray-500' :
                  'text-gray-300'
                }>{l || '\u00A0'}</div>
              ))
          }
        </div>
      )}

      {/* Browser screenshot panel — thumbnail by default, click to expand full size */}
      {screenshot?.data && (
        <div className="border-t bg-gray-50">
          <button onClick={() => setShowShot(s => !s)}
            className="w-full px-5 py-2 flex items-center justify-between text-xs text-gray-400 hover:text-gray-600">
            <span className="flex items-center gap-1.5 font-medium">
              <span className="text-gray-300">{showShot ? '▾' : '▸'}</span>
              Browser snapshot
              {screenshot.label?.includes('failed') && (
                <span className="ml-1 bg-red-100 text-red-600 px-1.5 py-0.5 rounded text-[10px] font-semibold">failure</span>
              )}
            </span>
            <span className="text-[10px] text-gray-300 font-mono truncate max-w-xs">
              {screenshot.label} · {screenshot.timestamp ? new Date(screenshot.timestamp).toLocaleTimeString() : ''}
            </span>
          </button>
          {showShot && (
            <div className="px-5 pb-4">
              {/* Thumbnail — click to open full-size lightbox */}
              <ScreenshotThumb data={screenshot.data} label={screenshot.label} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Research() {
  const { role } = useAuth();
  const isAdmin = role === 'admin';

  const [apiQueue,         setApiQueue]         = useState(() => readQueue('api'));
  const [browserQueue,     setBrowserQueue]     = useState(() => readQueue('browser'));
  const [batches,          setBatches]          = useState([]);
  const [workers,          setWorkers]          = useState([]);
  const [methodFilter,     setMethodFilter]     = useState('all');
  const [isLive,           setIsLive]           = useState(false);
  // True while we're waiting for a browser runner subprocess to register after launch
  const [awaitingWorker,   setAwaitingWorker]   = useState(false);
  const [backendError,     setBackendError]     = useState(null);

  // Stable refresh — no cascading deps
  const refresh = useCallback(async () => {
    setApiQueue(readQueue('api'));
    setBrowserQueue(readQueue('browser'));
    try {
      const [batchesData, runnerData] = await Promise.all([
        apiFetch('/api/runs/batches'),
        apiFetch('/api/runner/status'),
      ]);
      setBatches(Array.isArray(batchesData) ? batchesData : []);
      setWorkers(runnerData.workers || []);
      setBackendError(null);
    } catch (err) {
      setBackendError('Cannot reach backend — is it running on port 8000?');
    }
  }, []);

  // Single stable interval — never re-created on state change
  const intervalRef = useRef(null);
  const batchesRef  = useRef(batches);
  const activeWorkersRef  = useRef(workers);
  batchesRef.current = batches;
  activeWorkersRef.current = workers;

  useEffect(() => {
    // Initial load
    refresh();

    const tick = () => {
      const hasRunning =
        batchesRef.current.some(batchIsRunning) ||
        activeWorkersRef.current.some(w => !['done', 'idle'].includes(w.status));
      setIsLive(hasRunning);
      refresh();
    };

    const schedule = () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      const hasRunning =
        batchesRef.current.some(batchIsRunning) ||
        activeWorkersRef.current.some(w => !['done', 'idle'].includes(w.status));
      intervalRef.current = setInterval(tick, hasRunning ? FAST_MS : IDLE_MS);
    };

    schedule();
    // Re-schedule when running state might have changed (batches/workers updated)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []); // ← empty deps: mount/unmount only, no cascade

  // Adjust interval speed when running state changes without re-mounting.
  // awaitingWorker=true means a runner subprocess was just launched — poll fast
  // so we detect registration quickly (before PendingJob timeout fires).
  useEffect(() => {
    const hasRunning = awaitingWorker || batches.some(batchIsRunning) || workers.some(w => !['done', 'idle'].includes(w.status));
    setIsLive(hasRunning);
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = setInterval(() => {
      refresh();
    }, hasRunning ? FAST_MS : IDLE_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [
    awaitingWorker,
    // Only re-run when the "is something running" boolean changes, not on every batch update
    // eslint-disable-next-line react-hooks/exhaustive-deps
    batches.some(batchIsRunning),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    workers.some(w => !['done', 'idle'].includes(w.status)),
    refresh,
  ]);

  // When awaitingWorker=true, we launched a browser runner and are waiting for it to register.
  // Once any non-idle/done worker appears, clear the browser queue — it's confirmed running.
  useEffect(() => {
    if (!awaitingWorker) return;
    const activeNow = workers.filter(w => !['done', 'idle'].includes(w.status));
    if (activeNow.length > 0) {
      clearQueue('browser');
      setBrowserQueue(null);
      setAwaitingWorker(false);
    }
  }, [workers, awaitingWorker]);

  // Safety timeout: if no worker appears within 2 minutes, stop waiting so the
  // Pending Job card reverts to normal (user can retry or see the error).
  useEffect(() => {
    if (!awaitingWorker) return;
    const t = setTimeout(() => setAwaitingWorker(false), 2 * 60 * 1000);
    return () => clearTimeout(t);
  }, [awaitingWorker]);

  const handleBrowserLaunched = useCallback(() => {
    setAwaitingWorker(true);
    refresh(); // kick off faster polling immediately
  }, [refresh]);

  const handleLoginReady = async (platform, name) => {
    await apiFetch('/api/runner/login-ready', {
      method: 'POST',
      body: JSON.stringify({ platform, name }),
    });
    refresh();
  };

  const handleStop = async (name) => {
    await apiFetch('/api/runner/stop', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
    setTimeout(refresh, 500); // short delay to let process die
  };

  const handleResetWorkers = async () => {
    await apiFetch('/api/runner/workers', { method: 'DELETE' });
    setTimeout(refresh, 300);
  };

  // Partition batches
  const allBatches     = batches.filter(b => methodFilter === 'all' || (b.methods || []).includes(methodFilter));
  const activeBatches  = allBatches.filter(batchIsActive);
  const historyBatches = allBatches.filter(b => !batchIsActive(b));
  const activeWorkers  = workers.filter(w => !['done', 'idle'].includes(w.status));

  const hasPending  = !!(apiQueue || browserQueue);
  const hasActive   = activeBatches.length > 0 || activeWorkers.length > 0;
  const hasHistory  = historyBatches.length > 0;
  const hasAnything = hasPending || hasActive || hasHistory;

  return (
    <div className="space-y-8">
      {/* ── Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Research Command Center</h1>
            <LiveDot active={isLive} />
          </div>
          <p className="text-gray-500 text-sm mt-1">
            Configure, run and monitor research sessions.{' '}
            <Link to="/prompts" className="text-indigo-500 hover:underline">Select prompts →</Link>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={refresh}
            className="text-xs text-gray-400 hover:text-indigo-600 border border-gray-200 px-3 py-1.5 rounded-lg hover:border-indigo-300 transition">
            ↻ Refresh
          </button>
          <a href="/api/runs/export/csv"
            className="text-xs text-gray-500 hover:text-indigo-600 border border-gray-200 px-3 py-1.5 rounded-lg hover:border-indigo-300 transition">
            Export all ↓
          </a>
        </div>
      </div>

      {/* ── Backend error banner ── */}
      {backendError && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-5 py-3 flex items-center gap-3">
          <span className="text-red-500 text-lg">⚠</span>
          <div>
            <p className="text-sm font-semibold text-red-700">{backendError}</p>
            <p className="text-xs text-red-500 mt-0.5">
              Run: <code className="bg-red-100 px-1 rounded">cd backend &amp;&amp; uvicorn app.main:app --reload --port 8000</code>
            </p>
          </div>
        </div>
      )}

      {/* ── Pending Jobs — admin only ── */}
      {isAdmin && hasPending && (
        <section>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Pending Jobs</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {apiQueue     && <PendingJob method="api"     queue={apiQueue}     onStarted={refresh} onBrowserLaunched={handleBrowserLaunched} />}
            {browserQueue && <PendingJob method="browser" queue={browserQueue} onStarted={refresh} onBrowserLaunched={handleBrowserLaunched} />}
          </div>
        </section>
      )}

      {/* ── Active & Recent ── */}
      {hasActive && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-2">
              Active & Recent
              {isLive && (
                <span className="text-blue-500 normal-case font-normal text-xs flex items-center gap-1">
                  · collecting now
                </span>
              )}
            </h2>
          </div>
          <div className="space-y-3">
            {activeBatches.map(b => (
              <BatchCard key={b.batch_index} batch={b} defaultOpen={b.is_latest} onRefresh={refresh} isAdmin={isAdmin} />
            ))}
            {activeWorkers.map(w => (
              <BrowserWorkerCard
                key={w.worker_id}
                worker={w}
                onLoginReady={handleLoginReady}
                onStop={handleStop}
                onReset={handleResetWorkers}
                isAdmin={isAdmin}
              />
            ))}
          </div>
        </section>
      )}

      {/* ── Empty state ── */}
      {!hasAnything && (
        <div className="bg-gray-50 border border-dashed border-gray-200 rounded-xl p-12 text-center">
          <p className="text-3xl mb-3">📋</p>
          <p className="font-medium text-gray-600 mb-1">No research sessions yet</p>
          <p className="text-sm text-gray-400">
            Go to <Link to="/prompts" className="text-indigo-500 hover:underline">Prompt Library</Link>,
            select prompts, and click "Send to Research".
          </p>
        </div>
      )}

      {/* ── Run History ── */}
      {hasHistory && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Run History</h2>
            <div className="flex gap-1 bg-gray-100 p-0.5 rounded-lg text-xs">
              {[['all','All'],['api','API'],['browser','Web']].map(([v, l]) => (
                <button key={v} onClick={() => setMethodFilter(v)}
                  className={`px-3 py-1 rounded-md font-medium transition ${methodFilter === v ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-500'}`}>
                  {l}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            {historyBatches.map(b => <BatchCard key={b.batch_index} batch={b} onRefresh={refresh} isAdmin={isAdmin} onDelete={refresh} />)}
          </div>
        </section>
      )}

    </div>
  );
}
