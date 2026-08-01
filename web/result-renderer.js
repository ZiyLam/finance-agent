/* Research-result presentation and Markdown export. */

let elements;
let notify;
let getProfessionalOptions;
let lastResult = null;

export function configureResultRenderer(options) {
  elements = options.elements;
  notify = options.notify;
  getProfessionalOptions = options.getProfessionalOptions;
}

export function setLastResult(result) {
  lastResult = result;
}

export function renderProfessionalIndexComparison(reply) {
  const snapshots = Array.isArray(reply.snapshots) ? reply.snapshots : [];
  const selection = reply.snapshot || {};
  const period = reply.research_period || {};
  const selectedMarkets = Array.isArray(selection.markets) ? selection.markets : [];
  const selectedMetrics = Array.isArray(selection.metrics) ? selection.metrics : [];
  renderLanguageContext(reply.language_context);
  clearEntityCandidates();
  setResultState("专业研究完成", true);
  elements.resultKicker.textContent = "专业版 · 确定性多指数研究";
  elements.resultTitle.textContent = `${snapshots.length} 个指数对比结果`;
  elements.resultScope.textContent = `${selectedMarkets.map((key) => professionalOptionLabel("markets", key)).join(" · ")} · ${snapshots.length} 个指数`;
  elements.resultPeriod.textContent = period.start_date && period.end_date
    ? `精确区间：${period.start_date} 至 ${period.end_date}`
    : "未返回有效日期区间";
  renderTags(
    elements.resultSources,
    selectedMetrics.map((key) => professionalOptionLabel("metrics", key)),
    "未返回研究指标",
  );
  setRichSection(
    elements.summaryHeading,
    elements.summary,
    "区间对比结论",
    reply.text,
    "未生成多指数对比说明。",
  );

  elements.observationsHeading.textContent = selectedMetrics.some((metric) => (
    ["market_data", "period_performance", "market_sentiment"].includes(metric)
  )) ? "指数行情与表现" : "所选指数范围";
  elements.observations.replaceChildren();
  const comparisonGrid = document.createElement("span");
  comparisonGrid.className = "professional-comparison-grid";
  for (const snapshot of snapshots) comparisonGrid.append(createProfessionalIndexCard(snapshot));
  if (!snapshots.length) comparisonGrid.textContent = "未返回指数研究结果。";
  elements.observations.append(comparisonGrid);
  elements.observations.classList.toggle("placeholder", !snapshots.length);

  elements.risksHeading.textContent = "风格、成分边界与风险";
  elements.risks.replaceChildren();
  let boundaryCount = 0;
  for (const snapshot of snapshots) {
    const index = snapshot.index || {};
    const style = snapshot.valuation_style || {};
    const industries = snapshot.constituent_industries || {};
    const risks = Array.isArray(snapshot.risks) ? snapshot.risks : [];
    if (!style.style && !industries.industry_note && !risks.length) continue;
    boundaryCount += 1;
    const block = document.createElement("span");
    block.className = "professional-boundary-block";
    const title = document.createElement("strong");
    title.textContent = index.display_name || index.symbol || "指数";
    block.append(title);
    if (style.style) block.append(document.createTextNode(`\n风格：${style.style}`));
    if (style.valuation) block.append(document.createTextNode(`\n估值边界：${style.valuation}`));
    if (industries.industry_note) block.append(document.createTextNode(`\n成分行业：${industries.industry_note}`));
    if (risks.length) block.append(document.createTextNode(`\n风险：${risks.join("；")}`));
    elements.risks.append(block);
  }
  if (!boundaryCount) elements.risks.textContent = "本次未勾选风格、成分行业或风险指标。";
  elements.risks.classList.toggle("placeholder", !boundaryCount);

  elements.nextStepsHeading.textContent = "数据边界";
  const limitations = [...new Set(snapshots.flatMap((snapshot) => (
    Array.isArray(snapshot.limitations) ? snapshot.limitations : []
  )))];
  renderNextSteps(limitations, "当前没有额外的数据边界说明。");
}

function createProfessionalIndexCard(snapshot) {
  const index = snapshot.index || {};
  const marketData = snapshot.market_data || {};
  const period = marketData.period_performance || {};
  const latest = marketData.latest || {};
  const sentiment = snapshot.market_sentiment || {};
  const selectedMetrics = Array.isArray(snapshot.selected_metrics) ? snapshot.selected_metrics : [];
  const card = document.createElement("span");
  card.className = "professional-index-card";
  const title = document.createElement("strong");
  title.textContent = index.display_name || index.symbol || "指数";
  const meta = document.createElement("small");
  meta.textContent = [index.symbol, index.market, index.currency].filter(Boolean).join(" · ");
  card.append(title, meta);
  if (marketData.status === "complete") {
    if (selectedMetrics.includes("market_data")) {
      const latestLine = document.createElement("span");
      latestLine.className = "professional-index-line";
      latestLine.textContent = `最新收盘 ${latest.close ?? "—"}（${latest.date || "日期未知"}）`;
      card.append(latestLine);
    }
    if (selectedMetrics.includes("period_performance")) {
      const performanceLine = document.createElement("span");
      performanceLine.className = "professional-index-line";
      performanceLine.append(
        document.createTextNode(`区间 ${period.first_date || "—"} 至 ${period.last_date || "—"} · `),
        percentBadge(period.change_percent),
        document.createTextNode(` · ${period.trading_days ?? 0} 个交易日`),
      );
      card.append(performanceLine);
    }
  } else if (
    selectedMetrics.some((metric) => ["market_data", "period_performance", "market_sentiment"].includes(metric))
  ) {
    const unavailable = document.createElement("span");
    unavailable.className = "professional-index-line unavailable";
    unavailable.textContent = marketData.reason || "所选区间行情暂不可用。";
    card.append(unavailable);
  }
  if (sentiment.label) {
    const sentimentLine = document.createElement("span");
    sentimentLine.className = "professional-index-line";
    sentimentLine.append(document.createTextNode("区间情绪 "), sentimentBadge(sentiment));
    card.append(sentimentLine);
  }
  return card;
}

function professionalOptionLabel(group, key) {
  const professionalOptions = getProfessionalOptions();
  const options = Array.isArray(professionalOptions?.[group]) ? professionalOptions[group] : [];
  return options.find((option) => option.key === key)?.label || key;
}

export function renderMarketScan(reply) {
  const snapshot = reply.snapshot || {};
  const sentiment = snapshot.market_sentiment || {};
  const leaders = Array.isArray(snapshot.leading_industries) ? snapshot.leading_industries : [];
  const laggards = Array.isArray(snapshot.lagging_industries) ? snapshot.lagging_industries : [];
  const complete = snapshot.status === "complete";
  const sentimentTone = Number(sentiment.laggard_average_change_percent) >= 0
    ? "up"
    : Number(sentiment.leader_average_change_percent) > 0 ? "flat" : "down";
  renderLanguageContext(reply.language_context);
  clearEntityCandidates();
  setResultState(complete ? "板块扫描完成" : "远端数据失败", complete);
  elements.resultKicker.textContent = "确定性板块扫描 · 无二次模型等待";
  elements.resultTitle.textContent = "近期 A 股板块关注扫描";
  elements.resultScope.textContent = "行业涨跌排行样本 · 只读数据";
  elements.resultPeriod.textContent = reply.research_period?.start_date && reply.research_period?.end_date
    ? `输入时间语义：${reply.research_period.start_date} 至 ${reply.research_period.end_date}`
    : "以数据源当前或延迟行情为准";
  renderTags(elements.resultSources, complete && snapshot.source ? [snapshot.source] : [], "板块排行远端数据不可用");

  elements.summaryHeading.textContent = "市场情绪与结论";
  elements.summary.replaceChildren(document.createTextNode(`${reply.text || "未生成扫描说明"}\n市场情绪：`));
  elements.summary.append(sentimentBadge({ label: sentiment.label || "待数据", tone: sentiment.tone || sentimentTone }));
  if (complete) {
    elements.summary.append(document.createTextNode(
      `；领先样本平均涨跌 ${formatSignedPercent(sentiment.leader_average_change_percent)}，` +
      `落后样本平均涨跌 ${formatSignedPercent(sentiment.laggard_average_change_percent)}。`,
    ));
  }
  elements.summary.classList.toggle("placeholder", !complete);

  elements.observationsHeading.textContent = "板块涨跌幅";
  elements.observations.replaceChildren();
  if (!complete) {
    elements.observations.textContent = snapshot.reason || "板块排行远端数据源当前不可用。";
    elements.observations.classList.add("placeholder");
  } else {
    appendIndustryRows(elements.observations, "领涨样本", leaders);
    appendIndustryRows(elements.observations, "落后样本", laggards);
    elements.observations.classList.remove("placeholder");
  }
  setSection(
    elements.risksHeading,
    elements.risks,
    "数据边界与风险",
    complete
      ? "行业涨跌排名仅反映当前或延迟的横截面样本，不代表板块基本面、持续性或未来收益；关注板块仍需继续核验估值、盈利与拥挤度。"
      : "本次未取得可核验的板块排行，因此不生成关注建议，也不使用模型猜测补齐。",
    "请结合数据时效和研究边界理解结果。",
  );
  elements.nextStepsHeading.textContent = "下一步";
  renderNextSteps(
    complete
      ? ["对感兴趣的板块补充指数或证券代码，再查看近期行情、历史表现与风险。"]
      : ["前往参数配置页复测 Eastmoney；连接恢复后再次提交同一问题。"],
    "可稍后重试。",
  );
}

function appendIndustryRows(container, title, rows) {
  container.append(document.createTextNode(`${title}：`));
  if (!rows.length) {
    container.append(document.createTextNode("未返回样本。\n"));
    return;
  }
  rows.forEach((row, index) => {
    container.append(document.createTextNode(`${index ? "；" : ""}${row.name || row.code || "未知板块"} `));
    container.append(percentBadge(row.change_percent));
  });
  container.append(document.createTextNode("\n"));
}

function percentBadge(percent) {
  const value = Number(percent);
  const badge = document.createElement("span");
  badge.className = `price-change ${Number.isFinite(value) && value > 0 ? "up" : Number.isFinite(value) && value < 0 ? "down" : "flat"}`;
  badge.textContent = formatSignedPercent(percent);
  return badge;
}

function formatSignedPercent(percent) {
  const value = Number(percent);
  if (!Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value}%`;
}

export function renderResearchError(error) {
  setAnalysisDuration(null);
  clearEntityCandidates();
  setResultState("分析失败", false);
  elements.resultKicker.textContent = "研究请求未完成";
  elements.resultTitle.textContent = "本次研究没有生成结果";
  elements.resultScope.textContent = "服务端或数据源暂时不可用";
  elements.resultPeriod.textContent = "未生成有效分析区间";
  renderTags(elements.resultSources, error.requestId ? [`请求 ID：${error.requestId}`] : [], "未取得请求追踪 ID");
  setSection(elements.summaryHeading, elements.summary, "错误说明", error.message || "研究请求失败。", "研究请求失败。");
  setSection(elements.observationsHeading, elements.observations, "排查提示", "错误会保留在结果块中；可使用上方请求 ID 对照服务端日志。", "请检查服务状态。");
  setSection(elements.risksHeading, elements.risks, "结果边界", "本次没有形成可用研究结果，请勿将此状态视为行情平稳或无风险。", "本次未生成结果。");
  elements.nextStepsHeading.textContent = "下一步";
  renderNextSteps(["前往参数配置页检查数据源连通状态，或稍后重试。"], "请稍后重试。");
}

export function renderAgentResult(reply) {
  const researchPeriod = reply.research_period || null;
  const intent = reply.language_context?.intent || {};
  const toolCalls = Array.isArray(reply.tool_calls) ? reply.tool_calls : [];
  renderLanguageContext(reply.language_context);
  clearEntityCandidates();
  setResultState("已分析", true);
  elements.resultKicker.textContent = "RAG 增强 Agent 分析";
  elements.resultTitle.textContent = intent.label || "研究 Agent 的分析结果";
  elements.resultScope.textContent = `识别意图：${intent.label || "开放式研究"}`;
  elements.resultPeriod.textContent = "Agent 将根据输入与可用工具判断分析范围";
  renderTags(elements.resultSources, toolCalls.map((call) => `调用：${call.name}`).filter(Boolean), "本轮未调用数据工具");
  setRichSection(elements.summaryHeading, elements.summary, "Agent 分析", reply.text || "Agent 未返回可显示的分析。", "Agent 未返回可显示的分析。");
  setSection(elements.observationsHeading, elements.observations, "分析路径", toolCalls.length ? "Agent 已按需调用上方标注的只读工具。" : "本轮基于输入与检索上下文完成分析；如需实时或历史数据，可在同一文本框继续说明。", "本轮未调用工具。");
  setRichSection(elements.risksHeading, elements.risks, "研究边界", "风险提醒：黄色。结论应结合数据源、时效性与不确定性理解；页面不会执行交易或提供收益保证。", "请结合研究边界理解结果。");
  elements.nextStepsHeading.textContent = "继续分析";
  renderNextSteps(["可在同一文本框补充背景、代码、时间范围或追问下一步。"], "可继续补充问题。");
  if (researchPeriod?.start_date && researchPeriod?.end_date) {
    elements.resultPeriod.textContent = `分析区间：${researchPeriod.start_date} 至 ${researchPeriod.end_date}`;
  }
}

function renderEntityDisambiguation(reply) {
  const candidates = Array.isArray(reply.entity_candidates) ? reply.entity_candidates : [];
  renderLanguageContext(reply.language_context);
  setResultState("需要选择", false);
  elements.resultKicker.textContent = "证券匹配";
  elements.resultTitle.textContent = "请选择交易市场";
  elements.resultScope.textContent = "“汇丰银行”可对应不同上市证券";
  elements.resultPeriod.textContent = "选择后默认：最新可用日线 + 最近五个交易日";
  renderTags(elements.resultSources, [], "尚未调用行情工具");
  setSection(elements.summaryHeading, elements.summary, "先确认你要看的证券", reply.text, "请选择一个上市证券后继续。");
  setSection(
    elements.observationsHeading,
    elements.observations,
    "为什么需要选择",
    "港股普通股和美股 ADR 虽然对应同一发行人，但交易市场、币种、交易时段及证券形式不同。价格不能直接按数字比较。",
    "请先选择一个上市证券。",
  );
  setSection(
    elements.risksHeading,
    elements.risks,
    "基础内容范围",
    "选定后将先展示最新可用行情和最近一周表现；财报与监管披露尚未接入时会明确提示，不会编造结论。",
    "请先选择一个上市证券。",
  );
  elements.nextStepsHeading.textContent = "下一步";
  renderNextSteps(["点击下方卡片，使用同一个自然语言输入框继续。"], "请选择一个上市证券。");
  renderEntityCandidates(candidates);
}

export function renderIndexSnapshot(reply) {
  const snapshot = reply.snapshot || {};
  const index = snapshot.index || {};
  const market = snapshot.market_data || {};
  const latest = market.latest || {};
  const recentWeek = market.recent_week || {};
  const marketSentiment = snapshot.market_sentiment || {};
  const valuationStyle = snapshot.valuation_style || {};
  const constituentIndustries = snapshot.constituent_industries || {};
  const risks = Array.isArray(snapshot.risks) ? snapshot.risks : [];
  const limitations = Array.isArray(snapshot.limitations) ? snapshot.limitations : [];
  renderLanguageContext(reply.language_context);
  clearEntityCandidates();
  setResultState(market.status === "complete" ? "指数研究完成" : "指数研究完成（行情暂不可用）", true);
  elements.resultKicker.textContent = "指数单次全景研究";
  elements.resultTitle.textContent = index.display_name || "指数研究";
  elements.resultScope.textContent = [index.symbol, index.market, index.currency].filter(Boolean).join(" · ");
  elements.resultPeriod.textContent = snapshot.default_scope || "近期行情与最近五个交易日历史表现";
  renderTags(elements.resultSources, [market.source, "指数规则说明"].filter(Boolean), "行情数据暂不可用");
  setSection(elements.summaryHeading, elements.summary, "全景结论", reply.text, "未生成指数研究说明。");
  renderIndexMarketSection(
    elements.observationsHeading,
    elements.observations,
    market,
    latest,
    recentWeek,
    index.currency,
    marketSentiment,
  );
  setSection(
    elements.risksHeading,
    elements.risks,
    "估值/风格、成分行业与风险",
    [
      valuationStyle.style,
      valuationStyle.valuation,
      constituentIndustries.methodology,
      constituentIndustries.industry_note,
      ...risks,
    ].filter(Boolean).join("\n"),
    "未返回指数风格和风险说明。",
  );
  elements.nextStepsHeading.textContent = "数据边界";
  renderNextSteps(limitations, "当前没有额外的数据边界说明。");
}

function renderIndexMarketSection(heading, element, market, latest, recentWeek, currency, sentiment) {
  renderMarketSection(heading, element, market, latest, recentWeek, currency);
  heading.textContent = "近期行情与历史表现";
  element.append(document.createTextNode("\n指数表现情绪："));
  element.append(sentimentBadge(sentiment));
  if (sentiment.basis) element.append(document.createTextNode(`；${sentiment.basis}`));
}

export function renderBeginnerSnapshot(reply) {
  const snapshot = reply.snapshot || {};
  const security = snapshot.security || {};
  const market = snapshot.market_data || {};
  const recentWeek = market.recent_week || {};
  const latest = market.latest || {};
  const financialReports = snapshot.financial_reports || {};
  const limitations = Array.isArray(snapshot.limitations) ? snapshot.limitations : [];
  renderLanguageContext(reply.language_context);
  clearEntityCandidates();
  setResultState(market.status === "complete" ? "基础概览完成" : "行情暂不可用", market.status === "complete");
  elements.resultKicker.textContent = "证券研究概览";
  elements.resultTitle.textContent = security.display_name || "证券基础概览";
  elements.resultScope.textContent = [security.symbol, security.market, security.currency, security.instrument_type].filter(Boolean).join(" · ");
  elements.resultPeriod.textContent = snapshot.default_period?.label || "最新可用日线与最近五个交易日";
  renderTags(elements.resultSources, market.source ? [market.source] : [], "行情数据暂不可用");
  setSection(elements.summaryHeading, elements.summary, "基础结论", reply.text, "尚未生成基础概览。");
  renderMarketSection(elements.observationsHeading, elements.observations, market, latest, recentWeek, security.currency);
  setSection(
    elements.risksHeading,
    elements.risks,
    "财报与数据边界",
    [financialReports.message, ...limitations].filter(Boolean).join("\n"),
    "请结合数据来源与时效理解结果。",
  );
  elements.nextStepsHeading.textContent = "下一步";
  renderNextSteps(
    [
      "输入“比较汇丰港股 0005 与美股 ADR HSBC”可继续比较两地上市差异。",
      "输入更具体的问题、时间范围或研究目标，可进入 Agent 深入分析。",
    ],
    "可在同一个文本框继续提问。",
  );
}

export function renderCandidateSnapshots(reply) {
  const snapshots = Array.isArray(reply.snapshots) ? reply.snapshots : [];
  renderLanguageContext(reply.language_context);
  setResultState("已并列分析", true);
  elements.resultKicker.textContent = "证券匹配 · 并列基础概览";
  elements.resultTitle.textContent = "可能的上市证券";
  elements.resultScope.textContent = "每个候选均展示最新可用日线与最近五个交易日";
  elements.resultPeriod.textContent = "无需先选择；请按市场、币种与证券类型阅读";
  renderTags(elements.resultSources, snapshots.map((item) => item.market_data?.source).filter(Boolean), "行情数据暂不可用");
  setSection(elements.summaryHeading, elements.summary, "分析说明", reply.text, "未返回候选说明。");
  elements.observationsHeading.textContent = "候选行情概览";
  elements.observations.replaceChildren();
  for (const snapshot of snapshots) elements.observations.append(candidateMarketCard(snapshot));
  elements.risksHeading.textContent = "数据边界";
  elements.risks.textContent = "不同上市证券的币种、交易时段与证券形式不同；价格绝对值不能直接比较。财报未接入时会明确标注。";
  elements.nextStepsHeading.textContent = "继续分析";
  renderNextSteps(["可直接输入其中任一代码、市场或更具体的研究问题继续分析。"], "可在同一文本框继续提问。");
  clearEntityCandidates();
}

function candidateMarketCard(snapshot) {
  const security = snapshot.security || {};
  const market = snapshot.market_data || {};
  const recent = market.recent_week || {};
  const latest = market.latest || {};
  const card = document.createElement("article");
  card.className = "candidate-market-card";
  const title = document.createElement("h5");
  title.textContent = security.display_name || security.symbol || "候选证券";
  const meta = document.createElement("p");
  meta.textContent = [security.symbol, security.market, security.currency, security.instrument_type].filter(Boolean).join(" · ");
  const latestLine = document.createElement("p");
  latestLine.textContent = latest.date ? `最新日线 ${latest.date}：收盘 ${latest.close} ${security.currency || ""}；高/低 ${latest.high} / ${latest.low}` : (market.reason || "行情暂不可用");
  const changeLine = document.createElement("p");
  changeLine.textContent = recent.last_date ? `近 ${recent.trading_days} 个交易日：${recent.first_close} → ${recent.last_close}，涨跌 ` : "";
  if (recent.last_date) changeLine.append(changeBadge(recent.change, recent.change_percent));
  card.append(title, meta, latestLine, changeLine);
  return card;
}

function renderEntityCandidates(candidates) {
  elements.entityCandidates.replaceChildren();
  elements.entityCandidates.hidden = !candidates.length;
  for (const candidate of candidates) {
    const card = document.createElement("article");
    card.className = "entity-candidate-card";
    const title = document.createElement("h5");
    title.textContent = candidate.display_name || candidate.canonical_name || "上市证券";
    const meta = document.createElement("p");
    meta.className = "entity-candidate-meta";
    meta.textContent = [candidate.symbol, candidate.market, candidate.currency, candidate.instrument_type].filter(Boolean).join(" · ");
    const description = document.createElement("p");
    description.textContent = candidate.description || "";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button button-secondary entity-candidate-button";
    button.textContent = "查看基础概览";
    button.addEventListener("click", () => {
      elements.request.value = candidate.continuation_prompt || `${candidate.display_name || "该证券"} 基础概览`;
      runResearch();
    });
    card.append(title, meta, description, button);
    elements.entityCandidates.append(card);
  }
}

function clearEntityCandidates() {
  elements.entityCandidates.replaceChildren();
  elements.entityCandidates.hidden = true;
}

function formatBeginnerMarket(market, latest, recentWeek, currency) {
  if (market.status !== "complete") return market.reason || "行情数据暂不可用。";
  const latestLine = latest.date
    ? `最新可用日线（${latest.date}）：收盘 ${latest.close ?? "—"} ${currency || ""}；当日高/低 ${latest.high ?? "—"} / ${latest.low ?? "—"}`
    : "未返回最新可用日线。";
  const weekLine = recentWeek.last_date
    ? `最近 ${recentWeek.trading_days ?? "—"} 个交易日（${recentWeek.first_date} 至 ${recentWeek.last_date}）：收盘 ${recentWeek.first_close ?? "—"} → ${recentWeek.last_close ?? "—"}；区间高/低 ${recentWeek.highest_high ?? "—"} / ${recentWeek.lowest_low ?? "—"}`
    : "未返回最近一周汇总。";
  return `${latestLine}\n${weekLine}\n数据时效：日线 / 可能延迟，并非实时成交报价。`;
}

function renderMarketSection(heading, element, market, latest, recentWeek, currency) {
  heading.textContent = "行情（默认最近一周）";
  element.replaceChildren();
  if (market.status !== "complete") { element.textContent = market.reason || "行情数据暂不可用。"; return; }
  element.append(document.createTextNode(`最新可用日线（${latest.date}）：收盘 ${latest.close ?? "—"} ${currency || ""}；当日高/低 ${latest.high ?? "—"} / ${latest.low ?? "—"}\n`));
  element.append(document.createTextNode(`最近 ${recentWeek.trading_days ?? "—"} 个交易日（${recentWeek.first_date} 至 ${recentWeek.last_date}）：收盘 ${recentWeek.first_close ?? "—"} → ${recentWeek.last_close ?? "—"}，涨跌 `));
  element.append(changeBadge(recentWeek.change, recentWeek.change_percent));
  element.append(document.createTextNode("；数据时效：日线 / 可能延迟，并非实时成交报价。"));
}

function changeBadge(change, percent) {
  const value = Number(change);
  const badge = document.createElement("span");
  badge.className = `price-change ${Number.isFinite(value) && value > 0 ? "up" : Number.isFinite(value) && value < 0 ? "down" : "flat"}`;
  const sign = Number.isFinite(value) && value > 0 ? "+" : "";
  badge.textContent = `${sign}${change ?? "—"}（${sign}${percent ?? "—"}%）`;
  return badge;
}

function sentimentBadge(sentiment) {
  const badge = document.createElement("span");
  const tone = ["up", "down", "flat"].includes(sentiment?.tone) ? sentiment.tone : "flat";
  badge.className = `price-change ${tone}`;
  badge.textContent = sentiment?.label || "待行情数据";
  return badge;
}

function renderResult(result) {
  setAnalysisDuration(result.analysis_duration_ms);
  renderLanguageContext(result.language_context);
  const intent = result.intent || {};
  if (result.request_status === "needs_clarification") {
    renderClarification(result, intent);
    return;
  }
  const scope = result.scope || {};
  const evidence = Array.isArray(result.evidence) ? result.evidence : [];
  const risks = Array.isArray(result.risk_flags) ? result.risk_flags : [];
  const limitations = Array.isArray(result.limitations) ? result.limitations : [];
  setResultState(result.report_status === "complete" ? "完成" : "证据不足", result.report_status === "complete");
  elements.resultKicker.textContent = `${intent.scenario || "研究"} · ${intent.market || "自动识别"}`;
  elements.resultTitle.textContent = `${scope.symbol || intent.symbol || "研究"} 的研究结果`;
  elements.resultScope.textContent = `标的：${scope.symbol || intent.symbol || "未识别"}`;
  elements.resultPeriod.textContent = dateRange(intent.start_date, intent.end_date);
  renderTags(elements.resultSources, [...new Set(evidence.map((item) => item.source).filter(Boolean))], "报告未标注数据源");
  setSection(elements.summaryHeading, elements.summary, "研究摘要", result.model_narrative || result.summary || "未生成可复核摘要。", "未生成可复核摘要。");
  setSection(elements.observationsHeading, elements.observations, "市场观察", (result.market_observations || []).map(formatObservation).filter(Boolean).join("\n"), "未返回市场观察。");
  setSection(elements.risksHeading, elements.risks, "风险与限制", [...risks.map((risk) => risk.trigger || risk.risk_id), ...limitations].filter(Boolean).join("\n"), "未报告额外限制。");
  renderNextSteps(result.next_research_actions || [], "暂无额外核验项。");
  elements.nextStepsHeading.textContent = "下一步核验";
}

function renderClarification(result, intent) {
  setResultState("需要补充", false);
  elements.resultKicker.textContent = "自然语言意图澄清";
  elements.resultTitle.textContent = "请补充研究条件";
  elements.resultScope.textContent = `已识别标的：${intent.symbol || "尚未识别"}`;
  elements.resultPeriod.textContent = dateRange(intent.start_date, intent.end_date);
  renderTags(elements.resultSources, [], "尚未调用数据源");
  setSection(elements.summaryHeading, elements.summary, "系统说明", result.message || "请补充必要信息后再次提交。", "请补充必要信息后再次提交。");
  const questions = (result.clarifications || []).map((item) => {
    const options = Array.isArray(item.options) && item.options.length ? `（可选：${item.options.join(" / ")}）` : "";
    return `• ${item.question}${options}`;
  }).join("\n");
  setSection(elements.observationsHeading, elements.observations, "需要补充", questions, "没有额外澄清项。");
  setSection(elements.risksHeading, elements.risks, "已识别条件", describeIntent(intent), "尚未识别研究条件。");
  elements.nextStepsHeading.textContent = "下一步";
  renderNextSteps(["在同一个文本框补充上述信息，然后再次提交。"], "请补充信息后再次提交。");
}

function renderLanguageContext(context) {
  const references = Array.isArray(context?.references) ? context.references : [];
  elements.chainStatus.textContent = context?.framework === "lcel_rag"
    ? `已识别为“${context.intent?.label || "开放式研究"}”，并采用与本次问题匹配的解读深度，通过 LCEL 检索 ${context.document_count} 条应用内参考以增强分析。`
    : "未获得语言增强上下文。";
  renderTags(elements.chainReferences, references.map((item) => item.title).filter(Boolean), "未检索到额外参考");
}

export function setAnalysisDuration(value) {
  if (value === null || value === undefined || value === "") {
    elements.resultAnalysisDuration.hidden = true;
    elements.resultAnalysisDuration.textContent = "";
    return;
  }
  const milliseconds = Number(value);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) {
    elements.resultAnalysisDuration.hidden = true;
    elements.resultAnalysisDuration.textContent = "";
    return;
  }
  const formatted = milliseconds < 1_000
    ? `${Math.round(milliseconds)} ms`
    : `${(milliseconds / 1_000).toFixed(milliseconds < 10_000 ? 1 : 0)} 秒`;
  elements.resultAnalysisDuration.textContent = `分析耗时：${formatted}`;
  elements.resultAnalysisDuration.hidden = false;
}

function setSection(heading, element, title, value, fallback) {
  heading.textContent = title;
  element.textContent = value || fallback;
  element.classList.toggle("placeholder", !value);
}

function setRichSection(heading, element, title, value, fallback) {
  heading.textContent = title;
  element.replaceChildren();
  appendRichText(element, value || fallback);
  element.classList.toggle("placeholder", !value);
}

function appendRichText(element, value) {
  const text = String(value || "");
  const pattern = /(风险提醒[：:]?\s*(?:红色|黄色)|[+-]\s*\d+(?:\.\d+)?%)/g;
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    element.append(document.createTextNode(text.slice(offset, match.index)));
    const token = match[0];
    const span = document.createElement("span");
    if (token.includes("红色")) span.className = "risk-flag risk-red";
    else if (token.includes("黄色")) span.className = "risk-flag risk-yellow";
    else span.className = `price-change ${token.trim().startsWith("+") ? "up" : "down"}`;
    span.textContent = token;
    element.append(span);
    offset = (match.index || 0) + token.length;
  }
  element.append(document.createTextNode(text.slice(offset)));
}

function renderNextSteps(items, fallback) {
  elements.nextSteps.replaceChildren();
  const values = Array.isArray(items) && items.length ? items : [fallback];
  for (const item of values) {
    const row = document.createElement("li");
    row.textContent = item;
    elements.nextSteps.append(row);
  }
  elements.nextSteps.classList.toggle("placeholder", !(Array.isArray(items) && items.length));
}

function renderTags(container, values, fallback) {
  container.replaceChildren();
  for (const value of (values.length ? values : [fallback])) {
    const tag = document.createElement("span");
    tag.textContent = value;
    container.append(tag);
  }
}

function setResultState(label, complete) {
  elements.resultState.textContent = label;
  elements.resultState.className = `report-state${complete ? " complete" : ""}`;
}

function formatObservation(item) {
  if (!item || typeof item !== "object") return "";
  const values = [item.source, item.date, item.timestamp, item.summary, item.observation, item.research_implication]
    .filter((value) => typeof value === "string" && value.trim());
  return values.join(" · ");
}

function describeIntent(intent) {
  const values = [
    intent.scenario && `场景：${intent.scenario}`,
    intent.market && `市场：${intent.market}`,
    intent.symbol && `标的：${intent.symbol}`,
    dateRange(intent.start_date, intent.end_date),
  ].filter(Boolean);
  return values.join("\n");
}

function dateRange(startDate, endDate) {
  if (startDate && endDate) return `区间：${startDate} 至 ${endDate}`;
  if (startDate) return `起始：${startDate}`;
  if (endDate) return `截至：${endDate}`;
  return "未识别日期区间";
}

export async function copyMarkdown() {
  const text = resultMarkdown();
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  notify("研究结果 Markdown 已复制到剪贴板");
}

function resultMarkdown() {
  if (!lastResult) return "# Finance Agent\n\n尚未提交研究请求。";
  if (lastResult.mode === "error") {
    return [
      "# 研究请求失败",
      "",
      lastResult.message || "研究请求未完成。",
      lastResult.request_id ? `\n> 请求 ID：${lastResult.request_id}` : "",
      "",
      "本次没有形成可用研究结果。",
    ].filter(Boolean).join("\n");
  }
  if (lastResult.mode === "agent") {
    const intent = lastResult.language_context?.intent || {};
    return [
      `# ${intent.label || "RAG 增强 Agent 分析"}`,
      "",
      lastResult.text || "Agent 未返回可显示的分析。",
      "",
      "---",
      "仅用于个人研究与内容整理，不构成投资建议或交易指令。",
    ].join("\n");
  }
  if (["entity_disambiguation", "beginner_snapshot", "index_snapshot", "market_scan"].includes(lastResult.mode)) {
    return [
      `# ${elements.resultTitle.textContent || "Finance Agent"}`,
      "",
      elements.summary.textContent || "未生成摘要。",
      "",
      "## 行情或选择说明",
      elements.observations.textContent || "未生成说明。",
      "",
      "## 数据边界",
      elements.risks.textContent || "请结合数据来源与时效理解结果。",
      "",
      "---",
      "仅用于个人研究与内容整理，不构成投资建议或交易指令。",
    ].join("\n");
  }
  const intent = lastResult.intent || {};
  const lines = [
    `# ${lastResult.request_status === "needs_clarification" ? "研究条件澄清" : `${intent.symbol || "研究"} 的研究结果`}`,
    "",
    `> 场景：${intent.scenario || "未识别"}`,
    `> ${dateRange(intent.start_date, intent.end_date)}`,
    "",
    "## 研究说明",
    lastResult.message || lastResult.model_narrative || lastResult.summary || "未生成摘要。",
  ];
  if (lastResult.request_status === "needs_clarification") {
    lines.push("", "## 需要补充", ...(lastResult.clarifications || []).map((item) => `- ${item.question}`));
  } else {
    lines.push("", "## 风险与限制", ...(lastResult.limitations || []).map((item) => `- ${item}`));
  }
  lines.push("", "---", "仅用于个人研究与内容整理，不构成投资建议或交易指令。");
  return lines.join("\n");
}
