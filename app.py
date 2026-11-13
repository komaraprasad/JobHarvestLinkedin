"""JobHarvest dashboard. Local:  python app.py  (or JobHarvest.exe), then open http://127.0.0.1:5000
Hosted (Render etc.):  gunicorn wsgi:app  with DATABASE_URL set to a PostgreSQL database (see DEPLOY_RENDER.md)."""
import io
import json
import os
import sys
import threading
import webbrowser
import zipfile

from flask import Flask, abort, render_template, request, send_file
from werkzeug.middleware.proxy_fix import ProxyFix

from ljt.extapi import create_blueprint
from ljt.extstore import ExtStore
from ljt.search import DATE_POSTED, EXPERIENCE, JOB_TYPE, SORT, WORK_TYPE

FROZEN = getattr(sys, "frozen", False)
# Bundled read-only files (templates, extension, world_geo.db) vs. the writable folder for results.
RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(DATA_DIR, "output")
HOST, PORT = "127.0.0.1", 5000

# Requests that change something must come from the dashboard page itself or from a browser extension (or carry no
# Origin, e.g. curl/tests). Blocks other websites open in the same browser from starting/stopping runs.
ALLOWED_ORIGINS = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}


def _origin_ok(origin, own):
    return (not origin or origin == own or origin in ALLOWED_ORIGINS
            or origin.startswith(("chrome-extension://", "extension://")))


def create_app(db_path=None, limits=None, out_dir=None):
    app = Flask(__name__, template_folder=os.path.join(RES_DIR, "templates"))
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)   # behind Render's HTTPS proxy: see the real https://host
    out = out_dir or OUT_DIR
    os.makedirs(out, exist_ok=True)
    # DATABASE_URL (postgres://...) when hosted; otherwise a local SQLite file in output/.
    store = ExtStore(db_path or os.environ.get("DATABASE_URL") or os.path.join(out, "signedin.sqlite3"), limits)
    app.register_blueprint(create_blueprint(store, out))

    @app.before_request
    def check_origin():
        own = request.host_url.rstrip("/")
        if request.method not in ("GET", "HEAD", "OPTIONS") and not _origin_ok(request.headers.get("Origin"), own):
            abort(403)

    @app.get("/")
    def index():
        return render_template("index.html", work=WORK_TYPE, dates=DATE_POSTED, exp=EXPERIENCE, jobtypes=JOB_TYPE, sorts=SORT)

    @app.get("/results")
    def results_page():
        return render_template("results.html")

    @app.get("/extension.zip")
    def extension_zip():
        """The browser extension, zipped fresh from the extension/ folder (always the current version)."""
        folder = os.path.join(RES_DIR, "extension")
        with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
            version = json.load(f).get("version", "")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(os.listdir(folder)):
                if os.path.isfile(os.path.join(folder, name)):
                    z.write(os.path.join(folder, name), name)   # flat: the unzipped folder is the one to Load unpacked
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"jobharvest-extension-v{version}.zip", mimetype="application/zip")

    return app


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}"
    print(f"JobHarvest dashboard: {url}   (keep this window open; close it to stop)")
    print(f"Results are saved in: {OUT_DIR}")
    if FROZEN or "--open" in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve          # production WSGI server when available
        serve(create_app(), host=HOST, port=PORT, threads=8)
    except ImportError:
        create_app().run(host=HOST, port=PORT, debug=False, threaded=True)
