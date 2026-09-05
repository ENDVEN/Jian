# Jian - 项目开发规范与上下文记忆 (v4.6)

## 1. 项目愿景与定位
- **项目名称:** Jian (专业量化交易复盘与分析系统)
- **项目目标:** 采用 MVP 模式与敏捷开发，打造一个具有企业级地基、高扩展性、数据绝对安全的桌面端软件。
- **核心理念:** 
  - 坚持代码的高内聚、低耦合（SRP 原则），严禁模块臃肿。
  - 坚持程序本体与用户数据的物理隔离，保障数据主权。
  - 坚持操作的绝对幂等性（防呆、防重、防手残）。

## 2. 技术栈与核心设施
- **UI 框架:** PyQt6 / PySide6 (主界面与视图组件)
- **图表引擎:** PyQtGraph (自定义 `CandlestickItem`，强制抗锯齿、去描边、单色填充，严格遵循 Michael Pokorny 视觉规范)
- **数据源接入:** AkShare。日线行情统一走**新浪源为主 + 东财源兜底** (A股 `stock_zh_a_daily` 与期货 `futures_main_sina` 同源，多数受限网络可达；东财 `stock_zh_a_hist` 兜底北交所等标的)
- **指标计算:** 纯原生 `Pandas` 向量化 TAEngine (零编译依赖，完美兼容 Python 3.14+，已实现 MA/BOLL/MACD)
- **持久化方案:** 
  - **业务数据:** SQLite (`INSERT OR IGNORE` 事务与哈希去重)
  - **海量时序数据:** Data Lake 数据湖架构 (利用 `pyarrow` 实现高速分区 `.parquet` 存储)
- **并发控制:** 任何耗时 I/O 强制使用 `QThread` `Worker`，保证 UI 丝滑。

## 3. 核心架构设计原则 (MVC 深度解耦与数据守护)
本项目严格遵循以下开发铁律：

1. **防呆入库与反馈闭环 (Idempotent Design):** 
   - 数据库插入必须严格使用 `INSERT OR IGNORE`。
   - 任何导入操作必须通过统计报告（`inserted`, `ignored`）向 UI 层清晰反馈结果，让用户对数据的去重和拦截有绝对掌控感。
2. **确定性哈希主键:** 针对外部数据（如 CFMMC 期货交割单），使用 **MD5(账户名_单号_交易日期_数量)** 生成绝对唯一的 `internal_id`，以支持多次反复导入与跨月缝合。
3. **数据物理隔离:** 用户产生的 `.db` 文件与行情数据湖必须存在于操作系统的独立数据目录（如 `~/.jian_data`）中。
4. **组件物理拆分:** 严禁将不同的业务逻辑揉在一个大文件里（例如已将所有的 Dialog 拆分为独立模块）。
5. **单一时间锚点 (v1.1):** 交割单现实只有"交易日期"，严禁为填充字段而虚构开/平仓时间。一切日历/绩效/回放都以唯一 `trade_time`（盈亏实现日）为锚点；无法自洽的统计（如持仓时长）直接下线而非伪造。

## 4. 目录结构 (Phase 4 演进态)
```text
Jian/
├── main.py                 # 程序唯一启动入口，负责环境初始化
├── requirements.txt        # 依赖清单 (PyQt6 / pyqtgraph / pandas / pyarrow / akshare)
├── JIAN_RULES.md           # 本规范与记忆文件 (当前版本 v4.6)
├── config/                 # 【配置中心】
│   └── settings.py         # 全局常量、颜色、路径、UI 样式统一定义
├── models/                 # 【数据模型】
│   └── trade.py            # 核心数据契约 (TradeRecord, v1.1 单一 trade_time)，含强化版 internal_id 钩子
├── core/                   # 【核心逻辑引擎】
│   ├── engine.py           # 中央数据引擎 (DataEngine)，统筹内存状态与 DB 报告
│   ├── database.py         # 业务数据库管家 (SQLite)，负责复盘单据的 CRUD 与防呆拦截
│   ├── indicators.py       # 纯 Pandas 原生技术分析引擎 (TAEngine)
│   ├── analyzer.py         # 绩效评估与回撤计算引擎
│   ├── utils.py            # 无副作用公共工具 (品种主体提取、交易时间格式化)
│   └── updater.py          # 异步后台版本检测 (QThread)
├── data/                   # 【数据来源与持久化】
│   ├── data_feed.py        # 账单解析抽象层 (BaseTradeParser + PARSER_REGISTRY) + CFMMC FIFO 缝合
│   ├── akshare_feed.py     # 外部金融数据爬取代理 (A股/期货日线及花名册)，含市场智能路由
│   └── market_db.py        # 工业级 Parquet 数据湖管家 (DataLakeManager)
└── ui/                     # 【表现层 (UI)】
    ├── main_window.py      # 总路由器 (Controller)，极简代码，只负责引入组件与事件分发
    ├── widgets/            # 【可复用图元与控件】
    │   ├── custom_widgets.py       # Hover 悬浮列表、Pokorny 风格 K线图元等
    │   ├── screenshot_gallery.py   # 复盘截图画廊 (粘贴/导入/预览/删除/序列化)
    │   └── yearly_review.py        # 年度复盘面板 (月度盈亏卡片/策略贡献/净值曲线)
    ├── dialogs/            # 【物理拆分后的独立弹窗】
    │   ├── list_manager.py     # 账户/策略管理与删除警告
    │   ├── manual_entry.py     # 手工录入交易单
    │   ├── import_futures.py   # 期货 CFMMC 专属导入 (QThread 静默拆单与防重报告)
    │   └── import_stocks.py    # 通用外部数据映射向导 (手动绑定字段)
    └── views/              # 页面级大型视图组件
        ├── dashboard.py    # 资金与表现面板
        ├── records.py      # 流水表格，含多维高级过滤器与全量 CSV 导出
        ├── review.py       # 深度复盘双模态工作台 (含 K线交易回放)
        └── market.py       # 市场行情对照与沙盒视图
```

## 5. AI 协作约定 (给 AI 的最高指令)
当你（AI）阅读到此文件时，请在接下来的对话中严格遵守以下规则，不容妥协：

Michael Pokorny UI 准则: 任何新增图表元素必须严格遵循“抗锯齿、去描边、单色高对比”原则。

防阻塞底线: 涉及 Parquet 读取或网络拉取时，主动封装入 QThread 异步方案。

架构纪律: 新增功能时，请主动评估应该将代码放入 core (计算), data (获取/存储), 还是 ui (展示) 层，绝不可在 ui 文件中写死 SQL 或爬虫逻辑。

代码全量输出兜底: 修改核心文件时，请尽量提供该文件的全量代码或明确的插入锚点，防止小白用户复制时引发缩进灾难。

## 6. 开发进度与 Roadmap
✅ Phase 1~3: 完成基础 MVP 闭环（UI组件物理隔离、SQLite防重持久化、CFMMC跨月交割单智能缝合）。

✅ Phase 4.1 (基础设施建设): 完成 Parquet 极速数据湖 (market_db.py)、零依赖向量化指标库 (indicators.py)、AkShare 接口封装 (akshare_feed.py)。

✅ v1.1 (数据契约重构): 交割单导入与全链路仅保留单一 `trade_time`；旧库双时间自动无损迁移；交易回放改单点锚定式；删除无法自洽的"时长分析"。

🚀 Phase 4.2+: 前端集成与业务展现 (当前阶段)

[ ] 打通视图层: 将数据湖的数据喂给 ui/views/market.py，并利用 custom_widgets.py 中的底盘渲染出行情图表，提供输入代码查询交互。

[ ] 复盘涂鸦板: 允许在行情图表上绘制支撑/阻力线并持久化。

[ ] 热力图看板: 升级 dashboard，引入 GitHub 风格日历热力图。

## 7. v1.1 数据契约变更记录 (改前必读)

### 7.1 发生了什么
交割单 (CFMMC) 只有"交易日期"，原先 `entry_time` / `exit_time` 双时间结构会在流水表格制造虚构信息。v1.1 将二者合并为**单一 `trade_time`**：

- 数据库 `trades` 表：`entry_time`、`exit_time` 两列删除，改为 `trade_time`。
- 启动时自动迁移：`DatabaseManager` 检测到旧结构会把表改名备份后重建；
  数据归并规则 **`COALESCE(exit_time, entry_time)`**（平仓日优先，开仓日兜底），
  已有 `internal_id` 原样继承，无主键的远古库会逐行补全。
- 导出 CSV 只包含 `trade_time` 单时间列。
- `format_trade_time()`：若时间恰为当天零点只显示 `YYYY-MM-DD`，有具体时分才带 `HH:MM`，杜绝虚假 `00:00`。

### 7.2 已下线的模块与理由
| 模块 | 去处 | 理由 |
|---|---|---|
| 流水表"进场/平仓时间"列与"持仓(h)"列 | 删除 | 数据源无开平仓双时间 |
| 流水页"持仓时间"高级过滤器 | 删除 | 依赖时长，逻辑无法自洽 |
| 复盘页 "⏳ 时长分析" 页签与其散点图 | 删除 | 同上 |
| `core/utils.parse_time_gap_hours` | 删除 | 被以上功能独占 |

### 7.3 交易回放的新的表现形态 (单点锚定式)
交割单无法提供进场/离场两个坐标点，回放改为：
1. 以 `trade_time` 为圆心截取前后 ±45 天本地 K 线 (`PLAYBACK_CONTEXT_DAYS`);
2. 定位时间上最接近的一根 K 线为锚点，画垂直虚线;
3. 在该 K 线上叠加标记：**箭头方向 = 多/空**，**颜色 = 盈/亏**，并带 PnL 文字;
4. 本地缺数据或锚点误差 > 7 天 (`MAX_ANCHOR_GAP_DAYS`) 时明确提示，
   绝不硬凑坐标，并自动切回"累计盈亏"页。

### 7.4 后续使用注意事项
- **升级即迁移**：旧库首次启动自动重建为 v1.1，迁移日志走 logging；
  数据量不大，迁移在后台瞬时完成。
- **约定俗成**：新增任何按日统计/日历/回放功能一律使用 `trade_time`；
  严禁重新引入成对的进场/离场时间列。
- 手工录入与股票导入向导均已改为单"交易时间"，向导中该字段现在是必选映射项。
- 若将来真能拿到带时分秒的开/平仓逐笔流水，应新增**可选**的 `entry_time`
  作为独立附表字段，而不是推翻 `trade_time` 主锚点设计。