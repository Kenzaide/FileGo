"""Serve the built frontend (dist/) from the same origin and port as the API.

One address for everything (http://<laptop-ip>:5000): no CORS, no second port, and a phone only
needs to know one URL. Any path that is not /api and not a real file returns index.html so that
refreshing /library or /inbox works with the React router.
"""
import os
from pathlib import Path

from flask import send_file, send_from_directory
from werkzeug.exceptions import NotFound
from werkzeug.utils import safe_join

from .errors import ApiError

NOT_BUILT = (
    "<!doctype html><meta charset='utf-8'><title>FileGo</title>"
    "<body style='font-family:sans-serif;max-width:560px;margin:60px auto;line-height:1.6'>"
    "<h2>FileGo server is running</h2>"
    "<p>The web interface has not been built yet. In the project folder run "
    "<code>npm install</code> and then <code>npm run build</code>, then reload this page.</p>"
    "<p>The API is available at <a href='/api/health'>/api/health</a>.</p></body>"
)


def frontend_dir(app):
    return Path(app.config["FRONTEND_DIST"])


def register(app):
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path):
        if path == "api" or path.startswith("api/"):
            raise ApiError("not_found", "Unknown API endpoint.", 404)
        dist = frontend_dir(app)
        index = dist / "index.html"
        if not index.is_file():
            return NOT_BUILT, 503, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}

        if path:
            full = safe_join(str(dist), path)  # None for anything that escapes dist/
            if full and os.path.isfile(full):
                resp = send_from_directory(str(dist), path)
                # Vite file names contain a content hash, so they can be cached for a long time.
                resp.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
                )
                return resp
            if "." in path.rsplit("/", 1)[-1]:
                raise NotFound()  # a missing asset is a 404, not the app shell

        resp = send_file(str(index), mimetype="text/html")
        resp.headers["Cache-Control"] = "no-cache"  # always pick up a new build
        return resp
