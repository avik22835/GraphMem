# GraphMem — AWS Deployment Documentation

> Built for the **First Commit × AWS Hackathon (Bharat Builds Tour — Ship It track)**
> This document covers every architectural decision, every blocker hit, every workaround applied,
> and every AWS service used. It is intended to serve as both an internal reference and the
> source of truth for hackathon submission form answers.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Full Architecture Diagram](#2-full-architecture-diagram)
3. [Data Layer — PostgreSQL + pgvector (RDS)](#3-data-layer--postgresql--pgvector-rds)
4. [Graph Layer — Neptune Serverless](#4-graph-layer--neptune-serverless)
5. [Async Processing Pipeline — SQS + Lambda](#5-async-processing-pipeline--sqs--lambda)
6. [API Layer — FastAPI on ECS Fargate](#6-api-layer--fastapi-on-ecs-fargate)
7. [Auth Layer — Cognito + API Keys](#7-auth-layer--cognito--api-keys)
8. [CI/CD — GitHub Actions → ECR](#8-cicd--github-actions--ecr)
9. [VPC + Networking Architecture](#9-vpc--networking-architecture)
10. [IAM Roles](#10-iam-roles)
11. [Deployment Journey — Every Blocker and Workaround](#11-deployment-journey--every-blocker-and-workaround)
12. [Why Each AWS Service Was Chosen](#12-why-each-aws-service-was-chosen)
13. [What Worked Well / What Could Be Better](#13-what-worked-well--what-could-be-better)
14. [DB Schema + Graph Logic Integration](#14-db-schema--graph-logic-integration)
15. [Hackathon Submission Form Answers](#15-hackathon-submission-form-answers)

---

## 1. Executive Summary

**GraphMem** is a drop-in memory and context management API service for developers building LLM/AI agents. The core problem it solves: LLM agents that naively dump full conversation history into context waste tokens on irrelevant messages and hit context limits quickly. GraphMem instead models conversation history as a **semantic graph** — messages are nodes, edges are cosine similarity between embeddings — and retrieves only the most relevant messages at inference time via a multi-set retrieval algorithm called `recall()`.

### What makes it different from a vector database

A plain vector DB returns top-K similar messages. GraphMem's `recall()` returns four sets unioned together:
- **Set B**: strict top-K by cosine similarity (pgvector HNSW)
- **Set A'**: any node not in B whose similarity ≥ threshold (catches relevant but not top-K nodes)
- **Set C**: 1-hop Neptune graph neighbors of B (catches contextually adjacent messages even if not directly similar to the query)
- **Set R**: the last M messages (recency guarantee — always included, exempt from token budget cuts)

The graph expansion (Set C) is the key differentiator. It surfaces messages that are semantically related to what was already retrieved, not just to the query. This catches implicit context — a setup message that led to a later conclusion, for example — which a pure vector search would miss.

### Why AWS for this architecture

The system has three fundamentally different compute and storage profiles that map naturally to different AWS services:
- **Structured relational data + vector search** → RDS PostgreSQL + pgvector
- **Graph traversal** → Neptune Serverless (Gremlin)
- **Async background processing** (embedding, graph-building, topic clustering) → SQS + Lambda
- **Synchronous API layer** → ECS Fargate + FastAPI
- **Auth** → Cognito (JWT) + custom API keys (bcrypt, stored in RDS)

All services run in the same AWS account (us-east-1), same VPC, communicating over private IPs.

---

## 2. Full Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              DEVELOPER'S APPLICATION                                │
│                                                                                     │
│   from graphmem import GraphMem                                                     │
│   gm = GraphMem(api_key="gm_sk_...", base_url="http://graphmem-alb-...elb.amazonaws.com")│
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │ HTTP (port 80)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         AWS — us-east-1 — Default VPC                               │
│                                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                    PUBLIC SUBNETS (us-east-1a, us-east-1b)                   │   │
│  │                                                                              │   │
│  │  ┌──────────────────────────────────────────────────────────────────────┐    │   │
│  │  │   ALB (graphmem-alb)  [graphmem-alb-sg: inbound 80/0.0.0.0/0]       │    │   │
│  │  │   DNS: graphmem-alb-1377576243.us-east-1.elb.amazonaws.com          │    │   │
│  │  │   Listener: HTTP:80 → Target Group: graphmem-tg (port 8000)         │    │   │
│  │  └───────────────────────────────┬──────────────────────────────────────┘    │   │
│  │                                  │ port 8000                                 │   │
│  │  ┌───────────────────────────────▼──────────────────────────────────────┐    │   │
│  │  │  ECS Fargate Task (graphmem-cluster / graphmem-service)              │    │   │
│  │  │  [graphmem-ecs-sg: inbound 8000/graphmem-alb-sg, outbound all]       │    │   │
│  │  │  Image: ECR avik22835/graphmem:latest                                │    │   │
│  │  │                                                                      │    │   │
│  │  │  gunicorn --workers 3 -k UvicornWorker api.main:app                 │    │   │
│  │  │  FastAPI routes:                                                     │    │   │
│  │  │    /health   /memory   /conversations                                │    │   │
│  │  │    /topics   /auth     /utils                                        │    │   │
│  │  │                                                                      │    │   │
│  │  │  Lifespan:                                                           │    │   │
│  │  │    init_pool() ──────────────────────────────────────────────────────┼────┼───┼──► RDS:5432
│  │  │    init_neptune() ───────────────────────────────────────────────────┼────┼───┼──► Neptune:8182
│  │  │                                                                      │    │   │
│  │  │  add_response() path:                                                │    │   │
│  │  │    save to RDS ──► push_node_job() ─────────────────────────────────┼────┼───┼──► SQS node-queue
│  │  │                                                                      │    │   │
│  │  │  recall() path:                                                      │    │   │
│  │  │    embed_query(Jina) ──► pgvector Set B ──► Neptune Set C           │    │   │
│  │  │    ──► union A'∪B∪C∪R ──► token budget ──► RecallResult            │    │   │
│  │  │                                                                      │    │   │
│  │  │  Auth:                                                               │    │   │
│  │  │    Bearer JWT ──► Cognito JWKS verify (python-jose RS256)            │    │   │
│  │  │    X-API-Key  ──► prefix lookup in RDS ──► bcrypt.checkpw           │    │   │
│  │  └──────────────────────────────────────────────────────────────────────┘    │   │
│  │                                                                              │   │
│  │  ┌──────────────────────────────────────────────────────────────────────┐    │   │
│  │  │  NAT Gateway (nat-10bf1589970292357)                                  │    │   │
│  │  │  Subnet: subnet-0a0fc495e9870ee59 (us-east-1a, public)               │    │   │
│  │  │  Elastic IP attached                                                  │    │   │
│  │  └──────────────────────────────┬───────────────────────────────────────┘    │   │
│  │                                 │                                            │   │
│  └─────────────────────────────────┼────────────────────────────────────────────┘   │
│                                    │                                                 │
│  ┌─────────────────────────────────┼────────────────────────────────────────────┐   │
│  │                   PRIVATE SUBNET (172.31.96.0/20, graphmem-private)           │   │
│  │                   Route table: 0.0.0.0/0 → NAT Gateway                       │   │
│  │                                │                                              │   │
│  │  ┌─────────────────────────────▼────────────────────────────────────────┐    │   │
│  │  │  Lambda: graphmem-node-worker                                         │    │   │
│  │  │  [graphmem-ecs-sg, same SG as ECS — allowed by RDS + Neptune SGS]    │    │   │
│  │  │  Trigger: SQS graphmem-node-queue (batch=1, visibility=360s)         │    │   │
│  │  │  Timeout: 5min  Memory: 512MB                                         │    │   │
│  │  │                                                                      │    │   │
│  │  │  Flow:                                                                │    │   │
│  │  │    SQS event ──► fetch node (RDS) ──► Jina embed 1024-dim            │    │   │
│  │  │    ──► UPDATE memory_nodes.embedding (pgvector)                      │    │   │
│  │  │    ──► addVertex (Neptune)                                            │    │   │
│  │  │    ──► cosine search → addEdge pairs (Neptune, weight≥0.4)           │    │   │
│  │  │    ──► node_count++ ──► if count%10==0: push to topic-queue          │    │   │
│  │  │                                                                      │    │   │
│  │  │  Internet via NAT: Jina AI API (api.jina.ai:443)                     │    │   │
│  │  │  VPC private: RDS:5432, Neptune:8182                                 │    │   │
│  │  └──────────────────────────────────────────────────────────────────────┘    │   │
│  │                                                                              │   │
│  │  ┌──────────────────────────────────────────────────────────────────────┐    │   │
│  │  │  Lambda: graphmem-topic-worker                                        │    │   │
│  │  │  Trigger: SQS graphmem-topic-queue (batch=1, visibility=360s)        │    │   │
│  │  │  Timeout: 5min  Memory: 512MB                                         │    │   │
│  │  │                                                                      │    │   │
│  │  │  Flow:                                                                │    │   │
│  │  │    SQS event ──► fetch all nodes+embeddings (RDS)                    │    │   │
│  │  │    ──► fetch all edges (Neptune Gremlin)                             │    │   │
│  │  │    ──► build NetworkX graph ──► Louvain community detection          │    │   │
│  │  │    ──► per cluster: Groq llama-3.3-70b label+summarize              │    │   │
│  │  │    ──► if is_mixed: recurse at higher resolution (limit=2)           │    │   │
│  │  │    ──► DELETE old topics ──► INSERT new topics (RDS)                 │    │   │
│  │  │                                                                      │    │   │
│  │  │  Internet via NAT: Groq API (api.groq.com:443)                       │    │   │
│  │  │  VPC private: RDS:5432, Neptune:8182                                 │    │   │
│  │  └──────────────────────────────────────────────────────────────────────┘    │   │
│  │                                                                              │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  RDS PostgreSQL (graphmem-db.cchco0ei6wzx.us-east-1.rds.amazonaws.com)       │   │
│  │  db.t4g.micro  |  db: graphmem  |  user: graphmem                            │   │
│  │  Extensions: pgvector, uuid-ossp                                             │   │
│  │  SG: default (inbound 5432 from graphmem-ecs-sg)                             │   │
│  │  Tables: conversations, memory_nodes, topics, api_keys                       │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  Neptune Serverless (graphmem-neptune.cluster-cchco0ei6wzx.us-east-1...)     │   │
│  │  Gremlin WebSocket endpoint: wss://endpoint:8182/gremlin                     │   │
│  │  IAM auth: OFF (plain WebSocket, VPC-private only)                           │   │
│  │  SG: graphmem-neptune-sg (inbound 8182 from graphmem-ecs-sg)                 │   │
│  │  Vertices: memory_node {memory_id, conversation_id}                          │   │
│  │  Edges: similar_to {weight, conversation_id} (bidirectional)                 │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  SQS Standard Queues                                                         │   │
│  │  graphmem-node-queue  (visibility: 360s)                                     │   │
│  │  graphmem-topic-queue (visibility: 360s)                                     │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  Cognito User Pool: us-east-1_bYrtLpJPH                                      │   │
│  │  App client: graphmem-client (706dfajvla7jbsgllh22ki5c45)                    │   │
│  │  Sign-in: email  |  No MFA  |  Self-registration: enabled                   │   │
│  │  JWKS: https://cognito-idp.us-east-1.amazonaws.com/us-east-1_bYrtLpJPH/     │   │
│  │         .well-known/jwks.json                                                │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

CI/CD Pipeline (outside VPC):

  GitHub (avik22835/GraphMem)
         │ git push → triggers
         ▼
  GitHub Actions (ubuntu-latest)
    ├── aws-actions/configure-aws-credentials (IAM user: graphmem-deploy)
    ├── aws-actions/amazon-ecr-login
    ├── docker build + push → ECR avik22835/graphmem:latest       (API)
    ├── docker build + push → ECR avik22835/graphmem:node-worker  (Lambda)
    └── docker build + push → ECR avik22835/graphmem:topic-worker (Lambda)

  ECR: 748439418518.dkr.ecr.us-east-1.amazonaws.com/avik22835/graphmem
```

---

## 3. Data Layer — PostgreSQL + pgvector (RDS)

### Instance

| Property | Value |
|---|---|
| Endpoint | `graphmem-db.cchco0ei6wzx.us-east-1.rds.amazonaws.com` |
| Instance class | `db.t4g.micro` (Sandbox / Easy Create) |
| Engine | PostgreSQL 16 |
| Database | `graphmem` |
| User | `graphmem` |
| Extensions | `pgvector`, `uuid-ossp` |
| AZ | `us-east-1b` |

### Connection (asyncpg)

```python
_pool = await asyncpg.create_pool(
    host=settings.postgres_host,
    port=5432,
    database="graphmem",
    user="graphmem",
    password=...,
    min_size=2,
    max_size=10,
    init=_init_connection,   # register_vector on each new connection
)

async def _init_connection(conn):
    await register_vector(conn)  # pgvector.asyncpg
```

`register_vector` must be called per connection (not per pool) because the vector type codec is connection-level. With `init=`, every new connection in the pool automatically registers it.

### Schema

#### `conversations`

```sql
CREATE TABLE conversations (
    conversation_id     UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    metadata            JSONB       NOT NULL DEFAULT '{}',
    next_index          INT         NOT NULL DEFAULT 0,
    node_count          INT         NOT NULL DEFAULT 0,
    last_topic_recompute TIMESTAMPTZ,
    dirty_topics        JSONB       NOT NULL DEFAULT '[]',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Why each column:**
- `next_index` — atomic counter incremented with `UPDATE ... SET next_index = next_index + 1 RETURNING next_index` inside a transaction. This gives each node a deterministic, collision-free index even under concurrent `add_prompt()` calls from agentic pipelines.
- `node_count` — separate from `next_index`. Only incremented after a node is fully embedded and inserted into Neptune. Used to trigger topic recomputation every 10 complete nodes.
- `dirty_topics` — JSONB array of topic_ids that contain a deleted node and need recomputation. Maintained on `delete_node()`.
- `last_topic_recompute` — timestamp of last full topic recompute. Used by the Lambda worker to avoid redundant runs.

#### `memory_nodes`

```sql
CREATE TABLE memory_nodes (
    memory_id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id     UUID        NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    index               INT         NOT NULL,
    prompt              TEXT        NOT NULL,
    response            TEXT,                           -- NULL while status = 'pending'
    timestamp_prompt    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    timestamp_response  TIMESTAMPTZ,
    embedding           vector(1024),                   -- NULL until status = 'complete'
    status              TEXT        NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'complete')),
    metadata            JSONB       NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (conversation_id, index)
);
```

**Why 1024 dimensions:** Jina Embeddings v4 is called with `"dimensions": 1024` (Matryoshka truncation). This matches Amazon Titan Embeddings v2 default (1024), keeping schema flexibility for model switching. 2048-dim vectors would double storage and slow HNSW significantly.

**Why `status` column:** `add_prompt()` creates a `pending` node with only the prompt. `add_response()` sets `response` and flips to `complete`. The Lambda node_worker only processes `complete` nodes. This handles concurrent agentic pipelines where prompts and responses arrive separately.

**Indexes:**

```sql
-- HNSW on embedding for cosine ANN search (Set B)
CREATE INDEX memory_nodes_embedding_hnsw
    ON memory_nodes USING hnsw (embedding vector_cosine_ops);

-- Composite for conversation+status filtering
CREATE INDEX memory_nodes_conv_status
    ON memory_nodes (conversation_id, status);

-- Chronological ordering for Set R and cold start
CREATE INDEX memory_nodes_conv_timestamp
    ON memory_nodes (conversation_id, timestamp_prompt ASC);
```

**Why HNSW over IVFFlat:**
- HNSW (Hierarchical Navigable Small World) works on dynamic datasets — no pre-training step required. IVFFlat requires a `VACUUM` + reindex step after significant inserts to rebuild the inverted file.
- HNSW queries are faster at the same recall level for small-to-medium datasets (< 1M vectors).
- GraphMem inserts nodes continuously (one per `add_response()`), making IVFFlat's pre-training requirement impractical.

#### `topics`

```sql
CREATE TABLE topics (
    topic_id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id     UUID        NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    label               TEXT,
    description         TEXT,
    summary             TEXT,
    coherence           FLOAT,
    is_mixed            BOOLEAN     NOT NULL DEFAULT FALSE,
    sub_themes          JSONB       NOT NULL DEFAULT '[]',
    status              TEXT        NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active', 'dormant', 'resolved')),
    message_ids         JSONB       NOT NULL DEFAULT '[]',
    centroid            vector(1024),
    louvain_resolution  FLOAT       NOT NULL DEFAULT 1.0,
    recompute_count     INT         NOT NULL DEFAULT 0,
    last_active         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX topics_centroid_hnsw
    ON topics USING hnsw (centroid vector_cosine_ops);
```

**Why `centroid` vector:** `current_topic()` in centroid mode does `ORDER BY centroid <=> recent_embedding LIMIT 1` — a single vector similarity query to find which topic the most recent message belongs to. Without the centroid stored, you'd need to compute it on every query from all member embeddings.

**Why `is_mixed` and `sub_themes`:** Louvain clustering is structural (graph-based), not semantic. A cluster of messages might span multiple actual topics. Groq evaluates each cluster and flags it as mixed if it detects this. Mixed clusters with low coherence trigger recursive Louvain at a higher resolution (up to 2 times).

**Why `louvain_resolution` and `recompute_count`:** Tracks what resolution parameter was used to generate the cluster. The LLM suggests `next_resolution` when it flags `is_mixed=true`. The worker uses this value for the recursive call. `recompute_count` enforces the recursion limit.

#### `api_keys`

```sql
CREATE TABLE api_keys (
    key_id          UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
    key_prefix      TEXT    NOT NULL,
    key_hash        TEXT    NOT NULL,
    user_id         TEXT    NOT NULL,
    project_name    TEXT,
    permissions     JSONB   NOT NULL DEFAULT '{"read": true, "write": true}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_used_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX api_keys_prefix ON api_keys (key_prefix);
CREATE INDEX api_keys_user   ON api_keys (user_id);
```

**Why prefix + hash:** The full key is `gm_sk_<32-byte-urlsafe-random>`. Only the first 22 characters (prefix) are stored in plaintext — used to look up the row. The full key is hashed with bcrypt (rounds=12) and the hash is what's stored and verified. The developer never sees the key again after creation (shown once).

---

## 4. Graph Layer — Neptune Serverless

### Instance

| Property | Value |
|---|---|
| Cluster endpoint | `graphmem-neptune.cluster-cchco0ei6wzx.us-east-1.neptune.amazonaws.com` |
| Port | `8182` |
| Protocol | Gremlin WebSocket (`wss://`) |
| IAM auth | **OFF** — plain WebSocket, no SigV4 signing |
| Capacity | Serverless (0.5–128 NCU, scales to zero) |
| AZ | `us-east-1b` |

### Why Neptune instead of pgvector for everything

pgvector answers the question: *"which stored vectors are most similar to this query vector?"* (ANN search)

Neptune answers the question: *"starting from these nodes, who are their neighbors?"* (graph traversal)

Set C in `recall()` requires: *"given nodes in Set B, find their 1-hop similar neighbors in the graph."* This is not a similarity search — it's a traversal. You're not asking which nodes are similar to the query; you're asking which nodes are connected to Set B nodes. The distinction matters because two messages might not directly resemble the query but are semantically adjacent to messages that do. Neptune's Gremlin traversal expresses this in one query:

```python
g.V()
 .has("memory_node", "memory_id", P.within(b_id_list))
 .outE("similar_to")
 .has("weight", P.gte(threshold))
 .has("conversation_id", conversation_id)
 .inV()
 .values("memory_id")
 .to_list()
```

Doing this in pgvector would require a JOIN on a self-referencing edges table with a cosine condition — possible, but slower and not what the engine is optimized for.

### Connection initialization

```python
def init_neptune() -> None:
    endpoint = f"wss://{settings.neptune_endpoint}:{settings.neptune_port}/gremlin"
    _connection = DriverRemoteConnection(endpoint, "g")   # for traversal DSL
    _client = client.Client(                               # for raw Gremlin string queries
        endpoint, "g",
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )
```

Both are initialized at ECS startup (lifespan). `DriverRemoteConnection` is used by the FastAPI service for traversal DSL queries (`get_traversal()`). `client.Client` is used by the Lambda workers for raw Gremlin string submission (`get_neptune().submit(...)`). The raw client is more reliable for complex mutations like `addE().from_()` which has Python DSL binding issues.

### Graph schema (schema-free, Gremlin property graph)

No DDL required — Neptune is schema-free.

**Vertices:**
```
memory_node {
    memory_id:       UUID string
    conversation_id: UUID string
}
```

**Edges (bidirectional — two edges per pair):**
```
similar_to {
    weight:          float (cosine similarity, ≥ threshold)
    conversation_id: UUID string
}
```

Edges are stored bidirectionally (src→dst AND dst→src) so that traversal using `.outE()` from any node in Set B finds all neighbors without needing `.bothE()`.

### Why IAM auth OFF

Neptune supports IAM authentication which requires SigV4 signing on every Gremlin request. This requires `boto3.Session` credential management and a custom transport layer in `gremlin-python`. For a hackathon with Neptune in a private VPC (no external access), the security benefit of IAM auth is minimal — the network layer already enforces access via security groups. Plain WebSocket kept the code simple.

---

## 5. Async Processing Pipeline — SQS + Lambda

### Why async at all

Jina AI embedding is an external HTTP API call that takes 200–800ms depending on text length. If `add_response()` was synchronous, every API call would block the developer's application for up to a second just for embedding. Worse, topic recomputation (Louvain + Groq LLM) takes several seconds for large conversations.

SQS decouples the write path from the compute path: `add_response()` writes to RDS and pushes to SQS in ~10ms. The embedding and graph-building happen asynchronously in Lambda, typically completing within 2–5 seconds without blocking the calling application.

### node_worker flow

```
SQS graphmem-node-queue receives message: {memory_id, conversation_id}
        │
        ▼
1. Fetch node from RDS
   SELECT prompt, response FROM memory_nodes
   WHERE memory_id=$1 AND status='complete'

2. Embed (Jina AI)
   POST api.jina.ai/v1/embeddings
   {model: jina-embeddings-v4, dimensions: 1024, task: retrieval.passage}
   → normalize to unit vector

3. Write embedding to pgvector
   UPDATE memory_nodes SET embedding=$1 WHERE memory_id=$2

4. Insert Neptune vertex
   g.addV('memory_node')
    .property('memory_id', mid)
    .property('conversation_id', cid)

5. Find all existing complete nodes with cosine similarity ≥ 0.4
   SELECT memory_id, 1-(embedding<=>$1) AS sim
   FROM memory_nodes
   WHERE conversation_id=$2 AND status='complete'
     AND memory_id != $3 AND embedding<=>$1 <= 0.6   -- (1 - 0.4 = 0.6)

6. For each similar neighbor: add bidirectional Neptune edge
   g.V().has('memory_node','memory_id',src).as('a')
    .V().has('memory_node','memory_id',dst)
    .addE('similar_to').from('a')
    .property('weight', sim)

7. Increment node_count on conversation
   UPDATE conversations SET node_count=node_count+1 RETURNING node_count

8. If node_count % 10 == 0:
   SQS graphmem-topic-queue.send_message({conversation_id})
```

### topic_worker flow

```
SQS graphmem-topic-queue receives message: {conversation_id}
        │
        ▼
1. Fetch all complete nodes with embeddings from RDS

2. Fetch all edges from Neptune
   g.V().has('memory_node','conversation_id', cid)
    .outE('similar_to')
    .project('src','dst','weight')

3. Build NetworkX graph from edges
   G = nx.Graph()
   G.add_nodes_from(all_node_ids)
   G.add_edge(src, dst, weight=w)

4. Louvain community detection
   partition = community_louvain.best_partition(G, resolution=1.0)

5. Per cluster (skipped if size < 2):
   a. Select representative messages (top N by graph centrality)
   b. Select most recent messages
   c. Prompt Groq llama-3.3-70b:
      → Output: {label, description, summary, coherence,
                 is_mixed, sub_themes, status, next_resolution}

   d. If is_mixed AND recompute_count < 2:
      → Re-run Louvain on subgraph at next_resolution
      → Recurse _process_cluster() on sub-clusters
      → Limit: 2 recursive levels

6. DELETE FROM topics WHERE conversation_id=$1
   INSERT all new topics with centroids

7. UPDATE conversations SET last_topic_recompute=NOW(), dirty_topics='[]'
```

### Why Lambda (not ECS background threads)

| Concern | ECS BackgroundTask | Lambda |
|---|---|---|
| Isolation | Worker crash affects API process | Worker crash is isolated, SQS retries |
| Scaling | Bound to 3 gunicorn workers | Up to 1000 concurrent Lambda invocations |
| Retry | Manual, silent failures | SQS retries 3× automatically, then DLQ |
| Timeout | Gunicorn 120s hard limit | Lambda up to 15 min |
| Cost at scale | ECS runs 24/7 | Lambda pays per invocation only |
| Slow Jina calls | Ties up gunicorn worker | Zero API impact |

For a hackathon demo with 10–50 messages, ECS background tasks would work. Lambda is the production-grade choice and the Lambda worker code exists in the repo — deployed separately from the API image.

### Lambda configuration

| Setting | node_worker | topic_worker |
|---|---|---|
| Runtime | Container image | Container image |
| Image | `avik22835/graphmem:node-worker` | `avik22835/graphmem:topic-worker` |
| Memory | 512 MB | 512 MB |
| Timeout | 5 min | 5 min |
| VPC | graphmem-private subnet | graphmem-private subnet |
| SG | graphmem-ecs-sg | graphmem-ecs-sg |
| Trigger | SQS graphmem-node-queue, batch=1 | SQS graphmem-topic-queue, batch=1 |

**Batch size 1:** Each SQS message triggers one Lambda invocation. This ensures independent retry per node/topic — a failure in one doesn't affect others.

---

## 6. API Layer — FastAPI on ECS Fargate

### Container command

```dockerfile
CMD ["gunicorn", "api.main:app",
     "-k", "uvicorn.workers.UvicornWorker",
     "-w", "3",
     "--bind", "0.0.0.0:8000",
     "--timeout", "120",
     "--access-logfile", "-"]
```

**Why 3 workers:** Formula = `(2 × vCPUs) + 1`. Task definition uses 1 vCPU → 3 workers. This maximizes throughput under I/O-bound workloads (waiting on RDS, Neptune, Jina API) without oversubscribing the CPU.

**Why no `--preload`:** Gunicorn's `--preload` loads the application before forking workers. asyncpg's connection pool is created in the asyncio event loop, which doesn't survive a `fork()`. Without `--preload`, each worker creates its own pool independently in its own event loop — correct behavior.

**Why gunicorn over uvicorn directly:** gunicorn acts as the process manager — it restarts crashed workers, manages signals (SIGTERM for graceful shutdown), and provides access logging. uvicorn alone would require a separate process supervisor.

**Why `--timeout 120`:** Neptune Gremlin traversals on cold graphs (first query after Neptune scales from zero) can take 10–30 seconds. Slow Jina calls during `recall()` queries add another 1–2 seconds. The 120s timeout covers these edge cases without unnecessarily killing legitimate requests.

### Routes

```
GET  /health                          — open, no auth
POST /memory/prompt                   — add_prompt() → pending node
POST /memory/{memory_id}/response     — add_response() → complete → push SQS
POST /memory/recall                   — recall() → RecallResult
GET  /memory/{memory_id}              — get node
DELETE /memory/{memory_id}            — delete node + Neptune vertex
GET  /memory/{memory_id}/neighbours   — get 1-hop neighbors
POST /memory/batch                    — add_batch() for bulk ingestion

POST /conversations                   — create_conversation()
GET  /conversations                   — list_conversations()
DELETE /conversations/{id}            — delete_conversation()

GET  /topics/{conversation_id}        — list_topics()
GET  /topics/{conversation_id}/current        — current_topic()
POST /topics/{conversation_id}/recompute      — manual trigger
GET  /topics/{topic_id}/info          — topic_info() (full object)
GET  /topics/{topic_id}/summary       — topic_summary()
GET  /topics/{topic_id}/status        — topic_status()
GET  /topics/{topic_id}/retrieve      — retrieve_by_topic()
POST /topics/retrieve_by_topics       — retrieve_by_topics()
GET  /topics/relevance                — topic_relevance()

POST /auth/keys                       — create API key (requires Cognito JWT)
GET  /auth/keys                       — list user's keys
DELETE /auth/keys/{key_id}            — revoke key

GET  /utils/count_tokens              — tiktoken token count
```

### Auth middleware design

All routes except `/health` require auth. Implemented via `Depends(get_current_principal)` added to each router at registration time in `main.py`:

```python
_auth = [Depends(get_current_principal)]
app.include_router(memory.router,  prefix="/memory",  dependencies=_auth)
app.include_router(topics.router,  prefix="/topics",  dependencies=_auth)
```

`get_current_principal` checks:
1. `Authorization: Bearer <token>` → Cognito JWT path
2. `X-API-Key: gm_sk_...` → API key path
3. Neither → 401

Write-only routes additionally depend on `require_write` which checks `principal["permissions"]["write"]`.

### ECS task definition (revision 2)

```
Family:       graphmem-task
CPU:          1024 (1 vCPU)
Memory:       2048 MB
Network mode: awsvpc
Image:        748439418518.dkr.ecr.us-east-1.amazonaws.com/avik22835/graphmem:latest
Port:         8000/tcp
```

**Env vars injected at task level (not in image):**
```
POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
NEPTUNE_ENDPOINT, NEPTUNE_PORT
SQS_NODE_QUEUE_URL, SQS_TOPIC_QUEUE_URL
COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, COGNITO_REGION
JINA_API_KEY, GROQ_API_KEY
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
```

Env vars are injected at runtime, not baked into the image. This means the same image works in any environment by changing the task definition — no rebuild needed for credential rotation.

---

## 7. Auth Layer — Cognito + API Keys

### Dual-auth design

GraphMem is a developer-facing API. Developers need two auth flows:
1. **Interactive (Cognito JWT):** Developer logs into their app, gets a JWT, uses it to call `/auth/keys` to provision API keys for their application
2. **Programmatic (API keys):** The developer's application calls GraphMem with `X-API-Key: gm_sk_...` on every request — no JWT required

### Cognito JWT verification

```python
async def _get_jwks() -> dict:
    # Fetched once, cached in module-level dict, never re-fetched
    url = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json"
    resp = await httpx.AsyncClient().get(url)
    _jwks_cache = resp.json()
    return _jwks_cache

async def verify_cognito_token(token: str) -> dict:
    jwks = await _get_jwks()
    issuer = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
    payload = jwt.decode(token, jwks, algorithms=["RS256"], issuer=issuer,
                         options={"verify_aud": False})
    return payload
```

**Why `verify_aud: False`:** Cognito JWTs carry an `aud` claim set to the client ID. Since GraphMem may be called from multiple clients, audience verification is relaxed. The issuer check (URL bound to your specific user pool) still ensures the token was issued by your Cognito pool, not a foreign one.

**Why JWKS caching:** Cognito's JWKS endpoint contains the RS256 public keys. These rotate rarely (Cognito rotates them automatically on a long schedule). Caching them in-process avoids an HTTP round-trip on every request. A module-level dict is initialized to `None` and populated on first JWT verification — effectively a singleton initialized lazily.

### API key design

```
Full key:    gm_sk_<32-byte-urlsafe-random>   → shown to developer ONCE
Prefix:      first 22 chars of full key        → stored in plaintext, used for DB lookup
Hash:        bcrypt(full_key, rounds=12)        → stored, never decrypted
```

**Verification path:**
```python
async def authenticate_key(raw_key: str) -> dict:
    key_prefix = raw_key[:22]
    row = await conn.fetchrow(
        "SELECT key_hash, user_id, permissions, is_active FROM api_keys WHERE key_prefix=$1",
        key_prefix,
    )
    if not row or not row["is_active"]:
        raise HTTPException(401)
    valid = await asyncio.to_thread(bcrypt.checkpw, raw_key.encode(), row["key_hash"].encode())
    if not valid:
        raise HTTPException(401)
    await conn.execute("UPDATE api_keys SET last_used_at=NOW() WHERE key_id=$1", row["key_id"])
```

**Why `asyncio.to_thread` for bcrypt:** `bcrypt.checkpw` is CPU-bound (by design — it's the cost factor). Running it directly in an async handler would block the event loop for ~50–200ms at rounds=12. `asyncio.to_thread` offloads it to a thread pool executor, keeping other requests responsive.

**Why bcrypt (not SHA-256 or SHA-512):** API keys are long-lived credentials stored in a database. If the database is compromised, bcrypt's cost factor (rounds=12 means 2^12 = 4096 iterations) makes brute-force attacks computationally expensive — roughly 0.3 seconds per guess on modern hardware. SHA-256 without key stretching would allow millions of guesses per second.

---

## 8. CI/CD — GitHub Actions → ECR

### Why GitHub Actions

The development machine (Windows 11) has no hardware virtualization enabled, so Docker Desktop cannot run. AWS CloudShell was also unavailable (see blocker 'a' in Section 11). GitHub Actions provides a Linux runner (ubuntu-latest) with Docker pre-installed, giving a free, fully managed Docker build environment.

### Workflow

```yaml
# .github/workflows/deploy.yml
name: Build and Push to ECR
on:
  push:
    branches: [main]

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id:     ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1
      - uses: aws-actions/amazon-ecr-login@v2

      # Main API image
      - run: |
          docker build -t 748439418518.dkr.ecr.us-east-1.amazonaws.com/avik22835/graphmem:latest .
          docker push 748439418518.dkr.ecr.us-east-1.amazonaws.com/avik22835/graphmem:latest

      # Lambda node_worker image
      - run: |
          docker build -t 748439418518.dkr.ecr.us-east-1.amazonaws.com/avik22835/graphmem:node-worker \
            -f workers/node_worker/Dockerfile workers/node_worker/
          docker push ...graphmem:node-worker

      # Lambda topic_worker image
      - run: |
          docker build -t 748439418518.dkr.ecr.us-east-1.amazonaws.com/avik22835/graphmem:topic-worker \
            -f workers/topic_worker/Dockerfile workers/topic_worker/
          docker push ...graphmem:topic-worker
```

**Deploy consequence:** Every deployment requires a `git push`. There is no manual deploy button. This is actually a benefit — every production deployment is automatically version-controlled and traceable via commit SHA.

**Docker layer caching strategy (in the API Dockerfile):**
```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt   # cached if requirements.txt unchanged
COPY api/ ./api/                                      # only this layer rebuilds on code changes
```

When only application code changes (not dependencies), the pip install layer is cached and the build takes ~20 seconds instead of ~2 minutes.

**IAM user `graphmem-deploy`:**
- Policy: `AmazonEC2ContainerRegistryPowerUser`
- Access key stored as GitHub repository secrets
- Used only for ECR push — no ECS or other service access

---

## 9. VPC + Networking Architecture

### VPC layout

```
VPC: vpc-03db9daa60bd3a47c (default VPC, 172.31.0.0/16, us-east-1)

PUBLIC SUBNETS (route: 0.0.0.0/0 → Internet Gateway igw-xxx)
├── subnet-0a0fc495e9870ee59  172.31.0.0/20   us-east-1a   [ALB, NAT Gateway]
├── subnet-09d3fd1698da3e2e1  172.31.80.0/20  us-east-1b   [ALB, ECS task]
├── subnet-05cf75d5ada6a062c  172.31.16.0/20  us-east-1c
├── subnet-035d026e8f23cbe18  172.31.32.0/20  us-east-1d
├── subnet-03f7df8ffd06db415  172.31.48.0/20  us-east-1e
└── subnet-08af5e0ec46eac70e  172.31.64.0/20  us-east-1f

PRIVATE SUBNET (route: 0.0.0.0/0 → NAT Gateway nat-10bf1589970292357)
└── subnet-0b0b1e1f74aff8eb0  172.31.96.0/20  us-east-1a   [Lambda workers]
    Route table: graphmem-private-rt
```

### NAT Gateway

| Property | Value |
|---|---|
| ID | `nat-10bf1589970292357` |
| Type | Public |
| Subnet | `subnet-0a0fc495e9870ee59` (us-east-1a, public) |
| Elastic IP | Allocated separately |
| State | Available |

Lambda functions in the private subnet route all outbound traffic through the NAT Gateway → Internet Gateway → internet. This gives them access to Jina AI and Groq APIs while keeping them VPC-private for RDS and Neptune access.

**Cost note:** NAT Gateway costs $0.045/hour + $0.045/GB data transfer in us-east-1. For a hackathon weekend (~48 hours), this is approximately $2.16 in NAT fees alone. The API calls to Jina and Groq are small payloads so data transfer cost is negligible.

### Security groups

```
graphmem-alb-sg (sg-0044f58c5f437593f)
  Inbound:  HTTP 80   0.0.0.0/0
  Outbound: All       0.0.0.0/0

graphmem-ecs-sg (sg-0194bca7e64937046)
  Inbound:  TCP 8000  sg-0044f58c5f437593f (graphmem-alb-sg)
  Outbound: All       0.0.0.0/0
  [Also used by Lambda workers — they share this SG]

default SG (sg-08287ac8fcb39ce21)  [attached to RDS]
  Inbound:  TCP 5432  sg-0194bca7e64937046 (graphmem-ecs-sg)
  Outbound: All       0.0.0.0/0

graphmem-neptune-sg (sg-07faa4104f3be954e)
  Inbound:  TCP 8182  sg-0194bca7e64937046 (graphmem-ecs-sg)
  Outbound: All       0.0.0.0/0
```

**Why Lambda uses graphmem-ecs-sg:** Lambda workers need to reach RDS (port 5432) and Neptune (port 8182). Both of those services' security groups already allow inbound from `graphmem-ecs-sg`. Reusing the same SG for Lambda avoids adding another inbound rule to each database SG.

### Traffic flows

```
Internet → ALB:80 (graphmem-alb-sg allows) → ECS:8000 (graphmem-ecs-sg allows from ALB SG)
ECS → RDS:5432 (default SG allows from graphmem-ecs-sg)
ECS → Neptune:8182 (graphmem-neptune-sg allows from graphmem-ecs-sg)
ECS → SQS (outbound all → internet)
ECS → Jina/Groq (outbound all → internet)

Lambda (private subnet) → NAT → internet → Jina/Groq
Lambda (private subnet) → RDS:5432 (default SG allows graphmem-ecs-sg which Lambda uses)
Lambda (private subnet) → Neptune:8182 (same reason)
Lambda (private subnet) → NAT → internet → SQS (topic queue from node_worker)
```

---

## 10. IAM Roles

### graphmem-ecs-execution-role

Used by ECS to pull the container image and write logs. Not available to the running container.

```
AmazonECSTaskExecutionRolePolicy (managed)
  → ecr:GetAuthorizationToken
  → ecr:BatchCheckLayerAvailability
  → ecr:GetDownloadUrlForLayer
  → ecr:BatchGetImage
  → logs:CreateLogStream
  → logs:PutLogEvents
```

### graphmem-ecs-task-role

Available inside the running ECS container (via EC2 instance metadata endpoint). Used by `boto3` to send SQS messages.

```
Custom inline policy: graphmem-sqs-send
  → sqs:SendMessage on graphmem-node-queue
  → sqs:SendMessage on graphmem-topic-queue
```

### graphmem-lambda-role

Used by both Lambda functions.

```
AWSLambdaVPCAccessExecutionRole (managed)
  → ec2:CreateNetworkInterface
  → ec2:DescribeNetworkInterfaces
  → ec2:DeleteNetworkInterface
  → logs:CreateLogGroup, CreateLogStream, PutLogEvents

AmazonSQSFullAccess (managed)
  → sqs:* on all queues

graphmem-sqs-receive (inline, from earlier setup)
  → SQS receive/delete for trigger processing
```

---

## 11. Deployment Journey — Every Blocker and Workaround

This section documents every obstacle encountered during deployment, in chronological order. The purpose is to show the real cost of building on AWS from scratch in a hackathon account, and to provide an honest accounting for the submission.

---

### Blocker A — CloudShell Blocked by Account Verification

**What happened:** AWS CloudShell requires identity verification on new accounts. The hackathon account had been active for roughly 2 days. CloudShell showed a blocking screen requiring phone or credit card verification before access was granted.

**Why it mattered:** The original plan was: write code locally → `docker build` in CloudShell → `docker push` to ECR → deploy. Without CloudShell, there was no Linux shell with Docker available. The development machine (Windows 11) has virtualization disabled in BIOS, so Docker Desktop cannot run.

**Workaround:** Created an IAM user `graphmem-deploy` with `AmazonEC2ContainerRegistryPowerUser`, added its access key and secret as GitHub repository secrets, and wrote a GitHub Actions workflow (`.github/workflows/deploy.yml`) that runs on every push to `main`. GitHub provides ubuntu-latest runners with Docker pre-installed.

**Overhead:** Setting up GitHub Actions took approximately 45 minutes — creating the IAM user, configuring the ECR repo, writing and debugging the workflow, adding secrets. This was overhead that had nothing to do with the project itself.

**Lasting consequence:** Every code change requires a `git push` to trigger a build. There is no fast local iteration loop. Each deployment cycle takes 2–4 minutes.

---

### Blocker B — RDS Query Editor Only Supports Aurora

**What happened:** Needed to run `schema.sql` on the RDS PostgreSQL instance. Went to RDS → Query Editor in the AWS console. The console explicitly said: "Query Editor is only available for Aurora Serverless clusters."

**Why it mattered:** Standard PostgreSQL RDS has no browser-based SQL interface in the AWS console. The only options were: psql CLI (not available without CloudShell or local psql), external tool (DBeaver/pgAdmin — requires opening port 5432 to the internet), or a custom script.

**Workaround:** Wrote `run_schema.py` — a Python script using `asyncpg` that connected directly from the local machine. Temporarily opened RDS port 5432 to `0.0.0.0/0`, ran the schema, immediately closed the rule.

---

### Blocker C — Database "graphmem" Didn't Exist

**What happened:** RDS Easy Create (Sandbox template) creates the PostgreSQL instance but only creates the `postgres` default database. Our connection string specified `database="graphmem"` which didn't exist. First run of `run_schema.py` failed: `FATAL: database "graphmem" does not exist`.

**Why it mattered:** Spent time debugging connection parameters before realizing the database itself was the issue — Easy Create gives you a server, not a named database.

**Workaround:** Modified `run_schema.py` to:
1. Connect to `database="postgres"` (always exists)
2. `CREATE DATABASE graphmem`
3. Close connection
4. Reconnect to `database="graphmem"`
5. Run `schema.sql`

---

### Blocker D — RDS Port 5432 Closed

**What happened:** Even after opening port 5432 in the RDS security group with destination `0.0.0.0/0`, initial connection attempts from the local machine timed out. The security group was attached to the default SG, which was correctly edited, but the change took ~30 seconds to propagate.

**Resolution:** Wait + retry. RDS was then accessible. Port was closed immediately after schema application.

---

### Blocker E — ECS Cluster: "Unable to Assume Service Linked Role"

**What happened:** First attempt to create the ECS cluster failed with: `"Unable to assume service linked role. Please verify that the role exists."` The role being referenced was `AWSServiceRoleForECS` — a service-linked role that ECS creates automatically.

**Root cause:** The role already existed in the account from a previous ECS usage. AWS was confused and displayed a misleading error.

**Workaround:** Waited 10 seconds and retried. The cluster was created successfully on the second attempt.

---

### Blocker F — ALB Listener Port Already Exists

**What happened:** When creating the ECS service with load balancer integration, the wizard offered to "Create a new listener on port 80." Clicking this failed with an error indicating the port 80 listener already existed (it was created when the ALB was created).

**Workaround:** Changed the radio button from "Create new listener" to "Use existing listener" and selected the existing port 80 listener. The service was created successfully.

---

### Blocker G — Container Crash: ModuleNotFoundError: No module named 'groq'

**What happened:** After the first successful ECS deployment, the container started, ran for a few seconds, then crashed with exit code 3. CloudWatch logs showed:

```
File "/app/api/services/topics.py", line 4, in <module>
    from groq import AsyncGroq
ModuleNotFoundError: No module named 'groq'
```

**Root cause:** `api/services/topics.py` was written with `from groq import AsyncGroq` (the Groq Python SDK), but `groq` was never added to `requirements.txt`. The Docker image was built without it. This was a pure omission — the package was used in code but never declared as a dependency.

**Fix:** Added `groq==0.11.0` to `requirements.txt`, pushed to GitHub, waited for GitHub Actions to build a new image (2 min), then force-deployed in ECS.

**Time cost:** ~20 minutes. The ECS deployment cycle (push → build → ECR push → ECS pulls → container starts → crash → CloudWatch logs show error → identify → fix → repeat) is slow.

---

### Blocker H — ALB Timeout Despite Healthy Target

**What happened:** After fixing the groq crash, ECS showed the task as Running and the ALB target group showed the target as **Healthy**. But `http://graphmem-alb-...elb.amazonaws.com/health` in Chrome showed `ERR_TIMED_OUT`.

**Debugging path:**
1. Checked ALB scheme → internet-facing ✓
2. Checked ALB SG inbound → tried to add port 80 rule → got "already exists" error ✓ (rule was already there)
3. Checked ECS SG inbound → tried to add port 8000 rule → got "already exists" ✓
4. Checked ALB listener → HTTP:80 → forward to graphmem-tg ✓
5. Target group → Healthy ✓

**Root cause:** Chrome was attempting HTTPS (redirecting port 80 to 443 silently in some network configs). `curl -v http://...` showed `HTTP/1.1 200 OK` with body `{"status":"ok"}`.

**Resolution:** The API was live the entire time. The browser test was misleading. The URL requires explicit `http://` prefix in the browser address bar.

---

### Blocker I — Lambda VPC + Internet Access Conflict

**What happened:** Lambda workers need two things simultaneously:
1. **VPC access** — RDS (port 5432) and Neptune (port 8182) are only accessible from within the VPC
2. **Internet access** — node_worker calls Jina AI (api.jina.ai:443), topic_worker calls Groq (api.groq.com:443)

Lambda functions placed **outside** VPC have internet access but cannot reach VPC resources (RDS, Neptune). Lambda functions placed **inside** VPC by default have no internet access because they get private IPs and the VPC route table points internet traffic to the Internet Gateway — but Lambda functions don't get public IPs even in public subnets.

**Alternatives considered:**

| Option | Problem |
|---|---|
| Lambda outside VPC + make RDS public | Bad security; Neptune has no publicly accessible endpoint option |
| Lambda outside VPC + NLB in front of Neptune | Complex, additional cost, latency |
| VPC endpoints for Bedrock (replace Jina/Groq) | Would require changing embedding model (dimension change in schema) |
| Lambda in VPC + NAT Gateway | Standard solution, small cost |

**Solution:** Created a private subnet (`172.31.96.0/20`, `graphmem-private`) in the default VPC. Created a NAT Gateway in an existing public subnet (us-east-1a). Created a new route table (`graphmem-private-rt`) with `0.0.0.0/0 → NAT Gateway` and associated it with the private subnet. Deployed Lambda workers in this private subnet.

Result: Lambda → private subnet → NAT Gateway → Internet Gateway → Jina/Groq APIs. Lambda → private subnet → VPC routing → RDS/Neptune.

**Time cost:** ~30 minutes. This is a fundamental AWS networking issue that affects every Lambda-heavy architecture that needs both external API calls and VPC resource access.

---

### Blocker J — SQS Visibility Timeout < Lambda Timeout

**What happened:** When adding the SQS trigger to `graphmem-node-worker` (configured with 5-minute timeout), AWS rejected the trigger creation with:

```
Queue visibility timeout: 30 seconds is less than Function timeout: 300 seconds
```

**Why this matters:** If SQS visibility timeout (the time a message is hidden after delivery) is shorter than Lambda's execution time, SQS will re-deliver the message to another Lambda invocation before the first one finishes. This causes duplicate processing.

**Fix:** Updated both SQS queues: **SQS → queue → Edit → Visibility timeout: 360 seconds** (must be ≥ Lambda timeout of 300s, with a margin).

---

### Blocker K — Jina Embedding Dimensions Mismatch

**What happened:** The PostgreSQL schema uses `vector(1024)`. Jina Embeddings v4's default output dimension is 2048. Neither the FastAPI embedding service (`api/services/embedding.py`) nor the Lambda node_worker's `embed()` function specified `"dimensions": 1024` in the API call.

**Why it wasn't caught earlier:** The embedding service was never called against an actual Jina response during development (recall() was never tested with real data). The mismatch would only surface when the first actual embed call tried to write a 2048-dim vector into a 1024-dim column.

**Fix:** Added `"dimensions": 1024` to all Jina API calls. Jina v4 supports Matryoshka representation learning — you can request any power-of-2 dimension from 32 to 2048 and get a semantically valid truncated embedding.

```python
json={
    "model": "jina-embeddings-v4",
    "input": [text],
    "task": "retrieval.passage",
    "dimensions": 1024,    # ← added
}
```

---

### Blocker L — Cognito New UI

**What happened:** The AWS Cognito console was redesigned. The old flow started directly with "Configure sign-in options." The new flow starts with "Application type" (Traditional web app, SPA, Mobile app, Machine-to-machine) and auto-generates example code.

**What it required:** Had to figure out which application type to select (SPA — closest to a developer-facing API client), and navigate the new flow (application type → name → sign-in identifier → self-registration → return URL → create).

**Outcome:**
- User Pool ID: `us-east-1_bYrtLpJPH`
- Client ID: `706dfajvla7jbsgllh22ki5c45`
- JWKS URL: `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_bYrtLpJPH/.well-known/jwks.json`

---

## 12. Why Each AWS Service Was Chosen

### Amazon RDS PostgreSQL + pgvector

GraphMem stores structured relational data: conversations reference memory nodes, memory nodes reference topics, API keys reference users. This is textbook relational data with foreign key integrity (ON DELETE CASCADE is used throughout). PostgreSQL was the obvious choice.

The `pgvector` extension adds `vector(n)` column types and operators (`<=>` for cosine distance, `<->` for L2) directly to PostgreSQL. This means the Set B similarity search (`SELECT ... ORDER BY embedding <=> $1 LIMIT k`) runs in the same database transaction as the metadata query — no cross-service round trip to a separate vector DB.

HNSW index on the embedding column gives approximate nearest neighbor search at O(log n) instead of O(n) brute force. For a developer API handling multiple conversations, this is essential.

### Amazon Neptune Serverless

Neptune is the only AWS-managed graph database. The Set C recall step — 1-hop expansion of graph neighbors — is fundamentally a graph traversal, not a vector similarity search. Gremlin's declarative traversal language expresses it in one statement.

Serverless eliminates capacity planning. Neptune scales from 0.5 NCU (minimum) to whatever is needed, and scales to zero when idle. For a hackathon project with bursty, unpredictable load, this is ideal.

### Amazon SQS

SQS standard queues decouple the add_response() write path from the embedding/graph-build compute path. This is the classic producer-consumer pattern. The producer (FastAPI) is latency-sensitive; the consumer (Lambda) is throughput-sensitive and can tolerate delays.

Standard queue (not FIFO) was chosen because order doesn't matter for node processing — each node is independent.

### AWS Lambda

Lambda is invoked exactly once per SQS message. It has no idle cost (unlike ECS which runs 24/7). Lambda's built-in SQS integration handles polling, batching, and deletion of processed messages automatically. If a Lambda invocation fails, SQS retries the message up to 3 times before routing to a dead-letter queue.

Lambda container images allow the same Docker-based packaging used for ECS — no zip file management, no layer size limits.

### ECS Fargate

ECS Fargate is serverless container hosting — no EC2 instance management. The task definition specifies CPU, memory, image URI, env vars, and IAM role. Fargate provisions infrastructure, pulls the image, and runs the container.

With ALB in front, ECS tasks can be replaced (for new deployments or health check failures) without downtime.

### Application Load Balancer (ALB)

The hackathon requires a "live stable URL." ALB provides a stable DNS name that doesn't change across deployments. ECS tasks get ephemeral private IPs that change on every restart — the ALB abstracts this behind a fixed DNS entry.

ALB also provides health check integration: ECS service monitors the `/health` endpoint and replaces unhealthy tasks automatically.

### Amazon ECR

ECR is a private Docker registry fully integrated with ECS and Lambda. No authentication complexity — the ECS execution role and Lambda execution role automatically have access via IAM. Image scanning and lifecycle policies are available but not configured for the hackathon.

### Amazon Cognito

Cognito provides user directory, JWT issuance, and OIDC-compatible JWKS endpoint. Building user authentication from scratch (bcrypt passwords, session tokens, email verification) would take days. Cognito handles it in minutes.

The JWKS endpoint (`/.well-known/jwks.json`) allows the FastAPI service to verify JWTs without calling Cognito on every request — it fetches the public keys once and verifies locally.

### IAM

IAM roles follow the principle of least privilege:
- ECS task role: only SQS SendMessage — cannot read SQS, cannot touch RDS directly via IAM, cannot touch ECR
- Lambda role: VPC access (required for ENI attachment) + SQS full access (trigger + send to topic queue)
- Execution roles: separate from task roles — only allow ECR pull and CloudWatch write

### NAT Gateway

The fundamental solution to the Lambda VPC internet access problem. Without NAT, Lambda workers in VPC cannot reach external APIs. With NAT, they route through a managed gateway that provides a stable outbound IP while keeping the Lambda private.

---

## 13. What Worked Well / What Could Be Better

### What worked well

**ECS Fargate + ECR + GitHub Actions:** Once the pipeline was established, the deploy cycle became: write code → git push → 2-3 minutes later the new container is running in ECS. Zero manual steps in the AWS console after initial setup.

**pgvector HNSW:** Adding vector search to PostgreSQL with one `CREATE INDEX` statement is elegant. The `<=>` operator integrates seamlessly with standard SQL predicates (WHERE, JOIN, LIMIT). No separate vector database service to manage.

**Neptune Serverless zero-to-available:** Neptune was provisioned in about 8 minutes via the console. The Gremlin Python client connected immediately with a WebSocket URL — no SDK configuration, no auth complexity with IAM off.

**SQS-Lambda trigger integration:** Adding SQS as a Lambda event source is a two-click operation in the console. Lambda automatically polls the queue, deserializes messages, and passes them as `event["Records"]`. The developer writes `handler(event, context)` and gets a list of messages — no polling code, no SQS client needed for receives.

**ALB health check + ECS:** The ECS service automatically replaced the container when it crashed (groq import error). The ALB stopped routing traffic to the unhealthy target while the replacement was starting. This happened without any manual intervention.

**asyncpg + pgvector:** `register_vector(conn)` in the pool init callback means every connection in the pool can read and write vector columns natively. asyncpg's performance for bulk operations (add_batch) is significantly faster than psycopg2.

### What could be better

**CloudShell account verification gating:** Blocking CloudShell on new accounts is the highest-friction issue for hackathon participants. CloudShell is the primary way most AWS users run CLI commands. The forced alternative (GitHub Actions) added 45+ minutes of setup. AWS should provide at least a limited CloudShell with just ECR push permissions during the account verification period.

**RDS Query Editor not supporting PostgreSQL:** Every AWS PostgreSQL tutorial mentions the Query Editor, but it's Aurora-only. The console should be explicit about this before the user spends time trying to connect. An alternative lightweight query interface (even a read-only one) for standard RDS would eliminate the need for external tools.

**Lambda VPC + internet access discoverability:** The documentation for "Lambda in VPC loses internet access" exists, but it's not surfaced during the Lambda VPC configuration flow. When you select a VPC for a Lambda function, the console should prominently warn: "Lambda functions in a VPC don't have internet access. You need a NAT Gateway or VPC endpoints for external API calls." This would have saved 30+ minutes of debugging.

**ECS service linked role error:** The error "Unable to assume service linked role" when the role already exists is misleading. The fix (retry) is nowhere in the error message or the linked documentation.

**Neptune IAM auth default ON:** Neptune clusters require IAM authentication by default. Plain gremlin-python with a WebSocket URL fails silently with connection errors. The documentation for disabling IAM auth is buried. For first-time Neptune users, starting with "authentication: none + inside VPC" would be a better default for learning.

**SQS visibility timeout constraint not shown proactively:** The constraint that queue visibility timeout must be ≥ Lambda function timeout is not shown in the Lambda trigger configuration UI until after you try to save. The form should validate against the Lambda timeout before submission.

---

## 14. DB Schema + Graph Logic Integration

### How recall() maps to the schema

```
recall(query, conversation_id, K=5, threshold=0.4, strategy="semantic",
       always_include_recent=0, max_tokens=2000) → RecallResult

Step 1 — Cold start check
  SELECT node_count FROM conversations WHERE conversation_id=$1
  if node_count < cold_start_min_nodes (5):
    return full history (SELECT * FROM memory_nodes ORDER BY timestamp_prompt)

Step 2 — Embed query
  Jina AI API → q_emb (1024-dim unit vector)

Step 3 — Set B: top-K by cosine similarity (pgvector HNSW)
  SELECT memory_id, prompt, response, timestamp_prompt,
         1 - (embedding <=> $1) AS cosine_score
  FROM memory_nodes
  WHERE conversation_id = $2 AND status = 'complete'
  ORDER BY embedding <=> $1     ← HNSW index used here
  LIMIT $3                      ← K (default 5)

Step 4 — Set A': threshold sweep (any node ≥ threshold, not in B)
  SELECT ... 1-(embedding<=>$1) AS cosine_score
  FROM memory_nodes
  WHERE conversation_id=$2 AND status='complete'
    AND NOT (memory_id = ANY($3::uuid[]))   ← exclude Set B
    AND embedding <=> $1 <= $4              ← 1 - threshold = 0.6

Step 5 — Set C: Neptune 1-hop expansion from Set B
  g.V()
   .has("memory_node", "memory_id", P.within(b_id_list))
   .outE("similar_to")
   .has("weight", P.gte(threshold))
   .has("conversation_id", conversation_id)
   .inV()
   .values("memory_id")
   .to_list()
  → set of neighbor memory_ids not in B or A'
  → fetch their embeddings from RDS for Python-side scoring

Step 6 — Set R: last M messages (always_include_recent)
  SELECT * FROM memory_nodes
  WHERE conversation_id=$1 AND status='complete'
  ORDER BY timestamp_prompt DESC
  LIMIT M

Step 7 — Token budgeting
  total = R∪A'∪B∪C
  R is exempt (guaranteed in output)
  remaining_budget = max_tokens - tokens(R)
  sort candidates (A'∪B∪C) by cosine_score DESC
  greedily add until budget exhausted

Step 8 — Final sort and return
  merge survivors + R
  sort by timestamp_prompt ASC
  return RecallResult {messages, text (JSON), total_tokens, strategy_used}
```

### How topic recomputation maps to the schema

```
node_count % 10 == 0 → push to SQS topic queue → topic_worker

topic_worker:
  1. SELECT memory_id, embedding, prompt, response, timestamp_prompt, index
     FROM memory_nodes
     WHERE conversation_id=$1 AND status='complete' AND embedding IS NOT NULL

  2. Neptune: fetch all edges for conversation
     → build NetworkX graph G

  3. Louvain: community_louvain.best_partition(G, resolution=1.0)
     → {node_id: cluster_id}

  4. Per cluster (len ≥ 2):
     - compute centroid: mean of member embeddings → normalize
     - select central nodes (by NetworkX degree centrality)
     - select recent nodes (by index DESC)
     - Groq prompt → JSON response:
       {label, description, summary, coherence, is_mixed, sub_themes, status, next_resolution}
     - if is_mixed AND recompute_count < 2:
         sub-partition with next_resolution → recurse

  5. DELETE FROM topics WHERE conversation_id=$1
     INSERT INTO topics (topic_id, conversation_id, label, description, summary,
                         coherence, is_mixed, sub_themes, status, message_ids,
                         centroid, louvain_resolution, recompute_count, last_active, ...)
     UPDATE conversations SET last_topic_recompute=NOW(), dirty_topics='[]'
```

### How current_topic() maps to the schema

```
current_topic(conversation_id, mode="centroid"|"hybrid"|"llm")

Centroid mode:
  1. Fetch most recent complete node with embedding
  2. SELECT topic_id, label, 1-(centroid<=>$1) AS score
     FROM topics WHERE conversation_id=$2 AND centroid IS NOT NULL
     ORDER BY centroid <=> $1        ← HNSW index on topics.centroid
     LIMIT 1
  → Return: {topic_id, label, score, mode: "centroid"}

Hybrid mode:
  1. Same centroid query (gets top result + score)
  2. Fetch all topics with summaries
  3. Groq prompt: "centroid says topic X — does the most recent message confirm?"
  → Return: LLM-chosen topic with centroid as fallback

LLM mode:
  1. Fetch most recent message + all topics
  2. Groq prompt: "which topic does this message belong to?"
  → Return: LLM-chosen topic
```

---

## 15. Hackathon Submission Form Answers

### "How did you use AWS in your project?"

GraphMem is a semantic graph-based memory and context management API for LLM agent developers. It models conversation history as a graph (messages = nodes, semantic similarity = edges) and retrieves the most relevant context at inference time, reducing token usage while improving recall quality.

**Build it (AWS open source stack):**
- FastAPI (Python web framework) containerized with Docker
- gunicorn + UvicornWorker for ASGI process management
- gremlin-python for Neptune graph traversal
- asyncpg for async PostgreSQL access
- pgvector Python package for vector type registration
- python-jose for JWT verification
- NetworkX + python-louvain for graph-based topic clustering

**Ship it (AWS services):**
- **Amazon ECS Fargate** — hosts the FastAPI API (graphmem-service on graphmem-cluster, 1 vCPU/2GB, 3 gunicorn workers)
- **Amazon ECR** — private Docker registry for 3 container images (API, node-worker, topic-worker)
- **Amazon RDS PostgreSQL** — stores conversations, memory nodes, topics, and API keys; pgvector extension enables vector similarity search (HNSW index on 1024-dim embeddings)
- **Amazon Neptune Serverless** — stores the semantic graph (memory_node vertices + similar_to edges); Gremlin traversal is used for 1-hop neighbor expansion in the recall() algorithm
- **Amazon SQS** — two standard queues (graphmem-node-queue, graphmem-topic-queue) decouple the write API from async processing
- **AWS Lambda** — two container-image-based Lambda functions (node_worker: embed + graph-build; topic_worker: Louvain clustering + LLM labeling) triggered by SQS
- **Application Load Balancer** — internet-facing ALB provides the stable live URL required by the hackathon
- **Amazon Cognito** — user pool for JWT-based authentication; developers authenticate to provision API keys
- **AWS IAM** — least-privilege roles for ECS (SQS send only) and Lambda (VPC access + SQS)
- **NAT Gateway** — enables Lambda workers in a private subnet to reach external APIs (Jina AI embeddings, Groq LLM) while staying VPC-private for RDS and Neptune access

---

### "What did you like about the AWS services you used?"

**ECS Fargate + ECR:** The deploy cycle is frictionless once GitHub Actions is set up. Every `git push` to main triggers a Docker build and ECR push. ECS pulls the new image and replaces running tasks automatically. The ALB health check integration means task replacement is zero-downtime. No server management, no AMI, no SSH.

**pgvector on RDS:** Adding vector similarity search to a standard PostgreSQL instance with one SQL extension is elegant engineering. `ORDER BY embedding <=> $1 LIMIT k` is a real ANN query using an HNSW index — not a brute-force scan. Having structured metadata (conversations, foreign keys, transactions) and vector search in the same database eliminates the operational overhead of running a separate vector service.

**Neptune Serverless:** Scales to zero when idle — critical for a hackathon project where testing is bursty. The Gremlin WebSocket client connected immediately with zero configuration (IAM auth off, VPC security group allows the ECS SG). Schema-free vertices and edges meant we could start inserting data without DDL.

**SQS + Lambda integration:** The Lambda SQS trigger is automatic. After wiring the trigger in the console, Lambda polls the queue, receives messages, passes them to the handler, and deletes successfully processed messages — all without any polling code in the worker. If the handler raises an exception, SQS retries the message automatically.

---

### "What did you NOT like about the AWS services you used?"

**CloudShell blocked on new accounts:** CloudShell was unavailable due to account verification requirements — this is the most common CLI entry point and blocking it forced a 45-minute GitHub Actions detour. A limited-capability CloudShell (or even just ECR push access) should be available from day one for hackathon accounts.

**RDS Query Editor is Aurora-only:** Every AWS tutorial on RDS shows the Query Editor, but it silently rejects non-Aurora instances. There is no lightweight browser-based SQL interface for standard PostgreSQL RDS. This forced writing an external Python script just to run schema.sql.

**Lambda VPC networking is not surfaced clearly:** When you configure a Lambda function to use a VPC, there is no console warning that this removes internet access. Lambda functions in a VPC need a NAT Gateway or VPC Interface Endpoints for outbound internet — a non-obvious and non-free requirement. This should be a prominent warning in the VPC configuration panel.

**SQS visibility timeout constraint discovered late:** The requirement that SQS visibility timeout must be ≥ Lambda function timeout is enforced at trigger creation time — not shown proactively in the form. This caused one failed trigger creation attempt and a round-trip to SQS to fix the timeout.

**Neptune IAM auth ON by default:** New Neptune clusters require IAM authentication, which requires SigV4 request signing in every Gremlin client. Plain gremlin-python over WebSocket fails with confusing connection errors when IAM auth is on. For first-time Neptune users, the default should be explained upfront with a prominent toggle and documentation link during cluster creation.
