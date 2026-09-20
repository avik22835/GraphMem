const GM_BASE = window.location.origin;

function _headers(useJwt = false) {
  const h = { 'Content-Type': 'application/json' };
  if (useJwt) {
    h['Authorization'] = `Bearer ${gmGetIdToken()}`;
  } else {
    const key = localStorage.getItem('gm_api_key') || '';
    if (key) h['X-API-Key'] = key;
  }
  return h;
}

async function _req(method, path, body = null, useJwt = false) {
  const opts = { method, headers: _headers(useJwt) };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(`${GM_BASE}${path}`, opts);
  if (resp.status === 204) return null;
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

// Auth — JWT required
const AuthAPI = {
  createKey: (name, permissions) =>
    _req('POST', '/auth/keys', { project_name: name, permissions }, true),
  listKeys: () =>
    _req('GET', '/auth/keys', null, true),
  revokeKey: (keyId) =>
    _req('DELETE', `/auth/keys/${keyId}`, null, true),
};

// Conversations — API key
const ConversationsAPI = {
  create:  (meta)   => _req('POST', '/conversations', { metadata: meta || {} }),
  list:    ()       => _req('GET',  '/conversations'),
  stats:   (id)     => _req('GET',  `/conversations/${id}/stats`),
  export:  (id)     => _req('GET',  `/conversations/${id}/export`),
  delete:  (id)     => _req('DELETE', `/conversations/${id}`),
};

// Memory — API key
const MemoryAPI = {
  addPrompt:   (convId, content, meta)      => _req('POST', '/memory/prompt', { conversation_id: convId, content, metadata: meta }),
  addResponse: (memId, convId, content)     => _req('POST', `/memory/${memId}/response`, { conversation_id: convId, content }),
  addBatch:    (items)                      => _req('POST', '/memory/batch', { items }),
  recall:      (convId, query, opts = {})   => _req('POST', '/memory/recall', { conversation_id: convId, query, ...opts }),
  get:         (memId)                      => _req('GET',  `/memory/${memId}`),
  delete:      (memId)                      => _req('DELETE', `/memory/${memId}`),
  neighbours:  (memId, threshold = 0.5)     => _req('GET',  `/memory/${memId}/neighbours?threshold=${threshold}`),
};

// Topics — API key
const TopicsAPI = {
  list:       (convId, status)  => _req('GET',  `/topics?conversation_id=${convId}${status ? '&status='+status : ''}`),
  current:    (convId, mode)    => _req('GET',  `/topics/current?conversation_id=${convId}&mode=${mode||'centroid'}`),
  relevance:  (convId, query, n)=> _req('GET',  `/topics/relevance?conversation_id=${convId}&query=${encodeURIComponent(query)}&top_n=${n||3}`),
  retrieve:   (convId, query, topN, maxTokens) =>
    _req('POST', '/topics/retrieve', { conversation_id: convId, query, top_n: topN||3, max_tokens: maxTokens }),
  recompute:  (convId)          => _req('POST', `/topics/recompute?conversation_id=${convId}`),
  get:        (topicId)         => _req('GET',  `/topics/${topicId}`),
  summary:    (topicId)         => _req('GET',  `/topics/${topicId}/summary`),
  status:     (topicId)         => _req('GET',  `/topics/${topicId}/status`),
  messages:   (topicId, convId, query, maxTokens) => {
    let url = `/topics/${topicId}/messages?conversation_id=${convId}`;
    if (query) url += `&query=${encodeURIComponent(query)}`;
    if (maxTokens) url += `&max_tokens=${maxTokens}`;
    return _req('GET', url);
  },
};

// Utils
const UtilsAPI = {
  health:      ()     => _req('GET',  '/health'),
  countTokens: (text) => _req('POST', '/utils/count_tokens', { text }),
};
