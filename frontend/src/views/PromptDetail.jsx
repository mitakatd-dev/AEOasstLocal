import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '../api';
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  Filler, Tooltip, Legend,
} from 'chart.js';
import { Line } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip, Legend);

const LLM_NAMES = ['openai', 'gemini', 'perplexity'];
const LLM_LABELS = { openai: 'OpenAI GPT-4o', gemini: 'Gemini 1.5 Flash', perplexity: 'Perplexity Sonar' };
const LLM_COLORS = { openai: '#6366f1', gemini: '#10b981', perplexity: '#f59e0b' };
const QT_COLORS = { category: 'bg-blue-100 text-blue-700', problem: 'bg-teal-100 text-teal-700', comparison: 'bg-amber-100 text-amber-700', brand_direct: 'bg-gray-100 text-gray-600' };

function StatusBadge({ status }) {
  const c = { completed: 'bg-green-100 text-green-700', partial: 'bg-yellow-100 text-yellow-700', failed: 'bg-red-100 text-red-700', running: 'bg-blue-100 text-blue-700' };
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${c[status] || 'bg-gray-100 text-gray-600'}`}>{status}</span>;
}

export default function PromptDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch(`/api/trends/prompt/${id}`)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <p className="text-gray-500">Loading...</p>;
  if (!data || data.error) return <p className="text-red-500">Prompt not found.</p>;

  // Build chart data from series
  const allDates = new Set();
  LLM_NAMES.forEach(llm => (data.series?.[llm] || []).forEach(p => allDates.add(p.date)));
  const sortedDates = [...allDates].sort();
  const hasChartData = sortedDates.length > 0;

  const chartDatasets = LLM_NAMES.map(llm => {
    const seriesMap = {};
    (data.series?.[llm] || []).forEach(p => { seriesMap[p.date] = p.mention_rate; });
    return {
      label: LLM_LABELS[llm],
      data: sortedDates.map(d => seriesMap[d] ?? null),
      borderColor: LLM_COLORS[llm],
      backgroundColor: `${LLM_COLORS[llm]}22`,
      fill: false,
      tension: 0.3,
      pointRadius: 3,
      borderWidth: 2,
      spanGaps: true,
    };
  });

  // Aggregate stats per LLM
  const llmStats = {};
  LLM_NAMES.forEach(llm => {
    const series = data.series?.[llm] || [];
    if (series.length === 0) { llmStats[llm] = null; return; }
    const totalMentions = series.reduce((s, p) => s + p.mention_rate, 0);
    const avgMention = totalMentions / series.length;
    const totalSent = { positive: 0, neutral: 0, negative: 0 };
    series.forEach(p => {
      if (p.sentiment) {
        totalSent.positive += p.sentiment.positive || 0;
        totalSent.neutral += p.sentiment.neutral || 0;
        totalSent.negative += p.sentiment.negative || 0;
      }
    });
    llmStats[llm] = { avgMention: avgMention.toFixed(1), sentiment: totalSent, dataPoints: series.length };
  });

  return (
    <div>
      <div className="mb-6">
        <Link to="/prompts" className="text-indigo-600 text-sm hover:underline mb-2 inline-block">&larr; Back to Prompts</Link>
        <h1 className="text-2xl font-bold">{data.label}</h1>
        <p className="text-gray-500 text-sm mt-1">{data.text}</p>
        <div className="flex gap-2 mt-2">
          {data.query_type && (
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${QT_COLORS[data.query_type] || 'bg-gray-100 text-gray-600'}`}>
              {data.query_type}
            </span>
          )}
          {data.variant_group && (
            <span className="bg-purple-50 text-purple-700 px-2 py-0.5 rounded text-xs font-medium">
              {data.variant_group}
            </span>
          )}
        </div>
      </div>

      {/* Mention Rate Trend Chart */}
      {hasChartData ? (
        <div className="bg-white rounded-lg border p-6 mb-6">
          <h2 className="text-lg font-semibold mb-4">Mention Rate Trend</h2>
          <div style={{ height: 300 }}>
            <Line
              data={{ labels: sortedDates, datasets: chartDatasets }}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                  legend: { position: 'top' },
                  tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y}%` } },
                },
                scales: {
                  y: { min: 0, max: 100, ticks: { callback: v => `${v}%` } },
                },
              }}
            />
          </div>
        </div>
      ) : (
        <div className="bg-white rounded-lg border p-8 mb-6 text-center">
          <p className="text-gray-500">No run data for this prompt yet.</p>
          <Link to="/prompts" className="text-indigo-600 text-sm hover:underline mt-2 inline-block">Run this prompt from the Prompts page</Link>
        </div>
      )}

      {/* Per-LLM Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {LLM_NAMES.map(llm => {
          const ls = llmStats[llm];
          if (!ls) return (
            <div key={llm} className="bg-white rounded-lg border p-4">
              <h3 className="font-semibold text-sm mb-2" style={{ color: LLM_COLORS[llm] }}>{LLM_LABELS[llm]}</h3>
              <p className="text-gray-400 text-sm">No data</p>
            </div>
          );
          const sentTotal = ls.sentiment.positive + ls.sentiment.neutral + ls.sentiment.negative;
          const domSent = sentTotal === 0 ? 'neutral' :
            ls.sentiment.positive >= ls.sentiment.neutral && ls.sentiment.positive >= ls.sentiment.negative ? 'positive' :
            ls.sentiment.negative >= ls.sentiment.neutral ? 'negative' : 'neutral';
          return (
            <div key={llm} className="bg-white rounded-lg border p-4">
              <h3 className="font-semibold text-sm mb-3" style={{ color: LLM_COLORS[llm] }}>{LLM_LABELS[llm]}</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500">Avg Mention Rate</span>
                  <span className="font-bold">{ls.avgMention}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Dominant Sentiment</span>
                  <span className={`font-medium ${domSent === 'positive' ? 'text-green-600' : domSent === 'negative' ? 'text-red-600' : 'text-gray-500'}`}>
                    {domSent}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Data Points</span>
                  <span>{ls.dataPoints}</span>
                </div>
                <div className="flex gap-2 text-xs text-gray-400 pt-1 border-t">
                  <span className="text-green-600">{ls.sentiment.positive}+</span>
                  <span>{ls.sentiment.neutral}=</span>
                  <span className="text-red-600">{ls.sentiment.negative}-</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Run History */}
      <h2 className="text-lg font-semibold mb-3">Run History</h2>
      <div className="bg-white rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="text-left px-4 py-2 font-medium">Run</th>
              <th className="text-left px-4 py-2 font-medium">Time</th>
              {LLM_NAMES.map(l => (
                <th key={l} className="text-center px-4 py-2 font-medium">{LLM_LABELS[l]}</th>
              ))}
              <th className="text-center px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {(data.runs || []).map(run => (
              <tr key={run.id} className="border-b last:border-0 hover:bg-gray-50">
                <td className="px-4 py-2">
                  <Link to={`/runs/${run.id}`} className="text-indigo-600 hover:underline">#{run.id}</Link>
                </td>
                <td className="px-4 py-2 text-gray-500">{run.triggered_at ? new Date(run.triggered_at).toLocaleString() : '-'}</td>
                {LLM_NAMES.map(llm => {
                  const r = (run.results || []).find(res => res.llm === llm);
                  if (!r) return <td key={llm} className="text-center px-4 py-2 text-gray-400 text-xs">-</td>;
                  if (r.error) return <td key={llm} className="text-center px-4 py-2 text-red-400 text-xs">err</td>;
                  return (
                    <td key={llm} className="text-center px-4 py-2">
                      {r.mentioned
                        ? <span className="text-green-600 text-xs font-medium">Yes</span>
                        : <span className="text-red-500 text-xs font-medium">No</span>}
                      {r.sentiment && (
                        <span className={`ml-1 text-xs ${r.sentiment === 'positive' ? 'text-green-500' : r.sentiment === 'negative' ? 'text-red-400' : 'text-gray-400'}`}>
                          ({r.sentiment[0]})
                        </span>
                      )}
                    </td>
                  );
                })}
                <td className="text-center px-4 py-2"><StatusBadge status={run.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
