-- GraphMem PostgreSQL Schema
-- Run once on a fresh RDS instance

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────
-- conversations
-- ─────────────────────────────────────────
CREATE TABLE conversations (
    conversation_id     UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    metadata            JSONB       NOT NULL DEFAULT '{}',
    next_index          INT         NOT NULL DEFAULT 0,      -- atomic counter for node index
    node_count          INT         NOT NULL DEFAULT 0,
    last_topic_recompute TIMESTAMPTZ,
    dirty_topics        JSONB       NOT NULL DEFAULT '[]',   -- array of dirty topic_ids
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────
-- memory_nodes
-- ─────────────────────────────────────────
CREATE TABLE memory_nodes (
    memory_id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id     UUID        NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    index               INT         NOT NULL,
    prompt              TEXT        NOT NULL,
    response            TEXT,                               -- NULL while status = pending
    timestamp_prompt    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    timestamp_response  TIMESTAMPTZ,
    embedding           vector(1024),                       -- NULL until status = complete
    status              TEXT        NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'complete')),
    metadata            JSONB       NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (conversation_id, index)
);

-- HNSW index for cosine similarity search (Set B in recall)
-- HNSW works without pre-training, better for dynamic inserts than IVFFlat
CREATE INDEX memory_nodes_embedding_hnsw
    ON memory_nodes USING hnsw (embedding vector_cosine_ops);

CREATE INDEX memory_nodes_conv_status
    ON memory_nodes (conversation_id, status);

CREATE INDEX memory_nodes_conv_timestamp
    ON memory_nodes (conversation_id, timestamp_prompt ASC);

-- ─────────────────────────────────────────
-- topics
-- ─────────────────────────────────────────
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
    message_ids         JSONB       NOT NULL DEFAULT '[]',  -- array of memory_ids
    centroid            vector(1024),                       -- mean embedding of all messages in topic
    louvain_resolution  FLOAT       NOT NULL DEFAULT 1.0,
    recompute_count     INT         NOT NULL DEFAULT 0,
    last_active         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX topics_conv
    ON topics (conversation_id, status);

-- HNSW on topic centroids for current_topic() centroid mode
CREATE INDEX topics_centroid_hnsw
    ON topics USING hnsw (centroid vector_cosine_ops);

-- ─────────────────────────────────────────
-- api_keys
-- ─────────────────────────────────────────
CREATE TABLE api_keys (
    key_id          UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
    key_prefix      TEXT    NOT NULL,       -- e.g. "gm_sk_A1B2C3D4" shown to dev for identification
    key_hash        TEXT    NOT NULL,       -- bcrypt hash of full key, never stored plaintext
    user_id         TEXT    NOT NULL,       -- Cognito sub
    project_name    TEXT,
    permissions     JSONB   NOT NULL DEFAULT '{"read": true, "write": true}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_used_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX api_keys_prefix ON api_keys (key_prefix);
CREATE INDEX api_keys_user   ON api_keys (user_id);
