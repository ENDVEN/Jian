# Jian — 开发规范与上下文记忆 (文档 v6.50)

> **本文档是"给未来的你看"的权威记忆**，但它现在**分册**了 —— 目的是让**本文件能被一次读完**
> （v6.32 前它是 297k 字符，而单次读取上限只有 100k ⇒ 物理上读不完，只能检索 ⇒ 遗漏 + 误信旧数字，
> 已经真实造成过一次版本号事故）。**本文件只放"现在是什么 / 必须遵守什么 / 下一步做什么"；
> 历史与操作手册按下表去 `docs/` 取。**
> ⚠ **v6.50 又超了一次**（118k → 搬走 45k → **73k**）：按 §10-14「先搬走，再写新内容」把
> **逐文件代码地图**拆去 `docs/JIAN_CODEMAP.md`、把 **§7-B1/B2 / §7-B10 两份已收官主案**与
> **§11.6 历史刷新块**搬去 `docs/JIAN_ARCHIVE.md`。**下次再加内容前先量字符**（见 §11.7 末条）。

## ⭐ 当前状态快照（每次开工先读这一段）

| 项 | 值 |
|---|---|
| APP 版本 | **1.40**（三处同步 §9-A：`APP_VERSION` ✅ / `version.json` ✅ / **commit 首词待用户提交**） |
| 文档版本 | **v6.55**（§7-E5 下载层新鲜度对齐真交易日历：周末/节假日/盘中不再空转全池；用户实测反馈驱动。E1–E3 已提交 `c969112`/`0e080c0`/`96abc3f`，E4 闸门结案） |
| 最近三版 | `1.40` §7-E5 下载层日历感知跳过 · `1.39` §7-E3 日线列白名单 · `1.38` §7-E2 代理失败说人话+熔断提前 |
| **当前主线** | **§7-E 施工队列（E1–E4 闭环 → 追加 E5 已落地 1.40）**；**push 待用户**（领先远端 6）。**下一步候选** = §7-B4 回测进阶（复用 `TradeAnalyzer` 绩效维度 + 每回合明细持久化）/ 深色主题（用户原定"功能差不多了再统一做"，四个回测子模块已全部收官，**可能已到该时点**）/ §7-E5 的后续性能档（并发 / 批量快照通道，见 §7-E5 备注，**须用户拍板**） |
| **断点** | **v6.49（1.37）§7-A4 回测历史存档 ✅（v6.49 复核重做）**：存储 = `data/backtest_archive.py`（不可变快照：每份 `<时间戳_uuid>.json` + 轻量索引 `_index.json`；save/list/load/pin/delete/淘汰/防注入）；**版式 = `ui/widgets/backtest_history_ui.py`（1.22 同款分工：过滤条 / `HistoryTable` / `MiniEquityChart` / `HistoryPreviewPane` / 页脚设置），页面 `ui/views/backtest_history.py` 只持状态与接线**（市场回测页第 4 子页「运行历史」：列表+预览+载入查看/复用参数/重跑/送行情页/★重点/删除）。每次回测默认自动存档（偏好 `backtest_archive.auto` 可关；发起瞬间定格 `_last_config` 保证"存档=跑的那次"）；逐笔全量 + 净值抽稀≤250（**端点保底 + 并入全部成交日**）；每标的20/总500 滞动淘汰、**重点豁免**；文件名 uuid 防注入、单文件≤2MB；**读路径绝不写盘**；schema 带 kind 预留 M2/M3（本轮只 M1）。M1 视图新增 `show_archived`（**只读回放：保存/恢复现场 + 预览期禁导出 + 黄色横幅与「退出预览」**）/`exit_preview`/`load_archive_config`/`save_to_history`（导出菜单「💾 存为历史快照」）；结果区净值曲线**新增买卖点散点**（`buy_at`/`sell_at`）；`StrategyBridge.apply_payload` 抽出复用。验收：`smoke_chart` **782** / `smoke_pages_overlay` **554** 全绿 + compileall（存档测试全用临时 root；防污染自检含 `backtest_results`）。坑=§11.5-75。**（v6.50）文档瘦身已完成**：主文件 **118k → ≈73k 字符**（逐文件地图 → `docs/JIAN_CODEMAP.md`；§7-B1/B2 + §7-B10 主案与 §11.6 历史块 → `docs/JIAN_ARCHIVE.md`）。**（v1.38）§7-E2 已落地**：代理失败"说人话" + 熔断提前 —— `_classify_error` 先判 `proxy` 文本指纹（⚠ `requests.ProxyError` 也是 `OSError` 子类，顺序错就被吞成 network）、三出口文案各一档（**不写死 `127.0.0.1:7897`**）、`proxy_circuit_breaker=3`、`abort_reason_text` 三消费方共用、`bulk_download` 竞态判据收编 `JobGuard`；smoke **796 / 557** 全绿。**（v1.39）§7-E3 已落地**：日线落盘**列白名单** —— `DAILY_KEEP_COLUMNS`（OHLCV + `symbol`/`amount`/`turnover`/`outstanding_share`）+ `_normalize_ohlcv` 末尾 **apply-if-present** 裁列（对齐分钟路径）；STEP 1 探针实测：杂列仅涉 **6 个文件**（期货两列 ×5 / 东财中文六列 ×1，全仓 0 引用）、`index_daily` 无 `amount`、`kline_min` 无 `symbol` ⇒ 实证"必须只减不增"；**存量 parquet 不动**；`smoke_chart` 新增"白名单 ⊇ 横截面内核所需列"**交叉护栏**（防筛选静默失效）；验收 **803 / 557** 全绿。**（v6.54）§7-E4 闸门结案**：时点成分股**数据源实测不可得** —— ① akshare 5 个成分股接口**签名里只有 `symbol`、无任何日期参数**（决定性）；② `csindex.com.cn` 首页 **200** 但 5 个候选 REST 端点**全 404**，历史调样是**公告 PDF/Excel**（要自建解析 + 长期维护）；③ 旁证：快照接口的「日期」列 = **快照日**、无入选/退出日。⇒ **按拍板 P3 就地结案：不发版、不写 UI、不造假能力**，保留现有诚实提示；**复活路径**（须先用浏览器抓官网真实端点）记在 §7-E4。**§7-E 队列至此全部闭环；下一步候选见"当前主线"。** |

### 📚 文档地图（先看这里，再定点检索）

| 想知道 | 去哪 |
|---|---|
| 现在什么版本 / 下一步做什么 | **本快照** + **§7-E 施工队列**（E1→E4 按序）+ §11.6 顶部 |
| 项目定位 / 技术栈 / 页面全景 | §1 · §2 · §3 |
| **哪个文件干什么（逐文件地图）** | ★ **`docs/JIAN_CODEMAP.md`**（本文件 §4 只留顶层骨架） |
| **大文件红黑榜（≥400 行）/ 体积纪律** | §4（**行数只存这一处**） |
| **数据契约 / 铁律 / 既定口径（改代码前必读）** | §5 |
| 已完成能力清单 | §6 · §6.5 |
| 未完成项 / **活的主案** | §7（**已完结主案 → `docs/JIAN_ARCHIVE.md`「一」**） |
| **我该遵守什么（不可妥协）** | §10 |
| 我要改 X，该动哪个文件 | §11.4 |
| **最容易踩的坑（全量）** | **`docs/JIAN_PLAYBOOK.md`**（本文件 §11.5 只留编号索引） |
| 收工前自检 | §11.7 |
| 什么时候改了什么（时间线） | `docs/JIAN_HISTORY.md`（版本叙事 + §8 changelog） |
| 某个旧决定"当年为什么这么定" | `docs/JIAN_ARCHIVE.md`（已完成主案 + 旧审计发现 + §11.6 历史块） |

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

## 4. 目录结构与代码地图（**逐文件地图已拆出 → `docs/JIAN_CODEMAP.md`**；此处只留顶层骨架 + 体积纪律）

> **v6.50 搬家说明**（§10-14「先搬走，再写新内容」）：逐文件树是**查阅型**内容，却占了本文件
> ≈19% 字符、把"现状 / 铁律 / 下一步"挤到读不完的边缘。现在：
> **① 逐文件地图 → `docs/JIAN_CODEMAP.md`**（每层每个文件干什么）；**② 本文件只留顶层骨架**；
> **③ 大文件红黑榜（≥400 行）与体积纪律仍在下面** —— 行数永远只存这一处（§10-14 纪律①）。

```text
Jian/                    # 根目录只留"门面"（§10-13 白名单）
├── main.py              #   唯一启动入口：建数据目录、pg 抗锯齿、装配 MainWindow
├── requirements.txt     #   PyQt6 / pyqtgraph / pandas / numpy / pyarrow / akshare / openpyxl
├── version.json         #   ⚠ 发布物：UPDATE_CHECK_URL 直链指向**此文件** → 禁止移动/改名（§9-A）
├── JIAN_RULES.md        #   本文件（唯一权威记忆，**故意**留在根：第一眼要看见）
├── .gitignore           #   忽略 __pycache__ / screenshots / *.db / samples/* / 实例* 等隐私
├── config/              #   全局常量（APP_VERSION / 颜色 / USER_DATA_DIR / 更新直链）
├── models/              #   数据契约（TradeRecord —— 全链路唯一闭环交易契约）
├── core/                # 【纯计算层：零 UI 零网络】引擎门面 / 解析落库 / 指标 / 公式 DSL / 回测内核
├── data/                # 【数据获取/存储层】行情源 / 数据湖 / 同步门面 / 交易日历 / 各类 *_store
├── ui/                  # 【表现层：只做展示，禁 SQL/爬虫】views / widgets / dialogs / workers(唯一 QThread 处)
├── scripts/             # 【只给人手动敲命令，不进 app import 图】（sync_roster.py）
├── tests/               # 【人工运行的验收脚本】smoke_chart.py / smoke_pages_overlay.py
├── samples/             # 【私有样例：是数据不是代码，.gitignore 整体忽略】
└── docs/                # 【给"未来的我"读的归档，app 不 import】
    ├── JIAN_HISTORY.md  #     时间线 + §8 完整 changelog（历史数字冻结）
    ├── JIAN_PLAYBOOK.md #     §11.5「最容易踩的坑」全量清单（编号不变）
    ├── JIAN_ARCHIVE.md  #     已完成主案规格 + 旧审计发现 + §11.6 历史块
    └── JIAN_CODEMAP.md  #     ★ 逐文件地图（本文件 §4 的详细版）
```

→ **要看"某个文件到底是干什么的、纪律钉在哪"**：`docs/JIAN_CODEMAP.md`

**体积红黑榜（v6.50 实测）· 口径与纪律：**
- **只给 ≥400 行的文件标行数（v6.16 用户拍板）**：行数的唯一用途是"提醒哪个文件快膨胀到
  不该再堆功能"，逐个文件维护精确数字只会定期返工（v6.15 那批实测已有 10+ 处对不上）。
  **<400 行的文件在 §4 一律不标数字**；要看体积请现测（口径 = **非空行**）。
- **业务文件 ≥400 行（1.26 收官实测降序）**：
  `ui/views/backtest.py` **787 → 940**（1.22 拆分收官；v1.37 §7-A4 又加：预览横幅/`exit_preview`/
    `save_to_history`，**登记不返工** —— 再长可把"预览回放态"整块搬进 `ui/widgets/backtest_preview.py`）>
  ⚠ `ui/widgets/backtest_history_ui.py` **460**（v1.37 新建即越线：过滤条/列表/迷你净值/预览/页脚
    五个构件同居一文件；**登记不返工**，再长先把 `HistoryPreviewPane` + `MiniEquityChart`
    拆成 `backtest_history_preview.py`）>
  ⚠ `ui/widgets/backtest_flow.py` **304 → 416**（v1.37 越线：`_auto_archive`/`archive_now`/`_frozen_config`
    + 定格 `_last_config`；**登记不返工**，再长可把"存档接线"抽成伴生件）>
  `core/backtest.py 495` > ⚠ `ui/views/data_manager.py` **473 → 476**（v1.38/§7-E2 中断原因文案；
    已接近 500，**登记不返工**）> ⚠ `ui/widgets/desk_layout.py` **570 → 613**
    （v6.44 加 R7 副图换序 UI：按钮/工具条/列表；**登记不返工**，再长可把配方页 `build_formula_page` 拆出）>
  ⚠ `ui/widgets/annotation_layer.py 613`（v6.26 接绘制会话、v6.28 加"按形状拾取"、
    v6.29 接 `reshape`/`normalize` 两个钩子又越线；**处置不变**：场景 I/O（挂信号/落点换算/
    静音已有标注）可再拆进 `annotation_draw_session.py`）>
  ⚠ `data/annotations.py 595`（v6.29 又长：32 种类型常量三件套 + 语义档位 + 回归函数；
    **再加新类型前**，先把"kind 常量表"拆成 `data/annotation_kinds.py`）>
  ✅ `ui/widgets/annotation_shapes.py` **587 → 296**（v6.29 · §4 处置照做：`place_*`/`read_*`
    + 两个上下文对象 + 回归几何搬进 **`ui/widgets/annotation_layouts.py`(360)**，
    两个文件都回到 400 线内；`ui/widgets/annotation_decos.py 342` 也在线内）>
  `core/database.py 435` > ⚠ `ui/widgets/backtest_result.py` **432 → 478**（v1.37 §7-A4 加净值曲线
    买卖点散点 + `kline_hint`；仍<600，**登记不返工**）> ⚠ `ui/dialogs/bulk_download.py` **416 → 454**
    （v1.38/§7-E2：竞态判据改用公共件 `JobGuard` + 中断原因文案；**登记不返工**）>
  ⚠ `ui/widgets/breadth_flow.py` **443**（v6.39 越线后 v6.43 又长：幸存者偏差提示/指数图形透传；
    **登记不返工** —— 收口时可把"范围解析→体检接线"这对重复动作与 `scan_flow` 一起收进 `ReadinessFlow`）>
  ⚠ `ui/widgets/chart_host.py` **580**（v6.43 分界线拖动调高越线；新设施是宿主级可复用件（§9-U），
    再长可把 `enable_divider_drag`+eventFilter 拆成 `ui/widgets/divider_drag.py` 伴生件）>
  ⚠ `ui/widgets/scan_flow.py` **413**（v6.43 先选后扫/闸门/落位越线；**登记不返工**，
    再长可把"日期控件三件套（选择/落位/同步）"抽成伴生件）>
  ⚠ `data/akshare_feed.py` **462 → 487**（v6.46 §7-B10 `fetch_trade_calendar` 越线、v1.39/§7-E3 再加
    `DAILY_KEEP_COLUMNS` + 落盘裁列；本就是"行情源大杂烩"候选拆点，**再加新源前先分文件**）> ⚠ `data/sync_service.py` **457 → 531**（v1.38/§7-E2 又长：`proxy` 分类
   + `looks_like_proxy_error` + 三出口文案 + `abort_reason_text` + `proxy_circuit_breaker`；
   **登记不返工** —— 再长可把"失败分类与人话文案"整段抽成 `data/fetch_messages.py` 伴生件）。
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
- **A4 [x] 回测结果历史存档（✅ v1.37 落地 · v6.49 复核重做）** `data/backtest_archive.py` + `ui/widgets/backtest_history_ui.py`（版式/渲染）+ `ui/views/backtest_history.py`（薄壳，市场回测页第 4 子页「运行历史」）：
  每次回测默认**自动**落一份**不可变快照**（~/.jian_data/backtest_results/，每份一个 `<时间戳_uuid>.json` + 轻量索引）：配置快照(可复用/重跑) + KPI + 逐笔全量 + 净值抽稀≤250（**端点保底 + 并入全部成交日**，留档）。载入查看=**只读回放**（保存/恢复现场 + 预览期禁导出 + 横幅「退出预览」；净值曲线补画买卖点）、复用参数=灌回编辑器、重跑=走 §7-B10 滞后自动补、**送行情页**=经主窗口转交函数段。★重点用户手标、豁免淘汰（pin 就地更新一行，**保住选中**）。上限：每标的 20 / 总量 500 滚动淘汰（重点仍计入 500）；防注入：文件名 uuid、用户文本只进 JSON 字段、单文件≤2MB；**读路径不写盘**。导出菜单另有「💾 存为历史快照」作手动兜底。schema 带 kind 预留 M2/M3（本轮只 M1，列表里置灰标"预留"）。

- **[x] A3 P0 数据管理页（v5.8 已完成）**：`DataLakeManager` 补删除/清点原语 +
  第 6 导航页 `ui/views/data_manager.py` + 批量预下载弹窗 `ui/dialogs/bulk_download.py` +
  同步门面 `data/sync_service.py`。
  **遗留（属 B1，非 A3 欠账）**：`scan_cache` zone 仍不存在 —— M2 横截面筛选落地时再建。

### B 类 · 市场回测扩展（**规格已于 2026-09-19 定稿** —— 主案正文已收官，见 `docs/JIAN_ARCHIVE.md`「一、§7-B1/B2 主案规格」；下面的条目只留**现状与口径**）
- **B1 [x] M2 全市场单日横截面筛选（v6.31 立项 · **STEP 1–4 已落地 v6.37**；后续收尾见 B2/B3 与 §7-B10）**：
  `backtest_module.py` 的 `page_scan` **已换成真页面**。
  ✅ **STEP 1 已落地**：`core/cross_section.py`（**越 400 线，行数见 §4 红榜**）——
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
  **主案已定稿（正文 → `docs/JIAN_ARCHIVE.md`「一、§7-B1/B2」）**：**一个引擎两种视图**（M2 = 某日纵向取列 / M3 = 跨标的按日求和）+ **会话内存缓存**
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
  （v6.2 → v6.12，含 §7-B4 坐标轴自适应 v6.15）。完整主案 → `docs/JIAN_ARCHIVE.md`「一、§7-B3 主案规格」；
  ⚠ 该主案正文里"现状（待消除）"那段已过期，**保留作历史记录**（真实状态看本条与本文件顶端）。
- **B4 [ ] P1c 回测进阶（部分）**：结果长期入库已有雏形(A2)，缺 复用 `TradeAnalyzer` 绩效维度
  与每回合明细的持久化侧写。
- **B5 [x] ⭐回测成交真实性（v6.17 立项 / v6.18 落地 / v6.19 发版）**：**P0 已完成**
  = 成交时点三档（次日开盘 / 当日收盘 / 触发式条件单）+ **T+1 硬约束** + 同根不重建仓，
  用户手动实测通过；**P1/P2 仍挂起**（账户+容量+成本 / 盘中即时成交 —— ⚠ **不许顺手做**）。
  完整规格、实测证据与验收断言见 **`docs/JIAN_ARCHIVE.md`「一、§7-B5 主案规格」**。用户口径：**宁可变难看，也要真**。
- **B6 [x] ⭐行情工作台版式收口（v6.21 立项 → v6.22 收官 · 用户 2026-09-16 拍板）**：
  **结构 = 样板 A 骨架 + 配色 = 现状（B 语言）**；⚠ **深色主题整体推迟**（用户拍板
  "放到后面软件功能实现得差不多了再统一去做"）——本轮一处深色都没加。
  **STEP 0–6 全部 ✅**（护栏/基线 → 样式公共件 → 读数条 provider → 顶栏两行+分钟档位 →
  左栏图标轨+折起+chips"最近使用" → 读数条接线+回执一行化 → 拆分收官），详见 **`docs/JIAN_ARCHIVE.md`「一、§7-B6 主案规格」**；
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
  完整条目、施工顺序与待拍板问题见 **`docs/JIAN_ARCHIVE.md`「一、§7-B8 主案规格」**。
- **B9 [x] ⭐画线工具「在图上点出来」+ 通道语义修正 + 最后 5 种（v6.26 · 用户 2026-09-18 实测反馈 ·
  **7 条拍板 + 已施工完成**）**：① 2 点以上工具不再"先生成默认线再拖"，改**用户依次点锚点**
  （橡皮筋预览 + Esc/右键取消 + **画完自动回浏览模式** + 点到已有标注也算落点、允许重合）；
  ② **平行通道从"四角可变形多边形"修正为"基线 + 填充带 + ⇕ 宽度手柄 ⇒ 两条严格平行的线"**；
  ③ **目录 32 种全部可画**（回归通道 / 波浪降级 / 头肩降级 / **甘氏扇形随缩放重算** / 斐波弧）。
  完整方案、拍板记录与施工产出见 **`docs/JIAN_ARCHIVE.md`「一、§7-B9 主案规格」**（§8 v6.26 行）。
- **B10 [x] ⭐数据新鲜度：日线收盘定稿守卫 + 扫描页「更新到最新」引导（v6.45 立项 · **§7-B10 全案已收官 v6.47/1.35 · 用户 2026-09-22）**：
  ✅ **M1（v6.46）**：定稿守卫（STEP 0/1）+ 真交易日历件（`data/trade_calendar.py` + `fetch_trade_calendar` + `CalendarWorker`）+ **M1 回测区间默认终点修复**（默认=最近已定稿交易日 / 滞后自动联网补 / 补不到回退有数据那天并出回执，推翻原 F「不引日历」）。✅ **M2/M3（v6.47）**：`ReadinessFlow` 新增 `update_latest()` 一键「⬆ 更新到最新」（与“补齐缺失”**合并**，整批当前范围增量）+ 滞后提示（`start_calendar_fetch`/`trading_days_between`/`format_stale`，真日历）+ M2 基准日诚实化（`lbl_asof_hint`）。完整规格见 **`docs/JIAN_ARCHIVE.md`「一、§7-B10 主案规格」**。
  两个真实问题（用户实测）：① **盘中同步会把“今天那根未完成 bar”永久冻结进日线库**
  （`_is_fresh` 末日==今天即跳过 + 增量起点 last+1 永不回补 → 半根 bar 再也刷不掉，污染收盘口径的回测/扫描）；
  ② **M2/M3 页面没有“把数据更新到最新交易日”的入口**（“补齐缺失”只补从没下过的股票），
  且基准日被硬收紧到本地最新、未来日灰掉无解释无桥。
  **拍板**：问题2 走**方案A（严格：未收盘定稿的当天 bar 一律不写进日线库）**；问题1 **三条都做**
  （更新动作 + 滞后检测 + 基准日诚实化，互相印证）。完整规格与施工顺序见 **`docs/JIAN_ARCHIVE.md`「一、§7-B10 主案规格」**。

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
- **D4 [~] 时点成分股（point-in-time，治幸存者偏差）**（v6.43 登记 → **v6.54/§7-E4 闸门结案：数据源实测不可得**）：
  现在 M2/M3 的成分股范围永远是**当前快照** —— 扫历史基准日时用的是"今天的名单"
  ⇒ **幸存者偏差**（后来被调出/退市的弱势股不参与，结果系统性偏乐观）。
  **实测结论（v6.43）**：三个候选接口都**没有入选/剔除日期列**（官网只给当日快照+日期列，
  同花顺只给入选日期无退出日期且当前表只含在册股）⇒ 当前数据源做不出真时点。
  **已做的缓解**：名单带快照日期上界面；基准日早于快照 ⇒ 回执自动提示幸存者偏差（两页）。
  **将来做法（动工前先与用户对齐）**：接中证指数官网的历史调样公告（半年/季度公布调入调出），
  建 `~/.jian_data/constituent_history.json`（指数 → 按生效日排序的调入调出事件流），
  按基准日回放事件流得时点名单；花名册名称的"历史 ST 不可追溯"（D5 同款）一并解决不在本项范围。
  → **已按 §7-E4 过闸门并结案（v6.54 · 2026-09-23）**：
  **① akshare 侧无路** —— 5 个成分股接口（`index_stock_cons_csindex`/`index_stock_cons`/
  `index_stock_cons_sina`/`index_stock_cons_weight_csindex` + 申万两个）**签名里只有 `symbol`，
  没有任何日期参数**；**② 官网侧网络可达但无可用端点** —— `csindex.com.cn` 首页 200，
  但 5 个候选 REST 端点全 404（真实路径要从站点前端 JS 里挖），且历史调样是**公告 PDF/Excel**，
  即便找到也要自建解析器 + 长期维护；**③ 旁证**：现有快照接口的「日期」列 = **快照日**，
  无入选/退出日。
  ⇒ **根治暂不可得**（不是"没设计好"，是**外部数据源不存在**）：**不发版、不写 UI、不造假能力**，
  保留现有两处诚实提示。**复活路径见 §7-E4**（须先用浏览器抓官网真实端点，属"数天 + 长期维护"的投入）。

### §7-E 施工队列（v6.51 定稿 · 用户 2026-09-23 拍板 · **按序施工，一项一 commit，独立可回滚**）
> **✅ 队列已闭环（2026-09-23）**：E1 ✅ 提交 `c969112`（1.37）→ E2 ✅ 落地并提交 `0e080c0`（1.38）→
> E3 ✅ 落地并提交 `96abc3f`（1.39）→ E4 ⛔ **闸门不过 ⇒ 就地结案**（零代码变更，见下）。
> **➕ 追加 E5 ✅ 落地 `1.40`**（用户实测反馈驱动："大池子每天更新到最新很影响体验"）——
> 见下方 **E5**；它的**后续性能档**（并发 / 批量快照通道）仍待拍板。
> **push 仍待用户执行**（本地领先远端 6）。

> 四项均已勘察到**代码落点**（不是设想）。关联账目：E2 → §9.3 待修清单；E3 → §9.1「可修的小债」；E4 → §7-D4。
> 拍板记录见本节末尾「E. 拍板」。

#### E1 · 提交推送 1.37（收尾 · 非功能 · ✅ **已提交 `c969112`；push 待用户**）
- **现状**：`APP_VERSION` / `version.json` 均 `1.37`；已提交 **17 文件 / +2983 −722**（含 5 个新文件：
  `data/backtest_archive.py`、`ui/views/backtest_history.py`、`ui/widgets/backtest_history_ui.py`、
  `docs/JIAN_CODEMAP.md`、`design/1.37-backtest-history/index.html`）；本地领先远端 **3**（1.35/1.36/1.37 未推）。
- **STEP**：① `git add -A` ✅ → ② commit 首词 `1.37` ✅ → ③ **push 由用户执行**（会一次带上 1.35/1.36）。
- ⚠ push 的两个**设计内**副作用：① 所有 ≤1.36 用户开机弹「✨ 发现新版本」（`version.json` 的 `notes` 就是弹窗文案）；② 点「是」打开 Releases **列表页**（现阶段不制作 Release，§9-A）。

#### E2 · 代理失败"说人话" + 熔断提前（→ 1.38 · ✅ **已落地 v1.38**）
**已核实落点**：`_classify_error`（`data/sync_service.py:478`，关键词表**已含** `proxy` ⇒ 现归 `network`）· 三个文案出口 `short_fetch_reason:486` / `friendly_fetch_message:496` / `friendly_constituent_message:518` · **熔断真正执行处 = `ui/workers.py:123`** `SyncWorker.run()`（`consecutive_fail >= policy.circuit_breaker`，默认 12）。
- **STEP 1 纯函数层**：`_classify_error` 增加 **`"proxy"`**（**优先级高于 `network`**）+ 可复用 `looks_like_proxy_error(text)`。断言：`ProxyError` → proxy、普通断网 → network、**互不误伤**。
- **STEP 2 三出口文案**：`proxy` 分支 =「疑似**本机代理问题**：请检查代理软件（Clash / V2Ray 等）是否在运行，或切换节点后重试；国内行情源通常可直连」。
  ⚠ **绝不把 `127.0.0.1:7897` 写进用户文案** —— 那是**本机**诊断记录（§9.3），写死等于对新用户撒谎；端口只留在 §9.3 的历史记录里。
- **STEP 3 熔断提前**：`ThrottlePolicy` 加 `proxy_circuit_breaker: int = 3`；`SyncWorker` 另计 `consecutive_proxy`，达阈值即停，`finished` 回包带 `aborted_by="proxy"`；回执改「疑似代理问题，已提前停手以免白等」。断言：连给 3 次 proxy 失败 ⇒ **提前停 + 标记**（现在要白等 12 次超时）。
- **STEP 4 顺手项（P4）**：`ui/dialogs/bulk_download.py` 的 `_cons_token` 手写判据 → 公共件 `JobGuard`（`workers.py:257` 已挂账"择机改用它"）。
- **STEP 5 文档 + 版本**：§9.3 三条打勾；§11.5 加新坑（**批量同错 + `ProxyError` ⇒ 先查代理，别怀疑行情源、别加重试**）；§8 加 1.38；三处版本号。
- **不做**：❌ 加重试（只让代理全灭更慢）❌ 自动改 `trust_env` ❌ 主动探测代理端口 ❌ 「不走系统代理」开关（见 P5）。

#### E3 · 日线落盘列白名单（→ 1.39 · ✅ **已落地 v1.39**）
**根因（已核实）**：`_normalize_ohlcv`（`data/akshare_feed.py`）**只 rename 不裁列** ⇒ 三类杂列进湖：
① 新浪源透传 `turnover` / `outstanding_share`；② 东财兜底的中文列；③ 期货列 `持仓量` / `动态结算价`。
**对照**：分钟路径**有**显式裁剪（`fetch_a_share_minute` 的 `keep`）⇒ **日线/分钟不对称**。
**依赖盘点（已全仓 grep）**：`_BASE_COLUMNS`（`core/cross_section.py`）= `date/open/high/low/close/volume/amount`；另加 `turnover` / `outstanding_share`（`columns_for` / 逐行判定）；**`持仓量` / `动态结算价` 全仓 0 次引用 ⇒ 纯噪声**。落盘侧 `data/market_db.py: save_data` **不做任何列校验**。
- **STEP 1 ✅ 实测（只读 parquet footer；探针跑完即删）**：

  | 分区 | 文件 | 体积 | 列集合（v1.39 实测） |
  |---|---|---|---|
  | `kline_daily` | **420** | 48.7 MB | OHLCV+`symbol` = 100% · `amount`/`turnover`/`outstanding_share` = **98.6%（414）** · `持仓量`/`动态结算价` = 5 · 东财中文六列 = **1** |
  | `kline_daily_raw` | 1 | 0.2 MB | 10 列标准（**干净**） |
  | `index_daily` | 29 | 3.1 MB | OHLCV+`symbol`（**无 `amount`**） |
  | `kline_min` | 3 | 0.1 MB | **只有 6 列 OHLCV（无 `symbol`）** |

  **结论**：① 没有"第四类"未发现的杂列（§9.1 记载的三类就是全部）；
  ② 杂列只涉及 **6 个文件** ⇒ **本项收益不是省空间，而是"消除隐性依赖 + 让列集合由一处说了算"**；
  ③ `index_daily` 无 `amount`、`kline_min` 无 `symbol` ⇒ **必须 apply-if-present**（require 就会砍坏），
  这两处是实测给出的硬证据（不是推理）。
- **STEP 2 白名单 + 落盘裁剪**：`akshare_feed` 新增**模块级** `DAILY_KEEP_COLUMNS = OHLCV_COLUMNS + ('symbol', 'amount', 'turnover', 'outstanding_share')`；`_normalize_ohlcv` 末尾按 **apply-if-present**（只留"存在且在白名单里"的列）⇒ `index_daily`（无 amount）/ 期货（无 turnover）**不会被砍坏**。
- **STEP 3 ✅ 断言**（`smoke_chart` **+7 项**）：① 白名单 ⊇ OHLCV + `symbol`/`amount`/`turnover`/`outstanding_share`，且**不含任何杂列**；
  ② **★★ 白名单 ⊇ 横截面内核所需的全部列**（`_BASE_COLUMNS` ∪ `columns_for(启用换手率 + 市值)`）
  —— 这条是防"将来裁列让筛选**静默失效**"的**交叉护栏**（§9.1 的核心警告）；
  ③ 脏数据（**照实测的三类杂列构造**）清洗后只剩白名单列；④ **apply-if-present**：只有 OHLCV 也不报错、不凭空造列；
  ⑤ 受支持列 `amount`/`turnover`/`outstanding_share` **不被裁掉**；⑥ 分钟路径行为不变（白名单含 `symbol`，但分钟随后仍裁回 6 列）。
  ⚠ **原计划第 ④ 条预判有误，如实修正**：原以为"存量杂列会被清掉 ⇒ 旧断言『缺列的票落数据不足』前提消失、变成**假绿**"，
  但实测显示**存量 parquet 不动** ⇒ 那条断言前提**依然成立**，**保留不动**（它测的三态诚实仍有效）。
  **教训**：涉及"存量数据"的推断，**必须等探针跑完再下结论**。
- **STEP 4 ✅ 存量数据**：白名单**只对新落盘生效**，湖里已有杂列**不动**（数据主权）；想瘦身用「重新全量下载」。**不做自动迁移**。
  ⚠ **本轮不做**："在数据管理页加一句'重新下载可瘦身'说明" —— 收益边际（只涉 6 个文件、且用户不可见），
  而该页有 6 条护栏不变量，不值得为一句话动它；诚实登记为**不做**（不假装做了）。
- **STEP 5 ✅ 文档 + 版本**：§9.1 改写为「**现行**：白名单已上」+ 实测表；§11.4 加行「改数据湖允许存在哪些列 → `DAILY_KEEP_COLUMNS` **一处**」；
  §4 红榜更新 `akshare_feed` 行数（462 → 487）；§8 加 1.39；三处版本号。
- **不做**：❌ **不给东财兜底源补 `成交额→amount` / `换手率→turnover` 映射** —— 东财 `换手率` 是**百分数**(0.93)、新浪 `turnover` 是**小数**(0.0093)，直接映射会把 **100× 口径**混进同一列（正是 §9-V 最怕的事故）；要做得先定换算 + 断言，**登记为后续项**。❌ 不动 `OHLCV_COLUMNS` 常量本身（被 `_PRICE_COLUMNS` 与分钟 `keep` 依赖）。❌ 不动存量 parquet。
- **验收**：`smoke_chart` **796 → 803 项** / `smoke_pages_overlay` **557 项** 全绿 + 全仓 compileall。

#### E4 · 时点成分股（治幸存者偏差）→ **⛔ 闸门不过 ⇒ 已就地结案（2026-09-23 · 零代码变更 · 拍板 P3）**

**闸门结论（两关都实测过，跑完即删）**：
- **第一关 · akshare 侧：无历史日期入口（决定性）**。`akshare 1.18.60` 里 5 个成分股候选接口
  **全部只有 `symbol` 一个参数**：`index_stock_cons_csindex` / `index_stock_cons` /
  `index_stock_cons_sina` / `index_stock_cons_weight_csindex`，外加 `index_stock_info()`（无参、非成分）、
  `index_component_sw` / `sw_index_third_cons`（申万行业，同样只有 `symbol`）。
  ⇒ **"按历史日期取成分股"在 akshare 侧根本不存在这条路**（不是"没试出来"，是签名里没有）。
- **第二关 · 官方渠道：网络可达，但没有可用的"带生效日"数据端点**。实测
  `csindex.com.cn` 首页 **HTTP 200**（网络通）、`sse.com.cn` 指数页 **403**（反爬）；
  连试 5 个候选 REST 端点（`/csindex-home/search/notice-list`、`/index/notice`、`/news/news-list`、
  `/index/sample-adjust`、`/index/cons-download`）**全部 404**（后端是 Spring Boot 服务，路径得从
  站点前端 JS 里挖，**猜不到**）。官网的历史调样以**公告 PDF/Excel**形式发布 ⇒ 即便找到真实端点，
  仍要**自建解析器 + 长期随格式变更维护**。
- **旁证 · 现有快照接口的列**：`index_stock_cons_csindex('000300')` → 300 行，列为
  `日期/指数代码/指数名称/成分券代码/成分券名称/…`，其中「日期」= **快照日（2026-09-22）**，
  **没有入选日、没有退出日** ⇒ 与 v6.43 的结论一致。

**⇒ 按拍板 P3 结案**：**不发版、不写 UI、不引入任何"看着支持"的假能力**；
保留现有两处**诚实提示**（`constituent_snapshot_text` 报快照日 + 两页"区间早于快照 ⇒ 幸存者偏差"警告），
并在 §7-D4 记明"实测不可得 + 将来若要做的复活路径"。

**将来若要复活（须先与用户对齐投入）**：唯一可行路径是**用浏览器打开 csindex.com.cn，从 Network
面板抓到"公告/调样"的真实端点**（或直接取公告文件），再按 §7-E4 原 STEP 2–5 施工：
建 `~/.jian_data/constituent_history.json`（指数 → 按生效日排序的调入/调出事件流）→
`constituents_at(index_code, asof)` 事件流回放 → `fetch_index_constituents(code, asof=None)`
（⚠ `asof` **只进参数、不进缓存键**，与 `scan_store` 同款纪律）。**这是一项"数天 + 长期维护"的投入**，
不是一个顺手的补丁。

---

<details>
<summary>原方案（保留备查 · 闸门通过时才施工）</summary>

> ⚠ **本项成败不取决于代码量，而取决于"有没有带生效日的历史调样数据源"**（v6.43 已实测：三个候选接口都**没有**调入/调出日期）。**闸门不过 ⇒ 就地结案，不发版、不写 UI** —— 绝不允许出现"界面看着支持、名单是假的"。
**已核实**：现有缓解已做（`constituent_snapshot_text` `readiness_flow.py:49` + 两页各自的"区间早于快照 ⇒ 幸存者偏差"提示）；名单链路 = `ConstituentsWorker` → `MarketSyncService.fetch_index_constituents:215` → `AkShareFeed.fetch_index_constituents:409`（中证官网优先）；**返回只有 `symbol` + `snapshot_date`（`:480`）⇒ 天生做不出时点**。落点建议 `~/.jian_data/constituent_history.json`（指数 → 按生效日排序的调入/调出事件流）。
- **STEP 1 可行性探针（⛔ 闸门 · 跑完即删）**：① **`index_stock_cons_weight_csindex` 等接口是否接受历史日期参数**（接受 ⇒ 最优解：直接时点查询）；② 中证官网 `csindex.com.cn` 的调样公告页 / 样本调整文件（半年/季度）是否可取、格式是否稳定；③ 遍历 `dir(ak)` 找成分股的历史版接口。产出「候选源 / 能否取到生效日 / 覆盖年数 / 稳定性 / 请求次数」表。**拿不到 ⇒ 回写 §7-D4 结案。**
- **STEP 2 数据件**（仅闸门通过后）：`data/constituent_history.py`（纯 Python 零 Qt）：`load_or_build(index_code)` 当日 JSON 缓存 + `constituents_at(index_code, asof)` **事件流回放** + 拿不到时回退"当前快照并标注"。断言：给定事件流回放任意日期得正确名单（**调出后不再出现**）。
- **STEP 3 接线**：`fetch_index_constituents(code, asof=None)` —— ⚠ **`asof` 只进参数、不进缓存键**（与 `scan_store` 同款纪律，§11.5-59）；M2/M3 的 `resolve_scope` 把基准日 / 区间起点传下去；`ConstituentsWorker` 加 `asof` 透传。
- **STEP 4 UI 诚实化**：能取到时点名单 ⇒ 把"⚠ 幸存者偏差"换成"✓ 时点名单（YYYY-MM-DD 生效）"；**取不到就保持现有警告**（不假装）。
- **STEP 5 文档 + 版本**（含 §7-D4 状态改写）。
- **不做**：❌ 花名册名称的"历史 ST 可追溯"（D5 同款，范围外）❌ 全历史全部指数的自动回补（只按需拉当前要用的那个）。

</details>

#### E5 · 下载层新鲜度对齐真交易日历 → ✅ **已落地 v1.40**（用户实测反馈驱动）

> **来源**：用户提问"下载最新数据的速度 —— 大池子每天更新到最新很影响体验"。
> **先量再改**（§11.5-58）：量出的结论是"**节流 sleep ≈ 全部耗时**，本地 parquet 读写只占 2–5%"
> ⇒ 明确**不去优化读写/存储格式**（那是白费力气）。

**已落地（v1.40）**
- `data/sync_service.py`：`ThrottlePolicy.expected_latest`（注入式"该到哪天"= 最近一个**已收盘定稿**
  的交易日）+ `_is_fresh(last, within_days, expected_latest)` —— 给了 expected 就判 `last >= expected`，
  没给则**完全保持旧语义**（"末日 == 今天"）。
- `ui/workers.py`：新增 `inject_expected_latest(policy)` —— **每批只取一次日历**并注入；
  `SyncWorker.run()` / `SingleSyncWorker.run()` 都走。拿不到日历 ⇒ **原样返回同一对象** ⇒ 回落旧判据。
- 预估修正：`estimate_seconds(count, policy, stale_count=None)` + 新 `format_duration`（唯一展示出口）；
  M2/M3 二次确认用体检报告的 `coverage_at` 报"其中约 N 只真正联网、约 X 分钟，其余自动跳过"；
  批量弹窗改口"最多约…（已最新的自动跳过）"。

**效果（按 5400 只估）**

| 场景 | 旧行为 | v1.40 |
|---|---|---|
| 周末 / 法定节假日 / 盘中点「更新到最新」 | ≈50 分钟，**零变化** | **≈0**（只读本地判据即跳过） |
| 盘后首次（真该补当天） | 必须跑（本来就是真活） | **不变**（必须跑） |
| 盘后第二次点（已同步过） | 已会跳过 | 不变 |
| 界面预估 | 永远"约 50 分钟"（劝退） | 按真正联网只数算；批量弹窗注明"最多约" |

**后续性能档（⚠ 须用户拍板，本轮不做）**
1. **并发 K=3~4**（池只能建在 `ui/workers.py`，数据层保持纯同步）：54min → ~14min；
   风险 = 与"宁可慢也不封 IP"的既有取向冲突。
2. **批量快照通道** `ak.stock_zh_a_spot_em()`（1 次请求拿全市场当日 OHLCV+额+换手+市值）：
   盘后补当天 54min → ~1–2min。⚠ **三条硬边界**：① 只能在 15:05 定稿后跑（否则落库半根 bar，
   正是 §7-B10 治过的东西）；② 只能补**当天这一根**（多日缺口仍须逐只）；③ spot 是**不复权**价，
   落到 qfq 分区必须在端点自洽、且**不能当复权修正通道**（除权后历史段仍靠「重新全量下载」）。
3. （不推荐）降 `interval` / 优化本地 IO：前者有封 IP 风险，后者只占 2–5%。

#### E. 拍板（2026-09-23）

| # | 议题 | 结论 |
|---|---|---|
| P1 | 文档瘦身（v6.50）与 §7-E 是否**并进 1.37 同一个 commit** | ✅ **并进**（不为纯文档单抬一个版本号） |
| P2 | E3 白名单是否保留 `turnover` / `outstanding_share` | ✅ **保留** —— 砍掉会让 M2/M3 换手率/市值筛选**当场全变「数据不足」**，正是 §9.1 警告的静默失效 |
| P3 | E4 闸门不过是否**就地结案** | ✅ **就地结案**（不留永远做不成的条目） |
| P4 | 顺手把 `bulk_download._cons_token` 改用公共件 `JobGuard` | ✅ **做**（`workers.py:257` 已挂账，<$1h 防坑）→ 并入 E2 同批 |
| P5 | E2「设置里加『行情拉取不走系统代理』开关」本轮是否做 | ❌ **本轮不做** —— app **目前没有设置页**（`ui/dialogs/` 9 个弹窗无设置项、`main_window.py` 连 `preferences` 都没引用，偏好全是各页面自己写）；要加这个开关须先定"设置入口放哪"，**属独立话题**，登记为 backlog |

**顺序**：**E1 → E2 → E3 → E4**（不变）。理由：E2/E3 是"确定性能在本轮出结论"的工作；E4 的探针可能需要用户配合（联网环境 / 代理状态），放最后不会卡住前三项。

---

### §7-B1/B2 主案规格 → **已收官，全文在 `docs/JIAN_ARCHIVE.md`「一、§7-B1/B2 主案规格」**
（v6.31 立项 · v6.37 STEP 4 = M2 页 · v6.38 STEP 5 = M3 页 · v6.39 STEP 6 = 联动收尾 · v6.43 STEP 6.5 = 体验修复轮）

**仍现行、必须记住的 4 条口径**（"当年怎么定/怎么测"去归档查）：
1. **三态铁律**：命中 / 未命中 / **数据不足** —— 数据不足**绝不用 0/False 冒充**，广度必须同时报"有效样本数"。
2. **一个引擎两种视图**：M2 = 某日纵向取列 · M3 = 跨标的按日求和；缓存只有一份
   （`data/scan_store.py` **会话内存**，键**六样**含**粗筛阈值**与**数据版本**，`asof` **不进键**）。
3. **复权单口径**：界面必须明示"本次扫描口径 = 前复权"；`kline_daily_raw` 没备齐前**不许假装支持**不复权。
4. **两页常驻 ≤3 行**、粗筛阈值收进抽屉、**非扫描基准日的数值列必须是 `—`**（绝不拿旧快照冒充当日）。
---
### §7-B10 主案规格 → **已收官（v6.47 / 1.35），全文在 `docs/JIAN_ARCHIVE.md`「一、§7-B10 主案规格」**
（v6.45 立项 · v6.46 M1 切片 · v6.47 M2/M3 收尾）

**仍现行、必须记住的 3 条口径**：
1. **定稿判据只有一处**：`data/sync_service.py` 的 `DAILY_SETTLE_HHMM`(默认 15:05) + `is_daily_bar_settled`
   （纯函数）；`refresh_one` 落盘前对日线类分区 `_drop_unsettled_tail`（**分钟分区不裁**）
   ⇒ 盘中那根半成品 bar **绝不进日线库**。
2. **"最近交易日"走真日历**：`data/trade_calendar.py`（当日 JSON 缓存 + 失败回退 + 全无则 None）；
   滞后提示 = `trading_days_between` + `format_stale`，**离线不提示数字、不许用 busday 虚报**。
3. **M2/M3 更新入口只有一个**：「⬆ 更新到最新」（= 原「补齐缺失」合并而来）；
   **就绪 ≠ 扫描**（就绪=历史行数够、扫描=基准日当天有行）⇒ `representative_latest` + `coverage_at` 诚实提示。
---
## 8. 版本演进备忘（压缩 changelog）

> 📦 **完整 changelog（v1.0 → 现在）已归档 → `docs/JIAN_HISTORY.md` §8。**
> 本文件只保留**最近三版**（"我刚做了什么"），更早的按需去归档查。

| 版本 | 一句话 |
|---|---|
| **1.40** | §7-E5 **下载层新鲜度对齐真交易日历**（用户实测反馈驱动："大池子每天更新到最新很影响体验"）：根因 = `_is_fresh` 比的是**日历日**（只有"末日==今天"才算最新），而"今天"不是交易日 ⇒ **周末/节假日/盘中把全池都判成"不新鲜"**，逐只发一次注定返空的请求（5400 只 × 0.6s ≈ **50 分钟换来零变化**），而 M1/M2/M3 的滞后提示早已用**真交易日历**正确判定"已最新"⇒ 两把尺子打架。修法：`ThrottlePolicy.expected_latest`（注入式"该到哪天"）+ `_is_fresh` 改判 `last >= expected_latest`；**注入而非自取**（`data/trade_calendar` 已依赖 `sync_service`，反向 import 成环；且日历每批只该取一次）⇒ 由调度层 `ui/workers.inject_expected_latest` 每批注入一次，`SyncWorker`/`SingleSyncWorker` 均走；**拿不到日历 ⇒ 原样返回同一对象、回落旧判据（零行为变化、可回滚）**。附带修预估：`estimate_seconds(stale_count=)` 按"真正要联网的只数"算 + `format_duration` 单一出口，M2/M3 二次确认改用体检已知的覆盖率（修掉"永远显示约 50 分钟"的劝退式预估）；批量弹窗改口"**最多约…（已最新的自动跳过）**"。smoke **803→817** / 557（§11.5-78） |
| **1.39** | §7-E3 日线落盘列白名单：`data/akshare_feed.py: DAILY_KEEP_COLUMNS`（OHLCV + `symbol`/`amount`/`turnover`/`outstanding_share`，**apply-if-present**）+ `_normalize_ohlcv` 末尾裁列 ⇒ 源透传的中文列 / 期货列**不再进湖**；**白名单 ⊇ 横截面内核所需全部列**有交叉断言钉住（防"换手率 / 市值筛选静默失效"）；**存量 parquet 不动**（数据主权）；实测杂列仅涉 6 个文件 ⇒ 收益是"消除隐性依赖"而非省空间；smoke 796→803 / 557（§11.5-77） |
| **1.38** | §7-E2 代理失败"说人话" + 熔断提前：`_classify_error` 新增 `"proxy"`（**必须先判文本指纹再退回 isinstance** —— `requests.ProxyError` 也是 `OSError` 子类，顺序错就被吞成 network）+ `looks_like_proxy_error` + 三出口文案各一档（**不写死 `127.0.0.1:7897`**）+ `ThrottlePolicy.proxy_circuit_breaker=3` + `abort_reason_text` 三处消费方共用 + P4 收编 `JobGuard`；smoke 782→796 / 554→557（§11.5-76） |

> **1.37 及更早**（`1.37` §7-A4 回测历史存档 / `1.36` §7-A2 图表导出 / `1.35` §7-B10 全案 /
> `1.34` R7 副图换序 / `1.33` M2-M3 体验修复轮，以及 v6.42–v6.46 各批叙事）
> → **`docs/JIAN_HISTORY.md` §8 全表**（v1.38 已把这批叙事归档补齐）。
>
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
  · **当前值 = `1.37`**（= §7-A4 回测历史存档（不可变快照 + 运行历史子页）；1.36 = §7-A2 回测图表导出；1.35 = §7-B10 数据新鲜度全案；1.34 = §7-B8 R7 副图换序收尾；1.33 = M2/M3 体验修复轮；1.32 = 修复成分股名称列全空 + 内核警告出口；1.31 = 成分股代码格式；1.30 = STEP 6 联动收尾；1.29 = M3 广度页；
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
4. **~~可修的小债（择机）~~ ✅ v1.39/§7-E3 已修**：日线补上**落盘列白名单**（对齐分钟线做法）——
   白名单 = `data/akshare_feed.py: DAILY_KEEP_COLUMNS`（OHLCV + `symbol`/`amount`/`turnover`/`outstanding_share`），
   `_normalize_ohlcv` 末尾按 **apply-if-present** 裁列。
   **v1.39 实测（只读 footer，420 个日线文件）**：杂列只剩
   `持仓量`/`动态结算价`（期货，5 文件）+ 东财中文六列（1 文件）—— **全仓 0 引用 ⇒ 已可安全裁掉**；
   `kline_daily_raw` 1 文件、`index_daily` 29 文件（**无 `amount`**）、`kline_min` 3 文件（**只有 6 列、无 `symbol`**）
   ⇒ 这三处正是"**必须 apply-if-present**"的实证（require 就会砍坏）。
   ⚠ **存量 parquet 不动**（数据主权）：白名单只对新落盘生效；想瘦身用「重新全量下载」。
   ⚠ **本项收益不是省空间**（6 个文件而已）：是**消除"隐性依赖"**——从此"湖里的列集合"由**一处**说了算，
   下游要什么列就在白名单里登记（有 `smoke_chart` 的**交叉一致性断言**钉住）。
   仍**不做**：不给东财把 `成交额→amount` / `换手率→turnover` 做映射（单位分别是百分数/小数，
   直接映射会造成 100× 口径混入 —— §9-V）⇒ **登记为后续项**。

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

### 9.3 系统代理环境下行情拉取「批量全灭」（v6.42 诊断 · **v1.38/§7-E2 已修 ✅**）

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
2. ~~**`_classify_error` 已把 `proxy` 归入 network 类** ⇒ 失败文案归类没错，但没有把"疑似本机代理问题"
   单独说出来 —— 用户看不出该去检查代理。~~ **✅ v1.38 已修，且发现真正的坑**：
   `requests.exceptions.ProxyError` → `ConnectionError` → `RequestException` → **`IOError`（就是内建 `OSError`）**，
   所以"先 `isinstance(error, OSError)` 再看文本"的写法会把代理失败**先归成 network** ——
   必须**先判文本指纹、再退回 isinstance**（§11.5-76）。

**施工方案 = §7-E2（✅ 已落地 v1.38）**。三条待修的处置：

- [x] **拉取失败文案识别 ProxyError**（✅ v1.38）：`_classify_error` 新增 `"proxy"`，
      三出口（`short_fetch_reason` / `friendly_fetch_message` / `friendly_constituent_message`）
      各有一档"疑似本机代理问题"文案 —— 与"行情源失败 / 被限流"**分开安抚**（§10-10 补全）。
      ⚠ **没有写死 `127.0.0.1:7897`**（那是本机诊断值）—— 只说"检查代理软件是否在运行 / 切节点"；
      且有断言钉住"三个出口的文案里都不许出现 `127.0.0.1` / `7897`"。
- [x] **连续 ProxyError ⇒ 熔断提前**（✅ v1.38）：`ThrottlePolicy.proxy_circuit_breaker = 3`
      （通用仍 12）；`SyncWorker` 另计 `consecutive_proxy`，达阈值即停并把
      `aborted_by="proxy"` 带回 UI —— 三处消费方（批量预下载 / 数据管理 / M2-M3 更新补齐）
      统一用 `abort_reason_text(stats)` 出人话，**不再只显示一个"已中断"**。
- [ ] **不做（本轮）**：设置里加"行情拉取不走系统代理"开关（`session.trust_env=False` / 显式空 proxies）
      —— 国内行情源直连通常更快，但**必须默认跟随系统**；且 app **目前没有设置页**，
      要做须先定"设置入口放哪"，**属独立话题**（§7-E 拍板 P5），已登记 backlog。

**⚠ 给未来的我（判据）**：凡"**批量同错 + `ProxyError` / `Unable to connect to proxy` 字样**"
⇒ 先查 `requests.utils.getproxies()` 与代理进程状态，**别怀疑行情源、别加重试**；
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
   杜绝"每个图表一对一地改"。底层契约见 `docs/JIAN_ARCHIVE.md`「一、§7-B3 主案规格」。
12. **【图表架构四层 + 两条管线 · v6.1 新增 · 总纲见 `docs/JIAN_ARCHIVE.md`「一、§7-B3」】**
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
    | `docs/` | **给"未来的我"读的文档归档**（非代码、非用户数据；app 不 import） | `JIAN_HISTORY.md` 时间线 / `JIAN_PLAYBOOK.md` 踩坑手册 / `JIAN_ARCHIVE.md` 已完成主案与旧审计 / **`JIAN_CODEMAP.md` 逐文件代码地图**（v6.50 增） |
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
     一次版本号事故。检索不是问题，"**现状与历史混在一起 + 同一数字十几处重复**"才是问题。
     ⚠ **v6.50 又超了一次**：`v6.32` 拆到 114k 后**没人再量**，一路长到 **118k** ⇒ 本轮按本条纪律搬走
     **45k**（逐文件地图 → `JIAN_CODEMAP.md`、§7-B1/B2 + §7-B10 主案与 §11.6 历史块 → `JIAN_ARCHIVE.md`）
     回到 **≈73k**；并新增 §11.7 末条「收工量字符数」把这条纪律变成**动作**，而不是愿望。）
   - **本文件只放"现在是什么 / 必须遵守什么 / 下一步做什么"**；**时间线、旧审计、已完成主案、
     踩坑全量清单、**逐文件代码地图**一律放 `docs/`（`JIAN_HISTORY.md` / `JIAN_ARCHIVE.md` / `JIAN_PLAYBOOK.md` / **`JIAN_CODEMAP.md`**），
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
| 改**失败原因分类 / 失败文案** | **`data/sync_service.py` 一处**（v1.38/§7-E2）：`_classify_error`（⚠ **先判 `looks_like_proxy_error` 文本指纹、再退回 isinstance** —— `requests.ProxyError` 也是 `OSError` 子类）+ `short_fetch_reason` / `friendly_fetch_message` / `friendly_constituent_message` 三出口 + `abort_reason_text`（批量中断原因，**三消费方共用**）。⚠ 文案里**不许写死本机端口/proxy 术语当唯一解释**（§10-10），有断言钉着 |
| 改**代理全灭时的停手时机** | `ThrottlePolicy.proxy_circuit_breaker`（默认 **3**，与通用 `circuit_breaker=12` 分开，v1.38/§7-E2）+ `ui/workers.py: SyncWorker.run` 的 `consecutive_proxy` 计数与 `aborted_by` 回传 |
| 改**数据湖里允许存在哪些列** | **`data/akshare_feed.py: DAILY_KEEP_COLUMNS`（唯一白名单）**（v1.39/§7-E3）—— `_normalize_ohlcv` 末尾 apply-if-present 裁列。⚠ **要加列先想清楚**：下游要读的列必须在这里登记，否则 **M2/M3 的相应筛选会静默失效**（`smoke_chart` 有"白名单 ⊇ 内核所需列"的交叉断言钉着）；⚠ 各分区列集合本来就不同（`index_daily` 无 `amount`、`kline_min` 无 `symbol`）⇒ 只能"只减不增"，**别 require** |
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
| 改回测历史存档 | 存储 = **`data/backtest_archive.py`**（`BacktestArchive` save/list/load/set_pinned/delete + `_evict` 滞动淘汰 + uuid 文件名防注入 + 单文件≤2MB；不可变快照 + `_index.json` 轻量索引，**读路径不写盘**；`sample_equity` **端点保底 + 并入成交日**）；**版式/渲染 = `ui/widgets/backtest_history_ui.py`**（`HistoryFilterBar`/`HistoryTable`/`MiniEquityChart`/`HistoryPreviewPane`/`HistorySettingsBar`）；**页面薄壳 = `ui/views/backtest_history.py`**（市场回测页第4子页，列表+预览+载入查看/复用/重跑/**送行情页**/★/删）；接线在 `backtest_flow._auto_archive`/`archive_now`（存 `build_record(result, _last_meta, config=_frozen_config(), source=)`，`_last_config` 在 `start_backtest` **发起瞬间定格**）；M1 视图 `show_archived`（只读回放：现场保存/恢复 + 预览期禁导出 + `_preview_bar`）/`exit_preview`/`load_archive_config`/`save_to_history`（导出菜单「💾 存为历史快照」）；结果区 `_render_equity` 见 `buy_at`/`sell_at` 列即画买卖点散点；开关键 `backtest_archive.auto`。⚠ 新增写用户目录文件→防污染自检名单已含 `backtest_results` |
| 判断"这笔是赚还是亏"（任何着色/正负号/标记色） | **`core/utils.record_net_amount(record)`**（v6.9）—— 净额 = 平仓盈亏 − 手续费的**唯一取值口径**。**禁止**再手写 `net_profit > 0` 或 `net_profit - commission`（§5.3-B / §9-P1） |
| 改下拉/日期等复合控件的外观 | **`ui/widgets/custom_widgets.py`**：用生成器 `combo_qss()` / `date_edit_qss()` 造新变体，或直接引用 8 个具名常量（`COMBO_QSS` / `COMBO_QSS_SMALL` / `COMBO_QSS_ACCENT` / `COMBO_QSS_EDIT` / `COMBO_QSS_EDIT_OK` / `LINE_COMBO_QSS` / `DATEEDIT_QSS_WARN` / `DIALOG_INPUT_QSS`）。**业务页面禁止就地 setStyleSheet**，且 `::drop-down` 与 `::down-arrow` 必须成对（v6.9：否则箭头消失，§10-9） |
| **给图表加自适应坐标轴**（刻度随缩放变密/换格式、纵轴跟随可视区间） | **`ui/widgets/adaptive_axis.py`（§7-B4 · v6.15）一处**：`attach_date_axis(pane, dates / texts, y_provider=…)`、`follow_y(pane, provider)`、`attach_all(host, dates, providers_by_pane)`。页面只写 `provider(i0, i1) -> (lo, hi)`（回答"这个窗格在可视区间内数值范围是多少"）。**禁止再手写 `setTicks` / `setYRange`**；日期格式梯子只在该文件的 `choose_date_format`（将来分钟线只改这里） |
### 11.5 最容易踩的坑（**全量清单已归档 → `docs/JIAN_PLAYBOOK.md`**）
> ⚠ 本清单**持续累积、只增不减**（已占原文件 8.2% 版面）—— 详情在
> **`docs/JIAN_PLAYBOOK.md`**，**编号不变**（`§11.5-25` 仍然叫 `§11.5-25`）。
> 用法：在下面索引里找到相关编号 → 只去 PLAYBOOK 读那一条（省 context，且不会漏）。
> **改动任何模块前，先扫一眼本期相关编号。**
> ⚠ **实际存放（v1.38 核对，别再搞错）**：**1–50 的完整血泪细节在 PLAYBOOK**（按序号排）；
> **51 起的条目本体就写在下面索引里**（编号即条目，写得较全）—— 去 PLAYBOOK 找是**找不到**的。
> 新条目**只往下面索引加**，不要两边写（会漂）。

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
- **11.5-75** 【v6.49 · §7-A4 回测历史存档】① **读路径绝不能写盘**——`_rebuild_index`/`list()` 若顺手 `_write_index`，开一次页就把真实 `~/.jian_data/backtest_results/` 建出来（实测污染自检红）；写盘只在 save/delete/pin 真变更时发生；`delete(不存在 id)` 也必须不建目录。② **滞动淘汰的新旧判据不能用秒级 created_at**——同秒批量保存会误把最新当最旧删；加单调 `seq=time.time_ns()` 作排序/淘汰键。③ **载入查看=只读回放态**（`_preview_mode`）：**不能改写 `_last_result/_last_meta`**（否则预览里点导出＝"存档结果 + 上次参数"这对错误组合）→ 预览前保存现场，`exit_preview` 还原，预览期**禁用导出**并显示横幅；复用参数走 `StrategyBridge.apply_payload`（与策略选用同一还原口径，单一事实源）。④ **防注入**：文件名只用 时间戳_uuid（用户输入不进路径），策略/标的名只进 JSON 字段。⑤ **净值抽稀必须端点保底**——`BacktestResult.cumulative_return == equity[-1] − 1`，末点丢了"载入查看"的累计就是错的；均匀网格用 `round(i*(n-1)/(k-1))` 并显式补 0 与 n-1。⑥ **抽稀上限与买卖点冲突时，成交日优先**（上限是省空间的软目标，另有 2MB 硬闸）——但要如实登记"可能超 250 点"。⑦ **pin 不能整表重建**——`refresh()` 会清空选中 ⇒ 用户看到的是"重点选不上"；必须就地更新那一行 + 保住选中（`select_by_id`）。⑧ **`setRowCount` 缩表后 Qt 可能保留旧 selection** ⇒ 删除后出现"幽灵选中"；不恢复选中时必须显式 `clearSelection()`。⑨ **表格数字着色不能用 `item.setForeground`**——选中行会在蓝色高亮上叠红/绿字（用户实测"点一下就变色"）；改用 `QStyledItemDelegate` 并让选中态走样式表。⑩ **`pg.PlotWidget.plot` 是 `__getattr__` 转发到 PlotItem 的**，不在 MRO 里 ⇒ 子类自定义 `plot()` 后 `super().plot(...)` 直接 `AttributeError`；要么改名（`set_series`），要么显式 `getPlotItem().plot(...)`。
- **11.5-76** 【v1.38 · §7-E2】① **`requests` 的异常继承链会让"先 isinstance 后看文本"的分类顺序翻车**：
   `ProxyError` → `requests.ConnectionError` → `RequestException` → **`IOError`（= 内建 `OSError`）**
   ⇒ 若先判 `isinstance(e, OSError)` 就归成"网络"，**"本机代理问题"永远说不出口**；
   必须**先判文本指纹（`looks_like_proxy_error`）、再退回 isinstance**，且要有
   "把 `ProxyError` 造在 `OSError` 子类上"的断言钉住（否则改回去也没人发现）。
   ② **代理全灭不能用通用熔断阈值**：失败率 100% 时 12 连败 = 白等十几次超时，
   用户该做的是"立刻查代理" ⇒ 单独 `proxy_circuit_breaker=3` + `aborted_by` 回传原因。
   ③ **诊断信息不许写进用户文案**：`127.0.0.1:7897` 是**某一台机器**的记录（§9.3），
   写进弹窗就是对新用户撒谎 —— 文案只说"检查代理软件是否在运行 / 切节点"，并加断言钉住。
   ④ **中断原因文案要做成公共件**（`abort_reason_text`）：`SyncWorker.finished` 有三个消费方，
   各写一遍"（已中断）"必然有一处漏 —— 漏的那处用户就看不到"为什么提前停"（§11.5-11）。
- **11.5-77** 【v1.39 · §7-E3】① **"裁列白名单"必须 apply-if-present（只减不增）**：各分区列集合
   **本来就不一样**（实测：`index_daily` 无 `amount`、`kline_min` 只有 6 列无 `symbol`）——
   写成"必须包含这些列"就会把正常分区砍坏，写成"只保留存在的白名单列"才对。
   ② **白名单必须覆盖下游真正要读的列，且要有交叉断言**：`smoke_chart` 有一条
   "白名单 ⊇ 横截面内核所需的全部列（`_BASE_COLUMNS` ∪ `columns_for(启用换手率+市值)`）"——
   没有它，"哪天顺手裁一下列"就会让换手率/市值筛选**当场全变「数据不足」而没人发现**（§9.1 的静默失效）。
   ③ **先探针、再下结论**：我原本预判"存量杂列会被清掉 ⇒ 旧断言会变成假绿"，跑完探针才发现
   **存量 parquet 不动**（数据主权）⇒ 旧断言前提仍在、保留即可。**涉及"存量数据"的推断必须实测**。
   ④ **收益要如实说**：本项只涉 6 个文件 ⇒ **不是省空间**，是"让列集合由一处说了算 + 消除隐性依赖"；
   别把"防未来事故"包装成"优化体积"（§10-4 诚实）。

   - **11.5-78** 【v1.40 · §7-E5】**下载层与 UI 必须用同一把尺子判"新鲜"，且那把尺子是交易日历**：
   ① **"今天"不是交易日**。`_is_fresh` 原先只认"本地末日 == 今天"（**日历日**）⇒
   周末 / 法定节假日 / 盘中（< 15:05 定稿）时**全池每一只都判成"不新鲜"**，逐只发一次注定返空的
   请求：5400 只 × 0.6s ≈ **50 分钟换来零变化**。⚠ **不许用"放宽 `fresh_within_days`"来治**
   （注释里早有理由：放宽到 1 会让"昨天已同步"的标的在今日盘后被永久跳过、永远滞后一天）；
   正解是用**真交易日历**（`data.trade_calendar.latest_settled_trading_day`）—— 它本来就是
   M1/M2/M3 滞后提示的**唯一真源**，只是下载层没接上 ⇒ 出现"UI 说已最新、下载却跑 50 分钟"。
   ② **反向依赖成环 ⇒ 注入，不要自取**。`data/trade_calendar` **已经 import `sync_service`**
   （用 `is_daily_bar_settled`），所以 `refresh_one` 不能 import 它；而且日历**每批只该取一次**
   （冷缓存时含一次网络），绝不能每只标的都取。⇒ 由调度层 `ui/workers.inject_expected_latest`
   注入 `ThrottlePolicy.expected_latest`（每次 `SyncWorker.run()` 取一次）。
   ③ **新增"注入字段"的默认值必须等价于"什么都没变"**：`None` ⇒ 回落旧判据；
   且**拿不到日历时要原样返回同一个对象**（不是拷贝），这样离线照常工作、行为可预测、可安全回滚。
   ④ **预估也是体验**。旧 `estimate_seconds` 一律按 `count` 算 ⇒ 该干 0 件也显示"约 50 分钟"，
   **等于把用户劝退**。要能传"真正会联网的只数"（M2/M3 的体检报告里已有 `coverage_at`），
   且**展示口径要有单一出口**（`format_duration`）—— 两个页面各写一遍必然说法不一致。
   ⑤ **性能问题先量再改**（§11.5-58 同源）：本轮量出的结论是"**节流 sleep ≈ 全部耗时**，
   本地 parquet 读写只占 2–5%"⇒ **不要去优化读写/换存储格式**，那是白费力气。
   ⑥ 发现路径 = **用户实测反馈**（"大池子每天更新到最新很影响体验"）：用户的体感描述
   往往指向一个**具体的判据错误**，而不是"整体慢"。
   - **11.5-79** 【v1.40 · 验收基线的前提】**`smoke_chart` 有 3 条"真实分区缓存一致性"断言
   只在数据湖静止时成立**：`data/scan_store.data_version()` 的指纹含每个 parquet 的
   `size:mtime_ns` ⇒ **只要有下载任务在写湖**，`scan_cached` 的第二次调用就会换版本、
   **缓存不命中**，于是"第二次调用命中" / "缓存矩阵切片 == 重扫（逐位一致）"必然红。
   ⇒ **跑验收前先确认没有下载在跑**。本轮实测：`git stash` 掉全部改动后基线同样是
   `通过 800 · 失败 3`（同为这 3 条），而湖在 6 秒内从 581 涨到 583 个文件（有 python 进程在写）
   ⇒ 结论是**并发写入**，不是回归。**教训**：看到"只有几条真实数据类断言红"时，
   先问"**有没有东西正在写数据**"，再怀疑自己的改动。



### 11.6 当前"下一步做什么"的推荐顺序（历史刷新**倒序**排列：主清单之下**第一块就是最新**）

> **v6.55（§7-E5 落地 · `1.40` · 2026-09-23 · 用户实测反馈驱动）**
> 用户提"下载最新数据的速度"：**大池子每天更新到最新很影响体验**（沪深300/中证500 还行，
> 进大池子就难受）。先摸链路再给方案，结论分两层：
> **① 诊断（先量）**：`ThrottlePolicy.interval=0.6s` 是**节流 sleep**，而单只本地开销
> （整文件 parquet 读 + 全历史 concat/去重/排序 + 整文件写）只占 **2–5%** ⇒
> **sleep 就是全部成本**（自证：文档自己写"5000 只 ≈50 分钟"，而 5000×0.6s=50min）。
> **② 最大一块不是"慢"而是"纯白干"**：`_is_fresh` 认的是**日历日**（只有"末日==今天"才算最新），
> 而"今天"不是交易日 ⇒ **周末 / 节假日 / 盘中**全池每一只都判"不新鲜"，
> 逐只发一次注定返空的请求（5400 只 ≈**50 分钟换来零变化**）；
> 而 M1/M2/M3 的滞后提示**早已用真交易日历**（`latest_settled_trading_day`）正确判定"已最新"
> ⇒ **两把尺子打架**，用户看到的正是这个落差。
> **落地**：`ThrottlePolicy.expected_latest`（注入式"该到哪天"）+ `_is_fresh(last, days, expected)`
> 改判 `last >= expected`；**注入而非自取**（`data/trade_calendar` 已依赖 `sync_service`，
> 反向 import 成环；且日历每批只取一次）⇒ 新增 `ui/workers.inject_expected_latest`，
> `SyncWorker` / `SingleSyncWorker` 都在 `run()` 里注入一次；
> **拿不到日历 ⇒ 原样返回同一对象 ⇒ 完全回落旧判据（零行为变化、可安全回滚）**。
> 附带修**劝退式预估**：`estimate_seconds(count, policy, stale_count=)` 按"真正要联网的只数"算，
> M2/M3 二次确认用体检已有的 `coverage_at` 报出"其中约 N 只真正联网、约 X 分钟，其余自动跳过"；
> `format_duration` 收成**唯一展示出口**；批量弹窗改口"**最多约…（已最新的自动跳过）**"。
> 验收：`smoke_chart` **803→817**（新增 14 条：判据四态 / 端到端"周末零请求 + 盘后必拉 +
> 未注入回落旧判据" / 注入件每批只取一次 + 拿不到日历原样返回 / 预估与格式化）、
> `smoke_pages_overlay` **557** 全绿 + 全仓 compileall。坑=**§11.5-78**。
> ⚠ **验收时的如实发现（已登记 §11.5-79）**：跑 `smoke_chart` 时那 3 条
> "真实分区缓存一致性"断言红。**先做基线对照**（`git stash` 掉全部改动）⇒ **基线同样是 800/3 红**，
> 且查明真实数据湖**正在被并发写入**（6 秒内 581→583 个文件，有 python 进程在跑）
> ⇒ 是**存量脆弱性**（`data_version` 含 `mtime_ns`，湖一动缓存就换版本），**不是本次回归**。
> **本条教训值得反复用**：断言大面积红之前，先确认"数据是不是正在被改"。
> **下一步候选** = ① §7-E5 的性能档续作（**并发 K=3~4** 或 **批量快照通道**
> `ak.stock_zh_a_spot_em` 只补当日，**须用户拍板**，后者有复权/定稿边界）；② §7-B4 回测进阶；
> ③ 深色主题。**push 待用户**（领先远端 6）。

> **v6.54（§7-E4 闸门结案 · 零代码变更 · 2026-09-23）**
> §7-E 队列最后一项「时点成分股（治幸存者偏差）」**不走代码，先过可行性闸门**（拍板 P3：不过就结案）。
> **闸门两关实测结论**：① **akshare 侧无路（决定性）** —— `akshare 1.18.60` 的
> `index_stock_cons_csindex` / `index_stock_cons` / `index_stock_cons_sina` /
> `index_stock_cons_weight_csindex` 四个成分股接口 + 两个申万行业接口，**签名里全部只有 `symbol`，
> 没有任何日期参数** ⇒ "按历史日期取成分股"这条路**根本不存在**（不是没试出来）；
> ② **官网侧网络可达但无可用端点** —— `csindex.com.cn` 首页 **HTTP 200**、`sse.com.cn` 指数页 403（反爬），
> 连试 5 个候选 REST 端点（`/csindex-home/search/notice-list`、`/index/notice`、`/news/news-list`、
> `/index/sample-adjust`、`/index/cons-download`）**全部 404**；官网历史调样以**公告 PDF/Excel**发布
> ⇒ 即便挖到真实端点仍要**自建解析器 + 长期随格式维护**；③ **旁证**：`index_stock_cons_csindex('000300')`
> 的列是 `日期/指数代码/…/成分券名称`，其中「日期」= **快照日（2026-09-22）**，**无入选日、无退出日**。
> **⇒ 按 P3 结案**：**不发版、不写 UI、不引入"看着支持"的假能力**；保留现有两处诚实提示
> （`constituent_snapshot_text` 报快照日 + 两页"区间早于快照 ⇒ 幸存者偏差"警告）。
> **复活路径**（要先与用户对齐投入）写在 §7-E4：用**浏览器打开官网、从 Network 面板抓真实端点**，
> 再走"事件流 JSON + `constituents_at(asof)` 回放 + `asof` 只进参数不进缓存键"的原方案。
> **§7-E 队列到此全部闭环**（E1 提交 1.37 → E2 1.38 → E3 1.39 → E4 结案）；
> **push 仍待用户**（本地领先远端 5）。**下一步候选** = §7-B4 回测进阶 / §7-B8 余量 / **深色主题**
> （用户原定"功能差不多了再统一做"—— 四个回测子模块现已全部收官，**可能已到该时点，值得拍板**）。

> **v6.53（§7-E3 落地 · `1.39` · 2026-09-23）**
> 按 §7-E 队列续做 E3（**日线落盘列白名单**）。**STEP 1 先探针实测**（只读 parquet footer，跑完即删）：
> 420 个日线文件里，杂列只剩 **期货两列 × 5 文件 + 东财中文六列 × 1 文件**（全仓 0 引用 ⇒ 可安全裁）；
> `kline_daily_raw` 干净、`index_daily` **无 `amount`**、`kline_min` **只有 6 列无 `symbol`**
> —— 后两者是"**必须 apply-if-present**"的实证（require 就会砍坏正常分区）。
> **STEP 2 落地**：`data/akshare_feed.py: DAILY_KEEP_COLUMNS`（OHLCV + `symbol`/`amount`/`turnover`/
> `outstanding_share`）+ `_normalize_ohlcv` 末尾裁列（对齐分钟路径早就有的 `keep`，消除"日线/分钟不对称"）。
> **STEP 3 断言**（`smoke_chart` **+7**）：其中最重要的是 **★ 白名单 ⊇ 横截面内核所需全部列**
> （`_BASE_COLUMNS` ∪ `columns_for(换手率+市值)`）—— 没有它，"哪天顺手裁一下列"就会让
> 换手率/市值筛选**当场全变「数据不足」而没人发现**（§9.1 的静默失效）。
> **STEP 4 存量**：白名单**只对新落盘生效**，湖里已有杂列**不动**（数据主权）。
> ⚠ **如实登记**：① 原计划"改造旧断言（怕它变假绿）"的**预判有误** —— 实测存量不动 ⇒ 旧断言前提仍在，
> **保留即可**（涉及存量数据的推断必须等探针跑完）；② "在数据管理页加一句瘦身说明"**本轮不做**
> （收益边际 + 该页有 6 条护栏不变量），诚实登记而不是假装做了。
> 验收：`smoke_chart` **803** / `smoke_pages_overlay` **557** 全绿 + 全仓 compileall。坑=§11.5-77。
> **下一步** = **E4 时点成分股（1.40）**：**先过可行性闸门**（探针问"能不能拿到带生效日的历史调样"），
> 拿不到就按拍板 P3 **就地结案**、不发版不写 UI。

> **v6.52（§7-E2 落地 · `1.38` · 2026-09-23）**
> 用户批准 §7-E 后按序开工（E1 提交 `1.37` → **E2 完成**）。**代理失败"说人话" + 熔断提前**：
> ① 修一个真陷阱 —— `requests.ProxyError` → … → **`IOError`(=`OSError`)**，所以"先 isinstance 再判文本"
> 会把代理失败**吞成 network**（§9.3"说不出代理"的真因）；新增 `looks_like_proxy_error` +
> `_classify_error` 先判指纹，新增 `"proxy"` 档；② 三出口文案各一档（**不写死 `127.0.0.1:7897`**、
> 明说"不是源挂了/不是限流，稍后重试没用"）；③ `ThrottlePolicy.proxy_circuit_breaker = 3`（通用仍 12）
> + `SyncWorker` 回传 `aborted_by`；④ 中断原因做成公共件 `abort_reason_text`（三消费方共用）；
> ⑤ P4 还清旧挂账：`bulk_download._cons_token` → 公共件 `JobGuard`（"只接受最新回包"全仓只剩一处实现）。
> 验收：`smoke_chart` **796** / `smoke_pages_overlay` **557** 全绿 + compileall。坑=§11.5-76。
> ⚠ **一处如实登记**：计划里的"真机复现验证（把代理指到死端口）"需联网/改环境，**未能执行**
> （分类判定已由单测钉死 —— 含"把 `ProxyError` 造在 `OSError` 子类上"这条最关键的陷阱）；
> 若要补真实复现，请按 §9.3 的做法做一次（探针跑完即删）。
> **下一步** = **E3 日线落盘列白名单（1.39）**：先跑 STEP 1 探针量列清单，再上 `DAILY_KEEP_COLUMNS`。

> **v6.51（§7-E 施工队列落档 · 2026-09-23 · 用户拍板"直接写进去，改动前先提交 git"）**
> 主文件**只落方案、不动代码**：§7-E 定稿四项队列，并给出**已核实的代码落点**（不是设想）。
> ① **E1 提交推送 1.37**（收尾 · 非功能；本地领先远端 2，push 后会一次带上 1.35/1.36）；
> ② **E2 代理失败"说人话"+ 熔断提前**（→1.38）：`_classify_error` 增 `"proxy"`（优先级高于 network）
> + 三出口文案（**不写死 127.0.0.1:7897**）+ `ThrottlePolicy.proxy_circuit_breaker=3`
> （熔断真正执行处 = `ui/workers.py:123`）+ P4 顺手把 `bulk_download._cons_token` 换 `JobGuard`；
> ③ **E3 日线落盘列白名单**（→1.39）：根因 = `_normalize_ohlcv` 只 rename 不裁列（分钟有 `keep`、日线没有），
> 白名单 = `DAILY_KEEP_COLUMNS`；**保留 `turnover`/`outstanding_share`**（砍掉= M2/M3 筛选静默失效）；
> ④ **E4 时点成分股**（→1.40 · **前置可行性闸门**）：拿不到"带生效日的历史调样"就**就地结案**，不发版不写 UI。
> **本轮明确不做**：P5「不走系统代理」开关（app **没有设置页**，属独立话题）。
> 文档：主文件 **≈82k 字符**（v6.50 瘦身 118k→73k 之后再加 §7-E，仍在 §10-14 硬指标内）。
> **下一步** = 执行 E1（提交 1.37）→ 再动 E2 的代码。

> **v6.49（§7-A4 回测历史存档 · 1.37 · 2026-09-22）**
> 新增“运行历史”子页：每次回测默认**自动**落一份不可变快照（`data/backtest_archive.py`：每份 `<时间戳_uuid>.json` + 轻量索引），含配置快照(可复用/重跑) + KPI + 逐笔全量 + 净值抽稀≤250(留档)。
> UI = `ui/widgets/backtest_history_ui.py`（版式/渲染）+ `ui/views/backtest_history.py`（薄壳，市场回测页第4子页）：列表+预览+载入查看(只读回放)/复用参数/重跑/送行情页/★重点(豁免淘汰)/删除(二次确认)。上限每标的20/总500滞动淘汰；文件名 uuid 防注入、单文件≤2MB；schema 带 kind 预留 M2/M3（本轮只 M1）。
> 接线：`backtest_flow._auto_archive`/`archive_now`（`build_record(result, _last_meta, config=_frozen_config(), source=)`）；M1 新增 `show_archived`（只读回放：现场保存/恢复 + 预览期禁导出 + 黄色横幅「退出预览」）/`exit_preview`/`load_archive_config`/`save_to_history`（导出菜单「💾 存为历史快照」）；`StrategyBridge.apply_payload` 抽出复用；偏好键 `backtest_archive.auto`。
> **v6.49 复核重做（用户实测反馈驱动）**：① 版式按 1.22 同款分工拆出 **`ui/widgets/backtest_history_ui.py`**（过滤条/`HistoryTable`/`MiniEquityChart`/`HistoryPreviewPane`/页脚设置），页面收敛为薄壳；② 修 **"重点选不上"**（pin 不再整表重建，改就地更新一行 + 保住选中）、**"点一下就变色"**（数字着色改用 `_SignedValueDelegate`，选中行交给样式表）、**"载入查看坏了"**（只读回放不再改写 `_last_result`，净值曲线补画买卖点，K 线页给诚实提示）；③ 存储层修**抽稀端点保底**（否则 `cumulative_return` 算错）与**读路径不写盘**（`delete('不存在')` 不再建目录）、僵尸索引剔除、`_evict` 旧→新明确截断；④ 补 **「📤 送行情页」**、**kind M2/M3 置灰**、**可折叠参数详情**。
> 验收：`smoke_chart` **782** / `smoke_pages_overlay` **554** 全绿 + compileall（存档测试全用临时 root；防污染自检含 `backtest_results`）。坑=§11.5-75（读路径不写盘 / seq 淘汰键 / 只读回放态 / `PlotWidget.plot` 遮蔽 / `setRowCount` 幽灵选中）。
> **下一步** = §7-B8 余量（R4 组合配置独立远期 / R12 暂缓）与其它 backlog（§7-B4 / §7-C/D）。

> **更早更新块（v6.48 / v6.47 / v6.46 / v6.44 / v6.43 / v6.39 / v6.38 / v6.31）→ 已搬 `docs/JIAN_ARCHIVE.md`「三」与 `docs/JIAN_HISTORY.md` §8 全表**
> （v6.50 按 §10-14"先搬走再写新内容"；各主案正文见 ARCHIVE「一」，立项拍板见主案 A 节、交付见 B2/G 节）。

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
- [ ] **改了公式引擎 / 图表渲染 / 图层公共件 / 控件样式（含 `SegmentedControl`）/ **工具行 chips 规则（`chip_mru`）** / 标注模型 / 配方库 / 周期重采样（含**分钟档位**）/ 自选股 / 复权口径 / 图元拖动 / 坐标轴 / 图表宿主读数条（§7-B6）/ 回测成交口径（§7-B5）/ **数据源护栏（§9-V：非正价拦下 · 兜底源单位统一）** / **K 线图元画法（§9-V-3：一字板横档）** / **画线类型规格表 / 附属图元 / 图元小件 / 绘制会话 / 画线填充配色（`chart_style.annotation_fill`）**（即 `annotation_shapes` / `annotation_decos` / `annotation_items` / `annotation_draw_session` / `chart_style` 任一文件），跑过 `py tests/smoke_chart.py` 吗？**（**817 项**，纯组件、离屏）
- [ ] **改了行情工作台页面（`trading_desk.py`）/ `ui/widgets/desk_*.py` 任一模块 / 回测页「成交模型」行 / 标注交互层 / **画线类型目录（新增类型、`implemented` 翻牌）**？** → 跑 `py tests/smoke_pages_overlay.py`（**557 项**，含 **§7-B6 的「迁移护栏」+ 顶栏分段控件/分钟档位 + 工具行 chips + 图标轨/分页面板/折起（含**富余宽度归图表、折起后左侧只剩图标轨**两条不变量）+ 读数条 + **口径回执的"除权跳空定位 / 数据体检"**+ STEP 6 的"实现落在哪个 `desk_*.py`"**：公共面被改名、旧入口（`cb_period`/`cb_adjust`/`cmb_tool`）被复活、**把薄壳写成空函数**、**分栏比例退化**、**回执退回"不解释"**，都会立刻红）；
      并在其收尾的防污染自检名单里**加上任何新写的 `~/.jian_data/*.json`**（现在有 annotations /
      formula_library / watchlist / backtest_strategies / **preferences（1.23 起）** / **backtest_results（1.37 起）** 六个）
- [ ] **改了复盘页（`ui/views/review.py`）/ `ui/widgets/review_*.py` 任一模块？** → 跑
      `py tests/smoke_pages_overlay.py`（**557 项**，含 **「复盘页迁移护栏」+ §9-U 分栏不变量**：
      公共面被改名、**把薄壳写成空函数**、宏观/微观**分栏退化成写死的 5:4 平铺**、
      分栏高度不落 `review_ui.v_sizes`，都会立刻红）
- [ ] **改了全市场筛选页（`ui/views/scan_view.py`）/ `ui/widgets/scan_*.py` 任一模块？** → 跑
      `py tests/smoke_pages_overlay.py`（**557 项**，含 **「M2 公共面护栏」+ 版式与口径不变量**）。
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
      `py tests/smoke_pages_overlay.py`（**557 项**，含 **「M3 公共面护栏」+ 双窗格/区间/增量不变量**）。
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
- [ ] **改了回测页/工作台/复盘页的叠层、检测、图层开关、公式对话框、窗格编排、用户标注、配方库/互送、自选股/周期/复权、成交模型行，跑过 `py tests/smoke_pages_overlay.py` 吗？**（**557 项**，页面级；标注与配方一律用**临时库**，脚本末尾还有"用户真实库未被写"的**防污染自检**（现含 `backtest_strategies.json`）；三条离屏打桩见 §11.5-20，**别删**）
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
      （**817 项**：非正价行必须被拦下、兜底源成交量必须 ×100 成「股」、量纲接缝判据不许误报
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
- [ ] **收工时量过本文件字符数吗？**（§10-14 硬指标 **< 100,000** —— 这是"能被一次读完"的物理前提）
      → `py -c "import io;print(len(io.open('JIAN_RULES.md',encoding='utf-8').read()))"`
      **超了就先搬走再写新内容**，去向：逐文件细节 → `docs/JIAN_CODEMAP.md`；
      已收官主案 → `docs/JIAN_ARCHIVE.md`「一」；§11.6 历史块 → ARCHIVE「三」或 HISTORY §8；
      踩坑全量 → `docs/JIAN_PLAYBOOK.md`。**别靠"多读几遍"硬扛**（v6.50 实测 118k 就是硬扛的代价）。
