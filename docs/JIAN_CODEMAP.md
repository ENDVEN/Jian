# Jian 代码地图（`docs/JIAN_CODEMAP.md`）

> **本册是什么**：`JIAN_RULES.md` §4 的**逐文件目录树**（每层每个文件干什么、纪律落在哪一行），
> v6.50 按 §10-14「先搬走，再写新内容」从主文件搬出 —— 它是**查阅型**内容（只在"我要改 X 在哪个
> 文件 / 这个公共件是干嘛的"时才需要），却占了主文件 ≈19% 的字符。
>
> **怎么用**：先看 `JIAN_RULES.md` §4 的**顶层骨架**判断"东西在哪一层"，再来这里定位到具体文件。
> **大文件红黑榜（≥400 行）与体积纪律仍留在 `JIAN_RULES.md` §4** —— 行数只存那一处。
>
> ⚠ 行数口径 = **非空行**；只有 ≥400 行的文件才标数字（v6.16 用户拍板）。
> ⚠ 本册随代码同步更新，**别在这里写"现状数字"以外的结论**（结论归 §5 / §10）。
> ⚠ **下面树里的行数是"历史值"，可能滞后 —— 一律以 `JIAN_RULES.md` §4 体积红榜为准**（§10-14：行数只存那一处）。

---

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
│   │                    #        + §9-V 数据源护栏（非正价 / 量纲接缝）断言（**条数见 `JIAN_RULES.md` §11.7**）
│   │                    #       `py tests/smoke_chart.py`（在仓库根执行）
│   │                    #       ⚠ 两脚本开头**自设 UTF-8 stdout**（v6.21）—— Windows GBK 控制台
│   │                    #        下带 `↔`/`⇒` 的 print 会抛 UnicodeEncodeError，表现为
│   │                    #        "整段分节被跳过 + 假报失败"（修前 328/3、修后 356/0）
│   └── smoke_pages_overlay.py # 回测页/工作台/**复盘页**叠层 + 标注 + 互送 + 自选/周期(含**分钟**)/
│                        #       复权/坐标轴 + 顶栏分段控件/chips + 图标轨/分页面板/折起
│                        #       （§7-B6 STEP 3b/3c/4）+ 成交模型行/教学弹窗/导出口径**页面级**验收（**条数见 §11.7**）
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
│   ├── backtest_archive.py #  ★v1.37 §7-A4 回测历史存档：BacktestArchive（不可变快照+轻量索引，
│   │                    #      save/list/load/pin/delete/滞动淘汰/uuid 防注入）+ build_record/record_to_result
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
    │                    #      + ★v1.43/§7-B11 **后台下载**：持有 `self.downloads`(DownloadHub) 与底部
    │                    #        `download_bar`、导航角标 `nav_badge`（角标是按钮子件 ⇒ 事件不冒泡，
    │                    #        btn_data 与角标**都要**装 eventFilter）、`show_download_queue()` 懒建面板、
    │                    #        `closeEvent` 退出守卫（队列非空 ⇒ 确认 + `hub.shutdown()` 等线程真结束）
    ├── download_hub.py  # ★v1.43/§7-B11 **全局后台下载队列**（`QObject` 调度件，**不自造 QThread**，
    │                    #      只编排 `ui.workers.SyncWorker`）：`DownloadJob`（标签/清单/分区/进度/失败）
    │                    #      + `submit`（**串行 K=1**、同样清单去重）/ `cancel(单个或全部)` /
    │                    #      `retry_failures` / `snapshot`；信号 `jobs_changed/job_progress/job_failed/
    │                    #      job_finished/activity_changed` = **进度唯一真源**（页面与弹窗只做投影）；
    │                    #      + ★v1.43 收口 **`SingleSyncGate`**（单只同步互斥的**唯一实现**：
    │                    #        `blocked_by()` 问一句 / `hold()` 幂等占位 / `release()` 可重复释放；
    │                    #        四个调用点：`desk_data` / `backtest_flow`(指数+个股) / `breadth_flow`）
    │                    #      + `is_busy_for` / `last_finished` / `_settle_activity`（取消后也要收角标）；
    │                    #      回执文案走 `abort_reason_text` + `failure_hint`；
    │                    #      `hub_of(page)` 统一取件（拿不到→None 降级）
    ├── workers.py       #     全 app 唯一的 QThread 定义处(v5.13)：ScanWorker(扫湖)/
    │                    #      SyncWorker(批量)/SingleSyncWorker(单只)/BacktestRunWorker(回测)/
    │                    #      ConstituentsWorker(成分股)/FuturesImportWorker(交割单)/
    │                    #      CrossSectionWorker(M2/M3：分块+进度+取消+job_id 回包)
    │                    #      + **JobGuard 竞态守卫**（只接受最新一次任务的回包，§9-O5）
    ├── widgets/         # custom_widgets.py(K线图元/NoWheel控件族/悬浮删除/SPINBOX_QSS
    │                    #   + ★v1.42 **数值控件唯一工厂**：`SPIN_MIN_WIDTH=72` + `double_spin()/int_spin()`
    │                    #     （只给 minimumWidth、**绝不 setFixedWidth** —— 钉死宽度会把"0.6"截成"0"）
    │                    #   + ★v1.43 `download_bar.py`（底部下载条：空闲 hide、长文案进 tooltip、
    │                    #     水平 Ignored 不撑窗 §11.5-73；文案全取 `DownloadJob`）与
    │                    #     `download_queue_panel.py`（**非模态**队列面板：任务表 + 只重试失败 /
    │                    #     复制失败清单 / 全部中断；不存任务数据，每次 `hub.snapshot()` 现取）
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
    │                    #   / **readiness_flow.py(★v6.39 **就绪度体检 + 「⬆ 更新到最新交易日」的两页共用控制器**（D6：
    │                    #     「就绪度模型只有一份」）—— `start()` 后台体检 → 回执一行 + 缺口可见 →
    │                    #     `update_latest()` / `fill_missing()`（★v1.43：**提交给主窗口的下载队列**，
    │                    #     不再自持 SyncWorker；温柔抓取可中断 + >50 只二次确认）→ 复检；
    │                    #     页面进度条与回执 = **队列的投影**（只认自己那个 `job_id`）；
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
    │                    #   / **backtest_history_ui.py(★v1.37 §7-A4 运行历史版式/渲染**：
    │                    #        过滤条 `HistoryFilterBar`(M2/M3 置灰预留) / `HistoryTable`
    │                    #        (9 列 + 按 id 选中；数字着色走 `_SignedValueDelegate` —— 选中行
    │                    #        不叠色) / `MiniEquityChart`(净值+买卖点散点；⚠ 方法名不能叫 `plot`) /
    │                    #        `HistoryPreviewPane`(KPI 胶囊 + 迷你图 + 可折叠参数 + 6 个动作) /
    │                    #        `HistorySettingsBar`(自动存档开关 + 回执 + 上限只读))
    │                    #   / review_*.py —— ★1.26/§9-U+§9-L **复盘页拆出来的 5 个模块**
    │                    #     （同款约定：状态留页面、行为搬模块 + 页面保留同名薄壳）：
    │                    #     · review_layout.py(310：两行操作轴 + 宏观/微观**可拖竖向分栏** +
    │                    #         孤儿补录条 + 编辑卡；分栏高度记 `review_ui.v_sizes`)
    │                    #     · review_charts.py(244：日历热力图 / 月度净值+资金K线 / 持仓时长)
    │                    #     · review_playback.py(238：交易回放双点锚定 + 单点降级 + 数据缺口提示)
    │                    #     · review_editor.py(310：当日清单 / 详情头 / 复盘保存 / 孤儿缝合)
    │                    #     · review_flow.py(197：月年切换 / 五个筛选 / 时间跳转 / 视图刷新)
    ├── dialogs/         # import_futures / manual_entry / list_manager
    │                    #   / bulk_download(469 批量预下载：v6.10 成分股改走同步门面；
    │                    #     ★v1.43 **非模态 + 任务交 `main_win.downloads`**（旧版模态冻屏且
    │                    #     `SyncWorker(parent=弹窗)` ⇒ 关窗必须硬等；现在弹窗只是参数页 + 一个投影）
    │                    #   / formula_overlay.py(★v6.7 行情页公式编辑器：每段目标窗格+示例模板)
    │                    #   / fill_model_help.py(★v6.17 成交模型用户教学弹窗：三档口径 + T+1
    │                    #        用一套固定价格数字讲差别；**只读不写**，不改任何配置)
    └── views/           # dashboard / records
                         #   / review(✅ 1.26 · §9-U 收口 + §9-L 拆分收官：**1067 → 173**，
                        #        月/年双模态 + 交易回放 + 资金K线 + 截图画廊；
                        #        行为分居 5 个 `ui/widgets/review_*.py`，本文件只持状态 + 同名薄壳；
                        #        宏观(日历·图表)/微观(清单·编辑) 改为**可拖竖向分栏**并记住上次)
                         #   / trading_desk(**499** ★v6.12/P8 行情工作台——旧 market.py 661 已删除；
                         #        ✅ **1.23 版式收口收官（§7-B6 STEP 0–6）**：顶栏两行（周期/复权分段控件
                         #        + 分钟档位 + "最近使用优先" chips）+ 图标轨/五页分页面板/可折起
                         #        + 图表常驻读数条；**1375 → 345 → 499**（行为分居 `ui/widgets/desk_*.py`，
                         #        本文件只持状态 + 同名薄壳，既有断言零改动）)
                         #   / backtest_module + backtest(787 ✅ 1.22 拆分收官：编辑卡片+抽屉 / 摘要条 /
                         #         结果区 / 导出 / 运行流程 / 策略库 六块各归其位，本页只做装配与接线；
                         #         ★v1.37 §7-A4 又加：预览横幅(`_preview_bar`)/`exit_preview`/
                         #         `save_to_history`，并把「运行历史」接成第 4 子页)
                         #   / **backtest_history(★v1.37 §7-A4 运行历史**——薄壳：状态 + 接线；
                         #         版式/渲染分居 `ui/widgets/backtest_history_ui.py`，
                         #         存档读写分居 `data/backtest_archive.py`；pin 走**就地更新一行**
                         #         以保住选中)
                         #   / **scan_view(164 ★v6.37/§7-B1/B2 STEP 4：M2 全市场筛选页**——状态全在页面
                         #         + 同名薄壳；版式/流程/渲染分居 `ui/widgets/scan_layout|flow|result`)
                         #   / **breadth_view(197 ★v6.38/§7-B1/B2 STEP 5：M3 广度统计页**——状态全在页面
                         #         + 同名薄壳；版式/流程/空态/图表分居 `ui/widgets/breadth_layout|flow|
                         #         result|chart`；与 M2 共用内核 + 会话缓存，一个引擎两种视图)
                         #   / data_manager(506 🗄数据管理, v5.8；★v1.43 同步类动作一律**提交后台队列**，
                         #     不再 `_set_busy` 锁住整页按钮；完成时 `_on_hub_finished` 刷清单，
                         #     不在前台则记 `_pending_rescan` 等 `showEvent` 补刷)
```
