const COGNITO_REGION    = 'us-east-1';
const COGNITO_CLIENT_ID = '706dfajvla7jbsgllh22ki5c45';
const COGNITO_URL       = `https://cognito-idp.${COGNITO_REGION}.amazonaws.com/`;

async function _cognito(target, body) {
  const resp = await fetch(COGNITO_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `AmazonCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.message || data.__type || 'Authentication error');
  return data;
}

async function gmSignUp(email, password) {
  return _cognito('SignUp', {
    ClientId: COGNITO_CLIENT_ID,
    Username: email,
    Password: password,
    UserAttributes: [{ Name: 'email', Value: email }],
  });
}

async function gmConfirmSignUp(email, code) {
  return _cognito('ConfirmSignUp', {
    ClientId: COGNITO_CLIENT_ID,
    Username: email,
    ConfirmationCode: code.trim(),
  });
}

async function gmSignIn(email, password) {
  const data = await _cognito('InitiateAuth', {
    AuthFlow: 'USER_PASSWORD_AUTH',
    ClientId: COGNITO_CLIENT_ID,
    AuthParameters: { USERNAME: email, PASSWORD: password },
  });
  const t = data.AuthenticationResult;
  localStorage.setItem('gm_id_token',      t.IdToken);
  localStorage.setItem('gm_access_token',  t.AccessToken);
  localStorage.setItem('gm_refresh_token', t.RefreshToken);
  localStorage.setItem('gm_email',         email);
  return t;
}

function gmSignOut() {
  ['gm_id_token','gm_access_token','gm_refresh_token','gm_email','gm_api_key'].forEach(k => localStorage.removeItem(k));
  window.location.href = '/login';
}

function gmGetIdToken()       { return localStorage.getItem('gm_id_token') || ''; }
function gmGetEmail()         { return localStorage.getItem('gm_email') || ''; }
function gmIsAuthenticated()  { return !!localStorage.getItem('gm_id_token'); }

function gmRequireAuth() {
  if (!gmIsAuthenticated()) {
    window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
  }
}
