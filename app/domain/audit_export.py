"""Serialize persisted audit records to decision-trace JSON files.

This is deliberately NOT wired into the live POST /events request path --
writing a file per HTTP request would be an odd side effect for a
service and would fight the isolated in-memory DBs used by tests. It is
invoked explicitly, e.g. by the fixture runner (Phase 9) or the CLI, to
produce the "audit and decision-trace output files" deliverable from a
completed run.

Output content is exactly the persisted audit record fields (vessel_id,
event_ids, resolved_risk_signal, resolution_reason, timestamp) -- no
wall-clock/generation timestamps are included, so the same event sequence
always produces byte-identical output, whether live or replayed.
"""

import json
import sqlite3
from pathlib import Path

from app.storage import repository


def export_audit_trail_for_vessel(
    conn: sqlite3.Connection, vessel_id: str, outputs_dir: Path
) -> Path:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    records = repository.get_audit_records_for_vessel(conn, vessel_id)
    path = outputs_dir / f"{vessel_id}_audit_trace.json"
    path.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
    return path


def export_all_audit_trails(conn: sqlite3.Connection, outputs_dir: Path) -> list[Path]:
    return [
        export_audit_trail_for_vessel(conn, vessel_id, outputs_dir)
        for vessel_id in repository.get_all_audited_vessel_ids(conn)
    ]
