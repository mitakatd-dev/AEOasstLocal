import { useState, useEffect } from 'react';
import { apiFetch } from '../api';

function Section({ title, children }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      {children}
    </div>
  );
}


function StatusBadge({ set, trueLabel = 'Configured', falseLabel = 'Not set' }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${set ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
      {set ? trueLabel : falseLabel}
    </span>
  );
}

function CodeBlock({ children }) {
  return (
    <pre className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 text-xs font-mono text-gray-700 overflow-x-auto whitespace-pre">
      {children}
    </pre>
  );
}

export default function Settings() {
  // ── Brand config ──────────────────────────────────────────────────────────
  const [targetCompany, setTargetCompany] = useState('');
  const [competitors, setCompetitors] = useState('');
  const [brandSaved, setBrandSaved] = useState(false);

  // ── API keys ──────────────────────────────────────────────────────────────
  const [openaiKey, setOpenaiKey] = useState('');
  const [geminiKey, setGeminiKey] = useState('');
  const [perplexityKey, setPerplexityKey] = useState('');
  const [keyStatus, setKeyStatus] = useState({ openai: false, gemini: false, perplexity: false });
  const [showKeys, setShowKeys] = useState({ openai: false, gemini: false, perplexity: false });
  const [keysSaved, setKeysSaved] = useState(false);

  // ── Brightdata (proxy) ────────────────────────────────────────────────────
  const [brightdataKey, setBrightdataKey] = useState('');
  const [brightdataZone, setBrightdataZone] = useState('residential_proxy');
  const [brightdataKeySet, setBrightdataKeySet] = useState(false);
  const [showBdKey, setShowBdKey] = useState(false);
  const [proxySaved, setProxySaved] = useState(false);

  // ── Browser Accounts ──────────────────────────────────────────────────────
  const [accounts, setAccounts] = useState([]);
  const [accountsError, setAccountsError] = useState(null);
  const [newAccPlatform, setNewAccPlatform] = useState('chatgpt');
  const [newAccLabel, setNewAccLabel] = useState('');
  const [newAccSession, setNewAccSession] = useState('');
  const [addingAccount, setAddingAccount] = useState(false);
  const [accountMsg, setAccountMsg] = useState(null);

  // ── Cost tracking ─────────────────────────────────────────────────────────
  const [costSummary, setCostSummary] = useState(null);

  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiFetch('/api/settings/'),
      apiFetch('/api/accounts/'),
      apiFetch('/api/costs/summary?days=30').catch(() => null),
    ])
      .then(([s, a, costs]) => {
        setTargetCompany(s.target_company || '');
        setCompetitors((s.competitors || []).join(', '));
        setKeyStatus({ openai: s.openai_key_set, gemini: s.gemini_key_set, perplexity: s.perplexity_key_set });
        setBrightdataKeySet(s.brightdata_key_set || false);
        setBrightdataZone(s.brightdata_zone || 'residential_proxy');
        setAccounts(a);
        setCostSummary(costs);
      })
      .catch((e) => console.error('Settings load error:', e.message))
      .finally(() => setLoading(false));
  }, []);

  // Shared helper — always keep competitors consistent across save operations
  const competitorList = () => competitors.split(',').map((c) => c.trim()).filter(Boolean);

  const saveBrand = (e) => {
    e.preventDefault();
    apiFetch('/api/settings/', {
      method: 'PUT',
      body: JSON.stringify({ target_company: targetCompany, competitors: competitorList() }),
    }).then(() => {
      setBrandSaved(true);
      setTimeout(() => setBrandSaved(false), 2000);
    });
  };

  const saveKeys = (e) => {
    e.preventDefault();
    const body = { target_company: targetCompany, competitors: competitorList() };
    if (openaiKey) body.openai_key = openaiKey;
    if (geminiKey) body.gemini_key = geminiKey;
    if (perplexityKey) body.perplexity_key = perplexityKey;
    apiFetch('/api/settings/', { method: 'PUT', body: JSON.stringify(body) })
      .then((s) => {
        setKeyStatus({ openai: s.openai_key_set, gemini: s.gemini_key_set, perplexity: s.perplexity_key_set });
        setOpenaiKey(''); setGeminiKey(''); setPerplexityKey('');
        setKeysSaved(true);
        setTimeout(() => setKeysSaved(false), 2000);
      });
  };

  const saveProxy = (e) => {
    e.preventDefault();
    const body = {
      target_company: targetCompany,
      competitors: competitorList(),
      brightdata_zone: brightdataZone,
    };
    if (brightdataKey) body.brightdata_key = brightdataKey;
    apiFetch('/api/settings/', { method: 'PUT', body: JSON.stringify(body) })
      .then((s) => {
        setBrightdataKeySet(s.brightdata_key_set || false);
        setBrightdataKey('');
        setProxySaved(true);
        setTimeout(() => setProxySaved(false), 2000);
      });
  };

  async function addAccount(e) {
    e.preventDefault();
    if (!newAccLabel.trim() || !newAccSession.trim()) return;
    try {
      JSON.parse(newAccSession);
    } catch {
      setAccountMsg({ type: 'error', text: 'Session JSON is not valid — paste the full contents of the .json file.' });
      return;
    }
    setAddingAccount(true);
    setAccountMsg(null);
    try {
      const acc = await apiFetch('/api/accounts/', {
        method: 'POST',
        body: JSON.stringify({ platform: newAccPlatform, label: newAccLabel.trim(), storage_state: newAccSession.trim() }),
      });
      setAccounts((prev) => [...prev, acc]);
      setNewAccLabel('');
      setNewAccSession('');
      setAccountMsg({ type: 'ok', text: `Account added (${acc.id.slice(0, 8)}…)` });
    } catch (ex) {
      setAccountMsg({ type: 'error', text: ex.message });
    } finally {
      setAddingAccount(false);
    }
  }

  async function expireAccount(id) {
    await apiFetch(`/api/accounts/${id}/expire`, { method: 'PUT' });
    setAccounts((prev) => prev.map((a) => a.id === id ? { ...a, status: 'expired' } : a));
  }

  async function deleteAccount(id) {
    await apiFetch(`/api/accounts/${id}`, { method: 'DELETE' });
    setAccounts((prev) => prev.filter((a) => a.id !== id));
  }

  function handleSessionFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setNewAccSession(ev.target.result);
    reader.readAsText(file);
  }

  if (loading) return <p className="text-gray-400 text-sm">Loading…</p>;

  // 'none' is an explicit revocation — exclude from Pending Approval.
  // Only show users who have truly never been assigned a role (null/undefined).
  const pendingUsers = users.filter((u) => !u.role || u.role === '');
  const activeUsers = users.filter((u) => u.role === 'admin' || u.role === 'viewer');

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {/* ── Brand Configuration ─────────────────────────────────────────── */}
      <Section title="Brand Configuration">
        <form onSubmit={saveBrand} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Target Company Name</label>
            <input
              type="text"
              value={targetCompany}
              onChange={(e) => setTargetCompany(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
              placeholder="e.g. Maersk"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Competitors <span className="font-normal text-gray-400">(comma-separated)</span></label>
            <input
              type="text"
              value={competitors}
              onChange={(e) => setCompetitors(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
              placeholder="MSC, CMA CGM, Hapag-Lloyd"
            />
          </div>
          <div className="flex items-center gap-3">
            <button type="submit" className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700">
              Save
            </button>
            {brandSaved && <span className="text-green-600 text-sm">Saved!</span>}
          </div>
        </form>
      </Section>

      {/* ── LLM API Keys ────────────────────────────────────────────────── */}
      <Section title="LLM API Keys">
        <p className="text-xs text-gray-400 -mt-2">Keys are stored securely in the database and never returned to the browser. Leave a field blank to keep the existing value.</p>
        <form onSubmit={saveKeys} className="space-y-3">
          {[
            { id: 'openai', label: 'OpenAI (GPT-4o)', value: openaiKey, setter: setOpenaiKey, set: keyStatus.openai, placeholder: 'sk-...' },
            { id: 'gemini', label: 'Google Gemini', value: geminiKey, setter: setGeminiKey, set: keyStatus.gemini, placeholder: 'AI...' },
            { id: 'perplexity', label: 'Perplexity Sonar', value: perplexityKey, setter: setPerplexityKey, set: keyStatus.perplexity, placeholder: 'pplx-...' },
          ].map(({ id, label, value, setter, set, placeholder }) => (
            <div key={id}>
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm font-medium text-gray-700">{label}</label>
                <StatusBadge set={set} />
              </div>
              <div className="flex gap-2">
                <input
                  type={showKeys[id] ? 'text' : 'password'}
                  value={value}
                  onChange={(e) => setter(e.target.value)}
                  placeholder={set ? '••••••••  (leave blank to keep current)' : placeholder}
                  className="flex-1 border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-300"
                />
                <button
                  type="button"
                  onClick={() => setShowKeys((prev) => ({ ...prev, [id]: !prev[id] }))}
                  className="px-3 py-2 text-xs border rounded-lg text-gray-500 hover:bg-gray-50"
                >
                  {showKeys[id] ? 'Hide' : 'Show'}
                </button>
              </div>
            </div>
          ))}
          <div className="flex items-center gap-3 pt-1">
            <button type="submit" className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700">
              Save Keys
            </button>
            {keysSaved && <span className="text-green-600 text-sm">Saved!</span>}
          </div>
        </form>
      </Section>

      {/* ── Browser Sessions ─────────────────────────────────────────────── */}
      <Section title="Browser Sessions">
        <div className="space-y-4 -mt-2">

          {/* When do I need this? */}
          <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1">
            <p className="font-semibold">When do you need new sessions?</p>
            <ul className="list-disc list-inside space-y-0.5 text-blue-700">
              <li>First setup — no sessions exist yet for a platform</li>
              <li>Runner reports <code className="bg-blue-100 px-1 rounded">waiting_login</code> in the Research tab</li>
              <li>Session expired (typically after 2–4 weeks)</li>
            </ul>
            <p className="pt-1 text-blue-600">
              You do <strong>not</strong> need sessions for API-mode research (GPT-4o, Gemini, Perplexity via API keys).
              Sessions are only required for browser-mode runs that interact with the chatbot UI directly.
            </p>
          </div>

          {/* Capture steps */}
          <div>
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">How to capture a new session</p>
            <div className="space-y-3">

              <div>
                <p className="text-xs text-gray-500 mb-1">1. Install dependencies (one-time, on your local machine)</p>
                <CodeBlock>{`pip install playwright camoufox
python -m playwright install chromium`}</CodeBlock>
              </div>

              <div>
                <p className="text-xs text-gray-500 mb-1">2. Run the capture script — replace values as needed</p>
                <CodeBlock>{`# From the aeo-insights project root:
python3 scripts/capture_session.py \\
  --platform chatgpt \\
  --label your@email.com \\
  --api https://aeo-insights-stg.web.app \\
  --upload

# For other platforms, change --platform:
#   --platform gemini
#   --platform perplexity`}</CodeBlock>
              </div>

              <div>
                <p className="text-xs text-gray-500 mb-1">3. Log in when the browser opens, then press Enter in the terminal</p>
                <p className="text-xs text-gray-400">
                  The script saves <code className="bg-gray-100 px-1 rounded">chatgpt_session.json</code> locally
                  and uploads it automatically when <code className="bg-gray-100 px-1 rounded">--upload</code> is passed.
                  You can also upload manually below.
                </p>
              </div>

            </div>
          </div>

          {/* Account list */}
          {accountsError && <p className="text-red-500 text-sm">{accountsError}</p>}
          {['chatgpt', 'gemini', 'perplexity'].map((platform) => {
            const platformAccounts = accounts.filter((a) => a.platform === platform);
            const labels = { chatgpt: 'ChatGPT', gemini: 'Gemini', perplexity: 'Perplexity' };
            const activeCount = platformAccounts.filter((a) => a.status === 'active').length;
            return (
              <div key={platform} className="border rounded-lg overflow-hidden">
                <div className="bg-gray-50 px-4 py-2 flex items-center justify-between border-b">
                  <span className="text-sm font-medium text-gray-700">{labels[platform]}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    activeCount > 0 ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                  }`}>
                    {activeCount > 0 ? `${activeCount} active` : 'No active sessions'}
                  </span>
                </div>
                {platformAccounts.length === 0 ? (
                  <p className="text-xs text-gray-400 px-4 py-3">No sessions added yet.</p>
                ) : (
                  <div className="divide-y divide-gray-100">
                    {platformAccounts.map((acc) => (
                      <div key={acc.id} className="flex items-center justify-between px-4 py-2">
                        <div>
                          <p className="text-sm text-gray-800 font-medium">{acc.label}</p>
                          <p className="text-xs text-gray-400 font-mono">{acc.id.slice(0, 8)}…
                            {acc.last_used_at && (
                              <span className="ml-2">last used {new Date(acc.last_used_at).toLocaleDateString()}</span>
                            )}
                          </p>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                            acc.status === 'active'  ? 'bg-green-100 text-green-700' :
                            acc.status === 'expired' ? 'bg-red-100 text-red-600' :
                                                       'bg-yellow-100 text-yellow-700'
                          }`}>
                            {acc.status}
                          </span>
                          {acc.status === 'active' && (
                            <button
                              onClick={() => expireAccount(acc.id)}
                              className="text-xs text-amber-500 hover:underline"
                            >
                              Mark expired
                            </button>
                          )}
                          <button
                            onClick={() => deleteAccount(acc.id)}
                            className="text-xs text-red-400 hover:underline"
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {/* Upload session manually */}
          <div className="pt-2 border-t">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Upload Session File Manually</p>
            <form onSubmit={addAccount} className="space-y-3">
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="block text-xs text-gray-500 mb-1">Platform</label>
                  <select
                    value={newAccPlatform}
                    onChange={(e) => setNewAccPlatform(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
                  >
                    <option value="chatgpt">ChatGPT</option>
                    <option value="gemini">Gemini</option>
                    <option value="perplexity">Perplexity</option>
                  </select>
                </div>
                <div className="flex-1">
                  <label className="block text-xs text-gray-500 mb-1">Label (email / name)</label>
                  <input
                    type="text"
                    value={newAccLabel}
                    onChange={(e) => setNewAccLabel(e.target.value)}
                    placeholder="account@example.com"
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">
                  Session file <span className="font-normal text-gray-400">(produced by capture_session.py)</span>
                </label>
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={handleSessionFile}
                  className="block w-full text-sm text-gray-500 file:mr-3 file:py-1.5 file:px-3 file:border file:border-gray-300 file:rounded-lg file:text-xs file:font-medium file:bg-white hover:file:bg-gray-50"
                />
                {newAccSession && (
                  <p className="text-xs text-green-600 mt-1">File loaded ({newAccSession.length.toLocaleString()} chars)</p>
                )}
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="submit"
                  disabled={addingAccount || !newAccLabel.trim() || !newAccSession.trim()}
                  className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
                >
                  {addingAccount ? 'Adding…' : 'Add Session'}
                </button>
                {accountMsg && (
                  <span className={`text-sm ${accountMsg.type === 'ok' ? 'text-green-600' : 'text-red-500'}`}>
                    {accountMsg.text}
                  </span>
                )}
              </div>
            </form>
          </div>
        </div>
      </Section>

      {/* ── Proxy ───────────────────────────────────────────────────────── */}
      <Section title="Proxy (Brightdata)">
        <div className="space-y-4 -mt-2">

          <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 text-xs text-gray-600 space-y-1">
            <p className="font-semibold text-gray-700">When is a proxy needed?</p>
            <p>
              Cloud Run research jobs run with stored sessions — the login step is bypassed entirely, so
              Cloud Run IPs are never exposed to login-gate IP checks. <strong>No proxy is needed for research.</strong>
            </p>
            <p>
              A proxy may be needed if your <strong>local machine&rsquo;s IP is blocked</strong> when capturing a new
              session (i.e. <code className="bg-gray-100 px-1 rounded">capture_session.py</code> opens the browser and
              you get a CAPTCHA or blocked page before you can log in). In that case, configure Brightdata below and
              re-run the capture script with <code className="bg-gray-100 px-1 rounded">--proxy</code>.
            </p>
          </div>

          <form onSubmit={saveProxy} className="space-y-3">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm font-medium text-gray-700">Brightdata API Key</label>
                <StatusBadge set={brightdataKeySet} />
              </div>
              <div className="flex gap-2">
                <input
                  type={showBdKey ? 'text' : 'password'}
                  value={brightdataKey}
                  onChange={(e) => setBrightdataKey(e.target.value)}
                  placeholder={brightdataKeySet ? '••••••••  (leave blank to keep current)' : 'your-brightdata-api-key'}
                  className="flex-1 border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-300"
                />
                <button
                  type="button"
                  onClick={() => setShowBdKey((v) => !v)}
                  className="px-3 py-2 text-xs border rounded-lg text-gray-500 hover:bg-gray-50"
                >
                  {showBdKey ? 'Hide' : 'Show'}
                </button>
              </div>
              <p className="text-xs text-gray-400 mt-1">
                Found at brightdata.com → Account → API token. Requires Finance/Admin permission to read zone cost.
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Zone Name</label>
              <input
                type="text"
                value={brightdataZone}
                onChange={(e) => setBrightdataZone(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-300"
                placeholder="residential_proxy"
              />
              <p className="text-xs text-gray-400 mt-1">
                The Brightdata zone to use for cost tracking. Shown in your Brightdata dashboard under Zones.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button type="submit" className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700">
                Save Proxy Settings
              </button>
              {proxySaved && <span className="text-green-600 text-sm">Saved!</span>}
            </div>
          </form>
        </div>
      </Section>

      {/* ── Cost Tracking ───────────────────────────────────────────────── */}
      <Section title="Cost Tracking">
        <div className="space-y-3 -mt-2">
          <p className="text-xs text-gray-500">
            Costs are tracked automatically — no manual setup required. Infrastructure spend is
            pulled from Cloud Monitoring (zero-setup; uses the Cloud Run service account).
          </p>

          {costSummary && (
            <div className="space-y-2">
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'API Tokens (30d)', value: `$${costSummary.breakdown?.api_tokens_usd?.toFixed(4) ?? '—'}`, note: 'Exact' },
                  { label: 'Proxy (30d)',       value: `$${costSummary.breakdown?.proxy_usd?.toFixed(4) ?? '—'}`,       note: costSummary.proxy_source === 'brightdata_api' ? 'Real' : 'Estimate' },
                  { label: 'Infra (30d)',        value: `$${costSummary.breakdown?.infra_usd?.toFixed(2) ?? '—'}`,       note: costSummary.infra_source === 'cloud_monitoring' ? 'Real' : 'Estimate' },
                ].map(({ label, value, note }) => (
                  <div key={label} className="border rounded-lg px-3 py-2 text-center">
                    <p className="text-xs text-gray-500">{label}</p>
                    <p className="text-lg font-semibold text-gray-900 mt-0.5">{value}</p>
                    <p className="text-xs text-gray-400">{note}</p>
                  </div>
                ))}
              </div>

              <div className="text-xs text-gray-400 space-y-0.5">
                <p>Infra source: <span className="font-mono">{costSummary.infra_source ?? 'unknown'}</span></p>
                {costSummary.note?.infra && <p>{costSummary.note.infra}</p>}
              </div>
            </div>
          )}

          {!costSummary && (
            <p className="text-xs text-gray-400">Could not load cost summary.</p>
          )}
        </div>
      </Section>

    </div>
  );
}
