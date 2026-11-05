---
status: history
topic: 历史正文 · recent
read_when: 追某版改动或决策链
skip_if: 只看现状
verified: 2026-11-02
---

# 历史 · 最近版本（1.90–1.93）

> 由原 `JIAN_HISTORY.md` 切分而来（该文件已删除）（2026-11-02 · D2c）。**内容一字未改**，历史数字仍然冻结。
> 范围：★1.90 三批 / ★1.91 / ★1.92 / ★1.93 的逐版叙事
上一卷：`narrative.md`（旧版叙事）· 更早：`changelog-1.md` / `changelog-2.md`

---

## ★1.90 · 组合页收口（第一批：基准只留指数）（2026-10-28 提交）

> 已随 **1.90** 一次提交（用户 2026-10-28：不要拆成多个版本号）。

**动因**：用户实测截图 —— 组合页「基准」下拉里出现 899050 / 000009 / 000010 / 000015 / 000016 /
000688 / 000698 / 000852 一串**裸代码**，原话"严重影响使用体验"，要求"基准里只保留指数或者行业指数"。
顺着上一轮审计的 6 条真问题一起收口。

**改了什么**
1. **基准下拉只列指数/行业指数**（`ui/views/portfolio_view.py`）：名称唯一真源 = `data/akshare_feed.INDEX_PRESETS`
   （30 项，带市场前缀）；先"已下载"再"未下载"；**认不出名字的本地指数不列**；个股不再作为基准；
   历史存档里的个股/未知基准**原样显示**为「当前 · 不在指数预设内」（不静默换成沪深300）。
   顺带修：899050 旧前缀启发式猜成 `sh899050` ⇒ 永远读不到（北交所是 `bj`），现在由预设表精确给文件名。
2. **基准缺日不再填 0 收益**：缺的交易日留 `NaN`（图上断线）+ 卡头写明"基准自 X 起才有数据"，
   超额收益只在**共同区间**计算（旧版会画出一条假平线，超额也失真）。
3. **用户可见文案的 markdown 双星号清零**（`portfolio_view.py` / `portfolio_edit.py` 共 6 处；QLabel 只认 HTML）。
4. **"组自动跟随"口径与代码对齐**：模块 docstring / 按钮说明改为"存成分快照 + `source_group` 仅溯源"；
   `_render` 新增**来源组成分与快照不一致**的提示（并说明"要对齐请重新导入，权重会回到等权"）。
5. **`core/portfolio_stats.py` 的口径说明与实现一致**：删掉两行永不触发的 `fillna(0.0)` 死代码，
   写明"交集口径 ⇒ 某只停牌那天整天不进组合"；`nav_series` 标注为"仅对照/测试用"。
6. **状态残留**：`_pf_cur` 提到早退之前（否则空组合时切"按行业 / 近 3 月"会渲染上一只组合）；
   日线缓存键加**文件 mtime**（`DataLakeManager.file_mtime` 新增，只 stat）⇒ 补下载后曲线自动更新。
7. **吞异常改出声**：换基准保存失败 → 提示 + 回退到磁盘那份；行业同步"抓到但没存盘"/worker error → 回执说清。
8. **佣金单一来源**：`nav_with_costs(rate=None)` 缺省跟随全局「回测佣金」；1.81 的"禁写死费率"护栏
   扫描名单补上 `portfolio_view.py` + `portfolio_stats.py`（旧名单漏了它们，才让一份 0.0003 藏在那里）。
9. **拆件**：`PfCard` / `RingChart` / `overview_qss` / `dot_title` → 新建 `ui/widgets/portfolio_parts.py`
   （`portfolio_view.py` 1304 行，仍越线；`_build`/`_render_p1` 留待下一轮）。

**断言**：`smoke_pages_overlay` 新增 ★1.90 段 9 条（基准只列指数 · 中文名 · 已下载在前 · 缺日不填 0 ·
cap 标签如实 · 文案无双星号 · 缓存带 mtime · 来源组提示 · 费率缺省跟随设置）。
实测：`smoke_chart` **1076/0** · `smoke_pages_overlay` **1210/0**。

**文档**：`docs/RULES.md` 断点 / §7-B17 基准口径 / §4 行数 / §11.7 断言数 / §11.5-146 索引；
`docs/plans/done/PORTFOLIO.md` §五-3 与新增 §A2；`docs/playbook/INDEX.md` §11.5-146 全文。

---

### ★1.90 第二批 · 市值权重真接 / 差额自动进现金 / 变更对照

> 同一版 **1.90** 的第三批（用户要求不拆版本号）。

**动因（用户实测三连问）**：① "你说接入了市值权重，为什么还显示暂未接入？"（上一轮只做到"可接线"）
② 合计 80% 时「确定」是灰的、**连一句提示都没有**，等于逼用户拿计算器凑 100%
③ "随便改编辑成分，调仓记录里全是空的" —— 他希望每次改完都能看到"原来多少 → 现在多少 → 变了几个点"。

**改了什么**
1. **市值权重真接**（`core/portfolio_stats.market_caps / cap_weights` + `portfolio_view.caps_of`）：
   流通市值 = **最新收盘 × 最新流通股本**（`outstanding_share`）；缺这一列的票**点名**、权重记 0
   （东财兜底源不给该列），绝不按剩下的重新归一冒充整个组合。权重是**编辑时快照**，口径写在页脚。
2. **合计不足 100% ⇒ 点「确定」自动计入现金**：元凶是 `_refresh_total` 在合计≠100 时把「确定」
   `setEnabled(False)` ⇒ 1.89 写的"留作现金"分支**永远走不到**（用户看到的就是灰按钮）。
   现在：不足 ⇒ 按钮可用 + 实时写明"现金 X% → Y%"；超过 ⇒ 才禁用并说清超出多少。
3. **编辑页三列对照**：`原权重 %`（只读）/ `新权重 %`（可编辑）/ `变化`（`▲ +1.50` 绿、`▼ -0.80` 红、
   `＋ 新增` 蓝），表格上方还有一行**变更摘要**（改权重 N 只 · 新增 · **删除的票在此点名** · 现金变化）。
4. **调仓记录接「手动改成分」**：`data/portfolio_store.diff_members / append_change`，
   组合新增 `changes`（只留最近 50 条）；卡片现在写"手动改成分 N 次 · 再平衡 M 次"，每条列出
   "哪只票 30.00→35.00（+5.00）"。**整组导入**也记一条。旧版只记月末再平衡 ⇒ 买入持有下永远是空的。
5. **持仓视角按钮与表格对齐**：`_set_hold_mode` 在 `_pf_cur` 为空时改为**从存储捞当前组合再渲染**
   （旧版会"按钮跳到按标的、表格还是按行业聚合的『未分类 90%』"）。
6. 卡片标题从"只记软件内 · 按月末"改为"手动改成分 + 月末再平衡"。

**断言**：`smoke_pages_overlay` ★1.90 段 9 条（市值 = 收盘×股本 · 按市值比例分配 · 选市值档真重算 ·
三列对照在位 · 改权重当场显示变化 · 删除点名 · 差额自动进现金 · 变更史限长 · 调仓记录含手动变更）。
实测：`smoke_overlay` **10xx/0**（见提交记录）· `smoke_chart` **1076/0**。

**踩到的坑（→ §11.5-147）**：本轮编辑工具把源码里的**全角引号成批改成半角**（overlay 40 行 /
RULES 21 行 / PLAYBOOK 29 行 / HISTORY 9 行），直接把 `smoke_pages_overlay.py` 变成语法错误；
修法是"只还原与 HEAD 仅差引号形态的行"，并当场 `py_compile` 验证。

---

### ★1.90 第三批 · 净值区间 5 档 / 调仓记录控件化

> 同一版 **1.90** 的第二批（用户要求不拆版本号）。

**动因**：① 区间只有「近 3 月 / 近 1 年 / 成立以来」，用户要「今年以来」与「自组合建立」；
② 调仓记录是富文本一坨（用户："文字都挤着不好分辨"），并给了富途「最近调仓」截图；
③ 记录要**永久保存**（"除非删除组合，不要上限"）。

**改了什么**
1. 区间 **5 档**：近 3 月 / 近 1 年 / **今年以来**（当年 1 月 1 日起）/ 成立以来 / **自组合建立**（`created_at` 起）。
   五档都在区间内**重新定基 1.0000**；创建日早于本机数据起点 ⇒ 按数据起点画 + 卡头写明；
   区间内不足 2 个交易日 ⇒ 卡头写「画不出曲线」，**不悄悄退回全段**（那是欺骗）。
2. **调仓记录控件化**：新建 `ui/widgets/portfolio_changes.py`（`ChangeList` + `build_records`）——
   每条 = 日期行 + 逐笔行（左「增持 / 减持 / 新增 / 剔除」彩色标签、中间名称 / 代码两行、
   右「30.00% > 35.00%」+「变化 +5.00」）+ 现金变化备注；买 = 蓝、卖 = 橙；
   列表**限高 320 并滚动**，记录再多也不撑破右栏（§11.5-137：宁可滚动，不许看不见）。
3. **记录永久保存**：删掉 `MAX_CHANGES = 50` 的截断（`append_change` 与 `_normalize` 都不再切片），
   只有删组合才消失。
4. 体积控制：整形逻辑搬到 `build_records`，`ui/views/portfolio_view.py` 1405 行（仍越线，`_build`/`_render_p1` 待拆）。

**断言**：★1.90 段 7 条（五档齐全 · 今年以来 = 当年 1/1 · 自组合建立 = 创建日 · 创建日更早时的说明 ·
控件化逐笔字段齐全 · 空记录不造假行 · 80 条一条不丢）。

---

## ★1.91（待提交）· 行业覆盖率改为「按池补」（2026-10-28）

**动因**：组合页的行业环几乎全是「未分类」—— `industry_map.json` 只有 **302** 条（全市场 5169 只 ≈5.8%）。
根因不是接口坏，而是**取法不对**：旧版走「全市场分页」（每批 3 页 ≈300 只、**按代码升序**）
⇒ 一个 300 只的组合要十几轮才轮到它关心的票（§11.5-106 的老坑重现）。

**改了什么**
1. 新增 `ui/workers.IndustryPoolWorker`（按池）：走 `sync_service.fetch_enrich_map`（`ulist`，
   100 只/请求）⇒ 300 只组合 = **1~3 个请求**补满；全市场分页那条路留给 M2/M3（它们本来就要全市场）。
2. 组合页 `_on_sync_industry` 改用它；**报告口径 = 本组合 N/M 只**（不再只报"库内 N 条"）；
   东财没给的票**点名**，不瞎猜。
3. **诚实边界**：门面 `fetch_enrich_map` 会把网络错误**吞成 `{}`** ⇒ worker 把"一个都没回"
   翻译成「网络 / 频控 / 未登录」，**不许**说成"这几只没行业"（那是把网络问题说成数据问题）；
   未登录东财时先弹提示并给「去设置登录」出口（匿名档常被整段 RST）。
4. 测试卫生：`_maybe_fetch_industry` 的"分批"断言在**冷却期**会假红（且随整包变慢而时红时绿）
   ⇒ 断言前先 `em_throttle.reset()`。

**断言**：★1.91 段 3 条（按池拿到 2/3 且点名缺的 · 源全空 ⇒ 说网络 · 组合页不再翻全市场 + 报本组合覆盖率）。

**真机探针（本轮）**：`fetch_enrich_map(['600320','600326','600777'])` 实测 **RemoteDisconnected**
（匿名档被 RST）⇒ 代码路径正确，但**要先登录东财**才补得上；界面上已把这条出路说清。

---

## ★1.92 · 下载耗时三件 + 场内基金（ETF/LOF）方案（2026-10-29 提交）

**动因（用户原话）**："全 A 名册从零开始更新和补全更新所花的时间基本完全一致……到底是什么原因导致下载如此之慢。"

**分析结论（决定性公式）**：单只耗时 ≈ `max(interval, 单只延迟 / 并发 K)`。
· 并发**不提高请求率**（`RateGovernor` 把全局排槽钉在 1/interval），只把延迟藏进别人的等待；
· 所以"从零"与"补全"同是 N 个请求 ⇒ 时间同一量级；补全只有在**缺口刚好 1 个交易日**时才走
  `spot 秒补`（全市场约 52 个请求 ≈ 分钟级），隔 3 天就退回逐只。

**本轮实测（2026-10-29，用户机器）**：单只日线请求延迟 **2.4~3.6s**；运行中的下载实测
**0.79 个文件写入/秒**（≈ 全 A 至少 1 小时）；`RateGovernor` 的 interval 下限（0.3s × K=7 ≈ 2.3 只/秒）
并没有被吃满 ⇒ **瓶颈不只在 interval，还在"单只延迟 ÷ K"**。

**改了什么**
1. **A · ETA 说真话**（`data/sync_service.estimate_seconds`）：**不再除以并发 K**，= `N × interval`。
   旧式在 K=7 时把 34 分钟算成 5.7 分钟（弹窗"最多约 6 分钟"），是"预期落差"的直接来源。
   批量弹窗那句静态"约 50 分钟"同步改成按当前间隔解释（并说明并发不加总速度）。
2. **B · 死票不重试**（`data/akshare_feed` 新增**线程本地** `note_fetch_error/last_fetch_error`；
   `refresh_one` 据此判）：源**正常返回空**（退市/停牌/代码错）⇒ 只发 1 次，不再白等 1+2+4s；
   **真报错**（RST/TLS/超时）仍重试 4 次 —— 别把网络抖动当死票。
3. **F · 实测吞吐**（`ui/workers`）：每 100 只记一行 `[吞吐] … 实测 X 只/秒 · 按实测剩余约 Ys`，
   收尾再记一行（只/秒 + 当时的 interval/K），`stats` 带 `elapsed_s / per_sec`。

**断言**：图表段替换原"ETA 除以 K"断言（现断言 **K=1 与 K=7 结果相同**）；overlay 新增 ★1.92 段
6 条（不随 K 变 · 5000×0.4=2000s · 错误线程本地且读完即清 · 无数据只发 1 次 · 真报错仍 4 次 · 吞吐日志在位）。

**⚠ 环境干扰（§11.5-79 复犯）**：跑冒烟时用户的应用正在**全市场下载**（实测 6 秒改 6 个 parquet），
`scan_store.data_version` 每秒都在变 ⇒ 两条"缓存命中"断言必然红（与本次改动无关）。
关掉下载或跑完后复测即为 0。

**同批产出（文档，未实现）**：`docs/plans/active/ETF-LOF.md` —— 用户 2026-10-29 拍板"只做场内 ETF/LOF，
不做港股通、不做场外"。方案里最关键的一条新结论：**跳空可以本地补齐** —— 新浪 `fund_etf_dividend_sina`
给"日期 + 累计分红"（510300 实测 14 条 / 0.7s），配合不复权日线即可算**等比前复权**（不需要东财登录）；
三道可信度闸门（累计单调 / 首值≈首个 d / 表起点早于本地首日）任一不过 ⇒ 退回不复权并在卡面标注分界日，
**不猜**。另：ETF 名单 1714 只 + LOF 359 只（各 1 个请求）；`volume` 实测为"股"（close×volume≈amount，
禁 ×100）；货币 ETF 19 只默认排除（价格恒 ~100、收益靠份额折算）。

---

## ★1.93 · 架构与性能评估方案（文档轮 · 2026-10-29）

**动因**：用户 2026-10-29 要求"以资深架构师视角看架构 / 文档编排 / 启动速度 / 目录归类"。
本轮**只出方案、不改代码**，产出 `docs/plans/active/ARCH-PERF.md`。

**实测（本机，2026-10-29）**：启动 **4.05s** = Qt 0.04 + import 1.36 + 构造 **2.48** + 首绘 0.16；
导入硬成本 pandas 0.54 / akshare 0.41 / pyqtgraph 0.18。构造期 cProfile 热点：
`getsize` 1.69 · parquet 1.18 · `readiness._footer_last_date` 0.55（2,673 次）· `iterrows` 15,055 次 ·
`strptime` 26,391 次 · `portfolio_view.__init__` 0.47（含 `_save_ui` 写盘 0.37）。

**四个判断**：① 启动最大的浪费是**9 个页面全在 `__init__` 建好**（首屏只用 1 个）⇒ 惰性建页可省 1.5~2.0s；
② 测试形态是最大结构债（2 个脚本 **14,389 行 = 22%** 代码量、无 unit/CI）；③ 文档 740k 字符、RULES 97.8k 临界、
HISTORY 172k 名不副实、**根目录无 README**；④ 目录归类基本规范，仅 `models/`、`samples/` 像遗留物。

**P0 清单（下一轮做）**：惰性建页（`_PAGE_FACTORIES` + `page_*` property + 只读 `_PAGES`；已核实全仓 0 处下标路由、
132 处外部引用经 property 语义不变）· `roster_names` 向量化 · 日历批量转换 · footer LRU(mtime+size) ·
新增 `scripts/probe_startup.py` 当同一把尺子。验收一律用**行为断言**（已建页面集合 / stat 调用数 / 逐位一致），
不用墙钟（会 flaky）。

---

## ★1.94 · 文档分层重构 + 开源准备（2026-11-02 提交）

**动因**：作者提出"文档过于臃肿、已完成计划书还当活文档，agent 不知道读什么"，并要求根目录尽量少放文件。

**四块改动（零业务代码）**

1. **开源准备**：`LICENSE` = GPLv3 全文（35,147 字符，取自本机 PyQt6 附带文本逐字复制）；真实交割单 xlsx 与公式 txt
   **移出仓库**（→ `~/.jian_data/samples/`）。历史核对：仓库只提交过 `samples/README.md`，**真实数据从未入库**
   ⇒ 无需重写历史。`.gitignore` 从"按扩展名忽略"改成 `samples/*` + `!samples/README.md`
   （旧 README 声称的规则其实不存在 —— 典型"文档与实况漂移"）。
2. **依赖合并**：`requirements.txt`（区间）+ `requirements.lock.txt`（精确）→ **一份精确锁定 35 项**
   （7 直接 + 28 传递），删掉 lock；`SETUP` 改写为"一份文件"口径。
3. **文档分层**：根目录 **7 → 6 个文件**（`.gitignore / LICENSE / README.md / main.py / requirements.txt / version.json`）。
   新增 `README.md`（产品页，GitHub 首页）+ `docs/AGENTS.md`（开发者/AI 入口，**不占根目录**）+ `docs/STATUS.md`
   （唯一状态源）；`JIAN_RULES.md` → `docs/RULES.md`（全仓 **76 处**引用）；7 份方案书分
   `plans/active`(2) / `plans/done`(5) 并补 `status:` 头；HISTORY/PLAYBOOK/ARCHIVE 切 **4 / 5 / 5 卷** + 索引
   （changelog 在 v6.54 断行、**114 行数据一行不少**；PLAYBOOK **72 条编号一条不丢**）；
   `CODEMAP` / `SETUP` → `reference/`。
4. **契约工具**：`scripts/check_docs.py`（front-matter / 计划登记 / 链接 / RULES 体积 / 模块清单，5 项）；
   `scripts/gen_codemap.py`（自动生成 `MODULE_INDEX.md`，191 个 .py）。RULES **98.8k → 89.8k**
   （19 条正文压成索引，规则：只压"全文确在 playbook 且更长"的条目）。

**顺手修掉的既有债**：`samples/README.md` 谎称 `samples/*` 已被忽略；RULES 里 6 处过期数字
（APP 版本 1.89 / 主线仍写 B15 / 行数 1350 / "待决 1.90 提交"…）随本次重写归位；
`§11.5-106` 确认**无正文**（记入 `docs/STATUS.md` §5 已知债）。

---

## ★1.95 · 发布前硬化：异常兜底 + README 门面 + 截图（2026-11-02 提交）

**动因**：作者要在 **1.100 之前结束 1.0 大版本**，要求先做一次"能不能真拿出去给人用"的彻查。

**查出的真问题（实测）**

| 项 | 结论 |
|---|---|
| **未捕获异常 = 闪退** | 离屏对照实验：槽里 `raise ValueError`，**不装** `excepthook` ⇒ 进程 **fastfail（RC 0xC0000409）**，日志无栈；**装了** ⇒ 事件循环继续（`app.exec()` 返回 0）。而 `main.py` 当时**没装**。⇒ 任何 UI 漏网异常都会让用户看到"软件自己关了"。 |
| **公开仓库无门面** | GitHub API 实测 `private:false` 但 `README on main: 404`、`license: null`、`releases:0` —— README/LICENSE 都在未推送的 1.94 里。 |
| 首次运行 | 全新用户目录实测：**3.65s** 开窗、5 个文件、**9 个页面逐一切换 0 失败**、无阻塞联网。 |
| 隐私 | 家目录/邮箱/手机/长数字 **0 命中**；历史 331 个文件 **0** 个 xlsx/db/png；`samples/` 只提交过 README。 |
| 依赖 | 35 项锁定版本在 PyPI 全部存在；代码里 9 个第三方顶层包全部已声明。 |
| 其它 | 15 处 `except: pass` 逐个看过，均不在数据丢失路径；`SingleSyncWorker.run` 是 18 个 worker 中唯一无 try（低风险）。 |

**改了什么**

1. `main.py` 新增 `_install_excepthook()`（`QApplication` 建好后立即装）：异常写日志（含完整栈）+ 弹一次可关闭提示
   （3 秒内连环异常只弹一次，离屏环境只记日志），并挂 `threading.excepthook`。
2. 两份冒烟脚本装同款 `_fastfail_guard`：打印栈 + **记一条失败** + 继续跑 ⇒ 那个"固定点硬崩"变成可见失败。
3. README 门面：徽章 · **离屏渲染截图**（`docs/assets/market.png` / `portfolio.png`，用**合成组合 + 公开 K 线**，
   `WA_DontShowOnScreen` + 真实字体引擎，避免 offscreen 插件的中文豆腐块）· 系统要求统一为
   **Windows 10/11 + Python 3.12+**（旧 README 写 3.10+ 与 SETUP 不一致）· 项目状态与 Issues 入口 · `Copyright (C) 2026 ENDVEN`。

**验证**：`smoke_chart` **1076/0** · `smoke_pages_overlay` **1236/0**（装 guard 后仍全绿）。

---

## ★2.0 · 1.0 收官 + P1 清理（2026-11-02 提交）

**背景**：作者在 1.100 之前决定**结束 1.0 大版本**，把后续都算作"优化与提升"，并从 **2.0** 重新起版本号。

**本版四件（无业务逻辑改动）**

1. `SingleSyncWorker.run` 补 try —— 18 个 QThread 里**唯一没有兜底**的一个。失败时发**同形状**回包
   （`ok=False, reason="error", message=...`），调用方按普通失败提示，不会再出现"整程序消失"。
2. **启动占位**（`main.py::_make_splash`）：冷启动构造期 1.7s 内不再白屏；只显示"正在加载页面与数据…"，
   **不编进度条**；窗口 `show()` 后 `splash.finish(window)`；创建失败只记一条日志、绝不拦启动。
3. 删除 `docs/assets/overview.png`（空界面，README 只放好看的两张）。
4. **CI**：`.github/workflows/ci.yml` 只跑**零依赖、确定性**的三步 —— 全仓 `compileall` ·
   `scripts/gen_codemap.py --check` · `scripts/check_docs.py`。**不跑两份冒烟**（空数据机器有 8 条已知环境性失败，
   会把红绿变成环境问题）；冒烟仍是发布前的本地必跑项。

---

## ★2.01 · 测试基建问题立项（纯文档，2026-11-02）

**触发**：2.0 发布时 overlay 连续两次 `0xC0000409`，第三次通过后进程又**不退出**（见 §11.5-150）。

**如实记录（关键：根因未确认）**

| 现象 | 证据 |
|---|---|
| fastfail | RC `-1073740791`；三次运行 崩/崩/通过；两次都停在同一行数 |
| 不是断言红 | 无失败行输出，进程直接消失 |
| 不是 Python 异常 | 1.95 起装有 `_fastfail_guard`；且 QThread 探针证明 hook 能兜住两类异常 ⇒ 本次是 C++ 层 abort |
| 不是"崩点=最后一行" | stdout 重定向是块缓冲，最后一行可能只是缓冲区边界 |
| 跑完不退出 | 打印 `1236/0` 后 CPU 83s、占住输出文件；`taskkill` 报"无实例"、`Stop-Process` 无效，`.NET Kill` 有效 |

**产出**：`docs/plans/active/TEST-HARNESS.md`（S1–S6 排查步骤 + 验收：连跑 10 次 0 崩 0 挂死）、
`docs/playbook/process.md` §11.5-150、`docs/playbook/INDEX.md` 一行、`docs/STATUS.md` §5 债。

---

## ★2.02 · 测试基建：fastfail 根因修复（2026-11-03 提交）

**结论**：`0xC0000409` 不是断言问题，也不是 Python 异常，而是**运行中的 QThread 被 GC**。

**根因**：`ReadinessFlow.start()` 每次直接覆盖 `self._probe`；上一轮 `ReadinessWorker`
还在跑时，最后一个 Python 引用在赋值瞬间归零 ⇒ sip 析构 C++ QThread ⇒
"QThread: Destroyed while thread is still running" ⇒ 进程 fastfail（无栈）。
`ReadinessWorker` 没有 parent，唯一引用就是 `self._probe`；是否踩中取决于上一轮是否刚好收尾。

**排查（S1–S6）**：
1. 冒烟输出改行缓冲（`line_buffering + write_through`）⇒ 推翻旧"固定 657 行"结论（块缓冲假象）；
2. `faulthandler` + 全局 15 分钟超时；可疑段用写 fd 2 的 trace 二分；
3. 定位链：`_on_rerun` → `apply_config` → `resolve_scope` → `readiness.start` → 覆盖 `_probe`；
4. 修法：旧线程先 `cancel()`（不 join），`_probes` 列表在收尾前一直持有引用；
5. 退出路径加存活线程清单 + 30s watchdog（卡住 ⇒ `RC=4` + 全线程栈）；
6. 连跑 **10/10** 通过（`1239/0`，最长 49.1s）。

**顺带修**：`ScanFlow._on_enrich_rows` 在迟到补全回包里读 `_outcome.result` 会
`AttributeError`（新扫描已清空 `_outcome`）⇒ 逐层 `getattr`，拿不到就留空。

**已知噪音**：Windows 上 pyqtgraph + `os._exit()` 的 DLL 卸载期 access violation
（退出码仍 0；只建 `pg.PlotWidget` 即可复现），正常收尾前关掉 `faulthandler` 静音。

**未收口**："打印完汇总不退出"修复后 10 次未复现，按"未复现"记录，不写成已修。

**产出**：`ui/widgets/readiness_flow.py`、`ui/widgets/scan_flow.py`、
`tests/smoke_{chart,pages_overlay}.py`（S1/S2/S5 + 3 条新断言）、
`docs/plans/active/TEST-HARNESS.md`、`docs/playbook/process.md` §11.5-150。


## ★2.03 · 启动优化 P0（2026-11-03 提交）

**目标**：ARCH-PERF P0 四件 —— 启动 4.05s → ≤2.2s，**不改 UI 行为**。

**改了什么**
1. **惰性建页**（`ui/main_window.py`）：`_PAGE_FACTORIES` + `page_*` property + 只读 `_PageMap`；
   构造期只建首屏 `overview`，其余页首次访问/切换才建。子页签信号在**建页时**接线，
   数据页建好后**立刻** `render_all_data()`（切过去不能是空白）。
2. **roster 向量化**（`core/engine.py`）：去 `iterrows`，一次 `astype('string').str.strip()` + `zip`。
3. **日历批量**（`data/trade_calendar.py`）：`to_dates()` 一次 `pd.to_datetime` + 内存缓存按
   `(mtime_ns,size)` 失效；逐位对比 200 个日期一致。
4. **footer LRU**（`data/readiness.py`）：`_footer_cached()` 键 `(path,size,mtime_ns)`、LRU 4096；
   同文件二次 **0 次**重开 parquet，补下载 mtime 变则自动失效。
5. **探针**（`scripts/probe_startup.py`）：import / construct / paint 三段 + 已建页面数。
6. **连带修复**：`PortfolioView._watchlist()` 不再 `getattr(main_win,"page_market")`（会把行情页
   建出来）⇒ 走 `page_if_built()` + `WatchlistStore` 兜底；`render_all_data()` 只刷已建页；
   两条 `currentIndex()==3/4` 断言改成按控件身份。
7. **冒烟退出**：2.02 的"跑完不退出"在后台复现（2 个 `ScanWorker` 存活 ⇒ `os._exit` 卡
   `ExitProcess` + 主线程持 GIL）⇒ 改 `TerminateProcess` 硬退出（只用于测试脚本）。

**断言**：`smoke_chart` **1080/0**（+4）· `smoke_pages_overlay` **1244/0**（+5）。

**实测（同一把尺子）**：构造 **3.6s → 0.27s**；已建页面 **9 → 1**；
真机探针总耗时 **2.145s**（import 1.31 + 构造 0.27 + 首绘 0.49），目标 ≤2.2s 达标。

**产出**：`ui/main_window.py` · `ui/views/portfolio_view.py` · `core/engine.py` ·
`data/{trade_calendar,readiness}.py` · `scripts/probe_startup.py` · 两份冒烟 ·
`docs/plans/active/ARCH-PERF.md` · `docs/playbook/ui.md` §11.5-151。

## ★2.04 · 测试提速 + 工程拆件（2026-11-04 提交）

**目标**：把日常测试等待压下来，并在不改行为的前提下拆大文件。

**改了什么**
1. **unit 层**：新增 `tests/unit` 41 条（日期批量 / roster / footer LRU / 缓存键与数据版本 /
   批量文案 / 组合统计 / merge_tail / 指标 / 风险与格式化），秒级反馈；不依赖 Qt / 不读数据湖。
2. **并行 runner**：`tests/run_smoke.py` 同时跑 chart + overlay，流式日志、慢段 Top5、
   单份超时强杀；锁按脚本分开。
3. **CI**：新增 `unit` job（最小依赖 pandas/numpy/pyarrow/akshare，不读数据湖、不联网）；
   冒烟仍本地跑。
4. **workers 拆件**：`ui/workers.py` 1081 → **58 行门面** + `workers_scan` / `workers_download` /
   `workers_sync` / `workers_backtest` / `workers_imports` / `workers_core` / `workers_throttle`；
   旧导入路径不变。
5. **其他大文件**：`history_parts.py`（运行历史小件）· `fetch_messages.py`（失败文案）·
   `backtest_preview.py`（回放）· `scan_enrich_flow.py`（补全调度）· `scan_filters.py`（阈值/帧准备）。

**验证**：unit **41/0** · chart **1080/0** · overlay **1244/0**；并行 **56–100s**（逐个相加 89–150s）。

## ★2.05 · 数据底层 P1：日更批量快照（2026-11-05 提交）

**目标**：把全市场日更从“5000 次单只历史请求（约 80 分钟）”改为“批量快照 + 本地合并”。

**改了什么**
1. **benchmark**：新增 `scripts/bench_data.py`，实测 provider/并发与存储三布局；
   存储最终选 **A 混合**（历史按 symbol + 每日快照）。
2. **日快照**：`data/daily_store.py` 原子写/读 + `merge_row`；快照先落盘，再逐只合并。
3. **批量入口**：`em_market.fetch_market_quotes`（clist 56 页）+ `MarketSyncService.fetch_market_snapshot`。
4. **DailySnapshotWorker**：>=3000 只走 clist，500–2999 走 ulist；16 路本地合并；
   缺口/除权/缺昨收退回单只 `refresh_one`，不抄错价。
5. **回滚**：`JIAN_BULK_DAILY=0` 回退旧 `SyncWorker`；<500 只仍走旧路径。

**实测（临时目录，不写用户库）**：全市场 fetch **50.8s** + 合并 **66.3s** = **117.1s**；
5220 只写入，343 只停牌/无正价归 skipped/missing；100 只新旧路径
`date/open/high/low/close/volume/amount` 逐位一致。

**尚未完成**：首次打开/后台补全队列、`MarketDataStore` 统一读门面、登录档 provider 实测。

## ★2.06 · 数据底层 P1 收尾（2026-11-05 提交）

**目标**：首次打开可用、后台补历史、覆盖率可见、读取有统一门面。

**改了什么**
1. **启动检查**：`StartupCheckWorker` 只读 footer + 交易日历；空库/只缺一天 → 日快照，
   缺口更大 → 低优先级 backfill；`JIAN_AUTO_DAILY=0` 关闭。
2. **自动补全**：日快照完成后的 `symbols_empty` 自动投 backfill；普通下载优先。
3. **覆盖率**：数据管理页用 `ReadinessWorker` 显示就绪/历史不足/未下载。
4. **统一读门面**：`data/market_store.py`；`MarketSyncService.status()` 已接，
   快照未合并时也能读到最后一天。
5. **回滚**：`JIAN_AUTO_DAILY` / `JIAN_AUTO_BACKFILL` / `JIAN_BULK_DAILY`。

**实测**：全市场日更 117s；100 只 parity；unit 59/0；chart 1080/0；overlay 1244/0。

## ★2.07 · 数据底层 P2：双通道 + 备源 + 一次性 bootstrap（2026-11-05 提交）

**目标**：把匿名/登录差异、候选源和登录档边界变成可实测、可回退的生产能力。

**改了什么**
1. **能力表**：`data/provider_caps.py`；设置页账号组显示“当前档位能做什么”，
   匿名状态明确提示“东财单只历史受限（快照/新浪历史仍可用）”。
2. **provider registry**：Eastmoney / Sina / Tencent / NetEase / Baostock 的
   数据集、认证、批量能力与实测状态；腾讯 limited、网易 unavailable、Baostock 未安装。
3. **备源**：
   - 新浪批量报价 100 只/批（快照备源）；
   - 腾讯近年历史 640 根（Sina 失败后；volume 手→股）；
   - 全市场快照失败时按花名册回退新浪。
4. **东财登录直连**：`data/em_history.py` 带 Cookie 走 `push2his`；
   实测 100 只 2010 起全历史 **7.06s / 0 错误**；日常只接近年/增量。
5. **一次性 bootstrap**：`data/bootstrap_once.py` + `scripts/bootstrap_history.py`；
   显式 arm、跑一次 consume、请求不占日常 300/日预算。
   2026-11-05 实跑 4955 只：统计到 **4605 成功 / 343.8s**，失败主要是 `920xxx` 北交所
   （东财直连不支持；本地原完整文件未覆盖），预算仍 **96/300**。

**验证**：unit **78/0** · chart **1080/0** · overlay **1244/0**；check_docs / codemap 全 OK。

## ★2.08 · Bootstrap 复权污染修复（2026-11-05 提交）

**现象**：P2 后 M3 广度统计图与之前不同。

**根因**：不是广度算法；`bootstrap_history --overwrite` 用东财加法前复权覆盖了
4605 个新浪比例前复权历史文件。抽样 `000001` 日收益率差异最高 32%；
228 个文件出现负收盘价（`600519` 2010 年 -188.89）。

**修复**：
1. 228 个负价文件先用新浪重拉（93.2s，0 失败）；
2. 全部非北交所文件再按新浪重拉（后台完成）；验收 **5172 文件 / 0 非正收盘价**，
   抽样 `000001/600519/600000` 与新浪逐值一致；
3. 新增 `data/quality.py` OHLC 闸门；`em_history` 拒收负价/重复日期；
4. `bootstrap_history` 默认 `--source sina`；`JIAN_EM_DIRECT` / `JIAN_TENCENT_HISTORY`
   默认关闭，避免不同复权口径再次拼入新浪历史；
5. 新增 `scripts/repair_history.py`，可 `--dry-run` / 坏文件 / `--all`。

**注意**：旧的广度结果/缓存仍是污染数据算出的，需重跑一次扫描。

## ★2.09 · 日更覆盖 + 新股入库（2026-11-05 提交）

- 补北交所 349 只、快照名单外新股 408 只（另 213 只有旧文件）、滞后标的 213 只；
  花名册 4955 → 5577，日线 5580 文件、0 非正收盘价。
- 全市场日更从快照增量发现新股并入花名册；北交所走新浪后置；
  `sina/tencent` 北交所前缀修为 `bj`。
- 残留：`689009`（CDR）/`301139` 源无历史，保留不伪造。
- unit 84/0；chart 受本机预算/代理态影响未作为通过依据。
