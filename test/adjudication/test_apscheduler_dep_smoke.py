"""Smoke tests for apscheduler dependency availability."""

from __future__ import annotations


def test_apscheduler_asyncio_scheduler_importable() -> None:
    """T0: apscheduler.schedulers.asyncio.AsyncIOScheduler is importable and is a class."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    assert isinstance(AsyncIOScheduler, type)


def test_apscheduler_version_is_three_dot_x() -> None:
    """T0b: apscheduler version is in the supported ^3.x range."""
    import apscheduler

    assert apscheduler.__version__.startswith("3.")
