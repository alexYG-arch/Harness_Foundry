/* One source subscription; sidebar and Document PiP render the same state. */
(() => {
  "use strict";

  const selector = document.getElementById("run-selector");
  const dashboard = document.getElementById("dashboard");
  const notice = document.getElementById("view-notice");
  const pipButton = document.getElementById("pip-button");
  const sidebarButton = document.getElementById("sidebar-button");
  const reconnectButton = document.getElementById("reconnect-button");
  const preferenceKey = "local-dashboard-view";
  const identityFields = ["kind", "project_id", "project_version", "run_id", "program_id", "prepared_event_id"];
  const statusLabels = {
    ACCEPTED: ["✓", "已接受", "accepted"],
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
  let pipRequest = 0;

  function text(value, fallback = "未提供") {
    return typeof value === "string" && value.trim() ? value : fallback;
  }

  function strings(value) {
    return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
  }

  function scopeLabels(selection) {
    return [["prepared_event_id", "Prepared"], ["program_id", "Program"]]
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
    if (!value) return "尚未收到快照";
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
    if (state.connection === "connected") return "观察服务已连接";
    if (state.connection === "stale") return "连接中断 · 保留上次快照";
    if (state.connection === "error") return "连接不可用";
    return state.snapshot ? "重新连接 · 保留上次快照" : "正在连接";
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

  function makeCurrentStep(doc, business, compact) {
    const steps = stepsOf(business);
    const current = steps.find((step) => step.step_id === currentStepId(business));
    const box = element(doc, "div", "current-step");
    if (current) {
      const status = statusOf(current);
      const heading = element(doc, "div", "current-step-heading");
      const label = text(current.label, current.step_id);
      if (compact) {
        const name = element(doc, "strong", "current", `当前 · ${label}`);
        name.title = `当前关注步骤：${label}${current.detail ? `；${current.detail}` : ""}`;
        heading.append(name);
      } else {
        heading.append(element(doc, "span", "step-caption", "当前关注步骤"));
      }
      heading.append(element(doc, "span", `item-state ${status[2]}`, `${status[0]} ${status[1]}`));
      box.append(heading);
      if (!compact) box.append(element(doc, "p", "current", label));
      if (current.detail) {
        const detail = element(doc, "p", "step-detail", current.detail);
        detail.title = current.detail;
        box.append(detail);
      }
    } else {
      const acceptance = completionOf(business);
      const finished = business.workflow && Array.isArray(business.workflow.steps) && !currentStepId(business)
        && steps.length && steps.every((step) => ["PASS", "ACCEPTED", "COMPLETED", "NOT_RUN"].includes(step.state))
        && acceptance && acceptance.completed === acceptance.total;
      if (finished) {
        box.append(element(doc, "p", "current workflow-finished", "已记录步骤完成"),
          element(doc, "p", "step-detail", "当前有效验收已满足"),
          element(doc, "p", "scope-state", `范围状态：${text(business.current, "待核实")}`));
      } else {
        box.append(element(doc, "p", "current", `范围状态：${text(business.current, "运行状态待核实")}`));
      }
    }
    if (!compact && current) box.append(element(doc, "p", "scope-state", `范围状态：${text(business.current, "待核实")}`));
    return box;
  }

  function makeCompactSteps(doc, business) {
    const steps = stepsOf(business);
    if (!steps.length) return null;
    const index = steps.findIndex((step) => step.step_id === currentStepId(business));
    const box = element(doc, "div", "compact-steps");
    const completed = steps.filter((step) => ["PASS", "ACCEPTED", "COMPLETED"].includes(step.state)).length;
    box.append(element(doc, "p", "step-count", `步骤已完成 ${completed} / ${steps.length} · 非验收计数`));
    const list = element(doc, "ul", "nearby-steps");
    const first = index >= 0 ? Math.max(0, index - 1) : 0;
    const last = Math.min(steps.length, index >= 0 ? index + 2 : 3);
    steps.slice(first, last).forEach((step, offset) => {
      const position = first + offset;
      if (position === index) return;
      const relation = index < 0 ? "步骤" : position < index ? "前项" : "下一项";
      const status = statusOf(step);
      const row = element(doc, "li", "nearby-step", `${relation} · ${text(step.label, step.step_id)} · ${status[1]}`);
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
    container.append(element(doc, "p", "note", "证据引用（通过原项目入口查看）"), list);
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
    section.append(element(doc, "p", "steps-note", "点选步骤查看详情和历史；查看位置不会改变当前运行状态。步骤按来源记录排列。"));
    const list = element(doc, "ul", "steps-list");
    steps.forEach((step, index) => {
      const current = step.step_id === currentId;
      const status = statusOf(step);
      const row = element(doc, "li", `step-row${current ? " is-current" : ""}${viewed && step.step_id === viewed.step_id ? " is-viewed" : ""}`);
      if (current) row.setAttribute("aria-current", "step");
      row.append(element(doc, "span", `step-number ${status[2]}`, `${index + 1}`));
      const body = element(doc, "div", "step-body");
      const heading = element(doc, "div", "step-heading");
      const button = element(doc, "button", "step-select", text(step.label, step.step_id));
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
      detail.append(element(doc, "h3", "section-title", `${current ? "当前步骤详情" : "正在查看步骤"} · ${text(viewed.label, viewed.step_id)}`));
      if (!current && currentIndex >= 0) {
        const back = element(doc, "button", "secondary return-current", "返回当前步骤");
        back.type = "button";
        back.addEventListener("click", () => { state.viewedStepId = null; render(); });
        detail.append(back);
      }
      const status = statusOf(viewed);
      detail.append(element(doc, "p", `item-state ${status[2]}`, `${status[0]} ${status[1]}`));
      if (viewed.detail) detail.append(element(doc, "p", "step-detail", viewed.detail));
      const dependencies = strings(viewed.depends_on);
      const names = new Map(steps.map((step) => [step.step_id, text(step.label, step.step_id)]));
      if (dependencies.length) detail.append(element(doc, "p", "step-dependencies", `依赖：${dependencies.map((id) => names.get(id) || id).join("、")}`));
      appendReferences(doc, detail, strings(viewed.evidence_refs));
      const history = Array.isArray(viewed.history) ? viewed.history : [];
      if (history.length) {
        detail.append(element(doc, "h4", "history-title", "历史记录"));
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
        detail.append(records);
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
    identity.append(element(doc, "span", "kind", kind), element(doc, "span", "project", text(selection.project_id, "尚未选择运行")));
    card.append(identity);
    const scope = scopeLabels(selection);
    if (typeof business.scope_ref === "string" && business.scope_ref.trim()) scope.push(`范围 ${business.scope_ref}`);
    const fullIdentity = [`运行 ${text(selection.run_id)}`, `版本 ${text(selection.project_version)}`, ...scope].join(" · ");
    if (compact && state.selected) {
      const prepared = text(selection.prepared_event_id, text(business.scope_ref, text(selection.run_id)));
      const shortPrepared = prepared.length > 22 ? `${prepared.slice(0, 9)}…${prepared.slice(-8)}` : prepared;
      // The same numbered range is in the main selector, so even identical shortened IDs stay distinguishable.
      const range = element(doc, "p", "compact-scope", `${scopeName(state.selected)} · ${shortPrepared}`);
      range.title = fullIdentity;
      range.setAttribute("aria-label", `${scopeName(state.selected)} · ${fullIdentity}`);
      card.append(range);
    } else {
      card.append(element(doc, "p", "run-identity", `运行 ${text(selection.run_id)} · 版本 ${text(selection.project_version)}`));
      if (scope.length) card.append(element(doc, "p", "run-identity", scope.join(" · ")));
      if (business.title) card.append(element(doc, "h2", "run-title", text(business.title)));
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
      const label = workProgress ? "累计工作进度（非验收通过率）" : text(completion.label, "完成项");
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
      progress.append(element(doc, "span", "completion-label", snapshot ? "未提供完整完成口径" : "等待来源快照"));
    }
    card.append(progress);
    if (workProgress) {
      const valid = acceptance && acceptance.completed === acceptance.total;
      const accepted = element(doc, "p", `valid-acceptance ${valid ? "accepted" : "waiting"}`);
      const count = acceptance ? `${acceptance.completed} / ${acceptance.total}` : "口径未提供";
      const full = acceptance ? `${count} · ${text(acceptance.label)}` : count;
      accepted.title = `当前有效验收：${full}`;
      accepted.setAttribute("aria-label", accepted.title);
      accepted.append(element(doc, "strong", "", "当前有效验收："));
      accepted.append(element(doc, "span", "", compact ? count : full));
      card.append(accepted);
    }
    card.append(makeCurrentStep(doc, business, compact));
    const recent = strings(business.recent);
    if (!compact && recent.length) card.append(element(doc, "p", "latest", `最近进展：${recent[0]}`));
    const pending = strings(business.pending);
    const failures = stepsOf(business).filter((step) => ["FAILED", "FAIL", "ERROR", "INVALIDATED"].includes(step.state));
    const gaps = strings(snapshot && snapshot.observation && snapshot.observation.gaps);
    const gapText = (gap) => gap === "SOURCE_UNAVAILABLE" ? "来源暂不可读，保留上次快照" : gap;
    if (compact) {
      const connectionProblem = state.connection === "stale" || state.connection === "error";
      if (pending.length || failures.length || gaps.length || connectionProblem) {
        const attention = element(doc, "aside", "attention has-pending compact-alerts");
        const counts = [];
        if (pending.length) counts.push(`待处理 ${pending.length}`);
        if (failures.length) counts.push(`步骤异常 ${failures.length}`);
        if (gaps.length) counts.push(`来源缺口 ${gaps.length}`);
        if (connectionProblem) counts.push(compactConnection[state.connection]);
        attention.append(element(doc, "strong", "alert-counts", counts.join(" · ")));
        const details = [connectionProblem ? connection.title : "", ...pending,
          ...failures.map((step) => `${text(step.label, step.step_id)}：${statusOf(step)[1]}`), ...gaps.map(gapText)].filter(Boolean);
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
        attention.append(element(doc, "span", "", snapshot ? "当前记录没有列出待处理事项" : "等待来源快照"));
      }
      card.append(attention);
      if (gaps.length) {
        const gapBox = element(doc, "aside", "gaps");
        gapBox.append(element(doc, "strong", "", "来源缺口"));
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
    if (snapshot && !compact) card.append(element(doc, "p", "source-freshness", `来源最近成功读取：${timestamp(snapshot.observation.observed_at)}`));
    const freshness = element(doc, "p", "freshness", `服务快照：${ageLabel(state.lastReceived)}`);
    freshness.dataset.freshness = "true";
    if (snapshot) freshness.title = `来源最近成功读取：${timestamp(snapshot.observation.observed_at)}`;
    card.append(freshness);
    return card;
  }

  function makeDetails(doc) {
    const fragment = doc.createDocumentFragment();
    if (!state.snapshot) return fragment;
    const {business, observation, component, selection, transport} = state.snapshot;
    const items = Array.isArray(business.items) ? business.items : [];
    const section = element(doc, "section", "results");
    section.append(element(doc, "h2", "section-title", "成果与检查"));
    if (!items.length) section.append(element(doc, "p", "empty", "当前来源未提供成果项；不据此推断没有产物。"));
    const list = element(doc, "ul", "item-list");
    items.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const row = element(doc, "li", "item");
      const status = Object.hasOwn(statusLabels, item.state) ? statusLabels[item.state]
        : ["?", text(item.state, "待核实"), "unknown"];
      const itemHeader = element(doc, "div", "item-header");
      itemHeader.append(element(doc, "span", `item-state ${status[2]}`, `${status[0]} ${status[1]}`));
      itemHeader.append(element(doc, "strong", "item-label", text(item.label, text(item.item_id))));
      row.append(itemHeader);
      const refs = strings(item.evidence_refs);
      if (refs.length) {
        const evidence = element(doc, "details", "evidence");
        evidence.dataset.detailKey = `evidence:${text(item.item_id)}`;
        evidence.append(element(doc, "summary", "", `证据引用 · ${refs.length}`));
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
      budget.append(element(doc, "summary", "", "原范围预算"));
      const facts = element(doc, "dl", "facts");
      facts.append(field(doc, "已消耗尝试", serial(business.budget.attempts_consumed)));
      facts.append(field(doc, "剩余尝试", serial(business.budget.attempts_remaining)));
      budget.append(facts, element(doc, "p", "note", "直接展示所选范围的预算，不换算完成率。"));
      fragment.append(budget);
    }
    const provenance = element(doc, "details", "details-block");
    provenance.dataset.detailKey = "provenance";
    provenance.append(element(doc, "summary", "", "范围、来源与观察时间"));
    const facts = element(doc, "dl", "facts");
    facts.append(field(doc, "范围", serial(business.scope_ref)), field(doc, "提案", serial(business.proposal_ref)));
    if (selection.program_id !== undefined) facts.append(field(doc, "Program", text(selection.program_id)));
    if (selection.prepared_event_id !== undefined) facts.append(field(doc, "Prepared", text(selection.prepared_event_id)));
    facts.append(field(doc, "来源版本", serial(business.source_revision)));
    facts.append(field(doc, "观察时间", timestamp(observation.observed_at)));
    facts.append(field(doc, "最近输出活动", timestamp(observation.activity && observation.activity.last_output_at)));
    facts.append(field(doc, "展示组件", `${text(component && component.id)} · ${text(component && component.version)}`));
    facts.append(field(doc, "传输序号", `${text(transport.session_id)} / ${transport.sequence}`));
    provenance.append(facts, element(doc, "p", "note", "来源版本、输出活动和连接传输分别记录；活动或心跳不代表完成。"));
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
      setConnection(state.snapshot ? "stale" : "error", "更新与当前运行不匹配或无法读取，保留最后可解释快照。");
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
    setConnection("connecting", "等待完整来源快照。");
    const stream = new EventSource(`api/events?run=${encodeURIComponent(run.id)}`);
    source = stream;
    stream.addEventListener("snapshot", (event) => {
      if (epoch !== generation) return;
      try { acceptSnapshot(JSON.parse(event.data), epoch); }
      catch (_) { setConnection(state.snapshot ? "stale" : "error", "收到无法读取的更新，等待后续完整快照。"); }
    });
    stream.onopen = () => {
      if (epoch === generation) setConnection("connecting", "连接已建立，等待完整来源快照。");
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
        setConnection(state.snapshot ? "stale" : "error", "宿主没有提供可观察的运行；本页不会创建或启动业务。");
        return;
      }
      runs.forEach((run) => {
        const label = [scopeName(run), ...scopeLabels(run.selection), text(run.selection.project_id), text(run.selection.run_id), text(run.selection.project_version)].join(" · ");
        const option = element(document, "option", "", label);
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

  function savePreference(value) {
    try { localStorage.setItem(preferenceKey, value); } catch (_) { /* Optional preference; viewing still works. */ }
  }

  function openPip() {
    if (pipWindow && !pipWindow.closed) { pipWindow.focus(); return; }
    if (pipOpening) return;
    if (!window.documentPictureInPicture || typeof window.documentPictureInPicture.requestWindow !== "function") {
      notice.textContent = "当前浏览器未提供 Document Picture-in-Picture，继续使用侧栏。普通窗口不算画中画。";
      return;
    }
    let request;
    const requestId = ++pipRequest;
    try {
      // Must be called synchronously inside this click handler, before any await.
      request = window.documentPictureInPicture.requestWindow({width: 360, height: 240});
      pipOpening = true;
      pipButton.disabled = true;
    } catch (_) {
      notice.textContent = "浏览器未允许打开画中画，侧栏仍可使用。需要时可再次点击尝试。";
      return;
    }
    Promise.resolve(request).then((openedWindow) => {
      if (requestId !== pipRequest) { openedWindow.close(); return; }
      pipWindow = openedWindow;
      const doc = openedWindow.document;
      doc.documentElement.lang = "zh-CN";
      doc.title = "运行观察 · 画中画";
      const stylesheet = doc.createElement("link");
      stylesheet.rel = "stylesheet";
      stylesheet.href = new URL("style.css", document.baseURI).href;
      doc.head.append(stylesheet);
      doc.body.className = "pip";
      const container = element(doc, "main", "pip-shell");
      pipDashboard = element(doc, "div", "pip-dashboard");
      container.append(pipDashboard);
      const detailsButton = element(doc, "button", "pip-details", "查看详情");
      detailsButton.type = "button";
      detailsButton.addEventListener("click", () => { window.focus(); selector.focus(); });
      container.append(detailsButton);
      doc.body.replaceChildren(container);
      openedWindow.addEventListener("pagehide", () => {
        if (pipWindow === openedWindow) {
          pipWindow = null;
          pipDashboard = null;
          notice.textContent = "画中画已关闭，侧栏继续更新；不会自动重新打开。";
        }
      }, {once: true});
      savePreference("pip");
      notice.textContent = "画中画与侧栏共享同一份状态；关闭浮窗不会停止业务。";
      render();
    }).catch(() => {
      notice.textContent = "画中画未能打开，继续使用侧栏。需要时可再次点击尝试。";
    }).finally(() => { pipOpening = false; pipButton.disabled = false; });
  }

  selector.addEventListener("change", () => {
    const run = state.runs.find((item) => item.id === selector.value);
    if (run) subscribe(run);
  });
  pipButton.addEventListener("click", openPip);
  sidebarButton.addEventListener("click", () => {
    pipRequest += 1;
    savePreference("sidebar");
    if (pipWindow && !pipWindow.closed) pipWindow.close();
    notice.textContent = "已记住侧栏偏好。仍可随时点击“画中画查看”。";
  });
  reconnectButton.addEventListener("click", loadRuns);
  window.addEventListener("pagehide", () => { if (source) source.close(); });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && state.selected) subscribe(state.selected, true);
  });
  try {
    notice.textContent = localStorage.getItem(preferenceKey) === "sidebar"
      ? "已采用你的侧栏偏好；需要时可打开画中画。"
      : "可点击“画中画查看”打开紧凑浮窗；浏览器需要这次点击。";
  } catch (_) {
    notice.textContent = "可点击“画中画查看”打开紧凑浮窗。";
  }
  setInterval(() => {
    document.querySelectorAll("[data-freshness]").forEach((node) => { node.textContent = `服务快照：${ageLabel(state.lastReceived)}`; });
    if (pipWindow && !pipWindow.closed) pipWindow.document.querySelectorAll("[data-freshness]").forEach((node) => { node.textContent = `服务快照：${ageLabel(state.lastReceived)}`; });
  }, 1000);
  render();
  loadRuns();
})();
