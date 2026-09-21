# GraphMem — Issues, Root Causes & Fix Strategies

> Built for the **First Commit × AWS** hackathon (Sep 2026).  
> Stack: FastAPI on ECS Fargate · Lambda (SQS-triggered) · Neptune · RDS pgvector · Cognito · ALB · ECR · GitHub Actions CI/CD

---

## Project Context

GraphMem is a semantic graph-based memory API for LLM agents. When an AI agent has a long conversation, passing the full history to the LLM every turn is expensive and noisy. GraphMem stores the conversation as a semantic graph and retrieves only what's relevant at query time.

**Core flow:**
1. `add_prompt` — logs user message as a pending memory node
2. `add_response` — completes the node, triggers async Lambda pipeline via SQS
3. Lambda (`node_worker`) — embeds the node (Jina AI), writes vector to pgvector, creates Neptune vertex + edges to similar past nodes
4. Lambda (`topic_worker`) — every 20 nodes, runs Louvain community detection on Neptune graph, labels clusters via Groq LLM
5. `recall(query)` — pgvector finds top-k seeds, Neptune expands 1-hop, token budget applied, returns relevant nodes

---

## Issues Found (Post-Build)

---

### Issue 1 — Duplicate Neptune Edges

**Symptom:**  
Conv2 stats show `edge_count: 1319` but maximum possible edges in a 50-node undirected graph is `50×49÷2 = 1225`. Graph density = `1.0767` (mathematically impossible, max is 1.0). `complete_count: 52 > node_count: 50`.

**Root cause:**  
`node_worker` Lambda was invoked multiple times for the same node due to SQS retries during seeding. The `add_edge_pair()` function blindly calls Neptune's `addE()` every time — Neptune has no uniqueness constraint on edges by default, so each retry creates a new duplicate edge between the same vertex pair.

**Why it matters:**  
Duplicate edges inflate `avg_degree` (was 52.76, max possible is 49), distort Louvain community detection weights, and make graph density metrics meaningless for debugging.

**Fix:**  
Neptune upsert using Gremlin `coalesce` — find existing edge or create new one, never duplicate:

```python
def add_edge_pair(src_id, dst_id, weight, conversation_id):
    w = round(weight, 6)
    neptune(
        f"g.V().has('memory_node','memory_id','{src_id}').as('a')"
        f".V().has('memory_node','memory_id','{dst_id}')"
        f".coalesce("
        f"  __.inE('similar_to').where(outV().as('a')),"
        f"  addE('similar_to').from('a')"
        f").property('weight',{w}).property('conversation_id','{conversation_id}')"
    )
    # repeat for reverse direction
```

**Interview angle:**  
> "Neptune doesn't enforce edge uniqueness the way relational DBs enforce UNIQUE constraints. Lambda's at-least-once delivery guarantee means you have to design your graph writes to be idempotent. The coalesce pattern is the Gremlin equivalent of an upsert."

---

### Issue 2 — Similarity Threshold Too Low → Dense Graph

**Symptom:**  
With `DEFAULT_THRESHOLD = 0.4`, a 50-node technical conversation (SaaS/FastAPI topics) produces 1,319 edges — essentially a complete graph where every node connects to every other node.

**Root cause:**  
Cosine similarity of 0.4 is too permissive for technical conversations. All messages share vocabulary (FastAPI, Python, API, auth, etc.), pushing cosine similarity between *unrelated* pairs above 0.4. A Stripe payment question and a JWT expiry question are thematically unrelated but share enough tokens to score 0.50+ in embedding space.

**Why it matters:**  
A near-complete graph makes the graph expansion in `recall()` meaningless — expanding 1-hop from 5 seeds in a complete graph returns all 50 nodes. The token budget then makes arbitrary cuts rather than relevance-based ones.

**Fix (part of the PPR architecture change):**  
Raise insert threshold to 0.6 and cap at 15 neighbors per node:

```python
cur.execute(
    """SELECT memory_id::text, 1 - (embedding <=> %s) AS sim
       FROM memory_nodes
       WHERE conversation_id = %s::uuid
         AND status = 'complete'
         AND memory_id != %s::uuid
       ORDER BY embedding <=> %s
       LIMIT 15""",
    (embedding, conversation_id, memory_id, embedding),
)
neighbours = [n for n in neighbours if float(n["sim"]) >= 0.6]
```

**Interview angle:**  
> "A threshold-based edge strategy doesn't scale. Raising the threshold just shifts the problem — in a deeply technical monologue, even 0.65 creates a dense graph. The root fix is capping edges per node so the graph stays sparse regardless of conversation content."

---

### Issue 3 — 1-Hop Expansion Doesn't Scale (Architectural)

**Symptom:**  
- Small conversation (8 nodes): 1-hop from 5 seeds returns all 8 nodes, including irrelevant ones
- Large conversation (100 nodes): 1-hop returns only immediate neighbors of seeds, potentially missing 15+ relevant nodes that are 2 hops away

**Root cause:**  
Fixed 1-hop expansion is query-agnostic. It doesn't know which neighbors are relevant to the current query — it includes all of them blindly. For small graphs it over-retrieves; for large sparse graphs it under-retrieves.

**Fix — Personalized PageRank (PPR) at query time:**  
Inspired by [HippoRAG (NeurIPS 2024)](https://github.com/osu-nlp-group/hipporag) and the [AWS Neptune + PPR blog](https://aws.amazon.com/blogs/machine-learning/hipporag-neurobiologically-inspired-rag-using-amazon-bedrock-amazon-neptune-and-personalized-pagerank/).

Instead of fixed 1-hop expansion, pull the full conversation graph from Neptune once, run PPR seeded on the pgvector results, and score every node by its PPR score × cosine similarity to the query:

```python
import networkx as nx
import numpy as np

def ppr_recall(seed_ids, query_embedding, conv_edges, all_nodes, alpha=0.85, ppr_threshold=0.005):
    G = nx.DiGraph()
    for e in conv_edges:
        G.add_edge(e["src"], e["dst"], weight=e["weight"])

    personalization = {n: 0.0 for n in G.nodes}
    for sid in seed_ids:
        if sid in personalization:
            personalization[sid] = 1.0 / len(seed_ids)

    ppr_scores = nx.pagerank(G, alpha=alpha, personalization=personalization, weight="weight")

    results = []
    for node_id, ppr in ppr_scores.items():
        if ppr < ppr_threshold:
            continue
        node = all_nodes.get(node_id)
        if not node:
            continue
        cos_sim = float(np.dot(query_embedding, node["embedding"]))
        combined_score = ppr * cos_sim
        results.append({**node, "relevance_score": round(combined_score, 4)})

    return sorted(results, key=lambda x: x["relevance_score"], reverse=True)
```

**Why PPR works for both cases:**
- Small conv: unrelated nodes get near-zero PPR score → filtered out by threshold
- Large conv: PPR propagates through multi-hop paths → reaches all relevant nodes, not just 1-hop neighbors
- Score = PPR × cosine similarity → both graph structure and semantic relevance matter

**Interview angle:**  
> "PPR is the same algorithm Google's original PageRank was based on, adapted for personalized ranking from seed nodes. In a memory graph, the seeds are the pgvector hits for the current query. PPR propagates 'relevance mass' from those seeds through the graph — nodes strongly connected to semantically relevant nodes score high even if they don't directly match the query embedding. That's exactly what you want for episodic memory: related context surfaces even when the user doesn't phrase it the same way."

#### How PPR Actually Works at Recall Time — Step by Step

**Setup:** After the fixed graph is built (threshold 0.6, cap 15), the graph has real topic clusters — auth nodes connect to auth nodes, payments to payments, frontend to frontend. Cross-cluster edges are absent or very weak.

```
Auth cluster:          Payments cluster:      Frontend cluster:
A -- B -- C            P -- Q -- R            F -- G -- H
|    |                 |                      |
D -- E                 S -- T                 I
```

**Query: "How should I handle JWT token expiry?"**

**Step 1 — pgvector seeds (unchanged):**
```sql
SELECT memory_id, 1 - (embedding <=> query_vec) AS sim
FROM memory_nodes ORDER BY embedding <=> query_vec LIMIT 5
```
Returns nodes A (0.76), B (0.72), D (0.69), C (0.64), E (0.61) — all auth cluster.

**Step 2 — Pull full conv graph from Neptune (one query):**
```python
raw = neptune(
    f"g.V().has('memory_node','conversation_id','{conv_id}')"
    ".outE('similar_to')"
    ".project('src','dst','weight')"
    ".by(outV().values('memory_id'))"
    ".by(inV().values('memory_id'))"
    ".by('weight')"
)
```

**Step 3 — Build graph + personalization vector:**
```python
G = nx.DiGraph()
for e in raw:
    G.add_edge(e["src"], e["dst"], weight=e["weight"])

personalization = {n: 0.0 for n in G.nodes}
for sid in seed_ids:
    personalization[sid] = 1.0 / len(seed_ids)  # 0.2 each for k=5
```

**Step 4 — Run PPR:**
```python
ppr_scores = nx.pagerank(G, alpha=0.85, personalization=personalization, weight="weight")
```

What the random walker does internally:
```
At every step:
  - With probability 0.85 → walk to a random neighbor (weighted by edge weight)
  - With probability 0.15 → teleport back to one of the 5 seeds
Repeat ~50 iterations until scores stabilize.
Final score per node = probability the walker is at that node.
```

**What the scores look like:**
```
Auth cluster (seeds):
  A: 0.089   B: 0.091   C: 0.072   D: 0.068   E: 0.061

Auth cluster (non-seeds, reachable from seeds):
  "Token rotation":      0.041  ← 2 hops from A via B — still reached
  "RBAC node":           0.028  ← 2 hops, weaker connection
  "Account disabled":    0.019  ← edge exists but weak

Payments cluster (no path to auth seeds):
  P: 0.003   Q: 0.002   R: 0.001  ← walker always teleports back before reaching

Frontend cluster:
  F: 0.004   G: 0.002
```

**Step 5 — Filter + final score:**
```python
for node_id, ppr in ppr_scores.items():
    if ppr < 0.005:          # cuts payments/frontend entirely
        continue
    cos_sim = np.dot(query_embedding, node["embedding"])
    combined = ppr * cos_sim  # structural relevance × semantic match
    results.append({...node, "relevance_score": combined})

results.sort(key=lambda x: x["relevance_score"], reverse=True)
```

**Why the teleportation term is the key insight:**  
The `(1 - alpha) = 0.15` snaps the walker back to seeds every 7 steps on average. So a node's score is always being pulled toward "how often does the walker reach me starting from the query seeds." Payments nodes have no edges to auth seeds — the walker teleports away before it gets there — near-zero score. Auth-adjacent nodes accumulate score because the walker keeps returning to seeds and walking back through them.

**Comparison vs 1-hop:**

| | 1-hop | PPR |
|---|---|---|
| "Token rotation" (2 hops) | **missed** | caught (ppr=0.041) |
| "Stripe webhooks" (no path) | included if graph dense | filtered (ppr=0.002) |
| Small conv (8 nodes, 3 relevant) | returns all 8 | returns only 3 |
| Large conv (200 nodes, 20 relevant) | returns ~50 | returns ~20 |
| Adapts to different queries | no | yes — seeds change, PPR recomputes |

---

### Issue 4 — Recall Results Sorted Chronologically, Not by Relevance

**Symptom:**  
In the recall API response, nodes are returned sorted by `index` (conversation order). The most semantically relevant node for "How should I handle JWT token expiry?" scored **0.7614** but appeared 6th in the list because it was the 8th message in the conversation. A Stripe payment node with score 0.5049 appeared higher.

**Root cause:**  
The recall endpoint applies the token budget and returns nodes in `ORDER BY index ASC` — preserving conversational order — without re-sorting by relevance first.

**Fix:**  
Sort candidates by `relevance_score` descending before applying the token budget. The token budget then naturally cuts the least relevant nodes, not the most recent ones:

```python
candidates = sorted(candidates, key=lambda x: x["relevance_score"], reverse=True)
# then apply token budget greedily from top
```

**Interview angle:**  
> "This is a classic retrieval vs. presentation ordering conflict. For the LLM consumer of the recall results, chronological order is fine — it preserves narrative context. But the *selection* of which nodes to include should be by relevance. We sort by relevance to select, then re-sort by index before returning so the LLM sees a coherent timeline."

---

### Issue 5 — Empty Responses on Some Nodes

**Symptom:**  
Nodes at conversation index 6 ("What's the format of the Cognito JWKS endpoint?") and index 10 ("How do I handle a user whose account gets disabled mid-session?") have `response: ""`. These nodes carry no content weight in recall.

**Root cause:**  
During seeding with `seed_demo.py`, Groq occasionally returned an empty string (likely a truncated or malformed response) and the seed script called `add_response` with that empty string. The node is marked `complete` but has no response content.

**Fix:**  
Validate in `add_response` endpoint that content is non-empty before marking complete. Also add a check in `seed_demo.py` to skip `add_response` if Groq returns empty:

```python
if not response.strip():
    print(f"  [{i}] Groq returned empty — skipping add_response")
    continue
```

---

### Issue 6 — All Topics Show "Unlabeled cluster"

**Symptom:**  
Both demo conversations have 3 Louvain clusters each, but all 6 topic records have `label: "Unlabeled cluster"`, `description: ""`, `summary: ""`, `coherence: 0.5`. The topic intelligence feature is completely non-functional for both demo convos.

**Root cause:**  
The `topic_worker` triggers every 20 nodes via SQS. During seeding, nodes were added at ~3s intervals, so topic recompute fired at node 20 and node 40 for each conversation. At those moments, Groq's 30 RPM rate limit was already saturated from the seed script's own Groq calls (generating responses). All 5 retry attempts in `_label_cluster()` hit 429 and fell through to the hardcoded fallback:

```python
return {
    "label": "Unlabeled cluster",
    "description": "", "summary": "",
    "coherence": 0.5, ...
}
```

Once written to the DB, nothing ever retriggers the labeling.

**Fix — three-part:**

**Part A:** Add `DelaySeconds=60` to the topic SQS message so Groq rate limits settle before labeling fires:
```python
_sqs.send_message(
    QueueUrl=SQS_TOPIC_QUEUE_URL,
    MessageBody=json.dumps({"conversation_id": conversation_id}),
    DelaySeconds=60,
)
```

**Part B:** Use Groq's rate limit response headers for smarter backoff:
```python
if resp.status_code == 429:
    retry_after = int(resp.headers.get("retry-after", 2 ** attempt))
    time.sleep(retry_after)
```

**Part C:** Self-healing lazy recompute — detect "Unlabeled cluster" on read and fire a background recompute:
```python
# In GET /topics endpoint
if any(t["label"] == "Unlabeled cluster" for t in topics):
    sqs.send_message(
        QueueUrl=SQS_TOPIC_QUEUE_URL,
        MessageBody=json.dumps({"conversation_id": conversation_id}),
        DelaySeconds=10,
    )
```

**Interview angle:**  
> "This is an at-most-once vs at-least-once design problem. The topic recompute was fire-and-forget — if it failed, there was no recovery path. The self-healing read pattern turns it into an eventually-consistent system: the first read after a failure triggers a background recompute, and the next read returns correct data. This is the same pattern DynamoDB Streams + Lambda uses for eventual consistency."

---

### Issue 7 — No Self-Healing on Failed Topic Labels

*(Covered in Issue 6 Part C above — listed separately for clarity)*

Once a topic is written as "Unlabeled cluster", no automatic mechanism retriggers labeling. A real user whose topic recompute failed would see empty topic labels forever unless they manually called the `recompute` endpoint.

---

### Issue 8 — `gremlinpython` / `aiohttp` Fails Silently in Lambda

**Symptom (found during build, fixed pre-submission):**  
Node and topic workers deployed to Lambda with `gremlinpython` in `requirements.txt`. Lambda invocations succeeded (exit 0) but no Neptune vertices or edges were created. CloudWatch showed the `aiohttp` async loop failing silently in the Lambda execution environment.

**Root cause:**  
`gremlinpython` uses WebSocket transport via `aiohttp`. Lambda's execution environment has a non-standard event loop setup that conflicts with `aiohttp`'s async context management. The connection attempt fails silently — no exception raised, no data written.

**Fix:**  
Replaced `gremlinpython` entirely with direct HTTP calls to Neptune's Gremlin HTTP endpoint (`POST /gremlin`):

```python
import httpx

NEPTUNE_URL = f"https://{os.environ['NEPTUNE_ENDPOINT']}:{os.environ['NEPTUNE_PORT']}/gremlin"

def neptune(query: str) -> list:
    resp = httpx.post(NEPTUNE_URL, json={"gremlin": query}, timeout=30.0)
    resp.raise_for_status()
    data = resp.json().get("result", {}).get("data", {})
    return data.get("@value", []) if isinstance(data, dict) else []
```

Also removed `gremlinpython` and `aiohttp` from `requirements.txt`, replaced with `httpx`.

**Interview angle:**  
> "Neptune supports both WebSocket (Gremlin server protocol) and HTTP REST endpoints. The WebSocket client (`gremlinpython`) requires a persistent async event loop which Lambda's execution model doesn't guarantee between invocations. The HTTP endpoint is stateless and works identically in Lambda, ECS, or a local script — no async plumbing required."

---

### Issue 9 — Neptune Binding Variables Return 400

**Symptom (found during build, fixed pre-submission):**  
Neptune returned HTTP 400 when queries used Gremlin binding variables:
```python
neptune("g.addV('memory_node').property('memory_id', mid)", bindings={"mid": memory_id})
```

**Root cause:**  
Neptune's HTTP Gremlin endpoint has limited support for binding variables in certain Gremlin traversal patterns. The `{"gremlin": query, "bindings": {...}}` format is accepted syntactically but raises a 400 for some property operations.

**Fix:**  
Embed values directly in f-string queries. UUIDs are safe to embed directly (no SQL injection risk in Gremlin — no user input reaches these queries):
```python
neptune(
    f"g.addV('memory_node')"
    f".property('memory_id', '{memory_id}')"
    f".property('conversation_id', '{conversation_id}')"
)
```

---

### Issue 10 — Token Savings Bar Visible on Cold Start

**Symptom:**  
When a conversation has fewer nodes than `cold_start_min_nodes`, `recall()` returns `strategy_used: "cold_start"` (returns all nodes, no filtering). The playground still renders the token reduction bar comparing full history vs GraphMem recall — but on cold start, GraphMem IS the full history, so the comparison is meaningless.

**Fix:**  
Hide the token context comparison section when `strategy_used === "cold_start"`:
```javascript
if (d.strategy_used === 'cold_start') {
    document.getElementById('tokenSavingsSection').style.display = 'none';
} else {
    document.getElementById('tokenSavingsSection').style.display = 'block';
}
```

---

## Architecture Evolution

### Why the retrieval strategy changed three times:

**V1 — Threshold-based edges (0.4) + 1-hop expansion**
- Simple: connect everything above similarity threshold, expand 1 hop at recall
- Problem: threshold doesn't adapt to conversation density. Technical conversations → complete graphs → noisy recall

**V2 — Top-K edges (cap 15) + 1-hop expansion**
- Better: sparse graph regardless of conversation length
- Problem: still query-agnostic. Small convs still return all neighbors. Large convs miss nodes 2+ hops away.

**V3 — Threshold (0.6) + cap 15 at insert + PPR at recall**
- Insert: moderate threshold + cap keeps graph sparse and meaningful
- Recall: PPR propagates relevance from query seeds through graph structure
- Scales to any conversation size: sparse graphs get tight PPR focus, large graphs get multi-hop reach
- Score = PPR × cosine similarity balances structural relevance with semantic match
- Inspired by HippoRAG (NeurIPS 2024) which uses same PPR approach on knowledge graphs

---

## Threshold Distinction — Easy to Confuse

Two separate `threshold` values exist in the codebase and they control completely different operations:

**`0.6` — build-time, `node_worker`:**  
When a new node is embedded, it queries pgvector for the top-15 most similar *existing nodes*, then only creates Neptune edges for pairs with cosine ≥ 0.6. Controls graph sparsity at insert time. Lives in `THRESHOLD = float(os.environ.get("DEFAULT_THRESHOLD", "0.6"))` in `node_worker/handler.py`. Never exposed to API users.

**`0.6` — recall-time, Set A' (`config.py → default_threshold`):**  
During `recall()`, Set A' scans all nodes in the conversation and includes any whose embedding is within `threshold` cosine distance of the *current query embedding*. This is what the `threshold` parameter in the Python SDK / HTTP API controls — it has nothing to do with graph edges. Lives in `settings.default_threshold = 0.6` in `config.py`.

**Why both are now 0.6:**  
Originally the recall threshold was 0.4 (looser, to account for query-vs-passage embedding distance being naturally smaller than passage-vs-passage). But since Set B already guarantees the top-K direct semantic hits, and Set C (PPR) handles graph-connected context, Set A' at 0.4 was pulling in semi-relevant noise. Aligning both to 0.6 creates a consistent semantic bar throughout the system: "0.6 is meaningful similarity, everything below is noise."

**Interview angle:**  
> "These look like the same config value but they measure different similarity pairs. The build-time threshold asks 'are these two stored memories similar enough to link?' The recall threshold asks 'is this stored memory similar enough to the live query to surface directly?' We aligned them both to 0.6 after finding that 0.4 for recall added noise on top of what PPR was already catching structurally."

---

## Fix Summary Table

| # | Component | Issue | Fix |
|---|---|---|---|
| 1 | node_worker (Neptune) | Duplicate edges on Lambda retry | `coalesce` upsert pattern |
| 2 | node_worker (pgvector) | Threshold 0.4 too low → dense graph | Raise to 0.6, cap 15 neighbors |
| 3 | API recall endpoint | 1-hop expansion doesn't scale | Replace with Personalized PageRank |
| 4 | API recall endpoint | Results sorted by index not relevance | Sort by `relevance_score` desc before token budget |
| 5 | seed_demo.py | Empty Groq responses stored as complete | Validate non-empty before `add_response` |
| 6 | node_worker (SQS) | Topic recompute fires during Groq rate limit | `DelaySeconds=60` on topic queue message |
| 7 | API /topics | "Unlabeled cluster" never self-heals | Lazy recompute on read if label is fallback |
| 8 | node_worker (Lambda) | `gremlinpython` + `aiohttp` silent failure | Replace with `httpx` HTTP calls to Neptune |
| 9 | node_worker (Neptune) | Binding variables return HTTP 400 | Embed values directly in f-string queries |
| 10 | Playground (JS) | Token savings bar shows on cold_start | Hide section when `strategy_used === "cold_start"` |

---

## Key Interview Questions This Prepares You For

- *"What was the hardest bug you hit?"* → Issue 8 (gremlinpython silent failure in Lambda)
- *"How did you handle rate limiting?"* → Issues 6/7 (Groq 429 → unlabeled topics → self-healing)
- *"How does your graph retrieval scale?"* → Issue 3 (PPR architecture evolution)
- *"What would you do differently?"* → Issue 2 (threshold design) + Issue 1 (idempotent writes from day 1)
- *"How did you ensure data integrity with async Lambda?"* → Issues 1, 8, 9 (at-least-once delivery challenges)
- *"Why Neptune over a regular adjacency table in Postgres?"* → Graph traversal, PPR, community detection native to graph DB; adjacency in Postgres requires recursive CTEs that don't scale past ~5 hops
