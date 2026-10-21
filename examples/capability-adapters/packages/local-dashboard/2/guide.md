# Local dashboard 2

Optional display component for a host that already owns a selected run. It does
not start, approve, repair, reverify, or recover business work. Protocol 2.9 and
the original budget remain with the original controller.

Select this package and its explicit version through the existing capability
prepare/consume helpers. Deliver the complete package layout (including
`capability.json` and `web/`) and keep project labels, adapters, source locations
and custom configuration outside it. The host uses the selected interpreter
invocation path, preserving virtual environment semantics. A component upgrade
takes effect when this observer restarts; it does not restart the business.

## Host entry

```sh
/selected/.venv/bin/python -I -B /selected/local-dashboard/2/dashboard.py --config /selected/project/dashboard.json
```

The command prints one JSON record with the local URL. Open that exact URL.
Use the foreground process's Ctrl-C / SIGTERM, or Python `Observer.stop()`, to
stop this observer. There is no browser shutdown, command, approval or arbitrary
file API. The URL has an observer-local random prefix and must remain private.
Only 127.0.0.1 is bound; local access does not authorize any business networking.
The host can choose `--port` (default 0, an available port),
`--poll-seconds` (default 1) and `--idle-seconds` (default 300; 0 disables idle
exit). An active SSE connection keeps the observer alive; closing the last
connection starts the idle period after its disconnection is observed.

Configuration names only selected display files, relative to the config file:

```json
{
  "runs": [{
    "id": "current",
    "selection": {
      "kind": "harness_run",
      "project_id": "example",
      "project_version": "candidate-1",
      "run_id": "task-001"
    },
    "source": "display/task-001.json"
  }]
}
```

Each source contains the same `selection`, a `business` object and optional
`observation.activity`. The producer should replace the source file atomically.
Incomplete reads retain the last valid display and mark the read gap; they do
not change the business result or replay commands. The observer never writes
these files. Foundry adapters also bind `program_id` and `prepared_event_id`.
The Foundry source workspace now supplies the WP06 adapter described below.
WP08 supplies the optional [target-native adapter](target-guide.md) for explicit
DATA, DOC and supplied host-review records. An arbitrary display JSON is not
proof of either real business integration or acceptance.

For Foundry selections, the selector and summaries keep Program/prepared scope
distinguishable even when project, version and run match. Compact PiP shows a
short scope identity; full identity remains available in sidebar details. This
presentation does not change complete-selection cache or subscription isolation.
Target adapters do not acquire a requirement to provide Foundry-specific fields.

```json
{
  "selection": {
    "kind": "harness_run",
    "project_id": "example",
    "project_version": "candidate-1",
    "run_id": "task-001"
  },
  "business": {
    "source_revision": 3,
    "scope_ref": "scope-001",
    "title": "Example task",
    "current": "Check the exported result",
    "completion": null,
    "items": [{"item_id": "export", "label": "Export", "state": "PENDING", "evidence_refs": []}],
    "pending": [],
    "recent": []
  },
  "observation": {"activity": {"last_output_at": null}}
}
```

An explicit `completion` may contain `completed`, `total` and `label`.
Without a valid denominator use null. The component does not infer completion
from item state, output, attempts, heartbeats or elapsed time. `budget`, when
present, displays the original `attempts_consumed`/`attempts_remaining` values
once; it is not a new budget. The adapter owns unique item identities, current
acceptance/invalidations, scope and coherent source version. Absence of a record
does not prove that work never happened.

Optional `business.steps` supplies actual steps from the same coherent source
snapshot. Each step has a unique `step_id` and a `state`, with optional
`label`, `detail` and `depends_on` (IDs of existing plan dependencies).
`business.current_step_id` may be omitted or null; when set, it identifies a step
in that snapshot. These are display
fields, not new protocol events, execution commands or acceptance rules.
Existing sources without steps remain supported; do not invent a fixed pipeline.
Step status or count does not change the separate `completion` denominator.
A recorded start is not evidence that work is still running now; preserve
unknown or awaiting-verification states when current activity is unconfirmed.

The same boundary is available as ordinary Python:
`Observer({id: {"selection": selection, "reader": callable}})`.
The callable performs a bounded read-only read and returns the above object.
It must finish promptly; Python cannot forcibly cancel an arbitrary blocked
callback. Keep database transactions short, release them before returning, and
do not execute business commands in the reader. Service startup, failure and
cleanup must not become a business dependency.

## Privacy, transport and presentation

Adapters supply already sanitized display strings and evidence identifiers.
The component strips fields outside the display contract and reports fixed
error codes instead of exception text. It cannot recognize an arbitrary secret
inside an allowed title/string: do not supply raw logs, environment variables,
credentials or private filesystem paths as display text. Evidence references
are text identifiers; access continues through the original host, not a new
file browser. All frontend code is local, with no CDN or telemetry.

One collector/cache per complete selection serves all subscribed views.
Every SSE subscription starts with a complete current snapshot; all later
events also replace the state in full, so coalescing or reconnecting does not
require historical replay. The observer session and sequence are transport
identities, separate from the business source revision. Read activity continues
even when the business revision is unchanged.

The page uses a single connection for the selected run and mirrors its cache
into Document Picture-in-Picture. The user clicks to request PiP; unsupported
or rejected requests retain the full sidebar. Closing PiP does not reopen it
or stop the business. The sidebar expands the step list and details; PiP emphasizes progress,
the current step, distinguishable scope and exceptional/pending states from the
same frontend state. Surface type selects the layout and window width/height
adjust density, so a narrow sidebar remains an expanded view. Full identifiers,
history, evidence and budget stay accessible in sidebar details. This is a
presentation change, not a second subscription or observer.
Browser/environment support, actual PiP, background
updates and readability require real browser observations. Engineering fixture
tests do not establish real Foundry/target acceptance, cross-device support,
human understanding or performance benefit.

## Foundry host adapter (WP06)

The Foundry source workspace provides
`examples/capability-adapters/foundry_dashboard.py` as a host entrypoint. This
adapter is outside the reusable package; target Harness delivery does not gain a
Foundry controller dependency. Use the existing capability preparation output
for the selected `local-dashboard` and Python binding. The adapter calls
`consume.prepare_call()` before loading the selected package's `Observer`.

The in-process host verifies its interpreter call path against the selected binding,
preserving distinct virtual environments even when they share a binary.
It does not switch interpreters or install dependencies automatically.

Run the host entrypoint with the selected project interpreter and
`--config /selected/host/foundry-dashboard.json`. Its configuration contains a
`materials` path and `runs`, each with `id`, `control_db` and a complete
`foundry_build` selection including `program_id` and `prepared_event_id`.
Relative paths resolve from the configuration directory. The project ID is
checked against the prepared target; project version is an explicit host display
label, not inferred from a plan revision. Use a clear undeclared-version label
when no delivery version is known.

The adapter reads one event list for the explicit prepared scope, uses existing
acceptance, invalidation, continuation and budget projections, and supplies only
allowlisted display fields. Original commands, paths, source text and logs stay
with the host. Completion describes that scope's currently accepted declared
checks. Candidate acceptance does not imply apply; an explicitly selected apply
scope may display its recorded acceptance without claiming full Harness
acceptance. Activity and natural expiry can
change without a new event revision. Refreshing or reconnecting never advances,
recovers or replays the business. Host `--port`, `--poll-seconds` and
`--idle-seconds`, Ctrl-C/SIGTERM and Python lifecycle use the same Observer API.

WP06 source integration is implemented; its engineering verification is recorded
separately in the Foundry workspace. This revision also has local Chrome fixture
observations for native PiP, resizing, background updates and narrow sidebar
layout. IAB opened PiP and immediately closed it in the observed environment;
this is not a claim that all hosts lack support. Real new-task UI, complete PiP/
background coverage for both dashboard types, target-owned integration, cross-device
validation and measured benefit remain separate unverified scopes. Historical source reads do not reconstruct live
UI or performance evidence from the original execution.

## Project theme preference (version 2)

The external observer configuration may set `"theme": "system"`, `"light"` or
`"dark"`. Omitting it preserves the former system-color behavior. `system`
follows the operating-system color scheme; explicit light/dark takes precedence
in both the sidebar and native Document PiP. No theme editor, browser storage,
new business subscription or business operation is added. The configuration is
read at observer startup; changing it requires only an observer restart.

Keep the preference outside the component. Upgrade the selected package and its
file binding through the existing component-upgrade path, preserving the theme
value, run mappings, labels and native evidence. A config that also contains the
component binding must update those binding fields; do not claim its entire file
is unchanged. The historical version 1 package remains available.

The Foundry host adapter passes an explicit theme only to a component supporting
this interface. Existing version 1 selections without a theme continue to work;
an explicit unsupported preference is diagnosed instead of silently ignored.
Engineering tests do not prove native PiP appearance or user readability.
