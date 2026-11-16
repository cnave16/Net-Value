# Read players, teams, and seasons for the frontend, with player search and paging.

from flask import Blueprint, request
from werkzeug.exceptions import BadRequest, NotFound

from ..database import query
from ..responses import success
from ..services.trade_finances import TRADE_SEASON_START_YEAR
from ..services.draft import rookie_estimates
from ..services.valuation import fair_values, valuation

catalog = Blueprint("catalog", __name__)


def integer_argument(name, default=None, minimum=1, maximum=None):
    # Read a whole number from the URL and reject values outside its range.
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise BadRequest(f"{name} must be an integer.") from None
    if value < minimum or (maximum is not None and value > maximum):
        raise BadRequest(f"{name} is outside the allowed range.")
    return value


@catalog.get("/teams")
def teams():
    return success(query(
        "SELECT team_id AS id, abbreviation, team_name, city "
        "FROM teams ORDER BY abbreviation"
    ))


@catalog.get("/seasons")
def seasons():
    return success(query(
        "SELECT season_id AS id, start_year, end_year "
        "FROM seasons ORDER BY start_year DESC"
    ))


@catalog.get("/players")
def players():
    # Validate filters, fetch one page of players, and include the match count.
    page = integer_argument("page", 1, maximum=1000000)
    limit = integer_argument("limit", 20, maximum=100)
    # PostgreSQL SERIAL IDs fit in a signed 32-bit integer.
    season_id = integer_argument("season_id", maximum=2147483647)
    search = request.args.get("search", "").strip()
    team = request.args.get("team", "").strip().upper()
    if len(search) > 100:
        raise BadRequest("search must be at most 100 characters.")
    if team and (len(team) != 3 or not team.isascii() or not team.isalpha()):
        raise BadRequest("team must be a three-letter abbreviation.")
    if team and season_id is None:
        # Membership is historical, so a team filter needs a specific season.
        raise BadRequest("season_id is required when filtering by team.")

    # Keep SQL conditions separate from the values supplied by the user.
    conditions, params = [], []
    if search:
        # Bind values and treat LIKE wildcard characters as literal search text.
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # Join first and last names; ILIKE ignores capitalization.
        conditions.append("(p.first_name || ' ' || p.last_name) ILIKE %s")
        params.append(f"%{escaped}%")
    if season_id is not None:
        season_filter = "ps.player_id = p.player_id AND ps.season_id = %s"
        params.append(season_id)
        if team:
            season_filter += " AND t.abbreviation = %s"
            params.append(team)
        # EXISTS avoids duplicate players who played for multiple teams.
        # LEFT JOIN still allows season-only matches without a team record.
        conditions.append(
            "EXISTS (SELECT 1 FROM player_seasons ps "
            "LEFT JOIN player_team_seasons pts ON pts.player_season_id = ps.player_season_id "
            "LEFT JOIN teams t ON t.team_id = pts.team_id WHERE " + season_filter + ")"
        )
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    # filtered holds all matches; paged selects only the requested slice.
    # One query keeps the total and results consistent during data imports.
    # The final LEFT JOIN keeps the total even when that page has no players.
    rows = query(
        "WITH filtered AS (SELECT p.player_id AS id, "
        "p.first_name || ' ' || p.last_name AS name, p.external_id FROM players p"
        + where + "), paged AS (SELECT f.*, ct.abbreviation AS team, c.cap_salary, c.contract_type "
        "FROM filtered f " + CONTRACT_JOIN.format(player="f.id")
        + " ORDER BY name, id LIMIT %s OFFSET %s) "
        "SELECT paged.*, totals.total FROM (SELECT COUNT(*) AS total FROM filtered) totals "
        "LEFT JOIN paged ON TRUE ORDER BY paged.name, paged.id",
        # Skip earlier pages: page 2 with a limit of 20 skips the first 20 rows.
        tuple(params + [TRADE_SEASON_START_YEAR, limit, (page - 1) * limit]),
    )
    # An empty page has a count-only row; don't return it as a player.
    _, values = fair_values()
    rookies = rookie_estimates()
    data = [player_response(row, values, rookies) for row in rows if row["id"] is not None]
    total = rows[0]["total"]
    return success(data, {
        "page": page, "limit": limit, "total": total,
        # Round up so a partly filled last page still counts as a page.
        "total_pages": (total + limit - 1) // limit,
        "season_id": season_id, "team_filter": team or None,
    })


# A player's current team and cap salary; at most one contract per season.
CONTRACT_JOIN = (
    "LEFT JOIN player_contracts c ON c.player_id = {player} AND c.season_start_year = %s "
    "LEFT JOIN teams ct ON ct.team_id = c.team_id"
)


def player_response(row, values, rookies):
    # Use the same player fields for search results and individual lookups.
    # team is the current (2026-27) contract team; null for players without one.
    return {
        "id": row["id"], "name": row["name"], "external_id": row["external_id"],
        "team": row.get("team"),
        **valuation(row["external_id"], row.get("cap_salary"), row.get("contract_type"),
                    values, rookies.get(row["id"])),
    }


def find_player(player_id):
    # Look up our database ID, not an external provider's player ID.
    if not 1 <= player_id <= 2147483647:
        raise BadRequest("player_id must be a positive database integer ID.")
    rows = query(
        "SELECT p.player_id AS id, p.first_name || ' ' || p.last_name AS name, p.external_id, "
        "ct.abbreviation AS team, c.cap_salary, c.contract_type FROM players p "
        + CONTRACT_JOIN.format(player="p.player_id") + " WHERE p.player_id = %s",
        (TRADE_SEASON_START_YEAR, player_id),
    )
    if not rows:
        raise NotFound("Player not found.")
    return rows[0]


@catalog.get("/players/<int:player_id>")
def player(player_id):
    row = find_player(player_id)
    _, values = fair_values()
    response = player_response(row, values, rookie_estimates())
    return success({**response, "seasons": player_seasons(player_id)})


@catalog.post("/valuation")
def player_valuation():
    """Fair value (Chase's model) against the player's 2026-27 cap salary."""
    body = request.get_json()
    if not isinstance(body, dict) or set(body) != {"player_id"} or type(body["player_id"]) is not int:
        raise BadRequest("Provide only player_id as a database integer ID.")
    row = find_player(body["player_id"])
    year, values = fair_values()
    rookie = rookie_estimates().get(row["id"])
    return success(
        {"player_id": row["id"], **valuation(row["external_id"], row.get("cap_salary"),
                                              row.get("contract_type"), values, rookie)},
        {
            "fair_value_basis": "league_cap_budget_by_lebron_above_replacement_times_minutes",
            "stats_season_end_year": year,
            "salary_season": {"start_year": TRADE_SEASON_START_YEAR, "end_year": TRADE_SEASON_START_YEAR + 1},
            "salary_source": "player_contracts.cap_salary",
        },
    )


def number(value):
    # NUMERIC columns arrive as Decimal; keep missing values null in JSON.
    return None if value is None else float(value)


def player_seasons(player_id):
    # Combine team stints so traded players still get one row per season.
    rows = query(
        "SELECT s.season_id, s.start_year, s.end_year, ps.lebron, "
        "ps.offensive_lebron, ps.defensive_lebron, "
        "SUM(pts.games_played) AS games_played, SUM(pts.minutes_played) AS minutes_played, "
        "ARRAY_REMOVE(ARRAY_AGG(t.abbreviation ORDER BY pts.minutes_played DESC NULLS LAST, "
        "t.abbreviation), NULL) AS teams "
        "FROM player_seasons ps JOIN seasons s ON s.season_id = ps.season_id "
        "LEFT JOIN player_team_seasons pts ON pts.player_season_id = ps.player_season_id "
        "LEFT JOIN teams t ON t.team_id = pts.team_id "
        "WHERE ps.player_id = %s "
        "GROUP BY s.season_id, s.start_year, s.end_year, ps.lebron, "
        "ps.offensive_lebron, ps.defensive_lebron "
        "ORDER BY s.start_year DESC, s.end_year DESC, s.season_id DESC",
        (player_id,),
    )
    return [{
        "season_id": row["season_id"], "start_year": row["start_year"],
        "end_year": row["end_year"], "teams": row["teams"],
        "games_played": None if row["games_played"] is None else int(row["games_played"]),
        "minutes_played": number(row["minutes_played"]),
        "lebron": number(row["lebron"]),
        "offensive_lebron": number(row["offensive_lebron"]),
        "defensive_lebron": number(row["defensive_lebron"]),
    } for row in rows]
