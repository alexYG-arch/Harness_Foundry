# Harness Foundry Controlled Execution Runtime guidance

- Python 3.11+ and the standard library are the default implementation surface.
- SQLite under each execution root is the authoritative Event Store. JSON and
  JSONL files are derived read views and must be reproducible.
- Never infer execution authorization from Start Package or bootstrap approval.
- Never reuse a legacy authorization in a new control-plane epoch.
- Default to `A1_PLAN_ONLY`; require an exact, active, unexpired
  `A3_PROGRAM_BOUNDED` authorization for continuous advance.
- Never auto-cross a declared human gate, real target install, P3 N/A, scope
  expansion, waiver, unknown non-idempotent outcome, Hash drift, exhausted
  budget, no-progress stop, or oscillation stop.
- Keep one Active Workpack or Active Pipeline Attempt globally and use
  reservation plus fencing for every transition.
- Treat candidate and legacy roots as read-only. Migration may write only a
  new empty execution root.
- Run `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`
  after implementation changes.
