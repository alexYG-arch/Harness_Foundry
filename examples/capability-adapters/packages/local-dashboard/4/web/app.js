/* One source subscription; embedded, fullscreen and Document PiP render the same state. */
(() => {
  "use strict";

  const selector = document.getElementById("run-selector");
  const dashboard = document.getElementById("dashboard");
  const notice = document.getElementById("view-notice");
  const pipButton = document.getElementById("pip-button");
  const fullscreenButton = document.getElementById("fullscreen-button");
  const reconnectButton = document.getElementById("reconnect-button");
  // An explicit host hint avoids pretending that WebView API exposure proves support.
  const embedded = new URL(document.baseURI).searchParams.get("view") === "embedded"
    || Boolean(window.top && window.top !== window);
  const canPip = !embedded && Boolean(window.documentPictureInPicture
    && typeof window.documentPictureInPicture.requestWindow === "function");
  const canFullscreen = !embedded && document.fullscreenEnabled === true
    && typeof document.documentElement.requestFullscreen === "function"
    && typeof document.exitFullscreen === "function";
  const identityFields = ["kind", "project_id", "project_version", "run_id", "program_id", "prepared_event_id"];
  const statusLabels = {
    ACCEPTED: ["✓", "检查已接受", "accepted"],
    COMPLETED: ["✓", "已完成", "accepted"],
    PASS: ["✓", "检查通过", "accepted"],
    RUNNING: ["●", "进行中", "running"],
    IN_PROGRESS: ["●", "进行中", "running"],
    PENDING: ["○", "待处理", "waiting"],
    WAITING: ["○", "等待", "waiting"],
    NOT_STARTED: ["—", "未开始", "unknown"],
    NOT_RUN: ["—", "未运行", "unknown"],
    FAILED: ["!", "失败", "failed"],
    FAIL: ["!", "检查未通过", "failed"],
    ERROR: ["!", "检查异常", "failed"],
    INVALIDATED: ["!", "原结果已失效", "waiting"],
    UNKNOWN: ["?", "待核实", "unknown"]
  };
  const state = {
    runs: [], selected: null, snapshot: null, theme: "system", connection: "connecting",
    connectionMessage: "正在读取运行列表", lastReceived: null,
    session: null, sequence: -1, retiredSessions: new Set(), viewedStepId: null
  };
  let source = null;
  let generation = 0;
  let listGeneration = 0;
  let pipWindow = null;
  let pipDashboard = null;
  let pipOpening = false;
  let fullscreenChanging = false;
  let pipRequest = 0;

  function text(value, fallback = "未提供") {
    return typeof value === "string" && value.trim() ? value : fallback;
  }

  function strings(value) {
    return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
  }

  function scopeLabels(selection) {
    return [["prepared_event_id", "准备范围编号"], ["program_id", "项目记录编号"]]
      .filter(([key]) => typeof selection[key] === "string" && selection[key].trim())
      .map(([key, label]) => `${label} ${selection[key]}`);
  }

  function element(doc, tag, className, value) {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }

  function field(doc, label, value) {
    const row = element(doc, "div", "fact");
    row.append(element(doc, "dt", "", label), element(doc, "dd", "", value));
    return row;
  }

  function timestamp(value) {
    const date = new Date(value);
    return typeof value === "string" && Number.isFinite(date.getTime())
      ? date.toLocaleString("zh-CN", {hour12: false}) : "未提供";
  }

  function ageLabel(value) {
    if (!value) return "尚未收到状态";
    const seconds = Math.max(0, Math.floor((Date.now() - value) / 1000));
    if (seconds < 60) return `${seconds} 秒前收到`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前收到`;
    return `${Math.floor(seconds / 3600)} 小时前收到`;
  }

  function serial(value) {
    if (value === null || value === undefined) return "未提供";
    if (typeof value === "string") return value;
    return JSON.stringify(value);
  }

  function connectionLabel() {
    if (state.connection === "connected") return "状态更新已连接";
    if (state.connection === "stale") return "连接中断 · 显示上次状态";
    if (state.connection === "error") return "连接不可用";
    return state.snapshot ? "重新连接 · 显示上次状态" : "正在连接";
  }

  function completionOf(business, key = "completion") {
    const value = business[key];
    if (!value || !Number.isFinite(value.completed) || !Number.isFinite(value.total)
      || value.total <= 0 || value.completed < 0 || value.completed > value.total) return null;
    return value;
  }

  function statusOf(item) {
    return Object.hasOwn(statusLabels, item.state) ? statusLabels[item.state]
      : ["?", text(item.state, "待核实"), "unknown"];
  }

  function stepsOf(business) {
    const steps = business.workflow && Array.isArray(business.workflow.steps) ? business.workflow.steps : business.steps;
    return Array.isArray(steps) ? steps.filter((step) => step && typeof step === "object"
      && typeof step.step_id === "string" && step.step_id.trim()) : [];
  }

  function currentStepId(business) {
    return business.workflow && Array.isArray(business.workflow.steps)
      ? business.workflow.current_step_id : business.current_step_id;
  }

  function scopeName(run) {
    const index = state.runs.findIndex((item) => item.id === run.id);
    return index >= 0 ? `范围 ${index + 1}/${state.runs.length}` : "所选范围";
  }

  function shortIdentity(value) {
    const valueText = text(value);
    return valueText.length > 22 ? `${valueText.slice(0, 9)}…${valueText.slice(-8)}` : valueText;
  }

  function isFoundry() {
    return Boolean(state.selected && state.selected.selection.kind === "foundry_build");
  }

  function taskLabel(identity, business) {
    const items = Array.isArray(business.items) ? business.items : [];
    const index = items.findIndex((item) => item && item.item_id === identity);
    return index < 0 ? null : `任务 ${index + 1}`;
  }

  function stepLabel(step, business) {
    const original = text(step.label, step.step_id);
    if (!isFoundry()) return original;
    const tasks = Array.isArray(business.items) ? business.items : [];
    for (const item of tasks) {
      if (!item || typeof item.item_id !== "string") continue;
      const task = taskLabel(item.item_id, business);
      if (original === item.item_id) return task;
      for (const phase of ["初次搭建", "追加返修"]) {
        const prefix = `${phase} · ${item.item_id} / `;
        if (!original.startsWith(prefix)) continue;
        const stage = original.slice(prefix.length);
        const labels = {"环境检查": "检查环境", "实施": "搭建产物", "接受结果": "确认检查结果"};
        let label = Object.hasOwn(labels, stage) ? labels[stage] : null;
        if (stage.startsWith("独立检查 · ")) {
          const unit = step.step_id.slice(0, step.step_id.lastIndexOf("/stage:"));
          const checks = stepsOf(business).filter((candidate) => candidate.step_id.startsWith(`${unit}/stage:`)
            && text(candidate.label, "").startsWith(`${prefix}独立检查 · `));
          const index = checks.findIndex((candidate) => candidate.step_id === step.step_id);
          if (unit && index >= 0) label = `独立检查 ${index + 1}`;
        }
        if (label) return `${task} · ${phase === "初次搭建" ? "首次搭建" : "追加返修"} · ${label}`;
      }
    }
    return original;
  }

  function stepDetail(value) {
    if (!isFoundry()) return value;
    const suffix = "；历史工作记录，不代表当前成果仍通过";
    const historic = typeof value === "string" && value.endsWith(suffix);
    const original = historic ? value.slice(0, -suffix.length) : value;
    const labels = {
      "计划内后续步骤；尚无本项执行记录": "计划中包含此步骤，暂未看到执行记录。",
      "命令已登记，尚无启动观测": "已安排执行，暂未收到启动记录。",
      "已记录启动，完成待核对；不据此声称仍在运行": "已有启动记录，尚未确认是否结束。",
      "命令完成观测已捕获；不代替最终验收": "已收到命令完成记录；是否通过验收还需看检查结果。",
      "已捕获未通过结果；沿原控制器处理": "已收到未通过结果，由原运行流程处理。",
      "结果尚未确认；保留原观测，不重放命令": "结果尚未确认，保留现有记录，不重复执行。",
      "只复验，本次未重放实施命令": "本次只重新检查，没有再次搭建产物。",
      "未派发；已用预算保留": "本次未开始搭建，已消耗的尝试次数仍保留。",
      "此工作项曾完成接受；当前成果是否仍有效请看当前有效验收": "此任务曾通过声明的检查，当前结果请看“当前验收通过”。",
      "当前接受已失效，等待范围内修复或复验；原接受记录保留在历史": "原检查结果已失效，等待修复或重新检查；旧结果仍保留在历史中。",
      "本范围合法复用既有接受；未在此重新执行这些步骤": "此范围复用仍有效的检查结果，没有重新执行这些步骤。",
      "本范围未重放原命令；复用记录不代表之后的接受仍有效": "此范围没有重跑原命令；当前检查结果是否有效需单独确认。"
    };
    return (Object.hasOwn(labels, original) ? labels[original] : original) + (historic ? " 这是历史完成记录，不代表当前成果仍通过检查。" : "");
  }

  function scopeState(value) {
    if (!isFoundry()) return text(value, "待核实");
    const labels = {
      "SUPERSEDED · 已由明确接续的新范围替代，不能继续派发；历史保留": "已由新的执行范围接续；此范围不再启动任务，历史保留。",
      "APPROVED · 已批准；派发前仍会核对有效范围和剩余预算": "运行已获批准；每次启动前仍核对授权范围和剩余次数。",
      "APPROVAL_REQUIRED · 该范围尚待用户批准": "此范围尚待用户批准。",
      "EXPIRED · 已到期，不能复用此范围继续执行": "授权已到期，此范围不能继续启动任务。",
      "REVOKED · 已撤销，不能复用此范围继续执行": "授权已撤销，此范围不能继续启动任务。"
    };
    return Object.hasOwn(labels, value) ? labels[value] : text(value, "待核实");
  }

  function pendingText(value, business) {
    if (!isFoundry()) return value;
    if (scopeState(value) !== value) return scopeState(value);
    for (const item of Array.isArray(business.items) ? business.items : []) {
      if (!item || typeof item.item_id !== "string" || !value.startsWith(`${item.item_id}：`)) continue;
      const label = taskLabel(item.item_id, business);
      const tail = value.slice(item.item_id.length + 1);
      const recovery = tail.match(/^(.+)（([A-Z_]+)）；责任方 (本机操作者|原控制器|原记录待核对)(?: \/ (?:LOCAL_OPERATOR|BUILD_CONTROLLER))?；Attempt .+$/);
      if (recovery) return `${label}：${recovery[1]}。处理方：${recovery[3] === "原控制器" ? "原运行流程" : recovery[3]}。`;
      if (tail === "尚未完成本范围声明检查，后续推进沿原控制器") return `${label}：尚未完成此范围声明的检查，后续由原运行流程推进。`;
      if (tail === "待原控制器只复验；未重新执行产品实施") return `${label}：等待原运行流程重新检查，没有再次搭建产物。`;
      if (/^已有接受失效记录；受影响分支修复与复验沿原控制器；Event .+$/.test(tail)) return `${label}：原检查结果已失效，需要修复受影响部分并重新检查。`;
    }
    return value;
  }

  function appendOriginalStep(doc, container, step) {
    const details = element(doc, "details", "evidence step-source");
    details.dataset.detailKey = `step-source:${step.step_id}`;
    details.append(element(doc, "summary", "", "原始步骤与编号"));
    const facts = element(doc, "dl", "facts");
    facts.append(field(doc, "步骤名称", text(step.label, step.step_id)), field(doc, "步骤编号", step.step_id),
      field(doc, "原始说明", text(step.detail)));
    details.append(facts);
    container.append(details);
  }

  function makeCurrentStep(doc, business, compact) {
    const steps = stepsOf(business);
    const current = steps.find((step) => step.step_id === currentStepId(business));
    const box = element(doc, "div", "current-step");
    if (current) {
      const status = statusOf(current);
      const heading = element(doc, "div", "current-step-heading");
      const label = stepLabel(current, business);
      if (compact) {
        const name = element(doc, "strong", "current", `当前 · ${label}`);
        name.title = `当前关注：${label}${current.detail ? `；${current.detail}` : ""}`;
        heading.append(name);
      } else {
        heading.append(element(doc, "span", "step-caption", "当前关注"));
      }
      heading.append(element(doc, "span", `item-state ${status[2]}`, `${status[0]} ${status[1]}`));
      box.append(heading);
      if (!compact) box.append(element(doc, "p", "current", label));
      if (current.detail) {
        const detail = element(doc, "p", "step-detail", stepDetail(current.detail));
        detail.title = current.detail;
        box.append(detail);
      }
    } else {
      const acceptance = completionOf(business);
      const finished = business.workflow && Array.isArray(business.workflow.steps) && !currentStepId(business)
        && steps.length && steps.every((step) => ["PASS", "ACCEPTED", "COMPLETED", "NOT_RUN"].includes(step.state))
        && acceptance && acceptance.completed === acceptance.total;
      if (finished) {
        box.append(element(doc, "p", "current workflow-finished", "已记录的步骤已处理"),
          element(doc, "p", "step-detail", "此范围声明的检查已通过"),
          element(doc, "p", "scope-state", `${isFoundry() ? "运行授权" : "当前状态"}：${scopeState(business.current)}`));
      } else {
        box.append(element(doc, "p", "current", `当前状态：${scopeState(business.current)}`));
      }
    }
    if (!compact && current) box.append(element(doc, "p", "scope-state", `${isFoundry() ? "运行授权" : "当前状态"}：${scopeState(business.current)}`));
    return box;
  }

  function makeCompactSteps(doc, business) {
    const steps = stepsOf(business);
    if (!steps.length) return null;
    const index = steps.findIndex((step) => step.step_id === currentStepId(business));
    const box = element(doc, "div", "compact-steps");
    const completed = steps.filter((step) => ["PASS", "ACCEPTED", "COMPLETED"].includes(step.state)).length;
    box.append(element(doc, "p", "step-count", `已完成步骤 ${completed} / ${steps.length}`));
    const list = element(doc, "ul", "nearby-steps");
    const first = index >= 0 ? Math.max(0, index - 1) : 0;
    const last = Math.min(steps.length, index >= 0 ? index + 2 : 3);
    steps.slice(first, last).forEach((step, offset) => {
      const position = first + offset;
      if (position === index) return;
      const relation = index < 0 ? "步骤" : position < index ? "前项" : "下一项";
      const status = statusOf(step);
      const row = element(doc, "li", "nearby-step", `${relation} · ${stepLabel(step, business)} · ${status[1]}`);
      row.title = row.textContent;
      list.append(row);
    });
    box.append(list);
    return box;
  }

  function appendReferences(doc, container, refs) {
    if (!refs.length) return;
    const list = element(doc, "ul", "refs");
    refs.forEach((ref) => list.append(element(doc, "li", "", ref)));
    const details = element(doc, "details", "evidence");
    details.dataset.detailKey = `refs:${refs.join("|")}`;
    details.append(element(doc, "summary", "", `查看证据引用 · ${refs.length}`), list,
      element(doc, "p", "note", "通过原项目的证据入口查看；本页不会打开业务文件。"));
    container.append(details);
  }

  function makeSteps(doc) {
    if (!state.snapshot) return doc.createDocumentFragment();
    const business = state.snapshot.business;
    const steps = stepsOf(business);
    if (!steps.length) return doc.createDocumentFragment();
    const currentId = currentStepId(business);
    const currentIndex = steps.findIndex((step) => step.step_id === currentId);
    const viewed = steps.find((step) => step.step_id === (state.viewedStepId || currentId));
    const section = element(doc, "section", "steps");
    section.append(element(doc, "h2", "section-title", "执行步骤"));
    section.append(element(doc, "p", "steps-note", "点选步骤查看详情和历史。当前关注表示需要查看的步骤，不一定正在运行。"));
    const list = element(doc, "ul", "steps-list");
    steps.forEach((step, index) => {
      const current = step.step_id === currentId;
      const status = statusOf(step);
      const row = element(doc, "li", `step-row${current ? " is-current" : ""}${viewed && step.step_id === viewed.step_id ? " is-viewed" : ""}`);
      if (current) row.setAttribute("aria-current", "step");
      row.append(element(doc, "span", `step-number ${status[2]}`, `${index + 1}`));
      const body = element(doc, "div", "step-body");
      const heading = element(doc, "div", "step-heading");
      const button = element(doc, "button", "step-select", stepLabel(step, business));
      button.title = text(step.label, step.step_id);
      button.type = "button";
      button.dataset.viewStep = step.step_id;
      button.setAttribute("aria-pressed", viewed && step.step_id === viewed.step_id ? "true" : "false");
      button.addEventListener("click", () => { state.viewedStepId = step.step_id; render(); });
      const position = current ? "当前关注" : currentIndex >= 0 && index > currentIndex ? "后续步骤" : "已记录步骤";
      heading.append(button, element(doc, "span", `item-state ${status[2]}`, `${status[0]} ${status[1]} · ${position}`));
      body.append(heading);
      row.append(body);
      list.append(row);
    });
    section.append(list);
    if (viewed) {
      const detail = element(doc, "section", "viewed-step");
      detail.dataset.viewedStep = viewed.step_id;
      const current = viewed.step_id === currentId;
      detail.append(element(doc, "h3", "section-title", `${current ? "当前步骤详情" : "正在查看步骤"} · ${stepLabel(viewed, business)}`));
      if (!current && currentIndex >= 0) {
        const back = element(doc, "button", "secondary return-current", "返回当前步骤");
        back.type = "button";
        back.addEventListener("click", () => { state.viewedStepId = null; render(); });
        detail.append(back);
      }
      const status = statusOf(viewed);
      detail.append(element(doc, "p", `item-state ${status[2]}`, `${status[0]} ${status[1]}`));
      if (viewed.detail) detail.append(element(doc, "p", "step-detail", stepDetail(viewed.detail)));
      appendOriginalStep(doc, detail, viewed);
      const dependencies = strings(viewed.depends_on);
      const names = new Map(steps.map((step) => [step.step_id, stepLabel(step, business)]));
      if (dependencies.length) detail.append(element(doc, "p", "step-dependencies", `依赖：${dependencies.map((id) => names.get(id) || id).join("、")}`));
      appendReferences(doc, detail, strings(viewed.evidence_refs));
      const history = Array.isArray(viewed.history) ? viewed.history : [];
      if (history.length) {
        const historyBox = element(doc, "details", "step-history-block");
        historyBox.dataset.detailKey = `history:${viewed.step_id}`;
        historyBox.append(element(doc, "summary", "history-title", `历史记录 · ${history.length}`));
        const records = element(doc, "ol", "step-history");
        history.forEach((entry) => {
          const status = statusOf(entry);
          const row = element(doc, "li", "history-entry");
          row.append(element(doc, "strong", "", text(entry.label, "已记录事件")),
            element(doc, "span", `item-state ${status[2]}`, ` · ${status[0]} ${status[1]}`));
          if (entry.detail) row.append(element(doc, "p", "step-detail", entry.detail));
          appendReferences(doc, row, strings(entry.evidence_refs));
          records.append(row);
        });
        historyBox.append(records);
        detail.append(historyBox);
      }
      section.append(detail);
    }
    return section;
  }

  function makeSummary(doc, compact) {
    const snapshot = state.snapshot;
    const selection = snapshot ? snapshot.selection : (state.selected ? state.selected.selection : {});
    const business = snapshot ? snapshot.business : {};
    const card = element(doc, "section", `summary ${compact ? "compact-summary" : "expanded-summary"}`);
    const identity = element(doc, "div", "identity");
    const kind = selection.kind === "foundry_build" ? "搭建" : selection.kind === "harness_run" ? "业务运行" : text(selection.kind, "运行");
    const title = business.title === "Foundry 已选范围只读观察" ? "Foundry 搭建进度" : business.title;
    const project = element(doc, "span", "project", text(title, text(selection.project_id, "尚未选择任务")));
    project.title = text(selection.project_id);
    identity.append(element(doc, "span", "kind", kind), project);
    card.append(identity);
    const scope = scopeLabels(selection);
    if (typeof business.scope_ref === "string" && business.scope_ref.trim()) scope.push(`范围 ${business.scope_ref}`);
    const fullIdentity = [`运行 ${text(selection.run_id)}`, `版本 ${text(selection.project_version)}`, ...scope].join(" · ");
    if (state.selected) {
      const prepared = text(selection.prepared_event_id, text(business.scope_ref, text(selection.run_id)));
      // The numbered scope remains unique even if shortened identifiers collide.
      const range = element(doc, "p", compact ? "compact-scope" : "run-scope", `${scopeName(state.selected)} · ${shortIdentity(prepared)}`);
      range.title = fullIdentity;
      range.setAttribute("aria-label", `${scopeName(state.selected)} · ${fullIdentity}`);
      card.append(range);
    }
    const compactConnection = {connected: "已连接", stale: "连接中断", error: "连接不可用", connecting: "正在连接"};
    const connection = element(doc, "p", `connection ${state.connection}`, compact ? compactConnection[state.connection] : connectionLabel());
    connection.setAttribute("role", "status");
    connection.title = [connectionLabel(), state.connectionMessage].filter(Boolean).join("；");
    if (compact) identity.append(connection);
    else card.append(connection);
    if (!compact && state.connectionMessage && state.connection !== "connected") {
      card.append(element(doc, "p", "connection-detail", state.connectionMessage));
    }
    const acceptance = completionOf(business);
    const workProgress = completionOf(business, "work_progress");
    const completion = workProgress || acceptance;
    const progress = element(doc, "div", `completion${workProgress ? " work-progress" : ""}`);
    if (completion) {
      const percent = completion.completed === completion.total ? 100
        : Math.min(99.9, Math.round(completion.completed / completion.total * 1000) / 10);
      progress.append(element(doc, "strong", "percent", `${percent}%`));
      const measure = element(doc, "span", "completion-measure");
      const label = workProgress ? "累计工作进度" : text(completion.label, "完成项");
      measure.title = `${label} ${completion.completed} / ${completion.total}${workProgress ? `；${text(completion.label)}` : ""}`;
      measure.setAttribute("aria-label", measure.title);
      measure.append(element(doc, "span", "completion-label", label), element(doc, "span", "completion-count", `${completion.completed} / ${completion.total}`));
      progress.append(measure);
      const bar = element(doc, "progress", "completion-bar");
      bar.max = completion.total;
      bar.value = completion.completed;
      bar.setAttribute("aria-label", `${label} ${completion.completed} / ${completion.total}`);
      progress.append(bar);
    } else {
      progress.append(element(doc, "strong", "unknown-progress", "总量待确定"));
      progress.append(element(doc, "span", "completion-label", snapshot ? "尚未提供可计算进度的总量" : "等待读取运行状态"));
    }
    card.append(progress);
    if (workProgress) {
      const valid = acceptance && acceptance.completed === acceptance.total;
      const accepted = element(doc, "p", `valid-acceptance ${valid ? "accepted" : "waiting"}`);
      const count = acceptance ? `${acceptance.completed} / ${acceptance.total}` : "尚未提供检查总量";
      const full = acceptance ? `${count} · ${text(acceptance.label)}` : count;
      accepted.title = `当前验收通过：${full}`;
      accepted.setAttribute("aria-label", accepted.title);
      accepted.append(element(doc, "strong", "", "当前验收通过："));
      accepted.append(element(doc, "span", "", count));
      card.append(accepted);
      if (!compact) card.append(element(doc, "p", "progress-note", "累计进度包含已确认的追加返修；做完工作不等于当前验收通过。通过数仅指此范围声明的检查。"));
    }
    card.append(makeCurrentStep(doc, business, compact));
    const recent = strings(business.recent);
    const pending = strings(business.pending).map((item) => pendingText(item, business));
    const failures = stepsOf(business).filter((step) => ["FAILED", "FAIL", "ERROR", "INVALIDATED"].includes(step.state));
    const gaps = strings(snapshot && snapshot.observation && snapshot.observation.gaps);
    const gapText = (gap) => gap === "SOURCE_UNAVAILABLE" ? "暂时无法读取运行记录，显示上次已知状态" : gap;
    if (compact) {
      const connectionProblem = state.connection === "stale" || state.connection === "error";
      if (pending.length || failures.length || gaps.length || connectionProblem) {
        const attention = element(doc, "aside", "attention has-pending compact-alerts");
        const counts = [];
        if (pending.length) counts.push(`待处理 ${pending.length}`);
        if (failures.length) counts.push(`步骤异常 ${failures.length}`);
        if (gaps.length) counts.push(`信息待核对 ${gaps.length}`);
        if (connectionProblem) counts.push(compactConnection[state.connection]);
        attention.append(element(doc, "strong", "alert-counts", counts.join(" · ")));
        const details = [connectionProblem ? connection.title : "", ...pending,
          ...failures.map((step) => `${stepLabel(step, business)}：${statusOf(step)[1]}`), ...gaps.map(gapText)].filter(Boolean);
        const preview = element(doc, "p", "pending-preview", details[0]);
        preview.title = details.join("；");
        attention.setAttribute("aria-label", `${counts.join("；")}。${details.join("；")}`);
        attention.append(preview);
        card.append(attention);
      }
    } else {
      const attention = element(doc, "div", `attention ${pending.length || failures.length ? "has-pending" : ""}`);
      if (failures.length) attention.append(element(doc, "p", "step-alert", `步骤异常：${failures.length} 项`));
      if (pending.length) {
        attention.append(element(doc, "strong", "", "待处理："));
        const list = element(doc, "ul", "pending-list");
        pending.forEach((item) => list.append(element(doc, "li", "", item)));
        attention.append(list);
      } else if (!failures.length) {
        attention.append(element(doc, "span", "", snapshot ? "当前记录未列出待处理事项" : "等待读取运行状态"));
      }
      card.append(attention);
      if (gaps.length) {
        const gapBox = element(doc, "aside", "gaps");
        gapBox.append(element(doc, "strong", "", "尚待核对的信息"));
        const gapList = element(doc, "ul", "gap-list");
        gaps.forEach((gap) => gapList.append(element(doc, "li", "", gapText(gap))));
        gapBox.append(gapList);
        card.append(gapBox);
      }
    }
    if (compact) {
      const track = makeCompactSteps(doc, business);
      if (track) card.append(track);
    }
    if (snapshot && !compact) card.append(element(doc, "p", "source-freshness", `最近读取记录：${timestamp(snapshot.observation.observed_at)}`));
    const freshness = element(doc, "p", "freshness", `页面更新：${ageLabel(state.lastReceived)}`);
    freshness.dataset.freshness = "true";
    if (snapshot) freshness.title = `最近读取记录：${timestamp(snapshot.observation.observed_at)}`;
    card.append(freshness);
    return card;
  }

  function makeDetails(doc) {
    const fragment = doc.createDocumentFragment();
    if (!state.snapshot) return fragment;
    const {business, observation, component, selection, transport} = state.snapshot;
    const items = Array.isArray(business.items) ? business.items : [];
    const section = element(doc, "section", "results");
    section.append(element(doc, "h2", "section-title", "各任务检查结果"));
    if (!items.length) section.append(element(doc, "p", "empty", "尚未提供成果清单，暂时无法在此查看。"));
    const list = element(doc, "ul", "item-list");
    items.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const row = element(doc, "li", "item");
      const status = Object.hasOwn(statusLabels, item.state) ? statusLabels[item.state]
        : ["?", text(item.state, "待核实"), "unknown"];
      const itemHeader = element(doc, "div", "item-header");
      itemHeader.append(element(doc, "span", `item-state ${status[2]}`, `${status[0]} ${status[1]}`));
      const itemLabel = element(doc, "strong", "item-label", isFoundry() ? (taskLabel(item.item_id, business) || text(item.label, text(item.item_id))) : text(item.label, text(item.item_id)));
      itemLabel.title = text(item.label, text(item.item_id));
      itemHeader.append(itemLabel);
      row.append(itemHeader);
      const refs = strings(item.evidence_refs);
      if (refs.length || isFoundry()) {
        const evidence = element(doc, "details", "evidence");
        evidence.dataset.detailKey = `evidence:${text(item.item_id)}`;
        evidence.append(element(doc, "summary", "", `原始结果与证据 · ${refs.length}`));
        evidence.append(element(doc, "p", "note", text(item.label, text(item.item_id))));
        const refsList = element(doc, "ul", "refs");
        refs.forEach((ref) => refsList.append(element(doc, "li", "", ref)));
        evidence.append(refsList, element(doc, "p", "note", "按原项目的证据入口查看；本页不提供文件浏览。"));
        row.append(evidence);
      }
      list.append(row);
    });
    section.append(list);
    fragment.append(section);
    const recent = strings(business.recent);
    if (recent.length) {
      const changes = element(doc, "details", "details-block");
      changes.dataset.detailKey = "recent";
      changes.append(element(doc, "summary", "", "最近变化"));
      const changesList = element(doc, "ol", "recent-list");
      recent.forEach((item) => changesList.append(element(doc, "li", "", item)));
      changes.append(changesList);
      fragment.append(changes);
    }
    if (business.budget && typeof business.budget === "object") {
      const budget = element(doc, "details", "details-block");
      budget.dataset.detailKey = "budget";
      budget.append(element(doc, "summary", "", "此范围的尝试次数"));
      const facts = element(doc, "dl", "facts");
      facts.append(field(doc, "已用次数", serial(business.budget.attempts_consumed)));
      facts.append(field(doc, "剩余次数", serial(business.budget.attempts_remaining)));
      budget.append(facts, element(doc, "p", "note", "这里显示已用与剩余次数，不用于计算工作进度。"));
      fragment.append(budget);
    }
    const provenance = element(doc, "details", "details-block");
    provenance.dataset.detailKey = "provenance";
    provenance.append(element(doc, "summary", "", "运行编号、原始状态与来源"));
    const facts = element(doc, "dl", "facts");
    facts.append(field(doc, "项目", text(selection.project_id)), field(doc, "项目版本", text(selection.project_version)),
      field(doc, "运行编号", text(selection.run_id)), field(doc, "准备范围编号", serial(business.scope_ref)),
      field(doc, "计划记录编号", serial(business.proposal_ref)), field(doc, "原始运行状态", text(business.current)));
    if (selection.program_id !== undefined) facts.append(field(doc, "项目记录编号（Program）", text(selection.program_id)));
    if (selection.prepared_event_id !== undefined) facts.append(field(doc, "准备范围编号（Prepared）", text(selection.prepared_event_id)));
    facts.append(field(doc, "来源版本", serial(business.source_revision)));
    facts.append(field(doc, "观察时间", timestamp(observation.observed_at)));
    facts.append(field(doc, "最近输出活动", timestamp(observation.activity && observation.activity.last_output_at)));
    facts.append(field(doc, "展示组件", `${text(component && component.id)} · ${text(component && component.version)}`));
    facts.append(field(doc, "传输序号", `${text(transport.session_id)} / ${transport.sequence}`));
    provenance.append(facts);
    if (strings(business.pending).length) {
      provenance.append(element(doc, "h3", "history-title", "原始待处理说明"));
      const original = element(doc, "ul", "refs");
      strings(business.pending).forEach((value) => original.append(element(doc, "li", "", value)));
      provenance.append(original);
    }
    provenance.append(element(doc, "p", "note", "收到输出或连接更新，只表示有新记录，不代表任务完成。"));
    fragment.append(provenance);
    return fragment;
  }

  function render() {
    // A host preference belongs to this observer, never to a business source.
    document.documentElement.dataset.theme = state.theme;
    if (pipWindow && !pipWindow.closed) pipWindow.document.documentElement.dataset.theme = state.theme;
    // Preserve disclosure preferences and keyboard focus across source refreshes.
    const opened = new Set(Array.from(dashboard.querySelectorAll("details[open]")).map((node) => node.dataset.detailKey));
    const focused = document.activeElement;
    const focusedSummary = focused && focused.tagName === "SUMMARY" && dashboard.contains(focused) ? focused.parentElement.dataset.detailKey : null;
    const focusedStep = focused && dashboard.contains(focused) ? focused.dataset.viewStep : null;
    dashboard.replaceChildren(makeSummary(document, false), makeSteps(document), makeDetails(document));
    dashboard.querySelectorAll("details").forEach((node) => {
      const key = node.dataset.detailKey;
      if (opened.has(key)) node.open = true;
      if (key === focusedSummary) node.firstElementChild.focus({preventScroll: true});
    });
    if (focusedStep) dashboard.querySelectorAll("[data-view-step]").forEach((node) => {
      if (node.dataset.viewStep === focusedStep) node.focus({preventScroll: true});
    });
    if (pipWindow && !pipWindow.closed && pipDashboard) {
      pipDashboard.replaceChildren(makeSummary(pipWindow.document, true));
    }
  }

  function setConnection(value, message) {
    state.connection = value;
    state.connectionMessage = message;
    render();
  }

  function acceptSnapshot(snapshot, epoch) {
    if (epoch !== generation || !state.selected) return;
    if (!snapshot || !snapshot.selection || !snapshot.business || !snapshot.observation || !snapshot.transport
      || typeof snapshot.transport.session_id !== "string" || !Number.isSafeInteger(snapshot.transport.sequence)
      || snapshot.transport.sequence < 0 || identityFields.some((key) => state.selected.selection[key] !== undefined
        && snapshot.selection[key] !== state.selected.selection[key])) {
      setConnection(state.snapshot ? "stale" : "error", "收到的更新与当前任务不匹配，或内容无法读取。继续显示上次已知状态。");
      return;
    }
    const {session_id: session, sequence} = snapshot.transport;
    if (state.retiredSessions.has(session)) return;
    if (state.session === session && sequence < state.sequence) return;
    // Every event is a complete snapshot, including reconnect/gap handshakes.
    // No missing event is replayed as a business operation.
    if (state.session && state.session !== session) state.retiredSessions.add(state.session);
    if (state.session !== session || sequence > state.sequence) state.snapshot = snapshot;
    if (state.viewedStepId && !stepsOf(state.snapshot.business).some((step) => step.step_id === state.viewedStepId)) state.viewedStepId = null;
    state.session = session;
    state.sequence = sequence;
    state.lastReceived = Date.now();
    setConnection("connected", "");
  }

  function subscribe(run, retain = false) {
    generation += 1;
    const epoch = generation;
    if (source) source.close();
    state.selected = run;
    if (!retain) {
      state.snapshot = null;
      state.viewedStepId = null;
      state.lastReceived = null;
      state.session = null;
      state.sequence = -1;
      state.retiredSessions.clear();
    }
    setConnection("connecting", "等待读取完整运行状态。");
    const stream = new EventSource(`api/events?run=${encodeURIComponent(run.id)}`);
    source = stream;
    stream.addEventListener("snapshot", (event) => {
      if (epoch !== generation) return;
      try { acceptSnapshot(JSON.parse(event.data), epoch); }
      catch (_) { setConnection(state.snapshot ? "stale" : "error", "收到的更新无法读取，等待下一份完整状态。"); }
    });
    stream.onopen = () => {
      if (epoch === generation) setConnection("connecting", "连接已建立，等待读取完整运行状态。");
    };
    stream.onerror = () => {
      if (epoch === generation) setConnection(state.snapshot ? "stale" : "error", "浏览器将尝试重新连接；原业务不受本页连接影响。");
    };
  }

  async function loadRuns() {
    const epoch = ++listGeneration;
    reconnectButton.disabled = true;
    try {
      const response = await fetch("api/runs", {cache: "no-store"});
      if (!response.ok) throw new Error("runs unavailable");
      const payload = await response.json();
      if (epoch !== listGeneration) return;
      if (!payload || !Array.isArray(payload.runs)) throw new Error("invalid runs");
      const runs = payload.runs.filter((run) => run && typeof run.id === "string" && run.selection && typeof run.selection === "object");
      const theme = payload.presentation && payload.presentation.theme;
      if (theme !== undefined && !["system", "light", "dark"].includes(theme)) throw new Error("invalid theme");
      state.theme = theme || "system";
      state.runs = runs;
      selector.replaceChildren();
      if (!runs.length) {
        if (source) source.close();
        generation += 1;
        selector.append(element(document, "option", "", "没有已选择的运行"));
        selector.disabled = true;
        setConnection(state.snapshot ? "stale" : "error", "尚未指定要查看的任务；可在 Chat 中说明要打开哪个看板。");
        return;
      }
      runs.forEach((run) => {
        const identity = text(run.selection.prepared_event_id, run.selection.run_id);
        const label = [scopeName(run), shortIdentity(run.selection.project_id), `版本 ${text(run.selection.project_version)}`, shortIdentity(identity)].join(" · ");
        const option = element(document, "option", "", label);
        option.title = [text(run.selection.project_id), text(run.selection.run_id), text(run.selection.project_version), ...scopeLabels(run.selection)].join(" · ");
        option.value = run.id;
        selector.append(option);
      });
      selector.disabled = false;
      const previous = state.selected;
      const chosen = runs.find((run) => previous && run.id === previous.id) || runs[0];
      selector.value = chosen.id;
      const retain = previous && previous.id === chosen.id && identityFields.every((key) => previous.selection[key] === chosen.selection[key]);
      subscribe(chosen, retain);
    } catch (_) {
      if (epoch === listGeneration) setConnection(state.snapshot ? "stale" : "error", "无法读取观察服务。可保留上次状态，稍后重新连接。");
    } finally {
      if (epoch === listGeneration) reconnectButton.disabled = false;
    }
  }

  function updateViewControls() {
    pipButton.hidden = !canPip;
    fullscreenButton.hidden = !canFullscreen;
    pipButton.disabled = pipOpening || fullscreenChanging;
    fullscreenButton.disabled = fullscreenChanging;
    fullscreenButton.textContent = document.fullscreenElement ? "退出全屏" : "全屏查看";
    fullscreenButton.setAttribute("aria-pressed", document.fullscreenElement ? "true" : "false");
  }

  function closePip() {
    pipRequest += 1;
    const opened = pipWindow;
    pipWindow = null;
    pipDashboard = null;
    if (opened && !opened.closed) opened.close();
  }

  function changeFullscreen(leaving) {
    fullscreenChanging = true;
    updateViewControls();
    const failed = leaving ? "未能退出全屏，可按 Esc 返回普通窗口。"
      : "浏览器未允许全屏，仍可在当前页面查看。";
    try {
      // Request directly in the click event; no network or asynchronous preparation.
      const request = leaving ? document.exitFullscreen() : document.documentElement.requestFullscreen();
      Promise.resolve(request).then(() => {
        notice.textContent = document.fullscreenElement
          ? "正在全屏查看。按 Esc 或“退出全屏”返回；任务运行不受影响。"
          : "已返回普通窗口，任务状态继续更新。";
      }).catch(() => { notice.textContent = failed; }).finally(() => {
        fullscreenChanging = false;
        updateViewControls();
      });
    } catch (_) {
      notice.textContent = failed;
      fullscreenChanging = false;
      updateViewControls();
    }
  }

  function toggleFullscreen() {
    if (!canFullscreen || fullscreenChanging) return;
    const leaving = Boolean(document.fullscreenElement);
    if (!leaving) closePip();
    changeFullscreen(leaving);
  }

  function openPip() {
    if (!canPip || fullscreenChanging) return;
    if (pipWindow && !pipWindow.closed) { pipWindow.focus(); return; }
    if (pipOpening) return;
    let request;
    const requestId = ++pipRequest;
    try {
      // Call before any await so the browser retains this click's user activation.
      request = window.documentPictureInPicture.requestWindow({width: 360, height: 260});
      pipOpening = true;
      updateViewControls();
    } catch (_) {
      notice.textContent = "浏览器未允许打开画中画，仍可在当前页面查看。";
      return;
    }
    if (document.fullscreenElement) changeFullscreen(true);
    Promise.resolve(request).then((openedWindow) => {
      if (requestId !== pipRequest) { openedWindow.close(); return; }
      pipWindow = openedWindow;
      const doc = openedWindow.document;
      doc.documentElement.lang = "zh-CN";
      doc.title = "任务进度 · 画中画";
      const stylesheet = doc.createElement("link");
      stylesheet.rel = "stylesheet";
      stylesheet.href = new URL("style.css", document.baseURI).href;
      doc.head.append(stylesheet);
      doc.body.className = "pip";
      const container = element(doc, "main", "pip-shell");
      pipDashboard = element(doc, "div", "pip-dashboard");
      container.append(pipDashboard);
      const detailsButton = element(doc, "button", "pip-details", "打开主窗口");
      detailsButton.type = "button";
      detailsButton.addEventListener("click", () => { window.focus(); selector.focus(); });
      container.append(detailsButton);
      doc.body.replaceChildren(container);
      openedWindow.addEventListener("pagehide", () => {
        if (pipWindow === openedWindow) {
          pipWindow = null;
          pipDashboard = null;
          notice.textContent = "画中画已关闭，主页面继续更新。";
        }
      }, {once: true});
      notice.textContent = "画中画和主页面显示同一份状态。关闭浮窗不会停止任务。";
      render();
    }).catch(() => {
      if (requestId === pipRequest) notice.textContent = "画中画未能打开，仍可在当前页面查看。";
    }).finally(() => { pipOpening = false; updateViewControls(); });
  }

  selector.addEventListener("change", () => {
    const run = state.runs.find((item) => item.id === selector.value);
    if (run) subscribe(run);
  });
  pipButton.addEventListener("click", openPip);
  fullscreenButton.addEventListener("click", toggleFullscreen);
  document.addEventListener("fullscreenchange", () => {
    updateViewControls();
    notice.textContent = document.fullscreenElement
      ? "正在全屏查看。按 Esc 或“退出全屏”返回；任务运行不受影响。"
      : "已返回普通窗口，任务状态继续更新。";
  });
  reconnectButton.addEventListener("click", loadRuns);
  window.addEventListener("pagehide", () => { if (source) source.close(); });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && state.selected) subscribe(state.selected, true);
  });
  updateViewControls();
  notice.textContent = embedded
    ? "正在内嵌看板中查看。需要画中画或全屏时，可在 Chat 中说“用 Chrome 打开这个看板”。"
    : canPip && canFullscreen ? "可打开画中画或全屏查看；只切换显示方式，不启动任务。"
    : canPip ? "可打开画中画；当前浏览器未提供全屏功能。"
    : canFullscreen ? "可全屏查看；当前浏览器未提供画中画功能。"
    : "当前浏览器不提供画中画或全屏。可在 Chat 中请求用 Chrome 打开这个看板。";
  setInterval(() => {
    document.querySelectorAll("[data-freshness]").forEach((node) => { node.textContent = `页面更新：${ageLabel(state.lastReceived)}`; });
    if (pipWindow && !pipWindow.closed) pipWindow.document.querySelectorAll("[data-freshness]").forEach((node) => { node.textContent = `页面更新：${ageLabel(state.lastReceived)}`; });
  }, 1000);
  render();
  loadRuns();
})();
