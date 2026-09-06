# Jian — 开发规范与上下文记忆 (文档 v5.2)

> **本文档是"给未来的你看"的唯一权威记忆**。功能开发前先读：
> §3 产品全景 → §4 代码地图 → §5 数据契约/铁律 → §6/§7 完成度清单。
> 本文档于 v5.0 全面重排：完成项按模块归类核对，未完成项按**优先级 + 依赖**重新分类。
> v5.1：记录「市场回测·阶段A」落地（多函数段共享池 + 条件组 Gate）。
> v5.2：记录「市场回测·阶段B」落地（引擎风控离场器 + exit_reason 全链路）。
> 状态图例：`[x]` 完成 · `[~]` 部分/半成品 · `[ ]` 未开始/占位。

---

## 1. 项目定位

- **项目名:** Jian（专业量化交易复盘与分析系统），桌面端（PyQt6）。
- **产品形态:** 期货交割单驱动的**复盘主链路**（交易流水/深度复盘/资金表现）
  + **股票行情浏览与市场回测**（扬长避短，见 §5.3-C）。
- **铁三角理念:** ① 代码高内聚低耦合（SRP，严禁大而全的模块）；
  ② 程序本体与用户数据**物理隔离**（数据主权）；③ 操作**绝对幂等/防呆/防手残**。

## 2. 技术栈与关键设施（与代码现状对齐）

| 层 | 选型 | 落点 |
|---|---|---|
| UI | PyQt6 | `ui/`（全部组件继承自 PyQt6，非 PySide6） |
| 图表 | pyqtgraph + 自研 `CandlestickItem` | `ui/widgets/custom_widgets.py`；全局强制抗锯齿（`main.py`） |
| 行情源 | AkShare：A股日线 **新浪主源 + 东财兜底**；期货 `futures_main_sina` 主连 | `data/akshare_feed.py` |
| 指标 | 纯 Pandas 向量化 `TAEngine`（MA/BOLL/MACD） | `core/indicators.py` |
| 公式 | 通达信方言 DSL：词法/语法/运行时/整段程序 | `core/formula/*` |
| 业务库 | SQLite，`INSERT OR IGNORE` 幂等 + MD5 确定性主键 | `core/database.py` |
| 时序湖 | pyarrow Parquet 分区数据湖（DataLake） | `data/market_db.py` |
| 偏好/策略库 | JSON 原子写（tmp + os.replace） | `core/preferences.py`、`data/strategy_store.py` |
| 并发 | 耗时 I/O 一律 QThread Worker | 导入/拉数/回测/版本检测四处 |

**用户数据目录（物理隔离，勿在仓库存业务数据）:** `~/.jian_data/`
（`jian_trades.db`、`preferences.json`、`backtest_strategies.json`、`data_lake/`、`screenshots/`）。

## 3. 产品全景：5 页导航 + 弹窗（已实现 UI 总览）

导航路由极简（`ui/main_window.py` 仅做组件装配与事件分发，不含业务逻辑）：

| 导航页 | 类（文件） | 完成度 | 能力摘要 |
|---|---|---|---|
| 📊 资金与表现 | `DashboardView` | [x] | 18 项净额口径 KPI 网格 + 净值曲线 + 单笔净额分布直方图 |
| 📝 交易流水 | `RecordsView` | [x] | 11 列明细表、五维过滤器、孤儿黄条、CSV 全量导出、时间精度切换 |
| 💡 深度复盘 | `ReviewView` | [x] | 月/年双模态、月历热力图、累计盈亏/交易回放/资金K线/持仓时长四页签、孤儿手工补录、截图画廊 |
| 📈 市场行情 | `MarketView` | [x] | 代码查询、数据湖优先+联网兜底、K线+MA/BOLL+量+MACD、趋势线(不持久) |
| 📐 市场回测 | `BacktestModule` | [~] | M1 单股回测完整；M2 全市场筛选 / M3 广度统计为 **ComingSoon 占位** |

| 弹窗 | 文件 | 完成度 | 摘要 |
|---|---|---|---|
| 期货交割单导入 | `dialogs/import_futures.py` | [x] | QThread 后台解析；inserted/ignored 防重报告；孤儿提醒；时间精度强选 |
| 手工录入 | `dialogs/manual_entry.py` | [x] | 账户仅真实列表+可新建；开仓时间选填(勾选才生效)；LONG/SHORT |
| 账户/策略管理 | `dialogs/list_manager.py` | [x] | 通用删除列表（带危险确认） |

---

## 4. 目录结构与代码地图（v5.0 与磁盘一致）

```text
Jian/
├── main.py              # 唯一启动入口：建数据目录、pg 抗锯齿、装配 MainWindow
├── sync_roster.py       # 独立花名册同步脚本(__main__)：A股+期货名册→DB market_symbols，纯手动运行
├── requirements.txt     # PyQt6 / pyqtgraph / pandas / numpy / pyarrow / akshare / openpyxl
├── version.json         # ⚠ 远端版本探测用（见 §9 债务-D）
├── JIAN_RULES.md        # 本文件
├── config/
│   └── settings.py      # 全局常量：APP_NAME、APP_VERSION=1.1.0(⚠)、颜色、INITIAL_CAPITAL=1e6、
│                        #   USER_DATA_DIR=~/.jian_data、UPDATE_CHECK_URL
├── models/
│   └── trade.py         # TradeRecord dataclass —— 全链路唯一闭环交易契约（字段见 §5.1）
├── core/                # 【纯计算层：零 UI 零网络】
│   ├── engine.py        # DataEngine 中央门面(157行)：UI唯一数据入口，编排解析→落库→报告；
│   │                    #    reload/clear/delete/stitch/coverage 全覆盖
│   ├── database.py      # DatabaseManager(479行)：trades+open_legs+import_coverage+coverage_gaps
│   │                    #    +market_symbols 五表 DAO；INSERT OR IGNORE；旧库自动迁移(备份/加列)
│   ├── indicators.py    # TAEngine：MA(5/20/60)/BOLL/MACD 向量化注册表
│   ├── analyzer.py      # TradeAnalyzer：净额口径统计(raw_report) + 持仓时长三级口径聚合
│   ├── backtest.py      # BacktestEngine/BacktestTrade/BacktestResult：LONG-only 单股回测；
│   │                    #   条件为真即触发 + 阶段B风控离场器(risk参数/exit_reason)
│   ├── formula/         # 通达信 DSL（详见 §5.2）
│   ├── utils.py         # 无副作用纯函数：品种去根/诚实时间/持仓秒/交易日跨度/格式化
│   ├── preferences.py   # Preferences 单例：~/.jian_data/preferences.json（唯一键 time_precision）
│   └── updater.py       # UpdateCheckerThread(QThread)：远端 version.json 异步比对，静默失败
├── data/                # 【数据获取/存储层】
│   ├── data_feed.py     # CFMMC 解析(965行)：纯函数无副作用；成交/持仓/结算月报三页签；
│   │                    #   BaseTradeParser+PARSER_REGISTRY；FIFO 缝合与孤儿分配；漏月检测
│   ├── akshare_feed.py  # AkShareFeed：A股新浪/东财兜底、期货主连、花名册、统一清洗、智能路由
│   ├── market_db.py     # DataLakeManager：parquet 分区存取(exists/save/load/get_latest_date)
│   └── strategy_store.py# StrategyStore：回测策略 JSON CRUD + 每标的 metrics 档案(同股对比)
└── ui/                  # 【表现层：只做展示，禁 SQL/爬虫】(见 §3)
    ├── main_window.py   # JianMainWindow：5页装配 + 弹窗调度 + render_all_data + CSV导出 + 漏月告警
    ├── widgets/         # custom_widgets.py(K线图元/悬浮删除) / screenshot_gallery.py / yearly_review.py
    ├── dialogs/         # import_futures / manual_entry / list_manager
    └── views/           # dashboard / records / review / market / backtest_module / backtest
```

---

## 5. 数据契约、铁律与关键口径（改代码前必读，防回归）

### 5.1 TradeRecord 字段语义（`models/trade.py` 为准）

| 字段 | 类型 | 语义/约束 |
|---|---|---|
| `trade_time` | datetime | **唯一主时间锚点** = 平仓/盈亏实现日，恒为纯日期 00:00:00，禁止自动填充时分 |
| `account` / `symbol` / `direction` | str | 账户；合约代码；LONG/SHORT（方向四象限由买卖动作推导，不单独存） |
| `lots` | int | 手数 |
| `net_profit` / `commission` | float | 平仓盈亏(毛) / 手续费；**净额 = net_profit − commission** |
| `internal_id` | str | MD5(账户_单号_交易日期_数量) 确定性哈希；FIFO 切片追加 `#索引` 盐防撞 —— 幂等基石 |
| `trade_id` | str | 展示用 `M_{uuid8大写}` |
| `entry_time` | datetime? | 开仓腿真实时刻（可空；孤儿/纯日期为 None，绝不填 0） |
| `entry_price`/`exit_price` | float? | 开/平仓价（待缝合孤儿 entry_price=None，UI 显示 —） |
| `entry_fill_time`/`exit_fill_time` | str | 原生成交时刻 `HH:MM:SS`（原始数据，完整入库） |
| `time_source` | str | DATE_ONLY / STATEMENT / MANUAL（时刻来源可追溯） |
| `multiplier` | float | 合约乘数：由 `成交额/(价×手数)` 反推（IF=300/IM=200），非近整数则 0 |
| `is_orphan` | int | 1=开仓腿缺失待缝合（CFMMC 专属概念，手工录入不卷入） |
| `strategy_tag`/`entry_reason`/`reflection`/`screenshot_paths` | str | 复盘语义字段；截图路径以 `;` 拼接 |

**DB 附表（`core/database.py`）:**
`trades`（主表）、`open_legs`（未平开仓腿，跨月延续，全量覆写幂等）、
`import_coverage` + `coverage_gaps`（月度资金勾稽 + 用户确认跳过月）、`market_symbols`（花名册）。
**数据湖 zones（`market_db.py`）:** `kline_daily`、`kline_min`(预留)、`index_daily`、`macro_eco`、
`fin_report`、`valuation`、`sentiment`、`hot_topic`。

### 5.2 通达信公式引擎（`core/formula/`）

- 分层：`tokens`(词法) → `parser`(递归下降→AST) → `runtime`(函数求值) → `program`(整段程序)。
- 门面 `FormulaEngine`：`validate/parse/evaluate/signal`；报错分 `FormulaCompileError`/`FormulaEvalError`。
- 内置函数（16 个）：MA EMA SMA REF HHV LLV COUNT SUM IF EVERY CROSS BARSLAST ABS MAX MIN
  **COUNT_TRUE**；多输出内置 MACD(DIF/DEA/HIST,×2) 与 KDJ(K/D/J)；列别名 C/O/H/L/V；
  `=`/`<>` 走容差近似。
  - **`COUNT_TRUE(条件1, 条件2, ...)`**：逐日统计 N 个条件同时成立的数量（变参 1~99）。
    它是「条件组 Gate · 至少 N 个满足」的翻译目标：表达式恒定一行，任意条件数都不爆炸。
    （等效：`>=1` 即 OR，`>=条件总数` 即 AND。）
- 整段程序三态语句：`X:=...` 赋值、`X:...,COLOR...` 输出（**属性被忽略，仅取值**）、
  `STICKLINE/DRAWICON/...` **一律 SKIP 跳过不执行**（⚠ 绘制尚未实现）。
- **多函数段共享执行（阶段A）**：`program.execute_programs(programs, df, params)` 让多段函数
  在【同一个 EvalContext】按序执行 ⇒ 共享变量池；后段可引用前段产出变量；同名后者覆盖，
  语义 = 各段文本以分号拼接成一段后执行，完全一致。`execute_program` 单段入口兼容保留。
- 缺参探测：UI 对全部函数段试运行，捕获"未定义的名称"→ 正则提取参数名 → 占位 5.0 复测
  （见 §7-B3）；`runtime._period` 对窗口类函数校验 `周期≥1`，非法给出友好错误而非裸抛。

### 5.3 产品决策与口径（禁止回归的既定结论）

- **A. 时间双轨制**：`trade_time` 永远纯日期；原生 `*_fill_time` 完整入库；
  用户「时间精度」偏好只控显示/排序（`preferences.time_precision`：DATE_ONLY/FILL_TIME），
  首次导入**强制选择**、流水页可随时切换。
- **B. 净额口径**：胜率/盈亏比/单笔极值/净值曲线一律用 `net_profit − commission`；
  毛利与手续费单列对照（实测净额胜率 45.2% vs 毛利 51.6%）。
- **C. 范围聚焦**：**交易流水/深度复盘只做期货**（股票导入链路已整体删除）；
  股票仅保留「市场行情」「市场回测」侧的行情/回测能力。
- **D. 持仓时长三级口径（v1.3 回归）**：① 开仓带时分→精确计时；② 仅日期→本地交易日历
  `trading_day_count`（无行情回退自然日并标注）；③ 无开仓时间→显示 `—` 绝不猜。
  统计必须标注覆盖样本（covered/total，UI 放 tooltip）。
- **E. 买卖分类**：面向个人，不做投机/套保/套利；只留买入开仓/卖出开仓等四象限文案，
  由 `direction` 推导并在 UI 呈现。
- **F. 孤儿单四层防御（不阻断）**：① 持仓明细页签→下月期初腿；② open_legs 持久化 +
  **全局按(日期,时刻,序号)排序后只跑一次 FIFO ⇒ 分批导入≡一次性导入**；③ 资金链
  `上月结存↔客户权益` 对账 + 漏月告警（最早导入月豁免；用户可登记"确无交易"）；
  ④ `is_orphan=1` 显式标记 + 复盘页手工补录(开仓日期/价,来源 MANUAL)，补导早月自动缝合。
- **G. 交易回放双点锚定**：完整闭环(entry/exit 齐全)→开/平双虚线+价格点线+盈绿亏红高亮带；
  孤儿/老数据→诚实降级单点，标题标"开仓信息缺失"，绝不硬凑坐标。
- **H. 回测铁律**：A股单市场、LONG-only。**信号语义 = 条件布尔为真即触发**（"金叉"类瞬时信号由
  `CROSS` 规则制造；持续为真的条件会在离场后再次进场），收盘评估次日开盘成交；末根K线当日收盘强平
  （`force_close`）；默认数据窗口 2018-01-01；通达信优先级最高（Python 沙箱=远期第二作者）。
  阶段B 硬性风控（止损/止盈/移动止盈/最长持仓）**盘中触发当日即离场、优先于卖出信号**，
  `max_bars` 超时按当日收盘强平——口径详见 §6.5-B。
- **I. 防呆幂等**：DB 一律 `INSERT OR IGNORE`；任何导入必须向 UI 反馈 `inserted/ignored` 统计。

---

## 6. 已完成能力清单（逐模块核对结果，[x]=代码验证通过）

### 6.1 复盘主链路（期货交割单）
- [x] CFMMC `.xls/.xlsx` 解析：成交明细(第9行表头起)/持仓明细/结算月报三页签，脏数据清洗
  （隐藏空格、`'--'`→0、成交时间非法→空串不造假）；`交易月份` 元信息不可信→以成交日期众数为准。
- [x] FIFO 缝合：理论盈亏加权分配、孤儿片承接余额；多文件合并**顺序无关**。
- [x] 幂等入库 + 防重统计报告（inserted/ignored）+ 跨月连续索引。
- [x] 资金链漏月检测 + 非阻断告警弹窗（立即补导 / 确无交易 / 稍后处理）。
- [x] 孤儿单全链路：标记→黄条提醒(流水页)→手工补录缝合(复盘页)→补导自动缝合。
- [x] 流水页五维过滤(账户/品种主体/方向/盈亏/完整度) + 常驻孤儿黄条 + CSV 全量导出。
- [x] 复盘月/年双模态 + 日/月历热力图 + 复盘记录(策略/进场理由/反思/截图) CRUD。
- [x] 绩效统计全净额口径 + 持仓时长三级口径卡片（覆盖数 tooltip 标注）。

### 6.2 市场行情（股票/期货浏览）
- [x] 花名册检索（`search_symbol` 模糊）+ 数据湖优先 → 联网兜底(AkShare 智能路由) → 自动回写数据湖。
- [x] pyqtgraph K线(`CandlestickItem`)+MA/BOLL+成交量+MACD 联动渲染（本地缓存数据正常渲染）。
- [~] 趋势线绘制（`LineSegmentROI` 添加/清除）—— **仅内存态，重渲染即清空，未持久化**（见 §7-A1）。

### 6.3 市场回测 M1 单股（`ui/views/backtest.py`）
- [x] **多函数段编辑（阶段A）**：① 卡为 `ui/widgets/function_segments.py`，可增删多段；检测时
  逐段解析、错误精确到"函数段 N"，在共享变量池上试运行，缺参探测对全段生效。
- [x] **条件组 Gate（阶段A）**：买卖侧各为 `ui/widgets/condition_gate.py` 的 `ConditionGate`，
  每侧可配**多行**积木条件（变量+规则+数值），组合逻辑用「满足计数」统一表达：
  全部满足(AND) / 任一满足(OR) / 至少 N 个满足 → 自动翻译为
  `COUNT_TRUE(cond1, cond2, ...) >= N` 单行 DSL，引擎零改动。
- [x] 整段函数粘贴编辑 → 一键检测（语法 / 哑数据试运行 / 缺参探测并用 5.0 占位复测）。
- [x] `BacktestEngine` 条件为真即触发回测：KPI(总成交/胜率/累计收益/平均单笔) + 净值曲线 +
  K线买卖点标注(三角买/菱形卖) + 9 列成交明细(含离场原因) + 参数区间快捷档 + 折叠专注编辑区。
- [x] **风控离场器（阶段B）**：`run(..., risk=)` 支持 最长持仓N根 / 固定止损 / 固定止盈 /
  移动止盈回撤；盘中触发、硬规则优先；`BacktestTrade.exit_reason` 全链路记录，
  UI 明细表按原因着色（止损/超时/强平等），策略快照随存随载。
- [x] 策略工作台：`StrategyStore` 保存/选用/删除；同股跨策略对比（`metrics_snapshot` 表格+曲线）。
- [x] **策略快照兼容（阶段A）**：payload 新增 `segments`(多段文本) + `function`(分号归并，供
  `find_same` 签名与旧版载入)；`condition_buy/sell` 升级为 `{logic, n, conditions[]}`，
  `ConditionGate.load_config` 兼容旧版单条件平铺 dict。
- [x] **签名含风控（阶段B）**：`_signature` 计入 `risk`，全 0 与旧档(无 risk)等价；
  任一风控启用即视为不同策略，避免不同风控配置相互污染对比。
- [x] 稳定性：缺参友好提示；非法周期不穿透 UI；UI 始终 QThread 执行拉数与回测。

### 6.4 基础设施与演进
- [x] SQLite 迁移链：旧双时间表自动备份重建（COALESCE 归并）；v1.2 增量列走 `ALTER TABLE` 零损加列。
- [x] 纯 Pandas 指标引擎（零编译依赖，兼容 Py3.14+）。
- [x] Parquet 数据湖基础原语（读写/探针/最新日期探测）。
- [x] 代码物理拆分纪律良好：UI 层无 SQL/爬虫；弹窗全独立；`DataEngine` 单一数据门面。

---

## 6.5 市场回测·升级迭代路线（阶段 A/B 已落地，C/远期排期）

> 2026-09 定稿的产品口径：**信号语义 = 多条件满足计数**，OR/AND 只是"至少N"的两个特例，
> 不做传统意义上的单一"事件"二分。以下阶段由用户分期批准，逐批实施。

- **[x] 阶段 A（已落地）** —— 静态多条件信号：
  - A-1 `COUNT_TRUE` 计数原语（runtime 注册表，变参 1~99）。
  - A-2 多函数段共享变量池（`execute_programs`）——覆盖"MACD金叉 + KDJ<20 + 自研>20"。
  - A-3 UI 条件组 Gate（多行积木 + 全部/任一/至少N）——覆盖"多个卖点任一满足就卖"。
  - A-4 策略快照结构升级 + 老档兼容读取。
- **[x] 阶段 B（已落地）** —— 引擎风控离场器（治"指标滞后、盈利单变亏"的**动态**痛点）：
  - B-1 `core/backtest.py`：`normalize_risk()` 归一百分比口径；`BacktestTrade.exit_reason` 记录
    离场来源（`signal`/`stop_loss`/`take_profit`/`trailing`/`max_bars`/`force_close`）。
  - B-2 引擎硬性规则（与信号正交）：固定止损/止盈/移动止盈基于当日 low/high **盘中触发即离场**
    （触发价=预设线，跳空越线则按开盘价，不占便宜）；下沿止损与移动止盈同根都触及取更高线先成交；
    `max_bars` 第 N 根收盘仍持仓则**当日收盘强平**；**硬规则优先于卖出信号**；净值/成交记录不变形。
  - B-3 `BacktestEngine.run(..., risk=dict)` 全零=关闭，默认行为与旧版完全一致（回归已验）。
  - B-4 UI：下区新增「🛡 风控离场」参数行（最长持仓/固定止损/固定止盈/移动止盈，0=关闭）；
    成交明细表新增「离场原因」列（按原因着色 + tooltip）。
  - B-5 `strategy_store`：策略 payload 新增 `risk` 字段；`_signature` 计入风控
    （全 0 等价旧档空字段，签名兼容已验证）。
- **[ ] 阶段 C** —— 大盘/指数 regime 门控：指数函数段独立求值→按日对齐拼接为门控列参与
  买卖组（引擎零改动）；需先补 `akshare_feed` 指数接口与 `index_daily` zone 使用。
- **[ ] 远期** —— 组合级多标的引擎（指数择时后全市场挑股 + 资金分配）= 全新模块，勿并入 M1。

---

## 7. Roadmap：未完成项（按优先级与依赖重新分类）

### A 类 · 半成品闭环（有代码入口/雏形，缺最后一公里 —— 建议优先）
- **A1 [~] 行情涂鸦板持久化** `ui/views/market.py`：画线已可交互，但 `drawn_lines` 随重渲染清空、
  无落盘。**收尾定义**：选定存储(DB 附表或 JSON) + 代码维度去重 + 复盘页/行情页复用。
- **A2 [~] 回测结果导出/删除** `ui/views/backtest.py` + `data/strategy_store.py`：
  `record_result` 已归档每标的 metrics 且同股对比可用，但**结果集无导出/删除 UI**。
  **收尾定义**：结果明细入库 + 列表管理 + CSV 导出（对齐主链路 `export_data` 体验）。
- **A3 [~] P0 数据管理页**：回测需"先本地湖后扫描"，当前**无删除缓存原语**（`DataLakeManager`
  缺 `delete_data`/同步方法）、无独立管理 UI、`akshare_feed` 无指数接口（M3 前置依赖）。
  **收尾定义**：`delete_data` 原语 → `index_daily` 指数拉取 → UI 管理页(预下载/增量/删除)。

### B 类 · 市场回测扩展（规格 §9 已定稿，占位就绪待填充）
- **B1 [ ] M2 全市场单日横截面筛选**：`backtest_module.py` `page_scan` 现为 `_ComingSoonPage`。
  依赖 A3（预下载全市场湖）。需 `scan_cache` zone（公式哈希+日期维中间结果缓存）。
- **B2 [ ] M3 全市场广度家数折线 + 指数双轴叠加**：`page_breadth` 占位；需指数日线接入。
- **B3 [ ] P1b+ 公式绘制补强** `core/formula/program.py`：STICKLINE/DRAWICON/颜色线型现被 SKIP。
  收尾：实现真执行（产出绘图指令序列）→ UI 叠加到 K线图；扩展函数子集 + 函数模板库。
- **B4 [ ] P1c 回测进阶（部分）**：结果长期入库已有雏形(A2)，缺 复用 `TradeAnalyzer` 绩效维度
  与每回合明细的持久化侧写。

### C 类 · 体验升级（有明确规格，尚未动工）
- **C1 [ ] Dashboard GitHub 风格日历热力图** `ui/views/dashboard.py`：当前 dashboard 无热力图
  （复盘页的月历热力图 ≠ 本需求，勿混淆）。可复用日级净额聚合。

### D 类 · 远期（设计预留，暂不排期）
- **D1 [ ] Python 脚本沙箱（AST 白名单）第二作者模式**：接入点预留在 `core/formula`。
- **D2 [ ] 期货侧回测**：`BacktestEngine` 明确 LONG-only/A股，做空与期货为远期。
- **D3 [ ] `kline_min` 高频分时数据湖 zone**（已 mkdir，功能预留）。

---

## 8. 版本演进备忘（压缩 changelog）

| 版本 | 里程碑 | 一句话备注 |
|---|---|---|
| Phase 1~3 | 基础 MVP | UI 组件物理隔离、SQLite 防重、CFMMC 跨月缝合 |
| Phase 4.1 | 基础设施 | Parquet 湖、TAEngine、AkShare 封装 |
| v1.1 | 数据契约重构 | 双时间→单一 `trade_time` 锚点；旧库自动无损迁移；删虚构"时长分析" |
| v1.2 | 交割单字段补全 | 补 entry/exit 价与 `*_fill_time`/乘数/time_source；持仓与月报解析；
        FIFO 加权分配；跨月真缝合(顺序无关)；漏月告警；孤儿显式化；净额口径；时间双轨 |
| v1.2.1 | 微观测算修正 | 盈亏分配"点数×乘数×手数"自洽、孤儿片接余额；孤儿语义收敛(CFMMC专属)；
        手工录入账户仅真实+可新建 |
| v1.3 | 范围聚焦+时长回归 | 删股票导入链路；持仓时长三级口径回归(卡+复盘页签)；手工录入补开仓时间(选填) |
| 阶段A(文档v5.1) | 回测信号升级 | 多函数段共享变量池；条件组 Gate(全部/任一/至少N→COUNT_TRUE)；策略快照兼容 |
| 阶段B(文档v5.2) | 回测风控落地 | 引擎风控离场器(止损/止盈/移动止盈/最长持仓,盘中触发硬规则优先) + exit_reason 全链路 + 明细着色 |
| 阶段C/远期 | 排期 | C=大盘指数 regime 门控；远期=组合级多标的引擎（见 §6.5） |

---

## 9. 审计发现：文档 ↔ 代码不一致 / 技术债（本次 v5.0 核对产出）

- **A. 版本号滞后（建议尽快修正）**：代码形态已达 v1.3 功能，但 `config/settings.py` 的
  `APP_VERSION` 与仓库 `version.json` 仍为 `1.1.0`（版本说明只写了 v1.1 变更）。发版时应升 v1.3.x
  并同步 notes（v1.2/v1.2.1/v1.3 见 §8）。
- **B. zone 命名口径漂移**：历史规格曾规划 `market_index` / `scan_cache` 两 zone；
  实际 `market_db.py` zones 为 `index_daily`/`sentiment`/`hot_topic` 等 8 个，且无 `scan_cache`。
  **以代码为准**，新增需求按现有 zone 命名体系扩展并回写本文档。
- **C. §4 文档树过时**：早前目录树缺 `sync_roster.py`、`core/formula/` 实际为 5 个 py；
  本文档 §4 已重绘为磁盘一致版。根目录 `screenshots/` 为历史遗留空壳目录，正式截图目录在
  `~/.jian_data/screenshots`。
- **D. `preferences.json` 目前唯一键为 `time_precision`**：偏好系统已留好读写骨架，
  后续新增用户偏好（图表主题等）直接加 key 即可。
- **E. 无显式代码债务**：全仓库扫描无 `TODO/FIXME/NotImplementedError`；所有"占位"
  均为 ComingSoon 页面或规格预留在注释/文档。

---

## 10. AI 协作最高指令（不可妥协）

1. **Michael Pokorny UI 准则**：任何新增图表元素必须"抗锯齿、去描边、单色高对比"。
2. **防阻塞底线**：涉及 Parquet 读取或网络拉取，一律封装 QThread 异步，UI 丝滑优先。
3. **架构纪律**：新功能先想落点——`core`(纯计算) / `data`(获取存储) / `ui`(展示)；
   **绝不在 ui 写 SQL 或爬虫**，UI 一律经 `DataEngine`/`StrategyStore` 等门面取数。
4. **幂等与诚实**：DB 插入保持 `INSERT OR IGNORE`；任何"看起来能填其实源里没有"的数据
   宁可显示 `—`/降级，**绝不虚构**（时间、价格、持仓一律适用）。
5. **全量输出兜底**：修改核心文件尽量给全量代码或明确插入锚点，防小白复制缩进灾难。
6. **隐私铁律**：用户私有公式/示例不得写入仓库、示例与占位；`.gitignore` 已忽略私密函数文件。
7. 完成一项功能后，**回写本文档 §6/§7** 的状态，保持记忆与磁盘一致。
