# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
"""Watchdog anomaly detection for adjudicators.

Implements spec §2.4: z-score outlier detection on approval rates and
freeze-lift rates across all adjudicators in a sliding window.
"""

from __future__ import annotations

import sqlite3
import statistics
from pathlib import Path
from typing import Union

CALIBRATION_FLOOR = 10


def _approval_rates(*, db_path: Union[str, Path], window_days: int) -> dict[str, float]:
    """Return {adjudicator_did: approval_rate} over the window.

    Approval rate = (approve + unfreeze) / total decisions.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT
                issued_by_did,
                SUM(CASE WHEN decision_type IN ('approve', 'unfreeze') THEN 1 ELSE 0 END) AS positive,
                COUNT(*) AS total
            FROM adjudication_decision
            WHERE created_at >= datetime('now', '-{window_days} days')
              AND issued_by_did IS NOT NULL
            GROUP BY issued_by_did
            """,
        ).fetchall()
    finally:
        conn.close()

    return {
        row["issued_by_did"]: row["positive"] / row["total"]
        for row in rows
        if row["total"] > 0
    }


def _freeze_lift_rates(
    *, db_path: Union[str, Path], window_days: int
) -> dict[str, float]:
    """Return {adjudicator_did: lift_rate} over the window.

    Lift rate = unfreeze / freeze.  Returns 0.0 when freeze count is 0.
    Every adjudicator with at least one decision in the window appears in
    the result dict.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # All adjudicators with any decision in the window
        all_dids = conn.execute(
            f"""
            SELECT DISTINCT issued_by_did
            FROM adjudication_decision
            WHERE created_at >= datetime('now', '-{window_days} days')
              AND issued_by_did IS NOT NULL
            """,
        ).fetchall()

        rows = conn.execute(
            f"""
            SELECT
                issued_by_did,
                SUM(CASE WHEN decision_type = 'unfreeze' THEN 1 ELSE 0 END) AS unfreeze_count,
                SUM(CASE WHEN decision_type = 'freeze' THEN 1 ELSE 0 END) AS freeze_count
            FROM adjudication_decision
            WHERE created_at >= datetime('now', '-{window_days} days')
              AND issued_by_did IS NOT NULL
              AND decision_type IN ('freeze', 'unfreeze')
            GROUP BY issued_by_did
            """,
        ).fetchall()
    finally:
        conn.close()

    freeze_map = {}
    for row in rows:
        did = row["issued_by_did"]
        freeze_count = row["freeze_count"] or 0
        if freeze_count == 0:
            freeze_map[did] = 0.0
        else:
            freeze_map[did] = (row["unfreeze_count"] or 0) / freeze_count

    result: dict[str, float] = {}
    for (did,) in all_dids:
        result[did] = freeze_map.get(did, 0.0)
    return result


def _zscore_outliers(rates: dict[str, float], threshold: float) -> dict[str, float]:
    """Flag adjudicators whose rate is an outlier vs. the population median.

    Uses ``statistics.pstdev`` (population stdev).  Short-circuits to {}
    when ``len(rates) < 2`` or ``pstdev == 0``.
    """
    if len(rates) < 2:
        return {}

    values = list(rates.values())
    med = statistics.median(values)
    try:
        stdev = statistics.pstdev(values, med)
    except statistics.StatisticsError:
        return {}

    if stdev == 0:
        return {}

    outliers: dict[str, float] = {}
    for did, rate in rates.items():
        zscore = (rate - med) / stdev
        if abs(zscore) >= threshold:
            outliers[did] = zscore

    return outliers


def scan_anomalies(
    *,
    db_path: Union[str, Path],
    window_days: int,
    zscore_threshold: float,
) -> dict:
    """Scan for anomalous adjudicator behaviour and persist findings.

    Returns ``{"calibrating": bool, "anomalies": [...]}``.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        total_decisions = conn.execute(
            f"""
            SELECT COUNT(*) FROM adjudication_decision
            WHERE created_at >= datetime('now', '-{window_days} days')
            """,
        ).fetchone()[0]

        if total_decisions < CALIBRATION_FLOOR:
            return {"calibrating": True, "anomalies": []}

        approval_rates = _approval_rates(db_path=db_path, window_days=window_days)
        freeze_lift_rates = _freeze_lift_rates(db_path=db_path, window_days=window_days)

        approval_outliers = _zscore_outliers(approval_rates, zscore_threshold)
        freeze_lift_outliers = _zscore_outliers(freeze_lift_rates, zscore_threshold)

        anomalies: list[dict] = []

        for did, zscore in approval_outliers.items():
            window_decisions = conn.execute(
                f"""
                SELECT COUNT(*) FROM adjudication_decision
                WHERE created_at >= datetime('now', '-{window_days} days')
                  AND issued_by_did = ?
                """,
                (did,),
            ).fetchone()[0]

            conn.execute(
                """
                INSERT INTO watchdog_anomaly
                (adjudicator_did, anomaly_type, zscore, window_decisions)
                VALUES (?, 'approval_rate_deviation', ?, ?)
                """,
                (did, zscore, window_decisions),
            )
            anomalies.append(
                {
                    "adjudicator_did": did,
                    "anomaly_type": "approval_rate_deviation",
                    "zscore": zscore,
                    "window_decisions": window_decisions,
                }
            )

        for did, zscore in freeze_lift_outliers.items():
            window_decisions = conn.execute(
                f"""
                SELECT COUNT(*) FROM adjudication_decision
                WHERE created_at >= datetime('now', '-{window_days} days')
                  AND issued_by_did = ?
                  AND decision_type IN ('freeze', 'unfreeze')
                """,
                (did,),
            ).fetchone()[0]

            conn.execute(
                """
                INSERT INTO watchdog_anomaly
                (adjudicator_did, anomaly_type, zscore, window_decisions)
                VALUES (?, 'freeze_lift_rate_deviation', ?, ?)
                """,
                (did, zscore, window_decisions),
            )
            anomalies.append(
                {
                    "adjudicator_did": did,
                    "anomaly_type": "freeze_lift_rate_deviation",
                    "zscore": zscore,
                    "window_decisions": window_decisions,
                }
            )

        conn.commit()
        return {"calibrating": False, "anomalies": anomalies}
    finally:
        conn.close()


def should_system_freeze(
    *,
    db_path: Union[str, Path],
    adjudicator_did: str,
    anomaly_threshold: int,
    window_days: int,
) -> bool:
    """Return ``True`` iff the adjudicator has ≥ *anomaly_threshold* anomalies
    in the sliding window.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute(
            f"""
            SELECT COUNT(*) FROM watchdog_anomaly
            WHERE adjudicator_did = ?
              AND detected_at >= datetime('now', '-{window_days} days')
            """,
            (adjudicator_did,),
        ).fetchone()[0]
        return count >= anomaly_threshold
    finally:
        conn.close()
