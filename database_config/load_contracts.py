"""Load current NBA rosters and cap salaries from Basketball-Reference.

Each team's contracts page lists the players under contract and their salary for
the upcoming or current season (the first salary column). That gives one
current team per player, which the trade simulator uses as its roster, and the
cap salary the valuation and payroll figures use.

Usage (from the repository root):
    python database_config/load_contracts.py --dry-run
    python database_config/load_contracts.py --cache-dir /tmp/bref

--dry-run parses and matches without writing. --cache-dir reuses downloaded
pages (and saves new ones) so reruns do not hit the site again. Requests are
spaced CRAWL_DELAY seconds apart, matching the site's robots.txt.

Players are matched to existing rows by normalized name (case, accents,
punctuation and suffixes such as Jr. or III ignored). Contract players with no
match, such as rookies, get a new players row without an NBA external ID. The
season's contracts and cap sheets are replaced in one transaction, so a player
who left the league no longer appears on a roster.
"""

import argparse
import html
import os
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

SEASON_START_YEAR = 2026
SOURCE = "https://www.basketball-reference.com/contracts/{}.html"
CRAWL_DELAY = 4
USER_AGENT = "Mozilla/5.0 (compatible; NetValue student project)"

# Basketball-Reference page code -> our teams.abbreviation, where they differ.
SOURCE_TEAMS = {
    "ATL": "ATL", "BOS": "BOS", "BRK": "BKN", "CHO": "CHA", "CHI": "CHI",
    "CLE": "CLE", "DAL": "DAL", "DEN": "DEN", "DET": "DET", "GSW": "GSW",
    "HOU": "HOU", "IND": "IND", "LAC": "LAC", "LAL": "LAL", "MEM": "MEM",
    "MIA": "MIA", "MIL": "MIL", "MIN": "MIN", "NOP": "NOP", "NYK": "NYK",
    "OKC": "OKC", "ORL": "ORL", "PHI": "PHI", "PHO": "PHX", "POR": "POR",
    "SAC": "SAC", "SAS": "SAS", "TOR": "TOR", "UTA": "UTA", "WAS": "WAS",
}


# Source names that differ from ours by more than formatting, after name_key.
# Found by load_nba_ids.py, which reports a player whose NBA ID already
# belongs to another row (a duplicate created by a missed match).
NAME_ALIASES = {
    "ron holland": "ronald holland",
}


def name_key(name):
    """Normalize a name for matching: 'Ronald Holland II' == 'Ronald Holland Ii'."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[.'’\-]", "", name)
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    name = " ".join(name.split())
    return NAME_ALIASES.get(name, name)


def money(text):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def two_way_names(text):
    """Names whose payroll note mentions a two-way contract."""
    notes = text[text.find('id="payroll-notes"'):]
    notes = notes[:notes.find("</table>")]
    names = set()
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", notes, re.S):
        player = re.search(r'data-stat="player"[^>]*>(?:<a [^>]*>)?([^<]+)', row)
        if player and re.search(r"two-way", re.sub(r"<[^>]+>", " ", row), re.I):
            names.add(html.unescape(player.group(1)).strip())
    return names


LATER_SEASONS = 3  # salary columns after the current season (y2-y4) to keep


def cell_salary(row, stat):
    """Salary in one column, or None if blank. Prefer the numeric sort key,
    since the text can be wrapped in <em> (non-guaranteed)."""
    cell = re.search(rf'<td[^>]*data-stat="{stat}"([^>]*)>(.*?)</td>', row, re.S)
    if not cell:
        return None
    sort_key = re.search(r'csk="(\d+)"', cell.group(1))
    return int(sort_key.group(1)) if sort_key else money(re.sub(r"<[^>]+>", "", cell.group(2)))


def parse_contracts_page(text):
    """Return (players, team_total).

    Each player has source_id, name, salary, later_salaries (the next seasons;
    None where the contract has ended or the source lists nothing) and
    contract_type. A blank salary is a two-way contract only when the payroll
    note says so; otherwise the salary is unknown (None) and the team's payroll
    is reported as incomplete.
    """
    two_way = two_way_names(text)
    table = text[text.find('id="contracts"'):]
    table = table[:table.find("</table>")]
    if not table:
        raise ValueError("Contracts table not found; the page layout may have changed.")
    players, team_total = [], None
    for row in re.findall(r"<tr\s*>(.*?)</tr>", table, re.S):
        salary = cell_salary(row, "y1")
        player = re.search(r'data-stat="player" csk="([^"]+)" ><a [^>]*>([^<]+)</a>', row)
        if player:
            name = html.unescape(player.group(2)).strip()
            is_two_way = salary is None and name in two_way
            players.append({
                "source_id": player.group(1), "name": name,
                "salary": 0 if is_two_way else salary,
                "later_salaries": [] if is_two_way else [
                    cell_salary(row, f"y{season}") for season in range(2, LATER_SEASONS + 2)
                ],
                "contract_type": "two_way" if is_two_way else "standard",
            })
        elif "Team Totals" in row:
            team_total = salary
    if not players or team_total is None:
        raise ValueError("No players or team total parsed; the page layout may have changed.")
    return players, team_total


def fetch(code, cache_dir):
    cached = cache_dir / f"{code}.html" if cache_dir else None
    if cached and cached.exists():
        return cached.read_text(), False
    request = urllib.request.Request(SOURCE.format(code), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8")
    if cached:
        cached.write_text(text)
    return text, True


def collect(cache_dir):
    """Download (or read) and parse every team page."""
    pages = {}
    for code in SOURCE_TEAMS:
        text, downloaded = fetch(code, cache_dir)
        pages[code] = parse_contracts_page(text)
        print(f"  {code}: {len(pages[code][0])} players")
        if downloaded:
            time.sleep(CRAWL_DELAY)
    seen = {}
    for code, (players, _) in pages.items():
        for p in players:
            if p["source_id"] in seen:
                raise ValueError(f"{p['name']} is listed by both {seen[p['source_id']]} and {code}.")
            seen[p["source_id"]] = code
    return pages


def match_players(cursor, pages):
    """Map each source player to a players.player_id, or None if new."""
    cursor.execute("SELECT player_id, first_name || ' ' || last_name FROM players")
    by_key = {}
    for player_id, name in cursor.fetchall():
        by_key.setdefault(name_key(name), []).append(player_id)
    matches, ambiguous = {}, []
    for players, _ in pages.values():
        for p in players:
            hits = by_key.get(name_key(p["name"]), [])
            if len(hits) > 1:
                ambiguous.append(p["name"])
            matches[p["source_id"]] = hits[0] if len(hits) == 1 else None
    if ambiguous:
        raise ValueError(f"Names match more than one database player: {sorted(ambiguous)}.")
    return matches


def load(cursor, pages, matches, retrieved_at):
    cursor.execute("SELECT abbreviation, team_id FROM teams")
    teams = dict(cursor.fetchall())
    missing = sorted(set(SOURCE_TEAMS.values()) - set(teams))
    if missing:
        raise ValueError(f"Teams missing from the database: {missing}.")

    cursor.execute("DELETE FROM player_contracts WHERE season_start_year = %s", (SEASON_START_YEAR,))
    cursor.execute("DELETE FROM team_cap_sheets WHERE season_start_year = %s", (SEASON_START_YEAR,))
    created = 0
    for code, (players, team_total) in pages.items():
        team_id, url = teams[SOURCE_TEAMS[code]], SOURCE.format(code)
        cursor.execute(
            "INSERT INTO team_cap_sheets (season_start_year, team_id, source_total_salary, "
            "source_url, retrieved_at) VALUES (%s, %s, %s, %s, %s)",
            (SEASON_START_YEAR, team_id, team_total, url, retrieved_at),
        )
        for p in players:
            player_id = matches[p["source_id"]]
            if player_id is None:
                first, _, last = p["name"].partition(" ")
                cursor.execute(
                    "INSERT INTO players (first_name, last_name) VALUES (%s, %s) RETURNING player_id",
                    (first, last or first),
                )
                player_id = cursor.fetchone()[0]
                matches[p["source_id"]] = player_id
                created += 1
            cursor.execute(
                "INSERT INTO player_contracts (season_start_year, player_id, team_id, cap_salary, "
                "later_salaries, contract_type, source_player_id, source_url, retrieved_at) "
                "VALUES (%s, %s, %s, %s, %s::numeric[], %s, %s, %s, %s)",
                (SEASON_START_YEAR, player_id, team_id, p["salary"], p["later_salaries"],
                 p["contract_type"], p["source_id"], url, retrieved_at),
            )
    return created


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="parse and match without writing")
    parser.add_argument("--cache-dir", type=Path, help="reuse and save downloaded pages here")
    args = parser.parse_args()
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        sys.exit("TEST_DATABASE_URL was not found. Define it in your .env file.")
    if args.cache_dir:
        args.cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading {SEASON_START_YEAR}-{str(SEASON_START_YEAR + 1)[-2:]} contracts...")
    pages = collect(args.cache_dir)
    retrieved_at = datetime.now(timezone.utc)

    connection = psycopg2.connect(url)
    try:
        with connection, connection.cursor() as cursor:
            matches = match_players(cursor, pages)
            total = len(matches)
            new = sum(player_id is None for player_id in matches.values())
            listed = [p for players, _ in pages.values() for p in players]
            two_way = sum(p["contract_type"] == "two_way" for p in listed)
            unknown = [p["name"] for p in listed if p["salary"] is None]
            print(f"{total} contracts: {total - new} matched, {new} new players, {two_way} two-way.")
            if unknown:
                print(f"Salary not listed yet for {len(unknown)}: {', '.join(unknown)}.")
            if args.dry_run:
                print("Dry run: nothing written.")
                return
            created = load(cursor, pages, matches, retrieved_at)
        print(f"Loaded {total} contracts for 30 teams; created {created} players.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
