#!/usr/bin/env python3
"""
Migrate specific run IDs from local SQLite to Cloud SQL (staging).

Usage:
  python3 scripts/migrate_runs.py --run-ids 102 103 104

Requires:
  pip3 install psycopg2-binary
  Cloud SQL Auth Proxy running on localhost:5432
  or: gcloud sql connect aeo-db-stg --user=postgres --project=aeo-insights-stg
"""
import argparse
import json
import sqlite3
import sys

try:
    import psycopg2
except ImportError:
    print("Run: pip3 install psycopg2-binary")
    sys.exit(1)

parser = argparse.ArgumentParser()
parser.add_argument("--run-ids", nargs="+", type=int, required=True)
parser.add_argument("--sqlite",  default="data/db.sqlite")
parser.add_argument("--pg-host", default="127.0.0.1")
parser.add_argument("--pg-port", default="5432")
parser.add_argument("--pg-db",   default="postgres")
parser.add_argument("--pg-user", default="postgres")
parser.add_argument("--pg-pass", default="")
args = parser.parse_args()

# ── Read from SQLite ──────────────────────────────────────────────────────────
src = sqlite3.connect(args.sqlite)
src.row_factory = sqlite3.Row

placeholders = ",".join("?" * len(args.run_ids))
runs = src.execute(
    f"SELECT * FROM runs WHERE id IN ({placeholders}) ORDER BY id",
    args.run_ids,
).fetchall()

results = src.execute(
    f"SELECT * FROM results WHERE run_id IN ({placeholders}) ORDER BY id",
    args.run_ids,
).fetchall()

print(f"Found {len(runs)} runs, {len(results)} results in SQLite")

# ── Write to PostgreSQL ───────────────────────────────────────────────────────
pg = psycopg2.connect(
    host=args.pg_host, port=args.pg_port,
    dbname=args.pg_db, user=args.pg_user, password=args.pg_pass,
)
cur = pg.cursor()

inserted_runs = 0
for r in runs:
    cur.execute("""
        INSERT INTO runs (prompt_id, triggered_at, status, session_id, collection_method)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (r["prompt_id"], r["triggered_at"], r["status"], r["session_id"], r["collection_method"]))
    new_run_id = cur.fetchone()[0]

    # Insert matching results
    for res in [x for x in results if x["run_id"] == r["id"]]:
        cur.execute("""
            INSERT INTO results (run_id, llm, raw_response, mentioned, position_score,
                                 sentiment, competitors_mentioned, error, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            new_run_id,
            res["llm"],
            res["raw_response"],
            bool(res["mentioned"]),
            res["position_score"],
            res["sentiment"],
            res["competitors_mentioned"],
            res["error"],
            res["latency_ms"],
        ))

    inserted_runs += 1
    print(f"  ✓ Run {r['id']} → new id {new_run_id} (prompt {r['prompt_id']})")

pg.commit()
cur.close()
pg.close()
src.close()

print(f"\nDone — migrated {inserted_runs} runs to Cloud SQL staging")
