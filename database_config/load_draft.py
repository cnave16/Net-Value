"""Load NBA draft results from Basketball-Reference.

Each draft page lists every pick with the drafting team and player. The draft
value model (data_model/draft_value.py) pairs these slots with Chase's fair
values, and the API uses the newest class to estimate rookies' value.

Usage (from the repository root):
    python database_config/load_draft.py --dry-run
    python database_config/load_draft.py --years 2021-2026 --cache-dir /tmp/draft

Draftees are matched to players first by Basketball-Reference ID through the
loaded contracts (exact), then by normalized name. Draftees with no match,
usually players who never reached the NBA, keep a null player_id; no players
rows are created. Each loaded year's rows are replaced in one transaction.
"""

import argparse
import html
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from load_contracts import CRAWL_DELAY, USER_AGENT, name_key  # noqa: E402

load_dotenv()

SOURCE = "https://www.basketball-reference.com/draft/NBA_{}.html"
FIRST_ROUND_PICKS = 30
# Basketball-Reference codes -> our teams.abbreviation where they differ.
TEAM_CODES = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX"}


def parse_draft_page(text):
    """Return picks as dicts: pick, round, team, source_id, name."""
    picks = []
    for row in re.findall(r"<tr >(.*?)</tr>", text, re.S):
        pick = re.search(r'data-stat="pick_overall" csk="(\d+)"', row)
        team = re.search(r'data-stat="team_id" csk="([A-Z]{3})\.', row)
        player = re.search(r"data-stat=\"player\"[^>]*><a href='/players/\w/(\w+)\.html'>([^<]+)</a>", row)
        if pick and team and player:
            number = int(pick.group(1))
            picks.append({
                "pick": number, "round": 1 if number <= FIRST_ROUND_PICKS else 2,
                "team": TEAM_CODES.get(team.group(1), team.group(1)),
                "source_id": player.group(1), "name": html.unescape(player.group(2)).strip(),
            })
    if not picks:
        raise ValueError("No picks parsed; the page layout may have changed.")
    return picks


def fetch(year, cache_dir):
    cached = cache_dir / f"{year}.html" if cache_dir else None
    if cached and cached.exists():
        return cached.read_text(), False
    request = urllib.request.Request(SOURCE.format(year), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8")
    if cached:
        cached.write_text(text)
    return text, True


def year_range(text):
    start, _, end = text.partition("-")
    return list(range(int(start), int(end or start) + 1))


def match_players(cursor, drafts):
    """Map source IDs to player_id: contracts' exact IDs first, then unique names."""
    cursor.execute("SELECT DISTINCT source_player_id, player_id FROM player_contracts")
    by_source = dict(cursor.fetchall())
    cursor.execute("SELECT player_id, first_name || ' ' || last_name FROM players")
    by_key = {}
    for player_id, name in cursor.fetchall():
        by_key.setdefault(name_key(name), []).append(player_id)
    matches = {}
    for picks in drafts.values():
        for p in picks:
            hits = by_key.get(name_key(p["name"]), [])
            matches[p["source_id"]] = by_source.get(p["source_id"]) or (hits[0] if len(hits) == 1 else None)
    return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--years", default="2021-2026", help="e.g. 2021-2026 or 2026")
    parser.add_argument("--dry-run", action="store_true", help="parse and match without writing")
    parser.add_argument("--cache-dir", type=Path, help="reuse and save downloaded pages here")
    args = parser.parse_args()
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        sys.exit("TEST_DATABASE_URL was not found. Define it in your .env file.")
    if args.cache_dir:
        args.cache_dir.mkdir(parents=True, exist_ok=True)

    drafts = {}
    for year in year_range(args.years):
        text, downloaded = fetch(year, args.cache_dir)
        drafts[year] = parse_draft_page(text)
        print(f"  {year}: {len(drafts[year])} picks")
        if downloaded:
            time.sleep(CRAWL_DELAY)
    retrieved_at = datetime.now(timezone.utc)

    connection = psycopg2.connect(url)
    try:
        with connection, connection.cursor() as cursor:
            matches = match_players(cursor, drafts)
            matched = sum(v is not None for v in matches.values())
            print(f"{len(matches)} picks: {matched} matched to players, {len(matches) - matched} not in the database.")
            if args.dry_run:
                print("Dry run: nothing written.")
                return
            cursor.execute("SELECT abbreviation, team_id FROM teams")
            teams = dict(cursor.fetchall())
            for year, picks in drafts.items():
                unknown = sorted({p["team"] for p in picks} - set(teams))
                if unknown:
                    raise ValueError(f"{year}: unknown team codes {unknown}.")
                cursor.execute("DELETE FROM draft_picks WHERE draft_year = %s", (year,))
                for p in picks:
                    cursor.execute(
                        "INSERT INTO draft_picks (draft_year, pick, round, team_id, player_id, "
                        "player_name, source_player_id, source_url, retrieved_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (year, p["pick"], p["round"], teams[p["team"]], matches[p["source_id"]],
                         p["name"], p["source_id"], SOURCE.format(year), retrieved_at),
                    )
        print(f"Loaded {len(matches)} picks for {', '.join(map(str, drafts))}.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
