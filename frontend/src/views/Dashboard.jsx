import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '../api';
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, ArcElement, Filler, Tooltip, Legend,
} from 'chart.js';
import annotationPlugin from 'chartjs-plugin-annotation';
import { Line, Bar, Doughnut } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, ArcElement, Filler, Tooltip, Legend, annotationPlugin,
);

const LLM_NAMES = ['openai', 'gemini', 'perplexity'];
const LLM_LABELS = { openai: 'OpenAI GPT-4o', gemini: 'Gemini 1.5 Flash', perplexity: 'Perplexity Sonar' };
const LLM_COLORS = { openai: '#6366f1', gemini: '#10b981', perplexity: '#f59e0b' };
const SENT_COLOR = { positive: 'text-green-600', neutral: 'text-gray-500', negative: 'text-red-600' };

const QT_COLORS = { category: 'bg-blue-100 text-blue-700', problem: 'bg-teal-100 text-teal-700', comparison: 'bg-amber-100 text-amber-700', brand_direct: 'bg-gray-100 text-gray-600' };
const QT_LABELS = { category: 'Category', problem: 'Problem', comparison: 'Comparison', brand_direct: 'Brand Direct' };

function formatCost(usd) {
  if (!usd || usd === 0) return '$0.00';
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function formatTokens(n) {
  if (!n) return '0';
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toString();
}

function StatusBadge({ status }) {
  const c = { completed: 'bg-green-100 text-green-700', partial: 'bg-yellow-100 text-yellow-700', failed: 'bg-red-100 text-red-700', running: 'bg-blue-100 text-blue-700' };
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${c[status] || 'bg-gray-100 text-gray-600'}`}>{status}</span>;
}

function MentionBadge({ results, llm }) {
  const r = results.find((res) => res.llm === llm);
  if (!r) return <span className="text-gray-400 text-xs">-</span>;
  if (r.error) return <span className="text-red-400 text-xs">err</span>;
  return r.mentioned
    ? <span className="text-green-600 text-xs font-medium">Yes</span>
    : <span className="text-red-500 text-xs font-medium">No</span>;
}

/* Sparkline — minimal line chart */
function Sparkline({ data, labels, color, height = 60, events = [] }) {
  if (!data || data.length === 0) return <p className="text-gray-400 text-xs">No trend data</p>;
  const annotations = {};
  (events || []).forEach((ev, i) => {
    const idx = labels.indexOf(ev.date?.split('T')[0]);
    if (idx >= 0) {
      annotations[`evt${i}`] = {
        type: 'line', xMin: idx, xMax: idx, borderColor: '#9ca3af', borderWidth: 1, borderDash: [4, 2],
        label: { display: true, content: ev.description, position: 'start', font: { size: 9 }, backgroundColor: 'rgba(0,0,0,0.6)' },
      };
    }
  });
  return (
    <Line
      data={{ labels, datasets: [{ data, borderColor: color || '#6366f1', backgroundColor: `${color || '#6366f1'}22`, fill: true, pointRadius: data.length > 10 ? 0 : 2, borderWidth: 2, tension: 0.3 }] }}
      options={{
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => `${ctx.parsed.y}%` } }, annotation: { annotations } },
        scales: { x: { display: false }, y: { display: false, min: 0, max: 100 } },
      }}
      height={height}
    />
  );
}

// ── Date range helpers ────────────────────────────────────────────────────────
const PRESETS = [
  { label: 'All time', value: 'all' },
  { label: '90d', value: '90' },
  { label: '30d', value: '30' },
  { label: '14d', value: '14' },
  { label: '7d', value: '7' },
  { label: 'Custom', value: 'custom' },
];

function presetToDates(preset) {
  if (preset === 'all' || preset === 'custom') return { from: null, to: null };
  const days = parseInt(preset, 10);
  const to = new Date().toISOString().split('T')[0];
  const from = new Date(Date.now() - days * 86400000).toISOString().split('T')[0];
  return { from, to };
}

function buildQS(from, to) {
  const p = new URLSearchParams();
  if (from) p.set('from_date', from);
  if (to) p.set('to_date', to);
  const s = p.toString();
  return s ? `?${s}` : '';
}

export default function Dashboard() {
  const [runs, setRuns] = useState([]);
  const [stats, setStats] = useState(null);
  const [narrative, setNarrative] = useState(null);
  const [settings, setSettings] = useState(null);
  const [prompts, setPrompts] = useState([]);
  const [loading, setLoading] = useState(true);

  // ── Filter mode: 'date' | 'batch' ────────────────────────────────────────
  const [filterMode, setFilterMode] = useState('batch');

  // ── Date range state ──────────────────────────────────────────────────────
  const [preset, setPreset] = useState('30');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState(new Date().toISOString().split('T')[0]);
  const [activeFrom, setActiveFrom] = useState(null);
  const [activeTo, setActiveTo]   = useState(null);

  // ── Batch state ────────────────────────────────────────────────────────────
  const [batches, setBatches]           = useState([]);
  const [selectedBatch, setSelectedBatch] = useState(null); // full batch object

  // Trend data
  const [dashTrend, setDashTrend] = useState(null);
  const [perLlmTrend, setPerLlmTrend] = useState(null);
  const [sentimentTrend, setSentimentTrend] = useState(null);
  const [sov, setSov] = useState(null);
  const [events, setEvents] = useState([]);

  // Action log form
  const [eventDate, setEventDate] = useState(new Date().toISOString().split('T')[0]);
  const [eventDesc, setEventDesc] = useState('');

  const fetchAll = useCallback((from, to) => {
    const qs = buildQS(from, to);
    setLoading(true);
    Promise.all([
      apiFetch('/api/runs/?per_page=10'),
      apiFetch(`/api/stats/${qs}`),
      apiFetch(`/api/stats/narrative${qs}`),
      apiFetch('/api/settings/'),
      apiFetch('/api/prompts/'),
      apiFetch(`/api/trends/dashboard${qs}`),
      apiFetch(`/api/trends/per-llm${qs}`),
      apiFetch(`/api/trends/sentiment${qs}`),
      apiFetch(`/api/trends/share-of-voice${qs}`),
      apiFetch('/api/events/'),
    ])
      .then(([r, s, n, st, p, dt, plt, sent, sovData, ev]) => {
        setRuns(r); setStats(s); setNarrative(n); setSettings(st); setPrompts(p);
        setDashTrend(dt); setPerLlmTrend(plt); setSentimentTrend(sent); setSov(sovData); setEvents(ev);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    // Load batches and auto-select the latest one
    apiFetch('/api/runs/batches')
      .then(bs => {
        setBatches(bs);
        if (bs.length > 0) {
          const latest = bs[0];
          setSelectedBatch(latest);
          setFilterMode('batch');
          fetchAll(latest.from_dt, latest.to_dt);
        } else {
          fetchAll(null, null);
        }
      })
      .catch(() => fetchAll(null, null));
  }, [fetchAll]);

  const applyBatch = (batch) => {
    setSelectedBatch(batch);
    setFilterMode('batch');
    fetchAll(batch.from_dt, batch.to_dt);
  };

  const applyPreset = (p) => {
    setPreset(p);
    setFilterMode('date');
    setSelectedBatch(null);
    if (p === 'custom') return;
    const { from, to } = presetToDates(p);
    setActiveFrom(from); setActiveTo(to);
    fetchAll(from, to);
  };

  const applyCustom = () => {
    setFilterMode('date');
    setSelectedBatch(null);
    setActiveFrom(customFrom || null);
    setActiveTo(customTo || null);
    fetchAll(customFrom || null, customTo || null);
  };

  const addEvent = () => {
    if (!eventDesc.trim()) return;
    apiFetch('/api/events/', { method: 'POST', body: JSON.stringify({ date: eventDate, description: eventDesc }) })
      .then(() => { setEventDesc(''); fetchAll(activeFrom, activeTo); });
  };

  const deleteEvent = (id) => {
    apiFetch(`/api/events/${id}`, { method: 'DELETE' }).then(() => fetchAll(activeFrom, activeTo));
  };

  const brand = settings?.target_company || 'your brand';
  const hasNarrative = narrative?.has_data;
  const summary = narrative?.summary || {};
  const brandNarr = narrative?.brand_narrative || {};
  const competitors = narrative?.competitors || [];
  const gaps = narrative?.positioning_gaps || [];
  const blindSpots = narrative?.blind_spots || {};

  // Prompt coverage counts
  const coverage = { category: 0, problem: 0, comparison: 0, brand_direct: 0, untagged: 0 };
  prompts.forEach(p => {
    if (p.query_type && coverage[p.query_type] !== undefined) coverage[p.query_type]++;
    else coverage.untagged++;
  });

  // Trend labels
  const trendLabels = (dashTrend?.data || []).map(d => d.date);
  const trendData = (dashTrend?.data || []).map(d => d.mention_rate);

  // Human-readable range label for KPI header
  const rangeLabel = filterMode === 'batch' && selectedBatch
    ? selectedBatch.label
    : preset === 'all'
      ? 'All time'
      : preset === 'custom'
        ? (activeFrom && activeTo ? `${activeFrom} → ${activeTo}` : 'Custom range')
        : `Last ${preset} days`;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">AEO Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">
            Tracking <span className="font-semibold text-gray-700">{brand}</span> visibility across AI engines
            {loading && <span className="ml-2 text-indigo-400 text-xs">Refreshing…</span>}
          </p>
        </div>

        {/* ── Filter controls ── */}
        <div className="flex flex-col gap-2 items-end">
          {/* Mode tabs */}
          <div className="flex rounded-lg border overflow-hidden text-sm">
            <button onClick={() => { setFilterMode('batch'); if (selectedBatch) fetchAll(selectedBatch.from_dt, selectedBatch.to_dt); }}
              className={`px-3 py-1.5 font-medium transition ${filterMode === 'batch' ? 'bg-indigo-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
              Run Batches
            </button>
            <button onClick={() => setFilterMode('date')}
              className={`px-3 py-1.5 font-medium transition ${filterMode === 'date' ? 'bg-indigo-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
              Date Range
            </button>
          </div>

          {/* Batch picker */}
          {filterMode === 'batch' && (
            <div className="flex items-center gap-2 flex-wrap justify-end">
              {batches.length === 0
                ? <span className="text-xs text-gray-400">No batches found</span>
                : batches.map(b => (
                    <button key={b.batch_index} onClick={() => applyBatch(b)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition whitespace-nowrap ${
                        selectedBatch?.batch_index === b.batch_index
                          ? 'bg-indigo-600 text-white border-indigo-600'
                          : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300 hover:text-indigo-600'
                      }`}>
                      {b.is_latest && <span className="mr-1">⚡</span>}
                      {b.label}
                      {b.failed > 0 && <span className="ml-1 text-red-400">{b.failed}✗</span>}
                    </button>
                  ))
              }
            </div>
          )}

          {/* Date range picker */}
          {filterMode === 'date' && (
            <div className="flex flex-wrap items-center gap-2 justify-end">
              {PRESETS.map(p => (
                <button key={p.value} onClick={() => applyPreset(p.value)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
                    preset === p.value && !selectedBatch
                      ? 'bg-indigo-600 text-white'
                      : 'bg-white border text-gray-600 hover:border-indigo-300 hover:text-indigo-600'
                  }`}>
                  {p.label}
                </button>
              ))}
              {preset === 'custom' && (
                <div className="flex items-center gap-2 mt-1 sm:mt-0">
                  <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)}
                    className="border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300" />
                  <span className="text-gray-400 text-sm">→</span>
                  <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)}
                    className="border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300" />
                  <button onClick={applyCustom}
                    className="bg-indigo-600 text-white px-3 py-1.5 rounded-lg text-sm font-medium hover:bg-indigo-700">
                    Apply
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {!hasNarrative ? (
        <div className="text-center py-16 bg-white rounded-lg border">
          <p className="text-gray-500 mb-2">No data yet.</p>
          <p className="text-gray-400 text-sm mb-4">Run prompts to start analyzing {brand}'s AI visibility.</p>
          <Link to="/prompts" className="text-indigo-600 font-medium hover:underline">Go to Prompts</Link>
        </div>
      ) : (
        <>
          {/* === PROMPT COVERAGE GRID === */}
          <div className="grid grid-cols-5 gap-3 mb-6">
            {Object.entries(QT_LABELS).map(([key, label]) => (
              <div key={key} className="bg-white rounded-lg border p-3 text-center">
                <p className="text-xs text-gray-400">{label}</p>
                <p className="text-2xl font-bold">{coverage[key]}</p>
              </div>
            ))}
            <div className="bg-white rounded-lg border p-3 text-center">
              <p className="text-xs text-gray-400">Untagged</p>
              <p className="text-2xl font-bold text-gray-400">{coverage.untagged}</p>
            </div>
          </div>
          {prompts.length > 0 && coverage.untagged === prompts.length && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-6 text-sm text-amber-700">
              Tag your prompts with a query type to unlock coverage analysis.
            </div>
          )}

          {/* === BRAND POSITION + VISIBILITY TREND === */}
          <div className="bg-white rounded-lg border p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Brand Position</h2>
              <span className="text-xs text-gray-400 bg-gray-50 border rounded px-2 py-1">{rangeLabel}</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-4">
              <div>
                <p className="text-xs text-gray-400 uppercase">Mention Rate</p>
                <p className={`text-3xl font-bold ${summary.mention_rate >= 70 ? 'text-green-600' : summary.mention_rate >= 40 ? 'text-amber-600' : 'text-red-600'}`}>
                  {summary.mention_rate}%
                </p>
                <p className="text-xs text-gray-500">{summary.mentioned_count} of {summary.total_results} responses</p>
              </div>
              <div>
                <p className="text-xs text-gray-400 uppercase">Position When Mentioned</p>
                <p className="text-xl font-bold">{summary.position_label}</p>
                <p className="text-xs text-gray-500">{summary.avg_position ? `Score: ${summary.avg_position}` : ''}</p>
              </div>
              <div>
                <p className="text-xs text-gray-400 uppercase">How LLMs Describe {brand}</p>
                <div className="flex flex-wrap gap-1 mt-1">
                  {(brandNarr.descriptors || []).slice(0, 6).map(([word, count]) => (
                    <span key={word} className="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded text-xs font-medium">
                      {word} ({count})
                    </span>
                  ))}
                  {(brandNarr.descriptors || []).length === 0 && <span className="text-gray-400 text-sm">Not enough data</span>}
                </div>
              </div>
              <div>
                <p className="text-xs text-gray-400 uppercase">Not Mentioned In</p>
                <p className="text-3xl font-bold text-gray-400">{summary.not_mentioned_count}</p>
                <p className="text-xs text-gray-500">responses where {brand} was absent</p>
              </div>
            </div>
            {/* Visibility trend sparkline */}
            <div className="border-t pt-3">
              <p className="text-xs text-gray-400 mb-2">Mention rate trend — {rangeLabel}</p>
              <div style={{ height: 80 }}>
                <Sparkline data={trendData} labels={trendLabels} color="#6366f1" height={80} events={events} />
              </div>
            </div>
          </div>

          {/* === SHARE OF VOICE === */}
          {sov && sov.competitors && sov.competitors.length > 0 && (
            <div className="bg-white rounded-lg border p-6 mb-6">
              <h2 className="text-lg font-semibold mb-4">Share of Voice</h2>
              <p className="text-xs text-gray-500 mb-4">Brand vs competitor mention rates across {sov.total_results} LLM responses</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Bar chart */}
                <div>
                  <Bar
                    data={{
                      labels: [sov.brand.name, ...sov.competitors.map(c => c.name)],
                      datasets: [{
                        label: 'Mention Rate %',
                        data: [sov.brand.mention_rate, ...sov.competitors.map(c => c.mention_rate)],
                        backgroundColor: [
                          '#6366f1',
                          ...sov.competitors.map(() => '#e5e7eb'),
                        ],
                        borderRadius: 4,
                      }],
                    }}
                    options={{
                      indexAxis: 'y', responsive: true,
                      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${ctx.parsed.x}%` } } },
                      scales: { x: { max: 100, ticks: { callback: v => `${v}%` } } },
                    }}
                    height={Math.max(200, (1 + sov.competitors.length) * 35)}
                  />
                </div>
                {/* Donut chart */}
                <div className="flex items-center justify-center">
                  <div style={{ maxWidth: 250 }}>
                    <Doughnut
                      data={{
                        labels: [sov.brand.name, ...sov.competitors.map(c => c.name)],
                        datasets: [{
                          data: [sov.brand.mentions, ...sov.competitors.map(c => c.mentions)],
                          backgroundColor: ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#84cc16', '#ec4899', '#14b8a6'],
                        }],
                      }}
                      options={{ responsive: true, plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } } }}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* === HOW LLMs TALK ABOUT THE BRAND === */}
          {(brandNarr.contexts || []).length > 0 && (
            <div className="mb-6">
              <h2 className="text-lg font-semibold mb-1">How LLMs Talk About {brand}</h2>
              <p className="text-sm text-gray-500 mb-3">Actual excerpts from LLM responses where {brand} is mentioned</p>
              <div className="space-y-3">
                {(brandNarr.contexts || []).slice(0, 6).map((ctx, i) => (
                  <div key={i} className="bg-white rounded-lg border p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs font-medium text-gray-500 uppercase">{ctx.llm}</span>
                      <span className={`text-xs ${SENT_COLOR[ctx.sentiment] || 'text-gray-500'}`}>{ctx.sentiment}</span>
                      <span className="text-xs text-gray-400">|</span>
                      <span className="text-xs text-gray-400">{ctx.prompt_label}</span>
                    </div>
                    <p className="text-sm text-gray-700 leading-relaxed">{ctx.context}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* === COMPETITIVE POSITIONING === */}
          {competitors.length > 0 && (
            <div className="mb-6">
              <h2 className="text-lg font-semibold mb-1">Competitive Positioning</h2>
              <p className="text-sm text-gray-500 mb-3">How competitors are described vs {brand}</p>
              <div className="bg-white rounded-lg border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="text-left px-4 py-2 font-medium">Competitor</th>
                      <th className="text-center px-4 py-2 font-medium">Overall %</th>
                      <th className="text-center px-3 py-2 font-medium text-indigo-600">GPT-4o</th>
                      <th className="text-center px-3 py-2 font-medium text-emerald-600">Gemini</th>
                      <th className="text-center px-3 py-2 font-medium text-amber-600">Perplexity</th>
                      <th className="text-left px-4 py-2 font-medium">Descriptors</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b bg-indigo-50">
                      <td className="px-4 py-2 font-semibold text-indigo-700">{brand} <span className="text-xs font-normal text-indigo-400">(you)</span></td>
                      <td className="text-center px-4 py-2 font-bold">{summary.mention_rate}%</td>
                      <td className="text-center px-3 py-2 font-medium text-indigo-600">
                        {summary.by_llm?.openai ? `${summary.by_llm.openai.mention_rate}%` : '—'}
                      </td>
                      <td className="text-center px-3 py-2 font-medium text-emerald-600">
                        {summary.by_llm?.gemini ? `${summary.by_llm.gemini.mention_rate}%` : '—'}
                      </td>
                      <td className="text-center px-3 py-2 font-medium text-amber-600">
                        {summary.by_llm?.perplexity ? `${summary.by_llm.perplexity.mention_rate}%` : '—'}
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex flex-wrap gap-1">
                          {(brandNarr.descriptors || []).slice(0, 4).map(([w]) => (
                            <span key={w} className="bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded text-xs">{w}</span>
                          ))}
                        </div>
                      </td>
                    </tr>
                    {competitors.slice(0, 8).map((c) => (
                      <tr key={c.name} className="border-b last:border-0 hover:bg-gray-50">
                        <td className="px-4 py-2 font-medium">{c.name}</td>
                        <td className="text-center px-4 py-2">{c.mention_rate}%</td>
                        <td className="text-center px-3 py-2 text-indigo-600">
                          {c.by_llm?.openai != null ? `${c.by_llm.openai.mention_rate}%` : '—'}
                        </td>
                        <td className="text-center px-3 py-2 text-emerald-600">
                          {c.by_llm?.gemini != null ? `${c.by_llm.gemini.mention_rate}%` : '—'}
                        </td>
                        <td className="text-center px-3 py-2 text-amber-600">
                          {c.by_llm?.perplexity != null ? `${c.by_llm.perplexity.mention_rate}%` : '—'}
                        </td>
                        <td className="px-4 py-2">
                          <div className="flex flex-wrap gap-1">
                            {(c.descriptors || []).slice(0, 4).map(([w]) => (
                              <span key={w} className="bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded text-xs">{w}</span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* === IMPROVEMENT AREAS === */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            {gaps.length > 0 && (
              <div className="bg-white rounded-lg border p-4">
                <h3 className="font-semibold text-sm mb-1">Positioning Gaps</h3>
                <p className="text-xs text-gray-500 mb-3">Descriptors competitors get that {brand} doesn't</p>
                <div className="space-y-2">
                  {gaps.map((g) => (
                    <div key={g.descriptor} className="flex items-center justify-between">
                      <span className="bg-red-50 text-red-700 px-2 py-0.5 rounded text-sm font-medium">{g.descriptor}</span>
                      <span className="text-xs text-gray-400">used {g.competitor_count}x for competitors</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {(blindSpots.prompts_where_not_mentioned || []).length > 0 && (
              <div className="bg-white rounded-lg border p-4">
                <h3 className="font-semibold text-sm mb-1">Blind Spots</h3>
                <p className="text-xs text-gray-500 mb-3">Prompts where {brand} is never mentioned</p>
                <div className="space-y-2">
                  {(blindSpots.prompts_where_not_mentioned || []).map(([label, count]) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-sm text-gray-700">{label}</span>
                      <span className="text-xs text-gray-400">{count} misses</span>
                    </div>
                  ))}
                </div>
                {(blindSpots.competitors_appearing_instead || []).length > 0 && (
                  <div className="mt-3 pt-3 border-t">
                    <p className="text-xs text-gray-500 mb-2">Who appears instead:</p>
                    <div className="flex flex-wrap gap-1">
                      {(blindSpots.competitors_appearing_instead || []).map(([name, count]) => (
                        <span key={name} className="bg-amber-50 text-amber-700 px-2 py-0.5 rounded text-xs">{name} ({count})</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* === PER-LLM BREAKDOWN WITH SPARKLINES === */}
          {stats && (
            <>
              <h2 className="text-lg font-semibold mb-3">Per-LLM Breakdown</h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                {LLM_NAMES.map((llm) => {
                  const d = stats.per_llm?.[llm];
                  if (!d) return null;
                  const hasCalls = d.successful > 0;
                  const s = d.sentiments || {};
                  const sentMax = Math.max(s.positive || 0, s.neutral || 0, s.negative || 0);
                  const dom = sentMax === 0 ? 'neutral' : s.positive === sentMax ? 'positive' : s.negative === sentMax ? 'negative' : 'neutral';
                  const llmSeries = perLlmTrend?.series?.[llm] || [];
                  return (
                    <div key={llm} className="bg-white rounded-lg border p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="font-semibold text-sm">{LLM_LABELS[llm]}</h3>
                        {d.errors > 0 && <span className="text-xs text-red-400">{d.errors} err</span>}
                      </div>
                      {!hasCalls ? (
                        <p className="text-gray-400 text-sm">No data. Check API key.</p>
                      ) : (
                        <>
                          <div className="mb-3">
                            <div className="flex justify-between text-sm mb-1">
                              <span className="text-gray-500">Mention rate</span>
                              <span className="font-bold">{d.mention_rate}%</span>
                            </div>
                            <div className="w-full bg-gray-100 rounded-full h-2">
                              <div className={`h-2 rounded-full ${d.mention_rate >= 70 ? 'bg-green-500' : d.mention_rate >= 40 ? 'bg-yellow-500' : 'bg-red-400'}`}
                                style={{ width: `${Math.max(d.mention_rate, 2)}%` }} />
                            </div>
                          </div>
                          {/* Per-LLM sparkline */}
                          {llmSeries.length > 0 && (
                            <div className="mb-3" style={{ height: 40 }}>
                              <Sparkline
                                data={llmSeries.map(p => p.mention_rate)}
                                labels={llmSeries.map(p => p.date)}
                                color={LLM_COLORS[llm]}
                                height={40}
                              />
                            </div>
                          )}
                          <div className="space-y-1.5 text-sm">
                            <div className="flex justify-between">
                              <span className="text-gray-500">Sentiment</span>
                              <span className={`font-medium ${SENT_COLOR[dom]}`}>{dom} <span className="text-gray-400 text-xs">({s.positive}+ {s.neutral}= {s.negative}-)</span></span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-gray-500">Latency</span>
                              <span>{d.avg_latency_ms > 0 ? `${(d.avg_latency_ms / 1000).toFixed(1)}s` : '-'}</span>
                            </div>
                          </div>
                          <div className="mt-3 pt-3 border-t flex justify-between text-xs text-gray-500">
                            <span>{formatCost(d.cost_usd)}</span>
                            <span>{formatTokens(d.total_tokens)} tok</span>
                            <span>~{formatCost(d.avg_cost_per_call)}/call</span>
                          </div>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {/* === SENTIMENT TREND === */}
          {sentimentTrend && sentimentTrend.data && sentimentTrend.data.length > 0 && (
            <div className="bg-white rounded-lg border p-6 mb-6">
              <h2 className="text-lg font-semibold mb-4">Sentiment Trend</h2>
              <div style={{ height: 200 }}>
                <Line
                  data={{
                    labels: sentimentTrend.data.map(d => d.date),
                    datasets: [
                      { label: 'Positive %', data: sentimentTrend.data.map(d => d.positive_pct), borderColor: '#10b981', backgroundColor: '#10b98122', fill: true, tension: 0.3, pointRadius: 2 },
                      { label: 'Neutral %', data: sentimentTrend.data.map(d => d.neutral_pct), borderColor: '#9ca3af', backgroundColor: '#9ca3af11', fill: true, tension: 0.3, pointRadius: 2 },
                      { label: 'Negative %', data: sentimentTrend.data.map(d => d.negative_pct), borderColor: '#ef4444', backgroundColor: '#ef444422', fill: true, tension: 0.3, pointRadius: 2 },
                    ],
                  }}
                  options={{
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { position: 'top', labels: { font: { size: 11 } } }, tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y}%` } } },
                    scales: { y: { max: 100, ticks: { callback: v => `${v}%` } } },
                  }}
                />
              </div>
            </div>
          )}

          {/* === ACTION LOG === */}
          <div className="bg-white rounded-lg border p-6 mb-6">
            <h2 className="text-lg font-semibold mb-2">Action Log</h2>
            <p className="text-xs text-gray-500 mb-4">Log external events (published content, campaigns) to track their impact on visibility trends</p>
            <div className="flex gap-2 mb-4">
              <input type="date" value={eventDate} onChange={e => setEventDate(e.target.value)}
                className="border rounded px-3 py-1.5 text-sm" />
              <input type="text" value={eventDesc} onChange={e => setEventDesc(e.target.value)}
                placeholder="e.g. Published blog post on logistics trends"
                className="flex-1 border rounded px-3 py-1.5 text-sm" />
              <button onClick={addEvent}
                className="bg-indigo-600 text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-indigo-700">
                Add Event
              </button>
            </div>
            {events.length > 0 && (
              <div className="space-y-1">
                {events.slice(0, 10).map(ev => (
                  <div key={ev.id} className="flex items-center justify-between text-sm py-1 border-b last:border-0">
                    <div>
                      <span className="text-gray-400 text-xs mr-2">{ev.date?.split('T')[0]}</span>
                      <span className="text-gray-700">{ev.description}</span>
                    </div>
                    <button onClick={() => deleteEvent(ev.id)} className="text-red-400 hover:text-red-600 text-xs">remove</button>
                  </div>
                ))}
              </div>
            )}
            {events.length === 0 && <p className="text-gray-400 text-xs">No events logged yet. Events appear as markers on trend charts.</p>}
          </div>

          {/* === RECENT RUNS === */}
          <h2 className="text-lg font-semibold mb-3">Recent Runs</h2>
          <div className="bg-white rounded-lg border overflow-hidden mb-6">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-4 py-2 font-medium">Prompt</th>
                  <th className="text-left px-4 py-2 font-medium">Time</th>
                  {LLM_NAMES.map((l) => (
                    <th key={l} className="text-center px-4 py-2 font-medium capitalize">{l}</th>
                  ))}
                  <th className="text-center px-4 py-2 font-medium">Cost</th>
                  <th className="text-center px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const cost = (run.results || []).reduce((s, r) => s + (r.cost_usd || 0), 0);
                  return (
                    <tr key={run.id} className="border-b last:border-0 hover:bg-gray-50">
                      <td className="px-4 py-2"><Link to={`/runs/${run.id}`} className="text-indigo-600 hover:underline">{run.prompt_label || `Run #${run.id}`}</Link></td>
                      <td className="px-4 py-2 text-gray-500">{run.triggered_at ? new Date(run.triggered_at).toLocaleString() : '-'}</td>
                      {LLM_NAMES.map((l) => <td key={l} className="text-center px-4 py-2"><MentionBadge results={run.results || []} llm={l} /></td>)}
                      <td className="text-center px-4 py-2 text-xs text-gray-500">{cost > 0 ? formatCost(cost) : '-'}</td>
                      <td className="text-center px-4 py-2"><StatusBadge status={run.status} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

        </>
      )}
    </div>
  );
}
