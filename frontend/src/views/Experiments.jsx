import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '../api';

function StatusBadge({ status }) {
  const colors = {
    active: 'bg-green-100 text-green-700',
    concluded: 'bg-gray-200 text-gray-700',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || 'bg-gray-100'}`}>
      {status}
    </span>
  );
}

export default function Experiments() {
  const [experiments, setExperiments] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [hypothesis, setHypothesis] = useState('');
  const [variantGroup, setVariantGroup] = useState('');
  const [loading, setLoading] = useState(true);

  const load = () => {
    apiFetch('/api/experiments/')
      .then(setExperiments)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const create = (e) => {
    e.preventDefault();
    if (!name.trim() || !hypothesis.trim() || !variantGroup.trim()) return;
    apiFetch('/api/experiments/', {
      method: 'POST',
      body: JSON.stringify({ name, hypothesis, variant_group: variantGroup }),
    })
      .then(() => {
        setName('');
        setHypothesis('');
        setVariantGroup('');
        setShowForm(false);
        load();
      });
  };

  if (loading) return <p className="text-gray-500">Loading...</p>;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Experiments</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700"
        >
          {showForm ? 'Cancel' : 'New Experiment'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={create} className="bg-white rounded-lg border p-4 mb-6 flex flex-col gap-3">
          <input
            type="text"
            placeholder="Experiment name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          />
          <textarea
            placeholder="Hypothesis (required) — what do you believe this experiment will show?"
            value={hypothesis}
            onChange={(e) => setHypothesis(e.target.value)}
            rows={3}
            className="border rounded px-3 py-2 text-sm"
            required
          />
          <input
            type="text"
            placeholder="Variant group (e.g. framing-v1)"
            value={variantGroup}
            onChange={(e) => setVariantGroup(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          />
          <button type="submit" className="self-start bg-green-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-green-700">
            Create Experiment
          </button>
        </form>
      )}

      {experiments.length === 0 ? (
        <p className="text-gray-500 text-sm">No experiments yet. Create one to start testing hypotheses.</p>
      ) : (
        <div className="bg-white rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-left px-4 py-2 font-medium">Hypothesis</th>
                <th className="text-left px-4 py-2 font-medium">Variant Group</th>
                <th className="text-center px-4 py-2 font-medium">Status</th>
                <th className="text-left px-4 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {experiments.map((exp) => (
                <tr key={exp.id} className="border-b last:border-0 hover:bg-gray-50">
                  <td className="px-4 py-2">
                    <Link to={`/experiments/${exp.id}`} className="text-indigo-600 hover:underline font-medium">
                      {exp.name}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-gray-500 max-w-xs truncate">{exp.hypothesis}</td>
                  <td className="px-4 py-2 text-gray-500">{exp.variant_group}</td>
                  <td className="text-center px-4 py-2">
                    <StatusBadge status={exp.status} />
                  </td>
                  <td className="px-4 py-2 text-gray-500">
                    {exp.created_at ? new Date(exp.created_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
