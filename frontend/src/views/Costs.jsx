import { useState, useEffect } from 'react';
import { apiFetch } from '../api';
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, Tooltip, Legend,
} from 'chart.js';
import { Bar } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend);

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmt(usd) {
  if (usd == null || usd === 0) return '$0.00';
  if (usd < 0.001) return `$${usd.toFixed(5)}`;
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function costPerResult(cost, count) {
  if (!cost || !count || count === 0) return '—';
  return fmt(cost / count);
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SummaryCard({ label, amount, note, accent }) {
  const accentMap = {
    indigo: 'border-t-indigo-500',
    emerald: 'border-t-emerald-500',
    amber: 'border-t-amber-500',
    gray: 'border-t-gray-400',
  };
  return (
    <div className={`bg-white rounded-xl border border-gray-200 border-t-2 ${accentMap[accent] || accentMap.gray} p-5 flex flex-col gap-1`}>
      <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</span>
      <span className="text-2xl font-bold text-gray-900">{amount}</span>
      {note && (
        <span className="text-xs text-gray-400 mt-1">{note}</span>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function ErrorBox({ message }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
      {message}
    </div>
  );
}

function TypeBadge({ method }) {
  if (method === 'api') {
    return <span className="px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-700">API</span>;
  }
  return <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">Web</span>;
}

// ── Main View ──────────────────────────────────────────────────────────────────

export default function Costs() {
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [daily, setDaily] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);

    Promise.all([
      apiFetch(`/api/costs/summary?days=${days}`),
      apiFetch(`/api/costs/sessions?limit=20&days=${days}`),
      apiFetch(`/api/costs/daily?days=${days}`),
    ])
      .then(([s, sess, d]) => {
        setSummary(s);
        setSessions(sess.sessions || []);
        setDaily(d.daily || []);
      })
      .catch((e) => setError(e.message || 'Failed to load cost data'))
      .finally(() => setLoading(false));
  }, [days]);

  // ── Daily chart data ────────────────────────────────────────────────────────

  const chartData = {
    labels: daily.map((r) => r.date),
    datasets: [
      {
        label: 'API cost (USD)',
        data: daily.map((r) => r.api_cost_usd || 0),
        backgroundColor: '#6366f1cc',
        borderRadius: 4,
      },
      {
        label: 'Infra (USD)',
        data: daily.map((r) => r.infra_usd || 0),
        backgroundColor: '#d1d5db',
        borderRadius: 4,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'bottom', labels: { font: { size: 11 }, boxWidth: 12 } },
      tooltip: {
        callbacks: {
          label: (ctx) => ` ${ctx.dataset.label}: ${fmt(ctx.parsed.y)}`,
        },
      },
    },
    scales: {
      x: {
        stacked: true,
        ticks: { font: { size: 10 }, maxRotation: 45, minRotation: 30 },
        grid: { display: false },
      },
      y: {
        stacked: true,
        ticks: {
          font: { size: 10 },
          callback: (v) => `$${v.toFixed(2)}`,
        },
        grid: { color: '#f3f4f6' },
      },
    },
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Cost Transparency</h1>
          <p className="text-sm text-gray-500 mt-0.5">Real spend tracking across API tokens, proxy, and infrastructure</p>
        </div>
        <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-lg p-1">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                days === d
                  ? 'bg-indigo-600 text-white'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorBox message={error} />}

      {loading ? (
        <Spinner />
      ) : (
        <>
          {/* Summary cards */}
          {summary && (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <SummaryCard
                label="Total spend"
                amount={fmt(summary.total_usd)}
                note={`Last ${days} days`}
                accent="indigo"
              />
              <SummaryCard
                label="API tokens"
                amount={fmt(summary.breakdown?.api_tokens_usd)}
                note="Exact — billed by providers"
                accent="emerald"
              />
              <SummaryCard
                label="Proxy (Brightdata)"
                amount={fmt(summary.breakdown?.proxy_usd)}
                note={summary.proxy_source === 'brightdata_api' ? 'Exact — from Brightdata API' : 'Estimated — set BRIGHTDATA_API_KEY for exact data'}
                accent="amber"
              />
              <SummaryCard
                label="Infra estimate"
                amount={fmt(summary.breakdown?.infra_usd)}
                note="Estimated — Cloud Run + SQL"
                accent="gray"
              />
            </div>
          )}

          {/* Per-LLM breakdown */}
          {summary?.per_llm && summary.per_llm.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-base font-semibold text-gray-900 mb-4">Per-platform breakdown</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
                      <th className="pb-3 pr-6">Platform</th>
                      <th className="pb-3 pr-6 text-right">Results</th>
                      <th className="pb-3 pr-6 text-right">Cost (USD)</th>
                      <th className="pb-3 text-right">Cost per result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {summary.per_llm.map((row) => (
                      <tr key={row.llm} className="hover:bg-gray-50">
                        <td className="py-3 pr-6 font-medium text-gray-900 capitalize">{row.llm}</td>
                        <td className="py-3 pr-6 text-right text-gray-700">
                          {row.result_count != null ? row.result_count.toLocaleString() : '—'}
                        </td>
                        <td className="py-3 pr-6 text-right text-gray-900 font-medium">{fmt(row.cost_usd)}</td>
                        <td className="py-3 text-right text-gray-500">
                          {costPerResult(row.cost_usd, row.result_count)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {summary.browser_sessions != null && (
                <p className="text-xs text-gray-400 mt-3">
                  Browser sessions in period: <span className="font-medium text-gray-600">{summary.browser_sessions}</span>
                </p>
              )}
            </div>
          )}

          {/* Daily trend chart */}
          {daily.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-base font-semibold text-gray-900 mb-4">Daily cost trend</h2>
              <div style={{ height: 200 }}>
                <Bar data={chartData} options={chartOptions} />
              </div>
            </div>
          )}

          {/* Daily trend table fallback (always shown as detail) */}
          {daily.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-base font-semibold text-gray-900 mb-4">Daily breakdown</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
                      <th className="pb-3 pr-6">Date</th>
                      <th className="pb-3 pr-6 text-right">Results</th>
                      <th className="pb-3 pr-6 text-right">API cost</th>
                      <th className="pb-3 text-right">Infra est.</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {daily.map((row) => (
                      <tr key={row.date} className="hover:bg-gray-50">
                        <td className="py-2.5 pr-6 text-gray-700">{row.date}</td>
                        <td className="py-2.5 pr-6 text-right text-gray-700">
                          {row.result_count != null ? row.result_count.toLocaleString() : '—'}
                        </td>
                        <td className="py-2.5 pr-6 text-right text-gray-900 font-medium">{fmt(row.api_cost_usd)}</td>
                        <td className="py-2.5 text-right text-gray-500">{fmt(row.infra_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Recent sessions */}
          {sessions.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-base font-semibold text-gray-900 mb-4">Recent sessions</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
                      <th className="pb-3 pr-6">Started</th>
                      <th className="pb-3 pr-6">Type</th>
                      <th className="pb-3 pr-6 text-right">Prompts</th>
                      <th className="pb-3 pr-6 text-right">API cost</th>
                      <th className="pb-3 pr-6 text-right">Proxy cost</th>
                      <th className="pb-3 pr-6 text-right">Total</th>
                      <th className="pb-3 text-right">Avg latency</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {sessions.map((s) => (
                      <tr key={s.session_id} className="hover:bg-gray-50">
                        <td className="py-2.5 pr-6 text-gray-700">
                          <div>{fmtDate(s.started_at)}</div>
                          <div className="text-xs text-gray-400">{fmtTime(s.started_at)}</div>
                        </td>
                        <td className="py-2.5 pr-6">
                          <TypeBadge method={s.collection_method} />
                        </td>
                        <td className="py-2.5 pr-6 text-right text-gray-700">
                          {s.result_count != null ? s.result_count : '—'}
                        </td>
                        <td className="py-2.5 pr-6 text-right text-gray-900">{fmt(s.api_cost_usd)}</td>
                        <td className="py-2.5 pr-6 text-right text-gray-700">{fmt(s.proxy_cost_usd)}</td>
                        <td className="py-2.5 pr-6 text-right font-medium text-gray-900">{fmt(s.total_usd)}</td>
                        <td className="py-2.5 text-right text-gray-500">
                          {s.avg_latency_ms ? `${(s.avg_latency_ms / 1000).toFixed(1)}s` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Info box */}
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 text-sm text-gray-600 space-y-2">
            <p className="font-semibold text-gray-800 text-sm">What's exact vs estimated?</p>
            <ul className="space-y-1 list-none">
              <li>
                <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 mr-2 align-middle" />
                <strong>API tokens</strong> — exact. Costs are derived from token counts returned by each provider and published pricing.
              </li>
              <li>
                <span className="inline-block w-2 h-2 rounded-full bg-amber-500 mr-2 align-middle" />
                <strong>Proxy (Brightdata)</strong> — exact. Billed per browser session initiated; shown as recorded.
              </li>
              <li>
                <span className="inline-block w-2 h-2 rounded-full bg-gray-400 mr-2 align-middle" />
                <strong>Infra</strong> — estimated. Cloud Run CPU/memory and Cloud SQL are allocated costs; actual GCP invoices may differ slightly.
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
