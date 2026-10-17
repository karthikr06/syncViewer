"""One process for small deployments: the API with the demo cloud (generator) mounted at /gen.

Set GENERATOR_URL=http://127.0.0.1:8000/gen so the collector reaches it in-process.
"""
from syncgen.main import app as generator

from app.main import create_app


def create_combined_app():
    app = create_app()
    app.mount("/gen", generator)
    return app
