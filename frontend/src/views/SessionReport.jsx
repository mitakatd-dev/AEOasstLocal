/**
 * SessionReport — post-run detail page for a single research session.
 * Route: /research/session/:sessionId
 *
 * Shows:
 *  - Session header (date, method, duration, platform count)
 *  - Aggregate mention stats per LLM
 *  - Per-prompt outcome table (mentioned by which LLMs, sentiment, latency, cost)
 *  - Export CSV button
 */
import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '../api';

const LLM_LABELS  = { openai: 'GPT-4o', gemini: 'Gemini', perplexity: 'Perplexity' };
const LLM_COLORS  = { openai: 'text-indigo-600', gemini: 'text-emerald-600', perplexity: 'text-amber-600' };
const LLM_BG      = { openai: 'bg-indigo-50',    gemini: 'bg-emerald-50',    perplexity: 'bg-amber-50'    };
const SENT_COLOR  = { positive: 'text-green-600', neutral: 'text-gray-400', negative: 'text-red-500' };
const SENT_ICON   = { positive: '↑', neutral: '=', negative: '↓' };

function formatMs(ms) {
  if (!ms) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatCost(usd) {
  if (!usd || usd === 0) return '—';
  if (usd < 0.001) return `$${usd.toFixed(5)}`;
  return `$${usd.toFixed(4)}`;
}

function MentionCell({ result }) {
  if (!result) return <td className="text-center px-3 py-2 text-gray-300 text-xs">—</td>;
  if (result.error) return (
    <td className="text-center px-3 py-2">
      <span className="text-red-400 text-xs" title={result.error}>err</span>
    </td>
  );
  return (
    <td className="text-center px-3 py-2">
      {result.mentioned
        ? <span className="text-green-600 font-semibold text-sm">✓</span>
        : <span className="text-red-400 text-sm">✗</span>
      }
      {result.sentiment && (
        <span className={`ml-1 text-xs ${SENT_COLOR[result.sentiment] || 'text-gray-400'}`}>
          {SENT_ICON[result.sentiment] || ''}
        </span>
      )}
    </td>
  );
}

export default function SessionReport() {
  const { sessionId } = useParams();
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  useEffect(() => {
    setLoading(true);
    apiFetch(`/api/runs/sessions/${encodeURIComponent(sessionId)}/results`)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) return <div className="text-center py-16 text-gray-400">Loading session…</div>;
  if (error)   return (
    <div className="text-center py-16">
      <p className="text-red-500 mb-3">{error}</p>
      <Link to="/research" className="text-indigo-600 hover:underline text-sm">← Back to Research</Link>
    </div>
  );
  if (!data || data.length === 0) return (
    <div className="text-center py-16 text-gray-400">No results found for this session.</div>
  );

  // Collect all LLMs present in this session
  const llmsPresent = [...new Set(data.flatMap(item => (item.results || []).map(r => r.llm)))].sort();

  // Aggregate stats
  const totalPrompts  = data.length;
  const triggeredAt   = data[0]?.triggered_at;
  const collectionMethod = data[0]?.results?.length > 0
    ? (data[0].results[0].cost_usd === 0 && data[0].results[0].total_tokens === 0 ? 'browser' : 'api')
    : 'unknown';

  const llmStats = {};
  llmsPresent.forEach(llm => {
    const results = data.flatMap(item => item.results.filter(r => r.llm === llm));
    const valid    = results.filter(r => !r.error);
    const mentioned = valid.filter(r => r.mentioned);
    const totalCost    = results.reduce((s, r) => s + (r.cost_usd || 0), 0);
    const totalLatency = valid.reduce((s, r) => s + (r.latency_ms || 0), 0);
    llmStats[llm] = {
      total:        results.length,
      mentioned:    mentioned.length,
      mention_rate: valid.length > 0 ? Math.round(mentioned.length / valid.length * 100) : 0,
      errors:       results.filter(r => r.error).length,
      total_cost:   totalCost,
      avg_latency:  valid.length > 0 ? Math.round(totalLatency / valid.length) : 0,
    };
  });

  const totalMentions = Object.values(llmStats).reduce((s, v) => s + v.mentioned, 0);
  const totalResults  = Object.values(llmStats).reduce((s, v) => s + v.total, 0);
  const overallRate   = totalResults > 0 ? Math.round(totalMentions / totalResults * 100) : 0;
  const totalCostAll  = Object.values(llmStats).reduce((s, v) => s + v.total_cost, 0);

  const exportUrl = `/api/runs/sessions/${encodeURIComponent(sessionId)}/export`;

  return (
    <div>
      {/* ── Breadcrumb ── */}
      <div className="mb-4 flex items-center gap-2 text-sm text-gray-400">
        <Link to="/research" className="hover:text-indigo-600">Research</Link>
        <span>›</span>
        <span className="text-gray-700 font-medium">Session Report</span>
      </div>

      {/* ── Session header ── */}
      <div className="bg-white rounded-xl border p-6 mb-6">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900 mb-1">Session Report</h1>
            <p className="text-sm text-gray-500 font-mono">{sessionId}</p>
            {triggeredAt && (
              <p className="text-sm text-gray-400 mt-1">
                {new Date(triggeredAt).toLocaleString()} ·{' '}
                <span className={`font-medium ${collectionMethod === 'browser' ? 'text-emerald-600' : 'text-indigo-600'}`}>
                  {collectionMethod === 'browser' ? '🌐 Web Browser' : '⚡ API'}
                </span>
              </p>
            )}
          </div>
          <a href={exportUrl}
            className="text-sm text-indigo-600 border border-indigo-200 hover:bg-indigo-50 px-4 py-2 rounded-lg font-medium transition">
            Export CSV ↓
          </a>
        </div>

        {/* Aggregate KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5 pt-5 border-t">
          <div>
            <p className="text-xs text-gray-400 uppercase">Prompts Run</p>
            <p className="text-2xl font-bold">{totalPrompts}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400 uppercase">Total Responses</p>
            <p className="text-2xl font-bold">{totalResults}</p>
            <p className="text-xs text-gray-500">{llmsPresent.length} platform{llmsPresent.length !== 1 ? 's' : ''}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400 uppercase">Overall Mention Rate</p>
            <p className={`text-2xl font-bold ${overallRate >= 70 ? 'text-green-600' : overallRate >= 40 ? 'text-amber-600' : 'text-red-500'}`}>
              {overallRate}%
            </p>
            <p className="text-xs text-gray-500">{totalMentions} of {totalResults} responses</p>
          </div>
          <div>
            <p className="text-xs text-gray-400 uppercase">API Cost</p>
            <p className="text-2xl font-bold">{totalCostAll > 0 ? formatCost(totalCostAll) : collectionMethod === 'browser' ? 'Web' : '$0'}</p>
            {collectionMethod === 'browser' && <p className="text-xs text-gray-400">No API charges</p>}
          </div>
        </div>
      </div>

      {/* ── Per-LLM summary cards ── */}
      <div className={`grid gap-4 mb-6`} style={{ gridTemplateColumns: `repeat(${Math.min(llmsPresent.length, 3)}, 1fr)` }}>
        {llmsPresent.map(llm => {
          const s = llmStats[llm];
          return (
            <div key={llm} className={`rounded-xl border p-4 ${LLM_BG[llm] || 'bg-gray-50'}`}>
              <p className={`text-xs font-semibold uppercase mb-2 ${LLM_COLORS[llm] || 'text-gray-500'}`}>
                {LLM_LABELS[llm] || llm}
              </p>
              <p className={`text-3xl font-bold mb-1 ${s.mention_rate >= 70 ? 'text-green-600' : s.mention_rate >= 40 ? 'text-amber-600' : 'text-red-500'}`}>
                {s.mention_rate}%
              </p>
              <p className="text-xs text-gray-500">{s.mentioned}/{s.total} mentioned</p>
              <div className="mt-2 pt-2 border-t border-black/5 flex justify-between text-xs text-gray-500">
                <span>Latency: {formatMs(s.avg_latency)}</span>
                {s.total_cost > 0 && <span>{formatCost(s.total_cost)}</span>}
                {s.errors > 0 && <span className="text-red-400">{s.errors} err</span>}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Per-prompt outcome table ── */}
      <div className="bg-white rounded-xl border overflow-hidden mb-6">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <h2 className="font-semibold text-sm">Prompt-by-Prompt Results</h2>
          <span className="text-xs text-gray-400">{totalPrompts} prompts</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600">Prompt</th>
                {llmsPresent.map(llm => (
                  <th key={llm} className={`text-center px-3 py-2 font-medium ${LLM_COLORS[llm] || 'text-gray-500'}`}>
                    {LLM_LABELS[llm] || llm}
                  </th>
                ))}
                <th className="text-center px-3 py-2 font-medium text-gray-600">Latency</th>
                <th className="text-center px-3 py-2 font-medium text-gray-600">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.map((item) => {
                const resultsByLlm = {};
                (item.results || []).forEach(r => { resultsByLlm[r.llm] = r; });
                const mentionedCount = llmsPresent.filter(llm => resultsByLlm[llm]?.mentioned).length;
                const allMentioned   = mentionedCount === llmsPresent.length;
                const noneMentioned  = mentionedCount === 0;
                const avgLatency     = item.results?.length > 0
                  ? Math.round(item.results.reduce((s, r) => s + (r.latency_ms || 0), 0) / item.results.length)
                  : 0;

                return (
                  <tr key={item.run_id}
                    className={`border-b last:border-0 ${noneMentioned ? 'bg-red-50/30' : allMentioned ? 'bg-green-50/20' : ''}`}>
                    <td className="px-4 py-2 max-w-xs">
                      <Link to={`/runs/${item.run_id}`} className="text-indigo-600 hover:underline font-medium text-sm">
                        {item.prompt_label || `Run #${item.run_id}`}
                      </Link>
                      {item.prompt_text && (
                        <p className="text-xs text-gray-400 mt-0.5 truncate max-w-xs" title={item.prompt_text}>
                          {item.prompt_text}
                        </p>
                      )}
                    </td>
                    {llmsPresent.map(llm => (
                      <MentionCell key={llm} result={resultsByLlm[llm]} />
                    ))}
                    <td className="text-center px-3 py-2 text-xs text-gray-400">
                      {avgLatency > 0 ? formatMs(avgLatency) : '—'}
                    </td>
                    <td className="text-center px-3 py-2">
                      {item.status === 'completed'
                        ? <span className="text-green-600 text-xs font-medium">done</span>
                        : item.status === 'failed'
                        ? <span className="text-red-400 text-xs font-medium">failed</span>
                        : <span className="text-gray-400 text-xs">{item.status}</span>
                      }
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Footer actions ── */}
      <div className="flex items-center justify-between">
        <Link to="/research" className="text-sm text-gray-400 hover:text-indigo-600">← Back to Research</Link>
        <a href={exportUrl}
          className="text-sm text-indigo-600 border border-indigo-200 hover:bg-indigo-50 px-4 py-2 rounded-lg font-medium transition">
          Export CSV ↓
        </a>
      </div>
    </div>
  );
}
