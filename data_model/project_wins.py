import os
import math
import psycopg2
from dotenv import load_dotenv

INTERCEPT = -6.7976
TEAM_LEBRON_COEF = 7.2448
TOP10_STD_COEF = 9.6252
POSITIVE_SHARE_COEF = 9.0796
TOP3_SHARE_COEF = 86.2970

def connect_to_database():
    load_dotenv()

    database_url = os.getenv("TEST_DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL was not found in the .env file.")

    return psycopg2.connect(database_url)

def get_roster_data(connection, player_ids):
    query = """
        SELECT
            p.player_id,
            p.external_id,
            ps.lebron,
            COALESCE(SUM(pts.minutes_played), 0) AS minutes_played
        FROM players p

        JOIN player_seasons ps
            ON p.player_id = ps.player_id

        JOIN seasons s
            ON ps.season_id = s.season_id

        LEFT JOIN player_team_seasons pts
            ON ps.player_season_id = pts.player_season_id

        WHERE p.external_id = ANY(%s)

        AND s.season_id = (
            SELECT MAX(s2.season_id)
            FROM player_seasons ps2
            JOIN seasons s2
                ON ps2.season_id = s2.season_id
            WHERE ps2.player_id = p.player_id
        )

        GROUP BY
            p.player_id,
            p.external_id,
            ps.lebron;
    """

    with connection.cursor() as cursor:
        cursor.execute(query, (player_ids,))
        rows = cursor.fetchall()

    roster = []

    for row in rows:
        roster.append({
            "player_id": row[0],
            "external_id": row[1],
            "lebron": float(row[2]),
            "minutes": float(row[3])
        })

    return roster

def calculate_team_lebron(roster):
    total_minutes = sum(player["minutes"] for player in roster)

    if total_minutes == 0:
        return 0

    weighted_lebron = sum(
        player["lebron"] * player["minutes"]
        for player in roster
    )

    return weighted_lebron / total_minutes

def calculate_top10_weighted_std(roster):
    top10 = sorted(
        roster,
        key=lambda player: player["minutes"],
        reverse=True
    )[:10]

    total_minutes = sum(player["minutes"] for player in top10)

    if total_minutes == 0:
        return 0

    weighted_mean = sum(
        player["lebron"] * player["minutes"]
        for player in top10
    ) / total_minutes

    weighted_variance = sum(
        player["minutes"] *
        ((player["lebron"] - weighted_mean) ** 2)
        for player in top10
    ) / total_minutes

    return math.sqrt(weighted_variance)

def calculate_positive_minute_share(roster):
    total_minutes = sum(player["minutes"] for player in roster)

    if total_minutes == 0:
        return 0

    positive_minutes = sum(
        player["minutes"]
        for player in roster
        if player["lebron"] > 0
    )

    return positive_minutes / total_minutes

def calculate_top3_minute_share(roster):
    total_minutes = sum(player["minutes"] for player in roster)

    if total_minutes == 0:
        return 0

    top3 = sorted(
        roster,
        key=lambda player: player["minutes"],
        reverse=True
    )[:3]

    top3_minutes = sum(
        player["minutes"]
        for player in top3
    )

    return top3_minutes / total_minutes

def project_wins(roster):
    team_lebron = calculate_team_lebron(roster)

    top10_std = calculate_top10_weighted_std(roster)

    positive_share = calculate_positive_minute_share(roster)

    top3_share = calculate_top3_minute_share(roster)

    projected_wins = (
        INTERCEPT
        + TEAM_LEBRON_COEF * team_lebron
        + TOP10_STD_COEF * top10_std
        + POSITIVE_SHARE_COEF * positive_share
        + TOP3_SHARE_COEF * top3_share
    )

    projected_wins = max(0, min(82, projected_wins))

    return {
        "projected_wins": projected_wins,
        "team_lebron": team_lebron,
        "top10_std": top10_std,
        "positive_share": positive_share,
        "top3_share": top3_share
    }

def main():
    player_ids = ["1627936","1628366","1628368","1628369","1628370","1628371","1628374","1628378","1628379","1628386","1628389","1628392","1628396","1628398"]

    if len(player_ids) < 12 or len(player_ids) > 15:
        print("Error: A roster must contain between 12 and 15 players.")
        return

    connection = None

    try:
        connection = connect_to_database()

        print("Connected to database successfully.")

        roster = get_roster_data(connection, player_ids)

        if len(roster) != len(player_ids):
            print()
            print("WARNING:")
            print(
                f"Requested {len(player_ids)} players, "
                f"but only found data for {len(roster)}."
            )

            found_ids = {
                player["player_id"]
                for player in roster
            }

            missing_ids = [
                player_id
                for player_id in player_ids
                if player_id not in found_ids
            ]

            print("Missing player IDs:", missing_ids)
            return

        print()
        print("ROSTER")
        print("----------------------------------------")

        for player in sorted(
            roster,
            key=lambda player: player["minutes"],
            reverse=True
        ):
            print(
                f"ID: {player['player_id']:>4} | "
                f"LEBRON: {player['lebron']:>6.2f} | "
                f"Minutes: {player['minutes']:>7.0f}"
            )

        results = project_wins(roster)

        print()
        print("MODEL FEATURES")
        print("----------------------------------------")
        print(
            f"Team LEBRON:          "
            f"{results['team_lebron']:.4f}"
        )
        print(
            f"Top-10 LEBRON Std:    "
            f"{results['top10_std']:.4f}"
        )
        print(
            f"Positive Minute Share:"
            f" {results['positive_share']:.4f}"
        )
        print(
            f"Top-3 Minute Share:   "
            f"{results['top3_share']:.4f}"
        )

        print()
        print("PROJECTED RESULTS")
        print("----------------------------------------")

        projected_wins = results["projected_wins"]
        projected_losses = 82 - projected_wins

        print(
            f"Projected Wins:   {projected_wins:.1f}"
        )
        print(
            f"Projected Losses: {projected_losses:.1f}"
        )

        print()
        print(
            f"Projected Record: "
            f"{round(projected_wins)}-"
            f"{82 - round(projected_wins)}"
        )

    except Exception as error:
        print("An error occurred:")
        print(error)

    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    main()