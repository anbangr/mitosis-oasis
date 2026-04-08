"""Shared fixtures for API-level tests.

Provides a FastAPI ``TestClient`` wired to the Metosis-OASIS app with
an in-memory database.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from oasis.api import app


@pytest.fixture()
def client() -> TestClient:
    """Return a synchronous TestClient for the Metosis-OASIS API.

    The app's lifespan handler starts Platform + Channel with an
    in-memory SQLite database, so each test gets a clean environment.
    """
    with TestClient(app) as c:
        yield c
