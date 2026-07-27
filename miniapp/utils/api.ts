import { API_BASE_URL } from "../config";

const SESSION_KEY = "finance_agent_access_token";
const SESSION_EXPIRY_KEY = "finance_agent_access_token_expiry";

export interface Clarification {
  field: string;
  question: string;
  options: string[];
}

export interface ResearchIntent {
  scenario: string;
  market: string | null;
  symbol: string | null;
  start_date: string | null;
  end_date: string | null;
  assumptions: string[];
  clarifications: Clarification[];
}

export interface Submission {
  status: "needs_clarification" | "queued" | "completed" | "failed";
  intent: ResearchIntent;
  task_id: string | null;
  assistant_message: string | null;
}

export interface ResearchTask {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  report_id: string | null;
  safe_error: string | null;
  intent: ResearchIntent;
}

interface LoginResponse {
  access_token: string;
  expires_at: string;
}

interface ApiErrorPayload {
  detail?: string;
}

function token(): string {
  const value = wx.getStorageSync(SESSION_KEY);
  return typeof value === "string" ? value : "";
}

function hasValidSession(): boolean {
  const expiresAt = wx.getStorageSync(SESSION_EXPIRY_KEY);
  return typeof expiresAt === "number" && expiresAt > Date.now() + 60_000 && Boolean(token());
}

export async function ensureSession(): Promise<void> {
  if (hasValidSession()) {
    return;
  }
  const login = await wx.login();
  if (!login.code) {
    throw new Error("微信登录未返回有效 code");
  }
  const result = await request<LoginResponse>("POST", "/v1/auth/wechat/login", { code: login.code }, false);
  wx.setStorageSync(SESSION_KEY, result.access_token);
  wx.setStorageSync(SESSION_EXPIRY_KEY, Date.parse(result.expires_at));
}

export async function createConversation(): Promise<{ id: string }> {
  return request("POST", "/v1/conversations", {});
}

export async function submitMessage(conversationId: string, content: string): Promise<Submission> {
  return request("POST", `/v1/conversations/${encodeURIComponent(conversationId)}/messages`, { content });
}

export async function getTask(taskId: string): Promise<ResearchTask> {
  return request("GET", `/v1/tasks/${encodeURIComponent(taskId)}`);
}

export async function getReport(reportId: string): Promise<{ report: Record<string, unknown> }> {
  return request("GET", `/v1/reports/${encodeURIComponent(reportId)}`);
}

async function request<Result>(
  method: "GET" | "POST",
  path: string,
  data?: Record<string, unknown>,
  authenticated = true
): Promise<Result> {
  if (authenticated) {
    await ensureSession();
  }
  return new Promise<Result>((resolve, reject) => {
    wx.request({
      url: `${API_BASE_URL}${path}`,
      method,
      data,
      header: authenticated ? { Authorization: `Bearer ${token()}` } : {},
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.data as Result);
          return;
        }
        const payload = response.data as ApiErrorPayload;
        reject(new Error(payload.detail || "服务暂时不可用"));
      },
      fail(error) {
        reject(new Error(error.errMsg || "网络请求失败"));
      }
    });
  });
}
