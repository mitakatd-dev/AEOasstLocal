import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '../api';

const LLM_ORDER = ['openai', 'gemini', 'perplexity'];

function SentimentBadge({ sentiment }) {
  const colors = {
    positive: 'bg-green-100 text-green-700',
    neutral: 'bg-gray-100 text-gray-600',
    negative: 'bg-red-100 text-red-700',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[sentiment] || 'bg-gray-100 text-gray-600'}`}>
      {sentiment}
    </span>
  );
}

function PositionLabel({ score }) {
  if (score === null || score === undefined) return <span className="text-gray-400">N/A</span>;
  let label = 'Late';
  if (score < 0.25) label = 'Early';
  else if (score < 0.5) label = 'Mid-early';
  else if (score < 0.75) label = 'Mid-late';
  return (
    <span>
      {label} — <span className="font-mono">{score.toFixed(2)}</span>
    </span>
  );
}

export default function RunDetail() {
  const { id } = useParams();
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({});

  useEffect(() => {
    apiFetch(`/api/runs/${id}`)
      .then(setRun)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <p className="text-gray-500">Loading...</p>;
  if (!run) return <p className="text-red-500">Run not found.</p>;

  const resultsByLlm = {};
  (run.results || []).forEach((r) => {
    resultsByLlm[r.llm] = r;
  });

  return (
    <div>
      <Link to="/" className="text-indigo-600 text-sm hover:underline mb-4 inline-block">
        &larr; Back to Dashboard
      </Link>
      <h1 className="text-2xl font-bold mb-1">Run #{run.id}</h1>
      <p className="text-sm text-gray-500 mb-6">
        {run.prompt_label} &middot; {run.triggered_at ? new Date(run.triggered_at).toLocaleString() : ''} &middot; Status: {run.status}
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {LLM_ORDER.map((llm) => {
          const r = resultsByLlm[llm];
          if (!r) {
            return (
              <div key={llm} className="bg-white rounded-lg border p-4">
                <h2 className="font-semibold capitalize mb-2">{llm}</h2>
                <p className="text-gray-400 text-sm">No result</p>
              </div>
            );
          }

          return (
            <div key={llm} className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold capitalize mb-3">{llm}</h2>

              {r.error ? (
                <p className="text-red-500 text-sm mb-2">Error: {r.error}</p>
              ) : (
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-500">Mentioned</span>
                    <span className={r.mentioned ? 'text-green-600 font-medium' : 'text-red-500 font-medium'}>
                      {r.mentioned ? 'Yes' : 'No'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Sentiment</span>
                    <SentimentBadge sentiment={r.sentiment} />
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Position</span>
                    <PositionLabel score={r.position_score} />
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Competitors</span>
                    <span>
                      {r.competitors_mentioned && r.competitors_mentioned.length > 0
                        ? r.competitors_mentioned.join(', ')
                        : 'None'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Latency</span>
                    <span>{r.latency_ms > 0 ? `${(r.latency_ms / 1000).toFixed(1)}s` : '-'}</span>
                  </div>
                  {(r.total_tokens > 0 || r.cost_usd > 0) && (
                    <div className="mt-2 pt-2 border-t space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-gray-400">Tokens (in/out)</span>
                        <span>{r.prompt_tokens} / {r.completion_tokens}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-gray-400">Cost</span>
                        <span className="font-medium">${r.cost_usd > 0 ? r.cost_usd.toFixed(4) : '0.00'}</span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="mt-3">
                <button
                  onClick={() => setExpanded((prev) => ({ ...prev, [llm]: !prev[llm] }))}
                  className="text-indigo-600 text-xs hover:underline"
                >
                  {expanded[llm] ? 'Hide' : 'Show'} raw response
                </button>
                {expanded[llm] && (
                  <pre className="mt-2 text-xs bg-gray-50 border rounded p-2 whitespace-pre-wrap max-h-64 overflow-y-auto">
                    {r.raw_response || 'No response'}
                  </pre>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
