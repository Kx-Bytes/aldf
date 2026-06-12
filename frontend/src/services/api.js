/**
 * API Service Layer — Central hub for all backend communication.
 * 
 * Base URL defaults to the Vite dev proxy ("/api") which forwards
 * to the FastAPI backend at localhost:8000.
 * 
 * If the proxy is unavailable, change API_BASE to "http://localhost:8000".
 */

export function getToken() {
  return localStorage.getItem('aldf_token');
}

export function setToken(token) {
  localStorage.setItem('aldf_token', token);
}

export function clearToken() {
  localStorage.removeItem('aldf_token');
  localStorage.removeItem('aldf_email');
}

const API_BASE = import.meta.env.PROD ? '' : '/api';

// ── Helper ──────────────────────────────────────────────────────────────────
async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const token = getToken();
  const authHeader = token ? { Authorization: `Bearer ${token}` } : {};

  try {
    const res = await fetch(url, {
      headers: { 
        'Content-Type': 'application/json', 
        ...authHeader,
        ...options.headers 
      },
      ...options,
    });
    if (!res.ok) {
      const errBody = await res.text();
      throw new Error(`API ${res.status}: ${errBody}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`[API] ${options.method || 'GET'} ${url} failed:`, err);
    throw err;
  }
}

// ── Bills ───────────────────────────────────────────────────────────────────

/**
 * Fetch bills with optional search/filter parameters.
 * Maps directly to GET /documents/search
 */
export async function fetchBills(params = {}) {
  const query = new URLSearchParams();
  if (params.keyword) query.set('keyword', params.keyword);
  if (params.subject) query.set('subject', params.subject);
  if (params.policyArea) query.set('policy_area', params.policyArea);
  if (params.billType) query.set('bill_type', params.billType);
  if (params.congress) query.set('congress', params.congress);
  if (params.fromActionDate) query.set('from_action_date', params.fromActionDate);
  if (params.toActionDate) query.set('to_action_date', params.toActionDate);
  if (params.sortBy) query.set('sort_by', params.sortBy);
  if (params.order) query.set('order', params.order);
  if (params.limit) query.set('limit', params.limit);
  if (params.offset) query.set('offset', params.offset);
  if (params.userPrompt) query.set('user_prompt', params.userPrompt);
  if (params.minScore) query.set('min_score', params.minScore);

  const qs = query.toString();
  return request(`/documents/search${qs ? '?' + qs : ''}`);
}

/**
 * Fetch the 50 most recent bills (no filters).
 * Maps to GET /documents
 */
export async function fetchRecentDocuments() {
  return request('/documents');
}

/**
 * Fetch full details for a single bill.
 * Maps to GET /documents/{source_id}
 */
export async function fetchBillDetails(sourceId) {
  return request(`/documents/${encodeURIComponent(sourceId)}`);
}

/**
 * Fetch the live action history for a bill from Congress.gov.
 * Maps to GET /documents/{source_id}/actions
 */
export async function fetchBillActions(sourceId) {
  return request(`/documents/${encodeURIComponent(sourceId)}/actions`);
}

// ── Stats ───────────────────────────────────────────────────────────────────

/**
 * Fetch overview statistics (total bills, unique subjects, date range).
 * Maps to GET /stats/overview
 */
export async function fetchStats() {
  return request('/stats/overview');
}

/**
 * Fetch subjects with their document counts.
 * Maps to GET /subjects
 */
export async function fetchSubjects() {
  return request('/subjects');
}

/**
 * Fetch subjects pre-grouped by ALDF focus-area category.
 * Maps to GET /subjects/grouped
 * Returns [{ category, subjects: [{ name, document_count }] }]
 */
export async function fetchSubjectsGrouped() {
  return request('/subjects/grouped');
}

/**
 * Fetch policy area stats.
 * Maps to GET /stats/policy-areas
 */
export async function fetchPolicyAreaStats() {
  return request('/stats/policy-areas');
}

// ── AI ──────────────────────────────────────────────────────────────────────

/**
 * Trigger AI scoring for a single bill.
 * Maps to POST /ai/process/{source_id}
 */
export async function triggerAIProcess(sourceId) {
  return request(`/ai/process/${encodeURIComponent(sourceId)}`, { method: 'POST' });
}

// ── Users ───────────────────────────────────────────────────────────────────

export async function createUser(body) {
  return request('/users', { method: 'POST', body: JSON.stringify(body) });
}

export async function getUser(email) {
  return request(`/users/${encodeURIComponent(email)}`);
}

export async function updateUser(email, body) {
  return request(`/users/${encodeURIComponent(email)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export async function fetchReviewBills(email) {
  return request(`/users/${encodeURIComponent(email)}/review-bills`);
}

// ── Health & Sync ─────────────────────────────────────────────────────────────

export async function checkHealth() {
  return request('/health');
}

export async function triggerSync(congress = 119) {
  return request(`/sync/backfill/${congress}`, { method: 'POST' });
}

// ── Live Search ──────────────────────────────────────────────────────────────

export async function fetchLiveSearch(prompt, date, userEmail = null) {
  return request('/search/live', {
    method: 'POST',
    body: JSON.stringify({ prompt, date, user_email: userEmail })
  });
}

// ── Auth API ─────────────────────────────────────────────────────────────────

export async function signup(email, password) {
  return request('/auth/signup', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function login(email, password) {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function resendVerification(email) {
  return request('/auth/resend-verification', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

export async function verifyAndActivate(email, password, token) {
  return request('/auth/verify-and-activate', {
    method: 'POST',
    body: JSON.stringify({ email, password, token }),
  });
}

