"""
analysis/metrics.py
===================
Metrics definitions for Mitosis-OASIS analysis.
Calculates EQ1/EQ2 scale metrics by querying the observatory database.
"""

import sqlite3
from typing import Any, Dict

class ObservatoryMetrics:
    def __init__(self, db_path: str):
        self.db_path = db_path
        
    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
            
    def compute_all_metrics(self) -> Dict[str, Any]:
        """Compute top-level summary metrics across the simulation."""
        return {
            "alpha_adherence": self.get_alpha_adherence(),
            "h_b_diversity": self.get_h_diversity(),
            "phi_cap_fidelity": self.get_phi_fidelity(),
            "beta_compliance": self.get_beta_compliance(),
            "economic_activity": self.get_economic_activity(),
            "adjudication_efficiency": self.get_adjudication_efficiency(),
            "adjudicator_concentration": self.get_adjudicator_concentration(),
            "contract_latency_mean": self.get_contract_latency_mean(),
            "schema_compliance_rate": self.get_schema_compliance_rate(),
            "regulatory_failure_rate": self.get_regulatory_failure_rate(),
        }

    def get_alpha_adherence(self) -> float:
        """Eq 1: Adherence to persona over time."""
        # Simulated/Aggregated from reputation ledger
        # A simple proxy: average reputation score across all registry agents
        rows = self._query("SELECT avg(reputation_score) as avg_rep FROM agent_registry WHERE agent_type = 'producer'")
        if rows and rows[0]['avg_rep'] is not None:
            return float(rows[0]['avg_rep'])
        return 1.0

    def get_h_diversity(self) -> float:
        """Eq 2: Shannon diversity of behavior signatures."""
        return 0.85 # Placeholder. Detailed implementation queries event_log distributions

    def get_phi_fidelity(self) -> float:
        """Eq 3: Capability translation into output quality."""
        return 0.90 # Placeholder. Queries task_assignment quality metric outputs

    def get_beta_compliance(self) -> float:
        """Eq 4: Institutional compliance."""
        # Inverse proportional to number of critical guardian alerts
        rows = self._query("SELECT count(*) as c FROM guardian_alert WHERE severity IN ('high', 'critical')")
        alerts = rows[0]['c'] if rows else 0
        return max(0.0, 1.0 - (alerts * 0.05))

    def get_economic_activity(self) -> float:
        """Calculate total volume of transaction in treasury."""
        rows = self._query("SELECT sum(abs(amount)) as vol FROM treasury")
        if rows and rows[0]['vol'] is not None:
            return float(rows[0]['vol'])
        return 0.0

    def get_adjudication_efficiency(self) -> float:
        """Time delta from BIDDING_OPEN to DEPLOYED (in seconds).
        Returns average end-to-end time across completed sessions.
        """
        rows = self._query(
            "SELECT created_at, updated_at FROM legislative_session "
            "WHERE state = 'DEPLOYED'"
        )
        if not rows:
            return 0.0
        
        from datetime import datetime
        total_seconds = 0.0
        valid_rows = 0
        
        for r in rows:
            if not r['created_at'] or not r['updated_at']:
                continue
            try:
                start = datetime.fromisoformat(r['created_at'].replace("Z", "+00:00"))
                end = datetime.fromisoformat(r['updated_at'].replace("Z", "+00:00"))
                total_seconds += (end - start).total_seconds()
                valid_rows += 1
            except (ValueError, TypeError):
                continue
                
        return total_seconds / valid_rows if valid_rows > 0 else 0.0

    def get_adjudicator_concentration(self) -> float:
        """Herfindahl-Hirschman index of stake_amount per bidder."""
        rows = self._query(
            "SELECT bidder_did, SUM(stake_amount) as total_stake "
            "FROM bid GROUP BY bidder_did"
        )
        if not rows:
            return 0.0
            
        total = sum((r['total_stake'] or 0.0) for r in rows)
        if total <= 0:
            return 0.0
            
        # HHI is sum of squares of market shares [0, 1]
        hhi = sum(((r['total_stake'] or 0.0) / total) ** 2 for r in rows)
        return hhi

    def get_contract_latency_mean(self) -> float:
        """Average of estimated_latency_ms across all bids."""
        rows = self._query("SELECT AVG(estimated_latency_ms) as avg_lat FROM bid")
        if rows and rows[0]['avg_lat'] is not None:
            return float(rows[0]['avg_lat'])
        return 0.0

    def get_schema_compliance_rate(self) -> float:
        """Ratio of validated specs to total specs."""
        total_rows = self._query("SELECT count(*) as c FROM contract_spec")
        total = total_rows[0]['c'] if total_rows else 0
        if total == 0:
            return 1.0  # By default fully compliant if no specs submitted
            
        valid_rows = self._query("SELECT count(*) as c FROM contract_spec WHERE status = 'validated'")
        valid = valid_rows[0]['c'] if valid_rows else 0
        return float(valid) / total

    def get_regulatory_failure_rate(self) -> float:
        """Ratio of rejected bids to total bids."""
        total_rows = self._query("SELECT count(*) as c FROM bid")
        total = total_rows[0]['c'] if total_rows else 0
        if total == 0:
            return 0.0
            
        rejected_rows = self._query("SELECT count(*) as c FROM bid WHERE status = 'rejected'")
        rejected = rejected_rows[0]['c'] if rejected_rows else 0
        return float(rejected) / total
