# Read players, teams, and seasons for the frontend, with player search and paging.

from flask import Blueprint, request
from werkzeug.exceptions import BadRequest, NotFound

from ..database import query
from ..responses import success

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
    season_id = integer_argument("season_id")
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
        + where + "), paged AS (SELECT * FROM filtered ORDER BY name, id LIMIT %s OFFSET %s) "
        "SELECT paged.*, totals.total FROM (SELECT COUNT(*) AS total FROM filtered) totals "
        "LEFT JOIN paged ON TRUE ORDER BY paged.name, paged.id",
        # Skip earlier pages: page 2 with a limit of 20 skips the first 20 rows.
        tuple(params + [limit, (page - 1) * limit]),
    )
    # An empty page has a count-only row; don't return it as a player.
    data = [player_response(row) for row in rows if row["id"] is not None]
    total = rows[0]["total"]
    return success(data, {
        "page": page, "limit": limit, "total": total,
        # Round up so a partly filled last page still counts as a page.
        "total_pages": (total + limit - 1) // limit,
        "season_id": season_id, "team_filter": team or None,
    })


def player_response(row):
    # Use the same player fields for search results and individual lookups.
    return {
        "id": row["id"], "name": row["name"], "external_id": row["external_id"],
        # Historical team membership does not establish a player's current team.
        # Salary and model outputs stay null until those sources are connected.
        "team": None, "salary": None, "predicted_value": None, "surplus": None,
    }


@catalog.get("/players/<int:player_id>")
def player(player_id):
    # Look up our database ID, not an external provider's player ID.
    rows = query(
        "SELECT player_id AS id, first_name || ' ' || last_name AS name, "
        "external_id FROM players WHERE player_id = %s", (player_id,)
    )
    if not rows:
        raise NotFound("Player not found.")
    return success(player_response(rows[0]))
