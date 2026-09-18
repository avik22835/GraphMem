import os
import json
import numpy as np
import httpx
import psycopg2
import psycopg2.extras
import boto3
from pgvector.psycopg2 import register_vector
from gremlin_python.driver import client, serializer

# ── Module-level connections (reused across warm Lambda invocations) ──────────

_pg_conn = None
_neptune_client = None
_sqs = boto3.client("sqs", region_name=os.environ["AWS_REGION"])

THRESHOLD = float(os.environ.get("DEFAULT_THRESHOLD", "0.4"))
TOPIC_INTERVAL = int(os.environ.get("TOPIC_RECOMPUTE_INTERVAL", "20"))
SQS_TOPIC_QUEUE_URL = os.environ["SQS_TOPIC_QUEUE_URL"]


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


def get_neptune():
    global _neptune_client
    if _neptune_client is None:
        endpoint = os.environ["NEPTUNE_ENDPOINT"]
        port = os.environ["NEPTUNE_PORT"]
        _neptune_client = client.Client(
            f"wss://{endpoint}:{port}/gremlin",
            "g",
            message_serializer=serializer.GraphSONSerializersV2d0(),
        )
    return _neptune_client


# ── Jina embedding ────────────────────────────────────────────────────────────

def embed(text: str) -> np.ndarray:
    resp = httpx.post(
        "https://api.jina.ai/v1/embeddings",
        headers={"Authorization": f"Bearer {os.environ['JINA_API_KEY']}"},
        json={
            "model": "jina-embeddings-v4",
            "input": [text],
            "task": "retrieval.passage",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    vec = np.array(resp.json()["data"][0]["embedding"], dtype=np.float32)
    # Normalise to unit vector — ensures pgvector cosine distance = 1 - cosine_similarity
    return vec / np.linalg.norm(vec)


# ── Neptune helpers ───────────────────────────────────────────────────────────

def add_vertex(memory_id: str, conversation_id: str) -> None:
    get_neptune().submit(
        "g.addV('memory_node')"
        ".property('memory_id', mid)"
        ".property('conversation_id', cid)",
        {"mid": memory_id, "cid": conversation_id},
    ).all().result()


def add_edge_pair(src_id: str, dst_id: str, weight: float, conversation_id: str) -> None:
    nc = get_neptune()
    # src → dst
    nc.submit(
        "g.V().has('memory_node','memory_id',src).as('a')"
        ".V().has('memory_node','memory_id',dst)"
        ".addE('similar_to').from('a')"
        ".property('weight',w).property('conversation_id',cid)",
        {"src": src_id, "dst": dst_id, "w": weight, "cid": conversation_id},
    ).all().result()
    # dst → src (bidirectional)
    nc.submit(
        "g.V().has('memory_node','memory_id',dst).as('a')"
        ".V().has('memory_node','memory_id',src)"
        ".addE('similar_to').from('a')"
        ".property('weight',w).property('conversation_id',cid)",
        {"src": src_id, "dst": dst_id, "w": weight, "cid": conversation_id},
    ).all().result()


# ── Core processing ───────────────────────────────────────────────────────────

def process_node(memory_id: str, conversation_id: str) -> None:
    conn = get_pg()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # 1. Fetch complete node from RDS
    cur.execute(
        "SELECT prompt, response FROM memory_nodes WHERE memory_id = %s AND status = 'complete'",
        (memory_id,),
    )
    row = cur.fetchone()
    if not row:
        print(f"[node_worker] Node {memory_id} not found or not complete — skipping")
        return

    # 2. Embed prompt + response as one semantic unit
    text = (row["prompt"] or "") + " " + (row["response"] or "")
    embedding = embed(text.strip())

    # 3. Write embedding to pgvector
    cur.execute(
        "UPDATE memory_nodes SET embedding = %s WHERE memory_id = %s",
        (embedding, memory_id),
    )
    conn.commit()

    # 4. Insert Neptune vertex
    add_vertex(memory_id, conversation_id)

    # 5. Find all existing complete nodes with similarity >= threshold
    cur.execute(
        """SELECT memory_id::text, 1 - (embedding <=> %s) AS sim
           FROM memory_nodes
           WHERE conversation_id = %s::uuid
             AND status = 'complete'
             AND memory_id != %s::uuid
             AND embedding <=> %s <= %s""",
        (embedding, conversation_id, memory_id, embedding, 1 - THRESHOLD),
    )
    neighbours = cur.fetchall()

    # 6. Insert bidirectional Neptune edges for each neighbour above threshold
    for n in neighbours:
        add_edge_pair(
            src_id=memory_id,
            dst_id=n["memory_id"],
            weight=float(n["sim"]),
            conversation_id=conversation_id,
        )

    # 7. Increment node_count on conversation (only after full graph insertion)
    cur.execute(
        """UPDATE conversations
           SET node_count = node_count + 1
           WHERE conversation_id = %s::uuid
           RETURNING node_count""",
        (conversation_id,),
    )
    result = cur.fetchone()
    conn.commit()
    node_count = result["node_count"]

    # 8. Trigger topic recompute every N nodes
    if node_count % TOPIC_INTERVAL == 0:
        _sqs.send_message(
            QueueUrl=SQS_TOPIC_QUEUE_URL,
            MessageBody=json.dumps({"conversation_id": conversation_id}),
        )
        print(f"[node_worker] Triggered topic recompute at node_count={node_count}")

    cur.close()
    print(f"[node_worker] Processed node {memory_id} — {len(neighbours)} edges inserted")


# ── Lambda entrypoint ─────────────────────────────────────────────────────────

def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        memory_id = body["memory_id"]
        conversation_id = body["conversation_id"]
        try:
            process_node(memory_id, conversation_id)
        except Exception as e:
            print(f"[node_worker] ERROR processing {memory_id}: {e}")
            raise  # Re-raise so SQS retries (up to 3 times), then DLQ
