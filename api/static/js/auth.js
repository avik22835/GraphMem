/* GraphMem auth helpers — calls backend proxy, not Cognito directly */

async function _api(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || 'Authentication error');
  return data;
}

async function gmSignUp(email, password) {
  return _api('/auth/signup', { email, password });
}

async function gmConfirmSignUp(email, code) {
  return _api('/auth/confirm', { email, code });
}

async function gmSignIn(email, password) {
  const data = await _api('/auth/signin', { email, password });
  localStorage.setItem('gm_id_token',      data.id_token);
  localStorage.setItem('gm_access_token',  data.access_token);
  localStorage.setItem('gm_refresh_token', data.refresh_token);
  localStorage.setItem('gm_email',         email);
  return data;
}

async function gmResend(email) {
  return _api('/auth/resend', { email });
}

function gmSignOut() {
  ['gm_id_token','gm_access_token','gm_refresh_token','gm_email','gm_api_key'].forEach(k => localStorage.removeItem(k));
  window.location.href = '/login';
}

function gmGetIdToken()      { return localStorage.getItem('gm_id_token')  || ''; }
function gmGetEmail()        { return localStorage.getItem('gm_email')     || ''; }
function gmGetApiKey()       { return localStorage.getItem('gm_api_key')   || ''; }
function gmIsAuthenticated() { return !!localStorage.getItem('gm_id_token'); }

function gmRequireAuth() {
  if (!gmIsAuthenticated()) {
    window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
  }
}
