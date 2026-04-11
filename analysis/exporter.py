"""
analysis/exporter.py
====================
Dumps OASIS experiment metrics and raw table data into CSV files 
for offline analysis and curve generation.
"""

import csv
import logging
import sqlite3
from pathlib import Path
from typing import List, Dict, Any

from analysis.metrics import ObservatoryMetrics

log = logging.getLogger(__name__)

    def __init__(
        self,
        db_path: str,
        out_dir: str,
        output_format: str = "csv",
        replicate_id: int | None = None,
    ):
        self.db_path = db_path
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.output_format = output_format
        self.replicate_id = replicate_id
        self.metrics = ObservatoryMetrics(db_path)
        
    def _fetch_table(self, table_name: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute(f"SELECT * FROM {table_name}")
                return [dict(row) for row in cursor.fetchall()]
            except sqlite3.OperationalError as e:
                log.warning(f"Failed to fetch {table_name}: {e}")
                return []
                
    def _write_csv(self, filename: str, data: List[Dict[str, Any]]):
        if not data:
            return
            
        file_path = self.out_dir / filename
        keys = list(data[0].keys())
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(data)
            
        log.info(f"Exported {len(data)} rows to {file_path}")

    def _write_json(self, filename: str, data: list[dict[str, Any]]) -> None:
        import json
        file_path = self.out_dir / filename
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        log.info(f"Exported {len(data)} rows to {file_path}")

    def _write(self, name: str, data: list[dict[str, Any]]) -> None:
        if self.output_format in ("csv", "both"):
            self._write_csv(f"{name}.csv", data)
        if self.output_format in ("json", "both"):
            self._write_json(f"{name}.json", data)

    def export_all(self):
        """Export core tables and compute scale metrics into CSV rows."""
        log.info(f"Starting export (format={self.output_format}, replicate={self.replicate_id}) from {self.db_path} to {self.out_dir}")
        
        # 1. Export Raw Tables
        tables = [
            "agent_registry",
            "legislative_session", 
            "proposal",
            "vote",
            "bid",
            "reputation_ledger",
            "event_log"
        ]
        
        for t in tables:
            rows = self._fetch_table(t)
            if rows:
                if self.replicate_id is not None:
                    for row in rows:
                        row["replicate_id"] = self.replicate_id
                self._write(t, rows)
                
        # 2. Export Computed EQ Metrics
        metrics_summary = self.metrics.compute_all_metrics()
        if self.replicate_id is not None:
            metrics_summary["replicate_id"] = self.replicate_id
        self._write("computed_metrics", [metrics_summary])
        
        log.info("Export complete.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import argparse
    import tempfile
    import os
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=str, required=False, help="Path to observatory sqlite db")
    parser.add_argument("--out", type=str, default="experiments/csv_export", help="Output directory")
    parser.add_argument("--format", choices=["csv", "json", "both"], default="csv")
    parser.add_argument("--replicate-id", type=int)
    args = parser.parse_args()
    
    # If not provided, try to find the latest tmp db for observatory
    db_path = args.db
    if not db_path:
        tmp_dir = tempfile.gettempdir()
        db_files = [os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir) if f.startswith("oasis_obs_") and f.endswith(".db")]
        if db_files:
            db_path = max(db_files, key=os.path.getmtime)
            log.info(f"Auto-selected database: {db_path}")
        else:
            log.error("No database path provided and none found in temp dir.")
            exit(1)
            
    exporter = ExperimentExporter(db_path, args.out, output_format=args.format, replicate_id=args.replicate_id)
    exporter.export_all()
