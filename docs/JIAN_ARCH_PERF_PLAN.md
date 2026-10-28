# 架构与性能优化方案 · ★1.93（2026-10-29 评估，未实现）

> 用户 2026-10-29：**"以资深架构师视角看架构 / 文档 / 启动速度 / 目录归类还有什么可优化"**。
> 本文件是**评估 + 执行清单**，不含代码改动；每条都带实测数字或代码位置，不靠感觉。
> **不做**：换框架、改视觉、改数据口径、追求"启动 <1 秒"（pandas/pyqtgraph/akshare 的硬导入成本≈1.1s，只能延迟、不能消灭）。

---

## 0. 结论摘要（先看这四条）

1. **启动 4.05s，其中 2.48s 是"9 个页面全在 `__init__` 里建好"** —— 首屏只用 1 个，其余 8 个白建（还各自扫数据湖）。
   ⇒ 惰性建页 + 三处热点修法，预计 **4.05s → 1.8~2.2s**，且**不改任何 UI 行为**。
2. **测试形态是全仓最大的结构债**：`tests/` 仅 2 个脚本却占 **14,389 行（22% 代码量）**，没有 unit 层/CI。
3. **文档总量 740k 字符**（RULES 97.8k 逼近 100k 上限 · HISTORY 172k 名叫"最近三版"实际全量 · ARCHIVE 242k），且**根目录没有 README**。
4. **目录归类基本规范**（根目录仅 7 个文件、`.gitignore` 到位），只有 `models/`、`samples/` 两处像遗留物。

---

## 1. 实测基线

| 项 | 实测 |
|---|---|
| 代码分布 | `ui/` 126 文件 **37,388 行**（57%）· `data/` 31 · **7,663** · `core/` 24 · **5,726** · `models/` 103 · `config/` 332 · `tests/` 2 文件 **14,389** |
| 超大文件 | ≥400 行 **41 个**；≥800 行 **11 个**（非测试最大 = `portfolio_view.py` 1,463） |
| 启动 | **4.05s** = Qt 0.04 + `import` 1.36 + 构造 **2.48** + 首绘 0.16（离屏实测，2026-10-29） |
| 导入成本 | pandas 0.54 · akshare **0.41** · pyqtgraph 0.18 · `ui.main_window` 0.39（后四项累计） |
| 构造热点（cProfile，有放大但排序可信） | `getsize` 1.69 / `nt.stat` 1.04 / parquet init 1.18 / `readiness._footer_last_date` 0.55（2,673 次）/ `iterrows` **15,055 次** / `strptime` **26,391 次** / `portfolio_view.__init__` 0.47 / `breadth_flow.resolve_scope` 0.67 |
| 页面 | **9 个页面全部在 `__init__` 建好**（overview/records/review/market/backtest/portfolio/hub/data/settings），首屏只显示 market |
| 文档 | RULES **97,765 字符**（上限 100k）· docs 合计 **641,993**：ARCHIVE 242k · HISTORY 172k · PLAYBOOK 87k · CODEMAP 61k |
| 工程配套 | 无 `README.md` · 无 `pyproject.toml` · 无 `pytest.ini/conftest.py` · 无 `.github`（无 CI） |

---

## 2. 架构层判断

### 2.1 三个真问题

**① 测试形态（最高优先级）**
- 事实：`smoke_pages_overlay.py` **8,703 行** + `smoke_chart.py` **5,686 行**；无 unit 层；跑一次 ~3 分钟；失败靠行号人眼找。
- 后果：任何纯函数（`portfolio_stats` / `scan_store` / `sync_service` 的合并与节流）都要搭 Qt 世界才能验 ⇒ 改动成本高、反馈慢。
- 方向：三层层级 —— `tests/unit/`（pytest，纯函数，秒级）· `tests/integration/`（临时数据湖）· `tests/ui_smoke/`（现有两个脚本，瘦身到只验路由/可见性/接线）。

**② 视图层过厚、没有分区规范**
- 事实：`ui/widgets/` **94 个文件平铺**；`ui/views/` 15 个；11 个文件 ≥800 行。
- 已有正确先例：`ui/widgets/portfolio_parts.py`（把纯显示件拆出去）。
- 方向：定一条组织法写进 RULES —— **`views/<page>.py` 只做装配与事件接线；子件进 `widgets/<page>/`**（比"禁止超 400 行"可执行）。

**③ 分层边角**
- `core/updater.py` 引 `PyQt6`（唯一反向依赖，可接受但要注明例外）。
- `core ↔ data` **双向**：`data/*` 用 `core.utils/preferences`；`core/engine.py` 直接 `data.market_db`。
- `models/trade.py`（103 行、5 处引用）夹在根目录，实为领域模型。
- `DataLakeManager()` 到处 `new`（每次 `makedirs` 10 个目录），而 `get_industry_store()` 是单例 ⇒ **两种风格并存**。

### 2.2 明确不做的
- 不换 Qt/不引入 DI 容器/不做微服务化（桌面单体是正确形态）。
- 不为了"行数少"而拆纯数据模块（`config/settings.py` 34KB 是常量表，拆了反而难查）。

---

## 3. 启动与运行速度（本方案主战场）

### 3.1 热点与归属

| 热点 | 证据 | 归属 |
|---|---|---|
| 9 个页面全建 | `ui/main_window.py:138-150` | 首屏只用 `TradingDeskView` |
| 扫描就绪度 | `readiness._footer_last_date` 2,673 次（逐文件读 parquet footer + stat） | 由页面构造触发（`ReadinessWorker` 之外的同步路径） |
| 广度范围解析 | `breadth_flow.resolve_scope` 0.67s | 广度页构造即解析 |
| 名册遍历 | `engine.roster_names()` 用 `iterrows`，15,055 次调用 | 每次取名字都全表迭代 |
| 日期解析 | `trade_calendar._to_date` `strptime` 26,391 次 | 日历逐条转 |
| 组合页构造 | `portfolio_view.__init__` 0.47s（`refresh` 0.41 + `setCurrentRow` 触发 `_save_ui` 0.37） | 构造期渲染 + 写盘 |

### 3.2 目标

| 阶段 | 目标 | 依据 |
|---|---|---|
| P0 完成 | **≤2.2s** | 惰性建页 −1.5~2.0s，其余三件 −0.6~0.9s（有重叠） |
| P1 完成 | **≤1.8s** | akshare 惰性 −0.4s、组合页延迟渲染 −0.4s |
| 不追求 | <1.0s | pandas+pyqtgraph+Qt 硬成本 ≈1.1s |

---

## 4. 文档编排

| 问题 | 证据 | 建议 |
|---|---|---|
| 无 README | 根目录只有 RULES/main.py/requirements | 新增 40 行 README：是什么 / 怎么跑 / **目录地图** / **文档地图** / 断言怎么跑 |
| HISTORY 名不副实 | 自称"最近三版"，实际 **172k** | `docs/history/2026.md` 分卷；主文件只留最近 10 版 + 指针 |
| RULES 临界 | 97.8k / 100k，已靠"搬走"回血 3 次 | §11.5 的 149 条索引拆到 `docs/PLAYBOOK_INDEX.md`，RULES 只留红线 + 指针 |
| CODEMAP 会漂移 | 61k 手工维护 | `scripts/gen_codemap.py` 生成，或降级为"每模块一行" |
| 命名/分类不一 | 计划类（ETF/HUB/SWEEP/M3/CLEANUP）与参考类（SETUP/CODEMAP）混放 | `docs/plans/`（`YYYYMMDD-主题.md`）· `docs/guides/` · `docs/reference/` |

---

## 5. 文件归类

| 位置 | 问题 | 建议 |
|---|---|---|
| `models/trade.py` | 与 core 并列、只服务 core/data | 并入 `core/models/` |
| `tests/` | 2 个脚本、无 `__init__.py`、无 pytest 结构 | `tests/{unit,integration,ui_smoke,fixtures}` |
| `samples/` | 交割单 xlsx + 函数样例放根目录，易被当代码 | `docs/samples/` 或 `tests/fixtures/` |
| `design/` | 69 个文件（HTML 样板 + 截图 + 3 个 py） | 脚本挪 `scripts/`，样板保留 |
| `scripts/` | 只有 2 个 | 集中 `gen_codemap` / `probe_startup` / `screenshot` |

> 根目录其余很干净（7 个文件）；`.gitignore` 已覆盖 `_tmp_*` / `*.db` / `screenshots/`。

---

## 6. 底层改动清单

### P0（启动，本批只做这四件 + 一条探针）

| # | 文件 | 改动 | 关键点 |
|---|---|---|---|
| P0-1 | `ui/main_window.py` | 页面改**惰性**：`_PAGE_FACTORIES`（键→构造闭包）+ `page_x` 变 `property` → `_ensure_page()`；`_PAGES` 换成只读映射（`__getitem__` 建页、`__iter__` 只出键） | ✅ 已核实：全仓 **0 处** `content_area.setCurrentIndex/indexOf` ⇒ 后插页不破坏路由；**132 处**外部 `win.page_*` 引用经 property 语义不变 |
| P0-2 | `core/engine.py` | `roster_names()` 的 `iterrows` → `dict(zip(df['symbol'], df['name']))` | 15,055 次调用 → 一次向量化；5000 行从 ~0.35s → ~5ms |
| P0-3 | `data/trade_calendar.py` | `_to_date` 增批量版 `to_dates(seq)`；`latest_settled_trading_day/previous_trading_day` 内部改走批量（或加 `functools.lru_cache`） | 26,391 次 `strptime` → 单次 `pd.to_datetime` |
| P0-4 | `data/readiness.py` | `_footer_last_date` 以 `(path, size, mtime_ns)` 为键做 **LRU(4096)**；`probe_readiness(..., use_cache=True)` | 文件没变就不重读 footer；补下载后 mtime 变 ⇒ 自动失效 |
| P0-5 | `scripts/probe_startup.py`（新增） | 打印"import / 构造 / 首绘"三段耗时 + 已建页面数 | 优化前后**同一把尺子**；不参与运行 |

### P1（吸收进下一轮）

| # | 文件 | 改动 |
|---|---|---|
| P1-1 | `data/akshare_feed.py` | 顶层 `import akshare` → 惰性（`_ak()` 内 import），启动省 0.4s |
| P1-2 | `ui/views/portfolio_view.py` | `refresh()` 延迟到页面**首次可见**；`_save_ui` 加 300ms 防抖（现在 `setCurrentRow` 就写盘） |
| P1-3 | `data/market_db.py` + 各调用点 | `get_lake()` 单例（与 `get_industry_store()` 统一风格），去掉重复 `makedirs` |

### P2（结构/文档，独立轮次）
测试分层 · README + 文档分卷 · `models`→`core/models` · `widgets` 按页分组 · CI 跑 unit + smoke 子集。

---

## 7. 步骤拆分（P0 可执行）

| 步骤 | 内容 | 验收（可机器判） | 估时 |
|---|---|---|---|
| P0-1a | `scripts/probe_startup.py` + 记录基线 4.05s | 三个数字打印出来，写进本文件 | 0.1 轮 |
| P0-1b | 惰性建页（工厂 + property + 只读 `_PAGES`） | 构造后 `已建页面 == {'market'}`；`win.page_portfolio` 访问后变 2；`list(win._PAGES)` **不触发**构建；导航 9 页仍能切 | 0.3 轮 |
| P0-2 | roster 向量化 | 单测：5000 行 <10ms；`roster_names()['600000']` 仍对 | 0.05 轮 |
| P0-3 | 日历批量 | 单测：`to_dates` 与逐条结果逐位一致；启动期 `strptime` 调用数下降 | 0.1 轮 |
| P0-4 | footer LRU | 单测：同文件二次调用不 stat/不解析（用计数器打桩）；改动 mtime 后自动失效 | 0.15 轮 |
| P0-5 | 断言 + 文档 | 冒烟新增 §1.93 段 6~8 条；实测启动 ≤2.2s 写进本文件 | 0.2 轮 |

合计 **≈0.9 轮**（一次会话可完成）。

---

## 8. 怎么证明"没退化"（不靠墙钟）

墙钟受机器负载影响，断言会 flaky ⇒ 用**行为断言**：
1. 构造后已建页面集合 == `{"market"}`；
2. 访问 `win.page_portfolio` 后集合 +1，且 `content_area.count()` 同步 +1；
3. `list(win._PAGES)` / `win._PAGES.get('portfolio')` 行为与旧版一致（后者会建页）；
4. `probe_readiness` 二次调用时 `os.stat` 调用数为 0（打桩计数）；
5. `roster_names()` 一次调用内 `DataFrame.iterrows` 调用数为 0（打桩）；
6. `trade_calendar` 批量转换结果与逐条版**逐位相等**（随机 200 个日期）；
7. `scripts/probe_startup.py` 输出三段耗时（人工对比，不作断言）。

---

## 9. 风险与规避

| 风险 | 规避 |
|---|---|
| 惰性建页打断 132 处 `page_*` 引用 | 用 `property` 而非 `__getattr__`（IDE 可跳转、错误更早暴露）；先跑全量冒烟 |
| `_PAGES` 被外部遍历导致"全部建回来" | 只读映射：`__iter__` 出键、`items()` 才建；现有遍历式断言改用键 |
| 惰性后首次切页卡顿 | 首次切页时建页 ≈0.3~0.5s，可接受；P1 再加"切页预建相邻页" |
| footer 缓存读旧数据 | 键含 `mtime_ns + size`，补下载必失效（与组合页缓存同款纪律） |
| 日历批量改动影响交易日判定 | 保留 `_to_date` 原函数，新增批量版；单测逐位对比 |
| 优化后"感觉快了但没证据" | `probe_startup.py` + 行为断言，前后各跑一次并写进文档 |

---

## 10. 延申（后续轮次）

- **P2-1 测试分层**：先搬 3 个纯模块（`portfolio_stats` / `scan_store` / `sync_service` 的纯函数）做试点，验证"秒级反馈"。
- **P2-2 文档**：README + `docs/history/` 分卷 + RULES 瘦身（目标 ≤85k）。
- **P2-3 目录**：`models` 归位、`samples` 迁移、`widgets` 按页分组（`widgets/portfolio/` 等）。
- **P2-4 CI**：GitHub Actions（ubuntu + offscreen）：`pytest tests/unit` + `smoke_chart` 子集（`SMOKE_FULL=0`）。
- **P3**：全市场扫描耗时（`cross_section` 758 行）—— **先加计时再动**，当前无实测数据，不盲优化。

---

## 11. 待确认（3 条）

1. **惰性建页**会让"第一次切到组合页"多 0.3~0.5s（一次性）—— 接受吗？
2. **P0 只做启动四件**（不碰测试分层与目录搬动），还是希望同批把 README 也补上？
3. `scripts/probe_startup.py` 是**长期保留**（当性能基线工具）还是用完即删（§10-13）？建议保留。
