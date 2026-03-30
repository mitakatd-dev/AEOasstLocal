import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '../api';
import { useAuth } from '../contexts/AuthContext';

const QUERY_TYPES = ['category', 'problem', 'comparison', 'brand_direct'];
const TYPE_COLORS = {
  category:    'bg-blue-100 text-blue-700',
  problem:     'bg-teal-100 text-teal-700',
  comparison:  'bg-amber-100 text-amber-700',
  brand_direct:'bg-gray-200 text-gray-700',
};
const TYPE_LABELS = {
  category: 'Category', problem: 'Problem',
  comparison: 'Comparison', brand_direct: 'Brand Direct',
};

// ── Queue helper ───────────────────────────────────────────────────────────────
const QUEUE_KEY = { api: 'aeo_pending_api', browser: 'aeo_pending_browser' };
function queueForResearch(method, prompts) {
  localStorage.setItem(QUEUE_KEY[method], JSON.stringify({
    prompt_ids:    prompts.map(p => p.id),
    prompt_labels: prompts.map(p => p.label),
    count:         prompts.length,
    sent_at:       new Date().toISOString(),
  }));
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function Toast({ message, type = 'info', onClose }) {
  useEffect(() => { const t = setTimeout(onClose, 5000); return () => clearTimeout(t); }, [onClose]);
  const colors = {
    info:    'bg-gray-900 text-white',
    success: 'bg-green-800 text-white',
    error:   'bg-red-800 text-white',
  };
  return (
    <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 ${colors[type]} text-sm px-5 py-3 rounded-xl shadow-xl flex items-center gap-4 z-50`}>
      <span>{message}</span>
      {type === 'info' && (
        <Link to="/research" className="underline text-indigo-300 hover:text-indigo-200 whitespace-nowrap">
          Go to Research →
        </Link>
      )}
      <button onClick={onClose} className="text-gray-400 hover:text-white ml-1">✕</button>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function Prompts() {
  const { role } = useAuth();
  const isAdmin = role === 'admin';

  const [prompts,       setPrompts]       = useState([]);
  const [label,         setLabel]         = useState('');
  const [text,          setText]          = useState('');
  const [queryType,     setQueryType]     = useState('');
  const [filterType,    setFilterType]    = useState('');
  const [filterVariant, setFilterVariant] = useState('');
  const [dateFrom,      setDateFrom]      = useState('');
  const [dateTo,        setDateTo]        = useState('');
  const [selected,      setSelected]      = useState(new Set());
  const [toast,         setToast]         = useState(null);
  const [uploading,     setUploading]     = useState(false);
  const [fixing,        setFixing]        = useState(false);
  const [deleteAll,     setDeleteAll]     = useState(false);
  const fileRef = useRef(null);

  const loadPrompts = () => {
    const params = new URLSearchParams();
    if (filterType)    params.set('query_type',    filterType);
    if (filterVariant) params.set('variant_group', filterVariant);
    if (dateFrom)      params.set('date_from',     dateFrom);
    if (dateTo)        params.set('date_to',       dateTo);
    const qs = params.toString();
    apiFetch(`/api/prompts/${qs ? '?' + qs : ''}`).then(setPrompts).catch(() => {});
  };

  useEffect(() => { loadPrompts(); }, [filterType, filterVariant, dateFrom, dateTo]);

  const addPrompt = (e) => {
    e.preventDefault();
    if (!label.trim() || !text.trim()) return;
    apiFetch('/api/prompts/', {
      method: 'POST',
      body: JSON.stringify({ label, text, query_type: queryType || null }),
    }).then(() => { setLabel(''); setText(''); setQueryType(''); loadPrompts(); });
  };

  const deletePrompt = (id) => {
    if (!confirm('Delete this prompt?')) return;
    apiFetch(`/api/prompts/${id}`, { method: 'DELETE' }).then(() => {
      setSelected(prev => { const n = new Set(prev); n.delete(id); return n; });
      loadPrompts();
    });
  };

  const deleteSelected = async () => {
    if (!confirm(`Delete ${selected.size} prompt${selected.size !== 1 ? 's' : ''}? This also removes all their run history.`)) return;
    for (const id of selected) {
      await apiFetch(`/api/prompts/${id}`, { method: 'DELETE' });
    }
    setSelected(new Set());
    loadPrompts();
    setToast({ message: `Deleted ${selected.size} prompts`, type: 'success' });
  };

  // ── CSV upload ───────────────────────────────────────────────────────────────
  const handleCsvUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const data = await apiFetch('/api/prompts/upload-csv', { method: 'POST', body: form });
      loadPrompts();
      setToast({ message: `Imported ${data.created} prompt${data.created !== 1 ? 's' : ''}${data.skipped ? ` · ${data.skipped} skipped (missing label/text)` : ''}`, type: 'success' });
    } catch (err) {
      setToast({ message: `Upload failed: ${err.message}`, type: 'error' });
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  // ── Fix {{brand}} → Maersk ──────────────────────────────────────────────────
  const fixBrandVars = async () => {
    setFixing(true);
    try {
      const data = await apiFetch('/api/prompts/bulk-replace', {
        method: 'POST',
        body: JSON.stringify({ find: '{{brand}}', replace: 'Maersk' }),
      });
      loadPrompts();
      setToast({ message: `Replaced {{brand}} with Maersk in ${data.updated} prompt${data.updated !== 1 ? 's' : ''}`, type: 'success' });
    } finally {
      setFixing(false);
    }
  };

  const toggleSelect = (id) =>
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const selectAll = () =>
    setSelected(selected.size === prompts.length ? new Set() : new Set(prompts.map(p => p.id)));

  const selectByType = (type) =>
    setSelected(new Set(prompts.filter(p => p.query_type === type).map(p => p.id)));

  const selectedPrompts = prompts.filter(p => selected.has(p.id));

  const sendTo = (method) => {
    if (!selectedPrompts.length) return;
    queueForResearch(method, selectedPrompts);
    const lbl = method === 'api' ? 'API Research' : 'Web Research';
    setToast({ message: `${selectedPrompts.length} prompt${selectedPrompts.length !== 1 ? 's' : ''} queued for ${lbl}`, type: 'info' });
  };

  const sendToBoth = () => {
    if (!selectedPrompts.length) return;
    queueForResearch('api', selectedPrompts);
    queueForResearch('browser', selectedPrompts);
    setToast({ message: `${selectedPrompts.length} prompt${selectedPrompts.length !== 1 ? 's' : ''} queued for API + Web Research`, type: 'info' });
  };

  const typeCounts    = QUERY_TYPES.reduce((acc, t) => { acc[t] = prompts.filter(p => p.query_type === t).length; return acc; }, {});
  const variantGroups = [...new Set(prompts.map(p => p.variant_group).filter(Boolean))];

  // Detect any prompts still using {{...}} template variables
  const hasVarPrompts = prompts.some(p => /\{\{.+?\}\}/.test(p.text) || /\{\{.+?\}\}/.test(p.label));

  return (
    <div className="pb-32">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Prompt Library</h1>
        {isAdmin && (
          <div className="flex items-center gap-2">
            {/* CSV upload — admin only */}
            <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={handleCsvUpload} />
            <button onClick={() => fileRef.current?.click()} disabled={uploading}
              className="text-sm px-3 py-1.5 rounded-lg border border-gray-200 hover:border-indigo-300 hover:text-indigo-600 text-gray-500 transition disabled:opacity-40">
              {uploading ? 'Importing…' : '⬆ Import CSV'}
            </button>
          </div>
        )}
      </div>

      {/* CSV format hint — admin only */}
      {isAdmin && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-2 mb-4 text-xs text-blue-700 flex items-center gap-2">
          <span>📋</span>
          <span>CSV import: columns <strong>label</strong>, <strong>text</strong> (required) · <strong>query_type</strong>, <strong>variant_group</strong> (optional). First row = header.</span>
        </div>
      )}

      {/* Variable warning banner — admin only (fix action) */}
      {isAdmin && hasVarPrompts && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-amber-800">Some prompts use <code className="bg-amber-100 px-1 rounded">{'{{brand}}'}</code> placeholder</p>
            <p className="text-xs text-amber-700 mt-0.5">These will be sent literally. Click Fix to replace with the configured brand name.</p>
          </div>
          <button onClick={fixBrandVars} disabled={fixing}
            className="ml-4 flex-shrink-0 bg-amber-500 hover:bg-amber-600 text-white text-xs font-semibold px-4 py-2 rounded-lg transition disabled:opacity-50">
            {fixing ? 'Fixing…' : 'Fix Now →'}
          </button>
        </div>
      )}

      {/* Add prompt — admin only */}
      {isAdmin && (
        <form onSubmit={addPrompt} className="bg-white rounded-xl border p-5 mb-6 space-y-3">
          <h2 className="font-semibold text-sm text-gray-700">Add Prompt</h2>
          <input type="text" placeholder="Label (e.g. 'Best container shipping companies')"
            value={label} onChange={e => setLabel(e.target.value)}
            className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300" />
          <textarea placeholder="Prompt text submitted to the AI…" value={text}
            onChange={e => setText(e.target.value)} rows={3}
            className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300" />
          <div className="flex gap-3">
            <select value={queryType} onChange={e => setQueryType(e.target.value)}
              className="border rounded-lg px-3 py-2 text-sm flex-1 focus:outline-none focus:ring-2 focus:ring-indigo-300">
              <option value="">Query type (optional)</option>
              {QUERY_TYPES.map(t => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
            </select>
            <button type="submit"
              className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700">
              Add Prompt
            </button>
          </div>
        </form>
      )}

      {/* Filters */}
      <div className="bg-white rounded-xl border p-4 mb-4 space-y-3">
        <div className="flex flex-wrap gap-2 items-center">
          <select value={filterType} onChange={e => setFilterType(e.target.value)}
            className="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300">
            <option value="">All types</option>
            {QUERY_TYPES.map(t => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
          </select>
          {variantGroups.length > 0 && (
            <select value={filterVariant} onChange={e => setFilterVariant(e.target.value)}
              className="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300">
              <option value="">All groups</option>
              {variantGroups.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
          )}
          {/* Date range */}
          <label className="text-xs text-gray-400">Added from</label>
          <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
            className="border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300" />
          <label className="text-xs text-gray-400">to</label>
          <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
            className="border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300" />
          {(dateFrom || dateTo) && (
            <button onClick={() => { setDateFrom(''); setDateTo(''); }}
              className="text-xs text-gray-400 hover:text-red-400 underline">Clear dates</button>
          )}
        </div>

        {/* Quick-select row */}
        <div className="flex flex-wrap gap-2 items-center">
          <button onClick={selectAll}
            className="text-sm text-gray-500 hover:text-indigo-600 underline">
            {selected.size === prompts.length && prompts.length > 0 ? 'Deselect all' : `Select all (${prompts.length})`}
          </button>
          <span className="text-gray-300">|</span>
          {QUERY_TYPES.filter(t => typeCounts[t] > 0).map(t => (
            <button key={t} onClick={() => selectByType(t)}
              className={`text-xs px-2.5 py-1 rounded-full border font-medium ${TYPE_COLORS[t]} hover:opacity-80`}>
              {TYPE_LABELS[t]} ({typeCounts[t]})
            </button>
          ))}
          {variantGroups.map(g => (
            <button key={g} onClick={() => setSelected(new Set(prompts.filter(p => p.variant_group === g).map(p => p.id)))}
              className="text-xs px-2.5 py-1 rounded-full border border-gray-200 text-gray-500 hover:border-indigo-300 hover:text-indigo-600">
              {g}
            </button>
          ))}
          <span className="ml-auto text-xs text-gray-400">{prompts.length} prompt{prompts.length !== 1 ? 's' : ''}</span>
        </div>
      </div>

      {/* Prompt list */}
      <div className="space-y-2">
        {prompts.map(p => {
          const hasVar = /\{\{.+?\}\}/.test(p.text) || /\{\{.+?\}\}/.test(p.label);
          return (
            <div key={p.id}
              className={`bg-white rounded-xl border p-4 flex items-start gap-3 transition ${selected.has(p.id) ? 'border-indigo-300 bg-indigo-50' : hasVar ? 'border-amber-200 bg-amber-50/30' : ''}`}>
              <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggleSelect(p.id)}
                className="mt-1 accent-indigo-600" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <Link to={`/prompts/${p.id}`}
                    className="font-medium text-sm text-indigo-600 hover:underline">{p.label}</Link>
                  {p.query_type && (
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${TYPE_COLORS[p.query_type]}`}>
                      {TYPE_LABELS[p.query_type]}
                    </span>
                  )}
                  {hasVar && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200">
                      {'{{var}}'}
                    </span>
                  )}
                  {p.created_at && (
                    <span className="text-xs text-gray-300 ml-auto">
                      {new Date(p.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
                <p className="text-gray-500 text-sm truncate">{p.text}</p>
              </div>
              {isAdmin && (
                <button onClick={() => deletePrompt(p.id)}
                  className="text-gray-300 hover:text-red-500 text-sm transition flex-shrink-0">✕</button>
              )}
            </div>
          );
        })}
        {prompts.length === 0 && (
          <div className="text-center py-16">
            <p className="text-gray-400 text-sm mb-3">No prompts found.</p>
            <button onClick={() => fileRef.current?.click()}
              className="text-sm text-indigo-600 hover:underline">
              Import from CSV →
            </button>
          </div>
        )}
      </div>

      {/* Selection action bar — admin only (write + launch actions) */}
      {isAdmin && selected.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 bg-white border-t shadow-lg px-6 py-4 flex items-center justify-between z-40">
          <div>
            <span className="font-semibold text-gray-800">{selected.size} selected</span>
            <button onClick={deleteSelected}
              className="ml-4 text-xs text-red-400 hover:text-red-600 border border-red-200 hover:border-red-400 px-2.5 py-1 rounded-lg transition">
              Delete selected
            </button>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => setSelected(new Set())}
              className="text-sm text-gray-400 hover:text-gray-600">Clear</button>
            <button onClick={() => sendTo('api')}
              className="px-4 py-2 rounded-lg border border-indigo-200 bg-indigo-50 text-indigo-700 text-sm font-medium hover:bg-indigo-100 transition">
              ⚡ API Research
            </button>
            <button onClick={() => sendTo('browser')}
              className="px-4 py-2 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 text-sm font-medium hover:bg-emerald-100 transition">
              🌐 Web Research
            </button>
            <button onClick={sendToBoth}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 transition">
              Send to Both →
            </button>
          </div>
        </div>
      )}

      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}
