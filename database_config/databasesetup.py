import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

db_url = os.getenv("TEST_DATABASE_URL")

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

-- Current rosters and cap salaries for an upcoming or in-progress season,
-- loaded by database_config/load_contracts.py. One team per player per season.
CREATE TABLE IF NOT EXISTS player_contracts (
    player_contract_id SERIAL PRIMARY KEY,

    season_start_year INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,

    -- Salary that counts against the cap. Two-way contracts count as zero;
    -- NULL means the source has not listed a standard contract's salary yet.
    cap_salary NUMERIC(14, 2) CHECK (cap_salary >= 0),
    -- Salaries for the following seasons, in order; NULL where none is listed.
    later_salaries NUMERIC(14, 2)[] NOT NULL DEFAULT '{}',
    contract_type VARCHAR(20) NOT NULL
        CHECK (contract_type IN ('standard', 'two_way')),
    CHECK (contract_type = 'standard' OR cap_salary = 0),

    source_player_id VARCHAR(20) NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,

    CONSTRAINT fk_player_contracts_player
        FOREIGN KEY (player_id)
        REFERENCES players(player_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_player_contracts_team
        FOREIGN KEY (team_id)
        REFERENCES teams(team_id)
        ON DELETE CASCADE,

    CONSTRAINT unique_player_contract_season
        UNIQUE (season_start_year, player_id)
);

-- The source's team payroll total. The amount above the listed players'
-- salaries is dead money and other charges for waived players.
CREATE TABLE IF NOT EXISTS team_cap_sheets (
    season_start_year INTEGER NOT NULL,
    team_id INTEGER NOT NULL,

    source_total_salary NUMERIC(14, 2) NOT NULL CHECK (source_total_salary >= 0),
    source_url TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,

    PRIMARY KEY (season_start_year, team_id),

    CONSTRAINT fk_team_cap_sheets_team
        FOREIGN KEY (team_id)
        REFERENCES teams(team_id)
        ON DELETE CASCADE
);

-- NBA draft results, loaded by database_config/load_draft.py. player_id is
-- null for draftees who never reached our players table.
CREATE TABLE IF NOT EXISTS draft_picks (
    draft_year INTEGER NOT NULL,
    pick INTEGER NOT NULL CHECK (pick BETWEEN 1 AND 60),
    round INTEGER NOT NULL CHECK (round IN (1, 2)),
    team_id INTEGER NOT NULL,
    player_id INTEGER,

    player_name VARCHAR(200) NOT NULL,
    source_player_id VARCHAR(20) NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,

    PRIMARY KEY (draft_year, pick),

    CONSTRAINT fk_draft_picks_team
        FOREIGN KEY (team_id)
        REFERENCES teams(team_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_draft_picks_player
        FOREIGN KEY (player_id)
        REFERENCES players(player_id)
        ON DELETE SET NULL
);
"""


# Columns added after a table was first created; safe to rerun.
ALTER_TABLES_SQL = """
ALTER TABLE player_contracts
    ADD COLUMN IF NOT EXISTS later_salaries NUMERIC(14, 2)[] NOT NULL DEFAULT '{}';
"""


CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_player_contracts_team
    ON player_contracts(season_start_year, team_id);

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
        cursor.execute(ALTER_TABLES_SQL)

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