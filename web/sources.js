import { apiFetch } from "./api-client.js";

const WEB_ACCESS_TOKEN_KEY = "finance-agent.web-access-token";

const elements = {
  apiDot: document.querySelector("#api-dot"),
  apiStatus: document.querySelector("#api-status"),
  apiToken: document.querySelector("#api-token"),
  connectApi: document.querySelector("#connect-api"),
  refreshSources: document.querySelector("#refresh-sources"),
  testAllSources: document.querySelector("#test-all-sources"),
  testAllLlms: document.querySelector("#test-all-llms"),
  sourceList: document.querySelector("#source-settings-list"),
  sourcesSummary: document.querySelector("#sources-summary"),
  llmList: document.querySelector("#llm-settings-list"),
  llmSummary: document.querySelector("#llm-summary"),
  toast: document.querySelector("#toast"),
};

let toastTimer;
let sources = [];

const CONFIGURATION_GROUPS = {
  dataSource: "data_source",
  llm: "llm",
};

async function request(path, options = {}) {
  return apiFetch(path, options);
}

function setConnection(state, message) {
  elements.apiDot.className = `status-dot ${state}`;
  elements.apiStatus.textContent = message;
}

function sourceOriginText(source) {
  if (source.credential_origin === "environment_variable") return `已由环境变量 ${source.token_environment_variable} 配置`;
  if (source.credential_origin === "secure_local_store") return "已保存到当前 Windows 用户的加密本地存储";
  return "尚未配置令牌";
}

function sourceUsageText(source) {
  if (source.configuration_group === CONFIGURATION_GROUPS.llm) {
    return source.token_required_by_adapter
      ? "当前 LLM 适配器会使用此令牌。"
      : "当前 LLM 适配器不读取此令牌。";
  }
  if (source.token_required_by_adapter) return "当前数据适配器会使用此令牌。";
  return "当前适配器不读取此令牌；此维护槽用于将来的服务变更或个人备忘。";
}

function connectivityState(source) {
  return source.connectivity || {
    name: source.name,
    status: "untested",
    checked_at: null,
    duration_ms: null,
    message: "尚未执行连通性测试。",
  };
}

function connectivityLabel(status) {
  return {
    untested: "未测试",
    checking: "测试中",
    healthy: "连接正常",
    not_configured: "未配置",
    local_unavailable: "本地不可用",
    remote_failure: "远端失败",
    unsupported: "暂不支持",
    disabled: "已停用",
  }[status] || "状态未知";
}

function formatCheckedAt(value) {
  if (!value) return "尚无测试时间";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? "测试时间不可用" : `检查于 ${timestamp.toLocaleString("zh-CN")}`;
}

function formatDuration(value) {
  if (value === null || value === undefined || value === "") return "";
  const milliseconds = Number(value);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "";
  return milliseconds < 1_000 ? `${Math.round(milliseconds)} ms` : `${(milliseconds / 1_000).toFixed(1)} 秒`;
}

function createElement(name, className, text) {
  const element = document.createElement(name);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderSources() {
  renderConfigurationGroup({
    group: CONFIGURATION_GROUPS.dataSource,
    list: elements.sourceList,
    summary: elements.sourcesSummary,
    noun: "数据源",
  });
  renderConfigurationGroup({
    group: CONFIGURATION_GROUPS.llm,
    list: elements.llmList,
    summary: elements.llmSummary,
    noun: "LLM",
  });
}

function renderConfigurationGroup({ group, list, summary, noun }) {
  const groupSources = sources.filter((source) => source.configuration_group === group);
  list.replaceChildren();
  if (!groupSources.length) {
    list.append(createElement("p", "settings-empty", `当前未配置可维护的 ${noun}。`));
    summary.textContent = `共 0 个 ${noun}`;
    return;
  }
  const configured = groupSources.filter((source) => source.configured).length;
  const enabled = groupSources.filter((source) => source.enabled).length;
  const healthy = groupSources.filter((source) => connectivityState(source).status === "healthy").length;
  const remoteFailures = groupSources.filter((source) => connectivityState(source).status === "remote_failure").length;
  const failureText = remoteFailures ? `，${remoteFailures} 个远端失败` : "";
  const countLabel = noun === "LLM" ? `${groupSources.length} 个 LLM` : `${groupSources.length} 个数据源`;
  summary.textContent = `共 ${countLabel}，${enabled} 个已启用，${configured} 个已配置令牌，${healthy} 个连接正常${failureText}`;
  for (const source of groupSources) list.append(createSourceCard(source));
}

function createSourceCard(source) {
  const connectivity = connectivityState(source);
  const card = createElement(
    "article",
    `source-settings-card configuration-${source.configuration_group} connectivity-${connectivity.status}${source.enabled ? "" : " provider-disabled"}`,
  );
  const heading = createElement("div", "source-card-heading");
  const title = createElement("div");
  title.append(createElement("h3", "", source.display_name));
  title.append(createElement("p", "source-name", source.name));
  const badge = createElement(
    "span",
    `source-config-badge ${source.configured ? "configured" : ""}`,
    source.token_required_by_adapter ? (source.configured ? "令牌已配置" : "需要令牌") : "当前无需令牌",
  );
  const headingActions = createElement("div", "source-card-actions");
  const activation = createElement(
    "button",
    `source-enable-toggle${source.enabled ? " enabled" : ""}`,
    source.enabled ? "已启用" : "未启用",
  );
  activation.type = "button";
  activation.setAttribute("role", "switch");
  activation.setAttribute("aria-checked", String(Boolean(source.enabled)));
  activation.setAttribute("aria-label", `${source.display_name}：${source.enabled ? "已启用，点击停用" : "未启用，点击启用"}`);
  activation.addEventListener("click", () => setProviderEnabled(source, activation));
  headingActions.append(badge, activation);
  heading.append(title, headingActions);

  const status = createElement("p", `source-origin ${source.configured ? "configured" : ""}`, sourceOriginText(source));
  const usage = createElement("p", "source-usage", sourceUsageText(source));
  const metadata = createElement("dl", "source-metadata");
  addMetadata(metadata, "令牌环境变量", source.token_environment_variable);
  if (source.base_url_environment_variable) {
    addMetadata(metadata, "服务地址", `由 ${source.base_url_environment_variable} 环境变量或默认本机地址决定`);
  }
  if (source.status_description) addMetadata(metadata, "当前说明", source.status_description);
  if (source.latency_class) {
    addMetadata(metadata, source.configuration_group === CONFIGURATION_GROUPS.llm ? "响应延迟分类" : "延迟分类", source.latency_class);
  }
  if (Number.isInteger(source.routing_priority)) {
    addMetadata(metadata, source.configuration_group === CONFIGURATION_GROUPS.llm ? "模型优先级" : "调用优先级", String(source.routing_priority));
  }
  if (source.tags.length) {
    const tags = createElement("div", "source-tags source-setting-tags");
    for (const tag of source.tags) tags.append(createElement("span", "", tag));
    metadata.append(createElement("dt", "", "能力标签"), createElement("dd", "", ""));
    metadata.lastElementChild.append(tags);
  }

  const connectivityPanel = createElement("section", "source-connectivity");
  const connectivityHeading = createElement("div", "source-connectivity-heading");
  connectivityHeading.append(
    createElement("strong", "", "连通状态"),
    createElement("span", `source-connectivity-badge ${connectivity.status}`, connectivityLabel(connectivity.status)),
  );
  const connectivityMessage = createElement("p", "source-connectivity-message", connectivity.message || "尚未执行连通性测试。");
  const duration = formatDuration(connectivity.duration_ms);
  const checkedMetadata = createElement(
    "p",
    "source-connectivity-metadata",
    [formatCheckedAt(connectivity.checked_at), duration && `耗时 ${duration}`].filter(Boolean).join(" · "),
  );
  const check = createElement(
    "button",
    "button button-secondary source-connectivity-button",
    connectivity.status === "checking" ? "正在测试…" : "测试连通",
  );
  check.type = "button";
  check.disabled = connectivity.status === "checking" || !source.enabled;
  if (!source.enabled) check.title = "启用此提供方后才能测试连通性";
  check.addEventListener("click", () => testSourceConnectivity(source));
  connectivityPanel.append(connectivityHeading, connectivityMessage, checkedMetadata, check);

  card.append(heading, status, usage, connectivityPanel, metadata);

  const form = createElement("div", "source-token-form");
  const label = createElement("label", "field compact-field");
  label.append(createElement("span", "", "新令牌"));
  const input = document.createElement("input");
  input.type = "password";
  input.autocomplete = "new-password";
  input.placeholder = "输入后加密保存，不会回显";
  input.setAttribute("aria-label", `${source.display_name} 的新令牌`);
  label.append(input);
  const actions = createElement("div", "source-token-actions");
  const save = createElement("button", "button button-primary", "保存令牌");
  save.type = "button";
  save.addEventListener("click", () => saveToken(source, input, save));
  const remove = createElement("button", "button button-danger", "删除本地令牌");
  remove.type = "button";
  remove.addEventListener("click", () => deleteToken(source, remove));
  actions.append(save, remove);
  form.append(label, actions);
  card.append(form);
  return card;
}

function replaceConnectivity(name, connectivity) {
  sources = sources.map((source) => source.name === name ? { ...source, connectivity } : source);
}

async function testSourceConnectivity(source) {
  if (!source.enabled) {
    showToast(`请先启用 ${source.display_name}`);
    return;
  }
  const previous = connectivityState(source);
  replaceConnectivity(source.name, {
    ...previous,
    status: "checking",
    message: "正在执行最小只读连接测试…",
  });
  renderSources();
  try {
    const response = await request(`/v1/web/sources/${encodeURIComponent(source.name)}/connectivity`, {
      method: "POST",
    });
    replaceConnectivity(source.name, response.source);
    renderSources();
    showToast(`${source.display_name}：${connectivityLabel(response.source.status)}`);
  } catch (error) {
    replaceConnectivity(source.name, previous);
    renderSources();
    showToast(`连通性测试未完成：${error.message}`);
  }
}

async function testConfigurationGroup(group, button, idleLabel, noun) {
  const groupSources = sources.filter((source) => source.configuration_group === group);
  const previous = new Map(groupSources.map((source) => [source.name, connectivityState(source)]));
  sources = sources.map((source) => ({
    ...source,
    connectivity: source.configuration_group === group && source.enabled
      ? { ...connectivityState(source), status: "checking", message: "等待或正在执行只读连接测试…" }
      : connectivityState(source),
  }));
  renderSources();
  setBusy(button, true, "正在测试…");
  try {
    const response = await request(
      `/v1/web/sources/connectivity?configuration_group=${encodeURIComponent(group)}`,
      { method: "POST" },
    );
    const results = new Map((Array.isArray(response.sources) ? response.sources : []).map((item) => [item.name, item]));
    sources = sources.map((source) => ({
      ...source,
      connectivity: source.configuration_group === group
        ? results.get(source.name) || previous.get(source.name)
        : connectivityState(source),
    }));
    renderSources();
    const remoteFailures = sources.filter(
      (source) => source.configuration_group === group && connectivityState(source).status === "remote_failure",
    ).length;
    showToast(remoteFailures ? `${noun}测试完成：${remoteFailures} 个远端连接失败` : `全部 ${noun} 连通性测试已完成`);
  } catch (error) {
    await loadSources();
    showToast(`${noun}批量测试未完成：${error.message}`);
  } finally {
    setBusy(button, false, idleLabel);
  }
}

async function setProviderEnabled(source, button) {
  const enabled = !source.enabled;
  setBusy(button, true, enabled ? "正在启用…" : "正在停用…");
  try {
    await request(`/v1/web/sources/${encodeURIComponent(source.name)}/enabled`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    await loadSources();
    showToast(`${source.display_name} 已${enabled ? "启用" : "停用"}`);
  } catch (error) {
    showToast(`未能更新启用状态：${error.message}`);
  } finally {
    setBusy(button, false, enabled ? "已启用" : "未启用");
  }
}

function addMetadata(container, label, value) {
  container.append(createElement("dt", "", label), createElement("dd", "", value));
}

async function loadSources() {
  elements.refreshSources.disabled = true;
  elements.refreshSources.textContent = "正在刷新…";
  try {
    const response = await request("/v1/web/sources");
    sources = Array.isArray(response.sources) ? response.sources : [];
    renderSources();
    setConnection("saved", "已连接 Finance Agent API");
  } catch (error) {
    elements.sourceList.replaceChildren(createElement("p", "settings-empty settings-error", `无法读取配置：${error.message}`));
    elements.llmList.replaceChildren(createElement("p", "settings-empty settings-error", `无法读取配置：${error.message}`));
    elements.sourcesSummary.textContent = "配置目录未加载";
    elements.llmSummary.textContent = "模型目录未加载";
    setConnection("error", "无法连接 Finance Agent API");
  } finally {
    elements.refreshSources.disabled = false;
    elements.refreshSources.textContent = "刷新状态";
  }
}

async function saveToken(source, input, button) {
  const token = input.value;
  if (!token.trim()) {
    showToast("请先输入要保存的令牌");
    input.focus();
    return;
  }
  setBusy(button, true, "正在保存…");
  try {
    await request(`/v1/web/sources/${encodeURIComponent(source.name)}/token`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    input.value = "";
    await loadSources();
    showToast(`${source.display_name} 的令牌已加密保存`);
  } catch (error) {
    showToast(`未能保存令牌：${error.message}`);
  } finally {
    setBusy(button, false, "保存令牌");
  }
}

async function deleteToken(source, button) {
  const message = source.credential_origin === "environment_variable"
    ? `将删除 ${source.display_name} 的本地加密令牌。环境变量 ${source.token_environment_variable} 不会被修改，且仍会优先使用。是否继续？`
    : `将删除 ${source.display_name} 的本地加密令牌。此操作无法恢复，是否继续？`;
  if (!window.confirm(message)) return;
  setBusy(button, true, "正在删除…");
  try {
    const response = await request(`/v1/web/sources/${encodeURIComponent(source.name)}/token`, { method: "DELETE" });
    await loadSources();
    showToast(response.source.stored_token_deleted ? "本地加密令牌已删除" : "未找到可删除的本地令牌");
  } catch (error) {
    showToast(`未能删除令牌：${error.message}`);
  } finally {
    setBusy(button, false, "删除本地令牌");
  }
}

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.textContent = label;
}

function showToast(message) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 3400);
}

elements.connectApi.addEventListener("click", () => {
  const token = elements.apiToken.value.trim();
  if (token) sessionStorage.setItem(WEB_ACCESS_TOKEN_KEY, token);
  else sessionStorage.removeItem(WEB_ACCESS_TOKEN_KEY);
  elements.apiToken.value = "";
  loadSources();
});
elements.refreshSources.addEventListener("click", loadSources);
elements.testAllSources.addEventListener("click", () => testConfigurationGroup(
  CONFIGURATION_GROUPS.dataSource,
  elements.testAllSources,
  "测试全部数据源",
  "数据源",
));
elements.testAllLlms.addEventListener("click", () => testConfigurationGroup(
  CONFIGURATION_GROUPS.llm,
  elements.testAllLlms,
  "测试全部 LLM",
  "LLM",
));

loadSources();
