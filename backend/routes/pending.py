"""Reserved project endpoints awaiting data and model integration."""

from flask import Blueprint

from ..responses import failure

pending = Blueprint("pending", __name__)


@pending.post("/valuation")
def valuation():
    return failure("NOT_IMPLEMENTED", "Player valuation model is not integrated yet.", 501)


@pending.post("/trade/validate")
def validate_trade():
    return failure(
        "NOT_IMPLEMENTED", "Trade rules, contracts, and pick ownership are not integrated yet.", 501
    )


@pending.get("/picks")
def picks():
    return failure("NOT_IMPLEMENTED", "Draft pick data and valuation are not integrated yet.", 501)
