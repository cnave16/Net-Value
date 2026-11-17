"""Copy a validated pick snapshot between databases, remapping teams by abbreviation.

Dry-run by default. --apply requires a backup directory and only writes this table.
Connection strings come from the chosen env file and are never logged.
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import dotenv_values
from psycopg2.extras import RealDictCursor, execute_values


COLUMNS = ("draft_year", "round", "original_team_id", "owner_team_id", "ownership_type",
           "is_resolved", "pool_id", "notes", "source_url", "retrieved_at")


def remap_snapshot(rows, source_teams, target_teams, first_year, last_year):
    """Reject incomplete snapshots before touching the target database."""
    source = {t["team_id"]: t["abbreviation"] for t in source_teams}
    target = {t["abbreviation"]: t["team_id"] for t in target_teams}
    if len(source) != 30 or set(source.values()) != set(target):
        raise ValueError("Source and target must contain the same 30 NBA teams.")
    counts = Counter((p["draft_year"], p["round"]) for p in rows)
    expected = {(year, rnd): 30 for year in range(first_year, last_year + 1) for rnd in (1, 2)}
    if counts != expected:
        raise ValueError("Expected exactly 30 picks in each year and round of the snapshot.")
    keys, mapped = set(), []
    for row in rows:
        key = (row["draft_year"], row["round"], row["original_team_id"])
        if key in keys or type(row["is_resolved"]) is not bool:
            raise ValueError("Duplicate pick or missing resolution flag.")
        keys.add(key)
        if row["ownership_type"] not in {"owned", "traded", "conditional", "swap_right", "pooled"}:
            raise ValueError("Unknown ownership type.")
        if row["is_resolved"] and row["ownership_type"] not in {"owned", "traded"}:
            raise ValueError("Resolved ownership conflicts with a conditional ownership type.")
        item = {key: row[key] for key in COLUMNS}
        for field in ("original_team_id", "owner_team_id"):
            item[field] = target[source[row[field]]]
        mapped.append(item)
    return mapped


def run(args):
    """Back up first, then atomically create/upsert/verify only pick ownership."""
    cfg = dotenv_values(args.env_file)
    with psycopg2.connect(cfg[args.source_key], connect_timeout=10) as source:
        source.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with source.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SET LOCAL statement_timeout=15000")
            cursor.execute("SELECT team_id, abbreviation FROM teams ORDER BY team_id")
            source_teams = [dict(r) for r in cursor.fetchall()]
            cursor.execute("SELECT * FROM draft_pick_ownership ORDER BY draft_year, round, original_team_id")
            rows = [dict(r) for r in cursor.fetchall()]
    source.close()
    with psycopg2.connect(cfg[args.target_key], connect_timeout=10) as target:
        target.set_session(readonly=not args.apply)
        with target.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SET LOCAL statement_timeout=15000")
            cursor.execute("SET LOCAL lock_timeout=5000")
            cursor.execute("SELECT team_id, abbreviation FROM teams ORDER BY team_id")
            target_teams = [dict(r) for r in cursor.fetchall()]
            mapped = remap_snapshot(rows, source_teams, target_teams, args.first_year, args.last_year)
            cursor.execute("SELECT to_regclass('public.draft_pick_ownership') AS name")
            exists = cursor.fetchone()["name"] is not None
            before = []
            if exists:
                if args.apply:
                    cursor.execute("LOCK TABLE draft_pick_ownership IN SHARE ROW EXCLUSIVE MODE")
                cursor.execute("SELECT * FROM draft_pick_ownership ORDER BY draft_year, round, original_team_id")
                before = [dict(r) for r in cursor.fetchall()]
            report = {"source_rows": len(rows), "target_rows_before": len(before),
                      "resolved": sum(r["is_resolved"] for r in rows), "applied": args.apply}
            if args.apply:
                backup = Path(args.backup_dir)
                backup.mkdir(parents=True, exist_ok=False)
                for name, data in (("source.json", rows), ("target-before.json", before),
                                   ("team-mapping.json", {"source": source_teams, "target": target_teams})):
                    (backup / name).write_text(json.dumps(data, default=str, indent=2) + "\n")
                (backup / "manifest.json").write_text(json.dumps({
                    "created_at": datetime.now(timezone.utc).isoformat(), "table_existed": exists,
                    "source_key": args.source_key, "target_key": args.target_key,
                }, indent=2) + "\n")
                cursor.execute((Path(__file__).parent / "migrations" / "001_draft_pick_ownership.sql").read_text())
                assignments = ", ".join(f"{key}=EXCLUDED.{key}" for key in COLUMNS[3:])
                execute_values(cursor,
                    f"INSERT INTO draft_pick_ownership ({', '.join(COLUMNS)}) VALUES %s "
                    f"ON CONFLICT (draft_year, round, original_team_id) DO UPDATE SET {assignments}",
                    [tuple(r[key] for key in COLUMNS) for r in mapped])
                cursor.execute("SELECT * FROM draft_pick_ownership ORDER BY draft_year, round, original_team_id")
                after = {(r["draft_year"], r["round"], r["original_team_id"]): dict(r) for r in cursor.fetchall()}
                for row in mapped:
                    actual = after[(row["draft_year"], row["round"], row["original_team_id"])]
                    if any(actual[k] != row[k] for k in COLUMNS):
                        raise ValueError("Post-copy verification failed; transaction will roll back.")
                report["target_rows_after"] = len(after)
        # A success report is written only after the transaction commits.
    target.close()
    if args.apply:
        (backup / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--source-key", default="TEST_DATABASE_URL")
    parser.add_argument("--target-key", default="PROD_DATABASE_URL")
    parser.add_argument("--first-year", type=int, default=2027)
    parser.add_argument("--last-year", type=int, default=2033)
    parser.add_argument("--backup-dir")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.backup_dir:
        parser.error("--apply requires --backup-dir pointing to a new directory")
    run(args)
