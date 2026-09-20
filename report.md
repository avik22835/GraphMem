# GraphMem API Test Report
**Date:** 2026-09-20  
**API Base:** `http://graphmem-alb-1377576243.us-east-1.elb.amazonaws.com`

---

## TL;DR

API is **live and structurally correct**. Auth middleware works. Cognito pool exists.  
**Full end-to-end flow (add memories → recall → topics) was NOT run** — blocked by one Cognito config checkbox.  
**Fix is 30 seconds in the AWS console.**

---

## What Was Actually Executed vs Not

### ACTUALLY RAN — real HTTP calls made

| # | Call | Result |
|---|------|--------|
| 1 | `GET /health` | ✅ 200 `{"status":"ok"}` |
| 2 | `GET /docs` | ✅ 200 — Swagger UI served |
| 3 | `GET /openapi.json` | ✅ 200 — 23 routes registered |
| 4 | `GET /conversations` (no auth) | ✅ 401 |
| 5 | `POST /conversations` (no auth) | ✅ 401 |
| 6 | `GET /memory/fake-id` (no auth) | ✅ 401 |
| 7 | `POST /memory/prompt` (no auth) | ✅ 401 |
| 8 | `POST /memory/recall` (no auth) | ✅ 401 |
| 9 | `GET /auth/keys` (no auth) | ✅ 401 |
| 10 | `POST /auth/keys` (no auth) | ✅ 401 |
| 11 | `GET /topics` (no auth) | ✅ 401 |
| 12 | `POST /utils/count_tokens` (no auth) | ✅ 401 |
| 13 | `POST /conversations` (fake `gm_sk_...` key) | ✅ 401 `"Invalid or revoked API key"` |
| 14 | `POST /utils/count_tokens` (fake key) | ✅ 401 `"Invalid or revoked API key"` |
| 15 | Cognito `sign_up` via boto3 | ✅ User created, confirmation email queued |
| 16 | Cognito JWKS `/.well-known/jwks.json` | ✅ 200 — 2 RS256 keys returned |
| 17 | Cognito `initiate_auth` USER_PASSWORD_AUTH | ❌ `InvalidParameterException` — **Blocker** |

**16 passed / 1 blocked**

---

### NOT RUN — needed valid JWT/API key (auth flow blocked)

None of these were called with real data:

| Endpoint | Blocked by |
|----------|------------|
| `POST /auth/keys` — create API key | Need valid JWT first |
| `POST /conversations` — create conversation | Need API key |
| `GET /conversations` — list | Need API key |
| `POST /memory/prompt` | Need API key |
| `POST /memory/{id}/response` → queues Lambda | Need API key |
| `POST /memory/batch` — bulk add | Need API key |
| `POST /memory/recall` — semantic recall | Need API key |
| `GET /memory/{id}/neighbours` — graph | Need API key |
| `GET /conversations/{id}/stats` | Need API key |
| `GET /topics?conversation_id=` | Need API key |
| `POST /topics/retrieve` | Need API key |
| `POST /utils/count_tokens` | Need API key |
| Lambda node_worker (Jina embed + Neptune edges) | Not triggered |
| Lambda topic_worker (Louvain + Groq label) | Not triggered |

---

## The One Blocker

`USER_PASSWORD_AUTH` is not enabled on the Cognito app client. The SPA client defaults to `USER_SRP_AUTH` only.

**Fix — 30 seconds:**
1. AWS Console → Cognito → User Pools → `us-east-1_bYrtLpJPH`
2. App clients → `706dfajvla7jbsgllh22ki5c45` → Edit
3. Authentication flows → tick **ALLOW_USER_PASSWORD_AUTH** → Save

Also: local AWS credentials are account `928974129252`, infra is on `748439418518` — admin Cognito ops fail due to account mismatch. After enabling USER_PASSWORD_AUTH, no admin ops are needed at all.

---

## Confirmed Route Map (no /v1/ prefix)

```
GET    /health                               public

POST   /auth/keys                            JWT Bearer only
GET    /auth/keys                            JWT Bearer only
DELETE /auth/keys/{key_id}                   JWT Bearer only

POST   /conversations                        body: {metadata?}
GET    /conversations
DELETE /conversations/{conversation_id}
GET    /conversations/{conversation_id}/stats
GET    /conversations/{conversation_id}/export

POST   /memory/prompt                        body: {conversation_id, content, timestamp?, metadata?}
POST   /memory/{memory_id}/response          body: {conversation_id, content} → queues Lambda
POST   /memory/batch                         body: {items: [{conversation_id, prompt, response}]}
POST   /memory/recall                        body: {conversation_id, query, k?, threshold?, strategy?}
GET    /memory/{memory_id}
DELETE /memory/{memory_id}
GET    /memory/{memory_id}/neighbours        ?threshold=0.7&limit=&order=relevance

GET    /topics                               ?conversation_id=&status=
GET    /topics/current                       ?conversation_id=&mode=centroid
GET    /topics/relevance                     ?conversation_id=&query=&top_n=
POST   /topics/retrieve                      body: {conversation_id, query, top_n?, max_tokens?}
POST   /topics/recompute                     ?conversation_id=
GET    /topics/{topic_id}
GET    /topics/{topic_id}/summary
GET    /topics/{topic_id}/status
GET    /topics/{topic_id}/messages           ?conversation_id=&query=&max_tokens=

POST   /utils/count_tokens
```

---

## Code Review Findings (static)

| Component | Status |
|-----------|--------|
| Auth middleware (`get_current_principal`) | Accepts Bearer JWT + X-API-Key — correct |
| API key format `gm_sk_<32>` prefix indexed | Correct |
| bcrypt offloaded to `asyncio.to_thread` | Correct — non-blocking |
| JWT verification with JWKS cache, RS256 | Correct |
| Memory add flow: prompt → response → SQS | Correct |
| Batch endpoint up to 100 items | Exists — use for demo load |
| All routes behind `dependencies=[Depends(get_current_principal)]` | Correct — no leak |

---

## Notes for Block 10

- `gm.memory.add(conv_id, prompt, response)` = two calls: POST /memory/prompt then POST /memory/{id}/response
- `gm.memory.add_batch(items)` = single POST /memory/batch — faster for demo
- `gm.auth.create_key()` requires Bearer JWT (not API key) — special case
- Playground needs CORS — `CORSMiddleware` not yet in `main.py`
