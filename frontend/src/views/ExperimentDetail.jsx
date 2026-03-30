import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '../api';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Bar } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

const LLM_NAMES = ['openai', 'gemini', 'perplexity'];
const LLM_COLORS = {
  openai: { bg: 'rgba(99, 102, 241, 0.7)', border: 'rgb(99, 102, 241)' },
  gemini: { bg: 'rgba(20, 184, 166, 0.7)', border: 'rgb(20, 184, 166)' },
  perplexity: { bg: 'rgba(245, 158, 11, 0.7)', border: 'rgb(245, 158, 11)' },
};

function SentimentBadge({ sentiment }) {
  const c = { positive: 'text-green-600', neutral: 'text-gray-500', negative: 'text-red-600' };
  return <span className={c[sentiment] || 'text-gray-500'}>{sentiment}</span>;
}

export default function ExperimentDetail() {
  const { id } = useParams();
  const [exp, setExp] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [loading, setLoading] = useState(true);
  const [concluding, setConcluding] = useState(false);
  const [conclusion, setConclusion] = useState('');

  useEffect(() => {
    Promise.all([
      apiFetch(`/api/experiments/${id}`),
      apiFetch(`/api/experiments/${id}/comparison`),
    ])
      .then(([expData, compData]) => {
        setExp(expData);
        setComparison(compData);
        setConclusion(expData.conclusion || '');
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  const conclude = () => {
    apiFetch(`/api/experiments/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ status: 'concluded', conclusion }),
    })
      .then((data) => {
        setExp((prev) => ({ ...prev, ...data }));
        setConcluding(false);
      });
  };

  if (loading) return <p className="text-gray-500">Loading...</p>;
  if (!exp) return <p className="text-red-500">Experiment not found.</p>;

  const variants = comparison?.prompts || [];

  const chartData = {
    labels: variants.map((v) => v.label.substring(0, 30)),
    datasets: LLM_NAMES.map((llm) => ({
      label: llm,
      data: variants.map((v) => Math.round((v.per_llm?.[llm]?.mention_rate || 0) * 100)),
      backgroundColor: LLM_COLORS[llm].bg,
      borderColor: LLM_COLORS[llm].border,
      borderWidth: 1,
    })),
  };

  const chartOptions = {
    responsive: true,
    plugins: {
      legend: { position: 'top' },
      title: { display: true, text: 'Mention Rate per Variant per LLM (%)' },
    },
    scales: { y: { beginAtZero: true, max: 100 } },
  };

  return (
    <div>
      <Link to="/experiments" className="text-indigo-600 text-sm hover:underline mb-4 inline-block">
        &larr; Back to Experiments
      </Link>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{exp.name}</h1>
          <span className={`inline-block mt-1 px-2 py-0.5 rounded text-xs font-medium ${exp.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-700'}`}>
            {exp.status}
          </span>
        </div>
        {exp.status === 'active' && !concluding && (
          <button
            onClick={() => setConcluding(true)}
            className="bg-gray-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-gray-700"
          >
            Mark as Concluded
          </button>
        )}
      </div>

      <div className="bg-white rounded-lg border p-4 mb-6">
        <h2 className="text-sm font-medium text-gray-500 mb-1">Hypothesis</h2>
        <p className="text-sm">{exp.hypothesis}</p>
      </div>

      {concluding && (
        <div className="bg-white rounded-lg border p-4 mb-6">
          <h2 className="text-sm font-medium text-gray-500 mb-2">Write your conclusion</h2>
          <textarea
            value={conclusion}
            onChange={(e) => setConclusion(e.target.value)}
            rows={4}
            className="w-full border rounded px-3 py-2 text-sm mb-3"
            placeholder="What did you learn from this experiment?"
          />
          <div className="flex gap-2">
            <button onClick={conclude} className="bg-green-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-green-700">
              Save & Conclude
            </button>
            <button onClick={() => setConcluding(false)} className="text-gray-500 text-sm hover:underline">
              Cancel
            </button>
          </div>
        </div>
      )}

      {exp.status === 'concluded' && exp.conclusion && (
        <div className="bg-green-50 rounded-lg border border-green-200 p-4 mb-6">
          <h2 className="text-sm font-medium text-green-700 mb-1">Conclusion</h2>
          <p className="text-sm">{exp.conclusion}</p>
          {exp.concluded_at && (
            <p className="text-xs text-green-500 mt-2">Concluded: {new Date(exp.concluded_at).toLocaleString()}</p>
          )}
        </div>
      )}

      <h2 className="text-lg font-semibold mb-3">Prompts in variant group: {exp.variant_group}</h2>
      {(exp.prompts || []).length === 0 ? (
        <p className="text-gray-500 text-sm mb-6">
          No prompts tagged with variant group "{exp.variant_group}" yet.{' '}
          <Link to="/prompts" className="text-indigo-600 hover:underline">Add prompts</Link>
        </p>
      ) : (
        <div className="space-y-1 mb-6">
          {(exp.prompts || []).map((p) => (
            <div key={p.id} className="bg-white rounded border px-3 py-2 text-sm flex items-center gap-2">
              <span className="font-medium">{p.label}</span>
              {p.query_type && (
                <span className="px-1.5 py-0.5 rounded text-xs bg-gray-100 text-gray-600">{p.query_type.replace('_', ' ')}</span>
              )}
              <span className="text-gray-400 truncate flex-1">{p.text}</span>
            </div>
          ))}
        </div>
      )}

      {variants.length > 0 && (
        <>
          <h2 className="text-lg font-semibold mb-3">Comparison</h2>
          <div className="bg-white rounded-lg border overflow-x-auto mb-6">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-4 py-2 font-medium">Variant</th>
                  <th className="text-center px-4 py-2 font-medium">Runs</th>
                  <th className="text-center px-4 py-2 font-medium">Mention Rate</th>
                  {LLM_NAMES.map((l) => (
                    <th key={l} className="text-center px-4 py-2 font-medium capitalize">{l}</th>
                  ))}
                  <th className="text-center px-4 py-2 font-medium">Avg Position</th>
                  <th className="text-center px-4 py-2 font-medium">Sentiment</th>
                </tr>
              </thead>
              <tbody>
                {variants.map((v) => (
                  <tr key={v.prompt_id} className="border-b last:border-0">
                    <td className="px-4 py-2 font-medium">{v.label}</td>
                    <td className="text-center px-4 py-2">{v.runs}</td>
                    <td className="text-center px-4 py-2">{Math.round(v.mention_rate * 100)}%</td>
                    {LLM_NAMES.map((l) => (
                      <td key={l} className="text-center px-4 py-2">
                        {Math.round((v.per_llm?.[l]?.mention_rate || 0) * 100)}%
                        <span className="text-xs text-gray-400 ml-1">
                          <SentimentBadge sentiment={v.per_llm?.[l]?.avg_sentiment || 'neutral'} />
                        </span>
                      </td>
                    ))}
                    <td className="text-center px-4 py-2">
                      {v.avg_position !== null ? v.avg_position.toFixed(2) : '—'}
                    </td>
                    <td className="text-center px-4 py-2">
                      <span className="text-green-600">{v.sentiment_breakdown?.positive || 0}</span>
                      {' / '}
                      <span className="text-gray-500">{v.sentiment_breakdown?.neutral || 0}</span>
                      {' / '}
                      <span className="text-red-600">{v.sentiment_breakdown?.negative || 0}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="bg-white rounded-lg border p-4 mb-6">
            <Bar data={chartData} options={chartOptions} />
          </div>
        </>
      )}
    </div>
  );
}
