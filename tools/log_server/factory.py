"""Flask application factory for the Skydock log server."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from config import data_paths, tile_cache_dir

_LOG_SERVER_DIR = Path(__file__).resolve().parent


def create_app() -> Flask:
    sim_root, missions_root = data_paths()
    app = Flask(
        __name__,
        template_folder=str(_LOG_SERVER_DIR / "templates"),
        static_folder=str(_LOG_SERVER_DIR / "static"),
        static_url_path="/static",
    )
    app.config["MISSIONS_ROOT"] = missions_root
    app.config["SIM_DATA_ROOT"] = sim_root
    app.config["TILE_CACHE_DIR"] = tile_cache_dir()

    from routes_api import bp as api_bp
    from routes_web import bp as web_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)
    return app
