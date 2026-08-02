/* Shared Web API client; access tokens remain in session storage only. */

const TOKEN_KEY = "finance-agent.web-access-token";

function apiBaseUrl() {
  const configured = String(globalThis.FINANCE_AGENT_CONFIG?.apiBaseUrl || "").trim();
  if (!configured) return "";

  let parsed;
  try {
    parsed = new URL(configured);
  } catch {
    throw new Error("FINANCE_AGENT_CONFIG.apiBaseUrl 必须是完整的 HTTP(S) 地址");
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("FINANCE_AGENT_CONFIG.apiBaseUrl 必须是完整的 HTTP(S) 地址");
  }
  if (
    parsed.username
    || parsed.password
    || configured.includes("?")
    || configured.includes("#")
  ) {
    throw new Error("FINANCE_AGENT_CONFIG.apiBaseUrl 不能包含凭据、查询参数或片段");
  }
  return configured.replace(/\/+$/, "");
}

export function resolveApiUrl(path) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) {
    throw new TypeError("API path 必须是以单个 / 开头的站内路径");
  }
  const baseUrl = apiBaseUrl();
  return baseUrl ? `${baseUrl}${path}` : path;
}

function requestCredentials(url) {
  if (!globalThis.location) return "include";
  const targetOrigin = new URL(url, globalThis.location.href).origin;
  return targetOrigin === globalThis.location.origin ? "same-origin" : "include";
}

export async function apiFetch(path, options = {}) {
  const url = resolveApiUrl(path);
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (token) headers.set("X-Finance-Agent-Token", token);
  let response;
  try {
    response = await fetch(url, { ...options, headers, credentials: requestCredentials(url) });
  } catch {
    throw new Error("无法连接 Finance Agent API。请检查后端服务和网页 API 地址配置。");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof payload.detail === "string" ? payload.detail : "API 请求未完成");
    error.requestId = response.headers.get("X-Request-ID") || "";
    throw error;
  }
  return payload;
}
