import { apiFetch } from "./api-client.js";
import {
  buildProfessionalPayload,
  configureResearchForm,
  getProfessionalOptions,
  getResearchMode,
  initializeProfessionalForm,
  setResearchMode,
} from "./research-form.js";
import {
  configureResultRenderer,
  copyMarkdown,
  renderAgentResult,
  renderBeginnerSnapshot,
  renderCandidateSnapshots,
  renderIndexSnapshot,
  renderMarketScan,
  renderProfessionalIndexComparison,
  renderResearchError,
  setAnalysisDuration,
  setLastResult,
} from "./result-renderer.js";

const CONVERSATION_KEY = "finance-agent.web-conversation-id";

const elements = {
  apiDot: document.querySelector("#api-dot"),
  apiStatus: document.querySelector("#api-status"),
  requestPanel: document.querySelector(".request-panel"),
  requestIntro: document.querySelector("#request-intro"),
  requestFieldLabel: document.querySelector("#request-field-label"),
  request: document.querySelector("#user-request"),
  runResearch: document.querySelector("#run-research"),
  simpleMode: document.querySelector("#simple-mode"),
  professionalMode: document.querySelector("#professional-mode"),
  professionalControls: document.querySelector("#professional-controls"),
  professionalStartDate: document.querySelector("#professional-start-date"),
  professionalEndDate: document.querySelector("#professional-end-date"),
  professionalMarketOptions: document.querySelector("#professional-market-options"),
  professionalIndexOptions: document.querySelector("#professional-index-options"),
  professionalMetricOptions: document.querySelector("#professional-metric-options"),
  professionalNote: document.querySelector("#professional-note"),
  requestExamples: document.querySelectorAll(".request-examples span"),
  resultState: document.querySelector("#result-state"),
  chainStatus: document.querySelector("#chain-status"),
  chainReferences: document.querySelector("#chain-references"),
  resultKicker: document.querySelector("#result-kicker"),
  resultTitle: document.querySelector("#result-report-title"),
  resultScope: document.querySelector("#result-scope"),
  resultPeriod: document.querySelector("#result-period"),
  resultAnalysisDuration: document.querySelector("#result-analysis-duration"),
  resultSources: document.querySelector("#result-sources"),
  entityCandidates: document.querySelector("#entity-candidates"),
  summaryHeading: document.querySelector("#summary-heading"),
  observationsHeading: document.querySelector("#observations-heading"),
  risksHeading: document.querySelector("#risks-heading"),
  nextStepsHeading: document.querySelector("#next-steps-heading"),
  summary: document.querySelector("#result-summary"),
  observations: document.querySelector("#result-observations"),
  risks: document.querySelector("#result-risks"),
  nextSteps: document.querySelector("#result-next-steps"),
  copyMarkdown: document.querySelector("#copy-markdown"),
  toast: document.querySelector("#toast"),
  loadingOverlay: document.querySelector("#loading-overlay"),
  loadingMessage: document.querySelector("#loading-message"),
  appShell: document.querySelector(".app-shell"),
};
let apiCapabilities = null;
let toastTimer;
let researchInFlight = false;
const conversationId = sessionStorage.getItem(CONVERSATION_KEY) || newConversationId();
sessionStorage.setItem(CONVERSATION_KEY, conversationId);

configureResearchForm({ elements, notify: showToast, conversationId });
configureResultRenderer({ elements, notify: showToast, getProfessionalOptions });

elements.runResearch.addEventListener("click", runResearch);
elements.simpleMode.addEventListener("click", () => setResearchMode("simple"));
elements.professionalMode.addEventListener("click", () => setResearchMode("professional"));
elements.copyMarkdown.addEventListener("click", copyMarkdown);
elements.request.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    runResearch();
  }
});

connectApi();

async function connectApi() {
  setConnection("connecting", "正在连接本地 API…");
  try {
    apiCapabilities = await apiFetch("/v1/web/status");
    initializeProfessionalForm(apiCapabilities.professional_research);
    setConnection("connected", `已连接 · ${apiCapabilities.model_provider} · LCEL/RAG 就绪`);
  } catch (error) {
    apiCapabilities = null;
    setConnection("failed", "API 未连接");
    showToast(error.message || "无法连接 Finance Agent API");
  }
}

async function runResearch() {
  if (researchInFlight) return;
  const content = elements.request.value.trim();
  const researchMode = getResearchMode();
  if (researchMode === "simple" && !content) {
    showToast("请在文本框中描述研究需求");
    elements.request.focus();
    return;
  }
  if (!apiCapabilities) {
    await connectApi();
    if (!apiCapabilities) return;
  }

  researchInFlight = true;
  setBusy(elements.runResearch, true, "正在分析…");
  try {
    const professionalPayload = researchMode === "professional" ? buildProfessionalPayload(content) : null;
    if (researchMode === "professional" && !professionalPayload) return;
    const reply = await apiFetch(
      researchMode === "professional" ? "/v1/web/professional-research" : "/v1/web/chat",
      {
        method: "POST",
        body: JSON.stringify(professionalPayload || { conversation_id: conversationId, content }),
      },
    );
    setLastResult({ mode: reply.response_kind || "agent", ...reply });
    setAnalysisDuration(reply.analysis_duration_ms);
    if (reply.response_kind === "professional_index_comparison") {
      renderProfessionalIndexComparison(reply);
      showToast("专业版多指数研究已完成");
    } else if (reply.response_kind === "candidate_snapshots") {
      renderCandidateSnapshots(reply);
      showToast("已生成多个候选证券的基础概览");
    } else if (reply.response_kind === "beginner_snapshot") {
      renderBeginnerSnapshot(reply);
      showToast("基础概览已生成");
    } else if (reply.response_kind === "index_snapshot") {
      renderIndexSnapshot(reply);
      showToast("指数全景研究已完成");
    } else if (reply.response_kind === "market_scan") {
      renderMarketScan(reply);
      showToast(reply.snapshot?.status === "complete" ? "板块扫描已完成" : "板块数据源当前不可用");
    } else {
      renderAgentResult(reply);
      showToast("Agent 分析完成");
    }
  } catch (error) {
    setLastResult({ mode: "error", message: error.message, request_id: error.requestId || "" });
    renderResearchError(error);
    showToast(error.message || "研究请求失败");
  } finally {
    setBusy(elements.runResearch, false, "开始分析");
    researchInFlight = false;
  }
}

function setConnection(state, message) {
  elements.apiStatus.textContent = message;
  elements.apiDot.className = `status-dot${state === "connected" ? " saved" : state === "failed" ? " error" : ""}`;
}

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.textContent = label;
  elements.loadingOverlay.hidden = !busy;
  elements.loadingMessage.textContent = busy ? label : "正在分析…";
  elements.appShell.setAttribute("aria-busy", String(busy));
  document.body.classList.toggle("is-loading", busy);
}

function showToast(message) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 3100);
}

function newConversationId() {
  return globalThis.crypto?.randomUUID
    ? `web-${crypto.randomUUID().replaceAll("-", "")}`
    : `web-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

