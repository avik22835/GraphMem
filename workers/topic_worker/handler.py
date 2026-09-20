import os
import json
import uuid
import httpx
import numpy as np
import networkx as nx
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from groq import Groq
import community as community_louvain
from datetime import datetime, timezone

# ── Module-level connections (reused across warm invocations) ─────────────────

_pg_conn     = None
_groq_client = None

NEPTUNE_URL = (
    f"https://{os.environ['NEPTUNE_ENDPOINT']}:{os.environ['NEPTUNE_PORT']}/gremlin"
)

LOUVAIN_DEFAULT_RESOLUTION = float(os.environ.get("LOUVAIN_DEFAULT_RESOLUTION", "1.0"))
TOPIC_MIN_CLUSTER_SIZE     = int(os.environ.get("TOPIC_MIN_CLUSTER_SIZE", "2"))
TOPIC_RECOMPUTE_INTERVAL   = int(os.environ.get("TOPIC_RECOMPUTE_INTERVAL", "20"))
REPRESENTATIVE_COUNT       = int(os.environ.get("TOPIC_LABEL_REPRESENTATIVE_COUNT", "5"))
RECENT_COUNT               = int(os.environ.get("TOPIC_LABEL_RECENT_COUNT", "3"))
RECURRENCE_LIMIT           = 2


def get_pg():
    global _pg_conn
    if _pg_conn is None or _pg_conn.closed:
        _pg_conn = psycopg2.connect(
            host=os.environ["POSTGRES_HOST"],
            port=os.environ["POSTGRES_PORT"],
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )
        _pg_conn.autocommit = False
        register_vector(_pg_conn)
    return _pg_conn


def neptune(query: str) -> list:
    resp = httpx.post(NEPTUNE_URL, json={"gremlin": query}, timeout=30.0)
    if not resp.is_success:
        print(f"[topic_worker] Neptune {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    data = resp.json().get("result", {}).get("data", {})
    return data.get("@value", []) if isinstance(data, dict) else []


def _parse_gmap(item: dict) -> dict:
    vals = item.get("@value", [])
    out = {}
    for i in range(0, len(vals), 2):
        k = vals[i]
        v = vals[i + 1]
        if isinstance(v, dict) and "@value" in v:
            v = v["@value"]
        out[k] = v
    return out


def get_groq():
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client


# ── Graph construction from Neptune ──────────────────────────────────────────

def _build_networkx_graph(conversation_id: str, node_ids: set) -> nx.Graph:
    raw = neptune(
        f"g.V().has('memory_node','conversation_id','{conversation_id}')"
        ".outE('similar_to')"
        ".project('src','dst','weight')"
        ".by(outV().values('memory_id'))"
        ".by(inV().values('memory_id'))"
        ".by('weight')"
    )

    G = nx.Graph()
    G.add_nodes_from(node_ids)
    for item in raw:
        e = _parse_gmap(item) if isinstance(item, dict) and "@value" in item else item
        src, dst = e.get("src"), e.get("dst")
        if src and dst and src in node_ids and dst in node_ids:
            G.add_edge(src, dst, weight=float(e.get("weight", 1.0)))
    return G


# ── Centroid ──────────────────────────────────────────────────────────────────

def _compute_centroid(node_ids: list, nodes: dict) -> np.ndarray:
    embs = np.array([nodes[n]["embedding"] for n in node_ids if n in nodes], dtype=np.float32)
    c    = embs.mean(axis=0)
    norm = np.linalg.norm(c)
    return c / norm if norm > 0 else c


# ── Groq labeling ─────────────────────────────────────────────────────────────

def _label_cluster(
    node_ids: list,
    nodes: dict,
    G: nx.Graph,
    resolution: float,
    recompute_count: int,
    conv_next_index: int,
) -> dict:
    subgraph = G.subgraph(node_ids)
    deg      = nx.degree_centrality(subgraph)

    central_ids = sorted(node_ids, key=lambda n: deg.get(n, 0), reverse=True)[:REPRESENTATIVE_COUNT]
    central_set = set(central_ids)
    recent_ids  = [
        n for n in sorted(node_ids, key=lambda n: nodes[n]["index"] if n in nodes else 0, reverse=True)
        if n not in central_set
    ][:RECENT_COUNT]

    def fmt(nid):
        node = nodes.get(nid)
        if not node:
            return ""
        resp = (node["response"] or "").strip()
        return f"[{nid}] USER: {node['prompt']} | ASSISTANT: {resp}"

    central_block = "\n".join(fmt(n) for n in central_ids)
    recent_block  = "\n".join(fmt(n) for n in recent_ids) if recent_ids else "(all shown above)"
    last_index    = max((nodes[n]["index"] for n in node_ids if n in nodes), default=0)

    prompt = f"""You are labelling a cluster of conversation messages grouped by a graph community-detection algorithm (Louvain), not by a human. Structural grouping does not guarantee semantic coherence.

2 failure modes to actively check:
1) Mixed Cluster: messages share vocabulary but cover 2+ distinct sub-themes or tasks.
2) Incomplete fragment: this cluster may be a partial slice of a larger topic split across clusters.

Temporal context: last message in this cluster is at conversation index {last_index} of {conv_next_index} total (1 = oldest). Current Louvain resolution: {resolution}. Rerun count: {recompute_count}.
Cluster total messages: {len(node_ids)}.

--- Most representative messages (by graph centrality) ---
{central_block}

--- Most recent messages in this cluster ---
{recent_block}

Do the following:
a) Decide if this is one coherent topic or a Mixed Cluster.
b) Produce a specific label (a few words) and a one-sentence description. Never use vague labels like "general discussion" — if you cannot find a shared thread, say so explicitly.
c) Write a 1-2 sentence summary of what this topic covers.
d) If Mixed, list the distinct sub-themes with message_ids belonging to each.
e) Give a coherence score 0.0-1.0 (how confident you are this is a single clean topic).
f) Assess status: "active" if ongoing, "resolved" if clearly concluded (question answered, decision made, task completed), "dormant" if it stopped without conclusion.
g) If is_mixed is true, suggest a next_resolution value (must be higher than {resolution}) to better split this cluster on rerun.

Output valid JSON only:
{{
  "label": string,
  "description": string,
  "summary": string,
  "coherence": float,
  "is_mixed": boolean,
  "sub_themes": [{{"label": string, "message_ids": [string]}}],
  "status": "active" | "dormant" | "resolved",
  "next_resolution": float
}}"""

    import time
    for attempt in range(5):
        try:
            resp = get_groq().chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                wait = 2 ** attempt
                print(f"[topic_worker] Groq 429 — retrying in {wait}s (attempt {attempt+1}/5)")
                time.sleep(wait)
                continue
            print(f"[topic_worker] Groq labeling error: {e}")
            break
    return {
        "label": "Unlabeled cluster",
        "description": "", "summary": "",
        "coherence": 0.5, "is_mixed": False, "sub_themes": [],
        "status": "dormant",
        "next_resolution": round(resolution * 1.5, 2),
    }


# ── Cluster processing (recursive, respects RECURRENCE_LIMIT) ────────────────

def _process_cluster(
    node_ids: list,
    nodes: dict,
    G: nx.Graph,
    resolution: float,
    recompute_count: int,
    conv_next_index: int,
) -> list[dict]:
    if len(node_ids) < TOPIC_MIN_CLUSTER_SIZE:
        return []

    label_result = _label_cluster(node_ids, nodes, G, resolution, recompute_count, conv_next_index)

    if label_result.get("is_mixed") and recompute_count < RECURRENCE_LIMIT:
        next_res = float(label_result.get("next_resolution", round(resolution * 1.5, 2)))
        subgraph = G.subgraph(node_ids).copy()

        if subgraph.number_of_edges() > 0:
            sub_partition = community_louvain.best_partition(subgraph, resolution=next_res, weight="weight")
        else:
            # No internal edges — subgraph can't be split, treat as single topic
            sub_partition = {n: 0 for n in node_ids}

        sub_clusters: dict[int, list] = {}
        for n, cid in sub_partition.items():
            sub_clusters.setdefault(cid, []).append(n)

        topics = []
        for sub_nodes in sub_clusters.values():
            topics.extend(_process_cluster(
                sub_nodes, nodes, G,
                resolution=next_res,
                recompute_count=recompute_count + 1,
                conv_next_index=conv_next_index,
            ))
        # If sub-clustering yielded nothing usable, fall back to single topic
        return topics or [_build_topic(node_ids, nodes, label_result, resolution, recompute_count, conv_next_index)]

    return [_build_topic(node_ids, nodes, label_result, resolution, recompute_count, conv_next_index)]


def _build_topic(
    node_ids: list,
    nodes: dict,
    label_result: dict,
    resolution: float,
    recompute_count: int,
    conv_next_index: int,
) -> dict:
    centroid    = _compute_centroid(node_ids, nodes)
    max_index   = max((nodes[n]["index"] for n in node_ids if n in nodes), default=0)
    last_active = max(
        (nodes[n]["timestamp_prompt"] for n in node_ids if n in nodes),
        default=datetime.now(timezone.utc),
    )

    # Temporal override: any node in the last TOPIC_RECOMPUTE_INTERVAL messages → active
    status = label_result.get("status", "dormant")
    if max_index > (conv_next_index - TOPIC_RECOMPUTE_INTERVAL):
        status = "active"

    return {
        "topic_id":           str(uuid.uuid4()),
        "label":              label_result.get("label", "Unlabeled"),
        "description":        label_result.get("description", ""),
        "summary":            label_result.get("summary", ""),
        "coherence":          float(label_result.get("coherence", 0.5)),
        "is_mixed":           bool(label_result.get("is_mixed", False)),
        "sub_themes":         label_result.get("sub_themes", []),
        "status":             status,
        "message_ids":        node_ids,
        "centroid":           centroid,
        "louvain_resolution": resolution,
        "recompute_count":    recompute_count,
        "last_active":        last_active,
    }


# ── Main recompute ────────────────────────────────────────────────────────────

def recompute_topics(conversation_id: str) -> None:
    conn = get_pg()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute(
        """SELECT memory_id::text, index, prompt, response, timestamp_prompt, embedding
           FROM memory_nodes
           WHERE conversation_id = %s::uuid AND status = 'complete' AND embedding IS NOT NULL
           ORDER BY index ASC""",
        (conversation_id,),
    )
    rows = cur.fetchall()

    if len(rows) < TOPIC_MIN_CLUSTER_SIZE:
        print(f"[topic_worker] Not enough nodes ({len(rows)}) for {conversation_id} — skipping")
        cur.close()
        return

    nodes = {
        row["memory_id"]: {
            "memory_id":        row["memory_id"],
            "index":            row["index"],
            "prompt":           row["prompt"],
            "response":         row["response"],
            "timestamp_prompt": row["timestamp_prompt"],
            "embedding":        np.array(row["embedding"], dtype=np.float32),
        }
        for row in rows
    }

    cur.execute(
        "SELECT next_index FROM conversations WHERE conversation_id = %s::uuid",
        (conversation_id,),
    )
    conv_row        = cur.fetchone()
    conv_next_index = conv_row["next_index"] if conv_row else len(rows)

    G = _build_networkx_graph(conversation_id, set(nodes.keys()))

    if G.number_of_edges() == 0:
        print(f"[topic_worker] No edges yet for {conversation_id} — skipping")
        cur.close()
        return

    partition = community_louvain.best_partition(G, resolution=LOUVAIN_DEFAULT_RESOLUTION, weight="weight")

    clusters: dict[int, list] = {}
    for node_id, cid in partition.items():
        clusters.setdefault(cid, []).append(node_id)

    all_topics = []
    for cluster_nodes in clusters.values():
        all_topics.extend(_process_cluster(
            cluster_nodes, nodes, G,
            resolution=LOUVAIN_DEFAULT_RESOLUTION,
            recompute_count=0,
            conv_next_index=conv_next_index,
        ))

    now = datetime.now(timezone.utc)
    try:
        cur.execute("DELETE FROM topics WHERE conversation_id = %s::uuid", (conversation_id,))

        for t in all_topics:
            cur.execute(
                """INSERT INTO topics (
                       topic_id, conversation_id, label, description, summary,
                       coherence, is_mixed, sub_themes, status, message_ids,
                       centroid, louvain_resolution, recompute_count,
                       last_active, created_at, updated_at
                   ) VALUES (
                       %s::uuid, %s::uuid, %s, %s, %s,
                       %s, %s, %s::jsonb, %s, %s::jsonb,
                       %s, %s, %s,
                       %s, %s, %s
                   )""",
                (
                    t["topic_id"], conversation_id,
                    t["label"], t["description"], t["summary"],
                    t["coherence"], t["is_mixed"],
                    json.dumps(t["sub_themes"]),
                    t["status"],
                    json.dumps(t["message_ids"]),
                    t["centroid"],
                    t["louvain_resolution"],
                    t["recompute_count"],
                    t["last_active"],
                    now, now,
                ),
            )

        cur.execute(
            """UPDATE conversations
               SET last_topic_recompute = %s, dirty_topics = '[]'::jsonb
               WHERE conversation_id = %s::uuid""",
            (now, conversation_id),
        )
        conn.commit()
        print(f"[topic_worker] Created {len(all_topics)} topics for {conversation_id}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ── Lambda entrypoint ─────────────────────────────────────────────────────────

def handler(event, context):
    for record in event["Records"]:
        body            = json.loads(record["body"])
        conversation_id = body["conversation_id"]
        try:
            recompute_topics(conversation_id)
        except Exception as e:
            print(f"[topic_worker] ERROR for {conversation_id}: {e}")
            raise   # SQS retries, then DLQ
