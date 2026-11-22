import logging

from flask import jsonify
from werkzeug.exceptions import HTTPException

log = logging.getLogger("filego")

_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    411: "length_required",
    413: "too_large",
    415: "unsupported_type",
    429: "rate_limited",
    507: "insufficient_storage",
}


class ApiError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def error_response(code, message, status):
    return jsonify({"error": {"code": code, "message": message}}), status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.code, e.message, e.status)

    @app.errorhandler(HTTPException)
    def _http_error(e):
        status = e.code or 500
        return error_response(_CODES.get(status, "error"), e.description or e.name, status)

    @app.errorhandler(Exception)
    def _unexpected(e):
        log.exception("Unhandled error")
        return error_response("server_error", "Something went wrong on the server.", 500)
