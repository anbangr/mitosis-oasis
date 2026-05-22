# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
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
