"""Shared response envelope for all API endpoints."""

from flask import jsonify


def success(data, meta=None):
    return jsonify(data=data, meta=meta or {}, error=None)


def failure(code, message, status):
    # Flask reads this tuple as the JSON response plus its HTTP status code.
    return jsonify(data=None, meta={}, error={"code": code, "message": message}), status
