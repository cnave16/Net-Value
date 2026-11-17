"""Load future picks and check transfers without guessing protected-pick outcomes."""

from ..database import query
from .trade_finances import TRADE_SEASON_START_YEAR

# This simulator uses 2026-27 contracts even when older ratings are selected.
FIRST_DRAFT = TRADE_SEASON_START_YEAR + 1
LAST_DRAFT = FIRST_DRAFT + 6


def pick_key(pick):
    return (pick["draft_year"], pick["round"], pick["original_team_id"])


def load_pick_ownership():
    """Keep unresolved rows for legality checks, never as selectable assets."""
    return query(
        "SELECT p.*, t.abbreviation AS original_team_abbreviation "
        "FROM draft_pick_ownership p JOIN teams t ON t.team_id = p.original_team_id "
        "ORDER BY p.draft_year, p.round, t.abbreviation"
    )


def pick_details(pick):
    return {key: pick.get(key) for key in (
        "draft_year", "round", "original_team_id", "original_team_abbreviation",
        "owner_team_id", "ownership_type", "is_resolved", "notes",
    )}


def selectable_picks(rows, team_id):
    return [pick_details(p) for p in rows if p["is_resolved"] is True
            and p["owner_team_id"] == team_id and FIRST_DRAFT <= p["draft_year"] <= LAST_DRAFT]


def check_pick_transfers(rows, transfers, team_ids, league_team_ids):
    """Apply all picks together, then check first-round availability by draft year.

    An unresolved row does not identify all possible claimants. Treat its whole
    year as uncertain when no resolved pick guarantees a team's first-rounder.
    This avoids both false approvals and invented failures from protection notes.
    """
    by_key = {pick_key(p): p for p in rows}
    checks = []
    valid = True
    for move in transfers:
        pick = by_key.get(pick_key(move))
        owned = bool(pick and pick["is_resolved"] is True
                     and pick["owner_team_id"] == move["from_team_id"])
        within = FIRST_DRAFT <= move["draft_year"] <= LAST_DRAFT
        valid = valid and owned and within
        checks.extend([
            {"code": "PICK_OWNERSHIP", "team_id": move["from_team_id"], "passed": owned,
             "pick": {k: move[k] for k in ("draft_year", "round", "original_team_id")},
             "message": f'{move["draft_year"]} round {move["round"]}: sender must own this resolved pick.'},
            {"code": "PICK_SEVEN_YEAR_LIMIT", "team_id": move["from_team_id"], "passed": within,
             "message": f'Future picks must fall within {FIRST_DRAFT}–{LAST_DRAFT} for this simulation.'},
        ])
    if not valid:
        return checks, False

    owners = {key: p["owner_team_id"] for key, p in by_key.items() if p["is_resolved"] is True}
    for move in transfers:
        owners[pick_key(move)] = move["to_team_id"]
    for team_id in team_ids:
        # Receiving firsts or moving seconds cannot reduce first-round availability.
        sent_years = {p["draft_year"] for p in transfers
                      if p["from_team_id"] == team_id and p["round"] == 1}
        if not sent_years:
            continue
        failed, unknown = [], []
        for year in range(FIRST_DRAFT, LAST_DRAFT + 1):
            pair = (year, year + 1)
            if not sent_years.intersection(pair):
                continue
            retained = any(key[1] == 1 and key[0] in pair and owner == team_id
                           for key, owner in owners.items())
            if retained:
                continue
            # Include the adjacent draft beyond the trade horizon. Missing data
            # there means review, not an assumption that the team has no pick.
            complete = all(
                (y, 1, original) in by_key and by_key[(y, 1, original)]["is_resolved"] is True
                for y in pair for original in league_team_ids
            ) and bool(league_team_ids)
            (failed if complete else unknown).append(list(pair))
        passed = False if failed else (None if unknown else True)
        pairs = failed or unknown
        detail = "; ".join(f"{a}/{b}" for a, b in pairs)
        message = (f"Stepien rule: no first-round pick remains in {detail}." if failed else
                   f"Stepien rule needs review for {detail}: unresolved rights or missing coverage." if unknown else
                   "Stepien rule: a resolved first-round pick remains in each affected consecutive draft pair.")
        checks.append({"code": "STEPIEN_RULE", "team_id": team_id, "passed": passed,
                       "message": message, "failed_year_pairs": failed, "uncertain_year_pairs": unknown})
        checks.append({
            "code": "FIRST_ROUND_PICK_RESTRICTIONS", "team_id": team_id, "passed": None,
            "message": "First-round pick freezes and league penalties need review; ownership data does not track them.",
        })
    return checks, True


def attach_pick_checks(legality, checks):
    """Preserve the existing incomplete verdict when facts are not available."""
    legality["checks"].extend(checks)
    failed = any(c["passed"] is False for c in legality["checks"])
    unknown = any(c["passed"] is None for c in legality["checks"])
    legality["status"] = "failed" if failed else "incomplete"
    legality["passes_supported_rules"] = False if failed else (None if unknown else True)
