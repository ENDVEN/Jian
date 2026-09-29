# Jian — 大扫除台账（§7-B14）

> 状态：**第一轮已执行完毕（`1.59` · 2026-09-29 · 用户拍板"全部同意"）**；量于同日。
> 本文件是 §7-B14 的唯一台账：触发判据实测 → 盘点清单 → 分批施工方案 → 每批执行记录
> （删了什么 / 凭什么能删 / 证据）。
> 纪律（照 `JIAN_RULES.md` §7-B14）：**先量后动 · 人审后才删 · 纯删除不顺手改行为 ·
> 每批只做 1 个主题 · 每批两份冒烟全绿（`smoke_chart` / `smoke_pages_overlay`）才进下一批**。
> 状态图例：`[x]` 已执行 · `[~]` 进行中 · `[ ]` 待拍板/未开始。

---

## 一、触发判据实测（2026-09-29 现测）

| # | 判据（JIAN_RULES §7-B14） | 门槛 | 实测 | 结论 |
|---|---|---|---|---|
| ① | 红榜（≥400 非空行）文件数 | ≥ 8 | **30** 个业务文件（1.59 重测；`custom_widgets` 1072→759） | **触发** |
| ② | 再导出/兼容壳（`# noqa: F401`） | ≥ 10 | **16** 处（明细见 §三-B2） | **触发** |
| ③ | 两套编辑面 / 双真源设置项 | ≥ 3 | 1 处（`download_settings` 无入口壳；S2-2 收口已预防其余） | 未触发 |
| ④ | 文档与实况漂移 | ≥ 5 | **≥ 7** 处（明细见 §五） | **触发** |

⇒ 判据①②④三条达标，**§7-B14 正式启动**；③未达标但存量 1 处一并清。

---

## 二、清单 A：垃圾与临时物（纯删除，零行为改动）

| 项 | 证据（凭什么能删） | 建议 | 状态 |
|---|---|---|---|
| 根目录 `_tmp_real_probe2.py` | 自带 docstring「跑完即删」；§10-13「临时产物不留仓」；git 未跟踪（`_tmp_*` 兜底） | 删 | [x] 已删 |
| 根目录 `screenshots/1.23-steps5-6/`（7 张离屏核验截图） | §9-C 早有记载「要么删要么登记」至今未决；正式截图目录永远是 `~/.jian_data/screenshots`；git 未跟踪 | 删 | [x] 已删 |
| **版本三处漂移**：commit 首词已到 `1.58`（**已推**，origin/main=17f535a），但 `APP_VERSION`/`version.json` 仍 `1.57` | git log vs `config/settings.py:170` vs `version.json` | 已推送不可 amend（§11.5-105）⇒ **`1.59` 提交顺推三处同批同步** | [x] 已修 |

---

## 三、清单 B：兼容壳与再导出

### B1 无入口兼容壳（1 个）

`ui/dialogs/download_settings.py` —— S2-2 已把它的三个入口全删（用户 2026-09-27 拍板「少一个按钮 = 少一处漂移面」），文档明写「待 §7-B14 删」。

- **谁在用**：生产代码 **0 处 import**（仅 3 处注释提及历史）；但冒烟脚本 4 处源码级断言读它
  （`smoke_chart.py:4720`；`smoke_pages_overlay.py:4193 / 4245 / 5559`）。
- **删了谁会红**：上述 4 处断言 ⇒ 删除必须**同批改冒烟**（断言对象换成真实编辑面 `download_queue_panel` / 设置页）。
- 已执行（`1.59`）：文件已删；§10-9 宽度断言改验**设置页渲染件**（`SettingsView.control_of`）；S2-2 段换"文件已删 + 全 ui/ 无残留"负向断言；smoke_chart"写盘键形"改钉注册表落点；3 处历史注释更新。 | 状态 [x] 已执行

### B2 再导出壳 16 处（`# noqa: F401`）分类

**处置原则**：区分「**过渡壳**」（拆件时期的零改动兼容层，调用方改 import 即可删）与「**门面/防环再导出**」（有明确架构理由，**保留**，不算债）。逐壳四问在执行批内做 AST 精算，下表引用数为 2026-09-29 的 grep 粗计。

| 壳（再导出方） | 被再导出 | 引用粗计 | 初步分类 | 状态 |
|---|---|---|---|---|
| `data/data_feed.py` ×4（feed_cells/fifo/months/report） | 解析子件符号 | 本体 3 处 import + 18 处经 `data.data_feed` 取符号 | **门面再导出**（data_feed 是解析链唯一门面，§11.2）——保留 | [x] 保留 |
| `data/sync_service.py:44`（`looks_like_proxy_error`） | `data.net_env` | net_env 全仓 1 处 import | **防环再导出**（v6.72 明写「⇒ 无 import 环」）——保留 | [x] 保留 |
| `ui/download_hub.py:45` | `ui.download_jobs`（DownloadJob/SingleSyncGate/hub_of） | download_hub 共 12 处 import | **过渡壳** —— 已撤：4 个生产调用方 + 冒烟 3 处改直连 `ui.download_jobs`，hub 只留自用 8 名（无 noqa） | [x] 已撤 |
| `ui/views/trading_desk.py` ×3（desk_data/desk_layers/desk_panel 常量） | 三个 desk_* 件的常量 | 4 / 2 / 3 处 import | **过渡壳** —— AST 矩阵核销：3 名纯死（无内部无外部消费）直接摘名；`PANEL_DEFAULT_WIDTH` 真自用保留；冒烟 1 处 import 改直连 `desk_panel` | [x] 已撤 |
| `ui/views/review.py:38`（`MAX_ANCHOR_GAP_DAYS`） | `review_playback` | 2 处 import | **过渡壳** —— 纯死名（无内部无外部消费）已摘；`PLAYBACK_CONTEXT_DAYS` 真自用保留 | [x] 已撤 |
| `ui/widgets/annotation_shapes.py:40` | `annotation_layouts`（DrawCtx/PlaceCtx） | 1 处 import | **活命名空间**（全部名规格表自用 + `annotation_layer` 以 `shapes.DrawCtx/PlaceCtx` 引用）—— 保留，摘无谓 noqa | [x] 保留 |
| `ui/widgets/annotation_layer.py:44` | `annotation_items`（FIB_*） | 4 处 import | **过渡壳** —— `FIB_COLORS`/`FIB_LEVEL_WIDTH` 纯死名已摘；其余 7 名真自用保留（摘 noqa）；smoke `_ClickableText` import 改指 `annotation_items` | [x] 已撤 |
| `ui/widgets/backtest_panes.py` ×3 | `custom_widgets`（QSS 常量/工厂） | custom_widgets 全仓 41 处 import | **AST 核销：9 名全部真自用** ⇒ 摘 noqa、不再算再导出；`backtest.py` 的 `hint_icon`/`mini_label` 改直连 custom_widgets | [x] 已处置 |
| `ui/widgets/review_layout.py:28`（`attach_date_axis`） | `adaptive_axis` | adaptive_axis 全仓 9 处 import | **预留接线**（1 行，有明确用途注释）—— 保留 | [x] 保留 |

---

## 四、清单 C：红榜瘦身（30 个越线文件 —— **只执行文档已承诺的拆法，其余登记不返工**）

> §7-B14「不做」条款：**不为好看重构能跑的模块**。下表只把 §4 里**当年写明「再长就把 X 拆 Y」**的
> 承诺收进来；无既定拆法的越线文件本轮一律不动，只复核行数（§五）。

| 文件 | 实测行数 | 文档既定拆法（出处 §4） | 优先级 | 状态 |
|---|---|---|---|---|
| `ui/widgets/custom_widgets.py` | 1072→**759** | 拆 `ui/widgets/styles.py`（**356 非空**，<400 不标数）——样式族九块逐字节搬移，本体 `import X as X` 同名再导出（零 noqa） | **P0** | [x] 已执行（批3） |
| `ui/views/backtest.py` | 955 | 搬「预览回放态」→ `ui/widgets/backtest_preview.py` | P2 | [ ] |
| `data/sync_service.py` | 834 | 抽「失败分类与人话文案」→ `data/fetch_messages.py` | P2 | [ ] |
| `ui/widgets/scan_flow.py` | 828 | 拆「范围解析 / 补全调度 / 回执文案」三件（补全调度已有 `scan_enrich.py`，继续外搬） | P2 | [ ] |
| `ui/widgets/backtest_history_ui.py` | 815 | 拆 `ScanStatBar` / `SectionCard` / `MiniEquityChart` → `history_parts.py` | P2 | [ ] |
| `core/cross_section.py` | 689 | 按 `scan_filters` / `scan_io` 拆 | P2 | [ ] |
| `ui/workers.py` | 688 | 按 worker 类拆 `ui/workers_download.py` | P2 | [ ] |
| 其余 23 个越线文件 | 418–617 | 无既定拆法 ⇒ **登记不返工**（B15 动到谁再顺手按 §10-12 落新件） | — | [x] 已登记 |

---

## 五、清单 D：文档漂移（判据④证据，修复在收尾批）

| # | 漂移 | 实况 | 状态 |
|---|---|---|---|
| 1 | 快照「push 状态」行过期 | 文档写「1.54–1.57 四条待推」；实测 **origin/main 已 = 1.58（17f535a）** | [x] 已回写 |
| 2 | 版本三处不同步 | commit 首词 `1.58`（已推）vs `APP_VERSION`/`version.json` = `1.57` | [x] 已随 1.59 归一 |
| 3 | §4 红榜行数过期 ≥6 处 | 例：`settings_registry` 312→**507**（+195）、`workers` 626→688、`backtest.py` 941→954、`scan_flow` 816→828、`download_hub`「退榜 378」→实际 **430 重回榜**、`sync_service` 828→834 | [x] 已全量重测回写（16 处） |
| 4 | 主文件字符数预警 | §10-14 硬指标 <100k；宣称 ≈73k，实测 **94,083**（1.59 收工复测见 §七） | [x] 已量已记 |
| 5 | 「最近三版」未含 1.58 | 顶部仍停 1.55–1.57；1.58（设计稿+可行性分析）未进 §8 表 | [x] 已更新 |
| 6 | 本文件（JIAN_CLEANUP.md）未登记 | §4 目录地图 / 文档地图需补一行 | [x] |

---

## 六、分批施工方案（待人审；每批一个主题、每批两份冒烟全绿）

| 批 | 主题 | 内容 | 验收 | 状态 |
|---|---|---|---|---|
| **0** | 垃圾清理 + 版本号 | 删 `_tmp_real_probe2.py`；根 `screenshots/` 处置（拍板）；版本漂移修复方案拍板（下次提交顺推 1.59） | `git status` 干净；两份冒烟不受影响 | [x] 已执行 |
| **1** | 无入口壳退场 | 删 `download_settings.py` + 迁移 4 处冒烟断言 + 清 3 处历史注释 | 两份冒烟全绿；全仓 grep 仅剩历史叙事与负向断言 | [x] 已执行 |
| **2** | 过渡壳逐个处置 | §三-B2「过渡壳」逐壳：调用方改 import → 删再导出行 → 改受影响断言（**门面/防环类保留**） | 两份冒烟全绿；`noqa: F401` 计数 16→**6**（仅门面/防环/预留） | [x] 已执行 |
| **3** | custom_widgets 拆 styles | 拆 `ui/widgets/styles.py`（结构搬家、**观感零变化**，照 v6.71 §9-F③ 范式），本体 re-export | 两份冒烟全绿 + 九块逐字节搬移 + 冒烟值断言全等 | [x] 已执行 |
| **4** | 文档对齐收尾 | §五全部 6 项回写（快照断点 / 版本 / §4 行数重测 / 字符数 / 最近三版 / 本文件登记） | `JIAN_RULES.md` 与实况逐条对上；字符数 <100k | [x] 已执行 |
| 之后 | 主线回归 | 回归 **§7-B15 参数稳健性研究 MVP**（设计已定案 v3，`docs/JIAN_SWEEP_PLAN.md`，约 1–2 轮） | — | [ ] |

**顺序理由**：批 0/1/2 是纯删除、风险最低且直接响应立项动机（「改一处要读三处」）；批 3 是文档已承诺、且 B15 新控件依赖样式公共件；批 4 收尾防漂移。红榜 P2 拆法不在本轮排期（登记不返工），B15 动到谁再说。

## 七、执行记录（1.59 · 2026-09-29）

| 批 | 结果 | 证据 |
|---|---|---|
| 0 | ✅ | `_tmp_real_probe2.py` / 根 `screenshots/` 已删；`git status` 只剩本轮有意改动 |
| 1 | ✅ | `download_settings.py` 已 `git rm`；§10-9/S2-2/smoke_chart 三段断言重写并全绿；新增 `SettingsView.control_of()`（+`_controls` 随 reload 清空） |
| 2 | ✅ | `noqa: F401` 16→6；生产改 6 文件（download_bar/download_queue_panel/desk_data/backtest_flow/breadth_flow/readiness_flow）+ trading_desk/review/annotation_layer/backtest_panes/backtest.py；冒烟改 3 处 import + `_dj19` 别名 |
| 3 | ✅ | `ui/widgets/styles.py` 新建（356 非空）；`custom_widgets` 1288→928 总行（1072→759 非空）；身份断言 `cw.X is st.X` 全等；§10-15/§9-F③ 断言改指 styles + 2 条新护栏 |
| 4 | ✅ | JIAN_RULES（快照 5 行 / §4 十六处 / §10-9、§10-15、§11.4、§11.6 新块、§11.7 断言数 854→859）/ CODEMAP / HISTORY v6.76 行 / version.json+APP_VERSION=1.59 |
| 验收 | ✅ | `smoke_chart` **890/0**；`smoke_pages_overlay` **858/1**（唯一失败 = 提交前版本号自愈项，提交后全绿）；overlay fastfail 连崩 3 次 ⇒ HEAD worktree 基线同点同频崩（595 OK 处）⇒ **存量问题**（§11.5-102）；JIAN_RULES 收工实测 **95,912** 字符（<100k，逼近红线——下批开工前先量） |
