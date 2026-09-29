import csv
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
import psycopg2
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
CSV_PATH = BASE_DIR / "player_data" / "2025-2026.csv"

load_dotenv(ENV_PATH)
DATABASE_URL = os.getenv("PROD_DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        f"DATABASE_URL was not found.\n"
        f"Expected .env file at: {ENV_PATH}"
    )

TEAM_ABBREVIATION_MAP = {
    "BRK": "BKN",
    "CHO": "CHA",
    "PHO": "PHX",
}

TEAMS = {
    "ATL": ("Atlanta Hawks", "Atlanta"),
    "BOS": ("Boston Celtics", "Boston"),
    "BKN": ("Brooklyn Nets", "Brooklyn"),
    "CHA": ("Charlotte Hornets", "Charlotte"),
    "CHI": ("Chicago Bulls", "Chicago"),
    "CLE": ("Cleveland Cavaliers", "Cleveland"),
    "DAL": ("Dallas Mavericks", "Dallas"),
    "DEN": ("Denver Nuggets", "Denver"),
    "DET": ("Detroit Pistons", "Detroit"),
    "GSW": ("Golden State Warriors", "San Francisco"),
    "HOU": ("Houston Rockets", "Houston"),
    "IND": ("Indiana Pacers", "Indianapolis"),
    "LAC": ("Los Angeles Clippers", "Los Angeles"),
    "LAL": ("Los Angeles Lakers", "Los Angeles"),
    "MEM": ("Memphis Grizzlies", "Memphis"),
    "MIA": ("Miami Heat", "Miami"),
    "MIL": ("Milwaukee Bucks", "Milwaukee"),
    "MIN": ("Minnesota Timberwolves", "Minneapolis"),
    "NOP": ("New Orleans Pelicans", "New Orleans"),
    "NYK": ("New York Knicks", "New York"),
    "OKC": ("Oklahoma City Thunder", "Oklahoma City"),
    "ORL": ("Orlando Magic", "Orlando"),
    "PHI": ("Philadelphia 76ers", "Philadelphia"),
    "PHX": ("Phoenix Suns", "Phoenix"),
    "POR": ("Portland Trail Blazers", "Portland"),
    "SAC": ("Sacramento Kings", "Sacramento"),
    "SAS": ("San Antonio Spurs", "San Antonio"),
    "TOR": ("Toronto Raptors", "Toronto"),
    "UTA": ("Utah Jazz", "Salt Lake City"),
    "WAS": ("Washington Wizards", "Washington"),
}

REQUIRED_COLUMNS = {
    "nba_id",
    "first_name",
    "last_name",
    "season",
    "team",
    "games_played",
    "minutes_played",
    "lebron",
    "o_lebron",
    "d_lebron",
    "team_wins",
    "team_losses",
}

def clean_text(value):
    if value is None:
        return None

    value = value.strip()

    if value == "":
        return None

    return value


def parse_int(value, field_name, row_number):
    value = clean_text(value)

    if value is None:
        raise ValueError(
            f"Row {row_number}: missing required integer "
            f"'{field_name}'"
        )

    try:
        return int(float(value))

    except ValueError as error:
        raise ValueError(
            f"Row {row_number}: invalid integer for "
            f"'{field_name}': {value}"
        ) from error


def parse_decimal(value, field_name, row_number):
    value = clean_text(value)

    if value is None:
        raise ValueError(
            f"Row {row_number}: missing required number "
            f"'{field_name}'"
        )

    try:
        return Decimal(value)

    except InvalidOperation as error:
        raise ValueError(
            f"Row {row_number}: invalid number for "
            f"'{field_name}': {value}"
        ) from error


def normalize_team(team):
    team = clean_text(team)

    if team is None:
        return None

    team = team.upper()

    return TEAM_ABBREVIATION_MAP.get(team, team)

def get_season_years(row, row_number):
    end_year = parse_int(
        row["season"],
        "season",
        row_number
    )

    start_year = end_year - 1

    return start_year, end_year

def validate_csv_header(fieldnames):
    if not fieldnames:
        raise ValueError(
            "The CSV file does not contain a header row."
        )

    missing_columns = REQUIRED_COLUMNS - set(fieldnames)

    if missing_columns:
        raise ValueError(
            "CSV is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )


def upsert_team(cursor, abbreviation):
    if abbreviation not in TEAMS:
        raise ValueError(
            f"Unknown team abbreviation: {abbreviation}"
        )

    team_name, city = TEAMS[abbreviation]

    cursor.execute(
        """
        INSERT INTO teams (
            abbreviation,
            team_name,
            city
        )
        VALUES (%s, %s, %s)

        ON CONFLICT (abbreviation)
        DO UPDATE SET
            team_name = EXCLUDED.team_name,
            city = EXCLUDED.city

        RETURNING team_id;
        """,
        (
            abbreviation,
            team_name,
            city
        )
    )

    return cursor.fetchone()[0]


def upsert_season(cursor, start_year, end_year):
    cursor.execute(
        """
        INSERT INTO seasons (
            start_year,
            end_year
        )
        VALUES (%s, %s)

        ON CONFLICT (start_year, end_year)
        DO UPDATE SET
            start_year = EXCLUDED.start_year

        RETURNING season_id;
        """,
        (
            start_year,
            end_year
        )
    )

    return cursor.fetchone()[0]


def upsert_player(
    cursor,
    external_id,
    first_name,
    last_name
):
    cursor.execute(
        """
        INSERT INTO players (
            first_name,
            last_name,
            external_id
        )
        VALUES (%s, %s, %s)

        ON CONFLICT (external_id)
        DO UPDATE SET
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name

        RETURNING player_id;
        """,
        (
            first_name,
            last_name,
            external_id
        )
    )

    return cursor.fetchone()[0]


def upsert_player_season(
    cursor,
    player_id,
    season_id,
    lebron,
    offensive_lebron,
    defensive_lebron
):
    cursor.execute(
        """
        INSERT INTO player_seasons (
            player_id,
            season_id,
            lebron,
            offensive_lebron,
            defensive_lebron
        )
        VALUES (%s, %s, %s, %s, %s)

        ON CONFLICT (player_id, season_id)
        DO UPDATE SET
            lebron = EXCLUDED.lebron,
            offensive_lebron = EXCLUDED.offensive_lebron,
            defensive_lebron = EXCLUDED.defensive_lebron

        RETURNING player_season_id;
        """,
        (
            player_id,
            season_id,
            lebron,
            offensive_lebron,
            defensive_lebron
        )
    )

    return cursor.fetchone()[0]


def upsert_player_team_season(
    cursor,
    player_season_id,
    team_id,
    minutes_played,
    games_played
):
    cursor.execute(
        """
        INSERT INTO player_team_seasons (
            player_season_id,
            team_id,
            minutes_played,
            games_played
        )
        VALUES (%s, %s, %s, %s)

        ON CONFLICT (
            player_season_id,
            team_id
        )
        DO UPDATE SET
            minutes_played = EXCLUDED.minutes_played,
            games_played = EXCLUDED.games_played;
        """,
        (
            player_season_id,
            team_id,
            minutes_played,
            games_played
        )
    )


def upsert_team_season(
    cursor,
    team_id,
    season_id,
    wins,
    losses
):
    cursor.execute(
        """
        INSERT INTO team_seasons (
            team_id,
            season_id,
            wins,
            losses
        )
        VALUES (%s, %s, %s, %s)

        ON CONFLICT (
            team_id,
            season_id
        )
        DO UPDATE SET
            wins = EXCLUDED.wins,
            losses = EXCLUDED.losses;
        """,
        (
            team_id,
            season_id,
            wins,
            losses
        )
    )


def import_player_data():
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"Could not find CSV file:\n{CSV_PATH}"
        )

    print("Starting data import...")
    print(f"CSV path: {CSV_PATH}")
    print()

    connection = None

    # These caches prevent unnecessary repeated database queries.
    team_ids = {}
    season_ids = {}
    player_ids = {}
    player_season_ids = {}

    # Used for reporting.
    unique_players = set()
    unique_teams = set()
    unique_seasons = set()

    player_team_rows = 0

    try:
        connection = psycopg2.connect(DATABASE_URL)

        # Important:
        # Nothing is permanently saved until connection.commit().
        connection.autocommit = False

        with connection.cursor() as cursor:

            with open(
                CSV_PATH,
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as csv_file:

                reader = csv.DictReader(csv_file)

                validate_csv_header(reader.fieldnames)

                for row_number, row in enumerate(
                    reader,
                    start=2
                ):

                    # ----------------------------------------
                    # Read player information
                    # ----------------------------------------

                    external_id = clean_text(
                        row["nba_id"]
                    )

                    first_name = clean_text(
                        row["first_name"]
                    )

                    last_name = clean_text(
                        row["last_name"]
                    )

                    if not external_id:
                        raise ValueError(
                            f"Row {row_number}: "
                            "nba_id is missing."
                        )

                    if not first_name:
                        raise ValueError(
                            f"Row {row_number}: "
                            "first_name is missing."
                        )

                    if not last_name:
                        raise ValueError(
                            f"Row {row_number}: "
                            "last_name is missing."
                        )

                    # ----------------------------------------
                    # Team
                    # ----------------------------------------

                    team = normalize_team(
                        row["team"]
                    )

                    if team not in TEAMS:
                        raise ValueError(
                            f"Row {row_number}: "
                            f"unknown team '{team}'"
                        )

                    # ----------------------------------------
                    # Season
                    # ----------------------------------------

                    start_year, end_year = \
                        get_season_years(
                            row,
                            row_number
                        )

                    # ----------------------------------------
                    # Games and minutes
                    # ----------------------------------------

                    games_played = parse_int(
                        row["games_played"],
                        "games_played",
                        row_number
                    )

                    minutes_played = parse_decimal(
                        row["minutes_played"],
                        "minutes_played",
                        row_number
                    )

                    # ----------------------------------------
                    # LEBRON statistics
                    # ----------------------------------------

                    lebron = parse_decimal(
                        row["lebron"],
                        "lebron",
                        row_number
                    )

                    offensive_lebron = parse_decimal(
                        row["o_lebron"],
                        "o_lebron",
                        row_number
                    )

                    defensive_lebron = parse_decimal(
                        row["d_lebron"],
                        "d_lebron",
                        row_number
                    )

                    # ----------------------------------------
                    # Team record
                    # ----------------------------------------

                    wins = parse_int(
                        row["team_wins"],
                        "team_wins",
                        row_number
                    )

                    losses = parse_int(
                        row["team_losses"],
                        "team_losses",
                        row_number
                    )

                    # ----------------------------------------
                    # Validate values
                    # ----------------------------------------

                    if games_played < 0:
                        raise ValueError(
                            f"Row {row_number}: "
                            "games_played cannot be negative."
                        )

                    if minutes_played < 0:
                        raise ValueError(
                            f"Row {row_number}: "
                            "minutes_played cannot be negative."
                        )

                    if wins < 0 or losses < 0:
                        raise ValueError(
                            f"Row {row_number}: "
                            "wins/losses cannot be negative."
                        )

                    if wins + losses != 82:
                        raise ValueError(
                            f"Row {row_number}: "
                            f"{team} record is "
                            f"{wins}-{losses}, "
                            "which does not equal 82 games."
                        )

                    # ========================================
                    # Insert / update team
                    # ========================================

                    if team not in team_ids:
                        team_ids[team] = upsert_team(
                            cursor,
                            team
                        )

                    team_id = team_ids[team]

                    # ========================================
                    # Insert / update season
                    # ========================================

                    season_key = (
                        start_year,
                        end_year
                    )

                    if season_key not in season_ids:
                        season_ids[season_key] = \
                            upsert_season(
                                cursor,
                                start_year,
                                end_year
                            )

                    season_id = \
                        season_ids[season_key]

                    # ========================================
                    # Insert / update player
                    # ========================================

                    if external_id not in player_ids:

                        player_ids[external_id] = \
                            upsert_player(
                                cursor,
                                external_id,
                                first_name,
                                last_name
                            )

                    player_id = \
                        player_ids[external_id]

                    # ========================================
                    # Insert / update player season
                    # ========================================

                    player_season_key = (
                        player_id,
                        season_id
                    )

                    if (
                        player_season_key
                        not in player_season_ids
                    ):

                        player_season_ids[
                            player_season_key
                        ] = upsert_player_season(
                            cursor,
                            player_id,
                            season_id,
                            lebron,
                            offensive_lebron,
                            defensive_lebron
                        )

                    player_season_id = \
                        player_season_ids[
                            player_season_key
                        ]

                    # ========================================
                    # Insert player/team/season data
                    # ========================================

                    upsert_player_team_season(
                        cursor,
                        player_season_id,
                        team_id,
                        minutes_played,
                        games_played
                    )

                    # ========================================
                    # Insert team season record
                    # ========================================

                    upsert_team_season(
                        cursor,
                        team_id,
                        season_id,
                        wins,
                        losses
                    )

                    # ----------------------------------------
                    # Keep track of totals
                    # ----------------------------------------

                    unique_players.add(
                        external_id
                    )

                    unique_teams.add(
                        team
                    )

                    unique_seasons.add(
                        season_key
                    )

                    player_team_rows += 1

        # ====================================================
        # Everything succeeded — save the transaction.
        # ====================================================

        connection.commit()

        print()
        print("===================================")
        print("Import completed successfully")
        print("===================================")
        print(
            f"Unique players: "
            f"{len(unique_players)}"
        )
        print(
            f"Player-team-season rows: "
            f"{player_team_rows}"
        )
        print(
            f"Teams: "
            f"{len(unique_teams)}"
        )
        print(
            f"Seasons: "
            f"{len(unique_seasons)}"
        )

    except Exception as error:

        # If even one row fails, undo the entire import.
        if connection is not None:
            connection.rollback()

        print()
        print("===================================")
        print("IMPORT FAILED")
        print("===================================")
        print(
            "No changes from this import "
            "were saved to the database."
        )
        print()
        print(f"Error: {error}")

        raise

    finally:

        if connection is not None:
            connection.close()


if __name__ == "__main__":

    try:
        import_player_data()

    except Exception:
        sys.exit(1)