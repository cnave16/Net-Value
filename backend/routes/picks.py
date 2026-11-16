"""Draft pick value by slot (data_model/draft_value.py on Chase's fair values)."""

from flask import Blueprint, request
from werkzeug.exceptions import BadRequest, UnprocessableEntity

from .catalog import integer_argument
from ..responses import success
from ..services.draft import draft_model

picks = Blueprint("picks", __name__)


@picks.get("/picks")
def pick_values():
    """Every slot, or one slot/round: expected value per season vs. rookie salary."""
    unknown = set(request.args) - {"slot", "round", "year"}
    if unknown:
        raise BadRequest(f"Unknown query parameters: {sorted(unknown)}.")
    if "year" in request.args:
        raise BadRequest("Values are per draft slot; projecting a specific future draft is not supported yet.")
    slot = integer_argument("slot", maximum=60)
    rnd = integer_argument("round", maximum=2)
    model = draft_model()
    if model is None:
        raise UnprocessableEntity(
            "Draft values need a complete stats season, loaded contracts, and draft results. "
            "Run database_config/load_draft.py."
        )
    data = [p for p in model["picks"]
            if (slot is None or p["pick"] == slot) and (rnd is None or p["round"] == rnd)]
    return success(data, {
        "value_basis": "chase_fair_value_by_draft_slot_and_career_year",
        "stats_season_end_year": model["stats_season_end_year"],
        "history_classes": model["history_classes"],
        "sample_size": model["sample_size"],
        "rookie_salary_class": model["rookie_class"],
        "assumptions": model["assumptions"],
        "notes": [
            "Expected value is the average fair value of past picks at this slot in their "
            "first seasons, smoothed across nearby slots.",
            "Rookie salary is the first-season cap salary of this year's pick at the slot; "
            "unsigned slots are interpolated (salary_is_estimate).",
            "Assumptions are placeholders pending review of the fair-value model.",
        ],
    })
