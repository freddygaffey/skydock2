"""Flask application factory for the Skydock log server."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from flask import Flask, Response

from config import data_paths, rpi_missions_root

_LOG_SERVER_DIR = Path(__file__).resolve().parent


def _maybe_start_yolo_predownload() -> None:
    """Optional background fetch of Ultralytics hub weights (``SKYDOCK_YOLO_PREDOWNLOAD=1``)."""
    if os.environ.get("SKYDOCK_YOLO_PREDOWNLOAD", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return

    def _run() -> None:
        try:
            from services.training_data import predownload_training_preset_weights

            r = predownload_training_preset_weights()
            good = sum(1 for x in r.values() if x.get("ok"))
            print(
                f"[training] SKYDOCK_YOLO_PREDOWNLOAD: {good}/{len(r)} hub weights cached",
                flush=True,
            )
        except Exception as exc:
            print(f"[training] SKYDOCK_YOLO_PREDOWNLOAD failed: {exc}", flush=True)

    threading.Thread(target=_run, daemon=True).start()


def create_app() -> Flask:
    sim_root, missions_root = data_paths()
    app = Flask(
        __name__,
        template_folder=str(_LOG_SERVER_DIR / "templates"),
        static_folder=str(_LOG_SERVER_DIR / "static"),
        static_url_path="/static",
    )
    app.config["MISSIONS_ROOT"] = missions_root
    app.config["RPI_MISSIONS_ROOT"] = rpi_missions_root()
    app.config["SIM_DATA_ROOT"] = sim_root

    # Register before blueprints so nothing shadows it; GET + HEAD;200 body (some clients treat 204 oddly).
    _FAVICON_SVG = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="6" fill="#1a5cbf"/>'
        '<text x="16" y="22" text-anchor="middle" fill="#fff" font-size="18" font-family="sans-serif">S</text>'
        '</svg>'
    )

    @app.route("/favicon.ico", methods=("GET", "HEAD"))
    def _favicon() -> Response:
        return Response(
            _FAVICON_SVG,
            mimetype="image/svg+xml",
            headers={"Cache-Control": "public, max-age=604800"},
        )

    from routes_api import bp as api_bp
    from routes_web import bp as web_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)

    _maybe_start_yolo_predownload()

    return app
