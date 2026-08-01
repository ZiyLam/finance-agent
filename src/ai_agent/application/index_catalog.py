"""Reviewed index metadata and professional-form catalog options."""

from __future__ import annotations

from dataclasses import dataclass

from .entity_resolution import SecurityCandidate


@dataclass(frozen=True, slots=True)
class IndexDefinition:
    """Stable reference metadata for an index that the Web entry can recognise."""

    key: str
    display_name: str
    display_symbol: str
    yahoo_symbol: str
    tickflow_symbol: str | None
    aliases: tuple[str, ...]
    style_profile: str
    methodology_note: str
    industry_note: str
    risk_notes: tuple[str, ...]
    market_key: str = "a_share"
    market_name: str = "中国 A 股宽基指数"
    currency: str = "CNY"
    zhitu_index_symbol: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "symbol": self.display_symbol,
            "yahoo_symbol": self.yahoo_symbol,
            "market_key": self.market_key,
            "market": self.market_name,
            "currency": self.currency,
            "style_profile": self.style_profile,
        }

    def selector_dict(self) -> dict[str, str]:
        """Return only non-sensitive metadata required by the professional form."""

        return {
            "key": self.key,
            "display_name": self.display_name,
            "symbol": self.display_symbol,
            "market": self.market_key,
        }

    def as_security(self) -> SecurityCandidate:
        """Reuse the bounded daily-price reader without giving an index stock semantics."""

        return SecurityCandidate(
            key=self.key,
            canonical_name=self.display_name,
            display_name=self.display_name,
            yahoo_symbol=self.yahoo_symbol,
            eodhd_symbol=None,
            display_symbol=self.display_symbol,
            market=self.market_name,
            currency=self.currency,
            instrument_type="指数",
            description=self.methodology_note,
            continuation_prompt=f"查看 {self.display_name} 的指数研究",
            tickflow_symbol=self.tickflow_symbol,
            zhitu_index_symbol=(
                self.zhitu_index_symbol
                if self.zhitu_index_symbol is not None
                else self.tickflow_symbol if self.market_key == "a_share" else None
            ),
        )


CSI_500 = IndexDefinition(
    key="csi_500",
    display_name="中证 500",
    display_symbol="000905",
    yahoo_symbol="000905.SS",
    tickflow_symbol="000905.SH",
    aliases=("中证500", "中证 500", "000905", "csi500", "csi 500"),
    style_profile="中小市值宽基；相较大盘蓝筹，对成长、制造业与风险偏好变化通常更敏感。",
    methodology_note=(
        "中证 500 从沪深市场中选取流动性较好、具有代表性的中小市值证券；"
        "实际样本、权重和定期调整以中证指数公司最新发布为准。"
    ),
    industry_note=(
        "覆盖多个 A 股行业。当前未接入官方成分股及行业权重数据，"
        "因此不展示可能过期的行业占比或前十大成分股。"
    ),
    risk_notes=(
        "中小市值指数的波动与流动性风险通常高于大盘宽基，市场风险偏好变化可能放大回撤。",
        "指数点位是收盘后或延迟数据，不代表实时可成交价格。",
        "静态风格说明不是当前估值结论；市盈率、市净率和盈利预期需连接官方或授权估值数据后复核。",
    ),
)


CSI_300 = IndexDefinition(
    key="csi_300",
    display_name="沪深 300",
    display_symbol="000300",
    yahoo_symbol="000300.SS",
    tickflow_symbol="000300.SH",
    aliases=("沪深300", "沪深 300", "000300", "csi300", "csi 300"),
    style_profile="大中市值核心宽基，较集中反映 A 股龙头公司的市场表现。",
    methodology_note="沪深 300 的实际样本、权重和定期调整以中证指数公司最新发布为准。",
    industry_note="当前未接入官方成分股及行业权重数据，不展示可能过期的行业占比或前十大成分股。",
    risk_notes=(
        "行业和龙头权重可能导致指数表现与全市场平均表现存在明显差异。",
        "指数点位是收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断市盈率、市净率或估值分位。",
    ),
)

CSI_1000 = IndexDefinition(
    key="csi_1000",
    display_name="中证 1000",
    display_symbol="000852",
    yahoo_symbol="000852.SS",
    tickflow_symbol="000852.SH",
    aliases=("中证1000", "中证 1000", "000852", "csi1000", "csi 1000"),
    style_profile="小市值宽基；对流动性、成长预期与风险偏好变化通常更敏感。",
    methodology_note="中证 1000 的实际样本、权重和定期调整以中证指数公司最新发布为准。",
    industry_note="当前未接入官方成分股及行业权重数据，不展示可能过期的行业占比或前十大成分股。",
    risk_notes=(
        "小市值风格的波动和流动性风险可能较高。",
        "指数点位是收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断市盈率、市净率或估值分位。",
    ),
)

SSE_50 = IndexDefinition(
    key="sse_50",
    display_name="上证 50",
    display_symbol="000016",
    yahoo_symbol="000016.SS",
    tickflow_symbol="000016.SH",
    aliases=("上证50", "上证 50", "000016", "sse50", "sse 50"),
    style_profile="上海市场大市值蓝筹指数，个别行业权重可能较集中。",
    methodology_note="上证 50 的实际样本、权重和定期调整以指数编制方最新发布为准。",
    industry_note="当前未接入官方成分股及行业权重数据，不展示可能过期的行业占比或前十大成分股。",
    risk_notes=(
        "行业集中度和大市值权重会影响指数与其他宽基的相对表现。",
        "指数点位是收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断市盈率、市净率或估值分位。",
    ),
)

CHINEXT = IndexDefinition(
    key="chinext",
    display_name="创业板指",
    display_symbol="399006",
    yahoo_symbol="399006.SZ",
    tickflow_symbol="399006.SZ",
    aliases=("创业板指", "创业板指数", "399006", "chinext"),
    style_profile="成长与创新风格较突出，盈利预期和估值变化的敏感度通常较高。",
    methodology_note="创业板指的实际样本、权重和定期调整以指数编制方最新发布为准。",
    industry_note="当前未接入官方成分股及行业权重数据，不展示可能过期的行业占比或前十大成分股。",
    risk_notes=(
        "成长风格指数对估值变化和业绩预期调整可能更敏感。",
        "指数点位是收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断市盈率、市净率或估值分位。",
    ),
)


SSE_COMPOSITE = IndexDefinition(
    key="sse_composite",
    display_name="上证指数",
    display_symbol="000001",
    yahoo_symbol="000001.SS",
    tickflow_symbol="000001.SH",
    aliases=("上证指数", "上证综指", "沪指", "000001", "sse composite", "shanghai composite"),
    style_profile="上海证券市场综合指数，覆盖沪市不同规模与行业的上市公司。",
    methodology_note="上证指数样本与编制规则以上海证券交易所最新公布为准。",
    industry_note="当前未接入交易所实时行业权重，不展示可能过期的行业占比。",
    risk_notes=(
        "综合指数受大市值权重、行业结构和沪市样本范围影响，不等同于全部 A 股平均表现。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断估值水平或分位。",
    ),
)

SZSE_COMPONENT = IndexDefinition(
    key="szse_component",
    display_name="深证成指",
    display_symbol="399001",
    yahoo_symbol="399001.SZ",
    tickflow_symbol="399001.SZ",
    aliases=("深证成指", "深成指", "399001", "szse component", "shenzhen component"),
    style_profile="深圳市场代表性成分指数，成长、制造与消费等行业影响较为显著。",
    methodology_note="深证成指样本与编制规则以深圳证券交易所最新公布为准。",
    industry_note="当前未接入交易所实时成分与行业权重，不展示可能过期的占比。",
    risk_notes=(
        "行业结构和成长风格暴露可能使其与上证指数、大盘蓝筹指数表现不同。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断估值水平或分位。",
    ),
)


HANG_SENG = IndexDefinition(
    key="hang_seng",
    display_name="恒生指数",
    display_symbol="HSI",
    yahoo_symbol="^HSI",
    tickflow_symbol=None,
    aliases=("恒生指数", "恒指", "hsi", "hang seng"),
    style_profile="香港大盘蓝筹指数，金融、互联网与地产等行业权重变化会显著影响指数表现。",
    methodology_note="恒生指数成分与权重以恒生指数有限公司最新公布为准。",
    industry_note="当前未接入恒生指数官方实时成分权重，不展示可能过期的行业占比。",
    risk_notes=(
        "港股交易制度、汇率、跨境资金与全球风险偏好会共同影响指数波动。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断市盈率、市净率或估值分位。",
    ),
    market_key="hong_kong",
    market_name="香港股票市场指数",
    currency="HKD",
)

HANG_SENG_TECH = IndexDefinition(
    key="hang_seng_tech",
    display_name="恒生科技指数",
    display_symbol="HSTECH",
    yahoo_symbol="^HSTECH",
    tickflow_symbol=None,
    aliases=("恒生科技指数", "恒生科技", "恒科", "hstech", "hang seng tech"),
    style_profile="香港上市科技龙头指数，对成长预期、流动性和监管环境变化通常更敏感。",
    methodology_note="恒生科技指数成分与权重以恒生指数有限公司最新公布为准。",
    industry_note="当前未接入官方实时成分权重，不展示可能过期的公司或行业占比。",
    risk_notes=(
        "科技成长风格可能放大估值、盈利预期和流动性变化带来的波动。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断估值水平或盈利预期。",
    ),
    market_key="hong_kong",
    market_name="香港股票市场指数",
    currency="HKD",
)

SP_500 = IndexDefinition(
    key="sp_500",
    display_name="标普 500",
    display_symbol="SPX",
    yahoo_symbol="^GSPC",
    tickflow_symbol=None,
    aliases=("标普500", "标普 500", "sp500", "s&p 500", "spx"),
    style_profile="美国大盘宽基指数，覆盖多个行业并较集中反映大型上市公司的表现。",
    methodology_note="标普 500 成分与权重以 S&P Dow Jones Indices 最新公布为准。",
    industry_note="当前未接入官方实时成分与行业权重，不展示可能过期的占比。",
    risk_notes=(
        "美元利率、盈利预期、行业集中度与全球风险偏好会影响指数表现。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断当前估值分位。",
    ),
    market_key="us",
    market_name="美国股票市场指数",
    currency="USD",
)

NASDAQ_100 = IndexDefinition(
    key="nasdaq_100",
    display_name="纳斯达克 100",
    display_symbol="NDX",
    yahoo_symbol="^NDX",
    tickflow_symbol=None,
    aliases=("纳斯达克100", "纳斯达克 100", "纳指100", "nasdaq100", "nasdaq 100", "ndx"),
    style_profile="美国大型非金融成长指数，科技与通信服务权重较高，风格集中度明显。",
    methodology_note="纳斯达克 100 成分与权重以 Nasdaq 最新公布为准。",
    industry_note="当前未接入官方实时成分与行业权重，不展示可能过期的公司占比。",
    risk_notes=(
        "科技成长集中度、利率变化和大型成分股业绩预期可能放大指数波动。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
        "未接入当前估值数据，不推断当前估值分位。",
    ),
    market_key="us",
    market_name="美国股票市场指数",
    currency="USD",
)


NASDAQ_COMPOSITE = IndexDefinition(
    key="nasdaq_composite",
    display_name="纳斯达克综合指数（纳指）",
    display_symbol="IXIC",
    yahoo_symbol="^IXIC",
    tickflow_symbol=None,
    aliases=("纳斯达克综合指数", "纳斯达克综指", "纳指", "nasdaq composite", "ixic"),
    style_profile="覆盖纳斯达克市场多数上市证券的综合指数，科技与成长风格影响较明显。",
    methodology_note="纳斯达克综合指数范围与计算规则以 Nasdaq 最新公布为准。",
    industry_note="当前未接入官方实时成分与行业权重，不展示可能过期的公司或行业占比。",
    risk_notes=(
        "科技成长权重、利率与盈利预期变化可能显著影响指数波动。",
        "综合指数与纳斯达克 100 的样本范围不同，不应混为同一指数。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
    ),
    market_key="us",
    market_name="美国股票市场指数",
    currency="USD",
)

DOW_JONES = IndexDefinition(
    key="dow_jones",
    display_name="道琼斯工业平均指数",
    display_symbol="DJI",
    yahoo_symbol="^DJI",
    tickflow_symbol=None,
    aliases=("道琼斯工业平均指数", "道琼斯指数", "道指", "dow jones", "djia", "dji"),
    style_profile="美国大型蓝筹股价格加权指数，样本数量较少，单只高价成分股影响可能较明显。",
    methodology_note="道琼斯工业平均指数成分与计算规则以 S&P Dow Jones Indices 最新公布为准。",
    industry_note="当前未接入官方实时成分与行业权重，不展示可能过期的占比。",
    risk_notes=(
        "价格加权方法与较少的成分数量使其不能代表全部美国股票。",
        "美元利率、盈利预期和全球风险偏好会影响指数表现。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
    ),
    market_key="us",
    market_name="美国股票市场指数",
    currency="USD",
)

RUSSELL_2000 = IndexDefinition(
    key="russell_2000",
    display_name="罗素 2000",
    display_symbol="RUT",
    yahoo_symbol="^RUT",
    tickflow_symbol=None,
    aliases=("罗素2000", "罗素 2000", "russell2000", "russell 2000", "rut"),
    style_profile="美国小盘股代表指数，对融资条件、美国本土经济和风险偏好变化通常更敏感。",
    methodology_note="罗素 2000 样本与编制规则以 FTSE Russell 最新公布为准。",
    industry_note="当前未接入官方实时成分与行业权重，不展示可能过期的占比。",
    risk_notes=(
        "小盘股的盈利稳定性、流动性和融资风险通常高于大型公司。",
        "美元利率与美国国内经济预期可能放大指数波动。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
    ),
    market_key="us",
    market_name="美国股票市场指数",
    currency="USD",
)

NIKKEI_225 = IndexDefinition(
    key="nikkei_225",
    display_name="日经 225",
    display_symbol="N225",
    yahoo_symbol="^N225",
    tickflow_symbol=None,
    aliases=("日经225", "日经 225", "日经指数", "nikkei225", "nikkei 225", "n225"),
    style_profile="日本大型企业价格加权指数，出口行业、日元汇率与高价成分股影响较明显。",
    methodology_note="日经 225 成分与计算规则以 Nikkei Inc. 最新公布为准。",
    industry_note="当前未接入官方实时成分与行业权重，不展示可能过期的占比。",
    risk_notes=(
        "价格加权方法、日元汇率和日本货币政策可能显著影响指数表现。",
        "海外投资者还需考虑本币与日元之间的汇率风险。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
    ),
    market_key="japan",
    market_name="日本股票市场指数",
    currency="JPY",
)

FTSE_100 = IndexDefinition(
    key="ftse_100",
    display_name="富时 100",
    display_symbol="FTSE",
    yahoo_symbol="^FTSE",
    tickflow_symbol=None,
    aliases=("富时100", "富时 100", "英国富时", "ftse100", "ftse 100", "ukx"),
    style_profile="英国大型蓝筹指数，国际化公司、金融、能源与必需消费品影响较明显。",
    methodology_note="富时 100 成分与编制规则以 FTSE Russell 最新公布为准。",
    industry_note="当前未接入官方实时成分与行业权重，不展示可能过期的占比。",
    risk_notes=(
        "英镑汇率、能源与金融行业权重会影响指数表现。",
        "海外投资者需考虑本币与英镑之间的汇率风险。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
    ),
    market_key="europe",
    market_name="欧洲股票市场指数",
    currency="GBP",
)

DAX = IndexDefinition(
    key="dax",
    display_name="德国 DAX",
    display_symbol="DAX",
    yahoo_symbol="^GDAXI",
    tickflow_symbol=None,
    aliases=("德国dax", "德国 dax", "德国指数", "dax40", "dax 40", "gdaxi"),
    style_profile="德国大型蓝筹指数，工业、汽车、化工与金融等行业影响较明显。",
    methodology_note="DAX 成分与编制规则以 STOXX / Deutsche Börse 最新公布为准。",
    industry_note="当前未接入官方实时成分与行业权重，不展示可能过期的占比。",
    risk_notes=(
        "欧洲经济周期、能源价格、欧元汇率和出口需求可能影响指数表现。",
        "海外投资者需考虑本币与欧元之间的汇率风险。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
    ),
    market_key="europe",
    market_name="欧洲股票市场指数",
    currency="EUR",
)

CAC_40 = IndexDefinition(
    key="cac_40",
    display_name="法国 CAC 40",
    display_symbol="CAC40",
    yahoo_symbol="^FCHI",
    tickflow_symbol=None,
    aliases=("法国cac40", "法国 cac 40", "cac40", "cac 40", "fchi"),
    style_profile="法国大型蓝筹指数，奢侈品、工业、金融与消费行业影响较明显。",
    methodology_note="CAC 40 成分与编制规则以 Euronext 最新公布为准。",
    industry_note="当前未接入官方实时成分与行业权重，不展示可能过期的占比。",
    risk_notes=(
        "欧洲经济、全球消费需求、欧元汇率与行业集中度会影响指数表现。",
        "海外投资者需考虑本币与欧元之间的汇率风险。",
        "指数日线可能为收盘后或延迟数据，不代表实时可成交价格。",
    ),
    market_key="europe",
    market_name="欧洲股票市场指数",
    currency="EUR",
)


INDEXES_BY_KEY: dict[str, IndexDefinition] = {
    "sse_composite": SSE_COMPOSITE,
    "csi_300": CSI_300,
    "sse_50": SSE_50,
    "szse_component": SZSE_COMPONENT,
    "chinext": CHINEXT,
    "csi_500": CSI_500,
    "csi_1000": CSI_1000,
    "hang_seng": HANG_SENG,
    "hang_seng_tech": HANG_SENG_TECH,
    "sp_500": SP_500,
    "nasdaq_composite": NASDAQ_COMPOSITE,
    "nasdaq_100": NASDAQ_100,
    "dow_jones": DOW_JONES,
    "russell_2000": RUSSELL_2000,
    "nikkei_225": NIKKEI_225,
    "ftse_100": FTSE_100,
    "dax": DAX,
    "cac_40": CAC_40,
}
if any(key != definition.key for key, definition in INDEXES_BY_KEY.items()):
    raise RuntimeError("Index catalog keys must match their definitions")

INDEX_CATALOG: tuple[IndexDefinition, ...] = tuple(INDEXES_BY_KEY.values())

PROFESSIONAL_MARKETS: tuple[dict[str, str], ...] = (
    {"key": "a_share", "label": "A 股"},
    {"key": "hong_kong", "label": "港股"},
    {"key": "us", "label": "美股"},
    {"key": "japan", "label": "日本"},
    {"key": "europe", "label": "欧洲"},
)
PROFESSIONAL_METRICS: tuple[dict[str, str], ...] = (
    {"key": "market_data", "label": "最新行情"},
    {"key": "period_performance", "label": "区间表现"},
    {"key": "market_sentiment", "label": "市场情绪"},
    {"key": "valuation_style", "label": "估值 / 风格"},
    {"key": "constituent_industries", "label": "成分与行业"},
    {"key": "risks", "label": "风险提示"},
)
PROFESSIONAL_METRIC_KEYS = frozenset(option["key"] for option in PROFESSIONAL_METRICS)


def professional_research_catalog() -> dict[str, object]:
    """Return form options from the reviewed server-side index catalog."""

    return {
        "maximum_indices": 6,
        "maximum_trading_days_per_index": 120,
        "markets": [dict(option) for option in PROFESSIONAL_MARKETS],
        "indices": [definition.selector_dict() for definition in INDEX_CATALOG],
        "metrics": [dict(option) for option in PROFESSIONAL_METRICS],
    }


def get_index(key: str) -> IndexDefinition | None:
    """Resolve a professional-form index key without accepting arbitrary symbols."""

    return INDEXES_BY_KEY.get(key.strip().casefold())
