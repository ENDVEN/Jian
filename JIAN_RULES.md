# Jian — 开发规范与上下文记忆 (文档 v5.7)

> **本文档是"给未来的你看"的唯一权威记忆**。功能开发前先读：
> §11 速查表（30 秒找回手感）→ §5 数据契约/铁律 → §4 代码地图 → §6/§7 完成度清单。
> 本文档于 v5.0 全面重排：完成项按模块归类核对，未完成项按**优先级 + 依赖**重新分类。
> v5.1：记录「市场回测·阶段A」落地（多函数段共享池 + 条件组 Gate）。
> v5.2：记录「市场回测·阶段B」落地（引擎风控离场器 + exit_reason 全链路）。
> v5.3：记录「市场回测·阶段C」落地（大盘指数 regime 门控）。
> v5.4：记录「单股回测 UX 硬化」（指数预设扩充 / 防滚轮 / 角标弱化 / 编辑区滚动）。
> v5.5：**全仓逐文件通读核对产出** —— 修正 §4 目录树遗漏；新增 §9-F~L 七项实测发现的技术债
> （年度面板口径漂移、花名册半成功覆写风险、UI 边界松动等）；新增 **§11 速查表**。
> v5.6：修「风控行箭头与条件组不一致 + 上箭头只有右半边可点」（根因=Qt 复合控件半截 QSS，
> 见 §10-9 / §6.6-U5）；回测区间下沿 2018→**2016** 并新增近3个月/近6个月/近5年三档（§5.3-H）。
> v5.7：**甲方案收尾** —— 修 §9-F 年度面板净额口径 / §9-G 花名册半成功覆写 / §9-K 注释失真 /
> §9-A 版本号滞后（APP 升 **v1.4.0** 并同步 `version.json`）；
> 新增 **C1 Dashboard 每日净额日历热力图**（`ui/widgets/calendar_heatmap.py`，GitHub 风格 53×7）。
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
| 📊 资金与表现 | `DashboardView` | [x] | 18 项净额口径 KPI 网格 + **每日净额日历热力图(53×7, 可切年份)** + 净值曲线 + 单笔净额分布直方图 |
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
│   ├── utils.py         # 无副作用纯函数：品种去根/诚实时间/持仓秒/交易日跨度/格式化/日期对齐(align_by_date)
│   ├── preferences.py   # Preferences 单例：~/.jian_data/preferences.json（唯一键 time_precision）
│   └── updater.py       # UpdateCheckerThread(QThread)：远端 version.json 异步比对，静默失败
├── data/                # 【数据获取/存储层】
│   ├── data_feed.py     # CFMMC 解析(965行)：纯函数无副作用；成交/持仓/结算月报三页签；
│   │                    #   BaseTradeParser+PARSER_REGISTRY；FIFO 缝合与孤儿分配；漏月检测
│   ├── akshare_feed.py  # AkShareFeed：A股新浪/东财兜底、期货主连、指数日线(阶段C)、花名册、清洗路由
│   ├── market_db.py     # DataLakeManager：parquet 分区存取(exists/save/load/get_latest_date)
│   └── strategy_store.py# StrategyStore：回测策略 JSON CRUD + 每标的 metrics 档案(同股对比)
└── ui/                  # 【表现层：只做展示，禁 SQL/爬虫】(见 §3)
    ├── main_window.py   # JianMainWindow：5页装配 + 弹窗调度 + render_all_data + CSV导出 + 漏月告警
    ├── widgets/         # custom_widgets.py(K线图元/NoWheel控件族/悬浮删除) / screenshot_gallery.py
    │                    #   / yearly_review.py / condition_gate.py(买卖条件组Gate)
    │                    #   / function_segments.py(多段函数编辑器)
    │                    #   / calendar_heatmap.py(Dashboard 每日净额日历热力图, C1)
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
  （`force_close`）；**默认数据窗口 2016-01-01**（v5.6 由 2018 放宽，三处必须同源：
  `core/backtest.DEFAULT_START_DATE`、`ui/views/backtest.py` 的「全部(2016起)」预设、
  起始日期控件的 `setMinimumDate`）；通达信优先级最高（Python 沙箱=远期第二作者）。
  区间快捷档：近3个月 / 近6个月 / 近1年 / 近3年 / 近5年 / 全部(2016起)（顺序即下拉顺序）。
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
- [x] **指数 regime 门控（阶段C）**：③ 卡可选启用；指数下拉预设/手输新浪代码；买卖指数 Gate
  用 `IDX_` 前缀变量；数据就绪链(先指数后个股)；门控列拼入个股 df 后引擎零改动生效
  （详见 §6.5-C）。
- [x] **签名含指数门控（阶段C）**：`_signature` 计入 `index`；未启用/条件空与旧档等价。
- [x] 稳定性：缺参友好提示；非法周期不穿透 UI；UI 始终 QThread 执行拉数与回测
  （含指数日线同步）。

### 6.4 基础设施与演进
- [x] SQLite 迁移链：旧双时间表自动备份重建（COALESCE 归并）；v1.2 增量列走 `ALTER TABLE` 零损加列。
- [x] 纯 Pandas 指标引擎（零编译依赖，兼容 Py3.14+）。
- [x] Parquet 数据湖基础原语（读写/探针/最新日期探测）。
- [~] 代码物理拆分纪律：**弹窗全独立、`DataEngine` 单一门面**已达标；
  但 UI 层仍有边界松动（直连 `AkShareFeed` / `engine.db`），见 §9-H。
  `backtest.py` 1403 行 / `review.py` 1248 行偏大，是下一步拆分重点（§9-L）。

---

## 6.5 市场回测·升级迭代路线（阶段 A/B/C 已落地，远期排期）

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
- **[x] 阶段 C（已落地）** —— 大盘/指数 regime 门控（"不能把个股与大盘分离"）：
  - C-1 `data/akshare_feed.py`：新增 `fetch_index_daily(symbol, min_date)` 新浪指数接口
    （`ak.stock_zh_index_daily`，代码须带前缀如 `sh000001`/`sz399001`，附 `INDEX_PRESETS` 预设表
    与 `is_index_symbol` 校验）；数据落盘数据湖 **`index_daily` zone**。
  - C-2 `core/utils.align_by_date()`：把指数侧(外部日历)序列对齐到个股交易日轴
    —— reindex + ffill（指数停牌日沿用前值），前导空洞按 0 兜底。
  - C-3 UI ③「大盘/指数 regime 门控」卡（可折叠）：启用勾选 + 指数下拉/手输 +
    买卖两个指数 Gate（`gate_index_buy` 买入许可 / `gate_index_sell` 卖出破位）。
    指数 Gate 变量池 = 同一批函数段的 `IDX_` 前缀变量（同一段函数既算个股也算大盘）。
  - C-4 回测链路零引擎改动：指数函数段在大盘上求值 → 指数 Gate 表达式求布尔 →
    `align_by_date` 对齐 → 门控列 `IDX_GATE_BUY/SELL` 拼入个股 df →
    最终表达式 = 原买入 `AND` 许可门控 / 原卖出 `OR` 破位门控。
  - C-5 数据就绪链：先指数后个股（各自本地缺则 QThread 同步后再续跑）；
    `_signature` 计入指数门控（未启用/条件空等价旧档空字段）。
  - 边界纪律：指数求值失败（函数段依赖个股独有列）→ 明确提示，不静默放行。
- **[ ] 远期** —— 组合级多标的引擎（指数择时后全市场挑股 + 资金分配）= 全新模块，勿并入 M1。

### 6.6 单股回测 UX 硬化（文档 v5.4）

> 高信息密度工作台的防误触与可读性改造，由用户实测反馈驱动。

- **[x] U1 指数选择广度**：`INDEX_PRESETS` 从 8 项扩到 **29 项**（分组：大盘核心 / 风格红利 /
  科创创业板 / 热门行业主题 / 北交所），覆盖 `sh000688 科创50`、`sh000698 科创100`、
  `bj899050 北证50`、`sz399997 中证白酒`、`sz399975 证券公司` 等；全部经真实接口代测可用。
  `is_index_symbol` 前缀白名单扩展到 `sh/sz/bj`。行业板块(东财源)当前网络不稳定，未纳入预置。
- **[x] U2 防滚轮误触**：新增 `ui/widgets/custom_widgets.py` 的 **NoWheel 控件族**
  （`NoWheelComboBox/NoWheelDoubleSpinBox/NoWheelSpinBox/NoWheelDateEdit`），
  wheelEvent 直接 ignore —— 悬停参数控件滚动不再误改值，滚动权交还给父级滚动容器。
  已统一替换：回测页全部下拉/日期/风控数值、ConditionGate 全部行内控件、
  流水页 5 个过滤下拉、复盘页 7 个下拉、手工录入 3 个下拉。
- **[x] U3 灰字弱化**：把占版面的长说明文字收敛为「?」小角标 `_hint_icon`(hover 出 tooltip)：
  工具栏提示、②组合逻辑说明、③指数说明、风控行说明；风控各项已有独立 tooltip。
- **[x] U4 编辑区可滚动**：①/②/③ 卡片包进 `QScrollArea`；新增很多函数段/条件不再撑爆页面，
  超高超限时编辑区内部滚动；  `_resync_config_split` 重写为配合滚动容器 + 上区高度上限
  (`max(total*0.55, 320)`)，折叠卡片仍可把空间让给结果区。
- **[x] U5 数值控件视觉/热区统一（v5.6 · 修长期 Bug）**：风控离场行的 4 个
  `QDoubleSpinBox` 原先就地写了「只含控件本体」的半截 QSS，导致 Qt 用默认度量重绘
  子控件 ⇒ ① 上下箭头图标与买卖条件组的原生箭头不一致；② **上箭头只有右半边可点**。
  根治方案：新增 `ui/widgets/custom_widgets.SPINBOX_QSS`（空串 = 原生渲染）作为
  **数值控件唯一可改点**，风控行改为引用它，与条件组完全同源；
  并把宽度 64→72 留足箭头空间。纪律固化见 §10-9。

---

## 7. Roadmap：未完成项（按优先级与依赖重新分类）

### A 类 · 半成品闭环（有代码入口/雏形，缺最后一公里 —— 建议优先）
- **A1 [~] 行情涂鸦板持久化** `ui/views/market.py`：画线已可交互，但 `drawn_lines` 随重渲染清空、
  无落盘。**收尾定义**：选定存储(DB 附表或 JSON) + 代码维度去重 + 复盘页/行情页复用。
- **A2 [~] 回测结果导出/删除** `ui/views/backtest.py` + `data/strategy_store.py`：
  `record_result` 已归档每标的 metrics 且同股对比可用，但**结果集无导出/删除 UI**。
  **收尾定义**：结果明细入库 + 列表管理 + CSV 导出（对齐主链路 `export_data` 体验）。
- **A3 [~] P0 数据管理页**：回测需"先本地湖后扫描"，当前**无删除缓存原语**（`DataLakeManager`
  缺 `delete_data`/同步方法）、无独立管理 UI。（指数拉取能力已在阶段 C 就绪：`fetch_index_daily`
  + `index_daily` zone 缓存。）
  **收尾定义**：`delete_data` 原语 → UI 管理页(预下载/增量/删除)。

### B 类 · 市场回测扩展（规格 §9 已定稿，占位就绪待填充）
- **B1 [ ] M2 全市场单日横截面筛选**：`backtest_module.py` `page_scan` 现为 `_ComingSoonPage`。
  依赖 A3（预下载全市场湖）。需 `scan_cache` zone（公式哈希+日期维中间结果缓存）。
- **B2 [ ] M3 全市场广度家数折线 + 指数双轴叠加**：`page_breadth` 占位；指数日线能力已就绪
  （阶段C：`fetch_index_daily`/`index_daily`），缺广度统计实现与双轴 UI。
- **B3 [ ] P1b+ 公式绘制补强** `core/formula/program.py`：STICKLINE/DRAWICON/颜色线型现被 SKIP。
  收尾：实现真执行（产出绘图指令序列）→ UI 叠加到 K线图；扩展函数子集 + 函数模板库。
- **B4 [ ] P1c 回测进阶（部分）**：结果长期入库已有雏形(A2)，缺 复用 `TradeAnalyzer` 绩效维度
  与每回合明细的持久化侧写。

### C 类 · 体验升级（有明确规格，尚未动工）
- **[x] C1 Dashboard GitHub 风格日历热力图**（v5.7 已完成）`ui/widgets/calendar_heatmap.py` +
  `ui/views/dashboard.py`：整年 53×7 网格（周一为首行），颜色 = **当日净额**
  （绿盈红亏，5 档分位），灰色 = 无交易/净额为 0；支持年份下拉切换（默认停在最近有数据年）、
  年度摘要（交易日数 / 盈利天数 / 亏损天数 / 年度净额）、悬停 tooltip（日期+净额+笔数）。
  **注意**：复盘页的「月历热力图」是另一个东西（单月 6×7、可点选交易），勿混淆、勿互相替换。

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
| 阶段C(文档v5.3) | 指数门控落地 | 新浪指数接口 + index_daily 数据湖 + align_by_date 对齐 + ③指数Gate(买许可AND/卖破位OR)，引擎零改动 |
| v5.6(文档v5.6) | 回测 UX 补强 | 风控行箭头统一为原生（根治"上箭头只有右半边可点"）+ 区间下沿 2018→2016 + 新增近3月/近6月/近5年三档；新增 §10-9 控件一致性铁律 |
| v1.4.0 | 回测总集 + 甲方案收尾 | 多函数段共享池 / 条件组 Gate / 风控离场器 / 指数 regime 门控；年度面板净额口径统一；花名册覆写安全闸；Dashboard 每日净额日历(C1)；`APP_VERSION` 与 `version.json` 同步升 1.4.0 |
| 远期 | 排期 | 组合级多标的引擎（指数择时后全市场挑股+资金分配，见 §6.5） |

---

## 9. 审计发现：文档 ↔ 代码不一致 / 技术债（本次 v5.0 核对产出）

- **A. ✅ 已修（v5.7）版本号滞后**：`config/settings.py` 的 `APP_VERSION` 与 `version.json`
  已统一升到 **1.4.0**，notes 补齐 v1.2 / v1.2.1 / v1.3 / v1.4.0 全量变更。
  【纪律】改版本号必须**两处同步**：`APP_VERSION`（本地比对基准）与 `version.json`（远端清单），
  不同步会导致自动更新误报或漏报（见 `core/updater.py`）。
- **B. zone 命名口径漂移**：历史规格曾规划 `market_index` / `scan_cache` 两 zone；
  实际 `market_db.py` zones 为 `index_daily`/`sentiment`/`hot_topic` 等 8 个，且无 `scan_cache`。
  **以代码为准**，新增需求按现有 zone 命名体系扩展并回写本文档。
- **C. §4 文档树过时**：早前目录树缺 `sync_roster.py`、`core/formula/` 实际为 5 个 py；
  本文档 §4 已重绘为磁盘一致版。根目录 `screenshots/` 为历史遗留空壳目录，正式截图目录在
  `~/.jian_data/screenshots`。
- **D. `preferences.json` 目前唯一键为 `time_precision`**：偏好系统已留好读写骨架，
  后续新增用户偏好（图表主题等）直接加 key 即可。
- **E. 无显式代码债务**：全仓库扫描无 `TODO/FIXME/NotImplementedError`；所有"占位"
  均为 ComingSoon 页面或规格预留在注释/文档。（v5.5 复扫确认仍成立，唯一命中是
  `core/indicators.py` 注释里的 "add_xxx" 占位示例，非真实债务。）

### v5.5 全仓通读新增发现（按「会不会伤到用户数据」排序）
- **F. ✅ 已修（v5.7）~~【口径 Bug】年度面板未扣手续费，违反 §5.3-B 净额铁律~~**：
  `ui/widgets/yearly_review.py`：`:136` 年度净值曲线、`:111` 月度盈亏卡片、
  `:145` 策略贡献度条形图，**三处都用 `net_profit` 裸值**；
  而 `ui/views/review.py:518/577`、`core/analyzer.py:30` 一律用 `net_profit − commission`。
  后果：**同一批数据切到「年视图」看到的资金曲线比「月视图」系统性偏高**（差 = 总手续费）。
  修法（已实施）：`YearlyReviewPanel.render()` 统一先算
  `net_amount = net_profit − commission.fillna(0)`，三处消费点全改用它，
  标题补「(已扣手续费)」。冒烟断言：年度曲线末值 == 该年净额之和（与毛利差额 = 手续费）。
- **G. ✅ 已修（v5.7）~~【数据安全】`sync_roster.py` 半成功会毁掉 A 股名册~~**：`update_market_roster` 是
  `if_exists='replace'` 全量覆写（`core/database.py:456`）；`fetch_a_share_roster()` 断网返回
  空 DF，而期货名册是硬编码必然非空 → `sync_roster.py:24` 只判断 concat 后的整体是否为空，
  于是**A 股拉取失败时仍会用「只剩期货」的名册覆盖全表**，A 股名称全丢。
  修法（已实施）：改为**分市场各自判空**，任一为空即打印缺失方并 `return`，
  数据库既有名册原样保留。
- **H. 【架构边界松动】UI 层 3 处直连底层**（违反 §10.3 精神）：
  ① `ui/views/market.py:12,48` 直接 `AkShareFeed.fetch_daily_auto`；
  ② `ui/views/backtest.py:46,122,143,988` 直接 `AkShareFeed.*` + `is_stock_code`；
  ③ `ui/views/backtest.py:982` 直接 `self.main_win.engine.db.search_symbol`（UI 触到 DAO）。
  缓解事实：网络调用确实都包在 QThread 里，未卡 UI。收尾方向：把「搜索标的 + 取行情」
  收敛成 `DataEngine` / 新增 `MarketService` 门面，UI 只认门面。
- **I. 【重复代码】`_apply_pokorny_style` 一字不差重复两份**：
  `review.py:51-69` 与 `yearly_review.py:30-47`（约 19 行）。
  另有「排序→cumsum→按盈亏选色→plot+fillLevel」净值绘制逻辑重复于
  `review.py:576-585` 与 `yearly_review.py:135-143`。
  收尾：下沉到 `ui/widgets/chart_style.py`（建议新增公共模块）。
- **J. 【小坑合集】**（不改也不崩，但值得知道）：
  - `review.py:658-665`：持仓时长「仅日期」分支异常时把 0 天计入均值，与该文件
    注释宣称的"算不出来就不参与统计"自相矛盾。
  - `review.py:454`：`engine.df` 为空时提前 return，未刷新 `cb_time_picker`，留下陈旧月份项。
  - `review.py:497-499`：切到年视图不清空 `playback_chart`，可能残留上次 K 线回放。
  - `screenshot_gallery.py:143`：无扩展名文件 `rsplit('.')` 会 IndexError；
    `:84-88` 静默丢弃磁盘上已失效的截图路径（用户无感知，且会被写回库=变相删数据）。
  - `manual_entry.py:189`：`value() or None` 使真实 0 价无法录入（设计取舍，非 Bug）。
  - `import_futures.py`：`engine.parse_cfmmc` 在子线程内会读 SQLite（`load_open_legs`），
    且 `self.worker` 无 `wait()` 生命周期管理，提前关窗可能留下悬空线程。
- **K. ✅ 已修（v5.7）~~【文档与代码不一致】`data/data_feed.py` 注释称「UI 层已有调用」已失真~~**：
  `BaseTradeParser` / `CFMMCTradeParser` / `PARSER_REGISTRY` / `get_parser` /
  `parse_cfmmc_excel` 全仓**无外部引用**，是纯粹的扩展预留。真实对外 API 只有 3 个：
  `parse_cfmmc_files` / `legs_from_payload` / `detect_coverage_gaps`（均被 `core/engine.py` 调用）。
  已在 `parse_cfmmc_excel` 的 docstring 里写明事实，避免未来的我误用。
- **L. 【体积预警】**：`ui/views/backtest.py` 1403 行、`ui/views/review.py` 1248 行、
  `data/data_feed.py` 964 行。三者都还是"单一大类 + 长方法"形态，继续加功能前建议先拆
  （回测页可按「编辑区 / 运行管线 / 结果渲染」拆 3 个私有子构件）。

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
8. **每次会话结束前**，把本次改动摘要追加进 §8 版本表 + §9 债务表（若有新发现），
   让下一次的"我"打开这份文档就能接上，不需要重新通读 6400 行代码。
9. **【控件一致性铁律 · v5.6 新增】同一类控件必须同一张脸，且点击热区必须 == 视觉区域**：
   - **复用优先**：数值输入一律用 `ui/widgets/custom_widgets.py` 的
     `NoWheelSpinBox` / `NoWheelDoubleSpinBox` / `NoWheelComboBox` / `NoWheelDateEdit`，
     样式一律引用该文件导出的常量（当前 `SPINBOX_QSS` = 空串 = 原生渲染）。
   - **禁止半截 QSS**（本条由真实 Bug 倒逼产生，务必牢记）：
     `QSpinBox` / `QDoubleSpinBox` / `QComboBox` / `QDateEdit` 都是 Qt **复合控件**。
     只给控件本体写 QSS（例 `QDoubleSpinBox { padding…; border-radius… }`）而**不写全
     子控件**（`::up-button` / `::down-button` / `::up-arrow` / `::down-arrow` /
     `::drop-down` / `::down-arrow` …），Qt 会用默认度量重绘子控件，必然导致
     **图标样式漂移** 与 **热区与视觉错位**（历史 Bug：风控行上箭头只有右半边能点，
     长期未解）。
     → 要美化就写**完整**的 QSS，且必须收敛到 `custom_widgets.py` 统一导出，
     由所有调用方共用，**绝不在业务页面就地 `setStyleSheet`**。
   - **尺寸要给足**：窄控件会挤压箭头/下拉按钮，同样造成热区异常；
     数值控件最小宽度不得小于 72px。
   - **新增任何输入控件后自检**：① 与同类控件图标是否一致？② 上下/下拉按钮整块是否
     都能点？③ 是否复用了统一常量而非就地写样式？

---

## 11. 速查表：给"刚醒来的我"的 30 秒重启手册

> 以下内容是从 v5.5 全仓通读里提炼的**最高密度结论**。
> 如果你只有 30 秒，只看这一节；如果你要动刀，再按指引去翻对应章节。

### 11.1 一句话概括这个软件
一个**期货交割单驱动的复盘系统**（本地 SQLite + PyQt6 桌面端），
顺带挂了一个**A 股行情浏览 + 单股公式回测**的工作台。
两条链路几乎不交叉：**复盘链路只认期货，回测链路只认 A 股（且只能做多）**。

### 11.2 数据往哪流（记住这 4 跳就够了）
```
Excel(交割单) →data/data_feed.py 解析+FIFO缝合→ models/trade.py TradeRecord
             →core/engine.py DataEngine(唯一门面)→ core/database.py SQLite
             →core/analyzer.py 算指标 → ui/** 只负责画

AkShare →data/akshare_feed.py→ ~/.jian_data/data_lake/*.parquet (数据湖)
        →core/formula 通达信 DSL 求值 → core/backtest.py 单股回测 → ui/views/backtest.py
```
**UI 永远不许跳过 DataEngine 去碰 SQL**（现状有 3 处违规，见 §9-H，正在收敛中）。

### 11.3 用户数据在哪（改代码时别把仓库当数据库）
| 内容 | 路径 |
|---|---|
| 业务库（流水/持仓腿/覆盖/名册 5 表） | `~/.jian_data/jian_trades.db` |
| 偏好（目前只有 `time_precision`） | `~/.jian_data/preferences.json` |
| 回测策略 + 每标的指标档案 | `~/.jian_data/backtest_strategies.json` |
| 行情数据湖（8 个 zone，parquet） | `~/.jian_data/data_lake/` |
| 复盘截图 | `~/.jian_data/screenshots/` |
| 仓库根目录 `screenshots/` | **空壳历史遗留，勿用** |
| 仓库根目录 `实例*.xlsx` / `实例函数.txt` | **用户隐私，已被 .gitignore 忽略，勿提交勿引用** |

### 11.4 我要改 X，该动哪个文件？
| 想改的东西 | 落点 |
|---|---|
| 加一个统计指标 | `core/analyzer.py`（加 key）→ `ui/views/dashboard.py`（加一行 `metric_keys`） |
| 改交割单解析/缝合规则 | `data/data_feed.py`（纯函数，改完务必验"分批导入 ≡ 一次性导入"） |
| 加一个公式函数 | `core/formula/runtime.py`：`FUNCTIONS` 注册 + `ARITY` 声明元数 |
| 改回测撮合/风控 | `core/backtest.py`（`_run_on_signals` 是纯函数，好测） |
| 加一个技术指标（画图用，非公式） | `core/indicators.py`：`REGISTRY` + `OUTPUTS` |
| 加一个数据湖 zone | `data/market_db.py` 的 `self.zones` 字典 |
| 加一个用户偏好 | `core/preferences.py`：`DEFAULTS` 加 key 即可 |
| 改数值控件外观 | `ui/widgets/custom_widgets.py` 的 `SPINBOX_QSS`（**唯一可改点**，勿就地写 QSS，§10-9） |
| 改回测区间档位 | `ui/views/backtest.py` 的 `_PRESET_ORDER` + `_date_from_preset`（含 2016 下沿） |
| 改 Dashboard 日历热力图 | `ui/widgets/calendar_heatmap.py`（纯手绘控件）+ `dashboard.py` 的 `_prepare_calendar` / `_render_calendar` |
| 改版本号 | `config/settings.py` 的 `APP_VERSION` **和** 仓库 `version.json`（两处必须同步） |
| 回测页 UI | `ui/views/backtest.py`（⚠ 1403 行，先想清楚插在哪一段） |
| M2/M3 新子页 | `ui/views/backtest_module.py` 里换掉 `_ComingSoonPage` |

### 11.5 六个最容易踩的坑（血泪，别重犯）
1. **净额 = `net_profit − commission`**。任何"结果类"指标（胜率/盈亏比/极值/净值曲线）
   漏掉手续费就是造假。已知 `yearly_review.py` 就踩了这个坑（§9-F）。
2. **`trade_time` 永远是纯日期 00:00:00**，绝不自动填时分；真实时刻放 `*_fill_time`。
   没有开仓时间就显示 `—`，**绝不猜**。
3. **任何"看起来能填其实源里没有"的值，一律 `—`/降级**，不要 0、不要 00:00、不要编。
4. **DB 一律 `INSERT OR IGNORE`**，`internal_id` = MD5 确定性哈希（FIFO 切片会追加 `#i` 盐）。
   改哈希规则 = 让老库防重失效，**千万别动**。
5. **FIFO 必须全局排序后只跑一次**（按 日期→时刻→序号），这是"分批导入 ≡ 一次性导入"的地基。
6. **耗时 I/O 一律 QThread**：导入解析、拉个股行情、拉指数、回测计算、版本检测，共 5 处。
7. **别给复合控件写半截 QSS**（§10-9）：`QSpinBox/QDoubleSpinBox/QComboBox/QDateEdit`
   只写本体不写子控件 ⇒ 箭头图标漂移 + 点击热区错位。要美化就写全，并收敛到
   `custom_widgets.py`。

### 11.6 当前"下一步做什么"的推荐顺序（v5.7 刷新）
- ✅ ~~1. 修 §9-F 年度面板净额口径~~（v5.7 已完成）
- ✅ ~~2. 修 §9-G 花名册半成功覆写~~（v5.7 已完成）
- ✅ ~~4'. §7-C1 Dashboard 每日净额日历热力图~~（v5.7 已完成）
- **→ 3. §7-A3 数据管理页**（`DataLakeManager` 补 `delete_data` + 管理 UI）——
  它是 A1/A2/B1/B2 的**共同前置依赖**，做完后面全线解锁；**当前第一顺位**
- 4. §7-A1 涂鸦板持久化 → §7-A2 回测结果导出
- 5. §7-B1/B2（M2/M3 真实功能），依赖 3
- 6. §9-H 收敛 UI 直连（新增 `MarketService` 门面） / §9-I 抽 `chart_style.py` / §9-L 大文件拆分

### 11.7 收工前自检清单
- [ ] 改动的模块状态（`[x]` / `[~]` / `[ ]`）在 §6 / §7 同步了吗？
- [ ] 有没有引入新的"UI 直连 SQL/爬虫"？（§9-H）
- [ ] 净额口径有没有被绕过？（§5.3-B）
- [ ] 虚构数据了吗？（时间 / 价格 / 持仓）
- [ ] 耗时 I/O 走 QThread 了吗？
- [ ] 新发现的技术债写进 §9 了吗？本次摘要写进 §8 了吗？
