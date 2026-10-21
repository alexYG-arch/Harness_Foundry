"""Human readback of existing facts; no controller, validation or I/O."""

import json


ATTEMPT_LABELS = {
    "ACCEPTED": "该次任务的声明检查已通过并记录，不代表整个项目完成",
    "REJECTED": "该次任务未通过检查",
    "BLOCKED": "该次任务被阻断，不应盲目重试",
    "UNKNOWN_SIDE_EFFECT": "执行影响尚未确认，不能视为成功或未执行",
    "IN_FLIGHT": "记录尚未完成，不证明进程仍在运行",
    "INVALIDATED": "此前接受结果已失效",
    "RETRY_ALLOWED": "已记录处置，尚未因此重新执行",
    "NOT_DISPATCHED": "该次尝试未派发，已用预算仍保留",
}
AUTHORIZATION_LABELS = {
    "SUPERSEDED": "已由明确接续的新范围替代，不能继续派发；历史保留",
    "APPROVED": "已批准；派发前仍会核对有效范围和剩余预算",
    "APPROVAL_REQUIRED": "该范围尚待用户批准",
    "EXPIRED": "已到期，不能复用此范围继续执行",
    "REVOKED": "已撤销，不能复用此范围继续执行",
}
ACTION_LABELS = {
    "RECONCILE_EFFECTS": "先核对执行影响，不盲目重放",
    "RECONCILE_COMMAND_OBSERVATIONS": "先核对命令观测，不盲目重放",
    "REPAIR_RUNTIME_ENVIRONMENT": "先检查运行环境，不自动重试业务；已用预算保留",
    "REPAIR_WITHIN_BUDGET": "仅在当前有效授权和剩余预算内修复",
    "NO_REPLAY": "不要重放该次已接受的任务",
    "ADVANCE_WITH_CURRENT_SCOPE_AND_BUDGET": "仅在当前有效授权和剩余预算内推进",
    "REBUILD_AFFECTED_BRANCH_WITHIN_BUDGET": "仅在当前有效授权和剩余预算内重建受影响分支",
    "ALIGN_PUBLIC_CONTRACT_AND_VERIFIER": "先明确公开约定与检查器的冲突，不自动重试",
    "INSPECT": "先检查原始记录",
}


def _value(value):
    # Keep supplied identifiers and text distinguishable from display headings.
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def render_build_readback(result):
    """Render read-build results, retaining original status/error identifiers.

    Attempts and grants include history: do not derive new acceptance or choose
    a runnable grant from their display order. The controller remains authority.
    """
    if result.get("status") != "BUILD_READBACK":
        return ("结果：未能读取建设状态；不能据此判断任务是否完成。\n"
                "原始返回（错误码与详情保留）：\n"
                + json.dumps(result, ensure_ascii=False, indent=2))
    proposal = result["proposal"]
    binding = proposal["proposal_binding"]
    attempts = result["attempts"]
    lines = [
        "结果：已读取建设记录（BUILD_READBACK）；本次读取未启动任务。",
        f"项目：{_value(result['program_id'])}；记录版本：{result['stream_revision']}",
        f"当前计划：{_value(binding['plan_id'])}，版本 {binding['plan_revision']}；"
        f"需求版本：{binding['requirement_revision']}",
        f"计划记录：{_value(binding['proposal_event_id'])}",
        "边界：这是状态摘要，不替代完整需求、计划和授权范围。不是新的授权或验收决定。",
    ]
    if result.get("harness_e2e_verified") is False:
        lines.append("未验证：本返回未确认 Harness 端到端可用，也不证明完整需求或发行验收通过。")
    review = result["document_review"]
    review_status = review.get("status")
    if review_status == "HUMAN_DOCUMENT_CONFIRMATION_RECORDED":
        lines.append(f"搭建文档：已记录用户确认，版本 {_value(review.get('version'))}；"
                     "本次未重新核对文档文件，文档确认不等于运行授权。")
    else:
        lines.append(f"搭建文档：{_value(review_status)}；本摘要不代替文档确认。")
    lines.extend(["", "授权与预算（含历史范围，不自动选择可执行范围）："])
    if not result["authorizations"]:
        lines.append("- 尚无准备好的运行范围；此读取不准备或授予授权。")
    for grant in result["authorizations"]:
        state = grant["state"]
        budget = grant["budget"]
        relation = "当前计划" if grant["proposal_event_id"] == binding["proposal_event_id"] else "历史计划"
        lines.append(f"- {_value(grant['prepared_event_id'])}（{relation}）：{_value(state)}；"
                     + AUTHORIZATION_LABELS.get(state, "未识别状态，请查看原始 JSON"))
        lines.append(f"  尝试次数：已用 {budget['attempts_consumed']}，剩余 {budget['attempts_remaining']}；"
                     f"到期时间：{_value(grant['scope']['expires_at'])}")
        if grant.get("rebind_from"):
            lines.append(f"  接续来源：{_value(grant['rebind_from'])}；累计预算不重置；本范围已用 {budget['this_preparation_attempts']}。")
        if grant.get("superseded_by"):
            lines.append(f"  后续范围：{_value(grant['superseded_by'])}")
        resources = grant["scope"].get("verification_resources")
        if resources:
            lines.append(f"  默认验收运行目录：{_value(grant['scope']['workspace_root'])}（产品只读）；"
                         f"独立资源根：{_value(resources['root'])}")
            for name, profile in resources["profiles"].items():
                lines.append(f"  资源配置 {_value(name)}：{_value(profile['network'])}；"
                             f"可写区域：{_value(profile['writable_areas'])}；判定：STRUCTURED_V1")
                if "product_copy" in profile:
                    copy = profile["product_copy"]
                    lines.append(f"    在本次产品副本中验收；复制文件：{_value(copy['files'])}；"
                                 f"副本内可写生成目录：{_value(copy['writable_paths'])}；正式产品不写入。")
                for alias, credential in profile.get("credentials", {}).items():
                    lines.append(f"    测试凭据 {_value(credential['ref'])} → FOUNDRY_CREDENTIAL_{_value(alias)}；"
                                 f"用途：{_value(credential['purpose'])}；只在该检查命令运行时解析，引用不授予网络权限。")
            lines.append("  网络能力：Unix socket 使用声明路径；显式 TCP LOOPBACK 的原生授权允许 TCP/UDP 回环全部端口，"
                         "保留原生 53 端口例外，不隔离其他本机服务；外联代理不承诺端口或业务操作限制。")
    if result.get("repair_requests"):
        lines.extend(["", "外层 Codex 已核实的返修请求（保留历史，登记不等于已修复）："])
        for repair in result["repair_requests"]:
            lines.append(f"- {_value(repair['event_id'])}；范围：{_value(repair['workpack_ids'])}")
            lines.append(f"  原因：{_value(repair['finding']['reason'])}；"
                         f"修复目标：{_value(repair['finding']['repair_goal'])}")
    lines.extend(["", "任务尝试（按记录顺序，包含历史；不合并为当前计划的完成结论）："])
    if not attempts:
        lines.append("- 尚无任务执行记录；不能据此声称已实现或已验证。")
    for attempt in attempts:
        status = attempt["status"]
        lines.append(f"- 任务 {_value(attempt['workpack_id'])} / 尝试 {_value(attempt['attempt_id'])}："
                     f"{_value(status)}；" + ATTEMPT_LABELS.get(status, "未识别状态，请查看原始 JSON"))
        lines.append(f"  范围：{_value(attempt['prepared_event_id'])}；阶段：{_value(attempt['phase'])}")
        recovery = attempt["recovery"]
        action = recovery["next_action"]
        lines.append(f"  恢复建议：{ACTION_LABELS.get(action, '未识别动作，请查看原始 JSON')}"
                     f"（{_value(action)}）；责任方：{_value(recovery['owner'])}")
        lines.append(f"  证据尝试：{_value(recovery['evidence_attempt_id'])}；"
                     f"最小恢复路径：{_value(recovery['minimum_return_path'])}")
        for command in attempt.get("resource_commands", []):
            lines.append(f"  资源检查 {_value(command['case_id'])}：实际网络 {_value(command['effective_network_policy'])}；"
                         f"清理 {_value(command['cleanup'])}；报告 {_value(command['observation_root'])}")
            copy = command.get("binding", {}).get("product_copy")
            if copy:
                lines.append(f"    本次副本运行目录：{_value(copy['root'])}；"
                             f"副本写域：{_value(copy['write_roots'])}")
        if status != "ACCEPTED":
            if "reason" in attempt:
                lines.append(f"  原因（原始记录）：{_value(attempt['reason'])}")
            command = attempt.get("last_command", {})
            if "result" in command:
                lines.append(f"  最后命令结果（原始记录）：{_value(command['result'])}")
            for check in attempt.get("verification", []):
                lines.append(f"  检查证据（原始记录）：{_value(check)}")
    lines.extend(["", "下一步：按对应记录的恢复建议处理；实际派发仍由现有控制器核对范围、预算和未决影响。",
                  "需要完整需求、权限、路径、检查结果或观测附件时，使用同一 read-build 命令的 --json 输出。",
                  "本输出不新增逐任务审批，也不会自动推进任务。"])
    return "\n".join(lines)
