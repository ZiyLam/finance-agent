import assert from "node:assert/strict";
import test from "node:test";

import { resolveApiUrl } from "../web/api-client.js";

test.afterEach(() => {
  delete globalThis.FINANCE_AGENT_CONFIG;
});

test("keeps API paths relative when no independent backend is configured", () => {
  globalThis.FINANCE_AGENT_CONFIG = { apiBaseUrl: "" };
  assert.equal(resolveApiUrl("/v1/web/status"), "/v1/web/status");
});

test("joins an independent API base URL and removes its trailing slash", () => {
  globalThis.FINANCE_AGENT_CONFIG = { apiBaseUrl: "https://api.example.com/finance/" };
  assert.equal(resolveApiUrl("/v1/web/status"), "https://api.example.com/finance/v1/web/status");
});

test("rejects external or ambiguous API paths", () => {
  assert.throws(() => resolveApiUrl("https://evil.example/v1"), TypeError);
  assert.throws(() => resolveApiUrl("//evil.example/v1"), TypeError);
});

test("rejects invalid API base URLs", () => {
  globalThis.FINANCE_AGENT_CONFIG = { apiBaseUrl: "javascript:alert(1)" };
  assert.throws(() => resolveApiUrl("/v1/web/status"), /HTTP\(S\)/);

  globalThis.FINANCE_AGENT_CONFIG = { apiBaseUrl: "https://api.example.com?" };
  assert.throws(() => resolveApiUrl("/v1/web/status"), /查询参数/);
});
