"""Shared pytest fixtures."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.config import TestConfig


@pytest.fixture()
def app(tmp_path):
    config = TestConfig()
    config.DATA_DIR = str(tmp_path / "data")
    # Use a file-based SQLite DB per test: `:memory:` databases are
    # connection-local in SQLite, which makes reads from other connections
    # (request sessions) return empty results after a session close.
    config.DATABASE_URL = f"sqlite:///{tmp_path / 'test.db'}"
    application = create_app(config)
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return app.db


@pytest.fixture()
def user_id(app):
    """Create a user and return its id (FK targets must exist for inserts)."""
    from app import models

    return models.create_user(app.db, "testuser", "StrongPass1", "Test User", "Test School")


def register(client, username="teacher1", password="StrongPass1", display="Test Teacher"):
    return client.post(
        "/register",
        data={
            "username": username,
            "display_name": display,
            "school": "Test School",
            "password": password,
            "confirm_password": password,
        },
    )


@pytest.fixture()
def logged_in_client(client):
    register(client)
    client.post("/login", data={"username": "teacher1", "password": "StrongPass1"})
    return client
