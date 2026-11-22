// Thin client for the FileGo API. Always uses relative /api and the session cookie.
// State-changing requests carry the CSRF token the server issued at login.

let csrfToken = null;
let onUnauthorized = () => {};

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export const setCsrf = (token) => { csrfToken = token || null; };
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

function toError(status, body) {
  const e = body && body.error;
  return new ApiError(e?.message || (status ? `Request failed (${status}).` : 'Cannot reach the FileGo server.'), status, e?.code);
}

async function readJson(res) {
  try { return await res.json(); } catch { return null; }
}

export async function request(path, { method = 'GET', json, query } = {}) {
  const url = path + (query ? '?' + new URLSearchParams(Object.entries(query).filter(([, v]) => v !== '' && v != null)) : '');
  const headers = {};
  if (json !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  let res;
  try {
    res = await fetch(url, { method, headers, credentials: 'same-origin', body: json !== undefined ? JSON.stringify(json) : undefined });
  } catch {
    throw toError(0, null);
  }
  const body = await readJson(res);
  if (!res.ok) {
    // An expired session on a normal page: send the user back to the login screen.
    if (res.status === 401 && body?.error?.code === 'unauthenticated' && !path.startsWith('/api/auth/login')) onUnauthorized();
    throw toError(res.status, body);
  }
  return body;
}

export const api = {
  get: (path, query) => request(path, { query }),
  post: (path, json) => request(path, { method: 'POST', json: json ?? {} }),
  patch: (path, json) => request(path, { method: 'PATCH', json }),
  del: (path) => request(path, { method: 'DELETE' }),
};

// ---- auth -------------------------------------------------------------------------------
export async function login(username, password) {
  const r = await api.post('/api/auth/login', { username, password });
  setCsrf(r.csrfToken);
  return r.user;
}
export async function register(fields) {
  const r = await api.post('/api/auth/register', fields);
  setCsrf(r.csrfToken);
  return r.user;
}
export async function restoreSession() {
  try {
    const r = await request('/api/auth/me');
    setCsrf(r.csrfToken);
    return r.user;
  } catch (e) {
    if (e.status === 401) return null;
    throw e;
  }
}
export async function logout() {
  try { await api.post('/api/auth/logout'); } finally { setCsrf(null); }
}

// ---- uploads (raw streaming body with progress) ------------------------------------------
// The file is sent as the request body, so the server reads it in chunks of its buffer size.
export function uploadRaw(url, file, { onProgress, signal } = {}) {
  const started = performance.now();
  const xhr = new XMLHttpRequest();
  const promise = new Promise((resolve, reject) => {
    xhr.open('POST', url);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader('X-File-Name', encodeURIComponent(file.name));
    if (csrfToken) xhr.setRequestHeader('X-CSRF-Token', csrfToken);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded, e.total, (performance.now() - started) / 1000);
    };
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      const seconds = (performance.now() - started) / 1000;
      if (xhr.status >= 200 && xhr.status < 300) resolve({ body, seconds });
      else {
        if (xhr.status === 401) onUnauthorized();
        reject(toError(xhr.status, body));
      }
    };
    xhr.onerror = () => reject(toError(0, null));
    xhr.onabort = () => reject(new ApiError('Upload cancelled.', 0, 'cancelled'));
    xhr.send(file);
  });
  promise.abort = () => xhr.abort();
  return promise;
}

// Tell the server how long the upload took on this device (display only).
export function reportClientTiming(logId, seconds) {
  if (!logId || !(seconds > 0)) return Promise.resolve();
  return api.post(`/api/history/${logId}/client-timing`, { clientSeconds: Math.min(seconds, 21600) }).catch(() => {});
}

// ---- downloads and previews ---------------------------------------------------------------
export const downloadUrl = (id) => `/api/files/${id}/download`;
export const previewUrl = (id) => `/api/files/${id}/preview`;

// The browser's own download manager streams the file (cookie authenticates it).
// A HEAD request first, so an error shows a message instead of replacing the page with JSON.
export async function startDownload(id) {
  let res;
  try { res = await fetch(downloadUrl(id), { method: 'HEAD', credentials: 'same-origin' }); }
  catch { throw toError(0, null); }
  if (res.status === 401) onUnauthorized();
  if (!res.ok) throw new ApiError(res.status === 404 ? 'File not found or no longer available.' : `Download failed (${res.status}).`, res.status);
  const a = document.createElement('a');
  a.href = downloadUrl(id);
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}
