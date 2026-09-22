# Jian — 开发规范与上下文记忆 (文档 v6.32)

> **本文档是"给未来的你看"的权威记忆**，但它现在**分册**了 —— 目的是让**本文件能被一次读完**
> （v6.32 前它是 297k 字符，而单次读取上限只有 100k ⇒ 物理上读不完，只能检索 ⇒ 遗漏 + 误信旧数字，
> 已经真实造成过一次版本号事故）。**本文件只放"现在是什么 / 必须遵守什么 / 下一步做什么"；
> 历史与操作手册按下表去 `docs/` 取。**

## ⭐ 当前状态快照（每次开工先读这一段）

| 项 | 值 |
|---|---|
| APP 版本 | **1.36**（= 本次提交首词 · **三处已同批同步 §9-A**：commit 首词 / `APP_VERSION` / `version.json`） |
| 文档版本 | **v6.48**（§7-A2 回测结果**图表导出**：新增 .xlsx 内嵌净值曲线图+买卖点（逐日数据放隐藏表）；CSV 保持参数+逐笔。已发 **1.36**。上一版 v6.47 = §7-B10 数据新鲜度全案 1.35） |
| 最近三版 | `1.36` §7-A2 回测图表导出 · `1.35` §7-B10 数据新鲜度全案 · `1.34` R7 副图换序收尾 |
| **当前主线** | **§7-A2（回测图表导出）✅（本版 1.36）· §7-B10（数据新鲜度）全案已收官**；下一步 = §7-A4 回测历史存档（远期）/ §7-B8 余量（R4 组合配置=远期新引擎 / R12 暂缓）+ 其它 backlog（§7-C/D） |
| **断点** | **v6.48（1.36）§7-A2 回测结果图表导出 ✅**（用户实测：CSV 里“图表完全无法显示”——根因是 CSV 纯文本不能内嵌图，那一大段“图形绘制/QSD/GLX/STICKLINE”只是公式源码文本）。做法：① `build_daily_series(result)`（逐日净值+买卖点，取 equity+trades，**单一事实源**）；② CSV **不写逐日段**（用户反馈“逐日全量太占空间”，看图靠 xlsx）；③ 新增 `ui/widgets/backtest_xlsx.py`——openpyxl **内嵌真图表**（净值折线 + 买卖点 marker 落在曲线上），逐日数据放**隐藏 sheet**、主表只剩图；导出菜单加「📊 导出 Excel 图表…」。验收：`smoke_chart` **745** / `smoke_pages_overlay` **521** 全绿 + compileall（xlsx 图对**构建时 Workbook** 断言，openpyxl 读回会丢图；BytesIO 不落盘）。坑=§11.5-74。**上一版 v6.47（1.35）= §7-B10 全案收官**（定稿守卫+真日历+M1 区间修复+M2/M3 更新引导/滞后/基准日诚实化，坑 §11.5-71/72）。**下一步** = §7-A4 回测历史存档 / §7-B8 余量与其它 backlog |

### 📚 文档地图（先看这里，再定点检索）

| 想知道 | 去哪 |
|---|---|
| 现在什么版本 / 下一步做什么 | **本快照** + §7 的 A/B 类 + §11.6 顶部 |
| 项目定位 / 技术栈 / 页面全景 | §1 · §2 · §3 |
| **代码地图 / 大文件红黑榜** | §4 |
| **数据契约 / 铁律 / 既定口径（改代码前必读）** | §5 |
| 已完成能力清单 | §6 · §6.5 |
| 未完成项 / **活的主案** | §7（**已完结的 6 份主案 → `docs/JIAN_ARCHIVE.md`**） |
| **我该遵守什么（不可妥协）** | §10 |
| 我要改 X，该动哪个文件 | §11.4 |
| **最容易踩的坑（全量）** | **`docs/JIAN_PLAYBOOK.md`**（本文件 §11.5 只留编号索引） |
| 收工前自检 | §11.7 |
| 什么时候改了什么（时间线） | `docs/JIAN_HISTORY.md`（版本叙事 + §8 changelog） |
| 某个旧决定"当年为什么这么定" | `docs/JIAN_ARCHIVE.md`（已完成主案 + 旧审计发现） |

### ⚖ 三条防漂移纪律（v6.32 立 · 比拆分更重要）

1. **同一事实只存一处**：**版本号 → 只在 §9-A**；**断言数 → 只在 §11.7**；**行数 → 只在 §4 红榜**。
   别处一律写「见 §X」，**不再复制数字**（这是本文件此前最大的漂移源：同一数字十几处重复）。
2. **现状与历史分离**：`docs/` 里的历史行**数字冻结**（**永不回改**）；本文件现状行必须带「当前」或日期。
3. **每条待办带状态**：`[x]` 已完成 / `[~]` 进行中 / `[ ]` 未开始；**已完成的不再回改正文**。

状态图例：`[x]` 完成 · `[~]` 部分/半成品 · `[ ]` 未开始/占位。

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
| 并发 | 耗时 I/O 一律 QThread Worker | ✅ v5.13 已收口：`ui/workers.py` 是全 app **唯一的 QThread 定义处**（ScanWorker / SyncWorker / SingleSyncWorker / BacktestRunWorker / ConstituentsWorker / FuturesImportWorker / **CrossSectionWorker** / **ReadinessWorker**(v6.39) / **CalendarWorker**(v6.46 交易日历一次性后台抓））+ 公共件 **`JobGuard`（竞态守卫）**，页面与弹窗一律不自造线程类。**唯一例外**：`core/updater.py` 的 `UpdateCheckerThread` 属 core 层（版本检测不是 UI 职责），不搬进 ui/ |

**用户数据目录（物理隔离，勿在仓库存业务数据）:** `~/.jian_data/`
（`jian_trades.db`、`preferences.json`、`backtest_strategies.json`、`annotations.json`(v6.10 用户标注)、
`formula_library.json`(v6.11 公式配方)、`watchlist.json`(v6.12 自选股)、`data_lake/`、`screenshots/`）。

## 3. 产品全景：5 页导航 + 弹窗（已实现 UI 总览）

导航路由极简（`ui/main_window.py` 仅做组件装配与事件分发，不含业务逻辑）：

| 导航页 | 类（文件） | 完成度 | 能力摘要 |
|---|---|---|---|
| 📊 资金与表现 | `DashboardView` | [x] | **17 项**净额口径 KPI 网格（v5.12 实测，非 18 项，见 §9-O9）+ **每日净额日历热力图(53×7, 可切年份)** + 净值曲线 + 单笔净额分布直方图 |
| 📝 交易流水 | `RecordsView` | [x] | 11 列明细表、五维过滤器、孤儿黄条、CSV 全量导出、时间精度切换 |
| 💡 深度复盘 | `ReviewView` | [x] | 月/年双模态、月历热力图、累计盈亏/交易回放/资金K线/持仓时长四页签、孤儿手工补录、截图画廊 |
| 📈 行情工作台 | `TradingDeskView`（`ui/views/trading_desk.py`，P8 新页；旧 `market.py` 已删） | [x] | 代码查询、数据湖优先+联网兜底、K线+MA/BOLL+量+MACD、**🧮 自定义公式叠加**(与内置指标同一图层协议；**每段可选主图/副图 1/2/3**，多副图按需创建)、**跨窗格十字光标**、**自选股**(增删/排序/双击切换)、**周期 日·周·月**(日线就地聚合)、**复权 前复权/不复权**(两份数据各存一个分区且可单独同步/删除，v6.13)、**画线 32 种**(目录 32 种/6 类全部可画：趋势·水平垂直·形态·斐波分割·时间测量·文字标记；**在图上点出来**——选类型后依次点锚点、橡皮筋预览、画完自动回浏览模式，Esc/右键取消；按 `(标的,周期)` 持久化 + **逐个独立删除**)、**公式配方库**(💾 存为配方 / 📚 配方库 / 📤 送去做回测，开机自动恢复)、**坐标轴自适应**(v6.15/§7-B4：横轴刻度随缩放重算、**逐窗格**纵轴跟随可视区间)、**周期 日·周·月 + 分钟 1/5/15/30/60**(v6.21/§7 D3：分钟独立取数、**只有真实价一种口径**、时长提示到分钟) |
| 📐 市场回测 | `BacktestModule` | [~] | M1 单股回测完整（含 **📚 配方库 / 💾 存为配方 / 📤 送到行情页**，v6.11/P7）；M2 全市场筛选完整（v6.37/STEP 4；**v6.43：基准日先选后扫（日历自由选，默认=本地最新交易日，轴外就近落位）+ 缺数据扫描前二次确认闸门 + 无文件标的逐只诚实记「数据不足」**）；M3 广度统计完整（**v6.38/STEP 5**：广度家数（柱状/折线双视觉，默认柱状+MA5 趋势线）+ 指数副图 x 联动（**v6.43：折线/面积/K线/美国线四图形 + 按日对齐只画当前区间 + 两窗格轴对齐 + 分界把手拖动调高**）+ **⚡增量到最新**（尾段续接，历史一天不动）+ **⟳全量重算**二次确认 + 区间切片零成本；见 §7-B1/B2 主案 **B2 / B3 / D7**） |
| 🗄 数据管理 | `DataManagerView` | [x] | 数据湖 8 分区清单(行数/日期范围/体积/更新时间)、搜索过滤、勾选删除、清空分区(隔离+键入确认)、「更新到最新」「重新全量下载」、批量预下载 |

| 弹窗 | 文件 | 完成度 | 摘要 |
|---|---|---|---|
| 期货交割单导入 | `dialogs/import_futures.py` | [x] | QThread 后台解析；inserted/ignored 防重报告；孤儿提醒；时间精度强选 |
| 手工录入 | `dialogs/manual_entry.py` | [x] | 账户仅真实列表+可新建；开仓时间选填(勾选才生效)；LONG/SHORT |
| 账户/策略管理 | `dialogs/list_manager.py` | [x] | 通用删除列表（带危险确认） |
| 批量预下载 | `dialogs/bulk_download.py` | [x] | 来源：指数预设(29)/指数成分股/粘贴代码列表/全市场A股；参数：起点/间隔/抖动/熔断/跳过已最新；进度+失败清单+中断；**⚡「全市场扫描就绪」一键预设**（全A · 2016起 · 跳过已最新，D6-2） |

---

## 4. 目录结构与代码地图（v6.16 与磁盘逐文件核对；**行数只标 ≥400 行的文件**，口径 = 非空行）

```text
Jian/                    # 【v6.14 文件归置】根目录只留"门面"：入口 / 发布物 / 文档 / 忽略表
├── main.py              #     唯一启动入口：建数据目录、pg 抗锯齿、装配 MainWindow
├── requirements.txt     #     PyQt6 / pyqtgraph / pandas / numpy / pyarrow / akshare / openpyxl
├── version.json         #     ⚠ 发布物：`settings.UPDATE_CHECK_URL` 直链指向**仓库根的这个文件**
│                        #      → **禁止移动/改名**（挪走 = 自动更新静默失效）；须与 APP_VERSION 同步(§9-A)
├── JIAN_RULES.md        #     本文件（唯一权威记忆，**故意**留在根目录：打开仓库第一眼就要看见）
├── .gitignore           #     忽略 __pycache__ / screenshots / *.db / samples/* / 实例* 等隐私
├── scripts/             # 【运维脚本：只给人手动敲命令，**不进 app import 图**】
│   └── sync_roster.py   #     花名册同步(__main__)：A股+期货名册→DB market_symbols
├── tests/               # 【验收脚本：同上，独立入口】⚠ 一律用 `__file__` 反推仓库根，**禁止写死相对路径**
│   ├── smoke_chart.py   # 图表架构 + 控件/口径/标注/配方/周期(含**分钟**档位)/自选/复权/拖动/坐标轴
│   │                    #        + **§7-B1/B2 横截面内核（三态 / 粗筛 / 广度分母 / 缓存矩阵）**
│   │                    #        + **会话缓存（键六样 / 数据版本失效 / 切日期零成本 / 配额）**
│   │                    #        + **工具行 chips 规则（§7-B6 STEP 3c）**
│   │                    #        + **成交真实性(§7-B5)** + **§7-B8 R7/R8（副图换序 / 纵轴固定左槽）**
│   │                    #        + **§7-B8 R1 自选分组（分类语义 / 删组不删股）**
│   │                    #        + **v6.43 轴外基准日就近落位 / 缺文件诚实化 / 成分股选列回归钉**
│   │                    #        + §9-V 数据源护栏（非正价 / 量纲接缝）断言（**745 项**）
│   │                    #       `py tests/smoke_chart.py`（在仓库根执行）
│   │                    #       ⚠ 两脚本开头**自设 UTF-8 stdout**（v6.21）—— Windows GBK 控制台
│   │                    #        下带 `↔`/`⇒` 的 print 会抛 UnicodeEncodeError，表现为
│   │                    #        "整段分节被跳过 + 假报失败"（修前 328/3、修后 356/0）
│   └── smoke_pages_overlay.py # 回测页/工作台/**复盘页**叠层 + 标注 + 互送 + 自选/周期(含**分钟**)/
│                        #       复权/坐标轴 + 顶栏分段控件/chips + 图标轨/分页面板/折起
│                        #       （§7-B6 STEP 3b/3c/4）+ 成交模型行/教学弹窗/导出口径**页面级**验收（**521 项**）
│                        #       + **M2/M3 护栏（v6.43：y 真跟随/刻度可见/先选后扫/闸门/分界线拖动模拟）**
│                        #       + **「行情工作台 / 复盘页 / M2 / M3 迁移护栏」**（公共面改名/删除、把薄壳写成
│                        #         空函数、**§9-U 分栏退化 / 不落偏好**，立刻红）
│                        #       ⚠ 会真建主窗口（开用户库），勿与 app 同时跑；末尾含"用户真实库未被写"自检
├── samples/             # 【私有样例：是数据不是代码】`.gitignore` 里 `samples/*` 整体忽略
│   ├── README.md        #     本目录规则说明（**唯一入库文件**）
│   └── 实例函数*.txt / 实例交割单*.xlsx   # 用户私有公式与交割单（**禁止入库**，见 §10-6）
├── design/              # 【设计样板：HTML 交互原型，**不参与 app 运行**，只作长期设计参考】
│   ├── 1.22-backtest-ui/     # 回测页 4 套样板（用户拍板 A ⇒ 摘要条 + 遮罩抽屉）
│   ├── 1.23-trading-desk-ui/ # 行情工作台 4 套样板 + 汇总页（用户拍板 **A 骨架 + 现状配色**，见 §7-B6）
│   ├── 1.24-desk-sidebar-ui/ # 侧边栏 4 套样板（用户拍板 A 手风琴，见 §7-B8）
│   └── 1.27-scan-breadth-ui/ # ★M2/M3（§7-B1/B2 主案）：README 方案 + index 总览 +
│                             #   m2 全市场筛选 / m3 广度统计 两个可点原型（含状态演示）
├── docs/                # 【文档归档：给"未来的我"读；app 不 import，人看】（v6.32 分层重构新增）
│   ├── JIAN_HISTORY.md       # 时间线：版本叙事（v5.1→v6.32）+ §8 完整 changelog（**历史数字冻结**）
│   ├── JIAN_PLAYBOOK.md      # §11.5「最容易踩的坑」全量清单（**编号不变**）
│   └── JIAN_ARCHIVE.md       # 已完结的 6 份主案（§7-B3…B9）+ 旧审计发现（§9 版本子节）+ §11.6 历史块
├── config/
│   └── settings.py      #     全局常量：APP_NAME、APP_VERSION=1.28(跟随 git，与 version.json 同步)、颜色、
│                        #      INITIAL_CAPITAL=1e6、USER_DATA_DIR=~/.jian_data、UPDATE_CHECK_URL
├── models/
│   └── trade.py         #     TradeRecord dataclass —— 全链路唯一闭环交易契约（字段见 §5.1）
├── core/                # 【纯计算层：零 UI 零网络】
│   ├── engine.py        #     DataEngine 中央门面：UI唯一数据入口，编排解析→落库→报告；
│   │                    #      reload/clear/delete/stitch/coverage + search_symbol/list_stock_symbols
│   ├── database.py      # 435行 DatabaseManager：trades+open_legs+import_coverage+coverage_gaps
│   │                    #      +market_symbols 五表 DAO；INSERT OR IGNORE；旧库自动迁移(备份/加列)
│   ├── indicators.py    #     TAEngine：MA(5/20/60)/BOLL/MACD 向量化注册表
│   ├── analyzer.py      #     TradeAnalyzer：净额口径统计(raw_report) + 持仓时长三级口径聚合
│   ├── backtest.py      # 495行 ⚠ BacktestEngine/BacktestTrade/BacktestResult：LONG-only 单股回测；
│   │                    #      条件为真即触发 + 阶段B风控离场器(risk参数/exit_reason)
│   │                    #      + ★v6.17 成交时点模型(三档) + T+1 硬约束 + 触发式委托（§7-B5）
│   │                    #      + 离场原因 标签/配色/risk_summary/fill_summary 共享常量（v5.15 上收于此）
│   │                    #      + ★v6.17 用户指引文案同源件：FILL_MODE_LABELS / FILL_MODE_ONELINERS
│   │                    #        / fill_mode_oneliner / tick_to_yuan / yuan_to_tick
│   ├── cross_section.py # 564行 ⚠ M2 横截面 / M3 广度**纯计算内核**（§7-B1/B2 · STEP 1 已落地）：
│   │                    #      四态(命中/未命中/**数据不足**/被粗筛剔除) + 粗筛漏斗(D5 全阈值)
│   │                    #      + 逐日广度(日期→整数索引 + 一次 np.bincount) + uint8 缓存矩阵
│   │                    #      ⚠ 与 M1 **同口径**：prepare_frame ≡ BacktestEngine 的数据准备
│   │                    #        （`smoke_chart` 有**源码级**断言钉住：改一处漏一处立刻红）
│   │                    #      ⚠ 新建即越 400 线（§4 已登记）：**新增优先另起模块**
│   ├── formula/         #     通达信 DSL 共 6 文件（详见 §5.2 / §7-B3）
│   │   ├── __init__.py  #     FormulaEngine 门面：validate/parse/evaluate/signal
│   │   ├── tokens.py    #     词法
│   │   ├── parser.py    #     递归下降 → AST（优先级 NOT > 比较 > AND > OR）
│   │   ├── runtime.py   #     EvalContext + FUNCTIONS(16)/ARITY 注册表
│   │   ├── draw.py      #     ★P1 绘图 IR：COLOR_TABLE + DrawSpec/DrawData(hollow) + 属性校验
│   │   │                #      + DEFERRED_DRAW_FUNCTIONS（已知未渲染→不阻断，§9-Q-2）
│   │   └── program.py   #     ★P1 整段程序：ASSIGN/OUTPUT/DRAW 三个 kind（+ hidden(NODRAW) 子态，
│   │                    #      旧 SKIP 已彻底移除 —— 文档旧措辞"4 态"指此四种产出形态）
│   │                    #      + _split_draw_attrs（先摘属性尾巴再解析，§9-Q-1）
│   │                    #      + execute_programs / execute_programs_with_draws
│   │                    #      + execute_programs_with_draws_grouped★v6.8（draws 按段分组，多副图用）
│   │                    #      + probe_missing_parameters★v6.6（缺参探测，回测页/行情页共用）
│   ├── utils.py         #     无副作用纯函数：品种去根/诚实时间/持仓秒/交易日跨度/格式化/align_by_date
│   │                    #      + v6.6 跨页共用件：parse_params_text / synthetic_bars（哑行情，仅自检用）
│   │                    #      + ★v6.9 record_net_amount：净额 = 平仓盈亏 − 手续费的**唯一取值口径**
│   │                    #      + ★v6.12 resample_ohlcv / normalize_period / period_label（日→周/月，纯本地）
│   ├── preferences.py   #     Preferences 单例：~/.jian_data/preferences.json
│   │                    #      键：time_precision / backtest_ui（1.22 回测页卡片展开状态，记住上次）
│   └── updater.py       #     UpdateCheckerThread(QThread)：远端 version.json 异步比对，静默失败
├── data/                # 【数据获取/存储层】
│   ├── scan_store.py    # M2/M3 **会话内存缓存**（§7-B1/B2 STEP 2）：只缓存结果矩阵
│   │                    #      （≈22 MB/全市场，不缓存价量宽表）；键 = 公式 + **粗筛** + 标的域
│   │                    #      + 复权 + **数据版本** ⇒ 数据一变自动失效；`asof` 不进键
│   │                    #      ⇒ **切日期 / 换统计窗口零成本**；**全程不落盘**（无防污染负担）
│   │                    #      + ★v6.38 **⚡增量**（STEP 5 / D7）：`find_base()` 找「同配置、
│   │                    #        旧数据版本」条目 + `merge_tail()` 尾段续接 —— **历史一天都不动**；
│   │                    #        touch（无新交易日）沿用原矩阵、标的集合变了诚实退化全量（`note` 回执）
│   ├── readiness.py     # ★v6.39 就绪度体检（§7-B1/B2 STEP 6 / D6-1）：**只读 parquet footer**
│   │                    #      （行数 + date 统计，实测 0.66 ms/只 ⇒ 全市场 ≈3.6 s）—— 不读数据行、
│   │                    #      零 UI 零网络零写入；四分类 ready/partial/missing/unreadable
│   │                    #      （**坏文件进问题清单，绝不静默跳过**）+ `latest` 本地最新日期 +
│   │                    #      `summary_line()` 一行人话 + `gap_preview()` 缺口点名
│   ├── data_feed.py     # CFMMC 解析**编排层**：成交/持仓页签解析 + 多文件合并 + 解析器注册表；
│   │                    #      1.26 拆分后公共名**再导出** ⇒ 旧 import 口径零改动（§4 历史条目）
│   ├── feed_cells.py    # 单元格/工作表工具层：清洗·转换·列名别名表·页签定位读取（纯函数）
│   ├── feed_fifo.py     # Fill/OpenLeg/MonthlySummary + FIFO 配对引擎（孤儿分配·总额守恒）
│   ├── feed_report.py   # 结算月报页签解析（资金勾稽，缺字段回落 0 不抛异常）
│   ├── feed_months.py   # 月份推断（成交日期众数）+ 资金链对账（漏月检测用）
│   ├── akshare_feed.py  #     AkShareFeed：A股新浪/东财兜底、期货主连、指数日线(阶段C)、花名册、清洗路由
│   │                    #      + ★v6.13 ADJUST_QFQ/NONE：**两个源必须同一个 adjust**（降级不许静默换口径）
│   │                    #      ⚠ 供 UI 引用的仅限纯函数：is_stock_code/is_index_symbol/INDEX_PRESETS(29项)
│   ├── market_db.py     #     DataLakeManager：parquet 分区存取(exists/save/load/get_latest_date)
│   │                    #      + ★v6.13 新增 kline_daily_raw 分区（不复权，与前复权**各存一份**）
│   │                    #      + v5.8 清点删除(delete_data/clear_zone/list_zone/inventory 只读footer/zone_stats)
│   ├── sync_service.py  #     MarketSyncService(v5.8)：行情同步唯一门面 = 增量合并去重 + 温柔抓取
│   │                    #      + ★v6.46 §7-B10 日线收盘定稿守卫（is_daily_bar_settled / _drop_unsettled_tail）
│   ├── trade_calendar.py #    ★v6.46 §7-B10 交易日历获取件：load_or_fetch（当日 JSON 缓存+失败回退）/
│   │                    #      latest_settled_trading_day（日历∩定稿判据）；纯 Python 零 Qt，网络交 CalendarWorker
│   │                    #      + ★v6.13 zone_for_adjust / ADJUST_* / adjust_label（复权口径的**唯一规范化入口**）
│   │                    #      ThrottlePolicy(间隔/抖动/重试/熔断/断点续传)；纯 Python 零 Qt 依赖
│   │                    #      + friendly_fetch_message / short_fetch_reason / friendly_constituent_message
│   │                    #      + ★v6.10 fetch_index_constituents（联网抓取唯一入口，§9-H 红线）
│   ├── strategy_store.py#     StrategyStore：回测策略 JSON CRUD + 每标的 metrics 档案(同股对比)
│   ├── formula_store.py #     ★v6.11/P7 公式配方库：KIND 无关的"函数段+参数+每段目标窗格"资产化
│   │                    #      + 按 name upsert / touch+last_used(开机自动恢复) / 与 strategy_store 同源；
│   │                    #      + get_formula_store() 单例（两页面共用，防"后保存覆盖先保存"）
│   ├── annotations.py   #     ★v6.10/P6 用户标注：KIND_*（trend/hline/vline/**fib**/**text**）
│   │                    #      + `(标的,周期,id)` 原子写 CRUD + DateAxis（日期↔bar序号映射，防漂移）
│   │                    #      + ★v6.12 period_key（周期键规范化：任何写法→daily/weekly/monthly）
│   │                    #      + FIB_RATIOS / fib_levels（档位是语义常量，渲染与导出同源）；零 Qt
│   └── watchlist_store.py#     ★v6.12/P8 自选股：增删/上下移/名称刷新 + 坏数据与重复项容忍
│                        #      （⚠ 与"花名册 market_symbols"是两回事：那是全市场名单）
└── ui/                  # 【表现层：只做展示，禁 SQL/爬虫】(见 §3)
    ├── main_window.py   #     JianMainWindow：6页装配 + 弹窗调度 + render_all_data + CSV导出 + 漏月告警
    │                    #      + ★v6.11/P7 配方互送传话筒（send_formula_to_backtest/market + switch_to）
    ├── workers.py       #     全 app 唯一的 QThread 定义处(v5.13)：ScanWorker(扫湖)/
    │                    #      SyncWorker(批量)/SingleSyncWorker(单只)/BacktestRunWorker(回测)/
    │                    #      ConstituentsWorker(成分股)/FuturesImportWorker(交割单)/
    │                    #      CrossSectionWorker(M2/M3：分块+进度+取消+job_id 回包)
    │                    #      + **JobGuard 竞态守卫**（只接受最新一次任务的回包，§9-O5）
    ├── widgets/         # custom_widgets.py(K线图元/NoWheel控件族/悬浮删除/SPINBOX_QSS
    │                    #   + ★v6.9 **复合控件完整 QSS 契约**：combo_qss()/date_edit_qss() 生成器
    │                    #     & 8 个具名常量 COMBO_QSS* / LINE_COMBO_QSS / DATEEDIT_QSS_WARN /
    │                    #     DIALOG_INPUT_QSS —— 全 app 唯一的控件样式来源，§10-9)
    │                    #   + ★v6.21/§7-B6 STEP 1 **表单构件与分段控件**：mini_label / hint_icon /
    │                    #     TAB_QSS_ON·OFF（自 `backtest_panes` 上收）+ segment_qss() /
    │                    #     segment_button_qss(position) / **SegmentedControl**（周期·复权用）
    │                    #     + STEP 3c chip 样式 CHIP_QSS_ON/OFF/CHIP_MORE_QSS)
    │                    #   / chip_mru.py(★v6.21/§7-B6 STEP 3c **工具行 chips 规则**（纯函数 72 行）：
    │                    #     候选池 / push_recent / normalize_recent / resolve_chips（已启用 ∪
    │                    #     最近前 3）/ hidden_keys（喂「＋ 更多」）)
    │                    #   / desk_*.py —— ★v6.22/§7-B6 STEP 6 **行情工作台拆出来的 9 个行为模块**
    │                    #     （统一约定：**状态留页面、行为搬模块 + 页面保留同名薄壳**；
    │                    #      页面 `ui/views/trading_desk.py` 1375 → **345**，只持状态与转发）：
    │                    #     · desk_layout.py(361：顶栏两行 + 左栏五页 + 图表区装配)
    │                    #     · desk_data.py(278：取数/周期/复权/分钟档位/口径回执)
    │                    #     · desk_layers.py(219：显示用行情 + 统一图层渲染 + 坐标轴 provider；
    │                    #         `SUB_PLOT_HEIGHT`/`DEFAULT_VISIBLE_BARS` 定义于此并由页面再导出)
    │                    #     · desk_panel.py(196：**图标轨 + 分页面板 + DeskPanelController**（切页/折起）；
    │                    #         IconRail 互斥图标轨 + DeskPanel 每页一个空容器；
    │                    #         与行情业务无关 ⇒ §9-U 其他页面收口可直接复用)
    │                    #     · desk_chips.py(161：工具行 chips 投影/回流，"最近使用优先")
    │                    #     · desk_formula.py(157：公式编辑/编译/资产化/互送)
    │                    #     · desk_annotations.py(128：画线工具交互 + 回执)
    │                    #     · desk_watch.py(67：自选股) · desk_readout.py(52：读数条文案)
    │                    #   / screenshot_gallery.py / yearly_review.py
    │                    #   / condition_gate.py(买卖条件组Gate)
    │                    #   / function_segments.py(多段函数编辑器，v6.8 支持每段附件控件)
    │                    #   / calendar_heatmap.py(Dashboard 每日净额日历热力图, C1)
    │                    #   / chart_style.py(★v5.13 收敛点 + v6.3 style_axis/CROSSHAIR + v6.4 对比度守卫
    │                    #        + v6.6 MA_SERIES/BOLL_LINE_COLOR —— 内置指标配色唯一来源)
    │                    #   / backtest_report.py(★v5.15 PNG 报告图渲染, 见 §7-A2)
    │                    #   / chart_pane.py(★P0 已建，v6.10 补 remove_annotation 与 add 成对)
    │                    #   / chart_host.py(★P2 已建，v6.8 承接行情页窗格)
    │                    #   / adaptive_axis.py(★v6.15/§7-B4 坐标轴自适应公共件：
    │                    #        compute_ticks/compute_text_ticks/slice_span（纯函数）
    │                    #        + attach_date_axis/follow_y/attach_all（信号挂接，幂等替换）
    │                    #        —— **全 app 唯一的刻度与量程来源**，禁止页面再手写 setTicks/setYRange)
    │                    #   / draw_overlay.py(★P3 已建，全 app 唯一叠层渲染器)
    │                    #   / indicator_panes.py(★v6.8 成交量/MACD 副图内容构建)
    │                    #   / chart_layers.py(★v6.7 图层公共件：内置指标→IR + 量级引导)
    │                    #   / annotation_items.py(★v6.25 **与类型无关**的图元小件：
    │                    #        `_ClickableText`(v6.13) + `_RegionBand`(v6.25，同样因"不发点击信号"
    │                    #        而必须子类) + 箭头头(角度按**场景坐标**算) + 档位虚线/标签
    │                    #        + `highlight()` 高亮唯一分发口（文字改字色/区间带改填充/其余改画笔）)
    │                    #   / annotation_decos.py(143 ★v6.25 **附属图元**：档位/标签/箭头/周期竖线/
    │                    #        测量文案 —— 都由主图元派生，主图元一动就按新锚点重建)
    │                    #   / annotation_shapes.py(296 ★v6.25 **画线类型规格表**：`ShapeSpec` 一种类型
    │                    #        一行 = 锚点数/画法/回读/默认落点/是否重建附属图元；`DRAWABLE_KINDS`
    │                    #        是"能画哪些"的**唯一事实来源**（与目录 `implemented` 双向断言）；
    │                    #        ★v6.29 §4 处置：`place_*`/`read_*`/上下文对象搬进
    │                    #        `annotation_layouts.py`（本文件 587 → 296，回到 400 线内）)
    │                    #   / annotation_layouts.py(360 ★v6.29 **落点 / 回读 / 规范化**：
    │                    #        `DrawCtx`/`PlaceCtx` 两个上下文 + `read_*`（图元→日期+价）+
    │                    #        `place_*`（新建默认锚点）+ 回归通道的 `reg_*`（拟合/夹边界/
    │                    #        规范化/贴回）；**只做坐标换算与算术**，不 import 规格表（防成环）)
    │                    #   / annotation_catalog.py(★v6.24 32 种目录：6 类/每类一色相/编号即快捷键；
    │                    #        v6.25 起 27 种 implemented=True，余 5 种仍标「待实现」但不静默)
    │                    #   / annotation_tiles.py(★v6.24 目录可视件：tile + 吸顶分类标题滚动区)
    │                    #   / annotation_draw_session.py(★v6.26/§7-B9 **绘制会话**（零业务）：
    │                    #        选类型 ⇒ 在图上依次点锚点 ⇒ 点够落库；橡皮筋预览**复用规格表**
    │                    #        （预览 == 落库后）；Esc/右键取消；**画完自动回浏览模式**（防手残）；
    │                    #        点到已有标注也算落点（绘制期临时让已有标注不吃鼠标）
    │                    #   / annotation_layer.py(★v6.10/P6 用户标注交互：画/选中/**逐个删除**；
    │                    #        v6.12 加 斐波那契(7 档附属图元随主图元同删) 与 文字(_ClickableText)；
    │                    #        v6.13 文字**可拖动**——pyqtgraph 覆写了 mouseMoveEvent 且不调父类，
    │                    #        故 ItemIsMovable 无效，必须自己实现 mousePress/Drag + 松手落盘；
    │                    #        ★v6.25 **不再认识任何具体画法**：只准备 `DrawCtx` 交给规格表；
    │                    #        ★v6.26 接管绘制会话的输入（场景点击/移动）+ `commit_draw` 落库
    │                    #        + "依赖视图"类型的缩放重算钩子（甘氏扇形/斐波弧，2% 节流）)
    │                    #   / formula_library.py(★v6.11/P7 配方库窗口：列表/预览/载入/改名/删除，两页共用)
    │                    #   / backtest_panes.py(395 ★1.22 回测页五张编辑卡片：ƒ函数/⇄条件/📉大盘/🛡风控/
    │                    #        🎯成交（纯视图）+ **EditDrawer 右侧遮罩抽屉**（遮罩 + 页签 +
    │                    #        卡片堆叠）—— 样板 A 的 L3 层；含 mini_label/hint_icon/number_spin
    │                    #   / **scan_layout.py(327 M2 版式：L1 操作轴 / L2 摘要条 / L0 结果区 /
    │                    #        L3 抽屉两张卡「ƒ 筛选条件」「🎚 粗筛」（阈值⇄控件唯一换算处）)**
    │                    #   / **scan_flow.py(262 M2 运行流程：范围解析（自选/指数成分/全A）· 后台扫描
    │                    #        （CrossSectionWorker + JobGuard）· 进度回执 · **切日期零成本** · 跳行情)**
    │                    #   / **scan_result.py(137 M2 结果渲染：KPI 三态 + 有效样本 + 结果表 +
    │                    #        空态三选一动作；**非扫描基准日只显示状态，不拿旧快照冒充**)**
    │                    #        三个表单构件（全 app 唯一来源）。抽屉/遮罩与回测业务无关
    │                    #        ⇒ 其他页面可直接复用（§9-U）；**§7-B6 STEP 1 会把
    │                    #        mini_label/hint_icon + 页签 QSS 上收到 `custom_widgets.py`**
    │                    #        ✅ 已回到 400 线内（395，按 v6.16 口径不再标数字）)
    │                    #   / **breadth_*.py —— ★v6.38/§7-B1/B2 STEP 5 **M3 广度页拆出来的 4 个模块**
    │                    #     （同款约定：状态留页面、行为搬模块 + 页面保留同名薄壳）：
    │                    #     · breadth_layout.py(238：L1 操作轴 + L2 摘要条（⚡/⟳/▶ 三按钮）+
    │                    #         L0 结果区 + L3 抽屉三卡；**ƒ/🎚 直接复用 `scan_layout` 同款**)
    │                    #     · breadth_flow.py(390：范围解析 / 扫描 / **⚡增量** / **⟳全量重算**
    │                    #         （二次确认闸门）/ 区间切片 / 指数补拉链（`_ensure_index`）)
    │                    #     · breadth_chart.py(165：**双窗格图表**（BreadthChart）= 广度折线
    │                    #         （家数/占比% + MA5 平滑 + 末点标记）+ 指数副图；ChartHost
    │                    #         x 联动 + `adaptive_axis` + 读数条 provider（§7-B6 同款）)
    │                    #     · breadth_result.py(35：空态/忙碌态；与 `scan_result` 同一套 API))
    │                    #   / **readiness_flow.py(★v6.39 **就绪度体检 + ⬇补齐缺失的两页共用控制器**（D6：
    │                    #     「就绪度模型只有一份」）—— `start()` 后台体检 → 回执一行 + 缺口可见 →
    │                    #     `fill_missing()`（SyncWorker 温柔抓取可中断 + >50 只二次确认）→ 复检；
    │                    #     回调**绑定各自 scope**（旧范围迟到回包/进度一律丢弃，防覆盖新提示）；
    │                    #     `constituent_failure_text()` 成分股失败人话诊断唯一出口)
    │                    #   / backtest_result.py(432 ★1.22 结果区（L0 主角）：KPI 四卡 + K线控制行 +
    │                    #        4 个结果页签（净值曲线 / K线买卖点+公式叠层 / 策略对比 / 成交明细）
    │                    #        + 全部图表渲染与日期轴·量程自适应；`_df`/`_draws` 由页面每次显式喂入
    │                    #        ⚠ 已越 400 线：再长就按「图表渲染 / KPI+表格」再切一刀)
    │                    #   / backtest_flow.py(304 ★1.22 运行流程：发起前校验+**发起瞬间定格参数快照** /
    │                    #        数据就绪链（先指数后个股，缺数据走 SingleSyncWorker）/ 在真实行情上求值
    │                    #        +拼指数门控列 / 交 BacktestRunWorker 算 / 结果落地 + 归档。**状态全留页面**)
    │                    #   / backtest_strategy.py(194 ★1.22 策略库桥接：快照打包·还原·存删·归档·对比；
    │                    #        同上，状态（store / _active_strategy_id / 各控件）留在页面)
    │                    #   / backtest_summary_bar.py(★1.22 配置摘要条：一行 chips = 当前配置状态 + 入口，
    │                    #        右端承载运行回执与「▶ 开始回测」—— 样板 A 的 L2 层)
    │                    #   / backtest_export.py(★1.22 结果导出：compose_result_csv 纯函数 +
    │                    #        build_daily_series(§7-A2 逐日净值+买卖点共同源) + CSV/PNG 入口)
    │                    #   / backtest_xlsx.py(★v1.36 §7-A2：openpyxl 内嵌净值曲线图+买卖点，
    │                    #        _build_workbook 与存盘解耦)
    │                    #   / review_*.py —— ★1.26/§9-U+§9-L **复盘页拆出来的 5 个模块**
    │                    #     （同款约定：状态留页面、行为搬模块 + 页面保留同名薄壳）：
    │                    #     · review_layout.py(310：两行操作轴 + 宏观/微观**可拖竖向分栏** +
    │                    #         孤儿补录条 + 编辑卡；分栏高度记 `review_ui.v_sizes`)
    │                    #     · review_charts.py(244：日历热力图 / 月度净值+资金K线 / 持仓时长)
    │                    #     · review_playback.py(238：交易回放双点锚定 + 单点降级 + 数据缺口提示)
    │                    #     · review_editor.py(310：当日清单 / 详情头 / 复盘保存 / 孤儿缝合)
    │                    #     · review_flow.py(197：月年切换 / 五个筛选 / 时间跳转 / 视图刷新)
    ├── dialogs/         # import_futures / manual_entry / list_manager
    │                    #   / bulk_download(416 批量预下载；v6.10 成分股改走同步门面)
    │                    #   / formula_overlay.py(★v6.7 行情页公式编辑器：每段目标窗格+示例模板)
    │                    #   / fill_model_help.py(★v6.17 成交模型用户教学弹窗：三档口径 + T+1
    │                    #        用一套固定价格数字讲差别；**只读不写**，不改任何配置)
    └── views/           # dashboard / records
                         #   / review(✅ 1.26 · §9-U 收口 + §9-L 拆分收官：**1067 → 173**，
                        #        月/年双模态 + 交易回放 + 资金K线 + 截图画廊；
                        #        行为分居 5 个 `ui/widgets/review_*.py`，本文件只持状态 + 同名薄壳；
                        #        宏观(日历·图表)/微观(清单·编辑) 改为**可拖竖向分栏**并记住上次)
                         #   / trading_desk(**341** ★v6.12/P8 行情工作台——旧 market.py 661 已删除；
                         #        ✅ **1.23 版式收口收官（§7-B6 STEP 0–6）**：顶栏两行（周期/复权分段控件
                         #        + 分钟档位 + "最近使用优先" chips）+ 图标轨/五页分页面板/可折起
                         #        + 图表常驻读数条；**1375 → 345**（行为分居 `ui/widgets/desk_*.py`，
                         #        本文件只持状态 + 同名薄壳，既有断言零改动）)
                         #   / backtest_module + backtest(787 ✅ 1.22 拆分收官：编辑卡片+抽屉 / 摘要条 /
                         #         结果区 / 导出 / 运行流程 / 策略库 六块各归其位，本页只做装配与接线)
                         #   / **scan_view(164 ★v6.37/§7-B1/B2 STEP 4：M2 全市场筛选页**——状态全在页面
                         #         + 同名薄壳；版式/流程/渲染分居 `ui/widgets/scan_layout|flow|result`)
                         #   / **breadth_view(197 ★v6.38/§7-B1/B2 STEP 5：M3 广度统计页**——状态全在页面
                         #         + 同名薄壳；版式/流程/空态/图表分居 `ui/widgets/breadth_layout|flow|
                         #         result|chart`；与 M2 共用内核 + 会话缓存，一个引擎两种视图)
                         #   / data_manager(473 🗄数据管理, v5.8)
```

**体积红黑榜（v6.30 实测）· 口径与纪律：**
- **只给 ≥400 行的文件标行数（v6.16 用户拍板）**：行数的唯一用途是"提醒哪个文件快膨胀到
  不该再堆功能"，逐个文件维护精确数字只会定期返工（v6.15 那批实测已有 10+ 处对不上）。
  **<400 行的文件在 §4 一律不标数字**；要看体积请现测（口径 = **非空行**）。
- **业务文件 ≥400 行（1.26 收官实测降序）**：
  `ui/views/backtest.py 787`（1.22 拆分收官）>
  `core/backtest.py 495` > `ui/views/data_manager.py 473` > ⚠ `ui/widgets/desk_layout.py` **570 → 613**
    （v6.44 加 R7 副图换序 UI：按钮/工具条/列表；**登记不返工**，再长可把配方页 `build_formula_page` 拆出）>
  ⚠ `ui/widgets/annotation_layer.py 613`（v6.26 接绘制会话、v6.28 加"按形状拾取"、
    v6.29 接 `reshape`/`normalize` 两个钩子又越线；**处置不变**：场景 I/O（挂信号/落点换算/
    静音已有标注）可再拆进 `annotation_draw_session.py`）>
  ⚠ `data/annotations.py 595`（v6.29 又长：32 种类型常量三件套 + 语义档位 + 回归函数；
    **再加新类型前**，先把"kind 常量表"拆成 `data/annotation_kinds.py`）>
  ✅ `ui/widgets/annotation_shapes.py` **587 → 296**（v6.29 · §4 处置照做：`place_*`/`read_*`
    + 两个上下文对象 + 回归几何搬进 **`ui/widgets/annotation_layouts.py`(360)**，
    两个文件都回到 400 线内；`ui/widgets/annotation_decos.py 342` 也在线内）>
  `core/database.py 435` > `ui/widgets/backtest_result.py 432` > `ui/dialogs/bulk_download.py 416` >
  ⚠ `ui/widgets/breadth_flow.py` **443**（v6.39 越线后 v6.43 又长：幸存者偏差提示/指数图形透传；
    **登记不返工** —— 收口时可把"范围解析→体检接线"这对重复动作与 `scan_flow` 一起收进 `ReadinessFlow`）>
  ⚠ `ui/widgets/chart_host.py` **580**（v6.43 分界线拖动调高越线；新设施是宿主级可复用件（§9-U），
    再长可把 `enable_divider_drag`+eventFilter 拆成 `ui/widgets/divider_drag.py` 伴生件）>
  ⚠ `ui/widgets/scan_flow.py` **413**（v6.43 先选后扫/闸门/落位越线；**登记不返工**，
    再长可把"日期控件三件套（选择/落位/同步）"抽成伴生件）>
  ⚠ `data/akshare_feed.py` **462**（v6.46 §7-B10 `fetch_trade_calendar` 越线；本就是"行情源大杂烩"候选拆点，
    再加新源前先分文件）> `data/sync_service.py` **457**（v6.46 §7-B10 定稿守卫越线：
    `DAILY_SETTLE_HHMM`/`is_daily_bar_settled`/`_drop_unsettled_tail` + `refresh_one` 接裁尾；
    **登记不返工**，再长可把定稿守卫抽成伴生件）。
  ⚠ `core/cross_section.py` **655**（v6.43 又长：轴外落位/missing 诚实化；**处置不变**：
    新增优先另起模块）。
  ✅ `ui/views/trading_desk.py` **1375 → 345**（1.23 · §7-B6 STEP 6，**退出 400 线**）；
  ✅ `ui/widgets/backtest_panes.py` 395、`adaptive_axis.py` 396 也都在 400 线内
  （按 v6.16 口径不再标数字）。
- **验收脚本不参与"业务文件瘦身"**：`tests/smoke_chart.py 3676`、
  `tests/smoke_pages_overlay.py 3181`（总行数；**它们不是业务文件，别为了让数字好看去拆**）。
- ✅ **历史拆分叙事（`backtest.py` 1697→787 / `trading_desk.py` 1375→345 / §9-U + §9-L 收官 /
  v6.6–v6.15 行数涨落记录）→ 已搬 `docs/JIAN_ARCHIVE.md`「四、§4 体积红黑榜·历史条目」**
  （v6.35 · 照 §10-14"先搬走，再写新内容"）。**结论仍有效**：`ui/views/` 全部回到 400 线内；
  **新能力一律落到 `ui/widgets/*` 或 `data/*_store`**（§10-12）。
- ⚠ **`core/cross_section.py` 605（v6.34 新建即越线 · v6.36 又 +41：进度/取消钩子）**：
  已按「阈值/掩码 → 读数 → 结果 → 主入口」天然分段，但**没拆**（§4 口径：**不必为了行数返工，登记即可**）。
  ✅ 新模块 **`data/scan_store.py 247`** 与新增的 `CrossSectionWorker`/`JobGuard`（都在既有的
  `ui/workers.py 271`，未越线）正是这条纪律的示范：**新增另起模块，没往核心里堆**。
  STEP 6 收口时再按 `scan_filters`（阈值 + 逐行掩码）/ `scan_io`（读数）拆 `cross_section`。

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

- 分层：`tokens`(词法) → `parser`(递归下降→AST) → `runtime`(函数求值) → `program`(整段程序)
  → **`draw`**(绘图 IR 契约，v6.2/P1 新增：`COLOR_TABLE` + `DrawSpec`/`DrawData` + 属性校验)。
- 门面 `FormulaEngine`：`validate/parse/evaluate/signal`；报错分 `FormulaCompileError`/`FormulaEvalError`。
- 内置函数（16 个）：MA EMA SMA REF HHV LLV COUNT SUM IF EVERY CROSS BARSLAST ABS MAX MIN
  **COUNT_TRUE**；多输出内置 MACD(DIF/DEA/HIST,×2) 与 KDJ(K/D/J)；列别名 C/O/H/L/V；
  `=`/`<>` 走容差近似。
  - **`COUNT_TRUE(条件1, 条件2, ...)`**：逐日统计 N 个条件同时成立的数量（变参 1~99）。
    它是「条件组 Gate · 至少 N 个满足」的翻译目标：表达式恒定一行，任意条件数都不爆炸。
    （等效：`>=1` 即 OR，`>=条件总数` 即 AND。）
- 整段程序 **4 态**（v6.2 · P1）：`X:=...` 赋值、`X:...,COLOR...` 输出（属性**不再忽略** ——
  解析成 line/hidden 绘图规格，变量取值行为不变）、`STICKLINE/DRAWICON(...)` **绘图指令**
  （编译成 `DrawSpec`，求值产出 `DrawData`）；旧 `SKIP` 已移除。
- **属性尾巴要先摘掉再解析**（v6.5 · §9-Q-1）：`STICKLINE(...), COLORFF0000;` 是**合法写法**，
  顶层逗号之后的 `COLORFF0000` 是**绘制属性**、不属于表达式 —— 把整条语句直接送 `parse()`
  会让**存量已保存的函数当场报错**（真实事故）。
- **报错边界（v6.5 修订 v6.0 的"一律报错"）**：`STICKLINE/DRAWICON` 参数错 → 报错；
  已知但本期不实现的绘图函数（DRAWTEXT/DRAWBAND…）→ 登记 `kind='unsupported'` +
  **非阻断提示**（绝不 hard fail）；只有**完全不像函数调用**的语句才报错。
  绘图 IR 见 `draw.py`，纪律见 §11.5-14。
- 求值入口三枚（都走唯一的 `_run_programs` 循环，永不各写一遍）：`execute_programs`（只出变量，
  **行为与旧版逐位一致**，供检测/条件/指数门控）、`execute_programs_with_draws`（同一 EvalContext
  一遍同时出 `(变量, [DrawData])`，供渲染）、`execute_programs_with_draws_grouped`（v6.8：
  draws **按函数段分组**返回 —— 行情页"每段可选目标窗格"的引擎依据；
  ⚠ 各段仍共用一个变量池，**勿**按目标分组各跑一遍）。
- **多函数段共享执行（阶段A）**：`program.execute_programs(programs, df, params)` 让多段函数
  在【同一个 EvalContext】按序执行 ⇒ 共享变量池；后段可引用前段产出变量；同名后者覆盖，
  语义 = 各段文本以分号拼接成一段后执行，完全一致。`execute_program` 单段入口兼容保留。
- 缺参探测：UI 对全部函数段试运行，捕获"未定义的名称"→ 正则提取参数名 → 占位 5.0 复测
  （见 §7-B3）；`runtime._period` 对窗口类函数校验 `周期≥1`，非法给出友好错误而非裸抛。

### 5.3 产品决策与口径（禁止回归的既定结论）

- **A. 时间双轨制**：`trade_time` 永远纯日期；原生 `*_fill_time` 完整入库；
  用户「时间精度」偏好只控显示/排序（`preferences.time_precision`：DATE_ONLY/FILL_TIME），
  首次导入**强制选择**、流水页可随时切换。
- **B. 净额口径**：胜率/盈亏比/单笔极值/净值曲线/**盈亏筛选**一律用 `net_profit − commission`；
  毛利与手续费单列对照（实测净额胜率 45.2% vs 毛利 51.6%）。
  ✅ v5.13：流水页 / 复盘页的「仅盈利 / 仅亏损」筛选器已由毛利改净额（§9-O1 已修）。
  ✅ **v6.9：逐笔展示层也全部改净额**（§9-P1 收尾）—— 着色/正负号/标记色/高亮带方向
  一律经 **`core.utils.record_net_amount(record)`**（全站唯一取值口径，容忍
  Series/dict/TradeRecord + NaN），流水页盈亏列**列名改「净盈亏」并显示净额**
  （毛利 = 净额 + 右列手续费，Dashboard 仍单列毛利 KPI）。
  **至此"全站再无例外"首次真正成立**。新建任何"盈利/亏损"判定时，**必须**先调
  `record_net_amount()`，不要再手写 `net_profit - commission`（多处手写必然漂移）。
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

## 6. 已完成能力清单（**v6.37 起：逐模块全量核对已搬 `docs/JIAN_ARCHIVE.md`「六」**）

> **为什么搬走**：它本质是"**已完成**"的台账（§10-14 防漂移纪律③：**已完成的不再回改正文**），
> 且 13.4k 字符里大半是"当年怎么做的"叙事 —— 主文件逼近 100k 硬指标，按"先搬走，再写新内容"处理。
> **逐模块的 `[x]` 明细与验收数字**一律以归档为准；本文件只留**能力索引**（"这功能有没有" 30 秒能查到）。
> 新增能力：① 下表补一行要点；② 明细写 `docs/JIAN_HISTORY.md` 的版本行（**别在这里长肉**）。

| 模块 | 能力要点（现状） | 代码位置 |
|---|---|---|
| 交易流水 · 账户 | 交割单导入（CFMMC 解析 / 期货分月）+ 覆盖度体检 + 孤儿腿缝合 | `data/data_feed.py` + `feed_*` · `core/engine.py` |
| 市场行情 | 股票/期货 · 日/周/月 + 分钟 1/5/15/30/60 · 前复权/不复权 · 自定义公式叠加 · 32 种画线 · 配方库 | `ui/views/trading_desk.py` + `ui/widgets/desk_*` |
| 市场回测 M1 | 单股 LONG-only · 三档成交时点 + T+1 硬约束 · 阶段 B 风控离场器 · 策略库 / 对比 | `core/backtest.py` · `ui/views/backtest.py` |
| 复盘 | 日历 · 月度 · 时长分析 + 交易回放（双锚点）+ 清单/编辑卡（§9-U 可拖分栏） | `ui/views/review.py` + `review_*` |
| 数据管理 | 分区清单（行数/范围/体积/更新时间）+ 勾选删除 + 增量/全量 + 批量预下载 | `ui/views/data_manager.py` |
| **全市场筛选 M2** | 某一天的全市场横截面筛选：三态 KPI + 结果表（双击跳行情，超 2000 行截断说实话）· 粗筛漏斗（含换手率/市值）· **基准日先选后扫（日历自由选 + 轴外就近落位，v6.43）** · 缺数据扫描前二次确认闸门（v6.43）· 切日期零成本 · **就绪度体检 + ⬇补齐缺失**（v6.39） | `ui/views/scan_view.py` + `ui/widgets/scan_*` + `readiness_flow`（v6.37/39/43） |
| **广度统计 M3** | 逐日"有多少只满足条件"：广度家数**柱状/折线双视觉**（默认柱状+MA5 趋势线，家数刻度取整）+ 指数副图 x 联动（**折线/面积/K线/美国线四图形，按日对齐只画当前区间，v6.43**）+ **两窗格轴对齐 + 分界把手拖动调高**（v6.43）· **⚡增量到最新**（尾段续接，历史一天不动）· **⟳全量重算**（二次确认）· 区间切片零成本 · **就绪度体检 + ⬇补齐缺失**（v6.39） | `ui/views/breadth_view.py` + `ui/widgets/breadth_*` + `readiness_flow`（v6.38/39/43） |
| 基础设施 | parquet 分区数据湖 + SQLite + 偏好/配方/自选/标注（原子写）+ 自动更新检查 | `data/` · `core/` |
| **§6.5 远期** | **组合级多标的引擎**（指数择时 → 全市场挑股 → 资金分配）—— 见归档「六」 | — |

## 7. Roadmap：未完成项（按优先级与依赖重新分类）

### A 类 · 半成品闭环（有代码入口/雏形，缺最后一公里 —— 建议优先）
- **A1 [x] 行情涂鸦板持久化（✅ v6.10 由 §7-B3 的 P6 吸收并升级完成）**：
  旧的"内存趋势线"（`drawn_lines` 随重渲染清空、无落盘）已被
  `data/annotations.py` + `ui/widgets/annotation_layer.py` 取代 —— 三类标注、
  按 `(标的, 周期)` 持久化、**逐个独立删除**、坐标按日期锚定（不漂移）。
  复盘页复用（回放图上标注）属 P8 之后的事：API 已按 `(symbol, period, id)` 解耦，**只换调用方**。
- **A2 [x] 回测结果导出（✅ v1.36 图表能力补齐）** `ui/views/backtest.py` + `ui/widgets/backtest_export.py` + `ui/widgets/backtest_xlsx.py`：
  ✅ 导出菜单三项：📄 CSV 明细（**参数快照 + 逐笔成交**，不写逐日净值——看图靠 xlsx）、🖼 PNG 报告图、📊 **xlsx 内嵌真正的净值曲线图 + 买卖点标记**（openpyxl，打开即见图）。
  xlsx 三 sheet：「回测明细」+ 可见「净值曲线」（只放图）+ **隐藏「净值数据」**（逐日全量放隐藏表，主表不刷屏）；共同数据源 `build_daily_series(result)`（买卖点用成交日净值定位）。
  **明确不做**：结果删除 —— 用户判断"当前没有显式保存、结果会被覆盖，删除没有对象可删"。
  `StrategyStore.record_result` 仍是自动归档的缩略指标（同股对比用），不属于"可管理的结果集"。
- **A4 [ ] 回测结果历史存档（远期 · 由用户 v5.14 明确"找机会再做"）**：
  **为什么**：结果本质上是"易逝的"（同 策略×标的 每次回测静默覆盖旧缩略指标），
  用户迟早会问"上周那组参数跑出来的明细去哪了"。
  **设计要点（动工前先与用户对齐，勿直接照做）**：
  ① 每次回测生成一份**不可变存档**：`_last_meta`（配置快照，v5.14 已就绪）+
    `BacktestResult`（逐笔明细 + 净值）序列化到 `~/.jian_data/backtest_results/`
    （JSON 或 CSV，文件命名 = 时间戳 + 策略 + 标的 + 区间）；
  ② UI 新增「回测历史」列表（可参考「策略对比」页签的入口，或独立页签）：
    查看/复用参数（载入回编辑器）/打开明细，删除放这里但按 §10-10 做隔离 + 二次确认
    （此时"删除"才有明确对象 = 一份存档文件，可与"保存"配对）；
  ③ 若只想要"可复现"，也可只存档轻量 JSON（参数 + 函数文本）以便"一键重跑"，
     不必把整份净值曲线也存了 —— 先问用户要的是"复现"还是"留档"。
  **前置**：§6.3 的导出（v5.14）已把 `_last_meta` / `_compose_result_csv` 铺好路。

- **[x] A3 P0 数据管理页（v5.8 已完成）**：`DataLakeManager` 补删除/清点原语 +
  第 6 导航页 `ui/views/data_manager.py` + 批量预下载弹窗 `ui/dialogs/bulk_download.py` +
  同步门面 `data/sync_service.py`。
  **遗留（属 B1，非 A3 欠账）**：`scan_cache` zone 仍不存在 —— M2 横截面筛选落地时再建。

### B 类 · 市场回测扩展（**规格已于 2026-09-19 定稿** —— 见下方「§7-B1/B2 主案规格」）
- **B1 [~] M2 全市场单日横截面筛选（v6.31 立项 · **STEP 0–4 已完成** · 待施工：8 发版）**：
  `backtest_module.py` 的 `page_scan` **已换成真页面**。
  ✅ **STEP 1 已落地**：`core/cross_section.py`（**605 行**，越 400 线已登记 §4）——
  四态（命中 / 未命中 / **数据不足** / 被粗筛剔除）、粗筛漏斗（含 **换手率 / 流通市值**）、
  M3 逐日广度（**日期→整数索引 + 一次 `np.bincount`**）、uint8 缓存矩阵（`status_on(date)` 改日期秒回）。
  验收：`smoke_chart` 新增 **43 项**断言全绿，其中含 **"与 M1 口径逐字相同"的源码级护栏**。
  ✅ **STEP 2 已落地**：`data/scan_store.py`（**247 行**，**没往核心里堆** —— §4 的示范）——
  会话内存缓存：键**六样**（公式 / **粗筛阈值** / 标的域 / 复权 / **数据版本** / 快照列）、
  LRU 双闸（条数 + 字节）、`stats()` 占用可见可清、`clear()` 一键释放；
  **`asof` 不进键 ⇒ 切日期 / 换统计窗口零成本**（矩阵本来就是全日期的）。
  验收：`smoke_chart` **再 +23 项**，含 **"数据一变 ⇒ 键必变 ⇒ 必然不命中"的负向断言**。
  ✅ **STEP 3 已落地**：`ui/workers.py` 的 **`CrossSectionWorker`**（分块 + **两段进度** + 取消 +
  `job_id` 原样回包）与公共件 **`JobGuard`**（竞态守卫 §9-O5）；内核 `scan()` 收
  `progress` / `should_stop` 钩子（`DEFAULT_CHUNK=200`）。
  ★ **取消 = 抛 `ScanCancelled`，绝不返回半成品矩阵**（半个矩阵的占比全错且界面上看不出来），
  缓存也只落成功的结果。
  验收：`smoke_chart` **再 +12 项**（含**真并发**验证：旧任务回包被守卫丢弃、取消后缓存 0 条）。
  ✅ **STEP 4 已落地（v6.37）**：**M2 页** —— `ui/views/scan_view.py`（**164 行**，状态 + 同名薄壳）
  + `ui/widgets/scan_layout.py`（**327** 版式）/ `scan_flow.py`（**262** 流程）/ `scan_result.py`（**137** 渲染），
  全部 < 400 线。**范围三档**（我的自选 / 指数成分（异步走 `MarketSyncService`）/ 全 A 花名册）；
  **L1+L2+L0 常驻 ≤3 行**，粗筛阈值收进**抽屉**（样板 A）；
  **阈值⇄控件唯一换算处**（界面 亿元/% ⇄ 内核 元/小数，往返零漂移有断言）；
  **切日期零成本**（纯切片）且**非扫描基准日只显示状态**（不拿旧快照冒充，D3）；
  双击结果行 → 行情工作台（复用 `load_symbol`，**不另做看图器**）；
  新增门面 `DataEngine.roster_names()`（代码→名称，§9-H：UI 不碰 DatabaseManager）。
  验收：`smoke_pages_overlay` **396 → 419 项**（+23，含端到端真数据 5 只 0.13 s、
  **"非基准日数值列必须是 '—'"的负向断言**、常驻行 ≤3、阈值往返零漂移）；`smoke_chart` **667** 全绿。
  **主案已定稿**：**一个引擎两种视图**（M2 = 某日纵向取列 / M3 = 跨标的按日求和）+ **会话内存缓存**
  + **三态口径**；⚠ 早期写的"需 `scan_cache` zone"与"落盘面板 `kline_panel`"**均已被 STEP 0 实测取消**（B2 / B3）。
- **B2 [x] ⭐M3 全市场广度家数折线 + 指数叠加（v6.31 立项 · **✅ STEP 5 已落地 · v6.38/1.29**）**：
  `page_breadth` **已换成真页面 `BreadthView`**（`_ComingSoonPage` 占位类退役）。
  ✅ **交付内容**：`ui/views/breadth_view.py`（197）+ `breadth_layout`(238) / `breadth_flow`(390) /
  `breadth_chart`(165) / `breadth_result`(35)，全部 < 400 线（非空行口径）。
  **双窗格 x 联动**（B2 拍板：上下两窗格，不做真·双 y 轴；`ChartHost` + `adaptive_axis`）；
  **广度折线** = 家数 / 占比%（占比分母 = **有效样本**）+ **MA5 平滑**（可关）+ 末点标记 + 近5日迷你读数；
  **区间六档**（近3月→全部历史）= **纯切片零成本**（D3）；**⚡增量到最新**（D7：
  `scan_cached(incremental=True)` = `find_base` + `merge_tail` 尾段续接，**历史一天都不动**，
  ⚠ 引擎逐只路径下求值仍走全历史 —— 小范围秒级、全市场以回执实测为准，B3 复核）；
  **⟳全量重算** = 危险动作隔离 + `QMessageBox` 二次确认（§10-10）；
  **指数副图**读 `index_daily` 分区，缺数据**后台补拉一次**（`SingleSyncWorker` 走
  `MarketSyncService`，§9-H；失败只出声不连累主图）。
  验收：`smoke_chart` **+11 项**（增量合并 == 全量重扫**逐位一致**、历史逐位不动、touch 沿用原矩阵、
  标的集合变了诚实退化全量、Worker 增量通道）；`smoke_pages_overlay` **419 → 447 项**（+28，
  含 M3 公共面护栏 67 项、端到端真数据 5 只 0.15 s、双窗格 x 联动、区间零成本、增量/重算闸门、
  指数补拉链打桩）。
- **B3 [x] ⭐公式统一绘图（P0 · v6.0 定稿）** —— ✅ **P0–P8 已全部落地**
  （v6.2 → v6.12，含 §7-B4 坐标轴自适应 v6.15）。完整主案见下方「§7-B3 主案规格」；
  ⚠ 该主案正文里"现状（待消除）"那段已过期，**保留作历史记录**（真实状态看本条与本文件顶端）。
- **B4 [ ] P1c 回测进阶（部分）**：结果长期入库已有雏形(A2)，缺 复用 `TradeAnalyzer` 绩效维度
  与每回合明细的持久化侧写。
- **B5 [x] ⭐回测成交真实性（v6.17 立项 / v6.18 落地 / v6.19 发版）**：**P0 已完成**
  = 成交时点三档（次日开盘 / 当日收盘 / 触发式条件单）+ **T+1 硬约束** + 同根不重建仓，
  用户手动实测通过；**P1/P2 仍挂起**（账户+容量+成本 / 盘中即时成交 —— ⚠ **不许顺手做**）。
  完整规格、实测证据与验收断言见 **§7-B5 主案**。用户口径：**宁可变难看，也要真**。
- **B6 [x] ⭐行情工作台版式收口（v6.21 立项 → v6.22 收官 · 用户 2026-09-16 拍板）**：
  **结构 = 样板 A 骨架 + 配色 = 现状（B 语言）**；⚠ **深色主题整体推迟**（用户拍板
  "放到后面软件功能实现得差不多了再统一去做"）——本轮一处深色都没加。
  **STEP 0–6 全部 ✅**（护栏/基线 → 样式公共件 → 读数条 provider → 顶栏两行+分钟档位 →
  左栏图标轨+折起+chips"最近使用" → 读数条接线+回执一行化 → 拆分收官），详见 **§7-B6 主案**；
  验收：`smoke_chart` 356 → **423**、`smoke_pages_overlay` 180 → **255**、真实联网端到端复跑、
  离屏截图人眼核验、全仓 compileall；`trading_desk.py` **1375 → 345**（§9-L 体积债同批还清）。
  样板存档见 `design/1.23-trading-desk-ui/`。
- **B7 [x] ⭐行情工作台**侧边栏**重设计（✅ 已由 §7-B8 / `1.24` 落地：A 手风琴 + 自选分组 + 拖拽排序 + 配方库收编；与 B8 合并收官）**：
  用户原话："**把行情页里的侧边栏 UI 再次重新设计**，现阶段的侧边栏功能虽然整合过去了，
  但是 **UI 设计完全混乱和用户不友好**，必须在后续重新设计**侧边栏展开后的 UI 排版样式**。"
  **现状（量出来的，§7-B6 交付后的真实形态）**：左栏 = 图标轨（52px）+ 372px 定宽面板（5 页），
  每页都是"**小标题 + 控件平铺**"：① 五页共用同一个 372px 宽度（`PANEL_DEFAULT_WIDTH` 硬编码），
  页与页之间**只有位移没有层级**；② 自选页 = 标题 + **固定 150px 高**的列表 + 一行 4 个图标按钮
  （★🗑⬆⬇ 语义弱）+ 灰字说明；③ 图层页 = 5 个复选框平铺（"主图叠加 / 附图"两组靠间距分隔，
  **没有分组容器**）；④ 公式页 = 4 个等高按钮纵向堆叠，看不出**主次**（哪个是主操作）；
  ⑤ 数据页只有一行回执 + 说明，**大半屏是空的**；⑥ 折起态只剩图标轨（页名只靠 tooltip）。
  **下一步（按本项目惯例：先方案后动手）**：先出 **N 套侧边栏版式样板**（HTML 可交互原型，
  配色仍沿用现状白卡 + `#1976D2`，深色主题仍推迟）→ 用户挑一套 → 再写施工步骤（每步独立可验收）
  → 才动代码。⚠ **本轮不许顺手改**（§7-G 纪律）；⚠ 依赖 §7-B6 已固化的"护栏 + 同名薄壳"，
  改版**只能换容器与排布，不许改控件名/方法名**（`smoke_pages_overlay` 的迁移护栏会立刻红）。
- **B8 [x] ⭐`1.24` 侧边栏重设计（A 方案）+ 现有功能改进（v6.24 立项 · 用户 2026-09-17 拍板 · ✅ 除 R4 组合配置=远期独立立项、R12 数据页暂缓外已全部完成；R7 副图换序于 v6.44/1.34 收尾）**：
  已采纳 **A『手风琴卡片』**；用户同时要求**功能先行、版式收尾**
  （原话："对于现有里面的功能我们一起改好后再做"）。
  共 **R1–R12** 十二条（分组标签 / 两条添加入口 / 组合当日涨跌 / **组合配置**新栏目 /
  删图层页并整合出**配方库** / 配方主图·副图可视化分类 / **附图可排序** /
  **附图纵轴对齐** / 附图数量仍由 chips 控制 / 画线类型**图标+数字** / 支持 30+ 类型 / 数据页暂缓）。
  ✅ 其中 **R7（副图可排序：底层 API + UI 入口 + `sub_order` 持久化 + 拖拽 · v6.44/1.34 完成）/ R8（纵轴对齐✅）** 两处代码级真实缺陷均已修复；
  ⚠ **R4 组合配置 = §6.5「远期」的组合级多标的引擎**（勿新开平行债）。
  样板与路线图：`design/1.24-desk-sidebar-ui/`（`a2-accordion.html` + `ROADMAP.md`）。
  完整条目、施工顺序与待拍板问题见下方 **§7-B8 主案规格**。
- **B9 [x] ⭐画线工具「在图上点出来」+ 通道语义修正 + 最后 5 种（v6.26 · 用户 2026-09-18 实测反馈 ·
  **7 条拍板 + 已施工完成**）**：① 2 点以上工具不再"先生成默认线再拖"，改**用户依次点锚点**
  （橡皮筋预览 + Esc/右键取消 + **画完自动回浏览模式** + 点到已有标注也算落点、允许重合）；
  ② **平行通道从"四角可变形多边形"修正为"基线 + 填充带 + ⇕ 宽度手柄 ⇒ 两条严格平行的线"**；
  ③ **目录 32 种全部可画**（回归通道 / 波浪降级 / 头肩降级 / **甘氏扇形随缩放重算** / 斐波弧）。
  完整方案、拍板记录与施工产出见下方 **§7-B9 主案规格**（§8 v6.26 行）。
- **B10 [x] ⭐数据新鲜度：日线收盘定稿守卫 + 扫描页「更新到最新」引导（v6.45 立项 · **§7-B10 全案已收官 v6.47/1.35 · 用户 2026-09-22）**：
  ✅ **M1（v6.46）**：定稿守卫（STEP 0/1）+ 真交易日历件（`data/trade_calendar.py` + `fetch_trade_calendar` + `CalendarWorker`）+ **M1 回测区间默认终点修复**（默认=最近已定稿交易日 / 滞后自动联网补 / 补不到回退有数据那天并出回执，推翻原 F「不引日历」）。✅ **M2/M3（v6.47）**：`ReadinessFlow` 新增 `update_latest()` 一键「⬆ 更新到最新」（与“补齐缺失”**合并**，整批当前范围增量）+ 滞后提示（`start_calendar_fetch`/`trading_days_between`/`format_stale`，真日历）+ M2 基准日诚实化（`lbl_asof_hint`）。完整规格见下方 **§7-B10 主案规格**。
  两个真实问题（用户实测）：① **盘中同步会把“今天那根未完成 bar”永久冻结进日线库**
  （`_is_fresh` 末日==今天即跳过 + 增量起点 last+1 永不回补 → 半根 bar 再也刷不掉，污染收盘口径的回测/扫描）；
  ② **M2/M3 页面没有“把数据更新到最新交易日”的入口**（“补齐缺失”只补从没下过的股票），
  且基准日被硬收紧到本地最新、未来日灰掉无解释无桥。
  **拍板**：问题2 走**方案A（严格：未收盘定稿的当天 bar 一律不写进日线库）**；问题1 **三条都做**
  （更新动作 + 滞后检测 + 基准日诚实化，互相印证）。完整规格与 STEP 0–5 施工顺序见下方 **§7-B10 主案规格**。

### C 类 · 体验升级（有明确规格，尚未动工）
- **[x] C1 Dashboard GitHub 风格日历热力图**（v5.7 已完成）`ui/widgets/calendar_heatmap.py` +
  `ui/views/dashboard.py`：整年 53×7 网格（周一为首行），颜色 = **当日净额**
  （绿盈红亏，5 档分位），灰色 = 无交易/净额为 0；支持年份下拉切换（默认停在最近有数据年）、
  年度摘要（交易日数 / 盈利天数 / 亏损天数 / 年度净额）、悬停 tooltip（日期+净额+笔数）。
  **注意**：复盘页的「月历热力图」是另一个东西（单月 6×7、可点选交易），勿混淆、勿互相替换。

### D 类 · 远期（设计预留，暂不排期）
- **D1 [ ] Python 脚本沙箱（AST 白名单）第二作者模式**：接入点预留在 `core/formula`。
- **D2 [ ] 期货侧回测**：`BacktestEngine` 明确 LONG-only/A股，做空与期货为远期。
- **D3 [x] `kline_min` 高频分时数据湖 zone** —— ✅ **v6.21 落地（§7-B6 STEP 3a/3b）**：
  分区启用 + 按档位分键（`600519@5m`）+ 新浪分钟源（1m/5m/15m/30m/60m，
  实测深度 9/42/124/247/493 个交易日）+ 行情页一级/二级分段控件。
  ⚠ **不接批量预下载**（避免高频轰炸）；分钟只有**真实价一种口径**（实测 adjust 不生效）。
- **D4 [ ] 时点成分股（point-in-time，治幸存者偏差）**（v6.43 登记 · 用户 2026-09-21 提出）：
  现在 M2/M3 的成分股范围永远是**当前快照** —— 扫历史基准日时用的是"今天的名单"
  ⇒ **幸存者偏差**（后来被调出/退市的弱势股不参与，结果系统性偏乐观）。
  **实测结论（v6.43）**：三个候选接口都**没有入选/剔除日期列**（官网只给当日快照+日期列，
  同花顺只给入选日期无退出日期且当前表只含在册股）⇒ 当前数据源做不出真时点。
  **已做的缓解**：名单带快照日期上界面；基准日早于快照 ⇒ 回执自动提示幸存者偏差（两页）。
  **将来做法（动工前先与用户对齐）**：接中证指数官网的历史调样公告（半年/季度公布调入调出），
  建 `~/.jian_data/constituent_history.json`（指数 → 按生效日排序的调入调出事件流），
  按基准日回放事件流得时点名单；花名册名称的"历史 ST 不可追溯"（D5 同款）一并解决不在本项范围。

### §7-B1/B2 主案规格：M2 全市场横截面筛选 / M3 广度统计
（v6.31 立项 · 用户 2026-09-19 拍板 · **设计定稿，待按 STEP 施工** · 原型 `design/1.27-scan-breadth-ui/`）

#### A. 用户拍板记录（2026-09-19 · **不得擅自回退**）

| # | 议题 | 拍板结论 |
|---|---|---|
| 1 | **主轴** | ✅ 采纳「**派生扫描面板 `kline_panel` + 两段式漏斗**」，**不做**"逐只读文件直接算" |
| 2 | **复权** | ✅ **一次到位**：面板存「**不复权 OHLCV + 复权因子**」，**指标按用户需求复权**（支持 不复权 / 前复权 / 后复权） |
| 3 | **面板可见性** | ✅ **方案 B**：🗄 数据管理 页左栏**分两组** —— 「行情源分区」（现有 9 项）/「**派生缓存**」（`kline_panel`）；**同一套明细与勾选删除**，**底部动作按类型切换** |
| 4 | **缓存层级** | ✅ **L1 先、L2 后置**（用户授权由我决定）：先只做「面板缓存」；STEP 5 跑通后实测**重复扫描耗时**，**> 2s 才做 L2**；`scan_store` 预留 L2 位 |
| 5 | **粗筛阈值** | ✅ **多阈值 + 内置默认 + 全部可调**（开关 + 数值框 + 「↺ 恢复默认」）；**换手率先用「相对量」替代** |
| 6 | **口径铁律** | ✅ **三态**：命中 / 未命中 / **数据不足（未知）** —— 数据不足**绝不用 0/False 冒充**，广度必须同时显示"有效样本数" |

> ⚠ **表中第 1 / 2 / 3 条已被 STEP 0 实测改写，并经用户 2026-09-19 重新确认**（落盘面板 → **会话内存** ·
> 复权"一次到位" → **本轮前复权单口径** · 方案 B 分组 → **取消**）；**结论一律以 D 节为准**，依据见 **B2**。
> 第 4 / 5 / 6 条不变（L1 先 L2 后 · 粗筛多阈值可调 · 三态铁律）。

#### B. 现状实测（立项依据 · 量出来的，不是感觉）

| 事实 | 数字 / 来源 |
|---|---|
| 全市场标的 | 约 **5400 只**（`engine.list_stock_symbols()` / `market_symbols` 花名册） |
| 数据湖形态 | **按标的存 parquet**（`kline_daily/<symbol>.parquet`）—— 为"看一只"优化，对"看一列"最差 |
| "看一列"的代价 | **5000+ 次文件打开**（IO 会成为主要成本，而不是计算） |
| `scan_cache` / `kline_panel` | **均不存在**（`market_db.zones` 现有 9 分区，无派生层） |
| 估值 / 财务数据源 | **未接入**（`valuation` / `fin_report` 是预留空分区；`akshare_feed` 无对应抓取）⇒ **估值 / 财务类筛选本轮不做**。<br>⚠ 本条立项时附带的推论"⇒ 换手率也做不到"**已被 P1b 实测推翻**：`turnover` / `outstanding_share` **本就在分区里**（见 **B2 第 2 条 / D5**） |
| 现有可复用件 | `execute_programs_with_draws`（多段共享变量池）· `condition_gate`（→ 单行 `COUNT_TRUE` DSL，**已是纯转换**）· `backtest_flow` 的数据就绪链模式 · `SyncWorker`/`SingleSyncWorker` · `MarketSyncService` · `ChartHost`（多窗格 x 联动）· `adaptive_axis` · `INDEX_PRESETS`(29) · `fetch_index_constituents` |
| M2/M3 占位 | **均已退役**：`page_scan`（M2）= v6.37 真页面 `ScanView`；`page_breadth`（M3）= v6.38 真页面 `BreadthView`（STEP 5） |

#### B2. STEP 0 实测（2026-09-19 · 探针跑完即删 · **数字表已搬 `docs/JIAN_ARCHIVE.md`「五」，v6.43**）

> ✅ **本节的 3 条改写已于 2026-09-19 获用户确认**，并已落到 **D1 / D2 / D3 / D5 / D6 / D8**；
> 探针数字表（P1a/b/c · P2/P2b · P3a/b/c）、P4 端到端标杆表（外推 ≈26 s / 缓存命中 0.03 ms）、
> 两条新发现（逐行累加是性能真凶 → `np.bincount`；漏斗只砍 3.8% 不能救性能）、
> STEP 1 复核（368 只 2.60 s ⇒ 外推 ≈38 s，差额在 per-symbol 固定开销）全部在归档；
> 后续决策：STEP 6 复核（真机 7.85 ms/只 ⇒ ≈42 s）**已接受引擎路径，STEP 7 暂不排期**（见 G 节）。
>
> **改写的三句话**（结论以 D 节为准，逐版叙事见 `docs/JIAN_HISTORY.md` v6.33）：
> ① **IO 不是瓶颈** ⇒ "落盘面板"首要理由不成立 → **会话内存**（D1 / D3）；
> ② **真换手率 / 流通股本本来就有**（覆盖 362/368）→ **可用**（D5）；
> ③ **复权只能单口径**（`kline_daily_raw` 只有 1 只）→ 本轮**只上前复权 + 界面明示**（D8）。
> 两条数据健康问题（分区列结构不一致 / `shift` 跨空洞）见 **§9.1 / §9.2**。

#### C. 核心设计：**一个引擎，两种视图**

> 对每只股票，把「函数段 + 条件 Gate」在**它自己的日线序列**上跑一遍 ⇒ 得到**逐日布尔信号**。
> **M2 = 某一天纵向取一列**（命中清单）；**M3 = 跨标的按日横向求和**（家数）。
> ⇒ **绝不写两个引擎**；缓存也只有一份（M3 直接复用 M2 的中间结果）。

#### D. 规格（分层）

**D1 · 数据底座 —— ~~派生面板 `kline_panel`~~ ⇒ 直接用原始分区（v6.33 改写 · 见 B2）**
- **【改写理由】** P1 实测证明 **IO 不是瓶颈**（全市场 `dataset` 一次扫 ≈2.6 s；列投影只省 4%；
  row group 全 = 1 ⇒ 尾部窗口无收益）⇒ **落盘派生面板的首要理由不成立**，**取消该层**。
- **做法**：扫描时按需读 `kline_daily`（`pyarrow.dataset` 一次扫 / 或按标的按需读）；
  **不落盘、不进 `market_db.zones`、不改数据管理页结构**（省掉 430 MB 与分组改造）。
- **读列纪律（P1b 实测 · §9.1）**：分区**列结构不一致**（东财兜底透传中文列各 1 只；期货列 5 只）
  ⇒ **按"列是否存在"裁剪 + 缺列走三态**，**禁止假设 schema 统一**。
- **数据充分性**：缺数据 = 该标的**没有那一行**（不是 NaN 行）⇒ 三态由"标的的有效区间 + 有效行数"判定。

**D2 · 计算内核 —— `core/cross_section.py`（纯函数 · 零 UI · 零网络）**
1. **粗筛漏斗**（便宜列，见 D5）→ 候选集；
2. **默认路径 = 引擎逐只**（`execute_programs`，一次编译、逐标的求值）：
   - **口径与 M1 单股回测天然一致**（同一引擎、同一"逐标的自身序列"语义）；
   - P3 实测 **1.60 ms/只 ⇒ 全市场 ≈8.6 s**（可接受）；
3. **可选"性能档" = 宽表向量化**（P3 实测 0.409 ms/只 ⇒ ≈2.2 s，仅 **4×**）：
   - ⚠ 必须处理 **`shift/REF/CROSS` 的跨空洞语义**（P3c/§9.2）：宽表按**全局交易日历**对齐时，
     标的缺数据日会被 `shift(1)` 跨过，与"逐标的序列"在边界不一致（实测 **4/4022 ≈ 0.1%**）；
   - **启用前提**：① 用"**按列跳 NaN** 做 shift"（成本 ≈0.5–2 s/全市场，可接受）或
     显式声明口径；② 必须有**逐位一致断言**（对拍引擎路径）。
   - ⇒ **先做对（引擎逐只），再做快（向量化）**：本轮只交付引擎路径，向量化留作 STEP 6 后的可选优化；
4. 产出 **三态矩阵/摘要**：命中 · 未命中 · **数据不足**（+ 有效样本数）+ 可选"关键变量快照"；
5. **M2** = 取指定 `date` 一行；**M3** = 沿 `date` 轴求和（除以**有效样本数**得到占比）。

**D3 · 缓存 —— `data/scan_store.py`（v6.33 改写为**会话内存** · v6.35 落地并校正键）**
- **只缓存"结果"，不缓存"价量"**：会话内保存**逐日信号布尔矩阵**（`dates × symbols`）
  + 数据充分性掩码 + 关键变量快照；
  内存量级 = `4060 × 5400 × 1 B ≈ 22 MB`（bool）—— **比缓存在价量宽表（≈500 MB）省 20 倍**。
- **键 = 六样**（少一样 = 静默陈旧）：公式指纹（忽略注释 / 空白 / 大小写）· **粗筛阈值** · 标的域 ·
  复权口径 · **数据版本** · 快照列。
  ⚠ **v6.35 校正三处**：
  ① **粗筛阈值必须进键** —— 它决定四态里的「**被粗筛剔除**」桶；若不进键，用户改了阈值、界面却还在
     展示旧分桶 ⇒ **静默陈旧**（原 D3 漏了这条，**这是本轮自己抓出来的**）。
  ② **命中边界要说清**：`asof` 不进键（矩阵本来就是全日期的）⇒ **切日期 / 换统计窗口 / 重开同一视图
     = 零成本**；而**改粗筛 / 改公式 / 改标的域 = 必须重扫**（诚实告知 + 进度条，不假装能"重放"）。
  ③ **使用纪律**：命中时 `result.status / counts / snapshot / detail` 都是"**扫描时那个 `asof`**"的产物
     ⇒ **切日期后一律走 `status_on(date)` / `counts_on(date)`**，别读那几个字段。
- **L2（落盘结果缓存）**：**后置**，只在实测"重复扫描仍慢"时才做；
- ★ **失效必须含"数据版本"**（分区 mtime / `get_latest_date` / 行数指纹）—— **不能只看公式哈希**，
  否则"新下载了数据但不重算" = **静默陈旧**（违反 §5 / §10 铁律）。**做进键里**还有个好处：
  结构上就不存在"忘了检查是否过期"这种漏（`data_version` 一变 ⇒ 键就变 ⇒ 自动不命中）。
- ✅ **STEP 4 决策项已定（v6.37）**：M2 页选 **(a) 切日期后只显示状态**，数值 / "为什么"明细
  **只在扫描基准日**提供；界面脚注明示"本日只显示状态"，且冒烟有**负向断言**
  （非基准日数值列必须是 '—'，**绝不拿旧快照冒充当日**）。
  理由：② 要 **175 MB** 常驻内存，且"用户选中的列"会随需求漂移；
  ①的体验缺口（切日期看不到当日价格）后续可用「⟳ 重扫该日」（= `force=True`）按需补。

**D4 · 线程 —— `ui/workers.py` + `CrossSectionWorker`（v6.36 已落地）**
分块 + 进度 + 取消 + **竞态守卫**（§9-O5）。**UI 不卡**；线程仍只在 `ui/workers.py` 定义（§9-O2）。
- **分块 / 进度**：内核 `scan()` 收 `progress=f(done,total,note)` 与 `should_stop=f()->bool`，
  **每 `chunk`（默认 200）只**报一次进度、轮询一次取消 —— 回调本身不成为开销。
  进度**两段**：先 `(0, 0, '读取日线分区')`（此时还不知道总数），再进逐标的计算段（`total` 才是真总数）。
- **取消**：`cancel()` ⇒ 内核在块边界抛 **`ScanCancelled`** ⇒ 工作线程回 `finished(job, None)`。
  ★ **绝不返回半成品矩阵** —— 半个矩阵的命中家数 / 广度占比全错且界面上看不出来；
  用**异常**而不是"部分结果"，让调用方在**类型层面**无法把半成品当成品（缓存也只落成功的）。
- **竞态守卫**：`job_id` **原样回包**，页面用公共件 **`JobGuard`**（`next()` 取号 / `accept(id)` 判定）
  —— 把 `bulk_download._cons_token` 那套手写判据收成一处（§11.5-11；该页**择机**改用它）。
- **命中会话缓存时不进计算循环**（切日期 / 换窗口走这条）⇒ 连进度信号都不会有。

**D5 · 粗筛阈值（内置默认 + 全部可调 + 「↺ 恢复默认」）**

| 阈值 | 默认 | 来源 | 状态 |
|---|---|---|---|
| 成交额 ≥ | 5000 万元 | 日线 `amount` | ✅ |
| 价格 ≥ | 2 元 | 日线 `close` | ✅ |
| 有效数据 ≥ | 250 个交易日 | 日线行数（≈上市时长） | ✅ |
| 非停牌 | 开（`volume > 0`） | 日线 | ✅ |
| 剔除 ST / 退市 | 开 | 花名册名称含 `ST`/`退` | ⚠ 只能按**当前**名称过滤，历史 ST 不可追溯（界面如实标注） |
| 剔除一字板 | 开 | `high == low` | ✅（与 §9-V-3 一字板话题同源） |
| 涨跌幅区间 | 不限制 | `C/REF(C,1)-1` | ✅ |
| **换手率 ≥** | 不启用 | 日线 **`turnover`**（**分区里已有**！小数口径：0.0093 = 0.93%） | ✅ **可用**（v6.33 实测修正；展示按用户量纲 **×100 为 %**） |
| **流通市值 ≥** | 不启用 | `close × outstanding_share` | ✅ 可用（`outstanding_share` = 流通股本(股)） |
| 相对量 ≥ | 不启用 | `V ÷ MA(V,20)` | ✅ 保留（与换手率互补：一个看"自己比过去"、一个看"盘子比"） |

> ⚠ **`turnover` / `outstanding_share` 是"源透传列"**（不在 `OHLCV_COLUMNS` 常量里，属**隐性依赖**，见 §9.1）：
> ① **东财兜底源没有这两列** ⇒ 该标的这两项**一律记「数据不足」**（**绝不当 0**，否则换手率过滤会误杀一片）；
> ② 实测覆盖 **362/368（98.6%）** ⇒ 界面的"有效样本数"**必须把"该列缺失"也算进去**。

**交互规范**：每项 = **开关 + 数值框**（关掉即不参与漏斗）；**单位走用户量纲**（`5000 万元`，不写 `50000000`，§10-10）；
抽屉底部固定 **「↺ 恢复默认」**（§7-B8 R16 同款）；改动实时反映到摘要条的 `🎚 粗筛 N 项` chip。

**D6 · 与「🗄 数据管理」的联动（互利共赢 · 5 条硬规范）**
> 核心：**"扫描需要什么"变成数据管理的一个预设；"数据管理的下载/体检"变成扫描的一行回执**；**两边只有一份实现**。
> ⚠ **v6.33 改写**：原第 3 条"面板按方案 B 分组呈现"**已随 D1 取消**（不再有派生分区要管）；
> 数据管理页**结构一个字都不动**，"扫描就绪"这件事改由下面第 2 条的**下载预设**承担。

1. **就绪度体检（双向唯一口径）**：开跑前算 `已就绪 N/总 M`、缺口清单、区间是否够（含公式最小历史长度）、
   数据健康（**复用 §9-V 的非正价 / 量纲接缝判据**）+ **「补齐缺失（增量）」**按钮（后台 = 现成 `SyncWorker`）。
2. **反向预设**：`bulk_download` 新增 **「全市场扫描就绪」**（全A + 起点 + 复权，**也是将来备齐
   `kline_daily_raw` 的入口**），一键备齐底座。
3. **增量语义共用**：两页**同用** `fresh_within_days = 0`（末日==今天才算最新）、"空增量 = 已最新不是失败"
   ⇒ **杜绝"管理页说最新、扫描页说缺数据"**。
4. **下载顺序由"扫描损失"驱动**：缺口清单带优先级（按成交额降序）⇒ 广度先接近真实。
5. **问题清单回流**：读不出 / 校验不过的标的**回写数据管理的问题清单** + 「重新全量下载该只」入口，
   **不在扫描页静默跳过**（§9-V 护栏的自然延伸）。

**D8 · 复权口径（v6.33 定稿）**
- 本轮**只用「前复权」单口径** = `kline_daily` 现成数据（覆盖 98%+）且**与 M1 单股回测同口径**；
  界面**必须明示**"本次扫描口径 = 前复权"（口径唯一直说，§5.3）。
- **原因**：`kline_daily_raw`（不复权）**只有 1 只** ⇒ 复权因子（qfq ÷ raw）**算不出来**（B2 第 3 条）。
- **后续项**：把 raw 分区备齐（入口见 D6 第 2 条）后，再开「不复权 / 按需复权」；
  **在具备之前，界面上不许假装支持**（宁可少一个选项，也不要一个没跑通的选项）。

**D7 · M3 的天然增量**
`breadth[date]` **只依赖 ≤ date 的数据** ⇒ `⚡ 增量到最新` **只算最后一天**（秒级）；
唯一例外 = 数据被修订 / 换了复权口径 ⇒ **「⟳ 全量重算」**（危险动作：隔离 + 二次确认）。

#### E. UI 规范（照 `design/1.27-scan-breadth-ui/index.html` 第四节）

- **版式分层（§10-14）**：页签（沿用现有 `backtest_module` 壳，只换占位页）→ **L1 操作轴**（统计范围 · 日期/区间 · 复权，**1 行**）→ **L2 摘要条**（配置 chips + **数据就绪回执** + 主按钮，**1 行**）→ **L0 结果区**（吃满）→ **L3 配置抽屉**（**覆盖层，不动主区高度**，§11.5-26）。**常驻 ≤3 行**。
- **★ 三态语义**：`命中`（主色实心 pill）/ `未命中`（灰 pill + 行文字变浅）/ **`数据不足`（橙 pill + 计数显式）**。
- **口径必须印在标题上**：`📊 广度（全A · 剔除ST · 上市>250日 · 有效 4821/5390 · 不复权）`。
- **术语人话化（§10-10）**："横截面"→**"某一天的全市场筛选"**；"广度"→**"每天有多少只满足条件"**；"样本口径"→**"统计范围"**；"scan_cache"→**"扫描缓存"**。
- **回执一行化**：`扫描 2317/5390 · 命中 96 · 失败 2 · 用时 1.8s`（详解进 tooltip，§7-B6 STEP 5 同款）。
- **三种空态都给下一步动作**：未就绪 → 「补齐缺失」；无行情 → 「去数据管理」；失败 → 「重试 / 查看原因」。**禁止静默**。
- **双击结果行 → 行情工作台**（复用 `load_symbol`）—— **不另做看图器**。
- 配色沿用现状（`#1976D2` / 涨 `#2E7D32` / 跌 `#C62828` / 警示 `#E65100`），**深色主题继续推迟**。

#### F. 影响面（动代码前先看这 5 条 · **v6.33 已按"面板取消"修订**）

1. **数据管理页结构一个字都不动**（**不新增 zone、不改 `ZONE_ORDER` / `SYNCABLE`**）—— 只加
   **「全市场扫描就绪」下载预设**（D6 第 2 条）；"扫描就绪度"是**扫描页自己算的只读体检**。
2. **`backtest_module.py`** 只换占位页 —— M2 已换（v6.37）、**M3 已换（v6.38，占位类 `_ComingSoonPage` 随之退役）**；
   **新能力一律落新文件**（`core/cross_section.py` / `data/scan_store.py` / `ui/views/scan_view.py` /
   `breadth_view.py` / `ui/widgets/scan_*` / `breadth_*`）—— 已照做：M2 分居 `scan_layout / scan_flow / scan_result`，M3 分居 `breadth_layout / breadth_flow / breadth_result / breadth_chart`。
3. **`ui/workers.py`** 新增 `CrossSectionWorker`（线程仍只此一处定义，§9-O2）。
4. **读数纪律**：读 `kline_daily` 必须**按"列是否存在"裁剪**（§9.1：分区列结构不一致、存在源透传列），
   缺列 ⇒ 走**三态「数据不足」**，**禁止假设 schema 统一**。
5. **冒烟脚本**：新页面要进 `smoke_pages_overlay` 的迁移护栏与页面断言；新写 `~/.jian_data/*`
   要进防污染自检；**列存在性**（`turnover` / `outstanding_share`）要有断言钉住（§9.1）。

#### G. 实施步骤（每步独立可验收 · 一 commit 一步）

- **STEP 0 ✅（已完成 · 零业务代码）**：**探针实测 + 结论回填** —— P1（IO）/ P2（载入与内存）/ P3（计算层 + 一致性）
  已跑完（数字见 **B2**），**P4（端到端标杆）为收尾项**。探针**跑完即删**。
- **STEP 1**：`core/cross_section.py` + 单测（合成数据：**三态正确 · 粗筛生效（含换手率/流通市值）·
  命中矩阵逐位可验**；主路径 = 引擎逐只；**"数据不足绝不计成未命中"** 的负向断言）。
- **STEP 2 ✅**：`data/scan_store.py` —— 会话内存缓存（状态矩阵 **22 MB** / 键**六样** / **数据版本失效**
  / LRU 双闸 / 占用可见可清），**无落盘、无新分区、数据管理页结构不动**（D1 / D3）。
- **STEP 3 ✅**：`CrossSectionWorker` + `JobGuard`（分块 / **两段进度** / 取消抛 `ScanCancelled` /
  `job_id` 回包 / **竞态守卫**），内核加 `progress` / `should_stop` 钩子。
- **STEP 4 ✅**：**M2 页**已落地（`ui/views/scan_view.py` + `ui/widgets/scan_layout|flow|result`；
  范围三档 = 自选 / 指数成分（异步）/ 全 A；小范围端到端 **5 只 0.13 s**）。
  ⚠ **"真机全 A 的重复扫描耗时"与"是否做落盘 L2"留待复核**（STEP 6 前置，外推见 B3 的 STEP 1 复核）。
- **STEP 5 ✅（v6.38 / 1.29 已落地）**：**M3 页**（复用会话缓存 + 指数副图 x 联动 + `⚡增量到最新`
  + `⟳全量重算` 闸门）—— 交付与验收见 **B2 条目**。⚠ 施工中如实登记的一条：D7 的"增量只算最后一天
  （秒级）"在**引擎逐只路径**下只对**小范围**（自选/指数成分）成立 —— per-symbol 固定开销主导
  （B3 复核），全市场增量耗时 ≈ 全量重扫，以回执实测为准；真秒级要等 STEP 7 宽表向量化档。
- **STEP 6 ✅（v6.39 / 1.30 已落地）**：**联动收尾** —— ① **就绪度体检**（D6-1：`data/readiness.py`
  只读 footer 四分类 + `ReadinessWorker` + `ReadinessFlow` 两页共用控制器：范围就绪后自动体检 →
  回执一行「就绪 N/M · 未下载 X · 历史不足 Y · 文件损坏 Z · 本地最新」→ 缺口可见可动作）；
  ② **⬇ 补齐缺失**（missing 才补，partial 如实解释"补不齐"；`SyncWorker` 温柔抓取可中断 +
  >50 只二次确认 + 完成后自动复检）；③ **成分股失败人话诊断**（M2/M3 改用 `friendly_constituent_message`
  —— 不再裸甩"接口未返回成分股"；**真机联网实测**：000300→288 只 / 000905→429 只，8~14 s，
  解析中界面注明耗时预期）；④ **bulk_download「⚡全市场扫描就绪」预设**（D6-2）；⑤ **STEP 6 前置复核**
  （真机 368 只 2.89 s / 7.85 ms/只 ⇒ 外推 ≈42 s，**决策 = 接受引擎路径**，STEP 7 暂不排期）。
  验收：`smoke_chart` **678 → 692**（+14 体检内核段）、`smoke_pages_overlay` **447 → 457**（+10 两页接线段）。
  ⚠ **D6-4"缺口按成交额优先"的如实变通**：missing 的标的本地无数据、无成交额可排序 ⇒ 补齐按花名册序
  （等首轮补齐后有数据再谈优先级）；**D6-5"问题清单回流数据管理页"只做了扫描侧呈现**
  （unreadable/失败名单进 tooltip + 指引去数据管理），数据管理页侧的问题清单栏位**登记为后续项**。
- **STEP 6.5 ✅（v6.43 / 1.33 · 体验修复轮，用户 2026-09-20/21 两轮实测驱动）**：
  M3 图表可读性根治 + M2 先选后扫与缺数据全链路诚实化 + 成分股换中证官网权威源 +
  表格性能三件套。详情 = 顶部快照「断点」行 + §11.5-64…69 + `docs/JIAN_HISTORY.md` v6.43 行；
  新增后续项：§7-D 类 **D4 时点成分股**（幸存者偏差的根治路）。
- **STEP 7（可选性能档 · **暂不排期**）**：宽表向量化（必须先过"**逐位一致**"断言 + 定 `shift` 空洞口径，
  见 D2 第 3 条）。**v6.39 决策**：STEP 6 复核后接受引擎路径性能；等用户用「全市场扫描就绪」补齐全 A
  并实测后，若仍要提速再评估此档。
- **STEP 8**：文档回写（§4 / §6 / §8 / §11.4 / §11.6 / §11.7）+ 发版（三处版本号同批同步，§9-A）。

#### H. 风险与对策

| 风险 | 对策 |
|---|---|
| **"数据不足"被当成"未命中"** ⇒ 广度系统性偏低、横截面漏股 | **三态口径 + 有效样本数显式**；冒烟含负向断言（"数据不足"不得计成未命中） |
| **缓存静默陈旧**（下了新数据却不重算） | 失效键**必含数据版本**；含负向断言（改数据 ⇒ 必作废） |
| **复权能力不足**（`kline_daily_raw` 只有 1 只） | 本轮**只上前复权单口径 + 界面明示**（D8）；**不假装支持**不复权 |
| **全市场扫描把 UI 卡死**（载入 ~2.6 s + 求值 ~8.6 s） | 分块 + QThread + 进度 + 取消 + 竞态守卫；**会话缓存**让"改日期/改粗筛"秒回 |
| **内存峰值** | **引擎逐只路径不建宽表**（峰值 ≈ 结果矩阵 **22 MB**）；只有向量化档才需 250 MB(f32)/500 MB(f64)，届时按标的块分批 |
| **宽表 `shift` 跨空洞**（与引擎口径实测 0.1% 不符，§9.2） | 向量化档必须"**按列跳 NaN** 做 shift"或**显式声明口径**，并过逐位一致断言 |
| **源透传列被将来的列裁剪静默删掉**（`turnover`/`outstanding_share`，§9.1） | **显式登记为受支持列** + 冒烟加"列存在性"断言 |
| **两页口径分裂** | **就绪度模型只有一份**；下载一律走 `MarketSyncService`（§9-H） |

#### I. 本主案明确"不做"（防范围失控）

- ❌ **估值 / 财务类筛选**（PE/PB/ROE…）—— `valuation` / `fin_report` **无数据源**，属独立的数据源扩建。
- ❌ ~~真·换手率~~ —— **v6.33 修正：已可用**（`turnover` / `outstanding_share` **本就在分区里**，
  源自新浪源透传，覆盖 98.6%；见 **D5 / §9.1**）。仍不做的是"**接独立股本数据源**" —— 不再必要。
- ❌ **组合级多标的引擎**（择时后挑股 + 资金分配）= §6.5 远期，**另一个模块**。
- ❌ **扫描页内联网**（只读湖；联网一律走 `MarketSyncService`）。
- ❌ **扫描结果入 SQLite**（大表走 parquet 派生层）。
- ❌ **为扫描另做看图器**（双击跳行情工作台）。

#### J. 验收口径

`py tests/smoke_chart.py` + `py tests/smoke_pages_overlay.py` **失败 0 且断言数只增不减** + 全仓 `compileall`
+ **STEP 0 的实测标杆达标** + **用户手动实测手感**（先小范围再全市场）。
新增断言方向：三态矩阵逐位可验 · 粗筛生效且可恢复默认 · 面板增量 == 全量（**逐位一致**）·
缓存"数据版本变 ⇒ 作废" · 就绪度两页一致 · 双击结果行跳到行情页且标的正确 ·
**会话缓存"数据版本变 ⇒ 作废"** · **列存在性（`turnover` / `outstanding_share`）有断言钉住**（§9.1）·
**数据管理页结构确未被改动**（F 第 1 条）。

---
### §7-B10 主案规格：数据新鲜度（日线收盘定稿守卫 + 扫描页更新引导）
（v6.45 立项 · 用户 2026-09-22 拍板 · **设计定稿，待按 STEP 施工**）

#### A. 用户拍板记录（不得回退）
| # | 议题 | 结论 |
|---|---|---|
| 1 | 盘中半根 bar 污染 | ✅ **方案A（严格）**：未收盘定稿的“当天日线 bar”**一律不写进日线库**；盘中要看当天用分钟周期 |
| 2 | M2/M3 更新引导 | ✅ **三条全做**：①「更新到最新交易日」动作 · ②日期滞后检测提示 · ③基准日诚实化（互相印证） |
| 3 | 定稿时刻 | ✅ 默认 **15:05**（A股 15:00 收 + 缓冲），做成常量可配；判据**只此一处** |
| 4 | 「最近交易日」来源（M1 追加拍板 · 2026-09-22） | ✅ **改引真交易日历**（推翻原 F 条「不引第三方交易日历」）：AkShare 日历 + 当日 JSON 缓存 + 失败回退本地最新；本次先服务 M1 默认终点 |
| 5 | M2/M3 更新入口（STEP 2 追加拍板 · 2026-09-22） | ✅ **与“补齐缺失”合并为一键「⬆ 更新到最新」**（对整批当前范围跑增量，不再并列两个按钮）；滞后判据**复用真日历**（与 M1 同源）；本次连发版 1.35 |

#### B. 根因（读代码核实，非臆测）
- **问题2 · 半根 bar 永久冻结**（`data/sync_service.py`）：
  ① `ThrottlePolicy.fresh_within_days=0` + `_is_fresh`（末日==今天 ⇒ “已最新”）→ 盘中同步过一次，**同日盘后再点被 skip**；
  ② `refresh_one` 增量起点 `start_date = last + 1天` → **次日永不回补今天**；
  ③ `_merge` 虽 `keep="last"`（本可自愈）却因①②拿不到今天的完整数据 → 盘中那根半 bar 落库后**再也刷不掉**，污染收盘口径回测/扫描（成交额/换手/收盘类判定全错且界面看不出）。
- **问题1 · 无更新入口 + 基准日死胡同**：
  ① `readiness_flow.fill_missing` 只补 `gap_symbols()`（本地**从来没有**的股票），已下到 9/18 的不算缺失 → “补齐缺失”**不会推进到最新交易日**；M2/M3 页**没有**“更新到最新”的入口；
  ② `_calibrate_asof_date` 把 `date_asof` 上限**硬收到本地最新(9/18)** → 9/21 灰掉点不动，且无解释、无通往“先更新”的桥。

#### C. 核心设计
- **定稿判据（唯一真源）**：`sync_service.is_daily_bar_settled(bar_date, now=None, settle_hhmm=DAILY_SETTLE_HHMM) -> bool`
  = `bar_date < 今天` 恒真；`bar_date == 今天` 仅当 `now >= 今天 settle_hhmm` 才真；未来日 False。纯函数、零 Qt、零网络。
- **写入边界守卫**：`refresh_one` 落盘前，对**日线类分区**（`kline_daily` / `kline_daily_raw` / `index_daily`）应用 `_drop_unsettled_tail(df, now)`：**只裁掉“今天且未定稿”这一根**（历史/昨日/盘后当天都保留）。分钟分区 `kline_min` **不裁**（本就是盘中语义）。
  → 附带效果：盘中把今天裁掉后，本地末日=昨天 → 盘后再同步 `_is_fresh` 自然不跳过、起点=昨天+1=今天 → 拉到完整当天并落库。**无需再改 `_is_fresh`/起点**，方案A 自洽。
- **更新到最新（复用现成件）**：`ReadinessFlow.update_latest()` 对**当前统计范围整批**跑 `SyncWorker`（= `MarketSyncService.refresh_one` 增量，天然“拉到各自最新”），>50 二次确认、可中断、完成自动复检；与 `fill_missing` 并列、共用 SyncWorker/JobGuard。
- **滞后检测**（v6.47 改）：**复用真交易日历**——`trading_days_between(代表性最新日, 最近已定稿交易日, 日历)` 精确数“约 N 个交易日滞后”（节假日不误报）；代表性最新日 = `ReadinessReport.representative_latest`（每只 last 的**中位日**，非全局 max，不被单只刚同步标的掩盖）；拿不到日历（离线）→ **不提示滞后数字**，不猜。（原 busday 估算法已废弃）。
- **真交易日历（M1 追加 · 本次落地）**：`data/akshare_feed.py:fetch_trade_calendar`（源层）+ `data/trade_calendar.py`（薄模块：`load_or_fetch` 当日 JSON 缓存 / `latest_settled_trading_day` = 日历 ∩ `is_daily_bar_settled`）+ `ui/workers.py:CalendarWorker`（一次性后台抓，失败回 None → UI 回退本地最新）。三重兜底：缓存命中零网络 / 抓取失败回吐旧缓存 / 全无则 None。
- **基准日诚实化**：上限仍 = 本地最新（防选了扫不出），但①旁边一行小字说明“上限=本地最新 X；要选更近先『更新到最新交易日』”②`update_latest` 完成后复检 → 上限自动抬升、回执回显“现在可选到 Y”；③**（v6.47）新增“基准日当天覆盖 N/total”诚实提示**（`coverage_at(基准日)`）——避免“就绪 299/300”却“扫描 1/300”的困惑（就绪=历史行数够、扫描=基准日当天有行，两套口径；基准日默认不改算法，只加提示）。

#### D. 实施步骤（每步独立可验收 · 一 commit 一步 · 状态回写本表）

> **本主案收官（§7-B10 全案 · v6.47 · 1.35）**：STEP 0–4 已全部落地；STEP 5 = 本条文档回写 + 发版 1.35。真交易日历已接（推翻原 F「不引日历」），M1（v6.46）+ M2/M3（v6.47）均共用。
- **STEP 0 [x] 定稿判据（纯函数，零行为改变）**：`sync_service` 加 `DAILY_SETTLE_HHMM` + `is_daily_bar_settled` + `_drop_unsettled_tail`；`smoke_chart` 加纯函数断言（D<今天 / D==今天盘前 / 盘后 / 未来日；裁尾只削未定稿当天、不碰历史与分钟）。
- **STEP 1 [x] 写入边界接守卫（= 问题2 落地）**：`refresh_one` 落盘前对日线类分区 `_drop_unsettled_tail`；`smoke_chart` 断言：monkeypatch `_fetch` 回吐含“今天未完成行” + 假 `now`=盘中 → 落盘无今天行；`now`=盘后 → 有；分钟分区不受影响。**联网实测**：盘中对某只 refresh_one，查 parquet 末日不含今天。
- **STEP 2 [x] 「更新到最新交易日」动作（问题1-①）**：`ReadinessFlow.update_latest()` 与 `fill_missing` **合并为一键「⬆ 更新到最新交易日」**（共用 `_launch_sync`，整批当前范围增量）；M2/M3 空态同一入口；完成复检后 `date_asof` 上限自动抬升。
- **STEP 3 [x] 日期滞后检测提示（问题1-②）**：`ReadinessFlow.start_calendar_fetch()` 挂 `CalendarWorker` → `trading_target`；`_render_readiness` 用 `trading_days_between` 算滞后交易日数 + `format_stale` 回执文案；离线（无日历）不提示。
- **STEP 4 [x] 基准日诚实化（问题1-③）**：M2 `lbl_asof_hint`（上限=本地最新、要更先更新）+ 更新后复检 `_calibrate_asof_date` 抬升上限并回显（M3 无 date_asof，不适用）。
- **STEP 5 [ ] 文档回写 + 版本（发版时）**：§4/§6/§7 B10 状态/§11.5（新坑：盘中半根 bar 冻结 + 定稿守卫）/§11.6/§11.7 断言数 + §9-A 三处版本号（1.34 → 1.35）。

#### E. 验收口径
`py tests/smoke_chart.py` + `py tests/smoke_pages_overlay.py` **失败 0 且断言数只增不减** + 全仓 `compileall` + **用户实测**：① 盘中同步后查日线库不含当天半根；② M2 点「更新到最新交易日」→ 进度 → 复检 → 基准日可选到最近交易日 → 扫描出数；③ 滞后提示与实际一致。

#### F. 本主案明确“不做”（防范围失控）
- ❌ ~~不引第三方交易日历~~ —— **已被 v6.46 修订推翻**（用户 2026-09-22 为 M1 默认终点拍板引入真交易日历，见 A 条 #4 / C 条「真交易日历」）；滞后仍可用 busday 估作快速提示，精确“最近交易日”现在走日历。
- ❌ 不改 `_is_fresh`/增量起点语义（方案A 在写入边界裁尾已自洽，动它反而引入新分叉）。
- ❌ 分钟周期不施加定稿守卫（本就是盘中）。
- ❌ 不做“自动定时同步”（那是独立功能，本案只给**手动**更新入口 + 检测提示）。

---
## 8. 版本演进备忘（压缩 changelog）

> 📦 **完整 changelog（v1.0 → 现在）已归档 → `docs/JIAN_HISTORY.md` §8。**
> 本文件只保留**最近三版**（"我刚做了什么"），更早的按需去归档查。

| 版本 | 一句话 |
|---|---|
| **1.36** | §7-A2 回测结果图表导出：`build_daily_series`（逐日净值+买卖点共同源）+ CSV 末尾逐日净值数据段（Excel 选中列绘图）+ 新增 `ui/widgets/backtest_xlsx.py`（openpyxl 内嵌净值折线图+买卖点 marker，导出菜单「📊 导出 Excel 图表…」）；smoke 745 / 514→521（§11.5-74） |
| **1.35** | §7-B10 数据新鲜度全案（M2/M3 收尾）：`ReadinessFlow` 新增 `update_latest()` 一键「⬆ 更新到最新」（与“补齐缺失”合并、共用 `_launch_sync`）+ 滞后提示（`start_calendar_fetch`/`trading_days_between`/`format_stale`，真日历）+ M2 基准日诚实化（`lbl_asof_hint`）；承 v6.46 M1 切片（定稿守卫/真日历/M1 区间修复）；smoke 737→745 / 508→514（§11.5-71/72） |
| **1.34** | §7-B8 R7 副图换序收尾：`layer_model` 可持久化顺序（换序只改格位不改 target）+ `desk_ui.sub_order` + 配方页 ⬆⬇/拖拽（复用 `DragHandleListWidget` 三道闸）+ 测试偏好隔离补正（§11.5-70） |
| **1.33** | M2/M3 体验修复轮：M3 图表可读性根治（bar 轴/双视觉/指数四图形/分界把手/轴对齐）+ M2 先选后扫与缺数据诚实化（闸门/就近落位/missing 进总数）+ 成分股换中证官网权威源（§11.5-64…69） |

> 版本号纪律见 **§9-A**（唯一出处：commit 首词 + `settings.APP_VERSION` + `version.json`）。


## 9. 审计发现：文档 ↔ 代码不一致 / 技术债（本次 v5.0 核对产出）

- **A. ✅ 已修（v5.7）版本号滞后；🔁 编号体系于 v6.16 改版（用户拍板）**：
  `config/settings.py` 的 `APP_VERSION` 与 `version.json` 一度统一为 `1.4.0` / `1.4.1`
  —— 那是"回测总集"语义编号，与 git 提交里的 `1.07 … 1.20` **长期并行、互不同步**，**已废弃**。
  【★ v6.16 新纪律（2026-09-15 用户拍板）】**版本号统一跟随 git**：
  · 取值 = **最近一次 push 的 commit message 首词**（历史形如 `1.07`、`1.19`、`1.20`）；
  · **每次 push 递增 0.01**（1.21 → 1.22 → 1.23 …）：不跳号、不改三段式、不引入第四套编号；
  · ★ 2026-09-20 整合记录：未推送的 1.28–1.32 五批按用户要求重写为 **1.31（扫描模块代码）+ 1.32（文档与版本）**，
    1.28 / 1.29 / 1.30 三个号被消化（远端自 1.27 直达 1.31）；原五提交存于分支 `backup/1.28-1.32`；
  · **当前值 = `1.36`**（= §7-A2 回测结果图表导出（CSV 逐日净值/买卖点数据列 + .xlsx 内嵌净值曲线图）；1.35 = §7-B10 数据新鲜度全案；1.34 = §7-B8 R7 副图换序收尾；1.33 = M2/M3 体验修复轮；1.32 = 修复成分股名称列全空 + 内核警告出口；1.31 = 成分股代码格式；1.30 = STEP 6 联动收尾；1.29 = M3 广度页；
    1.28 = M2 全市场筛选页；1.27 = 文档分层重构；1.26 = 复盘页
    版式收口；1.25 = 画线工具重做「点选绘制」+ 通道语义修正；1.24 = 侧边栏重设计 + 自选分组；
    1.23 = 行情工作台收口）；
  上一轮 `1.22` = 回测页 UI 重构（摘要条 + 遮罩抽屉）；`1.21` = §7-B5「回测成交真实性」
  （三档成交时点 + T+1）；`1.20` = 图表架构 P0–P8 + 全仓文件归置 + 本版本号体系改版；
  更早的 `1.4.x` **已废弃**；
  · **三处必须同批同步**：① git commit message 首词；② `config/settings.py:APP_VERSION`；
    ③ 仓库根 `version.json`（它的 `version` 字段就是给老版本比对用的**远端清单**）；
  · 不同步的后果（`core/updater.py` 每次启动比对）：远端比本地新 → 老用户收到**误报**；
    远端比本地旧 → 新版本**永远不提示**；
  · ⚠ `version.json` 的 `url` 是"点『是』就打开"的页面：版本号一旦升上去并 push，
    所有老用户开机就会弹「✨ 发现新版本」。
    （**现状**：指向项目 Releases 列表页 `https://github.com/ENDVEN/Jian/releases`
    —— 用户 2026-09-15 决定：**暂不制作 Release**（软件尚未完工），先用它占位；
    将来正式发版时**换成具体版本的下载直链**。在那之前，老用户点进只会到 Releases 列表。）
- **B. zone 命名口径漂移**：历史规格曾规划 `market_index` / `scan_cache` 两 zone；
  实际 `market_db.py` zones 为 `index_daily`/`sentiment`/`hot_topic` 等 8 个，且无 `scan_cache`。
  **以代码为准**，新增需求按现有 zone 命名体系扩展并回写本文档。
- **C. §4 文档树过时**：早前目录树缺 `sync_roster.py`、`core/formula/` 实际为 5 个 py；
  本文档 §4 已重绘为磁盘一致版。根目录 `screenshots/` 为历史遗留空壳目录（**v6.14 已删除**），
  正式截图目录在 `~/.jian_data/screenshots`。
- **D. `preferences.json` 目前唯一键为 `time_precision`**：偏好系统已留好读写骨架，
  后续新增用户偏好（图表主题等）直接加 key 即可。
- **E. 无显式代码债务**：全仓库扫描无 `TODO/FIXME/NotImplementedError`；所有"占位"
  均为 ComingSoon 页面或规格预留在注释/文档。（v5.5 复扫确认仍成立，唯一命中是
  `core/indicators.py` 注释里的 "add_xxx" 占位示例，非真实债务。）

### 9.1 数据湖列结构不一致 + 源透传列属"隐性依赖"（v6.33 · STEP 0 实测 · **现行**）

**事实**（P1b 实测口径：`kline_daily` 368 只 / 90.1 万行）：
- 列覆盖：`date/open/high/low/close/volume/symbol` = 368；`amount` = 362；
  **`outstanding_share` = 362 · `turnover` = 362**；
  另混入 **期货列 `持仓量` / `动态结算价`（各 5 只期货标的）**，
  以及 **中文列 `股票代码`/`成交额`/`振幅`/`涨跌幅`/`涨跌额`/`换手率`（各 1 只）**。
- **根因**：`AkShareFeed._normalize_ohlcv()` **只 `rename`、不裁列** ⇒
  ① 新浪源自带的 `outstanding_share` / `turnover` **一路透传进湖**（`grep` 全仓 **0 命中**，代码从没提过它们）；
  ② 东财兜底源的中文列（只有 5 个进了映射表）**以中文名透传**；
  ③ 期货来源的 `持仓量` / `动态结算价` 同样透传。
  （对照：**分钟线**路径有 `out[keep]` 显式裁剪 —— **日线没有**，不对称。）

**风险与纪律**：
1. **禁止假设 schema 统一**：读数一律**按"列是否存在"裁剪**；缺列 ⇒ 走**三态「数据不足」**。
2. **`turnover` / `outstanding_share` 是"隐性依赖"**（不在 `OHLCV_COLUMNS` 常量里）⇒
   M2/M3 既然要用，就**必须先把它们显式登记为「受支持列」**，并加冒烟断言钉住"列存在"；
   否则将来任何一次列裁剪都会让**换手率过滤静默失效**（"静默"是本项目最忌讳的一类事故）。
3. **兜底源（东财）没有这两列** ⇒ 该股换手率 / 流通市值**一律记「数据不足」**（**绝不当 0**，否则会误杀一片）。
4. 可修的小债（择机，**别顺手做**）：给日线也补一次列裁剪 / 白名单校验（对齐分钟线做法），
   并在落盘与导出前统一列集合。

### 9.2 宽表 `shift` / `REF` / `CROSS` 的"跨空洞"语义分歧（v6.33 · STEP 0 实测 · **STEP 7 前必须定口径**）

**事实**（P3c / P3b 实测）：
- 同一公式，「**引擎逐只**」vs「**宽表向量化**」在**按标的自己的日期集合取行**时 = **0 差异**（语义等价）；
- 但宽表按**全局交易日历**做 `shift(1)` 时，标的**缺数据的中间日期**（停牌 / 未下载）会被跨过 ⇒
  实测 000021（区间内 31 个空洞日）出现 **4/4022 ≈ 0.1%** 的边界不符。
- ⚠ **陷阱**：若用"**按位置截断**"比对，会得到 **86–168 处假差异** —— 我第一版正是如此，
  且换成 float64 后**数字分毫不变**，才排除精度、锁定"对齐方式"。**先定对齐，再谈一致性。**

**纪律**：向量化档（STEP 7）**必须先择一，不许默默不同**：
- **(a) "按列跳 NaN" 做 shift** —— 与 M1"逐标的自身序列"口径一致；成本 ≈0.5–2 s/全市场（可接受）；或
- **(b) 显式声明"扫描以全局交易日历对齐"** 并在界面与文档登记该口径差异。

**默认路线**：本轮**只交付「引擎逐只」**（口径天然与 M1 一致、实现最简单），向量化留作可选性能档。

### 9.3 系统代理环境下行情拉取「批量全灭」（v6.42 · 2026-09-20 诊断 · **已定因待修 · 只记录不改码**）

**用户实测现象**：「⬇ 补齐缺失」一轮里**每一只**都报
`A股日线东财源失败 …(Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected(...)))`
⇒ `A股日线拉取失败: xxx (主源与兜底源均未返回数据)`，无一幸免。

**根因（已实锤，不是行情源的问题）**：本机 Windows 系统代理开启
（`Internet Settings: ProxyEnable=1, ProxyServer=127.0.0.1:7897`，Clash 类工具）。
`requests`（akshare 底层）**默认读系统代理** ⇒ app 的每一个行情请求都经 127.0.0.1:7897 转发；
**代理进程断连/退出/切换节点的瞬间**，所有请求统一死于 `ProxyError('Unable to connect to proxy')`。
诊断时实测：代理正常时新浪/东财直连与走代理**都通**（HTTP 200）；把代理指到死端口即
**逐字复现用户的报错**（主源新浪与兜底东财报同一类 ProxyError，最终错误行与用户日志一致）。
∴ 这类"**短时间内批量同错**"= 本机代理瞬断的指纹，**不是**行情源挂了、更不是被限流。

**为什么"补齐"最容易撞上**：补齐一次连续发几十上百个请求（间隔 0.6 s 起步），时间跨度长
⇒ 窗口内代理切换一次节点就全军覆没；且 `SyncWorker` 熔断（默认 12 连败）会提前停手 ——
用户看到的"每只都失败"其实是熔断前的十几次 + 停手（**熔断按设计工作了**）。

**连带发现（同轮一并处理，勿忘）**：
1. **`beg=20260919` 的旁证**：增量请求的起点 = 本地末日+1，说明 000591 本地已有数据（到 09-18）——
   它出现在"补齐缺失"名单里是因为**当时体检用的旧 data_version 还挂着**（补齐完成后复检会消掉）；
   若复现"已有数据的票也在补齐名单"请按这条排查，不要急着改补齐逻辑。
2. **`_classify_error` 已把 `proxy` 归入 network 类**（`data/sync_service.py` 的关键词表）⇒
   失败文案归类没错，但**没有把"疑似本机代理问题"单独说出来** —— 用户看不出该去检查代理。

**待修清单（用户拍板后再动，本轮零代码）**：
- [ ] 拉取失败文案**识别 ProxyError**：`疑似本机代理问题 —— 请检查代理软件（127.0.0.1:7897）是否在运行`，
      与"行情源失败 / 被限流"分开安抚（§10-10 分类安抚的补全）；
- [ ] 可选增强：连续 N 次 ProxyError ⇒ **熔断提前**并直接提示检查代理（现在的 12 连败熔断
      对"代理全灭"这种 100% 失败率太迟钝，白白等十几次超时）；
- [ ] 可选（谨慎）：设置里加"行情拉取不走系统代理"开关（`session.trust_env=False` /
      显式空 proxies）—— 国内行情源直连通常更快，但**必须默认跟随系统**，别替用户决定。

**判据（给未来的我）**：凡"批量同错 + `ProxyError`/`Unable to connect to proxy` 字样" ⇒
先查 `requests.utils.getproxies()` 与代理进程状态，**别怀疑行情源、别加重试**；
反之单只失败 / 两源报错形态不同，才往行情源方向查。

### 9.H 历史台账（**已归档 → `docs/JIAN_ARCHIVE.md`**）

> 下面这些按版本分节的审计发现**均已完结**（绝大多数标注"✅ 已修（vX.Y）"），
> 原文与编号**原样保留**在归档文件里；本文件只留 A–E（口径/纪律）与这条索引。
>
> ⚠ **其中仍有现行约束力的三条，必须记住**：
> 1. **§9-V 数据源护栏**：非正价 / 缺价行**丢弃并出声**；**降级到兜底源必须在出口统一量纲**
>    （东财=手、新浪=股，混用会让量能副图出现 100× 台阶）。可执行断言在 `smoke_chart`（见 §11.7）。
> 2. **§9-M 同步两大铁则**：`fresh_within_days=0`（末日==今天才算最新）+ **空增量 = 已最新不是失败**
>    —— 已固化进 **§11.5-8**。
> 3. **§9-O3 教训**：改常量前先看**代码本体**，再从代码反向修文档（`docstring` 会撒谎）。

- v5.5 全仓通读新增发现（F…L + U 版式 + V 数据源）
- v5.9 独立复查产出（M-1…M-4）· v5.10 UX 加固产出（N-1…N-5）· v5.12 全仓通读核对产出（O 系列）
- v6.5 事故记录（存量函数回归）· v6.7 用户实测反馈产出 · v6.8 全 App 坐标轴缺陷 · v6.9 第三次复查
- v6.14 全仓文件归置复查 · v6.24 施工产出（R7/R8 两处真实缺陷 + 三处新坑）

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
     都能点？③ 是否复用了统一常量而非就地写样式？④ **下拉/日历控件是否还看得见箭头？**
     （v6.9 实测：`QComboBox/QDateEdit/QDateTimeEdit` 一旦写了 `::drop-down` 而没写
     `::down-arrow`，Qt 走样式化绘制路径后**箭头完全不会被画出来** —— 必须**成对**写，
     或干脆只写本体。生成器 `custom_widgets.combo_qss()/date_edit_qss()` 已强制成对。）
10. **【按钮层级 + 文案铁律 · v5.10 新增】**：
   - **危险动作物理隔离**：会造成大范围/不可逆损失的操作（清空、批量删除）不能与
     日常高频按钮同排。低危=正常按钮；中危=同排但红色+二次确认；**高危=另找角落 + 低调呈现
     + 键入确认词**（如清空分区要求输入「清空」）。做得越费事，误操作率越低。
   - **面向用户说人话**：绝不在界面上甩内部术语（"增量更新 / 强制全量重拉 / 断点续传 /
     前复权 / 熔断"都不许直接当按钮名）。规则：动作动词 + 用户能猜到的对象（「更新到最新」
     「重新全量下载」），细节差异放 tooltip / 次要文案。
   - **【v6.17 追加 · 由用户实测反馈倒逼】术语不许当"唯一解释"，且必须有看得见的教学入口**：
     用户原话（针对第一版的"触发式条件单 / 触发跳数"）：**"用户完完全全都不知道……要么改文字表述，
     要么就要给用户一定的教育和指引才行"**。三条硬要求：
     ① **主说明用人话 + 具体数字**（把"1 跳"写成"0.01 元"、把"当根"写成"当天"、
       把"信号作废"写成"不买也不卖"）；
     ② **术语只允许出现在 tooltip / 教学弹窗里当"补充"**，**绝不能**是界面上唯一的说明；
     ③ **关键概念必须有"看得见的入口"**：行内常显说明（随选择实时变化）+ 问句式示例弹窗。
        ⚠ 只给 tooltip = 没有解释 —— 用户不会主动去悬停。
     参考实现：`core.backtest.fill_mode_oneliner` + `ui/dialogs/fill_model_help.py`（v6.17）。
     **自检动作**：新增任何"用户要填/要选"的参数，先问一句"用户看到这行字，知道自己该填什么吗"；
     答不上来 → 补行内说明 + 示例入口，**而不是加一行 tooltip 了事**。
   - **报错要"分类安抚"而非"统一吓唬"**：失败提示必须区分"网络/限流"与"数据本身没有
     （退市、停牌、代码错）"，后者明确告诉用户这不是他的错、且本地历史仍可用（§9-N5）。
11. **【统一绘图窗口 · v6.0 B3】凡"公式驱动的叠层"只能走一条底层管线**：
   引擎侧 = `core/formula/draw.py`（语句分类 + DrawSpec/DrawData IR + COLOR_TABLE），
   渲染侧 = `ui/widgets/draw_overlay.py`（唯一 `OverlayPainter`）。
   **任何页面（回测 K线、市场行情、未来新图）展示 STICKLINE/DRAWICON/公式线/状态柱，
   都禁止自己写绘图逻辑**；想改样式/语义 = 改引擎 IR 或 OverlayPainter 一处，
   杜绝"每个图表一对一地改"。底层契约见 §7-B3 主案规格。
12. **【图表架构四层 + 两条管线 · v6.1 新增 · 总纲见 §7-B3】**
   - **四层唯一落点**：① 引擎 IR = `core/formula/draw.py`；② 图表宿主 =
     `ui/widgets/chart_pane.py` / `chart_host.py`；③ 渲染器 = `ui/widgets/draw_overlay.py`；
     ④ 用户标注 = `data/annotations.py` + `ui/widgets/annotation_layer.py`。
     **新增任何图表能力，先归位到这四层之一，绝不新起一条并行管线。**
   - **两条管线不得混用**：**公式叠层（A）**随数据/参数**重算且不持久**；
     **用户标注（B）**持久化到 `(标的, 周期)` 且必须能**逐个独立删除**。
     二者只共用图表宿主这块舞台；禁止同一数据结构、禁止同一生命周期。
   - **渲染器入参是 `ChartPane` 不是 `PlotItem`**（P0 铁律）：防止"单图写死"——一旦写死，
     副图 / 行情页 / 复盘回放三处都要返工。
   - **内置指标（`core/indicators.py`）与用户公式在渲染层同一套"图层协议"**：
     都产出 `Series`/`DrawData` 交给同一 pane，禁止为"用户函数"单开特例分支。
   - **存储留退路**：标注先 JSON（原子写），但 `data/annotations.py` 对外 API 按
     `(symbol, period, id)` 抽象，将来迁 DB **只换实现、不动调用方**。
   - **P8 之前不得在旧页面继续堆功能**：新能力一律新建组件文件（§9-L 体积债）。
13. **【文件归置规范 · v6.14 新增】新文件先问"它是谁"，按角色入位 —— 根目录只留"门面"**：
   - **根目录白名单（只允许这 5 个文件 + 4 个层目录 + 4 个角色目录）**：
     `main.py`（唯一入口）、`requirements.txt`、`version.json`（发布物，直链指向此处 **禁止移动**）、
     `JIAN_RULES.md`（唯一权威记忆，**故意**放根：第一眼要看见）、`.gitignore`；
     层目录 `config/ models/ core/ data/ ui/`；角色目录 `scripts/ tests/ samples/ docs/`。
     **其它任何文件出现在根目录 = 归置错误。**
   - **三个角色目录的判据**（这是最容易搞混的一步，按"谁去调用它"分，不按它像什么分）：
     | 目录 | 判据 | 例子 |
     |---|---|---|
     | `scripts/` | **只给人手动敲命令**、不进 app 的 import 图 | `sync_roster.py`（花名册同步） |
     | `tests/` | 人工运行的**验收/冒烟**脚本 | `smoke_chart.py`、`smoke_pages_overlay.py` |
     | `samples/` | **是数据不是代码**、且属用户私有/隐私 | 实例函数 `.txt`、实例交割单 `.xlsx` |
    | `docs/` | **给"未来的我"读的文档归档**（非代码、非用户数据；app 不 import） | `JIAN_HISTORY.md` 时间线 / `JIAN_PLAYBOOK.md` 踩坑手册 / `JIAN_ARCHIVE.md` 已完成主案与旧审计（v6.32 分层重构产物） |
   - **能被 app import 的，一律进四层**（`core` 纯计算 / `data` 获取存储 / `ui` 展示 /
     `config`+`models` 契约与设置），**不许**新起平级目录来放"某一类功能"（那会架空 §10-12 四层）。
   - **子目录脚本必须靠 `__file__` 反推仓库根**：
     `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`。
     历史事故预防：脚本从根目录挪进 `scripts/`/`tests/` 后，`sys.path[0]` 会从"仓库根"变成
     "该子目录"，于是 `from data.xxx import ...` 当场 ImportError —— **移动脚本必须同时改引导**。
   - **隐私铁律的落地方式（§10-6）**：私有样例统一收进 `samples/`，`.gitignore` 里
     `samples/*` + `!samples/README.md` 整目录忽略、只放行说明 —— 比"逐个文件名模式"可靠
     （后者漏一个模式就泄露）。**纵深防御**：`实例*` 等文件名模式保留不删。
   - **新增/移动文件后必须同批完成的三件事**：① 更新本节 §4 目录地图与行数；
     ② 若是可运行脚本，**在仓库根实测跑一遍**（`py tests/xxx.py`）；
     ③ 全文搜索旧路径引用（含**用户可见文案**，如"请先运行 `scripts/sync_roster.py`"、
     docstring、`.gitignore`）。
   - **临时产物不留仓**：会话期的一次性探针脚本、重定向输出（`_tmp_*.py` / `_a.txt`）
     用完**立即删除**；`.gitignore` 有 `_tmp_*` 兜底，但兜底不等于可以留。
   - **删文件要同一批 `git rm`**（例：P8 删 `ui/views/market.py` 后，别让它在 git 里长期挂着
     "已删除未提交"）；**空目录即垃圾**（例：v6.14 删掉根目录空壳 `screenshots/`，
     正式截图目录在 `~/.jian_data/screenshots`）。
   - 登记待办（**暂缓**，勿顺手做）：`ui/widgets/` 现有 17 个文件平铺（图表件 7 / 控件 3 /
    业务展示 4 / 公式 1），可再分 `ui/widgets/chart/` 子包 —— 但有 **51 处 import 点**、
    且会牵动 §7-B3 四层表的路径锚点，属"收益中/成本中"，**留待单独一轮**。

14. **【文档分层与防漂移 · v6.32 新增】`JIAN_RULES.md` 必须能被"一次读完"**：
   - **硬指标**：本文件 **< 100,000 字符**（≈ 单次读取上限）。**超过就是结构错误**：先搬走，再写新内容。
     （背景：v6.32 前它是 297k 字符 ⇒ 物理上读不完 ⇒ 只能检索 ⇒ **遗漏 + 误信旧数字**，已真实造成
     一次版本号事故。检索不是问题，"**现状与历史混在一起 + 同一数字十几处重复**"才是问题。）
   - **本文件只放"现在是什么 / 必须遵守什么 / 下一步做什么"**；**时间线、旧审计、已完成主案、
     踩坑全量清单**一律放 `docs/`（`JIAN_HISTORY.md` / `JIAN_ARCHIVE.md` / `JIAN_PLAYBOOK.md`），
     **编号保持不变**（`§11.5-25`、`§7-B6` 这些引用照旧成立，只是全文在归档文件里）。
   - **同一事实只存一处**：**版本号 → 只在 §9-A**；**断言数 → 只在 §11.7**；**行数 → 只在 §4 红榜**。
     别处一律写「见 §X」，**不再复制数字** —— 这条治的是本项目最大的漂移源。
   - **历史行数字冻结**：`docs/` 里的旧行**永不回改**；本文件现状行必须带「当前」或日期。
   - **每次收工必做两件**：① 更新顶部「**当前状态快照**」的**断点**一行；
     ② 新的版本叙事/本批摘要写进 `docs/`（**只追加，不改旧行**）。

- **10-14 版式分层纪律（1.22 立 · 用户实测反馈驱动）**：页面的纵向空间按
  **「使用频率 × 视线停留时长」** 分配 —— 禁止"所有区块同一优先级平铺"
  （用户原话："函数段、条件段、大盘段占据了大量篇幅……加了什么功能都会压缩下方回测数据的体积"）。
  五层定义：
  - **L0 主角**（高频 · 长停留：结果 / 图表 / KPI）= 常驻并**吃满剩余高度**，**永不折叠**；
  - **L1 操作轴**（高频 · 短停留：标的 / 策略 / 区间 / 运行）= 常驻**一行**；
  - **L2 状态 + 入口**（低频但需随时确认：函数段数 / 条件组数 / 门控 / 风控 / 成交口径）
    = **一行 chips 摘要**（显示当前值 + 点击展开编辑）；
  - **L3 编辑区**（低频 · 配置时才看）= **右侧遮罩抽屉**（一次只显示一张卡片 + 抽屉内页签切换），
    **覆盖层、不进页面布局** ⇒ 打开配置时 L0 结果区的高度**一个像素都不变**；
    抽屉几何自己在 `resizeEvent` 里算（宽 = min(560, 页面宽 × 0.42)，高 = 整页高，§11.5-26）。
    ⚠ **禁止用"就地展开（手风琴）"替代抽屉**：用户 2026-09-16 实测拍板 ——
    "就地展开虽然直观但**不美观**"（把结果区挤矮 + 卡片撑满整页，视觉很散）。
  - **L4 附属**（K线开关 / 导出 / 教学入口）= 贴在 L0 头部的工具条。
  **硬约束**：给页面加任何新配置项，**默认落在 L2/L3**（摘要条 chip + 抽屉内一张卡片），
  **不许**在结果区上方新起常驻行；常驻的"皮"总量不得超过「工具栏 + 摘要条 + 区间行」三行。
  **依据与样板**：`design/1.22-backtest-ui/index.html`（四套交互模型对照 + 分层表 + 取舍分析，
  **已入库作为长期设计参考**）；抽屉组件可复用 = `ui/widgets/backtest_panes.py::EditDrawer`
  （遮罩 + 抽屉 + 页签，**与回测业务无关**，别的页面可直接搬）。

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
**UI 永远不许跳过 DataEngine 去碰 SQL**（v5.12 复核：§9-H 的 3 处违规**已全部修完**，
行情页 `trading_desk.py` / `backtest.py` 现在都走 `engine.search_symbol` + `SingleSyncWorker`，**保持住**）。

### 11.3 用户数据在哪（改代码时别把仓库当数据库）
| 内容 | 路径 |
|---|---|
| 业务库（流水/持仓腿/覆盖/名册 5 表） | `~/.jian_data/jian_trades.db` |
| 偏好（目前只有 `time_precision`） | `~/.jian_data/preferences.json` |
| 回测策略 + 每标的指标档案 | `~/.jian_data/backtest_strategies.json` |
| **用户手绘标注**（趋势线/水平线/垂直线，按 (标的,周期)） | `~/.jian_data/annotations.json`（v6.10） |
| **公式配方库**（函数段+参数+每段目标窗格） | `~/.jian_data/formula_library.json`（v6.11；⚠ 开机自动恢复"上次用过的"配方） |
| **自选股**（顺序 = 用户关注顺序） | `~/.jian_data/watchlist.json`（v6.12） |
| **行情日线（两份口径）** | `~/.jian_data/data_lake/kline/daily`（前复权）+ `.../daily_raw`（不复权，v6.13）—— 两份**互不覆盖**，「数据管理」可单独删 |
| 行情数据湖（8 个 zone，parquet） | `~/.jian_data/data_lake/` |
| 复盘截图 | `~/.jian_data/screenshots/` |
| **用户私有样例**（自研公式 txt / 真实交割单 xlsx） | `samples/`（**仓库内但被 `.gitignore` 整体忽略**：`samples/*` 只放行 README。⚠ 它**不是**运行数据 —— app 不读这里，删了不影响任何功能；只作"喂给 app 的输入样例"） |
| ~~仓库根目录 `screenshots/`~~ | **v6.14 已删除**（空壳历史遗留）；正式目录永远是 `~/.jian_data/screenshots` |
| ~~仓库根目录 `实例*.xlsx` / `实例函数.txt`~~ | **v6.14 已归置到 `samples/`**（用户隐私，`.gitignore` 整体忽略，勿提交勿被代码引用） |

### 11.4 我要改 X，该动哪个文件？
| 想改的东西 | 落点 |
|---|---|
| 加一个统计指标 | `core/analyzer.py`（加 key）→ `ui/views/dashboard.py`（加一行 `metric_keys`） |
| 改交割单解析/缝合规则 | `data/data_feed.py`（纯函数，改完务必验"分批导入 ≡ 一次性导入"） |
| 加一个公式函数 | `core/formula/runtime.py`：`FUNCTIONS` 注册 + `ARITY` 声明元数 |
| 改回测撮合/风控 | `core/backtest.py`（`_run_on_signals` 是纯函数，好测） |
| 改**成交时点 / T+1 / 条件单触发** | **`core/backtest.py` 一处**（v6.17 · §7-B5）：三档常量 `FILL_*` + `FILL_MODE_LABELS` + `normalize_fill` + `fill_summary`；T+1 闸门、`max_bars` 顺延、**同根不重建仓**都在 `_run_on_signals` 内。UI 行 = `ui/views/backtest.py` 的「🎯 成交模型」（`_fill_config`/`_apply_fill_config`）。⚠ **别在页面里重算口径**，也别绕过 `normalize_fill` 自己拼默认值 |
| 改**成交模型的用户可见文案**（含术语翻译） | ① 下拉/行内说明 = **`core.backtest.FILL_MODE_LABELS` + `fill_mode_oneliner`**（唯一来源，页面不许另写）；② 留档文案 = `fill_summary`（写进 CSV/PNG）；③ **教学弹窗** = `ui/dialogs/fill_model_help.py`。⚠ 界面文案**不许**出现"跳 / 当根 / K线 / 条件单"当唯一解释（§10-10 / §11.5-22），术语只能进 tooltip 与弹窗 |
| 加一个技术指标（画图用，非公式） | `core/indicators.py`：`REGISTRY` + `OUTPUTS` |
| 加一个数据湖 zone | `data/market_db.py` 的 `self.zones` 字典 |
| 加一个用户偏好 | `core/preferences.py`：`DEFAULTS` 加 key 即可 |
| 改数值控件外观 | `ui/widgets/custom_widgets.py` 的 `SPINBOX_QSS`（**唯一可改点**，勿就地写 QSS，§10-9） |
| 改回测区间档位 | `ui/views/backtest.py` 的 `_PRESET_ORDER` + `_date_from_preset`（含 2016 下沿） |
| 改 Dashboard 日历热力图 | `ui/widgets/calendar_heatmap.py`（纯手绘控件）+ `dashboard.py` 的 `_prepare_calendar` / `_render_calendar` |
| 增删/清理数据湖缓存 | 原语在 `data/market_db.py`；页面在 `ui/views/data_manager.py`（⚠ 删完要 `_rescan` 刷新） |
| 改行情同步/抓取节流 | `data/sync_service.py`（增量合并 + `ThrottlePolicy` 都在这里，**勿在 UI 里另起炉灶**） |
| 改日线收盘定稿判据 | **`data/sync_service.py` 一处**（v6.46 / §7-B10）：`DAILY_SETTLE_HHMM` + `is_daily_bar_settled`（纯函数）+ `_drop_unsettled_tail`（`refresh_one` 落盘前对 `DAILY_ZONES` 裁尾）。M1/M2/M3 一律复用，**别在页面另写一套“今天算不算数”** |
| 改“最近交易日”/交易日历 | **`data/trade_calendar.py`（v6.46 / §7-B10）**：`load_or_fetch`（当日 JSON 缓存 `~/.jian_data/trade_calendar.json` + 失败回退）/ `latest_settled_trading_day`（日历 ∩ 定稿判据）。接口细节在 `data/akshare_feed.py:fetch_trade_calendar`；UI 取数只走 `ui/workers.py:CalendarWorker` |
| 改 M1 回测区间默认终点/滞后补 | `ui/views/backtest.py`（`date_end` 默认 + `lbl_range_note` 回执行 + 构页时 `flow.start_calendar_fetch()`）+ `ui/widgets/backtest_flow.py`（`_on_calendar` 精修默认终点 / `_prepare_stock_then_run` 滞后自动补 / `_apply_end_date_receipt` 补不到回退+回执）。⚠ **控件名 `date_end`/`date_start`/`cmb_range_preset` 不能改**（迁移护栏）；状态仍留在页面 |
| 给页面加后台任务 | `ui/workers.py` —— 全 app 唯一 QThread 定义处（Scan/Sync/SingleSync/BacktestRun/Constituents/FuturesImport/**CrossSection / Readiness / Calendar 九个 Worker**），**禁止页面自造线程类**（§9-O2）。⚠ **"发起新任务 ⇒ 旧回包作废"一律用公共件 `JobGuard`**（`next()` 取号 / `accept(id)` 判定），别再各写一个 `_token` 计数器（§9-O5 / §11.5-11） |
| 改版本号 | **三处同批同步（§9-A v6.16 新纪律）**：git commit message 首词 · `config/settings.py` 的 `APP_VERSION` · 仓库根 `version.json`。取值 = 上次 push 的版本 **+0.01**（形如 `1.20` → `1.21`） |
| 回测页 UI / 版式 | `ui/views/backtest.py`（**787 行**，1.22 拆分收官）。**版式 = 样板 A**：工具栏行 → 摘要条 → 区间行 → **配置抽屉（覆盖层）** → 结果区。**加新的配置项一律「摘要条 chip + 抽屉内一张卡片」，不许在结果区上方新起常驻行、不许用"就地展开"**（§10-14）；卡片与抽屉改 `backtest_panes.py`，摘要条改 `backtest_summary_bar.py`，结果区改 `backtest_result.py`，导出改 `backtest_export.py` |
| 回测页「运行流程」 | `ui/widgets/backtest_flow.py`（`BacktestFlow`）：选标的 / 数据就绪链 / 求值 / 后台计算 / 结果落地。⚠ **状态全在页面**（`_pending_*` / `_last_*` / 线程句柄），改它别在模块里存状态 |
| 回测页「策略库」 | `ui/widgets/backtest_strategy.py`（`StrategyBridge`）：快照打包 / 还原 / 存删 / 归档 / 对比；`store` 与 `_active_strategy_id` 仍在页面 |
| 回测页「抽屉开合/记忆」 | `_open_pane(key)`（None = 关闭）+ `_layout_overlay()`（覆盖层几何，`resizeEvent` 重算）+ `preferences` 键 `backtest_ui`（`{"pane":..., "last":...}`）；`_refresh_summary()` 是"控件状态 → 胶囊文案"的唯一汇总点 |
| 行情工作台页面 UI / 公式叠加 / 自选 / 周期 / 画线工具栏 | `ui/views/trading_desk.py`（⚠ **898 行，P8 新页；旧 `market.py` 已删除，别再"找回"它**）+ 编辑器 `ui/dialogs/formula_overlay.py` |
| 自选股（增删/排序/名称） | `data/watchlist_store.py` —— 顺序 = 用户关注顺序；`update_name()` 在花名册刷新后同步名称（旧名不当真相）。⚠ 与"花名册 `market_symbols`（全市场）"是两回事 |
| 行情周期（日/周/月） | `core/utils.resample_ohlcv`（纯本地聚合，列名与日线一致 ⇒ 下游零改动）。**纪律：指标必须在聚合之后算**，否则"周线 MA5"会变成"日线 MA5 被抽样" |
| 行情复权（前复权/不复权） | **`data/sync_service.zone_for_adjust(adjust)`** → 分区（`kline_daily` / `kline_daily_raw`）+ `ADJUST_QFQ/NONE` + `adjust_label`。**页面禁止自己拼分区名**（§11.5-19）。⚠ 想加第三种口径（如后复权）= 加一个常量 + 一个分区，**不要**在原分区里加列 |
| 抓取时的复权口径 | `akshare_feed` 的 `adjust` 参数，必须**透传到新浪与东财两个源**（`fetch_a_share_daily` 内部两个分支都用同一个 `adjust`）—— 否则主源失败降级时会**静默换一种复权**，这是最阴的数据事故 |
| 让图元"跟着鼠标走"（pyqtgraph） | `ItemIsMovable` **不管用**：pyqtgraph 覆写了 `mouseMoveEvent` 且不调父类实现，Qt 内建移动逻辑根本不执行。必须自己实现 `mousePressEvent`（记起点）→ `mouseDragEvent`（按 `scenePos − buttonDownScenePos` 改坐标）→ **`isFinish()` 时才回调落盘**。参考 `annotation_layer._ClickableText` |
| **加 / 改一种画线类型**（★v6.25 改版） | ① `data/annotations.py`：加 `KIND_*` + `KIND_LABELS` + `REQUIRED_POINTS`（+ 若有序语义常量，像 `FIB_RATIOS`/`PERCENT_RATIOS` 一样放模型层）；② **`ui/widgets/annotation_shapes.py` 的 `SHAPES` 加一行 `ShapeSpec`**（画法 / 回读 / 默认落点 / 是否重建附属图元）—— **这是唯一必要条件**；③ 若需要附属图元（档位/标签/箭头），在 `annotation_decos.py` 加一个 `deco_*`；图元小件放 `annotation_items.py`；④ `annotation_catalog.py` 的 `implemented` 翻 True（**双向断言**钉着，漏改立刻红）；⑤ ⚠ **`annotation_layer.py` 不用改**（它不认识具体画法）；⑥ 附属图元由层统一登记 `_extras`，随主图元一起删 |
| 标注的"周期键" | `data/annotations.period_key()`（任何写法 → `daily`/`weekly`/`monthly`）；页面只管传 `'D'/'W'/'M'`。**别绕过它直接拼字符串**（§11.5-19） |
| 内置指标 → 绘图 IR / "该放主图还是副图" | **`ui/widgets/chart_layers.py`**（v6.7）：`builtin_indicator_layers()` / `layer_value_range()` / `scale_mismatch_hint()`。**别在页面里自己算**（页面只留开关与窗格编排） |
| 多段函数编辑器（含"段"的增删） | **`ui/widgets/function_segments.py`** —— 回测页与行情页公式编辑器**共用**；⚠ 改它前请读 §11.5-15（删控件必须 `setParent(None)`；容器给多余高度时必须有可伸缩子控件） |
| 复盘页 UI | `ui/views/review.py`（**173 行**，1.26 拆分后只做装配与转发）；行为落 `ui/widgets/review_*.py`：`review_layout`(版式/可拖竖分栏) / `review_charts`(日历·月度·时长) / `review_playback`(交易回放) / `review_editor`(清单·编辑·孤儿缝合) / `review_flow`(筛选·导航·视图刷新) |
| M2/M3 新子页 | **均已落地**：M2 = `ui/views/scan_view.py`（164 行）+ `ui/widgets/scan_layout|flow|result.py`（第 2 页签）；M3 = `ui/views/breadth_view.py`（197 行）+ `ui/widgets/breadth_layout|flow|result|chart.py`（第 3 页签）。**共用** `core/cross_section` / `data/scan_store`（含 ⚡增量）/ `ui/workers.CrossSectionWorker` |
| M3 广度页（折线 / 指数副图 / 增量 / 重算） | 页面 = `ui/views/breadth_view.py`（状态 + 同名薄壳）。**版式** `breadth_layout.py`（ƒ/🎚 两卡**直接复用 `scan_layout`**；`BreadthDisplayPane` = 平滑/占比/指数）；**流程** `breadth_flow.py`（`_start_worker` 统一入口：`force` / `incremental` 两开关；`_ensure_index` 指数补拉链）；**图表** `breadth_chart.py`（`BreadthChart`：ChartHost 双窗格 + `attach_all` + 读数条 provider —— **别在页面手写 addPlot/setTicks**）。**⚡增量的矩阵续接在 `data/scan_store.py`**（`find_base` + `merge_tail`），改它必跑 `smoke_chart` 的「STEP 5」段 |
| 就绪度体检 / 更新到最新（M2/M3 共用） | 内核 = **`data/readiness.py`**（`probe_readiness` 只读 footer 四分类 + `latest` + `summary_line`/`gap_preview`/`detail_text` + **v6.47 `format_stale`** 滞后文案；**别在页面另写“有没有数据”的判断**）；线程 = `ui/workers.py:ReadinessWorker`（第 8 个）/ `CalendarWorker`（第 9 个，滞后判据）；编排 = **`ui/widgets/readiness_flow.py:ReadinessFlow`**（两页共用：自动体检、**v6.47 一键「⬆ 更新到最新」`update_latest` 与“补齐缺失”合并（整批当前范围增量，共用 `_launch_sync`；`fill_missing` 保留但退位次级）**、`start_calendar_fetch` 挂日历→`trading_target`、滞后用 `trading_days_between`、M2 `_calibrate_asof_date` 抬升上限+`lbl_asof_hint` 回显、**回调绑定各自 scope** —— 改它必跑 `smoke_pages_overlay` 的「STEP 6」段）；成分股失败文案唯一出口 = `constituent_failure_text()`；「全市场扫描就绪」预设 = `bulk_download._apply_scan_ready_preset` |
| 全市场筛选页（M2） | `ui/views/scan_view.py`（状态 + 同名薄壳）。**版式** `scan_layout.py`（阈值⇄控件的**唯一换算处**在 `ScanFilterPane`，界面亿元/% ⇄ 内核元/小数）；**流程** `scan_flow.py`（范围解析 / 后台扫描 / 切日期零成本）；**渲染** `scan_result.py`（KPI 三态 + 结果表） |
| 改图表轴样式 / 净值曲线绘制 | **`ui/widgets/chart_style.py`（唯一来源，v5.13）** —— `apply_pokorny_style`（PlotWidget/PlotItem 都兼容）+ `plot_equity_curve`；业务页面**禁止就地写轴样式** |
| 给图表加"公式叠层"（STICKLINE/公式线/状态柱/DRAWICON） | **两条路都唯一**：引擎语义改 `core/formula/draw.py`；画图改 `ui/widgets/draw_overlay.py` 的 `OverlayPainter`（**入参 = `ChartPane`**，§7-B3）。宿主只做三件事：切窗口（`slice_draws`）、喂 x、扩 y（`overlay_extent`）。**禁止任何页面自己读函数文本再画** |
| 叠层颜色看不清 / 与背景撞色 | **`ui/widgets/chart_style.py` 的 `ensure_contrast()`**（唯一裁决点）。通达信公式按黑底写，本软件是白底 —— 白字黄字必须自动压暗；**不要**在页面里手改颜色 |
| 加"窗格 / 副图 / 主图-副图联动" | **`ui/widgets/chart_host.py`**（P2 已完成；v6.8 起行情页窗格也由它编排）+ 最小 `chart_pane.py`；x 联动/底部轴策略/日期轴/十字光标/钉死高度都在这；**禁止在业务页面自己 `addPlot` 拼窗格**（§10-12） |
| 行情页"成交量 / MACD"副图内容 | **`ui/widgets/indicator_panes.py`**（v6.8）：`fill_volume_pane` / `fill_macd_pane` —— 只往给定 PlotItem 画图元，不建窗格 |
| 改轴外观 / 换轴后重新着色 | **`ui/widgets/chart_style.py` 的 `style_axis()`**（v6.3 抽出，唯一来源）—— 图表宿主切换 `DateAxisItem` 后**必须**调用，否则新轴会退回 Qt 默认黑粗线 |
| 求值时把 draws **按函数段分组** | `core/formula/program.execute_programs_with_draws_grouped`（v6.8）—— 多副图的引擎侧依据；**各段仍共用一个变量池**，勿按目标分组各跑一遍 |
| 加"用户手绘标注"（趋势线/水平线/斐波那契/文字） | ✅ **P6 已完成（v6.10）**：模型+持久化 = `data/annotations.py`（JSON 先 / DB 可迁，API 按 `(标的,周期,id)`）；交互 = `ui/widgets/annotation_layer.py`。**加一种新标注类型** = ① `annotations.py` 加 `KIND_*` + `REQUIRED_POINTS` 条目；② `annotation_layer.py` 的 `_draw_item`/`_points_from_graphic` 各加一个分支；③ 行情页工具下拉加一项。**禁止在页面里自己 new ROII/InfiniteLine** |
| 用户标注"存哪、怎么存" | **`data/annotations.py`**：`~/.jian_data/annotations.json`（原子写）。**坐标一律存日期字符串**（不是 bar 序号）—— 否则数据窗口一变就整体漂移（§11.5-18 同级纪律：公共件入参按最脏情况防御） |
| 联网抓名单/成分股 | **`MarketSyncService.fetch_index_constituents()`**（v6.10 收编）—— **UI 层禁止 import `AkShareFeed`**（§9-H 红线，`tests/smoke_chart.py` 有源码级断言守门） |
| 存/载"公式配方"（函数段 + 参数 + 每段目标窗格） | **`data/formula_store.py`**：`get_formula_store()`（**单例**，两页面共用）+ `make_formula/normalize_segments/segments_as_tuples/segments_as_texts`。⚠ 任何新页面要存公式，**必须用这个单例**，别自己 `FormulaStore()`（会互相覆盖） |
| 行情页 ⇄ 回测页 互送函数 | **`ui/main_window.py`**：`send_formula_to_backtest()` / `send_formula_to_market()` / `switch_to()` —— **两个页面禁止互相 import**，一律经主窗口转交（§3 的"装配与事件分发"职责） |
| 配方库 UI（列表/预览/载入/改名/删除） | **`ui/widgets/formula_library.py` 的 `FormulaLibraryDialog`**（两页共用；新增页面直接用，别复制一份） |
| 载入外来公式后 | 页面侧必须做两件事：① **自动检测**（`detect_function(quiet=True)` / `_compile_formula()`），不能静默塞进去；② 回执说清**来源**（"已从回测页载入 N 段"） |
| 在行情页显示用户函数（像 MA/BOLL） | ✅ **P4 已完成**：编辑器 `ui/dialogs/formula_overlay.py`；图层 = 行情工作台 `ui/views/trading_desk.py` 的 `_formula_layers()` + **`ui/widgets/chart_layers.py` 的 `builtin_indicator_layers()`**（内置指标）→ **同一个 `OverlayPainter`**。加新内置指标 = 在 `builtin_indicator_layers()` 多产一个 `DrawData`，**不要另开绘制分支**（D4） |
| 改内置指标（MA/BOLL）配色 | **`ui/widgets/chart_style.py` 的 `MA_SERIES` / `BOLL_LINE_COLOR`**（v6.6 起唯一来源，原在 market.py） |
| 改"函数参数"输入格式 / 缺参探测口径 | **`core/utils.parse_params_text`** + **`core/formula/program.probe_missing_parameters`**（v6.6 起两页共用**同一份**，别在页面里重写正则或探测循环 —— 否则同一函数会"这页能跑那页缺参"） |
| 改行情页"云端同步"行为 | 行情工作台 `ui/views/trading_desk.py` 的 `sync_cloud`（v5.13 起默认增量：本地有数据=增量、没数据=全量；全量重下在「🗄 数据管理」页） |
| 改回测结果导出 | CSV：**`ui/widgets/backtest_export.py`** 的 `compose_result_csv`（参数快照+逐笔，**不写逐日净值**；页面留同名转发）+ `build_daily_series`（逐日净值+买卖点共同源，供 xlsx）；**xlsx（内嵌净值曲线图+买卖点，openpyxl）：`ui/widgets/backtest_xlsx.py`**（可见「净值曲线」只放图 + 隐藏「净值数据」放逐日行；`_build_workbook` 与存盘解耦）；PNG 报告图：**`ui/widgets/backtest_report.py`**（离屏 grab）；标签/配色/风控文案只改 **`core/backtest.py`**（三处同源）。⚠ CSV 纯文本不能内嵌图，“看图”靠 xlsx/PNG |
| 判断"这笔是赚还是亏"（任何着色/正负号/标记色） | **`core/utils.record_net_amount(record)`**（v6.9）—— 净额 = 平仓盈亏 − 手续费的**唯一取值口径**。**禁止**再手写 `net_profit > 0` 或 `net_profit - commission`（§5.3-B / §9-P1） |
| 改下拉/日期等复合控件的外观 | **`ui/widgets/custom_widgets.py`**：用生成器 `combo_qss()` / `date_edit_qss()` 造新变体，或直接引用 8 个具名常量（`COMBO_QSS` / `COMBO_QSS_SMALL` / `COMBO_QSS_ACCENT` / `COMBO_QSS_EDIT` / `COMBO_QSS_EDIT_OK` / `LINE_COMBO_QSS` / `DATEEDIT_QSS_WARN` / `DIALOG_INPUT_QSS`）。**业务页面禁止就地 setStyleSheet**，且 `::drop-down` 与 `::down-arrow` 必须成对（v6.9：否则箭头消失，§10-9） |
| **给图表加自适应坐标轴**（刻度随缩放变密/换格式、纵轴跟随可视区间） | **`ui/widgets/adaptive_axis.py`（§7-B4 · v6.15）一处**：`attach_date_axis(pane, dates / texts, y_provider=…)`、`follow_y(pane, provider)`、`attach_all(host, dates, providers_by_pane)`。页面只写 `provider(i0, i1) -> (lo, hi)`（回答"这个窗格在可视区间内数值范围是多少"）。**禁止再手写 `setTicks` / `setYRange`**；日期格式梯子只在该文件的 `choose_date_format`（将来分钟线只改这里） |
### 11.5 最容易踩的坑（**全量清单已归档 → `docs/JIAN_PLAYBOOK.md`**）
> ⚠ 本清单**持续累积、只增不减**（已占原文件 8.2% 版面）—— 全文（含每条的血泪细节）在
> **`docs/JIAN_PLAYBOOK.md`**，**编号不变**（`§11.5-25` 仍然叫 `§11.5-25`）。
> 用法：在下面索引里找到相关编号 → 只去 PLAYBOOK 读那一条（省 context，且不会漏）。
> **改动任何模块前，先扫一眼本期相关编号。**

- **11.5-1** 净额 = net_profit − commission
- **11.5-2** trade_time 永远是纯日期 00:00:00
- **11.5-3** 任何"看起来能填其实源里没有"的值，一律 —/降级
- **11.5-4** DB 一律 INSERT OR IGNORE
- **11.5-5** FIFO 必须全局排序后只跑一次
- **11.5-6** 耗时 I/O 一律 QThread
- **11.5-7** 别给复合控件写半截 QSS
- **11.5-8** 行情同步两大铁则
- **11.5-9** 别让两套机制同时 toggle 同一个选择状态
- **11.5-10** 别照着 docstring 改常量
- **11.5-11** 同类防护要做就做全套
- **11.5-12** 图表样式只改 ui/widgets/chart_style.py
- **11.5-13** 【v5.13 修订 · Qt 布局坑】顶部栏末尾的 QLabel 会"吞掉"主区高度
- **11.5-14** 【v6.5 · 最贵的一条】把"静默跳过"改成"报错"之前，先问一句"存量函数会不会被掐死"
- **11.5-15** 【v6.7 · Qt 动态控件的两条硬纪律】
- **11.5-16** 【v6.8 立项 / v6.15 已根治 · pyqtgraph 坐标轴的三个默认行为，全都不是我们要的】
- **11.5-17** 【v6.9 · 复合控件样式的"半截"会让箭头彻底消失】
- **11.5-18** 【v6.10 · pandas Series 不能做布尔判断】
- **11.5-19** 【v6.12 · 跨模块共享的"键"必须有规范化函数】
- **11.5-20** 【v6.12 · 离屏 GUI 脚本的三条打桩铁律】"脚本看起来卡死、毫无输出"几乎总是这三件事
- **11.5-21** 【v6.15 · ViewBox.setYRange 会偷偷加自己的 padding】"y 怎么总比预期宽一…
- **11.5-24** 【v6.18 · 一次性探针的 check(说明, 条件) 参数顺序写反 = 全部断言形同虚设】
- **11.5-28** 【v6.24 · AxisItem.setWidth() 不会立刻生效 —— 断言必须先转一圈事件循环】
- **11.5-29** 【v6.24 · 对齐要统一"预留量"，不是"最大值"】
- **11.5-30** 【v6.24 · FlowLayout 的换行高度会沿父链"静默失效" ⇒ 宿主必须直接钉 minimumH…
- **11.5-31** 【v6.24 · 空的 QLabel 会白占一个 spacing（组件"虚胖"的隐形原因）】
- **11.5-32** 【v6.24 · 冒烟测试不只不能"写"用户真实库，也不能"读"它当依据】
- **11.5-33** 【v6.24 · "静态表 + 动态键" = 三处静默失效】
- **11.5-34** 【v6.24 · 别拿"默认形状"当判据 —— 参数一变就误判】
- **11.5-35** 【v6.24 · 卡头被"拉满的卡片"撑成一个居中巨框 —— 拉伸因子必须显式钉死】
- **11.5-36** 【v6.24 · 收起一个子件，updateGeometry / 父布局 invalidate+activa…
- **11.5-37** 【v6.25 · LinearRegionItem 也不发点击信号 —— "能画出来"不等于"能选中/能删"…
- **11.5-38** 【v6.25 · 箭头/射线的角度必须按
- **11.5-39** 【v6.25 · "回正"类逻辑的判据必须读
- **11.5-40** 【v6.25 · 负向断言的样本别用"将来可能变真"的名字】
- **11.5-41** 【v6.26 · 同名函数会
- **11.5-42** 【v6.26/v6.27 · pyqtgraph 的点击事件：
- **11.5-43** 【v6.26 H-7 · "平移一条线"必须平移
- **11.5-44** 【v6.26 H-7 · 大幅高饱和填充会盖住画面主角 —— 填充是配角，K 线才是主角】
- **11.5-45** 【v6.26 H-7 · "每种类型自己声明的开关"是静默 bug 温床 —— 能推导就别让人声明】
- **11.5-47** 【v6.27 · 预览图元必须不吃鼠标 —— 它就画在光标下，不静音等于"怎么点都落不了地"】
- **11.5-48** 【v6.27 · "看不见" = "画不出来"：依赖视图的角度类工具不能用"屏幕 45°"】
- **11.5-49** 【v6.28 · "手搓假事件"的断言 = 假绿：它把事件系统整个绕过去了】
- **11.5-50** 【v6.28 · pyqtgraph 的点击/拖动事件是"
- **11.5-51** 【v6.28 · "能画出来"≠"能选中"：ROI 家族的三处点击黑洞】
- **11.5-52** 【v6.28 · "用户无法调整"是
- **11.5-53** 【v6.29 · "算出来的主图元"两条专属坑：不夹区间会外推、刚进场景回读会拿到过期坐标】
- **11.5-54** 【v6.29 · 拾取容差的单位必须是
- **11.5-55** 【v6.29 · 界面上看不见的位置，真实鼠标
- **11.5-56** 【v6.29 · "画完立刻回浏览模式"（拍板①）会被断言忘掉 —— 单点类型只画一条就退出绘制态】
- **11.5-57** 【v6.34 · `ds.dataset()` 全量扫会把"缺列"补成"一整列 NaN" —— `col in df.columns` 判不出来】
- **11.5-58** 【v6.34 · 优化前先量"到底是哪一段慢"：per-row 的 Python 循环才是性能真凶】
- **11.5-59** 【v6.35 · 缓存键里少一样 = 静默陈旧；`asof` 进键 = 缓存白做】
- **11.5-60** 【v6.36 · 取消要"抛异常"，不要"返回半成品"；竞态守卫要做成公共件】
- **11.5-61** 【v6.37 · 离屏冒烟里 `isVisible()` 恒 False —— 断言前先把页面切到前台】
- **11.5-62** 【v6.40 · 两套指数代码约定（日线带前缀 / 成分股裸码）—— 复用键必须在边界规范化】
- **11.5-63** 【v6.41 · 异步回包分支要装配与同步分支**同样的状态**；内核警告必须有 UI 出口】
- **11.5-64** 【v6.43 · `adaptive_axis` 的契约是 **bar 序号轴** —— 给 epoch 秒轴喂 `attach_all`，y 跟随会 100% 静默失效】
- **11.5-65** 【v6.43 · 按文件读数时"本地没文件"的标的会被静默跳过 —— 差集必须交给内核记「数据不足」（名单 429→只扫 27 之谜）】
- **11.5-66** 【v6.43 · 异步回包的"早退守卫"不能连占位文案一起跳过 —— "正在体检…"会永远挂在那里（用户以为卡了 3 分钟）】
- **11.5-67** 【v6.43 · 拖动调布局必须用"按下瞬间锁定的参考系" —— 拿实时几何反推 = 布局回流正反馈振荡（"拖一点就失控/单向没反应"）】
- **11.5-68** 【v6.43 · 数据源选列靠"含某字的第一个列"= 定时炸弹（官网 df 的「指数代码」被误当成分列）；测试打桩必须带与线上一致的列结构】
- **11.5-69** 【v6.43 · `QHeaderView.ResizeToContents` × 大表逐格 setItem = 平方级冻死 UI；填表三件套：关更新 → 一次性测宽 → tooltip 只给必要列】
- **11.5-70** 【v6.44 · 新增“记住上次”类偏好键会在构造期从**真实** preferences 泄入 → 冲乱默认顺序断言（且误写真实库）；`Preferences` 单例 import 时已载入真实值，光重定向 `path` 不够 ⇒ 必须在 **stub `save` 之后**把用户态在内存里抹平】
- **11.5-71** 【v6.46 · §7-B10-M1】三坑同体：① **回测静默截断** —— 本地日线滞后时 `BacktestEngine` 会把 `data<=end_date` 截到旧末日而不告知 ⇒ 默认终点必须走日历算“最近已定稿交易日”且回测前滞后自动补、补不到**回退+回执**（`_apply_end_date_receipt`，只回退不前移）；② **构页自启的 QThread Worker 会在离屏冒烟里真联网 + 写真实目录** ⇒ 测前必须把 `CalendarWorker` 打桩为不 `start`（并发到 `~/.jian_data/trade_calendar.json`，防污染自检名单要加）；③ **冒烟脚本里同名模块别名（`_bflow`）会被后续段落重新绑定成别的模块**（breadth_flow）⇒ 给新模块用**唯一别名**，否则 monkeypatch 打到错的模块、真线程偷偷跑起来
- **11.5-72** 【v6.47 · §7-B10 M2/M3】① **滞后提示必须用真日历而非 busday**——节假日用 busday 会虚报“滞后”，而拿不到日历时“不提示”远胜于“猜错”（`format_stale` 三参任一缺 → 空串）；② **合并“补齐缺失”为一键后，`set_empty` 只有一个动作位** —— 新旧两语义（缺/旧）共用 `update_latest` 单入口、`fill_missing` 退位次级（方法保留），别再往空态塞第二个按钮；③ **两页都在构页时 `start_calendar_fetch`** → 测前除 M1 外还要在 `readiness_flow` 命名空间把 `CalendarWorker` 打桩（同一桩类复用，§11.5-71②）；④ **就绪度“本地最新”=全局 max 会被单只刚同步的标的掩盖**（昨天扫的 300 只，今天只同步 1 只→latest=今天→M2 基准日默认跳到今天→其余 299 当天无行全判“数据不足”）⇒ 滞后用 `representative_latest`（中位日）、另报 `coverage_at(基准日)` 诚实提示“仅 N/total 有数据”（就绪≠扫描：就绪=历史行数够、扫描=基准日当天有行，两套口径）
- **11.5-73** 【v6.47 · 窄屏不撑窗（用户明令）】工具栏/摘要条的**单行 QLabel 绝不能塞长文本**——`QLabel` 不包字时 `minimumSizeHint` = 整串宽度，会把窗口**最小宽度**顶大，窄屏/小屏直接铺不开。做法：**单行标签只留短状态 + 一个“⚠”短标记，长说明进 tooltip 或结果区（`lbl_empty` 已 wordWrap，可换行）**；并给这类单行标签设 `setSizePolicy(QSizePolicy.Ignored, Preferred)` 使其**可缩不撑窗**（已用于 M2/M3 `lbl_receipt` 与 M1 `lbl_range_note`）。新加任何顶部回执都遵此模式。
- **11.5-74** 【v6.48 · §7-A2 回测图表导出】① **CSV 是纯文本、物理上不能内嵌渲染图**——用户看到的“图形绘制/QSD/GLX/STICKLINE”只是公式源码被当注释写进去了，不是数据也不是图；要“打开即见图”只能 .xlsx（openpyxl LineChart）。② **买卖点 marker 的 y 必须用“成交日净值”定位、不是成交价**——成交价与净值不同量纲，直接画会跑出坐标轴。③ **openpyxl 读回会丢图表**（`load_workbook` 不重建 chart）⇒ 测图只能对**构建时的 Workbook 对象**（`_build_workbook`）断言 `ws._charts`，不能存回再读；写盘用 BytesIO 不污染用户目录。④ **逐日全量很占空间、主表刷屏**（用户反馈）⇒ 不抽稀，而是把逐日数据放**隐藏 sheet「净值数据」**、图放可见 sheet（图表 Reference 跨表引用、`plotVisOnly=False`）；**CSV 干脆不写逐日段**（看图靠 xlsx）。


### 11.6 当前"下一步做什么"的推荐顺序（历史刷新**倒序**排列：主清单之下**第一块就是最新**）

> **v6.48（§7-A2 回测结果图表导出 · 1.36 · 2026-09-22）**
> 用户实测“CSV 里图表完全无法显示”→ 根因：CSV 纯文本不能内嵌图（那一大段“图形绘制/QSD/GLX”只是公式源码）。做法：
> ① **`build_daily_series(result)`**（`backtest_export.py`）——逐日净值 + 买卖点（取 equity+trades，**单一事实源**）；
> ② **CSV 不写逐日净值**（用户反馈“逐日全量太占空间”）——回到参数快照 + 逐笔成交；看图交给 xlsx；
> ③ **新增 `ui/widgets/backtest_xlsx.py`**——openpyxl **内嵌真正的净值曲线图 + 买卖点 marker**（成交日净值定位、落在曲线上）；逐日数据放**隐藏 sheet「净值数据」**、图放可见「净值曲线」（主表只剩图）；导出菜单加「📊 导出 Excel 图表…」；`_build_workbook` 与存盘解耦。
> 验收：`smoke_chart` 745 / `smoke_pages_overlay` 514→**521** 全绿 + compileall（xlsx 对构建时 Workbook 断言，openpyxl 读回丢图；BytesIO 不落盘）。坑=§11.5-74。
> **下一步** = §7-A4 回测历史存档（远期）/ §7-B8 余量与其它 backlog。

> **v6.47（§7-B10 全案收官 · 1.35 · 2026-09-22）**
> 承 v6.46 M1 切片，补齐 §7-B10 STEP 2–4（M2/M3）并**发版 1.35**（三处同步）：
> ① **一键「⬆ 更新到最新」**——`ReadinessFlow.update_latest()` 对**整批当前范围**跑 `SyncWorker` 增量（缺的补、旧的拉到最近交易日、已新鲜的自然 skip），与“补齐缺失”**合并**为单一空态动作（共用 `_launch_sync`，`fill_missing` 退位次级保留）。
> ② **滞后提示**——`start_calendar_fetch()` 挂 `CalendarWorker` → `trading_target`；`_render_readiness` 用 `trading_days_between`（真日历精确数）+ `format_stale`（`data/readiness.py` 零 UI）出“约 N 交易日滞后”；离线不提示不猜。
> ③ **M2 基准日诚实化**——`scan_layout` 新增 `lbl_asof_hint`；`_calibrate_asof_date` 抬升 `date_asof` 上限并回显（M3 无 date_asof 不适用）。
> ④ **（用户实测后修正）覆盖诚实提示 + 滞后不被单只掩盖**——“就绪 299/300”与“扫描 1/300”不矛盾（就绪=历史行数够、扫描=基准日当天有行）；根因是 `report.latest` 用**全局最大值**，单只刚同步的标的会把基准日默认拉到今天。修：`probe_readiness` 收集每只 last 分布→`representative_latest`（中位日，滞后用它）+ `coverage_at(基准日)`；`_render_readiness` 新增“基准日当天仅 N/total 只有数据→先更新/往前挪”提示（**不改基准日默认算法**，只加诚实提示）。
> 验收：`smoke_chart` **745** / `smoke_pages_overlay` **514** 全绿 + compileall；两页起 `CalendarWorker` 测中均打桩不联网。坑=§11.5-71/72。
> **下一步** = §7-B8 余量（R4 组合配置独立远期 / R12 暂缓）与其它 backlog（§7-A/C/D）。

> **v6.46（§7-B10-M1 切片 · 未发版 · 2026-09-22）**
> 用户实测 M1 单股回测“区间末日总是旧日” → 拆出一个定稿守卫 + 真日历 + M1 默认终点修复的最小切片：
> ① **定稿守卫（STEP 0/1）**——`sync_service` 新增 `DAILY_SETTLE_HHMM`/`is_daily_bar_settled`（纯函数）/
> `_drop_unsettled_tail`，`refresh_one` 落盘前对日线类分区裁“今天未定稿”那根（分钟不裁）。
> ② **真交易日历**（推翻 §7-B10 原 F「不引日历」）——`akshare_feed.fetch_trade_calendar` +
> `data/trade_calendar.py`（`load_or_fetch` 当日 JSON 缓存+失败回退 / `latest_settled_trading_day`）+
> `ui/workers.CalendarWorker`（一次性后台抓，异常回 None）。
> ③ **M1 区间修复**——`backtest.py` 构页起日历抓取 + `lbl_range_note` 回执行；`backtest_flow` 三方法
> （`_on_calendar` 精修默认终点 / `_prepare_stock_then_run` 滞后自动联网补 / `_apply_end_date_receipt`
> 补不到回退有数据那天+同步 `last_meta`，只回退不前移、绝不静默截断）。
> 验收：`smoke_chart` **745** / `smoke_pages_overlay` **514** 全绿 + compileall；新增防污染自检项
> `trade_calendar.json`（测中 CalendarWorker 打桩不联网）。坑=§11.5-71。
> **下一步** = §7-B10 STEP 2–4（M2/M3「更新到最新」入口 / 滞后提示 / 基准日诚实化）；发版时三处版本号 1.34→1.35。

> **v6.44（§7-B8 R7 副图换序收尾 · 1.34 · 2026-09-22）**
> R7 三步收尾（用户 2026-09-21/22 实测确认手感）：① **模型层（零 Qt）** —— `layer_model`
> 新增可持久化副图顺序 `set_sub_order/move_sub/apply_order/sub_order_keys`，构造收 `order=`；
> **换序只改格位、绝不改 target**（源码级断言钉死）。② **持久化** —— `desk_ui.sub_order` 落盘，
> `trading_desk` 构造与 `desk_formula._rebuild_model` 均带序（增删改名配方不丢顺序）。
> ③ **UI** —— 配方页「⇅ 副图换序」：⬆⬇ + **拖拽**（复用 `DragHandleListWidget` 三道闸 +
> 边缘自滚；拖完 `rowsMoved → QTimer.singleShot(0) → apply` 绝不在信号里重建列表）；
> `desk_formula` 四方法 + `trading_desk` 薄壳。旧的两条 stash 半成品（假弹窗 + 坏 docstring）作废。
> ④ **测试隔离补正** —— 新键 `sub_order` 与 breadth 显示前置（ratio/chart/overlay/index_style）
> 会在构造期从**真实** preferences 泄入（`Preferences` 单例 import 时已载入真实值，重定向 path
> 也来不及）→ 冒烟脚本在 **stub `save` 之后**把用户态在内存里抹平，让窗口以默认序起来（§11.5-70）。
> 验收：`smoke_chart` **721** / `smoke_pages_overlay` **493** 全绿 + compileall；未改 M2/M3 与产品口径。
> **下一步** = §7-B8 余量（R4 组合配置为独立立项、需新引擎；R12 数据页暂缓）与其它 backlog。

> **v6.43（§7-B1/B2 STEP 6.5 · M2/M3 体验修复轮 · 1.33 · 2026-09-21）**
> 用户两轮真机实测反馈驱动的修复（"图不可读 / 日期不能先选 / 一点就卡死 / 名单缺斤短两还不说"）：
> ① **M3 图表可读性根治** —— `breadth_chart` 改 bar 序号轴（adaptive_axis 的 y 跟随此前 100% 失效，
> §11.5-64）+ 指数按日对齐只画当前区间 + 柱状/折线双视觉（默认柱状+MA5，家数刻度取整）+
> 指数四图形（折线/面积/K线/美国线，新图元 `OhlcBarItem`，缺开高低退折线）+
> `ChartHost.enable_divider_drag` 分界把手（可见 + 按下锁定参考系，§11.5-67）+ 两窗格轴对齐
> （R8 第二版固定左槽，对齐不留白）。② **M2 先选后扫** —— 基准日日历自由选（默认=本地最新交易日，
> 体检回包校准）+ 内核轴外就近落位（平手取前一日，回执出声）+ ◀▶/日历双向同步。
> ③ **缺数据全链路诚实化** —— `scan(missing=…)` 无文件标的逐只记「数据不足」进总数（读数为空
> 也不回空白，§11.5-65）；扫描前闸门二次确认；体检占位文案不再冻结（§11.5-66）。
> ④ **成分股换中证官网权威源**（同花顺 300→288/500→429 缺斤短两）+ 快照日期/名义只数核对上界面
> + 修「指数代码」选列回归（§11.5-68）；幸存者偏差已界面声明，根治路登记 **§7-D 类 D4 时点成分股**。
> ⑤ 表格性能三件套（§11.5-69）+ 2000 行截断说实话；⑥ 冒烟断言方法论补正："挂了跟随器"≠"y 真的跟随"
> —— 新增缩放后 y 数值范围/刻度可见/真实鼠标拖动模拟断言；测试不许依赖用户真实偏好（overlay/index_style
> 隔日误报实锤）；顺手根治 vline 拖拽断言的 1px flaky（抓取点改取 viewbox 中线）。
> 验收：`smoke_chart` **707** / `smoke_pages_overlay` **482** 全绿（连跑两轮验稳）+ compileall；
> 联网实测沪深300 → 300 只不含 000300 快照 2026-09-18。
> **下一步 = 用户实测手感（分界线/闸门/四图形）→ STEP 8 发版收尾**；§9.3 代理文案待修清单仍挂。

> **v6.39（§7-B1/B2 STEP 6 联动收尾 · 1.30）**
> 交付：`data/readiness.py`（footer 只读体检）+ `ReadinessWorker`（第 8 个 Worker）+
> `ui/widgets/readiness_flow.py`（M2/M3 共用控制器：体检→缺口可见→⬇补齐缺失→复检）+
> M2/M3 成分股失败改 `friendly_constituent_message` 人话诊断 + bulk_download「⚡全市场扫描就绪」预设。
> **三项实测**（用户要求"必须真正拿到股票、出问题说清原因"的直接回应）：
> ① 成分股链路真机联网验证通过（000300→288 只 / 000905→429 只，8~14 s ⇒ 解析中界面注明耗时）；
> ② footer 体检 0.66 ms/只（全市场 ≈3.6 s，后台跑）；
> ③ 真机 368 只扫描 2.89 s（7.85 ms/只）⇒ 外推 ≈42 s ⇒ **决策接受引擎路径，STEP 7 暂不排期**。
> 验收：`smoke_chart` **692** / `smoke_pages_overlay` **457** 全绿 + 全仓 compileall。
> ⚠ D6-4（缺口按成交额优先）与 D6-5（问题清单回流数据管理页）做了如实变通/部分项，见 G-STEP 6。
> ⚠ **并行会话**：Qoder 正在施工 §7-B8 R7（desk_formula/desk_layout/test_r7_sort 三文件未提交），
> 本轮不含；**app 当前可能起不来**（desk_layout 引用尚未建成的页面薄壳）—— 等 R7 收尾或 stash 恢复。
> **下一步 = 用户手动实测**（先自选小范围 → ⬇补齐缺失 → 全A）→ STEP 8 收尾。

> **更早更新块（v6.38 STEP 5 / v6.31 立项）→ 已搬 `docs/JIAN_HISTORY.md` §8 全表**
> （v6.43 按 §10-14"先搬走再写新内容"；立项 6 条拍板见主案 A 节，STEP 5 交付见主案 B2/G 节）。

### 11.7 收工前自检清单
- [ ] 改动的模块状态（`[x]` / `[~]` / `[ ]`）在 §6 / §7 同步了吗？
- [ ] 有没有引入新的"UI 直连 SQL/爬虫"？（§9-H）
- [ ] 净额口径有没有被绕过？（§5.3-B）
- [ ] 虚构数据了吗？（时间 / 价格 / 持仓）
- [ ] 耗时 I/O 走 QThread 了吗？
- [ ] 新发现的技术债写进 §9（**仍在生效的**）或 §9.H 台账（**历史项 → `docs/JIAN_ARCHIVE.md`**）了吗？
      本次摘要写进 §8 的「最近三版」表 +（**只追加**）`docs/JIAN_HISTORY.md` §8 全表了吗？
- [ ] **改动前扫过 `§11.5` 编号索引、去 `docs/JIAN_PLAYBOOK.md` 读过本期相关坑了吗？**（别重犯血泪）
- [ ] **改了常量/数值，同文件与跨文件的 docstring / 注释同步改了吗？**（§9-O3、§11.5-10）
- [ ] **改了文件规模？** → 只有**越线（≥400 行）**的文件才需要在 §4 更新行数（v6.16 新口径：
      <400 行一律不标数字，**不必**为了行数返工）；越线了就在§4 标上并注意别再往里堆。
- [ ] **要 push 了吗？→ 版本号 +0.01，且三处同批同步**（v6.16 新纪律 · §9-A）：
      ① git commit message 首词（形如 `1.21`）；② `config/settings.py:APP_VERSION`；
      ③ 仓库根 `version.json`。⚠ 顺便确认 `version.json` 的 `url` 仍指向
      **项目 Releases 页**（正式发版时才需要换成具体版本的下载直链）。
- [ ] 同类防护（竞态守卫 / 口径 / 文案）是不是只改了一处、漏了另一处？（§11.5-11）
- [ ] **改了公式引擎 / 图表渲染 / 图层公共件 / 控件样式（含 `SegmentedControl`）/ **工具行 chips 规则（`chip_mru`）** / 标注模型 / 配方库 / 周期重采样（含**分钟档位**）/ 自选股 / 复权口径 / 图元拖动 / 坐标轴 / 图表宿主读数条（§7-B6）/ 回测成交口径（§7-B5）/ **数据源护栏（§9-V：非正价拦下 · 兜底源单位统一）** / **K 线图元画法（§9-V-3：一字板横档）** / **画线类型规格表 / 附属图元 / 图元小件 / 绘制会话 / 画线填充配色（`chart_style.annotation_fill`）**（即 `annotation_shapes` / `annotation_decos` / `annotation_items` / `annotation_draw_session` / `chart_style` 任一文件），跑过 `py tests/smoke_chart.py` 吗？**（**745 项**，纯组件、离屏）
- [ ] **改了行情工作台页面（`trading_desk.py`）/ `ui/widgets/desk_*.py` 任一模块 / 回测页「成交模型」行 / 标注交互层 / **画线类型目录（新增类型、`implemented` 翻牌）**？** → 跑 `py tests/smoke_pages_overlay.py`（**521 项**，含 **§7-B6 的「迁移护栏」+ 顶栏分段控件/分钟档位 + 工具行 chips + 图标轨/分页面板/折起（含**富余宽度归图表、折起后左侧只剩图标轨**两条不变量）+ 读数条 + **口径回执的"除权跳空定位 / 数据体检"**+ STEP 6 的"实现落在哪个 `desk_*.py`"**：公共面被改名、旧入口（`cb_period`/`cb_adjust`/`cmb_tool`）被复活、**把薄壳写成空函数**、**分栏比例退化**、**回执退回"不解释"**，都会立刻红）；
      并在其收尾的防污染自检名单里**加上任何新写的 `~/.jian_data/*.json`**（现在有 annotations /
      formula_library / watchlist / backtest_strategies / **preferences（1.23 起）** 五个）
- [ ] **改了复盘页（`ui/views/review.py`）/ `ui/widgets/review_*.py` 任一模块？** → 跑
      `py tests/smoke_pages_overlay.py`（**521 项**，含 **「复盘页迁移护栏」+ §9-U 分栏不变量**：
      公共面被改名、**把薄壳写成空函数**、宏观/微观**分栏退化成写死的 5:4 平铺**、
      分栏高度不落 `review_ui.v_sizes`，都会立刻红）
- [ ] **改了全市场筛选页（`ui/views/scan_view.py`）/ `ui/widgets/scan_*.py` 任一模块？** → 跑
      `py tests/smoke_pages_overlay.py`（**521 项**，含 **「M2 公共面护栏」+ 版式与口径不变量**）。
      ⚠ 六条最容易顺手改坏的：① **常驻行必须 ≤3**（粗筛阈值收在抽屉里，别往结果区上方加行）；
      ② **阈值"内核 ⇄ 界面"换算只许在 `ScanFilterPane` 一处**（界面亿元/% ⇄ 内核元/小数，
      换手率/市值**关闭时必须是 None**，变成 0 = 误杀一片）；
      ③ **非扫描基准日的数值列必须是 '—'**（缓存只存状态矩阵，D3 —— 拿旧快照冒充当日 = 静默错值）；
      ④ 复权口径必须**印在界面上**且只有前复权一种（D8）；
      ⑤ **基准日控件必须"扫描前就能用"且 asof 真传给内核**（v6.43 用户拍板：不许先扫后选；
        轴外日子由内核就近落位+回执出声，不许整轮"全市场数据不足"空跑）；
      ⑥ **缺数据闸门不许删**（`_confirm_scan_with_gaps`：体检有缺口/未完成 ⇒ 二次确认才能扫，
        选「否」不得启动任何线程；本地齐了不打扰）
- [ ] **改了广度统计页（`ui/views/breadth_view.py`）/ `ui/widgets/breadth_*.py` 任一模块？** → 跑
      `py tests/smoke_pages_overlay.py`（**521 项**，含 **「M3 公共面护栏」+ 双窗格/区间/增量不变量**）。
      ⚠ 七条最容易顺手改坏的：① **常驻行必须 ≤3**（⚡/⟳ 收在摘要条，别往结果区上方加行）；
      ② **双窗格必须 x 联动**（`ChartHost` 编排，禁止页面自己 `addPlot` 拼副图，§10-12）；
      ③ **广度占比的分母 = 有效样本**（命中+未命中）—— 换成"全市场只数" = 系统性压低且看不出来；
      ④ **切区间 = 纯切片零成本**（不许在区间切换里进线程/读盘，D3）；
      ⑤ **全量重算必须过二次确认**（危险动作隔离，§10-10 —— 把确认框删了立刻红）；
      ⑥ **图表 x 必须是 bar 序号轴**（§11.5-64：喂 epoch 秒给 `attach_all` 会让 y 跟随静默失效；
        断言验的是"缩放后 y 数值范围真的跟随"，不是"挂了跟随器"）；
      ⑦ **分界把手/双视觉/四图形的开关只换画法不动数据**（柱状=BarGraphItem+MA5 主线、
        折线=旧形态；指数缺开高低列必须退折线而不是画假四价）
- [ ] **改了 ⚡ 增量续接（`data/scan_store.py` 的 `find_base` / `merge_tail`）吗？** → 跑
      `py tests/smoke_chart.py`（「STEP 5 · ⚡ 增量到最新」段）。⚠ 四条红线：
      ① **增量合并 == 全量重扫逐位一致**（合并悄悄改变结果 = 最阴的静默错值）；
      ② **历史一天都不动**（旧日期的矩阵/家数必须与首轮结果逐位相同，D7 用户契约）；
      ③ **touch（无新交易日）= 沿用原矩阵 + 回执明说**（不许静默重算，也不许假装增量了）；
      ④ **标的集合变了不许硬接矩阵**（行序不同硬接 = 错位污染，必须诚实退化全量）
- [ ] **改了就绪度体检 / 补齐缺失（`data/readiness.py` / `ui/widgets/readiness_flow.py` / `ReadinessWorker`）吗？** → 跑
      `py tests/smoke_chart.py`（「STEP 6 · 就绪度体检」段）+ `py tests/smoke_pages_overlay.py`
      （「STEP 6 · 体检/补齐/诊断」段）。⚠ 五条红线：
      ① **四分类不许并桶**：历史不足（partial）不是"未下载"（补不齐 ≠ 可补齐），坏文件必须进问题清单；
      ② **只读 footer**（不许为了体检去读数据行 —— 那会让"扫描前体检"变成第二场扫描）；
      ③ **体检回调必须绑定各自 scope**（旧范围的迟到进度/回包一律丢弃 —— 否则会覆盖新范围提示或扫描回执）；
      ④ **已有扫描结果后，体检不得写回执**（回执区属于扫描）；但**占位文案里的"正在体检"必须被更新**
        （v6.43 §11.5-66：早退守卫连文案一起跳过 = 永远挂着"正在体检…"骗人）；
      ⑤ **更新到最新与“补齐缺失”已合并为单入口**（v6.47）：`update_latest` 对整批当前范围跑增量（缺的补/旧的拉到最新/已新鲜自然 skip，`fill_missing` 退位次级保留）；滞后提示走真日历（`trading_days_between`/`format_stale`，**离线不提示、不许 busday 虚报**）；partial 如实解释不假装能修；成分股失败文案必须走
         `constituent_failure_text()`（**不许再裸甩"接口未返回成分股"**）
- [ ] **改了后台扫描线程（`CrossSectionWorker`）或竞态守卫（`JobGuard`）吗？** → 跑
      `py tests/smoke_chart.py`（「STEP 3 · CrossSectionWorker」+「STEP 5 · 增量 Worker 通道」段）。⚠ 三条红线：
      ① **取消必须抛 `ScanCancelled`、不许"返回部分结果"**（半成品矩阵的占比全错且看不出来）；
      ② **`job_id` 必须原样回包**（页面靠它丢弃迟到回包；改名或吞掉它 = 竞态守卫静默失效）；
      ③ 异常**绝不穿透 QThread**（要么 `finished(job, None)`、要么 `failed(job, msg)`，不许无回包）
- [ ] **改了会话缓存（`data/scan_store.py`）或它的键吗？** → 跑 `py tests/smoke_chart.py`
      （「STEP 2 · 会话缓存」段）。⚠ 三条红线：① **键里少一样 = 静默陈旧**（尤其**粗筛阈值**
      与**数据版本**）；② `asof` **不许**进键（进了就变成"每换一天重扫一次"，缓存白做）；
      ③ 本模块**不许写盘**（有源码级断言钉着 —— 它一旦落盘，防污染自检名单必须同步加）
- [ ] **改了横截面内核（`core/cross_section.py`）或它的阈值/三态口径吗？** → 跑
      `py tests/smoke_chart.py`（其中的「**§7-B1/B2 STEP 1 · 横截面内核**」段）。
      ⚠ 三条最容易被"顺手改坏"的：① **"数据不足"被算成"未命中"**（新上市 / 停牌 / 缺列 / 当日无行）；
      ② **M3 的分母被换成"全市场只数"**（占比立刻被系统性压低，而且**看不出来**）；
      ③ `prepare_frame` 与 M1（`core/backtest.py`）**口径分叉** —— 有**源码级**断言钉着，**别绕过它**
- [ ] **动了图表的刻度或量程吗？** → 一律走 `ui/widgets/adaptive_axis.py`（§7-B4），
      **禁止页面手写 `setTicks` / `setYRange`**；要改日期格式只改 `choose_date_format`；
      设了 y 范围又想断言它 → 必须 `setYRange(..., padding=0)`（§11.5-21：pyqtgraph 会偷加 padding）
- [ ] **新增或修改了任何"盈利 / 亏损"判定吗？**（着色、正负号、标记色、高亮带方向）
      必须走 `core.utils.record_net_amount(record)`，**不许**手写 `net_profit > 0`（§5.3-B / §9-P1）
- [ ] **改了 `QComboBox` / `QDateEdit` / `QDateTimeEdit` 的样式吗？**
      → 只能用 `custom_widgets` 的常量（`::drop-down` 与 `::down-arrow` 必须成对，否则箭头消失）；
      改完跑 `py tests/smoke_chart.py` 看**箭头像素断言**（§11.5-17）
- [ ] **改了回测页/工作台/复盘页的叠层、检测、图层开关、公式对话框、窗格编排、用户标注、配方库/互送、自选股/周期/复权、成交模型行，跑过 `py tests/smoke_pages_overlay.py` 吗？**（**521 项**，页面级；标注与配方一律用**临时库**，脚本末尾还有"用户真实库未被写"的**防污染自检**（现含 `backtest_strategies.json`）；三条离屏打桩见 §11.5-20，**别删**）
- [ ] **新加了"往用户数据目录写文件"的功能吗？** → ① 用 `tmp + os.replace` 原子写；② 给 `tests/smoke_pages_overlay.py` 的收尾自检加一行文件名（§11.7 上一条）；③ 单条坏数据必须**跳过自己**而不是拖垮整库；
      ④ ⚠ 若它会**自动落盘**（"记住上次"类偏好，如 `backtest_ui` / `desk_ui`）→ **必须在冒烟脚本里
      把偏好单例的 `path` 重定向到临时目录**（只给 `Preferences.save` 打桩**实测不够**，仍被写脏过一次），
      否则跑一次测试就把用户真实偏好写脏（STEP 3c 真踩到，已修 + 两次回滚）
- [ ] **新加了数据湖分区吗？** → 三处都要登记：`market_db.zones`（否则 `_get_filepath` 直接抛"未注册的存储区"）、`data_manager.ZONE_ORDER/ZONE_LABELS`（否则管理页看不到）、`SYNCABLE`（若能联网同步）。参考 v6.13 的 `kline_daily_raw`
- [ ] **新增了任何"用户要填 / 要选"的参数或档位吗？** → 四问：
      ① 文案里有没有**内部术语当唯一解释**？② 有没有**行内常显说明**（不是 tooltip）？
      ③ 关键概念有没有**示例弹窗**？④ 术语有没有换成**用户量纲**（"1 跳"→"0.01 元"、
      "当根"→"当天"）？参数是否只在**有意义的档位**才出现？
      （§10-10 追加条款 / §11.5-22；参考 `fill_mode_oneliner` + `ui/dialogs/fill_model_help.py`）
- [ ] **让用户手动测一把了吗？** 离屏断言只能证明"逻辑通了"，**手感**（拖动跟不跟手、字会不会被遮、面板会不会截断）只有真跑一次才知道（§10-10）
- [ ] **新增了任何"联网抓取"吗？** 必须走 `MarketSyncService`（含成分股这类一次性名单查询）——
      **UI 层禁止 import `AkShareFeed`**，`tests/smoke_chart.py` 有源码级断言守门（§9-H / §9-T4-①）
- [ ] **新增/移动/删除了文件吗？** → 按 §10-13 归置：根目录白名单只放门面（`main.py`/`requirements.txt`/
      `version.json`/`JIAN_RULES.md`/`.gitignore` + 层目录 + `scripts|tests|samples`）；
      子目录脚本改 `__file__` 反推仓库根；同批更新 §4 目录地图 + 全文旧路径引用（含**用户可见文案**）；
      临时探针与输出**用完即删**；删文件同批 `git rm`
- [ ] **动了数据源/落盘护栏吗？（`data/akshare_feed.py` 的 `drop_unusable_price_rows` /
      `em_volume_to_shares`、`data/sync_service.py` 的取数分区）** → 跑 `py tests/smoke_chart.py`
      （**745 项**：非正价行必须被拦下、兜底源成交量必须 ×100 成「股」、量纲接缝判据不许误报
      单日放量/不许漏报持续换单位）；⚠ **降级到兜底源时必须在出口统一量纲**（§9-V：单位不一致
      会让同一分区里同时存在"手/股"两种单位，量能副图出现 100× 台阶）
- [ ] **动了 K 线图元（`CandlestickItem`）或其它"图形绘制"吗？** → ⚠ 记住：**"数据对不对"与
      "看得见看不见"是两件事**（§9-V-3：一字板实体高度 0 ⇒ 老画法只剩 1px 横线，缩小时几乎
      看不见 = 用户报的"显示问题"）。改完除了跑 `smoke_chart` 的像素断言，**还要在最小缩放
      （150 根/屏）下人眼确认一次**：一字板/十字星这类"零高度实体"必须仍看得见
- [ ] **改了 `ui/widgets/function_segments.py` 吗？**（回测页与行情页**共用**）
      → 两个 smoke 都要跑，并按 §11.5-15 检查"子控件数 == 布局管理数"
- [ ] ⚠ **动了 `parse_program` 的接受/拒绝行为（尤其"警告升级为报错"），
      拿 `samples/实例函数.txt` 端到端跑过一遍吗？**（§9-Q-4 事故教训：用户存量函数不能被打断；
      验证用临时脚本，跑完即删 —— 用户私有公式不入仓库，§10-6）
