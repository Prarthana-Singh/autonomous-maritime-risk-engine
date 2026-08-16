# Fixtures

Each file is a JSON array of raw events in the exact shape `POST /events`
and `POST /replay` accept. Run any of them with:

```
python replay_cli.py fixtures/<name>.json --output outputs/<name>_result.json
```

Corresponding generated outputs live in `../outputs/`.

## 01_duplicate_event.json
The same `event_id` is submitted twice (simulating an at-least-once
delivery retry). Expected: first event accepted, second rejected as
`rejected_duplicate`; only one persisted event and one audit record.

## 02_late_out_of_order.json
`MV-Atlas` receives HIGH at 12:00 and MEDIUM at 12:10 live, then a LOW
reading timestamped 11:50 arrives late (submitted last). Expected: the
reconstructed state history is ordered by timestamp, not arrival order —
LOW, HIGH, MEDIUM.

## 03_conflicting_signals.json
`MV-Borealis` gets a HIGH report from Weather and a LOW report from
Regulatory Compliance at the exact same timestamp (confidence tied at
0.8). Expected: resolved by `source_reliability` — Weather (0.9) beats
Regulatory Compliance (0.8), so the state resolves to HIGH. A later,
non-conflicting Geopolitical Risk MEDIUM report becomes its own state
entry.

## 04_replay_consistency.json
A richer single-vessel (`MV-Celeste`) timeline: a same-timestamp,
same-confidence pair from Weather and Regulatory Compliance (tie broken
by reliability), plus a late arrival timestamped before everything else.
Intended to be processed once live and once via `/replay`; the final
state history and audit trail must be identical either way (see
`tests/test_replay.py::test_live_vs_replay_produce_identical_final_state_and_audit`
for the same guarantee exercised directly).

## 05_multiple_vessels.json
Events for two vessels (`MV-Atlas`, `MV-Borealis`) interleaved in
submission order, including a late arrival for `MV-Borealis`. Expected:
each vessel's state history is reconstructed independently, with no
cross-vessel leakage.
