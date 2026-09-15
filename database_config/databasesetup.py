import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

db_url = os.getenv("DATABASE_URL")

if not db_url:
    raise ValueError(
        "DATABASE_URL was not found. Make sure it is defined in your .env file."
    )


CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS teams (
    team_id SERIAL PRIMARY KEY,
    abbreviation VARCHAR(3) NOT NULL UNIQUE,
    team_name VARCHAR(100) NOT NULL,
    city VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS seasons (
    season_id SERIAL PRIMARY KEY,
    start_year INTEGER NOT NULL,
    end_year INTEGER NOT NULL,

    CONSTRAINT unique_season UNIQUE (start_year, end_year),

    CONSTRAINT valid_season_years
        CHECK (end_year = start_year + 1)
);

CREATE TABLE IF NOT EXISTS players (
    player_id SERIAL PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,

    -- Optional external identifier for use later when importing
    -- data from another basketball data source.
    external_id VARCHAR(100) UNIQUE
);

CREATE TABLE IF NOT EXISTS player_seasons (
    player_season_id SERIAL PRIMARY KEY,

    player_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,

    lebron NUMERIC(8, 4),
    offensive_lebron NUMERIC(8, 4),
    defensive_lebron NUMERIC(8, 4),

    CONSTRAINT fk_player_seasons_player
        FOREIGN KEY (player_id)
        REFERENCES players(player_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_player_seasons_season
        FOREIGN KEY (season_id)
        REFERENCES seasons(season_id)
        ON DELETE CASCADE,

    CONSTRAINT unique_player_season
        UNIQUE (player_id, season_id)
);

CREATE TABLE IF NOT EXISTS player_team_seasons (
    player_team_season_id SERIAL PRIMARY KEY,

    player_season_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,

    minutes_played NUMERIC(10, 2) NOT NULL DEFAULT 0,
    games_played INTEGER,

    CONSTRAINT fk_player_team_seasons_player_season
        FOREIGN KEY (player_season_id)
        REFERENCES player_seasons(player_season_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_player_team_seasons_team
        FOREIGN KEY (team_id)
        REFERENCES teams(team_id)
        ON DELETE CASCADE,

    CONSTRAINT unique_player_team_season
        UNIQUE (player_season_id, team_id),

    CONSTRAINT valid_minutes_played
        CHECK (minutes_played >= 0),

    CONSTRAINT valid_games_played
        CHECK (
            games_played IS NULL
            OR games_played >= 0
        )
);

CREATE TABLE IF NOT EXISTS team_seasons (
    team_season_id SERIAL PRIMARY KEY,

    team_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,

    wins INTEGER,
    losses INTEGER,

    CONSTRAINT fk_team_seasons_team
        FOREIGN KEY (team_id)
        REFERENCES teams(team_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_team_seasons_season
        FOREIGN KEY (season_id)
        REFERENCES seasons(season_id)
        ON DELETE CASCADE,

    CONSTRAINT unique_team_season
        UNIQUE (team_id, season_id),

    CONSTRAINT valid_wins
        CHECK (
            wins IS NULL
            OR wins >= 0
        ),

    CONSTRAINT valid_losses
        CHECK (
            losses IS NULL
            OR losses >= 0
        )
);
"""


CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_player_seasons_player
    ON player_seasons(player_id);

CREATE INDEX IF NOT EXISTS idx_player_seasons_season
    ON player_seasons(season_id);

CREATE INDEX IF NOT EXISTS idx_player_team_seasons_player
    ON player_team_seasons(player_season_id);

CREATE INDEX IF NOT EXISTS idx_player_team_seasons_team
    ON player_team_seasons(team_id);

CREATE INDEX IF NOT EXISTS idx_team_seasons_team
    ON team_seasons(team_id);

CREATE INDEX IF NOT EXISTS idx_team_seasons_season
    ON team_seasons(season_id);
"""


def setup_database():
    connection = None
    cursor = None

    try:
        print("Connecting to Neon PostgreSQL...")

        connection = psycopg2.connect(db_url)
        cursor = connection.cursor()

        print("Connected successfully.")

        print("Creating tables...")
        cursor.execute(CREATE_TABLES_SQL)

        print("Creating indexes...")
        cursor.execute(CREATE_INDEXES_SQL)

        # Save all schema changes.
        connection.commit()

        print()
        print("Net Value database setup completed successfully.")

        # Display the tables that now exist.
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)

        tables = cursor.fetchall()

        print()
        print("Current database tables:")

        for table in tables:
            print(f"  - {table[0]}")

    except Exception as error:
        # Undo any partially completed transaction.
        if connection:
            connection.rollback()

        print()
        print("Database setup failed:")
        print(error)

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

        print()
        print("Database connection closed.")


if __name__ == "__main__":
    setup_database()