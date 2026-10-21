# Local dashboard 4

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
/selected/.venv/bin/python -I -B /selected/local-dashboard/4/dashboard.py --config /selected/project/dashboard.json
```

The command prints one JSON record with `url`, `view_urls.embedded` and `view_urls.browser`. Use the matching view URL as described below.
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
or rejected requests retain the ordinary page. Closing PiP does not reopen it
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
separately in the Foundry workspace. Earlier package revisions have local Chrome
fixture observations for native PiP, resizing, background updates and narrow
sidebar layout. Those observations do not establish version 4 visual acceptance. IAB opened PiP and immediately closed it in the observed environment;
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

## Cumulative work and step history (version 3)

The optional `business.work_progress` uses the same `completed`, positive `total`
and nonempty `label` shape as `completion`. It measures cumulative work only.
`completion` retains its original meaning: currently valid accepted checks. A
cumulative percentage never grants acceptance or hides an invalidation.

Optional `business.workflow` contains `steps` and, when known, `current_step_id`.
Each step has a unique nonempty `step_id` and a known display `state`; optional
`label`, `detail`, `evidence_refs` and `history` supply sanitized display text.
Each history entry has `state`, optional `label`, `detail` and `evidence_refs`.
The current ID, when present, must identify one of these steps. Unknown fields
are filtered. The host owns source interpretation and sanitization; never send
raw source text, logs, credentials or private paths. No extra acceptance rules,
commands or file access are introduced.

The sidebar shows named steps and lets readers select details and past records.
It retains that choice across updates and reconnects until the selection changes
or the step disappears. "返回当前步骤" resumes following the live current step.
PiP always follows that live step, including nearby named steps and a separate
step completion count. Both views share one cache and one subscription. Sources
without the optional fields retain the prior completion and step display.
Version 3 DOM fixtures check these interactions; native browser, PiP appearance
and human readability still require their own observations.

## Chat 打开与显示方式（版本 4）

同一观察服务输出两个地址：`view_urls.embedded` 用于 Codex 内嵌页，
`view_urls.browser` 用于外置浏览器。它们只相差 `?view=embedded`／`?view=browser`，
读取同一组已选记录和服务缓存；切换显示不启动业务、不重置进度或预算。

在 Chat 中可说“在内嵌侧边栏打开这个看板”或“用外置 Chrome 打开这个看板”。
宿主先确认所选项目、Program／prepared 或目标运行身份和已有观察配置；
已有同范围服务可复用，否则使用已绑定 Python 启动现有只读入口。
随后用实际可用的宿主浏览器工具打开对应地址：内嵌页使用 Codex 的浏览器面板，
外置页明确选择 Chrome。网页自身不启动浏览器、不把标签页移动到 Codex。
宿主没有相应工具时如实报告并给出本机地址，不把普通窗口称作画中画。
外置服务地址仅限本机，不能发送给另一设备或公开发布。

内嵌地址隐藏画中画与全屏按钮，保留完整页面、历史和重新连接。
外置地址按 `documentPictureInPicture.requestWindow` 与 Fullscreen API 的实际支持
分别显示按钮；没有显示提示的原地址同样按接口支持判断，不通过 User-Agent 猜测宿主。
`view` 只是宿主提供的展示提示，不是访问权限或可信浏览器身份。
复制地址到其他宿主时使用对应地址；不声称能自动识别所有内嵌浏览器。

画中画显示当前步骤、进度和异常；全屏使用真正的浏览器 Fullscreen API，支持退出全屏
和 Esc。两者须由用户点击触发，浏览器拒绝时保留普通页面并说明原因，不自动弹窗。
画中画与其主窗口共用一份前端状态和订阅；若同时另开内嵌页和 Chrome，则各有自己的
显示订阅，但仍共用同一服务采集缓存。关闭任何展示不停止业务。

## 阅读口径

首页优先展示累计工作、当前通过检查、当前步骤和待处理事项。累计工作 100% 不等于
当前验收全部有效，也不代表整个项目完成。任务、检查及范围编号帮助浏览，完整
prepared、Program、原步骤名称、状态说明和证据标识保留在详情中。
来源未提供完成总量时不猜百分比；结果未知不写成正在运行或失败。
历史选择不改变实时当前步骤，未读取记录不说明产物不存在。
这些文字与布局改进不改变原先的计数、接受、恢复或权限规则。

版本 1–3 保留原字节。项目须按现有选版／文件绑定流程选择版本 4 的完整包后重启
观察服务；旧部署和旧固定包不会自动获得此界面。本地工程和浏览器证据另记，不把
本次显示验证当作目标业务、跨设备或真人理解收益验收。
