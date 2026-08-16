# Autonomous Maritime Risk Assessment Engine

An event-driven risk assessment engine for maritime shipping. It ingests
risk events from four data sources (Weather, Port Congestion, Geopolitical
Risk, Regulatory Compliance), reconstructs a correct time-ordered risk
history per vessel even when events arrive late, out of order, or
duplicated, resolves contradictory reports deterministically, and
produces an auditable decision trail that can be reproduced exactly via
replay.

Built for a time-boxed (~4 hour) hackathon submission. Scope was kept
deliberately narrow: no ML/LLM risk prediction, no auth, no UI, no
distributed infrastructure — see [Design decisions](#design-decisions--trade-offs)
and [Known limitations](#known-limitations) below for what that trade-off
looks like in practice.

## Architecture

The system is **event-sourced**: the `events` table is the only mutable
source of truth. Nothing else is stored as a row that gets updated in
place. A vessel's resolved risk state and its audit trail are *derived*
by re-running the same deterministic reconciliation logic over that
vessel's accumulated events, sorted chronologically — not incrementally
patched. This is what makes replay, idempotency, and determinism
tractable: the same event set always produces the same output, regardless
of what order it arrived in or how many times it's reprocessed.

```
HTTP request (raw JSON)
        |
        v
  FastAPI route (app/api/*.py)  -- thin: no business logic
        |
        v
  LangGraph pipeline (app/graph/pipeline.py)
    validate -> deduplicate -> load_history -> reconstruct_temporal
        -> resolve_conflicts -> generate_audit -> persist
        |
        v
  Domain layer (app/domain/*.py)  -- pure functions, no FastAPI/LangGraph imports
        |
        v
  SQLite (app/storage/*.py)  -- append-only events + audit_records tables
```

Layers:
- **API** (`app/api/`): parses requests, calls the graph, maps results to
  HTTP status codes. No reconciliation or conflict-resolution logic lives
  here.
- **Graph** (`app/graph/`): wires the domain functions into a LangGraph
  `StateGraph`. This is the single processing path used by both live
  ingestion and replay.
- **Domain** (`app/domain/`): pure, framework-independent functions —
  validation, deduplication, temporal ordering, conflict resolution,
  state reconciliation, audit export. Each is independently unit-tested
  with no HTTP or graph involved.
- **Storage** (`app/storage/`): SQLite connection/schema and CRUD. Two
  append-only tables: `events`, `audit_records`.

## Why LangGraph

The PRD asks for a "deterministic processing workflow" with named stages
(validate, deduplicate, reconstruct state, resolve conflicts, audit,
persist) shared identically between live processing and replay. LangGraph
gives that a shape: each stage is a small `StateGraph` node, wired with
explicit edges, so the control flow is visible and testable as a unit
rather than buried inside one large function. Rejection (failed
validation or a duplicate `event_id`) is a real conditional edge to `END`
— not a chain of `if` guards inside every downstream function — so a
rejected event provably never reaches history loading, conflict
resolution, or persistence.

No LLM is used anywhere in this graph. Every node is a deterministic
Python function over structured data, per the PRD constraint against
ML/LLM risk prediction.

## Event lifecycle

1. **Validate** — construct the event from raw JSON (`app/models/schemas.py`).
   Structural errors (missing fields, wrong types) and semantic errors
   (invalid `risk_signal`, unknown `source`, out-of-range
   `confidence_score`) both fail here. `risk_signal` is normalized to
   lowercase before the closed-set check, so `"HIGH"` and `"high"` are
   equivalent.
2. **Deduplicate** — reject if `event_id` already exists for this vessel's
   event log. This is checked before anything is persisted.
3. **Load history** — fetch the vessel's existing events, in arrival
   (storage) order — deliberately *not* pre-sorted, so temporal ordering
   is never accidentally inherited from SQL (see below).
4. **Reconstruct temporal state** — combine history + the new event and
   sort chronologically.
5. **Resolve conflicts** — walk the chronological sequence, comparing
   each event's `risk_signal` against the vessel's current resolved
   event; on a genuine disagreement, resolve the pair using the PRD's
   priority chain (see below).
6. **Generate audit** — build an audit record for the state affected by
   this event: `vessel_id`, `event_ids`, `resolved_risk_signal`,
   `resolution_reason`, `timestamp`.
7. **Persist** — write the event and its audit record. Only now does the
   event become visible to future dedup checks.

## Temporal reconciliation strategy

`app/domain/temporal.py::reconstruct_temporal_history` sorts events by
`(timestamp, event_id)` — never by arrival order. This is deliberately
separated from storage: `repository.get_events_for_vessel` returns events
in raw insertion order (`ORDER BY rowid`), specifically so that "arrival
order is not temporal order" is an explicit, tested guarantee rather than
an accident of a SQL `ORDER BY` clause. A late event (say, timestamped
11:50 but arriving after a 12:00 and a 12:10 event) is slotted into its
correct chronological position on every reconstruction, live or replayed.

Ties on timestamp are broken lexicographically by `event_id` — a stable,
deterministic rule that is **not** part of the PRD; it exists only
because sorting requires *some* total order, documented here rather than
left implicit in code.

## Conflict resolution rules

`app/domain/conflict_resolution.py::resolve_conflict` implements the
PRD's exact priority chain over a set of candidate events:

1. Higher `confidence_score` wins.
2. If tied, higher `source_reliability` wins.
3. If tied, earlier `timestamp` wins.
4. If still tied (confidence, reliability, *and* timestamp all identical),
   fall back to the lexicographically smallest `event_id`. This fourth
   tier is an implementation detail, not a PRD rule — the PRD's chain
   doesn't cover a fully-tied case, so a fallback was necessary to keep
   the function total and deterministic.

Every resolution returns a specific, human-readable explanation (e.g.
*"Weather (w1) selected: confidence_score tied at 0.8 among 2 candidates;
source_reliability 0.9 is the highest among them."*) rather than a vague
message like "risk resolved successfully" — this explanation is what
lands in the audit trail.

**What counts as "conflicting":** events are processed in chronological
order (`app/domain/temporal.py::reconstruct_temporal_history`), and the
vessel's *current resolved event* is tracked as a running pointer. Each
next event in that order is compared against it by `risk_signal` alone:

- **Same `risk_signal`** — no conflict. The new event is accepted as its
  own state entry and becomes the new current resolved event (the most
  recent confirming evidence).
- **Different `risk_signal`** — a real conflict. `resolve_conflict` is
  run on exactly `[current_resolved_event, incoming_event]`; the winner
  becomes the new current resolved event, which may still be the
  *previous* one, if it outranks the challenger.

This means a later, weaker report does not just get to become its own
independent state — it has to actually win a resolution against
whatever is currently established, and a strong early report can persist
across several weaker later ones that disagree with it.

*Revision note:* an earlier version of this rule treated two events as
conflicting only if they shared the exact same timestamp, exempting
events with any timestamp difference — however small — from resolution
entirely. That undertriggered on realistic asynchronous data and did not
match the PRD's own example (Weather HIGH vs. Regulatory LOW is not
described as simultaneous). It was revisited and replaced with the
current-vs-incoming rule above for better PRD alignment; there is no
longer a timestamp-matching condition on what counts as a conflict.

## Source reliability

Configured explicitly in `app/config.py`:

| Source                 | Reliability | Source in PRD |
|-------------------------|:-----------:|---------------|
| Weather                 | 0.9         | Yes |
| Regulatory Compliance    | 0.8         | Yes |
| Geopolitical Risk        | 0.7         | Yes |
| Port Congestion          | 0.6         | **No — assumed.** The PRD lists Port Congestion as one of the four sources but never gives it a reliability weight. 0.6 (lowest of the four) is an explicit engineering assumption, not a PRD value. |

## Deduplication / idempotency

Deduplication is keyed on `event_id` alone (the PRD's MVP-scope text
mentions "event ID and timestamp," but the functional requirement is
explicit: duplicate `event_id` → `409 Conflict`; `event_id` alone is the
more concrete, testable rule and the one implemented). The `events` table
enforces this with a `PRIMARY KEY` constraint as a backstop, but the
dedup check (`app/domain/deduplication.py`) runs first, before any other
processing.

Because the system is event-sourced (state is *derived*, never mutated in
place) and duplicates are rejected outright rather than reprocessed,
reprocessing the same event — or replaying the same batch twice — is a
true no-op: it changes nothing about persisted state.

## Audit trail

Every accepted event produces exactly one audit record
(`app/storage/db.py`, table `audit_records`): `audit_id` (= the
triggering `event_id`), `vessel_id`, `event_ids` (either just the event
itself, if it agreed with the current resolved state, or that state's
event plus this one, if it was a genuine conflict), `resolved_risk_signal`,
`resolution_reason`, `timestamp`. Audit records are append-only and
retrievable via `GET /vessels/{vessel_id}/audit`.

Note that an audit record reflects the world as it was known *at the
moment it was generated* — if event A is processed before event B, and B
later conflicts with A, A's audit record legitimately shows "no conflict"
while B's shows the resolved conflict. Both are correct historical
snapshots; neither is retroactively rewritten.

Decision-trace JSON files are generated separately from live request
handling — see [CLI replay](#cli-replay) and [Fixtures](#fixtures) below
— by `app/domain/audit_export.py`, not as an automatic side effect of
`POST /events`. This keeps the live API free of filesystem side effects
and keeps generated output byte-reproducible (no wall-clock timestamps
are included in exported content).

## Replay behavior

`POST /replay` and `replay_cli.py` both call the exact same
`app.graph.runner.replay_response` function, which drives the events
through `app.graph.pipeline.build_graph` — the identical graph used by
live processing. There is no second implementation.

**Design decision:** replay runs against a fresh, isolated in-memory
SQLite store, never the live database. This means:
- Replaying events that were already processed live does not collide
  with them (no spurious 409s).
- Replay output is a pure function of the submitted event list — nothing
  about the live system's state can leak in or be mutated.
- Live-vs-replay consistency is verified directly:
  `tests/test_replay.py::test_live_vs_replay_produce_identical_final_state_and_audit`
  posts a set of events through the real `POST /events` HTTP path, then
  replays the same events, and asserts the resulting state history and
  audit trail are identical.

`POST /replay` accepts a bare JSON array as the request body (`[event1,
event2, ...]`), matching the PRD's literal wording ("accepts a list of
events") rather than wrapping it in an object.

## Project structure

```
app/
  main.py                    FastAPI app factory, router wiring
  config.py                  valid risk signals, source reliability weights
  models/schemas.py          EventIn (Pydantic): validation + normalization
  domain/
    validation.py            risk_signal normalization/validation
    deduplication.py         event_id uniqueness check
    temporal.py               chronological ordering (arrival order != temporal order)
    conflict_resolution.py   the 4-tier priority chain
    state_reconciliation.py  combines temporal ordering + conflict resolution into RiskState history
    audit_export.py          decision-trace JSON export (not wired into live requests)
  graph/
    state.py                 GraphState TypedDict
    pipeline.py               the LangGraph StateGraph and its nodes
    runner.py                 shared live/replay event-sequence runner
  api/
    events.py                POST /events
    vessels.py                GET /vessels/{id}/history
    audit.py                  GET /vessels/{id}/audit
    replay.py                  POST /replay
  storage/
    db.py                     SQLite schema/connection
    repository.py             CRUD for events + audit_records
replay_cli.py                 CLI replay entrypoint
fixtures/                     5 scenario JSON files + README describing each
outputs/                      generated decision-trace JSON, one per fixture
tests/                        pytest suite (66 tests)
Dockerfile, .dockerignore
requirements.txt
```

## Setup

Requires Python 3.12+.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
```

## Run

```
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
```

SQLite storage defaults to `data/app.db` (created automatically on first
run; gitignored).

## Test

```
.venv\Scripts\python -m pytest tests/ -v
```

66 tests, covering validation, deduplication, temporal reconciliation,
conflict resolution, the LangGraph pipeline's determinism, audit
generation/retrieval, replay consistency/idempotency, and all 5 fixture
scenarios end to end.

## Docker

Build the image:

```
docker build -t maritime-risk-engine:latest .
```

Run the container:

```
docker run -d --name maritime-risk-engine -p 8000:8000 maritime-risk-engine:latest
```

Verify:

```
curl http://127.0.0.1:8000/health
```

Run the CLI replay script inside the running container:

```
docker exec maritime-risk-engine python replay_cli.py fixtures/03_conflicting_signals.json
```

Stop and remove:

```
docker stop maritime-risk-engine
docker rm maritime-risk-engine
```

Note: SQLite storage is inside the container's filesystem and is not
persisted across container removal (no volume is mounted). This is
consistent with the PRD's local/in-memory storage constraint; mount a
volume at `/app/data` if you need the database to survive a restart.

## CLI replay

```
python replay_cli.py fixtures/02_late_out_of_order.json
python replay_cli.py fixtures/02_late_out_of_order.json --output outputs/02_late_out_of_order_result.json
```

Reads a JSON array of events from a file, replays them through the same
graph as live processing (against a fresh isolated store), and prints the
resulting per-event outcomes plus each affected vessel's final state
history and audit trail. `--output` additionally writes that result to a
file.

## Fixtures

Five scenarios, each a JSON array of raw events, under `fixtures/` (see
`fixtures/README.md` for a description of each and its expected
outcome):

| File | Scenario |
|---|---|
| `01_duplicate_event.json` | Same `event_id` submitted twice |
| `02_late_out_of_order.json` | A late-arriving event must slot into correct chronological position |
| `03_conflicting_signals.json` | Same-timestamp contradictory reports, resolved by source reliability |
| `04_replay_consistency.json` | A richer timeline intended to be run both live and replayed |
| `05_multiple_vessels.json` | Two vessels interleaved, independent reconstruction |

Each has a corresponding generated output in `outputs/<name>_result.json`,
produced by actually running `replay_cli.py` against the fixture (not
hand-written). `tests/test_fixtures.py` re-runs every fixture and asserts
the result still matches the committed output, so fixtures and outputs
can't silently drift apart.

## Example API requests

Submit an event:
```
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{"event_id":"w1","source":"Weather","vessel_id":"MV-Atlas","risk_signal":"high","timestamp":"2026-08-15T12:00:00Z","confidence_score":0.8}'
```

A conflicting report for the same vessel and timestamp:
```
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{"event_id":"r1","source":"Regulatory Compliance","vessel_id":"MV-Atlas","risk_signal":"low","timestamp":"2026-08-15T12:00:00Z","confidence_score":0.8}'
```

Fetch the reconstructed, time-ordered raw event history:
```
curl http://127.0.0.1:8000/vessels/MV-Atlas/history
```

Fetch the audit trail:
```
curl http://127.0.0.1:8000/vessels/MV-Atlas/audit
```

Replay a batch (isolated from live state):
```
curl -X POST http://127.0.0.1:8000/replay \
  -H "Content-Type: application/json" \
  -d '[{"event_id":"w1","source":"Weather","vessel_id":"MV-Atlas","risk_signal":"high","timestamp":"2026-08-15T12:00:00Z","confidence_score":0.8}]'
```

## Design decisions / trade-offs

- **Event-sourced storage, not mutable state.** Chosen over incrementally
  patched state rows because it makes replay and determinism trivially
  correct: the same event set always reconstructs to the same result, by
  construction, rather than by careful incremental bookkeeping.
- **SQLite over pure in-memory.** The PRD allows either; SQLite was
  chosen because "audit records must be stored and retrievable" reads
  more naturally as durable storage, at no real cost (stdlib `sqlite3`,
  no new dependency).
- **Replay uses an isolated store, not the live database.** See
  [Replay behavior](#replay-behavior). The alternative (writing replay
  into the live store) would make replaying already-ingested events
  collide with 409s, defeating the point of testing consistency.
- **Conflict = differing `risk_signal` against the current resolved
  state**, not exact-timestamp match. See
  [Conflict resolution rules](#conflict-resolution-rules). An
  exact-timestamp-match version was tried first and rejected: it
  undertriggered on realistic asynchronous data and didn't match the
  PRD's own non-simultaneous example.
- **`event_id` is the sole dedup key**, not `event_id` + `timestamp` (the
  MVP-scope text mentions both; the functional requirement only specifies
  `event_id`).
- **Malformed input → 400, not FastAPI's default 422.** A custom
  `RequestValidationError` handler remaps this, and the graph's own
  `validate` node (used by both live and replay) raises the same 400
  semantics for input that never touches FastAPI's request-parsing layer.
- **No wall-clock timestamps in audit/export content.** Deliberately
  excluded so live and replayed output can be compared for exact
  equality in tests.
- **Decision-trace file export is a standalone function, not a live
  side effect.** Avoids filesystem writes on every request and keeps the
  isolated-DB test strategy simple.
- **No ML/LLM anywhere.** Per the PRD constraint; every decision in the
  graph is a deterministic Python function over structured fields.

## Known limitations

- **No authentication, no UI** — out of scope per the PRD.
- **No pagination** on `/vessels/{id}/history` or `/vessels/{id}/audit` —
  fine at fixture/demo scale, would need it for a vessel with a large
  event history.
- **No staleness/decay on the resolved state.** A strong early report
  (high confidence, reliable source) can persist as the resolved
  `risk_signal` indefinitely, outranking any number of later, weaker
  conflicting reports — there's no time-based decay that would let old
  evidence "expire" and yield to newer-but-weaker reports. The PRD does
  not specify one.
- **No validation rejects events older than 7 days.** The PRD's "must
  handle events up to 7 days in the past" is treated as a capability
  requirement, not an input-rejection rule (see PRD reading in code
  comments) — there's no upper bound enforced on how old an event can be.
- **SQLite is single-file, single-process.** No concurrent-write
  tuning beyond SQLite's defaults; fine for this scope, would need
  attention under real concurrent load.
- **Docker storage is ephemeral** unless a volume is mounted (see
  [Docker](#docker)).
- **Bonus/advanced PRD scope was not implemented**: no LangChain
  natural-language summaries, no time-shifted replay, no versioned state
  snapshots. These were explicitly out of MVP scope and excluded to keep
  the implementation within the time constraint.
