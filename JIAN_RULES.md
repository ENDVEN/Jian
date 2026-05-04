# Jian - 项目开发规范与上下文记忆 (v4.5)

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
- **数据源接入:** AkShare (全A股/期货花名册拉取与日线数据接入)
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
2. **确定性哈希主键:** 针对外部无时间戳数据（如 CFMMC 期货交割单），强制使用 **MD5(账户名_单号_数量_进场日期)** 生成绝对唯一的 `internal_id`，以支持多次反复导入与跨月缝合。
3. **数据物理隔离:** 用户产生的 `.db` 文件与行情数据湖必须存在于操作系统的独立数据目录（如 `~/.jian_data`）中。
4. **组件物理拆分:** 严禁将不同的业务逻辑揉在一个大文件里（例如已将所有的 Dialog 拆分为独立模块）。

## 4. 目录结构 (Phase 4 演进态)
```text
Jian/
├── main.py                 # 程序唯一启动入口，负责环境初始化
├── JIAN_RULES.md           # 本规范与记忆文件 (当前版本 v4.5)
├── config/                 # 【配置中心】
│   └── settings.py         # 全局常量、颜色、路径、UI 样式统一定义
├── models/                 # 【数据模型】
│   └── trade.py            # 核心数据契约 (TradeRecord)，含强化版 internal_id 钩子
├── core/                   # 【核心逻辑引擎】
│   ├── engine.py           # 中央数据引擎 (DataEngine)，统筹内存状态与 DB 报告
│   ├── database.py         # 业务数据库管家 (SQLite)，负责复盘单据的 CRUD 与防呆拦截
│   ├── indicators.py       # 纯 Pandas 原生技术分析引擎 (TAEngine)
│   ├── analyzer.py         # 绩效评估与回撤计算引擎
│   └── updater.py          # 异步后台版本检测 (QThread)
├── data/                   # 【数据来源与持久化】
│   ├── data_feed.py        # 专职处理脏数据清洗与 CFMMC 交割单的 FIFO 匹配缝合
│   ├── akshare_feed.py     # 外部金融数据爬取代理 (A股/期货日线及花名册)
│   └── market_db.py        # 工业级 Parquet 数据湖管家 (DataLakeManager)
└── ui/                     # 【表现层 (UI)】
    ├── main_window.py      # 总路由器 (Controller)，极简代码，只负责引入组件与事件分发
    ├── widgets/            # 【可复用图元与控件】
    │   └── custom_widgets.py   # Hover 悬浮列表、Pokorny 风格 K线图元等
    ├── dialogs/            # 【物理拆分后的独立弹窗】
    │   ├── list_manager.py     # 账户/策略管理与删除警告
    │   ├── manual_entry.py     # 手工录入交易单
    │   ├── import_futures.py   # 期货 CFMMC 专属导入 (QThread 静默拆单与防重报告)
    │   └── import_stocks.py    # 通用外部数据映射向导 (手动绑定字段)
    └── views/              # 页面级大型视图组件
        ├── dashboard.py    # 资金与表现面板
        ├── records.py      # 流水表格，含多维高级过滤器与全量 CSV 导出
        ├── review.py       # 深度复盘双模态工作台
        └── market.py       # (建设中) 市场行情对照与沙盒视图
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

🚀 Phase 4.2+: 前端集成与业务展现 (当前阶段)

[ ] 打通视图层: 将数据湖的数据喂给 ui/views/market.py，并利用 custom_widgets.py 中的底盘渲染出行情图表，提供输入代码查询交互。

[ ] 复盘涂鸦板: 允许在行情图表上绘制支撑/阻力线并持久化。

[ ] 热力图看板: 升级 dashboard，引入 GitHub 风格日历热力图。