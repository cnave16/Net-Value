"""Shared response envelope for all API endpoints."""

from flask import jsonify


def success(data, meta=None):
    return jsonify(data=data, meta=meta or {}, error=None)


def failure(code, message, status):
    return jsonify(data=None, meta={}, error={"code": code, "message": message}), status
