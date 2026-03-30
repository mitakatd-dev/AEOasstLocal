/**
 * Thin fetch wrapper — local edition.
 * No auth token needed; backend accepts all requests.
 * Usage: import { apiFetch } from '../api';
 *        const data = await apiFetch('/api/prompts/');
 */

export async function apiFetch(path, options = {}) {
  const baseUrl = import.meta.env.VITE_API_URL || '';
  const isFormData = options.body instanceof FormData;

  const headers = {
    ...(!isFormData ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(`${baseUrl}${path}`, { ...options, headers });

  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail || text; } catch { /* keep as text */ }
    const err = new Error(detail);
    err.status = res.status;
    err.detail = detail;
    throw err;
  }

  if (res.status === 204) return null;
  return res.json();
}

// No-op kept for compatibility with any component that calls setTokenGetter
export function setTokenGetter() {}
