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
"""Constitution parameter shim for the adjudication layer.

Reads individual parameters from the governance ``constitution`` table
without loading the full validator.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union


# Simple per-process cache: (db_path, param_name) -> value
_CACHE: dict[tuple[str, str], float] = {}


def _get_constitution_param(
    db_path: Union[str, Path], name: str, default: float
) -> float:
    """Read a single parameter from the constitution table.

    Parameters
    ----------
    db_path:
        Path to the SQLite database containing the ``constitution`` table.
    name:
        Parameter name (e.g. ``'rotation_max_consecutive'``).
    default:
        Fallback value when the parameter is absent or the table does not exist.

    Returns
    -------
    float
        The stored parameter value, or *default* when not found.
    """
    key = (str(db_path), name)
    if key in _CACHE:
        return _CACHE[key]

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT param_value FROM constitution WHERE param_name = ?",
                (name,),
            ).fetchone()
            value = row["param_value"] if row is not None else default
        finally:
            conn.close()
    except sqlite3.Error:
        value = default

    _CACHE[key] = value
    return value
