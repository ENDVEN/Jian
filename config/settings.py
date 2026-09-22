# config/settings.py
import os
from pathlib import Path

# ==========================================
# 基础配置 (Base Settings)
# ==========================================
APP_NAME = "Jian - 专业交易复盘系统"
# 版本演进（1.4.1 及以前，属"回测总集"语义编号，已废弃）：
#          v1.1 交易时间契约重构 → v1.2 交割单字段补全 → v1.2.1 微观测算修正
#          → v1.3 范围聚焦 + 持仓时长三级口径回归
#          → v1.4.0 回测能力总集（多函数段共享池 / 条件组 Gate / 风控离场器 / 指数 regime 门控）
#                   + 单股回测 UX 硬化 + 年度面板净额口径统一 + Dashboard 每日净额日历
#          → v1.4.1 数据管理页（数据湖删除/清点/增量/批量预下载）+ 行情同步统一收敛(MarketSyncService)
# ★ v6.16 起版本号**统一跟随 git**（用户 2026-09-15 拍板）：版本号 == 最近一次 push 的
#   **commit message 首词**（形如 `1.22`），每次 push 递增 **0.01**（1.22 → 1.23 → …）。
#   三处必须同步（§9-A）：① git commit message 首词；② 本常量；③ 仓库根 `version.json`。
#   1.21 = §7-B5「回测成交真实性」（三档成交时点 + T+1 硬约束 + 用户指引）。
#   1.22 = 回测页 UI 重构（摘要条 + 右侧遮罩抽屉 + 结果区吃满）+ §9-L 模块拆分收官。
#   1.23 = 行情工作台版式收口（§7-B6：顶栏两行 + 图标轨/可折起左栏 + 常驻读数条
#          + 最近使用的 chips + 分钟档位 1/5/15/30/60）+ trading_desk 拆分（1375 → 341）。
#   1.24 = 侧边栏重设计（§7-B8：手风琴卡片 + 自选分组 + 拖拽排序 + 配方库收编内置指标）。
#   1.25 = 画线工具重做（§7-B9：在图上点出来 + 平行/回归通道语义修正 + 32 种全可画
#          + 拖动/点选交互修复 + 扇形改延伸射线）。
#   1.26 = §9-U 复盘页版式收口 + §9-L `review`/`data_feed` 拆分收官。
#   1.27 = 文档分层重构（主文件瘦身 + `docs/` 三册，零业务代码）。
#   1.28 = §7-B1/B2 M2「全市场筛选」页落地（内核 / 会话缓存 / 后台线程 / M2 页，STEP 0–4）。
#   1.29 = §7-B1/B2 M3「广度统计」页落地（广度折线 + 指数副图联动 + ⚡增量 + ⟳全量重算，STEP 5）。
#   1.30 = §7-B1/B2 STEP 6 联动收尾（就绪度体检 / ⬇补齐缺失 / 成分股人话诊断 / 扫描就绪预设）。
#   1.31 = 修复 M2/M3 指数成分股代码格式（sh000300 → 接口要 000300；normalize_cons_code 边界规范化）。
#   1.32 = 修复成分股名称列全空（回包漏装配 _names）+ 内核警告 UI 出口（此前被整段吞掉）。
#   1.33 = M2/M3 体验修复轮：M3 图表可读性根治（bar 序号轴/双视觉/指数四图形/分界把手/轴对齐）
#          + M2 基准日先选后扫与缺数据全链路诚实化（闸门/就近落位/missing 进总数）
#          + 成分股换中证官网权威源（修「指数代码」选列回归与缺斤短两）+ 表格性能三件套。
#   1.34 = §7-B8 R7 副图换序收尾（⬆⬇ + 拖拽：复用 DragHandleListWidget 三道闸 + layer_model
#          可持久化 sub_order + 换序只改格位不改 target）+ 测试偏好隔离补正
#          （新键 sub_order 防泄真实库 / breadth 显示前置钉死），smoke 707→721 / 482→493。
#   1.35 = §7-B10 数据新鲜度全案（M1+M2/M3）：定稿守卫（is_daily_bar_settled/裁尾）+
#          真交易日历（trade_calendar/CalendarWorker，当日缓存+离线回退）+ M1 区间默认终点/滞后自动补/
#          回退回执 + M2/M3 一键「更新到最新」/滞后提示/基准日诚实化，smoke 737→742 / 508→513。
#   1.36 = §7-A2 回测结果图表导出：build_daily_series（逐日净值+买卖点共同源）+
#          CSV 末尾逐日净值数据段（Excel 选中列绘图）+ 新增 backtest_xlsx.py（openpyxl 内嵌
#          净值曲线图+买卖点 marker），smoke 745 / 514→521。
#   1.37 = §7-A4 回测历史存档：data/backtest_archive.py（不可变快照+轻量索引，save/list/load/
#          pin/delete/滞动淘汰/uuid 防注入；净值抽稀端点保底+并入成交日；读路径不写盘）+
#          ui/widgets/backtest_history_ui.py（版式/渲染）+ ui/views/backtest_history.py（薄壳，
#          第4子页“运行历史”：载入查看/复用/重跑/送行情/★重点/删）；默认自动存档可关、
#          每标的20/总500淘汰重点豁免；M1 只读回放（现场保存/恢复+禁导出+横幅）+
#          导出菜单「存为历史快照」；结果区净值曲线新增买卖点散点，smoke 782 / 554。
#   1.38 = §7-E2 代理失败“说人话” + 熔断提前：_classify_error 新增 "proxy"
#          （⚠ 必须先判文本指纹再退回 isinstance —— requests 的 ProxyError 也是 OSError 子类）
#          + looks_like_proxy_error + 三出口文案各一档（不写死本机端口）
#          + ThrottlePolicy.proxy_circuit_breaker=3 + abort_reason_text 三消费方共用
#          + bulk_download 竞态判据收编公共件 JobGuard，smoke 796 / 557。
#   1.39 = §7-E3 日线落盘列白名单：akshare_feed.DAILY_KEEP_COLUMNS（OHLCV + symbol/amount/
#          turnover/outstanding_share）+ _normalize_ohlcv 末尾 apply-if-present 裁列
#          ⇒ 源透传的中文列/期货列不再进湖；白名单 ⊇ 横截面内核所需列有交叉断言钉住；
#          存量 parquet 不动。
#   1.40 = §7-E5 下载层新鲜度对齐真交易日历：ThrottlePolicy.expected_latest（由调度层
#          ui/workers 每批注入一次「最近一个已收盘定稿的交易日」）+ _is_fresh 改判
#          last >= expected ⇒ 周末/节假日/盘中不再把全池判成"不新鲜"而白跑一遍空增量
#          （5400 只 ≈ 50 分钟换来零变化）；estimate_seconds 支持 stale_count +
#          format_duration 单一出口，修掉"永远显示约 50 分钟"的劝退式预估。
#          拿不到日历 ⇒ 原样回落旧判据（零行为变化，可安全回滚）。smoke 817 / 557。
#   1.41 = §7-B1/B2 补漏「需要动作必有入口」（用户实测：M2 换范围后体检说未下载 456，
#          整页无更新入口）：按钮名收成单出口 custom_widgets.SYNC_ACTION_LABEL
#          （core/data 不许指名 UI 按钮）+ M2/M3 摘要条常驻 btn_sync + 两页
#          _drop_stale_result 作废旧结果（ScanResult/BreadthResult.clear）+
#          "已有结果"分支绝不调 set_empty + 坏文件补「去数据管理」入口；
#          同批把 JIAN_RULES.md 从 99.1k 瘦身回 96.8k。smoke 817 / 566。
# ⚠ 必须与仓库根目录 version.json 保持同步：自动更新以二者比对为准（见 core/updater.py）
APP_VERSION = "1.41"

# ==========================================
# 界面配置 (UI Settings)
# ==========================================
MAIN_WINDOW_WIDTH = 1500
MAIN_WINDOW_HEIGHT = 950

COLOR_PROFIT = "#4CAF50"         
COLOR_LOSS = "#F44336"           
COLOR_PROFIT_TEXT = "#2E7D32"    
COLOR_LOSS_TEXT = "#C62828"      
COLOR_TEXT_PRIMARY = "#212121"   
COLOR_BACKGROUND = "#FFFFFF"     

RGB_PROFIT = (76, 175, 80)
RGB_LOSS = (244, 67, 54)
RGB_PROFIT_FILL = (76, 175, 80, 50) 
RGB_LOSS_FILL = (244, 67, 54, 50)

# ==========================================
# 业务逻辑配置 (Business Logic Settings)
# ==========================================
DEFAULT_STRATEGY = "未分类"
# NOTE(v1.2.1): 已删除 DEFAULT_ACCOUNTS —— 手工录入的"归属账户"只应列出真实存在
# 的账户（来自已导入数据），不预置"国内长线/国内短线"这类虚构账户。

# 绩效统计的虚拟初始资金 (用于计算收益率与回撤基准)
INITIAL_CAPITAL = 1000000

# ==========================================
# 路径与存储配置 (物理隔离)
# ==========================================
USER_HOME = Path.home()
USER_DATA_DIR = os.path.join(USER_HOME, ".jian_data")

DB_PATH = os.path.join(USER_DATA_DIR, "jian_trades.db")
SCREENSHOT_DIR = os.path.join(USER_DATA_DIR, "screenshots")

# ==========================================
# 更新检测配置 (Update Settings)
# ==========================================
# 这里填写你存放在云端的 version.json 文件的直链地址
# 格式要求形如：{"version": "1.1.0", "notes": "修复了Bug", "url": "https://下载链接"}
# 测试阶段，我们先用一个安全的占位符，一会教你怎么在本地测试它
UPDATE_CHECK_URL = "https://raw.githubusercontent.com/ENDVEN/Jian/refs/heads/main/version.json"