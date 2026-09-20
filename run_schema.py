import asyncio
import asyncpg
import pathlib

# Fill these in before running
RDS_HOST = "graphmem-db.cchco0ei6wzx.us-east-1.rds.amazonaws.com"  # your RDS endpoint
RDS_PORT = 5432
RDS_DB   = "graphmem"
RDS_USER = "graphmem"
RDS_PASS = "avik.0x01"  # password you set during RDS creation


async def run():
    # Step 1 — connect to default postgres db and create graphmem db
    print("Connecting to RDS (postgres db)...")
    conn = await asyncpg.connect(
        host=RDS_HOST, port=RDS_PORT,
        database="postgres", user=RDS_USER, password=RDS_PASS,
    )
    await conn.execute(f'CREATE DATABASE "{RDS_DB}"')
    await conn.close()
    print(f"Database '{RDS_DB}' created.")

    # Step 2 — connect to graphmem db and run schema
    print("Connecting to graphmem db...")
    conn = await asyncpg.connect(
        host=RDS_HOST, port=RDS_PORT,
        database=RDS_DB, user=RDS_USER, password=RDS_PASS,
    )
    print("Running schema...")
    sql = pathlib.Path("api/db/schema.sql").read_text()
    await conn.execute(sql)
    await conn.close()
    print("Done — all tables created successfully.")


asyncio.run(run())
