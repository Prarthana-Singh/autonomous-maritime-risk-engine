#!/usr/bin/env python
"""CLI replay: reproduces the same deterministic processing as POST
/replay for a local JSON file of events, using the exact same graph
(app.graph.pipeline) via app.graph.runner.replay_response -- no separate
replay implementation.

Usage:
    python replay_cli.py fixtures/04_conflicting_signals.json
    python replay_cli.py fixtures/04_conflicting_signals.json --output outputs/replay_result.json
"""

import argparse
import json
import sys
from pathlib import Path

from app.graph.runner import replay_response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a JSON list of events deterministically.")
    parser.add_argument("events_file", type=Path, help="Path to a JSON file containing a list of events.")
    parser.add_argument(
        "--output", type=Path, default=None, help="Optional path to write the replay result JSON."
    )
    args = parser.parse_args(argv)

    raw_events = json.loads(args.events_file.read_text(encoding="utf-8"))
    result = replay_response(raw_events)
    text = json.dumps(result, indent=2, sort_keys=True)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")

    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
