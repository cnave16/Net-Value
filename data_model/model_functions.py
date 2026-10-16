import os
import psycopg2
from dotenv import load_dotenv
from project_wins import get_roster_data, project_wins

load_dotenv()

# Global database URL so all helper functions can use it
db_url = os.getenv("TEST_DATABASE_URL")


def get_team_player_ids(team_id):
    connection = None
    cursor = None

    try:
        connection = psycopg2.connect(db_url)
        cursor = connection.cursor()

        query = """
            SELECT DISTINCT p.external_id
            FROM players p
            JOIN player_seasons ps
                ON p.player_id = ps.player_id
            JOIN player_team_seasons pts
                ON ps.player_season_id = pts.player_season_id
            WHERE pts.team_id = %s;
        """

        cursor.execute(query, (team_id,))
        rows = cursor.fetchall()

        return [row[0] for row in rows]

    except Exception as error:
        print(f"Error retrieving players for team {team_id}: {error}")
        return []

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

def get_team_id(team_abbreviation):
    connection = None
    cursor = None

    try:
        connection = psycopg2.connect(db_url)
        cursor = connection.cursor()

        query = """
            SELECT team_id
            FROM teams
            WHERE UPPER(abbreviation) = UPPER(%s);
        """

        cursor.execute(query, (team_abbreviation,))
        row = cursor.fetchone()

        if row:
            return row[0]

        return None

    except Exception as error:
        print(f"Error retrieving team ID for {team_abbreviation}: {error}")
        return None

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

def compile_new_roster(current_roster, players_to_remove, players_to_add):
    # Remove requested players
    new_roster = [
        player_id
        for player_id in current_roster
        if player_id not in players_to_remove
    ]

    # Add new players, avoiding duplicates
    for player_id in players_to_add:
        if player_id not in new_roster:
            new_roster.append(player_id)

    return new_roster

def main():
    team_abbreviation = "PHI"

    # Get Philadelphia's team ID
    team_id = get_team_id(team_abbreviation)

    if team_id is None:
        print(f"Could not find team: {team_abbreviation}")
        return

    print(f"{team_abbreviation} has team ID {team_id}")

    # Pull the 2025-26 roster from our database
    current_roster = get_team_player_ids(team_id)

    if not current_roster:
        print("No players found for this team.")
        return

    print(f"\n2025-26 roster contains {len(current_roster)} players:")
    for player_id in current_roster:
        print(player_id)

    # Players who are no longer on Philadelphia's standard roster
    departures = {
        "Jared McCain": "1642272",
        "Quentin Grimes": "1629656",
        "Kelly Oubre Jr.": "1626162",
        "Andre Drummond": "203083",
        "Paul George": "202331",
        "Trendon Watford": "1630570",
        "Cameron Payne": "1626166",
        "Dalen Terry": "1631207",
        "Tyrese Martin": "1631213"
    }

    # Players added to Philadelphia for 2026-27
    additions = {
        "Labaron Philon": "1642889",
        "Jaylen Brown": "1627759",
        "Kentavious Caldwell-Pope": "203484",
        "Anfernee Simons": "1629014",
        "LeBron James": "2544",
        "Dean Wade": "1629731",
        "Ariel Hukporti": "1630574"
    }

    players_to_remove = list(departures.values())
    players_to_add = list(additions.values())

    # Show which departure IDs were actually present in our database roster
    print("\nPlayers being removed:")

    for name, player_id in departures.items():
        if player_id in current_roster:
            print(f"{name}: {player_id}")

    print("\nPlayers being added:")

    for name, player_id in additions.items():
        print(f"{name}: {player_id}")

    # Construct the new roster
    new_roster = compile_new_roster(
        current_roster,
        players_to_remove,
        players_to_add
    )

    print(f"\nProjected 2026-27 roster contains {len(new_roster)} players:")

    # Pull the statistical data for the newly constructed roster
    connection = psycopg2.connect(db_url)

    roster_data = get_roster_data(connection, new_roster)

    connection.close()

    # Project the team's wins using the updated roster
    results = project_wins(roster_data)

    print(
        f"\nProjected 2026-27 wins for the Philadelphia 76ers: "
        f"{results['projected_wins']:.1f}"
    )


if __name__ == "__main__":
    main()