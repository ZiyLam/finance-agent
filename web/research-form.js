/* Professional research mode and bounded form payload construction. */

let elements;
let notify;
let conversationId;
let researchMode = "simple";
let professionalOptions = null;

export function configureResearchForm(options) {
  elements = options.elements;
  notify = options.notify;
  conversationId = options.conversationId;
}

export function getResearchMode() {
  return researchMode;
}

export function getProfessionalOptions() {
  return professionalOptions;
}

export function setResearchMode(mode) {
  researchMode = mode === "professional" ? "professional" : "simple";
  const professional = researchMode === "professional";
  elements.simpleMode.classList.toggle("active", !professional);
  elements.professionalMode.classList.toggle("active", professional);
  elements.simpleMode.setAttribute("aria-pressed", String(!professional));
  elements.professionalMode.setAttribute("aria-pressed", String(professional));
  elements.professionalControls.hidden = !professional;
  elements.requestPanel.classList.toggle("is-professional", professional);
  elements.requestIntro.textContent = professional
    ? "明确选择日期、市场、指数和研究指标。多指数行情会并行读取，每个指数的行情类指标共用一次请求，不再依赖模型推断输入范围。"
    : "可以直接输入模糊想法、问题或分析目标。系统会先识别意图，再通过 LCEL 检索增强链路补充可用能力和研究边界，最后交由 LangChain Agent 分析；必要时由 Agent 自然追问，不要求按固定格式填写。";
  elements.requestFieldLabel.textContent = professional ? "补充研究说明（可选）" : "研究请求";
  elements.request.placeholder = professional
    ? "例如：重点比较大小盘风格差异，并说明数据不可比之处。"
    : "例如：我想了解新能源板块近期值得关注什么，或者请分析 600000 的历史走势。";
  if (elements.requestExamples.length === 2) {
    elements.requestExamples[0].textContent = professional
      ? "示例：跨市场比较恒生指数与标普 500"
      : "示例：查询 600000 最新价格";
    elements.requestExamples[1].textContent = professional
      ? "示例：只勾选风格与风险，不读取行情"
      : "示例：分析 AAPL.US 近三个月走势";
  }
}

export function initializeProfessionalForm(catalog) {
  if (!catalog || !Array.isArray(catalog.markets) || !Array.isArray(catalog.indices) || !Array.isArray(catalog.metrics)) {
    professionalOptions = null;
    elements.professionalNote.textContent = "专业版选项暂不可用，请刷新页面或检查服务状态。";
    return;
  }
  professionalOptions = catalog;
  elements.professionalMarketOptions.replaceChildren();
  elements.professionalIndexOptions.replaceChildren();
  elements.professionalMetricOptions.replaceChildren();

  for (const market of catalog.markets) {
    const option = createProfessionalOption("professional-market", market.key, market.label, market.key === "a_share");
    const marketInput = option.querySelector("input");
    marketInput.addEventListener("change", () => {
      if (!marketInput.checked) {
        for (const indexOption of elements.professionalIndexOptions.querySelectorAll(".professional-option")) {
          if (indexOption.dataset.market === market.key) indexOption.querySelector("input").checked = false;
        }
      }
      syncProfessionalIndexOptions();
    });
    elements.professionalMarketOptions.append(option);
  }
  for (const index of catalog.indices) {
    const option = createProfessionalOption(
      "professional-index",
      index.key,
      `${index.display_name} · ${index.symbol}`,
      ["csi_300", "csi_500"].includes(index.key),
    );
    option.dataset.market = index.market;
    const indexInput = option.querySelector("input");
    indexInput.addEventListener("change", () => {
      if (indexInput.checked) {
        const matchingMarket = [...elements.professionalMarketOptions.querySelectorAll("input")]
          .find((input) => input.value === index.market);
        if (matchingMarket) matchingMarket.checked = true;
      }
      syncProfessionalIndexOptions();
    });
    elements.professionalIndexOptions.append(option);
  }
  for (const metric of catalog.metrics) {
    elements.professionalMetricOptions.append(
      createProfessionalOption("professional-metric", metric.key, metric.label, true),
    );
  }

  if (!elements.professionalEndDate.value) {
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - 7);
    elements.professionalStartDate.value = localIsoDate(start);
    elements.professionalEndDate.value = localIsoDate(end);
  }
  syncProfessionalIndexOptions();
  elements.professionalNote.textContent = `日期默认过去一周；可直接勾选指数并自动启用所属市场，最多选择 ${catalog.maximum_indices || 6} 个指数，每个指数最多读取 ${catalog.maximum_trading_days_per_index || 120} 个交易日。`;
}

function createProfessionalOption(name, value, labelText, checked) {
  const label = document.createElement("label");
  label.className = "professional-option";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.name = name;
  input.value = value;
  input.checked = checked;
  label.append(input, document.createTextNode(labelText));
  return label;
}

function syncProfessionalIndexOptions() {
  const selectedMarkets = new Set(
    [...elements.professionalMarketOptions.querySelectorAll('input:checked')].map((input) => input.value),
  );
  for (const option of elements.professionalIndexOptions.querySelectorAll(".professional-option")) {
    option.classList.toggle("outside-market", !selectedMarkets.has(option.dataset.market));
  }
}

export function buildProfessionalPayload(content) {
  if (!professionalOptions) {
    notify("专业版选项尚未加载，请刷新页面");
    return null;
  }
  const startDate = elements.professionalStartDate.value;
  const endDate = elements.professionalEndDate.value;
  const markets = checkedValues(elements.professionalMarketOptions, "professional-market");
  const indices = checkedValues(elements.professionalIndexOptions, "professional-index");
  const metrics = checkedValues(elements.professionalMetricOptions, "professional-metric");
  if (!startDate || !endDate) {
    notify("请选择完整的开始日期和结束日期");
    return null;
  }
  if (startDate > endDate) {
    notify("开始日期不能晚于结束日期");
    return null;
  }
  if (!markets.length) {
    notify("请至少选择一个研究市场");
    return null;
  }
  if (!indices.length) {
    notify("请至少勾选一个研究指数");
    return null;
  }
  if (indices.length > (professionalOptions.maximum_indices || 6)) {
    notify(`最多选择 ${professionalOptions.maximum_indices || 6} 个研究指数`);
    return null;
  }
  if (!metrics.length) {
    notify("请至少勾选一个研究指标");
    return null;
  }
  return {
    conversation_id: conversationId,
    content,
    start_date: startDate,
    end_date: endDate,
    markets,
    indices,
    metrics,
  };
}

function checkedValues(container, name) {
  return [...container.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value);
}

function localIsoDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

