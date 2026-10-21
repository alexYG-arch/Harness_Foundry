"""Read one explicit Foundry scope for the optional observation component.

Execution and acceptance remain in the existing controller. Each read uses one
event list; process diagnostics are separate observations, never recovery or
permission to execute. Only the display projection is suitable for a browser.
"""

from datetime import datetime, timezone
from pathlib import Path

from .build_display import ACTION_LABELS, AUTHORIZATION_LABELS
from .build_entrypoint import _database, _program, _scope_readback
from .build_rebind import reverification_candidates
from .build_state import project_execution_state, project_readback_attempts
from .build_types import RequestValidationError
from .process_observation import CommandObservation
from .revision_store import RevisionControlEventStore


def read_build_scope(control_db, program_id, prepared_event_id):
    """Read persisted scope facts, without selecting or advancing an authority."""
    program_id = _program(program_id)
    if not isinstance(prepared_event_id, str) or not prepared_event_id.strip():
        raise RequestValidationError("an explicit prepared event ID is required")
    store = RevisionControlEventStore(_database(control_db), read_only=True, storage_format="REVISION_V1")
    events = store.list_events(program_id)
    prepared = next((event for event in events
                     if event["event_type"] == "BUILD_AUTHORIZATION_PREPARED"
                     and event["event_id"] == prepared_event_id), None)
    if prepared is None:
        raise RequestValidationError("prepared scope does not exist for this Program")
    execution_proposal_id = next((event["payload"]["proposal_event_id"] for event in reversed(events)
                                  if event["event_type"] == "BUILD_ATTEMPT_STARTED"
                                  and event["payload"].get("prepared_event_id") == prepared_event_id),
                                 prepared["payload"]["proposal_event_id"])
    execution_proposal = next((event for event in events
                               if event["event_type"] == "BUILD_PLAN_PROPOSED"
                               and event["event_id"] == execution_proposal_id), None)
    if execution_proposal is None:
        raise RequestValidationError("recorded execution proposal does not exist for this Program")
    execution_attempts, accepted = project_execution_state(events, prepared_event_id)
    attempts = [row for row in project_readback_attempts(events).values()
                if row["prepared_event_id"] == prepared_event_id]
    attempt_revisions = {event["payload"]["attempt_id"]: event["stream_revision"] for event in events
                         if event["payload"].get("prepared_event_id") == prepared_event_id
                         and event["payload"].get("attempt_id")}
    invalidations = [{"event_id": event["event_id"], "stream_revision": event["stream_revision"],
                      **event["payload"]} for event in events
                     if event["event_type"] == "BUILD_ACCEPTANCE_INVALIDATED"
                     and event["payload"].get("prepared_event_id") == prepared_event_id]
    command_observations = {}
    for event in events:
        payload = event["payload"]
        if (event["event_type"] in {"BUILD_COMMAND_PLANNED", "BUILD_COMMAND_STARTED", "BUILD_COMMAND_OBSERVED"}
                and payload.get("prepared_event_id") == prepared_event_id and payload.get("observation_root")):
            key = (payload["attempt_id"], payload["observation_root"])
            command_observations[key] = {"attempt_id": key[0], "observation_root": key[1]}
    for row in attempts:
        row["last_record_revision"] = attempt_revisions[row["attempt_id"]]
        command = row.get("last_command", {})
        if row["status"] in {"UNKNOWN_SIDE_EFFECT", "IN_FLIGHT"} and command.get("observation_root"):
            row["recovery"]["host_observation"] = CommandObservation.inspect(command["observation_root"])
    return {"status": "BUILD_SCOPE_READBACK", "program_id": program_id,
            "stream_revision": len(events), "authorization": _scope_readback(prepared, events),
            "execution_plan": execution_proposal["payload"]["plan"],
            "execution_proposal_event_id": execution_proposal_id,
            "execution_attempts": execution_attempts, "accepted": accepted, "attempts": attempts,
            "invalidations": invalidations, "command_observations": list(command_observations.values()),
            "reverification_pending": sorted(reverification_candidates(events, prepared_event_id)),
            "writes_performed": False, "harness_e2e_verified": False}


_ITEM_STATES = {
    "ACCEPTED": "ACCEPTED", "INVALIDATED": "INVALIDATED", "REJECTED": "FAILED",
    "BLOCKED": "WAITING", "IN_FLIGHT": "UNKNOWN", "UNKNOWN_SIDE_EFFECT": "UNKNOWN",
    "RETRY_ALLOWED": "PENDING", "NOT_DISPATCHED": "NOT_RUN",
}
_ATTEMPT_TITLES = {
    "ACCEPTED": "声明检查已接受", "INVALIDATED": "原接受已失效", "REJECTED": "检查未通过",
    "BLOCKED": "运行被阻断", "IN_FLIGHT": "尝试待结算", "UNKNOWN_SIDE_EFFECT": "执行影响待核对",
    "RETRY_ALLOWED": "已记录允许继续", "NOT_DISPATCHED": "未派发，已用预算保留",
}
_PHASES = {"IMPLEMENTATION": "实施", "VERIFICATION": "独立检查", "NOT_DISPATCHED": "尚未派发"}
_OWNERS = {"LOCAL_OPERATOR": "本机操作者", "BUILD_CONTROLLER": "原控制器"}
_HOST_STATES = {
    "DURABLE_RESULT_AVAILABLE": "已有持久观测，等待原控制器归并；不重放命令",
    "START_NOT_OBSERVED": "派发窗口待核对；不推断已执行或未执行",
    "COMPLETION_NOT_OBSERVED": "完成观测尚缺；不以进程存在判断完成",
}


def _refs(row):
    return [f"{label} {row[key]}" for key, label in (
        ("prepared_event_id", "Prepared"), ("proposal_event_id", "Proposal"),
        ("attempt_id", "Attempt"), ("reverification_of_attempt_id", "复验来源 Attempt")) if row.get(key)]


def _recovery_text(row):
    recovery = row.get("recovery", {})
    action = recovery.get("next_action", "INSPECT")
    action_label = ACTION_LABELS.get(action, ACTION_LABELS["INSPECT"])
    action_code = action if action in ACTION_LABELS else "INSPECT"
    owner = recovery.get("owner")
    owner_label = _OWNERS.get(owner, "原记录待核对")
    owner_code = f" / {owner}" if owner in _OWNERS else ""
    return (f"{row['workpack_id']}：{action_label}（{action_code}）；"
            f"责任方 {owner_label}{owner_code}；Attempt {row['attempt_id']}")


def _output_activity(command_observations):
    """Stat explicitly bound commands in this scope; never scan or read output."""
    latest = None
    gaps = []
    for row in command_observations:
        root = row["observation_root"]
        try:
            for name in ("stdout.bin", "stderr.bin"):
                output = Path(root) / name
                if output.exists():
                    timestamp = output.stat().st_mtime
                    latest = timestamp if latest is None else max(latest, timestamp)
        except OSError:
            gaps.append(f"Attempt {row['attempt_id']}：输出活动元数据暂不可读")
    return ({"last_output_at": datetime.fromtimestamp(latest, timezone.utc).isoformat()
             if latest is not None else None}, gaps)


def read_foundry_projection(control_db, selection):
    """Return only WP05 display fields, fixed labels and original identity refs.

    Project/version/run labels are explicitly supplied by the viewing host.
    The project is checked against the chosen scope; version is not inferred
    from a plan revision. No paths, argv, source text or raw output are exported.
    """
    names = ("kind", "project_id", "project_version", "run_id", "program_id", "prepared_event_id")
    if (not isinstance(selection, dict) or selection.get("kind") != "foundry_build"
            or any(not isinstance(selection.get(key), str) or not selection[key].strip() for key in names)):
        raise RequestValidationError("Foundry observation requires an explicit complete selection")
    selection = {key: selection[key] for key in names}
    result = read_build_scope(control_db, selection["program_id"], selection["prepared_event_id"])
    grant = result["authorization"]
    if grant["requirement_ir"]["target"]["id"] != selection["project_id"]:
        raise RequestValidationError("selected project differs from the prepared scope target")
    accepted = result["accepted"]
    pending_reverification = set(result["reverification_pending"])
    latest = {row["workpack_id"]: row for row in result["attempts"]}
    invalidated = {identity: event for event in result["invalidations"] for identity in event["workpack_ids"]}
    plan = result["execution_plan"]
    proposal_id = result["execution_proposal_event_id"]
    current_workpacks = {task["workpack_id"] for task in plan["workpacks"]}
    items, steps, pending, recent, gaps = [], [], [], [], []
    attention = []
    for task in plan["workpacks"]:
        identity = task["workpack_id"]
        row = latest.get(identity)
        invalidation = invalidated.get(identity)
        refs = [f"Prepared {selection['prepared_event_id']}", f"Proposal {proposal_id}"]
        if proposal_id != grant["proposal_event_id"]:
            refs.append(f"原授权 Proposal {grant['proposal_event_id']}")
        if identity in accepted:
            record = accepted[identity]
            reused = record["prepared_event_id"] != selection["prepared_event_id"]
            label = "合法复用的已接受成果" if reused else "声明检查已接受"
            state = "ACCEPTED"
            refs = list(dict.fromkeys([*refs, *_refs(record)]))
        elif invalidation and (row is None or invalidation["stream_revision"] > row["last_record_revision"]):
            label, state = "原接受已失效，等待范围内修复与复验", "INVALIDATED"
            refs.append(f"Event {invalidation['event_id']}")
            pending.append(f"{identity}：已有接受失效记录；受影响分支修复与复验沿原控制器；Event {invalidation['event_id']}")
        elif identity in pending_reverification:
            label, state = "保留旧产物，待独立复验", "PENDING"
            if row:
                label = "只复验待结算；保留旧产物" if row["status"] == "IN_FLIGHT" else "只复验尚待完成"
                state = _ITEM_STATES.get(row["status"], "UNKNOWN")
                refs.extend(_refs(row))
                pending.append(_recovery_text(row))
            else:
                pending.append(f"{identity}：待原控制器只复验；未重新执行产品实施")
        elif row:
            label = _ATTEMPT_TITLES.get(row["status"], "原记录状态待核对")
            state = _ITEM_STATES.get(row["status"], "UNKNOWN")
            refs.extend(_refs(row))
            if row["status"] != "ACCEPTED":
                pending.append(_recovery_text(row))
        else:
            label, state = "尚无本范围尝试或有效接受记录", "NOT_STARTED"
            pending.append(f"{identity}：尚未完成本范围声明检查，后续推进沿原控制器")
        items.append({"item_id": identity, "label": f"{identity} · {label}",
                      "state": state, "evidence_refs": list(dict.fromkeys(refs))})
        # These are the adopted plan's workpacks, not invented model phases or
        # another completion denominator. A recorded command phase does not
        # establish that a command is still running when the view is read.
        detail = label
        if row and row.get("last_command"):
            detail = f"最近记录阶段：{_PHASES.get(row.get('phase'), '阶段待核对')}；{label}"
        steps.append({"step_id": identity, "label": identity, "state": state,
                      "detail": detail, "depends_on": list(task["depends_on"])})
        if identity not in accepted:
            revision = max(row["last_record_revision"] if row else 0,
                           invalidation["stream_revision"] if invalidation else 0)
            attention.append((revision, -len(steps), identity))
    for row in reversed(result["attempts"]):
        status = row["status"]
        label = _ATTEMPT_TITLES.get(status, "原记录状态待核对")
        phase = _PHASES.get(row.get("phase"), "阶段待核对")
        recent.append(f"Attempt {row['attempt_id']} · {row['workpack_id']} · {phase} · {label}（历史尝试）")
        if row.get("reverification_of_attempt_id"):
            recent.append(f"Attempt {row['attempt_id']}：只复验来源 Attempt {row['reverification_of_attempt_id']}")
        current_unaccepted = (row["workpack_id"] in current_workpacks
                              and latest.get(row["workpack_id"]) is row and row["workpack_id"] not in accepted)
        diagnostics = gaps if current_unaccepted else recent
        if row.get("implementation_observation_status") == "MISSING_OBSERVATION":
            diagnostics.append(f"Attempt {row['attempt_id']}：该次实施报告观测不完整，沿原记录核对，不重放命令")
        host = row.get("recovery", {}).get("host_observation", {})
        if host.get("observation_state") in _HOST_STATES:
            diagnostics.append(f"Attempt {row['attempt_id']}：{_HOST_STATES[host['observation_state']]}")
        for command in row.get("resource_commands", []):
            cleanup = command.get("cleanup")
            if isinstance(cleanup, dict) and cleanup.get("status") == "CLEANUP_WARNING":
                recent.append(f"Attempt {row['attempt_id']}：资源清理警告，仅为诊断，不改变原接受状态")
    plan_basis = "最近尝试已采用" if result["attempts"] else "原 Prepared 绑定，尚无本范围尝试"
    recent.append(f"本范围展示计划 {plan['plan_id']} · revision {plan['revision']}（{plan_basis}）；"
                  f"Proposal {proposal_id}；原授权 Proposal {grant['proposal_event_id']}；"
                  f"原绑定来源 Event {grant['source_binding']['source_event_id']}；"
                  "此计划版本不代表已安装的产品版本")
    state = grant["state"]
    current = AUTHORIZATION_LABELS.get(state, "授权状态待核对")
    if state in AUTHORIZATION_LABELS:
        current = f"{state} · {current}"
    if grant.get("superseded_by"):
        pending.insert(0, f"当前显示历史范围；接续 Prepared {grant['superseded_by']}，未自动切换")
    if state in {"APPROVAL_REQUIRED", "EXPIRED", "REVOKED"}:
        pending.insert(0, current)
    activity, activity_gaps = _output_activity(result["command_observations"])
    gaps.extend(activity_gaps)
    business = {
        "title": "Foundry 已选范围只读观察", "current": current,
        "scope_ref": selection["prepared_event_id"], "proposal_ref": proposal_id,
        "source_revision": {"stream_revision": result["stream_revision"]},
        "items": items, "steps": steps,
        "completion": {"completed": sum(item["item_id"] in accepted for item in items),
                       "total": len(items), "label": "本范围声明检查已接受成果（非完整 Harness 验收）"} if items else None,
        "budget": {key: grant["budget"][key] for key in ("attempts_consumed", "attempts_remaining")},
        "pending": pending, "recent": recent,
    }
    if attention:
        # A viewing focus only: latest unresolved record, or the first pending
        # workpack if no local record exists. It never selects a task to run.
        business["current_step_id"] = max(attention)[2]
    return {"selection": selection, "business": business,
            "observation": {"activity": activity, "gaps": list(dict.fromkeys(gaps))}}
