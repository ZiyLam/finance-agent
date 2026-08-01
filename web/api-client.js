/* Same-origin API client; credentials remain in session storage only. */

const TOKEN_KEY = "finance-agent.web-access-token";

export async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (token) headers.set("X-Finance-Agent-Token", token);
  let response;
  try {
    response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  } catch {
    throw new Error("无法连接 API。请启动 finance-agent-api，并通过 /web/ 打开页面。");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof payload.detail === "string" ? payload.detail : "API 请求未完成");
    error.requestId = response.headers.get("X-Request-ID") || "";
    throw error;
  }
  return payload;
}

