# GraphMem — Configurable Variables Reference

All tunable parameters across the system. Defaults are starting points, not validated values.
Tune these after the demo using real conversation data.

Each variable lists: current default, what it controls, why that value was picked,
and the effect of going higher or lower.

---

## Layer 1 — Recall (Graph Retrieval)

---

### `default_k`
**Default:** `5`
**Lives in:** `api/config.py` → `Settings.default_k` | per-call override: `recall(k=...)`
**Controls:** Size of Set B — the strict top-K nodes by cosine similarity that seed the recall pipeline.

**Why 5:** Standard starting point for RAG-style retrieval. Keeps Set C expansion bounded.

**Higher →** More seed nodes, richer Set C expansion, more context retrieved, higher token usage.
**Lower →** Tighter focus, fewer total nodes, faster Neptune traversal, lower token usage. Risk: missing relevant nodes if conversation is large.

**Tune when:** You see recall() consistently missing obviously relevant messages → increase. Token budget regularly exceeded → decrease.

---

### `default_threshold`
**Default:** `0.4`
**Lives in:** `api/config.py` → `Settings.default_threshold` | per-call override: `recall(threshold=...)`
**Controls:** Three things simultaneously — (1) minimum cosine similarity for a graph edge to be created in the node_worker Lambda, (2) minimum cosine similarity for Set A' (threshold scan), (3) minimum edge weight for Set C 1-hop expansion from Neptune.

**Why 0.4:** Chosen to keep the graph sparse (notes page 1: "only store edges above ~0.4"). Below this, nodes are weakly related and edges add noise without value.

**Higher →** Sparser graph, fewer edges, smaller Set A' and Set C, tighter recall. Risks missing weakly related but contextually important messages.
**Lower →** Denser graph, more edges, larger recall sets, higher token usage. At 0.0 the graph degenerates to a fully-connected mesh.

**Tune when:** Graph is too sparse (few edges even for clearly related messages) → lower slightly. Recall is returning loosely-related noise → raise.

---

### `default_max_tokens`
**Default:** `2000`
**Lives in:** `api/config.py` → `Settings.default_max_tokens` | per-call override: `recall(max_tokens=...)`
**Controls:** Token budget for the recall result. Nodes are greedily added by cosine score until this limit is reached.

**Why 2000:** Fits comfortably inside a 4K context window alongside a system prompt and the current user message. Leaves ~2K tokens for the LLM to generate.

**Higher →** More context injected, richer responses, higher LLM inference cost.
**Lower →** Fewer tokens, cheaper inference, but risk of dropping relevant context.

**Tune when:** Developer changes their LLM (e.g., 128K context Llama) → can safely increase significantly. Cost-sensitive use case → decrease.

---

### `cold_start_min_nodes`
**Default:** `5`
**Lives in:** `api/config.py` → `Settings.cold_start_min_nodes`
**Controls:** Minimum number of complete nodes in a conversation before the real recall pipeline runs. Below this, falls back to returning all nodes chronologically.

**Why 5:** The graph is too sparse with fewer than 5 nodes to produce meaningful edge structure. At 5 nodes there can be at most 4 edges per node.

**Higher →** Longer cold-start period, more chronological dumping before graph kicks in.
**Lower →** Graph mode engages sooner, even on sparse graphs. At 1 or 2, the graph adds no real value.

**Tune when:** Conversations are typically short (< 10 messages) → lower to 3. Long conversations where cold start quality is poor → raise.

---

### `default_recency_half_life`
**Default:** `3600.0` (seconds = 1 hour)
**Lives in:** `api/config.py` → `Settings.default_recency_half_life` | per-call override: `recall(recency_half_life=...)`
**Controls:** How fast a node's recency score decays. At `t = half_life`, recency score = 0.5. At `t = 2 × half_life`, recency score = 0.25. Used only in `strategy="semantic_recency"`.

**Why 3600s:** For hour-scale conversations, a message from 2 hours ago is noticeably "older" but may still be very relevant. 1 hour felt like a natural half-life.

**Higher →** Recency decays slower — older messages stay competitive with recent ones. Good for slow-moving conversations or research sessions.
**Lower →** Recency decays faster — recent messages dominate. Good for real-time chat where older context truly is stale.

**Tune when:** `semantic_recency` strategy feels too biased toward old messages → decrease. Feels too biased toward recent ones even when older context is relevant → increase.

---

### `recency_alpha` (per-call default)
**Default:** `0.7` (hardcoded as route default in `RecallRequest`)
**Lives in:** `api/routes/memory.py` → `RecallRequest.recency_alpha` | per-call override: `recall(recency_alpha=...)`
**Controls:** Blend weight between cosine similarity and recency decay in `strategy="semantic_recency"`. Score = `alpha × cosine + (1-alpha) × recency`. 0.7 = 70% semantic, 30% recency.

**Why 0.7:** Semantic relevance should dominate. Recency is a tiebreaker, not the primary signal.

**Higher (→ 1.0) →** Pure semantic, recency has no effect (same as `strategy="semantic"`).
**Lower (→ 0.0) →** Pure recency — most recent nodes always win regardless of relevance. Almost never useful.

**Tune when:** Use case is a real-time assistant where recency matters a lot (e.g., customer support) → try 0.5. Use case is a research assistant where old messages are equally relevant → stick at 0.7 or higher.

---

### `always_include_recent` (per-call, default 0)
**Default:** `0`
**Lives in:** `api/routes/memory.py` → `RecallRequest.always_include_recent` | per-call override
**Controls:** Set R — last M complete nodes always included in context, exempt from token budgeting. At 0, Set R is empty and all nodes compete on cosine score.

**Why 0:** Off by default. Many use cases don't need forced recency. Developer opts in explicitly.

**Higher →** More recent messages forced in, fewer budget tokens for semantic candidates.
**Tune when:** Application needs to always include the last few turns for coherence (e.g., chatbot) → set to 2-3.

---

## Layer 1 — Neighbourhood

---

### `neighbourhood_default_threshold`
**Default:** `0.7`
**Lives in:** `api/routes/memory.py` → `GET /memory/{id}/neighbours?threshold=` | per-call query param
**Controls:** Minimum edge weight to include a neighbour in `neighbourhood()` results. Intentionally higher than `default_threshold` (0.4) — neighbourhood is a high-quality local view, not the full sparse graph.

**Why 0.7:** You want tight semantic neighbours here, not all weakly connected nodes. The graph may have edges at 0.41 that are structurally present but semantically weak.

**Higher →** Fewer, tighter neighbours. Useful for focused exploration.
**Lower →** More neighbours, including weak connections. Use `default_threshold` (0.4) as absolute floor.

---

## Layer 2 — Topic Pipeline

---

### `topic_recompute_interval`
**Default:** `20`
**Lives in:** `api/config.py` → `Settings.topic_recompute_interval` | Lambda env: `TOPIC_RECOMPUTE_INTERVAL`
**Controls:** (1) How often (every N complete nodes) the node_worker Lambda triggers a topic recompute via SQS. (2) The recency window for the temporal `active` status override — topics whose most recent node has `index > (next_index - topic_recompute_interval)` are forced `active`.

**Why 20:** Balances topic freshness with Groq API cost. Every 20 nodes = ~1-3 Groq calls per recompute depending on cluster count. At 1000 RPD free tier, this supports ~300-1000 recomputes/day.

**Higher →** Fewer recomputes, lower API cost, but topics go stale for longer between updates.
**Lower →** More frequent updates, fresher topics, higher Groq API cost. At 1 it recomputes on every message — never do this on free tier.

**Tune when:** Demo conversation has only 50 messages → set to 10 to see topic evolution. Production with many users → raise to 50+ to protect Groq quota.

---

### `louvain_default_resolution`
**Default:** `1.0`
**Lives in:** `api/config.py` → `Settings.louvain_default_resolution` | Lambda env: `LOUVAIN_DEFAULT_RESOLUTION`
**Controls:** Louvain community detection resolution parameter. Controls granularity of clustering.

**Why 1.0:** Standard default for the `python-louvain` library. Well-tested starting point.

**Higher (> 1.0) →** More, smaller clusters — finer-grained topics. Useful for long diverse conversations.
**Lower (< 1.0) →** Fewer, larger clusters — coarser topics. May group unrelated messages together.

**Tune when:** Topics are too broad ("everything about databases") → increase. Topics are too fine ("PostgreSQL index type question 3") → decrease.

---

### `topic_min_cluster_size`
**Default:** `2`
**Lives in:** `api/config.py` → `Settings.topic_min_cluster_size` | Lambda env: `TOPIC_MIN_CLUSTER_SIZE`
**Controls:** Minimum number of nodes for a Louvain cluster to become a topic. Singleton clusters (1 node) are always skipped. Clusters below this threshold are silently dropped.

**Why 2:** A single-message "topic" has no semantic meaning. Two messages at minimum gives the LLM something to reason about.

**Higher →** Fewer topics, small clusters discarded. Useful if you only want well-populated topics.
**Lower →** Can't go below 2 usefully. Setting to 1 would create single-node topics — bad.

---

### `topic_label_representative_count`
**Default:** `5`
**Lives in:** `api/config.py` → `Settings.topic_label_representative_count` | Lambda env: `TOPIC_LABEL_REPRESENTATIVE_COUNT`
**Controls:** How many nodes (selected by graph degree centrality) are shown to the Groq LLM in the "representative messages" section of the labeling prompt.

**Why 5:** Enough to give the LLM a semantic picture of the topic without excessive token usage. Central nodes by degree are the most semantically connected — good representatives.

**Higher →** Better topic understanding for large clusters, more accurate labels/summaries, higher Groq token cost per call.
**Lower →** Cheaper labeling, but LLM may miss important context especially for large or diverse clusters.

**Tune when:** Topics have 30+ messages and labels feel generic → increase to 10-15. Groq rate limit is a concern → decrease.

---

### `topic_label_recent_count`
**Default:** `3`
**Lives in:** `api/config.py` → `Settings.topic_label_recent_count` | Lambda env: `TOPIC_LABEL_RECENT_COUNT`
**Controls:** How many of the most chronologically recent nodes in a cluster are shown to the Groq LLM (in addition to the central nodes above) specifically to help detect `resolved` vs `dormant` status.

**Why 3:** The last 2-3 messages usually contain the resolution signal ("ok we decided X", "let's move on"). More than 3 rarely adds new information for status detection.

**Higher →** Better resolved/dormant accuracy, especially for long topics. More tokens per Groq call.
**Lower →** Cheaper but risks misclassifying resolved topics as dormant.

**Tune when:** Status detection is frequently wrong (topics marked dormant that were actually resolved) → increase to 5.

---

### `recurrence_limit`
**Default:** `2`
**Lives in:** `workers/topic_worker/handler.py` → `RECURRENCE_LIMIT = 2` (hardcoded constant)
**Controls:** Maximum number of local Louvain reruns allowed for a mixed cluster. A cluster flagged `is_mixed=True` triggers a local Louvain rerun on its subgraph. If the sub-clusters are still mixed, one more rerun is allowed. After 2 reruns, the result is accepted as-is.

**Why 2:** Prevents infinite recursion. In practice, 2 reruns are almost always enough to resolve mixed clusters. Notes page 17 specify this exact value.

**Higher →** More splitting attempts, finer final clusters, more Groq calls per recompute.
**Lower (1) →** One rerun pass, may leave some mixed clusters unfixed.

**To change:** Edit `RECURRENCE_LIMIT` constant in `workers/topic_worker/handler.py` directly (or move to env var if needed).

---

## Summary Table

| Variable | Default | Layer | Location |
|---|---|---|---|
| `default_k` | 5 | Recall | config.py + per-call |
| `default_threshold` | 0.4 | Recall + Graph | config.py + per-call |
| `default_max_tokens` | 2000 | Recall | config.py + per-call |
| `cold_start_min_nodes` | 5 | Recall | config.py |
| `default_recency_half_life` | 3600s | Recall | config.py + per-call |
| `recency_alpha` | 0.7 | Recall | per-call default |
| `always_include_recent` | 0 | Recall | per-call |
| `neighbourhood_default_threshold` | 0.7 | Graph | per-call query param |
| `topic_recompute_interval` | 20 | Topics | config.py + Lambda env |
| `louvain_default_resolution` | 1.0 | Topics | config.py + Lambda env |
| `topic_min_cluster_size` | 2 | Topics | config.py + Lambda env |
| `topic_label_representative_count` | 5 | Topics | config.py + Lambda env |
| `topic_label_recent_count` | 3 | Topics | config.py + Lambda env |
| `recurrence_limit` | 2 | Topics | hardcoded in Lambda |
