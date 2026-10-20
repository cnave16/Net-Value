import os
import sys
from contextlib import closing
from dataclasses import dataclass

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Official 2026-27 NBA salary cap and 0-years-of-service minimum salary.
SALARY_CAP_2026_27 = 164_961_000
BASE_SALARY_2026_27 = 1_357_763

NBA_TEAMS = 30
NBA_GAMES = 82
MINUTES_PER_TEAM_GAME = 48 * 5

# Hypotheses that should eventually be calibrated against real contract data.
REPLACEMENT_LEVEL_LEBRON = -1.5
MAX_SALARY_FRACTION = 0.35  # Broad illustrative ceiling; not individual CBA eligibility.
MIN_LEAGUE_MINUTES_COVERAGE = 0.90

@dataclass(frozen=True)
class _PlayerSeason:
    external_id: str
    name: str
    lebron: float
    minutes: float


def _fetch_season_players(cursor, season_end_year):
    """Read one season of league-wide player impact and aggregate traded minutes."""
    if season_end_year is None:
        cursor.execute(
            """
            SELECT s.season_id, s.end_year
            FROM seasons s
            WHERE EXISTS (
                SELECT 1 FROM player_seasons ps
                WHERE ps.season_id = s.season_id
            )
            ORDER BY s.end_year DESC
            LIMIT 1;
            """
        )
    else:
        cursor.execute(
            """
            SELECT s.season_id, s.end_year
            FROM seasons s
            WHERE s.end_year = %s
              AND EXISTS (
                  SELECT 1 FROM player_seasons ps
                  WHERE ps.season_id = s.season_id
              )
            LIMIT 1;
            """,
            (season_end_year,),
        )

    season_row = cursor.fetchone()
    if season_row is None:
        raise ValueError("The database has no player statistics for that season.")
    season_id, end_year = season_row

    cursor.execute(
        """
        SELECT
            p.external_id,
            CONCAT_WS(' ', p.first_name, p.last_name) AS player_name,
            ps.lebron,
            SUM(pts.minutes_played) AS total_minutes
        FROM players p
        JOIN player_seasons ps
            ON ps.player_id = p.player_id
        JOIN player_team_seasons pts
            ON pts.player_season_id = ps.player_season_id
        WHERE ps.season_id = %s
          AND ps.lebron IS NOT NULL
          AND p.external_id IS NOT NULL
        GROUP BY p.external_id, p.first_name, p.last_name, ps.lebron
        HAVING SUM(pts.minutes_played) > 0;
        """,
        (season_id,),
    )

    players = [
        _PlayerSeason(
            external_id=str(external_id).strip(),
            name=name,
            lebron=float(lebron),
            minutes=float(minutes),
        )
        for external_id, name, lebron, minutes in cursor.fetchall()
    ]
    return int(end_year), players

def _compute_salary_allocations(
    players,
    *,
    team_salary_cap=SALARY_CAP_2026_27,
    base_salary=BASE_SALARY_2026_27,
    replacement_lebron=REPLACEMENT_LEVEL_LEBRON,
    max_salary_fraction=MAX_SALARY_FRACTION,
):
    """Distribute the league salary-cap budget in proportion to impact-minutes.

    Replacement impact = max(LEBRON - replacement_lebron, 0) * minutes.
    Each player receives a base amount. The rest of the budget is distributed
    by impact weight, with iterative redistribution when players reach the
    configured individual cap fraction. A 0-weight player gets only the base.
    """
    if not players:
        raise ValueError("No players available for salary valuation.")
    if team_salary_cap <= 0 or base_salary < 0:
        raise ValueError("The cap must be positive and base salary nonnegative.")
    if not (0 < max_salary_fraction <= 1):
        raise ValueError("max_salary_fraction must be in (0, 1].")

    max_salary = team_salary_cap * max_salary_fraction
    if base_salary > max_salary:
        raise ValueError("Base salary exceeds the individual salary ceiling.")

    ids = [player.external_id for player in players]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate player IDs in the selected season.")

    weights = [
        max(player.lebron - replacement_lebron, 0.0) * player.minutes
        for player in players
    ]
    if any(player.minutes < 0 for player in players):
        raise ValueError("Negative player minutes found in the database.")

    league_budget = NBA_TEAMS * team_salary_cap
    unallocated = league_budget - len(players) * base_salary
    if unallocated < 0:
        raise ValueError("Player baselines exceed the league budget.")

    salaries = [float(base_salary)] * len(players)
    active = {i for i, weight in enumerate(weights) if weight > 0}
    max_bonus = max_salary - base_salary

    # 'Water-filling': if a star reaches our broad 35% ceiling, redistribute
    # their excess share among uncapped players rather than losing that money.
    while active and unallocated > 0.01:
        remaining_weight = sum(weights[i] for i in active)
        capped = {
            i
            for i in active
            if unallocated * (weights[i] / remaining_weight) >= max_bonus - 0.01
        }

        if not capped:
            for i in active:
                salaries[i] += unallocated * weights[i] / remaining_weight
            unallocated = 0.0
            break

        for i in capped:
            salaries[i] = max_salary
            unallocated -= max_bonus
        active -= capped

    if unallocated > 1:
        raise ValueError(
            "Could not allocate the league budget. Check that a complete "
            "league dataset was imported."
        )

    return dict(zip(ids, salaries))

def estimate_fair_salary(
    player_id,
    *,
    season_end_year=None,
    database_url=None,
    team_salary_cap=SALARY_CAP_2026_27,
    base_salary=BASE_SALARY_2026_27,
    replacement_lebron=REPLACEMENT_LEVEL_LEBRON,
    max_salary_fraction=MAX_SALARY_FRACTION,
):
    """Estimate a player's fair ANNUAL salary in US dollars (returns int).

    Args:
        player_id: NBA external ID, e.g. "1628401" for Derrick White.
                   (Not the internal players.player_id primary key.)
        season_end_year: Stats season end year, e.g. 2026 for 2025-26.
                         None uses the latest stats season in the database.
        database_url: Optional database URL. Defaults to TEST_DATABASE_URL,
                      then DATABASE_URL from .env / environment.
        team_salary_cap: Annual cap against which value is assessed.
        base_salary: Base annual salary allocated to each sampled player.
        replacement_lebron: LEBRON rating treated as replacement level.
        max_salary_fraction: Broad cap fraction used for a pragmatic ceiling.

    Returns:
        Rounded annual salary in dollars, as an integer.

    Raises:
        LookupError: Player has no playable minutes/LEBRON in that season.
        ValueError: Missing/incomplete seasonal data or bad parameters.
        psycopg2.Error: Database connection or SQL error.

    Note: Estimated values are budget-allocation estimates, not predictions
    from salary-trained regression and not legal individual max contracts.
    """
    external_id = str(player_id).strip()
    if not external_id:
        raise ValueError("player_id cannot be empty.")

    url = database_url or os.getenv("TEST_DATABASE_URL")
    if not url:
        raise ValueError("Set TEST_DATABASE_URL or DATABASE_URL in your .env file.")

    with closing(psycopg2.connect(url)) as connection:
        with connection.cursor() as cursor:
            year, players = _fetch_season_players(cursor, season_end_year)

    # Ensure the valuation isn't drastically inflated by an incomplete import
    # or an in-progress season with only a fraction of NBA games played.
    expected_minutes = NBA_TEAMS * NBA_GAMES * MINUTES_PER_TEAM_GAME
    total_minutes = sum(player.minutes for player in players)
    if total_minutes < expected_minutes * MIN_LEAGUE_MINUTES_COVERAGE:
        raise ValueError(
            f"Season ending {year} has only {total_minutes:,.0f} player "
            f"minutes loaded ({total_minutes / expected_minutes:.1%} of "
            "regulation league minutes). Import a complete regular season "
            "before estimating full-season salaries."
        )

    if not any(player.external_id == external_id for player in players):
        raise LookupError(
            f"Player external ID {external_id!r} has no playable LEBRON "
            f"statistics in the season ending {year}."
        )

    allocations = _compute_salary_allocations(
        players,
        team_salary_cap=team_salary_cap,
        base_salary=base_salary,
        replacement_lebron=replacement_lebron,
        max_salary_fraction=max_salary_fraction,
    )
    return round(allocations[external_id])

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python salary_value.py <NBA_external_player_id>")
        sys.exit(2)

    try:
        salary = estimate_fair_salary(sys.argv[1])
        print(f"Estimated fair annual salary: ${salary:,.0f}")
    except (LookupError, ValueError, psycopg2.Error) as error:
        print(f"Salary estimation failed: {error}", file=sys.stderr)
        sys.exit(1)