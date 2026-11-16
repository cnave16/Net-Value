"""Fill missing NBA person IDs (players.external_id) from Wikidata.

Players created by load_contracts.py (mostly rookies) have no NBA ID, so the
frontend can't show their headshot. Wikidata records NBA.com player IDs
(property P3647) and offers a public query service for this kind of lookup.

Usage (from the repository root):
    python database_config/load_nba_ids.py --dry-run
    python database_config/load_nba_ids.py

Safeguards, since Wikidata includes retired players who may share a name:
- A name must match exactly one Wikidata player (after normalization).
- Anyone drafted since MODERN_DRAFT_YEAR must match a recent ID (>= MODERN_ID).
- An ID already used by another player is never reused (also a DB constraint).
Only players with no external_id are updated; existing IDs are never changed.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from load_contracts import name_key  # noqa: E402

load_dotenv()

ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "NetValue-student-project/0.1 (NBA ID lookup for headshots)"
QUERY = 'SELECT ?nba ?label WHERE { ?p wdt:P3647 ?nba; rdfs:label ?label . FILTER(LANG(?label) = "en") }'
# Recent draftees have IDs from about 1627000 up (some get one before the
# draft, e.g. from the G League); older IDs belong to earlier players.
MODERN_DRAFT_YEAR = 2021
MODERN_ID = 1627000


def wikidata_ids():
    """{normalized name: {nba_id, ...}} for every Wikidata entry with an NBA ID."""
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": QUERY})
    request = urllib.request.Request(url, headers={
        "Accept": "application/sparql-results+json", "User-Agent": USER_AGENT,
    })
    with urllib.request.urlopen(request, timeout=90) as response:
        rows = json.load(response)["results"]["bindings"]
    ids = {}
    for row in rows:
        if row["nba"]["value"].isdigit():
            ids.setdefault(name_key(row["label"]["value"]), set()).add(row["nba"]["value"])
    return ids


def choose_ids(missing, ids, used):
    """Pick an ID per player, or a reason it was skipped.

    missing: (player_id, name, latest draft year or None) tuples.
    used: {nba_id: name of the player who already has it}.
    """
    chosen, skipped = {}, []
    for player_id, name, draft_year in missing:
        candidates = ids.get(name_key(name), set())
        if draft_year is not None and draft_year >= MODERN_DRAFT_YEAR:
            candidates = {c for c in candidates if int(c) >= MODERN_ID}
        taken = candidates & set(used)
        if len(candidates) == 1 and taken:
            owner = used[taken.pop()]
            skipped.append((name, f"duplicate of existing player {owner!r}; add a NAME_ALIASES entry"))
            continue
        candidates -= set(used)
        if len(candidates) != 1:
            skipped.append((name, "no match" if not candidates else "ambiguous"))
            continue
        nba_id = candidates.pop()
        chosen[player_id] = nba_id
        used[nba_id] = name
    return chosen, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="match without writing")
    args = parser.parse_args()
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        sys.exit("TEST_DATABASE_URL was not found. Define it in your .env file.")

    print("Querying Wikidata for NBA player IDs...")
    ids = wikidata_ids()
    connection = psycopg2.connect(url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT external_id, first_name || ' ' || last_name FROM players "
                           "WHERE external_id IS NOT NULL")
            used = dict(cursor.fetchall())
            cursor.execute(
                "SELECT p.player_id, p.first_name || ' ' || p.last_name, MAX(d.draft_year) "
                "FROM players p LEFT JOIN draft_picks d ON d.player_id = p.player_id "
                "WHERE p.external_id IS NULL GROUP BY p.player_id ORDER BY p.player_id"
            )
            missing = cursor.fetchall()
            chosen, skipped = choose_ids(missing, ids, used)
            print(f"{len(missing)} players without an NBA ID: {len(chosen)} found, {len(skipped)} skipped.")
            for name, reason in skipped:
                print(f"  skipped {name}: {reason}")
            if args.dry_run:
                print("Dry run: nothing written.")
                return
            for player_id, nba_id in chosen.items():
                cursor.execute(
                    "UPDATE players SET external_id = %s WHERE player_id = %s AND external_id IS NULL",
                    (nba_id, player_id),
                )
        print(f"Saved {len(chosen)} NBA IDs.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
