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
