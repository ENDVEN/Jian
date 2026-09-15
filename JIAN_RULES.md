# Jian — 开发规范与上下文记忆 (文档 v6.19)

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
> v5.8：**§7-A3 数据管理页落地 + §9-H 架构债清账** —— 数据湖补删除/清点原语；
> 同步逻辑收敛到 `data/sync_service.py`（增量合并 + 温柔抓取 ThrottlePolicy 防封 IP）；
> UI 线程统一到 `ui/workers.py`；第 6 导航页「🗄 数据管理」+ 批量预下载弹窗。
> APP 版本升 **v1.4.1**（`config/settings.py` 与 `version.json` 已同步）。
> v5.9：**对 v5.8 的独立复查（第二双眼睛）** —— 因会话中更换过语言模型，把上一批改动
> 当作陌生代码重新审查，发现并修复 4 个隐患（见 §9-M）：①增量"时效滞后一天" ②休市空增量
> 误判失败+白重试 ③数据起点 2010→2016 的静默缩水回归 ④扫描线程/关窗线程的竞态与崩溃风险。
> 全部以冒烟测试断言固化后回写本文件。
> v5.10：**数据管理页 UX 加固（用户实测反馈驱动）** —— 修"勾选框点击后直接消失"
> （根因：勾选列 ResizeToContents 算出≈0 宽，指示器不可见/点不中）+ 过滤下单元格行错位；
> 「清空分区」从主操作行**隔离**到左侧栏底部并要求键入「清空」二次确认；按钮/文案改用户语言
> （"增量更新"→「更新到最新」、"强制全量重拉"→「重新全量下载」）；
> 同步失败**按原因分类提示**，退市股（无数据源）不再被误报为"代码不存在/网络抖动"。
> 详见 §9-N；新增 §10-10 按钮层级与文案铁律。
> v5.11：**勾选框最终重设计** —— v5.10 用"原生 indicator + cellClicked"出现**双重触发**：
> Qt 对 indicator 自动切换一次、cellClicked 又切一次 → 点一次净效果=没点（永远打不出勾），
> 且 `ItemIsSelectable`+`SelectRows` 带来蓝色行高亮。最终方案：**彻底放弃 Qt 原生 checkbox**，
> 第 0 列自绘 ☐/☑ 字符 + 整格点击=唯一切换入口 + `NoSelection`（消除行高亮）。
> 已用 QTest **真实鼠标事件**验证单点/连点/取消均稳定（§9-N1 修订）。
> v5.12：**第二次全仓通读核对（模型切换后的"陌生代码"复查）**。本次**未改任何业务代码**，
> 只做"文档 ↔ 磁盘"的逐项对账，产出 §9-O 系列 10 项发现：
> ① 口径漂移：流水/复盘的「仅盈利/仅亏损」过滤器仍用毛利（O-1）；
> ② 架构债残留：`ui/workers.py` 只收口了"行情同步类"线程，回测/成分股/导入/版本检测
>   4 个 QThread 仍散落在各自文件（O-2）；③ `sync_service` 的 docstring 把数据起点写成
>   2016，与实际的 2010 冲突，是 §9-M3 的**回归隐患**（O-3）；
> ④ 行情页「☁️ 云端同步」恒为全量重拉、与管理页双按钮体验不一致（O-4）；
> ⑤ 回测页同步结果缺竞态守卫（O-5）；⑥ §4 目录树行数/版本号全面过时（O-6）；
> ⑦ 图表样式重复从 2 处变成 3 处（O-7）；⑧ §9-J 小坑确认仍在 + 一处文档描述有误（O-8）；
> ⑨ Dashboard KPI 实为 17 项非 18 项（O-9）；⑩ 复盘页回放 K 线反复全量读 Parquet（O-10）。
> **本节最底部的 §11.6 已据此刷新"下一步推荐顺序"。**
> v5.13：**第一 / 第二梯队全部落地**（用户已批准"筛选改净额"，并明确云端同步语义
> = "本地有数据就更新、没数据就抓取"）。改动清单（全部通过 25 项冒烟断言 +
> 离屏构造主窗口/全部弹窗）：
>   · **O-3** `data/sync_service.py` docstring 起点改回 2010-01-01 并写明"数据窗≠评估窗"；
>   · **O-5** `backtest.py` `_on_synced` / `_on_index_synced` 补竞态守卫（照抄 market.py）；
>   · **O-7** 新增 **`ui/widgets/chart_style.py`**，把**四份**重复的 Pokorny 轴样式与
>     资金/净值曲线绘制收敛为 `apply_pokorny_style` + `plot_equity_curve` 两个函数；
>     （⚠ 通读时漏数了一份：`ui/views/market.py` 也有，且它传的是 **PlotItem** 不是
>     PlotWidget —— 新函数两种类型都兼容）；
>   · **O-2** 三个 UI 线程（`_BacktestRunThread` / `_ConstituentsWorker` /
>     `FuturesImportWorker`）迁入 `ui/workers.py`，改名 `BacktestRunWorker` /
>     `ConstituentsWorker` / `FuturesImportWorker`；§2 表述已改为准确版本；
>   · **O-8** 四项小坑：`review.py` 空数据也刷新时间选择器 / `days=0` 改 `continue` /
>     切年视图清空回放图 / 画廊不再静默丢弃失效截图路径（改为标注「⚠ 已丢失」）；
>   · **O-1（用户拍板）** 流水页 + 复盘页「仅盈利/仅亏损」改为 **净额** 口径，
>     两处下拉加 tooltip 说明口径；
>   · **O-4（用户拍板）** 行情页 `force_sync_cloud` → 改名 `sync_cloud`，
>     `force_full` 恒为 **False**：本地有数据=增量、没数据=全量；
>     新增 `lbl_sync_status` 回执（已是最新 / 已更新新增 N 行 / 同步失败）。
>     "重新全量下载"仍只存在于「🗄 数据管理」页（§10-10 危险动作隔离）。
>     **v5.13 修订**：O-4 新增的同步状态 QLabel 触发了 Qt 布局坑（顶部栏末尾 QLabel
>     会把富余高度全吞掉、标题被拉成 400px），已给 main_splitter 显式 `stretch=1` 根治，
>     固化为 §11.5 第 13 条。
> v5.14：**回测结果导出落地（§7-A2 半程）** —— 用户拍板"**只做导出、不做删除**"，
> 并把「结果历史存档」列为**远期方案**（见 §7-A4，留给后续会话）。
>   · 回测页「K线控制行」右侧新增「导出明细」按钮；
>   · 新增 **`_last_meta` 参数快照**：`start_backtest` 发起瞬间定格 标的/区间/策略名/
>     函数段/参数/买卖表达式/风控/指数门控，导出永远对应当前 `_last_result`，
>     不掺导出瞬间的编辑框内容；
>   · **`_compose_result_csv`**（纯函数，14 项断言全过）= 注释头 + 逐笔明细；
>     `utf-8-sig` 落盘，Excel 可直接打开。
>     ⚠ **v5.16 推翻 v5.14 的"注释头裸写"方案**：裸写会让含英文逗号的函数源码行
>     （如 `STICKLINE(A, B, C, 3, 0), COLORFF0000;`、`MA(C, 5)`）被 Excel/WPS
>     当多列拆开 → 用户实测"第三部分：图形绘制"乱码不可读。正确做法见 v5.16。
> v5.15：**导出升级 · PNG 报告图 + 共享常量上收**（用户拍板：CSV 移除净值行 /
> PNG 加离场原因饼图 / 下拉菜单入口）。
>   · **CSV 精简**：移除 200+ 行「每日净值明细」段 —— 它既是可读性低的主因、又可由
>     引擎用相同参数复现；溯源义务交给『参数 + 逐笔』，净值曲线视觉化由 PNG 承担。
>   · **新增 `ui/widgets/backtest_report.py`**（SRP，218 行，零新增第三方依赖）：
>     单页 PNG 报告图 = 标题（品种/区间/策略）+ KPI 四卡 + 净值曲线 + **离场原因饼图** +
>     参数/风控/指数门控简表；复用 `chart_style.plot_equity_curve`；QWidget 离屏
>     grab() 渲染，中文依赖系统字体（沙箱缺 CJK 字体会显方框，属环境非代码问题）。
>   · **共享常量上收到 `core/backtest.py`**：`EXIT_REASON_LABELS` / `EXIT_REASON_COLORS`
>     / `risk_summary(...)` —— 明细表着色、CSV 表头、PNG 图例与饼图色彩**三处同源**，
>     禁止任何 UI 文件再各写一份（§9-O7 教训）。
>   · **下拉菜单取代单按钮**：`📄 导出 CSV 明细…` / `🖼 导出结果图 PNG…`，
>     未来加 XLSX 只需在 `_export_menu` 新增 action。
>   · **16 项断言全过**（CSV 无净值段且数据行=逐笔数、PNG 尺寸 1120×660、菜单结构、
>     共享常量、空 equity 容错）。报告图单页 1120×660。
> v5.16：**CSV 导出兼容性修复（用户用 WPS 实测反馈）** —— "函数源码第三部分含英文
> 逗号的行在表格软件里被拆列成乱码"。
>   · 根因：v5.14/5.15 把"注释/表头行"**裸写**（不走 csv 转义），而函数源码里
>     `STICKLINE(..., DYN_INDEX, DYN_INDEX, 3, 0), COLORFF0000;` 这类行含英文逗号，
>     Excel/WPS 打开时会当成多列拆分，表现为"图像绘制段看不到内容"。
>   · 修法：`_compose_result_csv` 里**每一行都作为单格字段走 csv.writer**
>     （含逗号行自动加引号 → 表格软件还原为单格；不含逗号行保持裸写；空行用
>     `writerow([])` 产生真·空行，不再出现 `""` 假空行）。
>   · 校验：**9 项断言** —— csv.reader 严格重解析整份文件：表头区每非空行 = 1 格、
>     逐笔区 = 8 列 × 成交数、中文离场原因可解析、无 `""` 假空行。
>   · **导出文件对任何遵循 CSV 规范的软件（Excel / WPS / 编辑器）均适配**。
> v6.0（规划定稿）：**§7-B3 公式统一绘图（引擎级 · 最高优先级 P0 · 无代码变更）** ——
> 用户复盘发现"函数里 STICKLINE/DRAWICON 画出的指标从没出现过"，根因是 `program.py`
> 长期 SKIP 绘图语句（历史 §7-B3 欠账），而 CSV/PNG/回测K线都没有能画它的底层管线。
> 用户定稿：以"**引擎产出统一绘图 IR + 唯一渲染器 OverlayPainter**"为长远架构，
> 避免未来优化各图表时逐图一对一手改；M0 契约层 / M1 求值层 / M2 渲染+回测页 /
> M3 收尾 / M4 远期全图复用。完整规格与验收见 §7-B3 主案，优先级见 §11.6。
> v6.1（图表架构总纲 · 用户 2026-09-10 拍板 · **无业务代码变更**）：
> 「§7-B3 公式统一绘图」**升级为「图表架构总纲」** —— 不再只解决"公式叠层画不出来"，
> 而是把绘图底层拆成**四层**（① 引擎 IR `core/formula/draw.py`；② 图表宿主
> `ui/widgets/chart_pane.py` + `chart_host.py`；③ 渲染器 `ui/widgets/draw_overlay.py`；
> ④ 标注对象 `data/annotations.py` + `ui/widgets/annotation_layer.py`），并厘清
> **两条互不相同的管线**：**A 公式叠层**（随数据/参数重算、**不持久**）与
> **B 用户标注**（持久到 `(标的,周期)`、**逐个独立删除**）。
> 终极形态 = **通达信级行情工作台**（主图/副图用户函数 + 画线工具 + 按标的持久化）。
> **四项拍板**：① `ChartPane` 抽象**插在 M2 之前**（防"单图写死"返工）；② 首个落地验证场
> 用**回测页**（P3），**行情页放 P4**；③ 标注存储**先 JSON、按可迁 DB 设计**（API 与存储解耦）；
> ④ **内置指标与用户公式在渲染层统一为一套"图层协议"**。
> 完整四层架构 + P0–P8 路线图见 §7-B3 总纲；铁律见 §10-12；"改 X 动哪"见 §11.4。
> v6.2（**P0+P1 落地** · 用户 2026-09-10 批准开工）：
> **P0 图表宿主最小抽象** `ui/widgets/chart_pane.py`(76 行)—— `ChartPane` 把「一个窗格」=
> PlotItem + 公式叠层容器 + 用户标注容器 固定下来；渲染器从此**只认 `ChartPane`**（防单图写死）。
> **P1 引擎 IR 契约 + 求值**：新增 `core/formula/draw.py`(124 行：COLOR_TABLE + DrawSpec/DrawData
> + 属性校验)；`core/formula/program.py` 113→**265 行**，语句分类 **3 态 → 4 态**
> （ASSIGN / OUTPUT / DRAW；旧 SKIP **移除** —— 无法识别的语句/绘图函数一律报错，绝不静默）；
> 新增 `execute_programs_with_draws()`（与 `execute_programs` **同一 EvalContext、不二次求值**）。
> 新增可复跑冒烟脚本 **`smoke_chart.py`**（P2 起扩展为"图表架构"统一冒烟入口）。
> **核心回归保证**：`execute_programs` 行为逐位不变 → 条件组 Gate / 函数检测 / 指数门控零影响。
> v6.3（**P2 多窗格落地**）：新增 `ui/widgets/chart_host.py`(262 行) —— `ChartHost` =
> **主图 + N 副图**（x 轴联动 `setXLink` / 只有最下窗格显示底部轴 / 窗格增删与高度权重 /
> `pg.DateAxisItem` 日期轴 / **跨窗格同步十字光标 + 数值回执**）；`chart_style.py` 抽出
> `style_axis()` 作为"换轴后重新着色"的唯一来源，并新增 `CROSSHAIR_COLOR`。
> `smoke_chart.py` 扩到 **97 项断言全过**；全仓 compileall + 主窗口离屏构造通过。
> v6.4（**P3 渲染器 + 回测页接入落地**）：新增 `ui/widgets/draw_overlay.py`(210 行) ——
> **全 app 唯一** `OverlayPainter(pane, bars_x).render(draws)`：line→`PlotDataItem`、
> stick→自绘 `_StickItem`（TDX 语义：width≤1 细线 / >1 实体 / 第5参=空心）、icon→`ScatterPlotItem`
> （图标号映射表 + 未知号默认菱形）；附 `slice_draws()` / `overlay_extent()` 两个宿主工具。
> **新增 `chart_style.ensure_contrast()` 对比度守卫**（通达信公式按黑底写的 `COLORWHITE`
> 搬到白底会"画了看不见"—— 保留色相地压暗/提亮到 WCAG 3:1 且亮度差 ≥0.30）。
> **回测页 `🕯 K线买卖点` 接入**：`_on_data_ready` 改走 `execute_programs_with_draws`
> （不二次求值）；`_render_kline` 按 **"排序后位置→原始行号"映射**切窗口喂叠层（防漂移）；
> 新增「显示公式叠层」开关（只切可见性、不重置缩放）；y 范围纳入叠层（超 K 线高低价不被裁）；
> **函数检测阶段也走同入口** → 写错的绘图语句"检测时"就报错。
> **验收**：`smoke_chart.py` **126 项** + `smoke_backtest_overlay.py` **20 项页面级**（含
> 离屏 grab 像素差异证明"真画上去了"）全过；全仓 compileall + 主窗口离屏构造通过。
> v6.5（**事故修复：存量函数回归** · 用户 2026-09-10 实测反馈）：用户在软件里报
> "之前能正常用的保存好的函数突然跑不了"，报错 `无法识别的语句 'STICKLINE(...), COLORFF0000':`
> `公式末尾存在无法解析的内容: ','`。**根因 = v6.4(P1) 引入的回归**：`_compile_draw` 把整条
> 绘图语句（含**尾部颜色属性**）直接喂给 `parse()`，而通达信本来就允许
> `STICKLINE(条件,价1,价2,宽,0), COLORFF0000;` —— 旧版整行 SKIP 所以"能用"，新版必炸；
> 且 `start_backtest` 依赖检测成功 ⇒ 函数**彻底跑不起来**（详见 §9-Q）。
> **修三处**：① 新增 `_split_draw_attrs()`，先按**顶层逗号**把尾部属性切出去再解析
> （与输出语句属性解析同源，不引入第二套文本解析）；
> ② 已知但未渲染的绘图函数（DRAWTEXT/DRAWBAND…）**不再硬报错**，登记成 `kind='unsupported'`，
> 由检测结果给出**非阻断提示** —— 既看得见、又不掐死存量函数；
> ③ `STICKLINE(状态, P, P, w, 0)`（价1==价2）原来会退化成 0 高度矩形 → **什么都看不见**，
> 改为画**横杠**（用户那 4 根彩色状态柱正是这个写法）。
> 已用**用户真实函数**（`samples/实例函数.txt`，L1=5/L2=20）端到端复验：解析通过、27 个变量、
> 2 线 + 4 色状态柱 + 1 图标、横杠有宽度。
> 断言：`smoke_chart.py` **134 项** + `smoke_backtest_overlay.py` **25 项** 全过。
> v6.6（**P4 落地：行情页公式叠加 + 内置/用户指标统一图层**）：
> 新增 `ui/dialogs/formula_overlay.py`(144 行) 公式编辑器（复用 `FunctionSegments`，
> 自检口径与回测页**同源**）；`ui/views/market.py` 新增「🧮 自定义公式」区（开关 + 编辑 + 状态），
> 并把 **MA/BOLL 与用户公式都翻成 `DrawData`** 交给**同一个** `OverlayPainter` ——
> §7-B3 D4「像 MA 一样显示用户函数」落地为**架构事实**，而不是给用户公式单开分支
> （连开关行为都与均线/布林带一致：同一个 `render_charts`）。
> 为消除跨页重复，抽出三件**共用件**：`core.utils.parse_params_text`、
> `core.utils.synthetic_bars`、`core.formula.program.probe_missing_parameters` ——
> 回测页与公式编辑器**共用同一份**，免得同一函数"行情页能跑、回测页缺参"（§11.5-11/12）。
> `smoke_backtest_overlay.py` **更名 `smoke_pages_overlay.py`**（现在也覆盖行情页）。
> 断言：`smoke_chart.py` **146 项** + `smoke_pages_overlay.py` **36 项** 全过；
> 全仓 compileall + 主窗口离屏构造通过。
> 下一步 = **P5 副图指标（附图）**。⚠ 注意 `market.py` 已到 425 行，**P5/P8 必须新建文件**。
> v6.7（**P5 前置 + 对话框返工 + 共用组件修 Bug** · 用户实测反馈驱动）：
> ① **`ui/widgets/function_segments.py` 两个真实 Bug**（回测页因在滚动容器里没显形，
>    对话框给出大高度才暴露）：
>    · **僵尸段** —— `set_texts()` 的 `removeWidget + deleteLater()` 只把控件移出布局，
>      在事件循环真正删除前它**仍是可见子控件** ⇒ 对话框里出现两个"函数段 1"（用户截图）；
>      修法：先 `setParent(None)` 立刻脱离父级，再 `deleteLater()`。
>    · **排版塌陷** —— 编辑框 `setFixedHeight(96)`，父级分到多余高度时**无人承接** ⇒
>      段标题被顶到最上、编辑框被推到几百像素之外（"标签与框之间一大片空白"）；
>      修法：`Expanding` 纵向策略 + 最小高度，让多余高度**变成编辑面积**。
> ② **公式对话框返工**（`ui/dialogs/formula_overlay.py` → 246 行）：去重复、补引导、收拾版面 ——
>    新增**目标窗格**（主图/副图）+ 随选动态说明 + **示例模板菜单**（主图/副图各一套，
>    "用例子教"比堆说明文字有效）；编辑区放进 `QScrollArea`，段多也不撑爆。
> ③ **支持副图叠加**（P5 前置）：`market.py` 在既有窗格体系上新增「**公式副图**」窗格
>    （`setXLink` 联动主图、**y 轴独立**、数值跨 0 时给零轴参考线）——
>    副图量级的函数（MACD/RSI/成交量）从此**不会再把 K 线压扁**。
> ④ **量级引导**：新增 `ui/widgets/chart_layers.py`(65 行，图层公共件) ——
>    `builtin_indicator_layers()`（内置指标→IR，页面不再自己换算）+
>    `layer_value_range()` + `scale_mismatch_hint()`（数值与股价差 3 倍或完全错位 →
>    在面板明说"建议改用副图"，完整解释进 tooltip）。
> 断言：`smoke_chart.py` **161 项** + `smoke_pages_overlay.py` **58 项** 全过；
> 全仓 compileall + 主窗口离屏构造通过。
> 下一步 = **P5 剩余部分**（多副图 / 内置指标也可放副图）→ P6 → P7 → P8。
> v6.8（**P5 落地：多副图 + 窗格编排收编 ChartHost**）：
> ① **每段可选目标窗格**（主图 / 副图 1/2/3）—— 对话框把"目标"下放到每个函数段右侧；
>    `FunctionSegments` 新增 `accessory_factory`（每段附件控件；回测页不传 ⇒ 行为零变化）。
> ② **引擎新增 `execute_programs_with_draws_grouped`**：draws **按函数段分组**返回 ——
>    各段必须共用**同一个变量池**（后段引用前段变量），所以"每段不同目标"只能
>    **一次求值、再按段归位**，绝不能按目标分组各跑一遍（那会把共享池打断）；
>    顺带把三个执行入口收敛到唯一的 `_run_programs` 循环（消除三处重复）。
> ③ **行情页窗格编排迁移到 ChartHost**（§10-12 的违规清账）：market.py 不再自己
>    `addPlot` 拼窗格；`ChartHost` 补齐 `fixed_height`（钉死附图 150px 旧观感）、
>    `bottom_axis_mode`（hide / no_values，行情页用后者保住轴线）、`clear_sub_panes()`、
>    `clear_pane_content()`（比 `PlotItem.clear()` 安全 —— 不会把十字光标一起删掉）、`setBackground()`。
> ④ **多副图按需创建**：有目标为副图的图层才建窗格；量能/振荡指标各占一格、互不压扁。
> ⑤ **内置副图内容搬出页面**：新增 `ui/widgets/indicator_panes.py`（成交量 / MACD 内容构建）。
>    ⚠ 量柱/MACD 仍是原生 `BarGraphItem`（逐柱配色是它的强项），**尚未**并入图层协议 ——
>    这是 P5 明确保留的例外（不为架构一致性去改两张已经好用的图，P8 统一）。
> 断言：`smoke_chart.py` **161 项** + `smoke_pages_overlay.py` **63 项** 全过
> （含"跨段共享变量池仍可用""窗格顺序/x 联动/y 独立""刻度值只在最下窗格"）。
> **market.py 463→448（首次下降）**。下一步 = **P6 标注持久化** → P7 → P8。
> v6.8 追记（收工前用户反馈 · **立项 §7-B4 坐标轴自适应**）：
> 行情数据中心放大看局部时间时，横轴只剩一个无意义刻度（截图中的"A"）、纵轴量程不随可视窗口
> 重算（副图整段历史被压成一条线）。经排查这是**全 App 普遍性缺陷**（§9-S：行情/复盘全是静态
> ticks，只有回测页手写对了），已立项 **§7-B4 主案 + 实施步骤** —— **P0–P8 步骤完成后立即做**，
> 方案与验收见 §7-B4。今日进度（P4/P5 前置/P5 + §9-Q/§9-R）已全部同步至 §4/§6/§7/§8/§9/§11。
> v6.9：**第三次"陌生代码"复查 + 小债清账**（本批为纯收尾，无新功能）：
> ① **§9-P1 净额残留收尾** —— 新增 `core/utils.record_net_amount(record)`（全站唯一
>    「净额 = 平仓盈亏 − 手续费」取值口径，容忍 Series/dict/TradeRecord + NaN），
>    并把**逐笔展示层**最后 4 处毛利判定改净额：流水页盈亏列（**着色 + 显示值，
>    列名改「净盈亏」**）、复盘页当日清单、复盘页详情头、回放标记色/高亮带方向。
>    至此 §5.3-B 的"全站再无例外"**首次真正成立**。
> ② **§10-9 控件契约收口** —— 新增 `custom_widgets` 的 **复合控件完整 QSS 生成器**
>    （`combo_qss` / `date_edit_qss` + 8 个具名常量）。清理 7 处业务页面就地半截样式。
>    ⚠ **实测发现一个长期隐形 Bug**：`QComboBox/QDateEdit` 一旦被写上 `::drop-down`
>    而**没有** `::down-arrow`，Qt 切到样式化绘制路径后**下拉箭头会整个消失** ——
>    复盘页时间选择器与手工录入弹窗此前正处于这种"没有箭头"状态。现统一用
>    **border 三角**绘制箭头（纯 QSS、零图片资源）。
> ③ **NoWheel 补齐**：新增 `NoWheelDateTimeEdit`；复盘页孤儿补录日期、手工录入弹窗的
>    日期/时间/数值控件全部换入 NoWheel 族（§6.6-U2 的遗漏项）。
> ④ **行情页接线跨窗格十字光标**（P2 早已具备、此前未接），竖线贯穿主图/量能/MACD/公式副图。
> ⑤ 断言：`smoke_chart.py` 161→**178 项**（+净额口径 6 项、+样式契约 11 项，含
>    "半截 QSS 看不到箭头"的**负向对照**）；`smoke_pages_overlay.py` **63 项** 全过；
>    全仓 compileall 通过。**§4 行数已按本次实测重刷**（口径 = 非空行）。
> v6.10：**红线收编 + P6 标注持久化落地**（承接 v6.9 的小债清账）：
> ① **§9-T4-① 收编（用户拍板"红线不放宽"）** —— `MarketSyncService` 新增
>    `fetch_index_constituents()`：**联网抓取的唯一入口**。`ConstituentsWorker`
>    不再 import 行情源（`ui/` 全层**零 `AkShareFeed`**，已用源码级断言守门）；
>    失败文案按"网络 / 行情源未收录"分类（§10-10）。连带修掉 §9-J 里
>    "docstring 与实现不符"的同源问题（worker 只调度，联网细节归门面）。
> ② **P6 用户标注持久化（管线 B）全部落地** ——
>    新增 `data/annotations.py`（255 行，零 Qt：对象模型 + `(标的,周期,id)` 原子写 CRUD +
>    `DateAxis` 日期↔序号映射）与 `ui/widgets/annotation_layer.py`（222 行：绘制 + 选中 +
>    **逐个独立删除**）。**坐标存日期不存序号** —— 数据窗口前移后标注仍锚在同一天
>    （有"前置 5 根 ⇒ 序号 +5 而非漂移"的页面级断言）。`ChartPane` 补 `remove_annotation()`
>    与 `add_annotation()` 成对（防"容器与真实图元不一致"）。行情页旧的"内存趋势线"
>    （§7-A1 欠账）**被吸收升级**：三类标注（趋势线/水平线/垂直线）+ 工具下拉 +
>    删除选中 + 清空（二次确认）+ Delete/Esc 快捷键 + 面板回执。
> ③ 断言：`smoke_chart.py` 178→**212 项**、`smoke_pages_overlay.py` 63→**84 项**，全过；
>    全仓 compileall 通过。§4 行数再次按实测重刷。
> v6.11：**P7 函数资产化 + 行情↔回测互送落地**：
> ① **配方库**（新增 `data/formula_store.py` 213 行，零 Qt）：把「函数段 + 参数 +
>    **每段的目标窗格**」存成有名字的**配方**，`~/.jian_data/formula_library.json` 原子写，
>    按 `name` upsert（同名即覆盖）、`touch/last_used` 记录使用、坏数据行容忍。
>    **与 `strategy_store` 同源但不合并**：配方只有公式；策略 = 配方 + 条件 + 风控 + 区间。
> ② **配方库窗口**（新增 `ui/widgets/formula_library.py` 171 行）：列表 + 预览 + 载入/改名/删除，
>    **两个页面共用同一个对话框**（不为某页写特例）。
> ③ **互送**（`main_window` 当唯一传话筒，两个页面**互不 import**）：
>    行情页「📤 送去做回测」→ 回测页①函数区（**目标窗格不随行**，回测没有副图概念）；
>    回测页「📤 送到行情页」→ 每段默认落主图并立即渲染；两边都会**自动切页 + 自动自检**。
> ④ **"公式重启就丢"治本**：行情页开机自动恢复 `last_used` 配方（面板明说来历），
>    另有「💾 存为配方…」入口（行情页存 **target**、回测页存 **文本**，来源分别标记）。
> ⑤ 断言：`smoke_chart.py` 212→**238 项**（配方模型 26 项，含"三种入参形态"与
>    "VALID_TARGETS 必须与编辑器下拉一致"的防漂移断言）、`smoke_pages_overlay.py`
>    84→**111 项**（互送链路 25 项 + **防污染自检 2 项**）；全仓 compileall 通过。
> ⑥ 一次性事故：P6 调试期某个中间版本在用户目录留下了一个**空** `annotations.json`
>    （`items: []`，零影响），已清理；并给页面级冒烟加了**"用户真实库未被创建/修改"**的
>    收尾自检 —— 以后测试再想污染用户数据，冒烟当场红。
> v6.12：**P8 行情页整体重做（换壳不换芯）落地**：
> ① **新页面 `ui/views/trading_desk.py`**（734 行，"行情工作台"）：旧 `ui/views/market.py`
>    **已删除**（661 行越线文件到此为止）。页面**只做装配与交互**，图表能力全部来自既有组件
>    （ChartHost / OverlayPainter / chart_layers / annotation_layer / indicator_panes /
>    formula_store / formula_library / workers+sync_service）—— 没有新增一行绘图逻辑。
> ② **自选股**（新增 `data/watchlist_store.py` 143 行，零 Qt）：增删/上下移/双击切换、
>    名称随花名册刷新、坏数据与重复项容忍；`~/.jian_data/watchlist.json` 原子写。
> ③ **周期切换 日/周/月**（`core/utils.resample_ohlcv` 纯函数）：由日线**就地聚合**
>    （开=首 高=max 低=min 收=末 量=和，**date 取该周期最后一根真实交易日**），
>    列名与日线完全一致 ⇒ K 线/指标/公式/标注**零改动**；指标在聚合**之后**才算
>    （否则"周线 MA5"会变成"日线 MA5 被抽样"）。
> ④ **画线工具栏 3 类 → 5 类**：新增**斐波那契**（两端点 + 7 档水平位 + 标签，
>    拖动重算）与**文字标注**（`_ClickableText` 子类 —— `pg.TextItem` 本身不发点击信号，
>    不补这个信号就**没法单独选中/删除**，管线 B 的"逐个独立删除"直接不成立）。
> ⑤ **标注按 `(标的, 周期)` 隔离**：新增 `data/annotations.period_key()` 规范化周期键，
>    存 `daily/weekly/monthly`；日线上画的线**不会**跑到周线上。斐波那契的附属图元
>    （水平位/标签）登记进 `_extras`，删/清/重建与主图元**同步**（§11.5-15 同类风险）。
> ⑥ 断言：`smoke_chart.py` 238→**278 项**（周期重采样 9 + 自选股 13 + 斐波那契/文字 18）；
>    `smoke_pages_overlay.py` 111→**132 项**（P8 页面级 21：自选/周期/隔离/新标注类型 +
>    防污染名单加 `watchlist.json`）；全仓 compileall 通过。
>    ⚠ **本轮踩到一次"脚本看起来卡死"**：详见 §11.5-20（离屏测试三条打桩铁律）——
>    根因是"模态框阻塞 + 管道缓冲 + 非守护线程不退出"三件事叠加，**与网络无关**。
> ⑦ **P8 仍待做（明确登记，非欠账）**：**复权切换**（需新增"不复权"数据湖分区 + 抓取链路，
>    涉及数据窗红线，单独一轮做）、**分钟周期**（§7 D3 远期）、斐波那契/文字的**锚点拖动**
>    （文字本轮为放置式）。修完这些再进 **§7-B4 坐标轴自适应**。
> v6.13：**P8 收尾完成（复权切换 + 文字标注拖动）**：
> ① **复权切换（前复权 / 不复权）** —— 关键决策：**不复权数据单独一个数据湖分区**
>    `kline_daily_raw`，而不是在原分区加一列。理由：前复权会随除权**整体漂移**、不复权不会，
>    两份数据永远无法互相推导；同文件只能二选一覆盖（切一次复权重下一遍全历史）。
>    链路：`akshare_feed` 两个源都按同一个 `adjust` 拉取（**不允许多源降级时静默换复权口径**）
>    → `sync_service.zone_for_adjust()`（UI 唯一入口）→ 工作台复权下拉；
>    「数据管理」新增「日线行情 (不复权)」分区并可单独同步/删除（两份互不影响）。
>    切到不复权若本地没有 → 自动转后台取数，面板立刻给"取数中"回执（**且不谎报根数**）。
> ② **文字标注可拖动** —— pyqtgraph 覆写了 `mouseMoveEvent` 且不调父类实现，所以
>    `ItemIsMovable` **不会**让图元真的跟着走：必须自己实现 `mousePressEvent`/`mouseDragEvent`
>    （按场景位移量改坐标），并**松手才落盘**（不在拖动途中疯狂写文件）；
>    拖动后坐标按 (日期, 价格) 回写，重启读回一致。
> ③ 断言：`smoke_chart.py` 278→**290 项**（复权链路 7 + 文字拖动 5）、
>    `smoke_pages_overlay.py` 132→**139 项**（页面级复权 7）；全仓 compileall 通过；
>    临时脚本/输出文件已清理，仓库无残留。
> ④ P8 **仅剩分钟周期**未做（`kline_min` 属 §7 D3 远期，非欠账）。下一步按用户指示进
>    **§7-B4 坐标轴自适应**。
> v6.14：**全仓文件归置（零业务代码变更）** —— 用户指出"根目录存在许多未分类文件"，
> 于是按新立的 **§10-13 文件归置规范** 把根目录收敛为"门面"：
> ① 新增三个**角色目录**（判据 = "谁去调用它"，不是"它像什么"）：
>    `scripts/`（运维脚本，**人工运行、不进 app import 图**）、`tests/`（验收脚本）、
>    `samples/`（私有样例，**是数据不是代码**）；
> ② 根目录**只留** `main.py` / `requirements.txt` / `version.json` / `JIAN_RULES.md` / `.gitignore`
>    + 四个层目录：`sync_roster.py`→`scripts/`、`smoke_*.py`→`tests/`、
>    `实例函数*.txt` + `实例交割单*.xlsx`→`samples/`；
> ③ **删除**根目录空壳 `screenshots/`（§9-C 早已记为"历史遗留"）与全仓 `__pycache__`；
> ④ 移动脚本**必须同批修路径引导** —— 子目录里 `sys.path[0]` 不再是仓库根，
>    一律改 `__file__` 反推，否则 `from data...` 当场 ImportError；
>    连带改掉**用户可见文案**（"花名册为空 —— 请先运行 `scripts/sync_roster.py`"）与 docstring；
> ⑤ `.gitignore` 收紧为 `samples/*` + `!samples/README.md`（**整目录忽略、只放行说明**，
>    比"逐个文件名模式"可靠得多）+ 新增 `_tmp_*` 兜底（会话期探针脚本/输出**不留仓**）；
> ⑥ 回归：`py tests/smoke_chart.py` **290 项** + `py tests/smoke_pages_overlay.py` **139 项** 全过，
>    全仓 compileall 通过；`git ls-files` 核对**无死代码**（所有 py 都被引用，唯二"零引用"的是
>    两个独立入口脚本，属正常）；`market.py` 的删除也在同批走 `git rm`。
> ⑦ 顺带登记待办（**暂缓**）：`ui/widgets/` 17 文件平铺，可再分 `chart/` 子包 —— 但涉 51 处
>    import 且牵动 §7-B3 四层表锚点，留待单独一轮。
> v6.15：**§7-B4 坐标轴自适应全部落地（全 App 收口）** —— 治的是用户截图反馈的两个普遍缺陷：
> ① **放大后横轴只剩一个刻度**；② **纵轴不随可视区自适应**（副图被全量极值压成一条线）。
> 根因：全 app 的 x 是"bar 序号 + 日期映射"，pyqtgraph 不知道这层映射；而正确实现只在回测页
> 写对过一次、**没抽成公共件** ⇒ "改一处漏三处"（§9-O7 同款）。
> ① 新建 **`ui/widgets/adaptive_axis.py`(348)** ＝全 app 唯一的刻度/量程来源：
>   纯函数 `compute_ticks`（日期格式梯子：日内 / 同年 / 跨年）/ `compute_text_ticks`（序数轴）/
>   `slice_span`（可视极值，NaN 忽略）；信号挂接 `attach_date_axis` / `follow_y` / `attach_all`
>   （**同轴重复 attach 自动替换旧跟随器**，页面每次重渲染无脑调）；
> ② **3 处静态 ticks 全部收敛**（行情主图/量/MACD/公式副图逐窗格、复盘 K线回放、复盘资金K线），
>   回测页两处也改为调用公共纯函数（「价格轴跟随可视区间」开关语义保留）；
> ③ 页面只回答"**该窗格在可视区间内的数值范围**"（provider 契约），公共件不猜业务；
> ④ 两条新知识已固化：**`ViewBox.setYRange` 会偷加自己的 padding**（一律 `padding=0`，§11.5-21）、
>   **复盘"资金 K 线"其实是"当月第几日"的序数轴**（套 `%m-%d` 会说谎 ⇒ 增设文本刻度入口，§9-v6.15）；
> ⑤ 断言：`smoke_chart` 290→**312**、`smoke_pages_overlay` 139→**150**，全过 + 全仓 compileall。
> v6.16：**A 类文档欠账清账（零业务代码变更）** —— 用户拍板两项：
> ① **§4 行数改为"只标 ≥400 行的文件"**（逐文件维护精确数字每次大改都要返工，且 v6.15 那批
>    实测已有 10+ 处漂移；行数的唯一用途是"提醒谁快越线"，<400 行不标即不漂）；
> ② **版本号统一跟随 git**（= 最近一次 push 的 commit message 首词，**每次 push 递增 0.01**）
>    —— `APP_VERSION` 与 `version.json` 已由 `1.4.1` 迁到 **1.20**，新纪律写进 §9-A；
>    顺带修掉 2 处"指向已删除 `market.py`"的**活引用**（`formula_overlay.py` / `backtest.py`）、
>    4 处历史叙事补注、文档 §11.4 两条活引用；§11.6 标题与全文旧行数一并校正。
> ℹ **`version.json` 的 `url` 已由占位符 `https://github.com` 改为项目 Releases 列表页**
> `https://github.com/ENDVEN/Jian/releases`（用户 2026-09-15 决定：软件尚未完工，
> **暂不制作 Release**，先用它占位；正式发版时再换成具体版本直链 —— 见 §9-A 末条）。
> v6.17：**§7-B5 立项「回测成交真实性」（零业务代码变更）** —— 用户提出三个痛点（指标滞后 /
> 开盘容量限制 / 盘中已出信号却要等次日成交），拍板四项：① **T+1 修正默认开启、不给旧口径开关**；
> ② **「当日收盘」成交档**要做；③ **触发式委托（条件单）**要做；④ **P1（账户+容量+成本）与
> P2（盘中即时成交）搁置**，设计留档待将来评估。
> 立项前用合成 K 线探针**实测 7 组**（跑完即删），坐实 5 条现状事实 ——
> 其中 **F3 是危险项：止损 / 止盈 / `max_bars` 能在买入当天就离场 ⇒ 按 A股 T+1 属违规，
> 方向是"低估风险"（带止损的策略回撤比真实好看）**；**F2 是"引擎根本没有仓位"**
> （`equity` 是 1 股复利、`shares` 恒为 1），所以"大仓位影响价格"当前无处安放。
> 产出 **§7-B5 主案**：P0 定稿规格（C1 三档成交时点 / C2 T+1 闸门 + "进场当根触发则顺延到
> 最早可卖根开盘价" / C3 触发价与跳空处理**与风控同源** / C4 唯一口径 / C5 **七条验收断言含
> 负向对照**）、影响面 5 条、实施步骤 0–5、P1/P2 挂起设计（含"明确不做"清单）。
> **下一步 = 步骤 1：引擎核心（`core/backtest.py`），等用户确认口径后开工。**
> v6.18：**§7-B5 P0 落地（步骤 1–3）+ 用户指引返工**。用户先追加拍板"**同根卖出后当根不再重建仓**"，
> 随后实测反馈"**触发式条件单 / 触发跳数 完完全全看不懂**"，于是这一批做了三件事：
> ① **引擎**（`core/backtest.py` 315→**495**）：三档成交时点 + **T+1 硬约束**（进场当根触发
>    价格型风控 → 顺延到最早可卖根**开盘价**成交；`max_bars` 顺延到次根收盘；末根不建仓）
>    + **同根不重建仓**（判据 = **成交根**重合，**不是**评估根 —— 写宽了会误杀"离场后下一根
>    的合法再入场"，实现时当场自我复查修窄）；
> ② **口径连通 + UI**：策略签名（**默认口径归并为空串** ⇒ 旧存档签名一字不变）/ 旧档回落 /
>    `_last_meta` / CSV 表头与「（T+1 顺延）」标记 / PNG 报告图；回测页新增「🎯 成交模型」行；
> ③ **用户指引**（用户反馈驱动）：文案换成"什么时候、按什么价、会发生什么"，术语翻译成
>    用户量纲（`1 跳 → 0.01 元`、`当根 → 当天`、"信号作废" → "就不买也不卖"）；新增
>    **行内实时说明**与**教学弹窗** `ui/dialogs/fill_model_help.py`（一套固定价格数字三档对照）；
>    参数只在有意义的档位出现。
> **纪律固化**：§10-10 追加条款（术语不许当唯一解释 + 教学入口三条硬要求）、§11.5-22（四步模板）、
> §11.7 自检加一栏。
> ④ **步长 Bug 修复（同批用户实测反馈）**："买卖价要多等"按一次上箭头就跳到 0.2 且无法继续
>    上调、没有过渡价格。根因**不是图标**：公共工厂 `_risk_spin` 把步长写死成
>    `1 if decimals == 0 else 0.5`，对 2 位小数的新控件等于"一按顶到上限"。
>    修为**随小数位自适应**（`0→1` / `1→0.5` / `≥2→10^-decimals`）并把上限放宽到 **1.00 元**；
>    教训固化为 **§11.5-23**（公共工厂里写死的经验默认值，换量纲就会咬人）。
> **验收**：四套一次性探针 —— C5 引擎 **39** / 口径+UI **22** / 文案可懂性 **24** / 数值控件步长 **12**
> （含**正则级行话检测**与**借 `git show HEAD` 旧引擎逐位回归**）全部通过；项目冒烟
> `smoke_chart` **312** + `smoke_pages_overlay` **150** 全过 + 全仓 compileall。
> ⑤ **步骤 4 验收**：断言移植进两个冒烟脚本（`smoke_chart` 312→**356**、`smoke_pages_overlay`
>    150→**180**）+ **用户真实资产端到端复跑**（两个私有公式解析/求值通过、27/17 变量、
>    各 7 条绘图指令；真实策略存档 2 套签名不变；三档 + 风控对照 49/41/33 笔、
>    T+1 顺延 10/0/10）—— 全部符合设计预期。
> **遗留 = 步骤 5（收尾回写）+ 用户手动实测手感。**
> v6.19：**提交发版 —— app 版本升到 `1.21`（零业务代码变更）**。§7-B5 回测成交真实性的
> 实现与验收已在 v6.17（立项）/ v6.18（落地）完成，本批只做**三处版本号同批同步**
> （§9-A 新纪律的**首次实跑**）：① commit message 首词 **`1.21 回测策略更新`**；
> ② `config/settings.py:APP_VERSION` = **`1.21`**；③ 仓库根 `version.json` = **`1.21`**
> （`notes` 换成这一轮的用户可见变更：三档成交时点 / T+1 / 同根不重建仓 / 口径入签名与导出 /
> 教学弹窗 / 步长修复）。**用户手动实测手感已通过**（原话"现阶段没问题"）
> ⇒ **§7-B5 步骤 0–5 全部收官**。
> ⚠ 本次**只提交、未 push**（push 才会触发老用户的「✨ 发现新版本」提示）。
> **下一轮 = `1.22`：回测页 UI 大改**（用户已定方向，方案待讨论 —— 见 §11.6）。
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
| 并发 | 耗时 I/O 一律 QThread Worker | ✅ v5.13 已收口：`ui/workers.py` 是全 app **唯一的 QThread 定义处**（ScanWorker / SyncWorker / SingleSyncWorker / BacktestRunWorker / ConstituentsWorker / FuturesImportWorker），页面与弹窗一律不自造线程类。**唯一例外**：`core/updater.py` 的 `UpdateCheckerThread` 属 core 层（版本检测不是 UI 职责），不搬进 ui/ |

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
| 📈 行情工作台 | `TradingDeskView`（`ui/views/trading_desk.py`，P8 新页；旧 `market.py` 已删） | [x] | 代码查询、数据湖优先+联网兜底、K线+MA/BOLL+量+MACD、**🧮 自定义公式叠加**(与内置指标同一图层协议；**每段可选主图/副图 1/2/3**，多副图按需创建)、**跨窗格十字光标**、**自选股**(增删/排序/双击切换)、**周期 日·周·月**(日线就地聚合)、**复权 前复权/不复权**(两份数据各存一个分区且可单独同步/删除，v6.13)、**画线 5 类**(趋势/水平/垂直/**斐波那契**/**文字可拖动**，按 `(标的,周期)` 持久化 + **逐个独立删除**)、**公式配方库**(💾 存为配方 / 📚 配方库 / 📤 送去做回测，开机自动恢复)、**坐标轴自适应**(v6.15/§7-B4：横轴刻度随缩放重算、**逐窗格**纵轴跟随可视区间) —— ⚠ 仅剩：分钟周期（§7 D3 远期） |
| 📐 市场回测 | `BacktestModule` | [~] | M1 单股回测完整（含 **📚 配方库 / 💾 存为配方 / 📤 送到行情页**，v6.11/P7）；M2 全市场筛选 / M3 广度统计为 **ComingSoon 占位** |
| 🗄 数据管理 | `DataManagerView` | [x] | 数据湖 8 分区清单(行数/日期范围/体积/更新时间)、搜索过滤、勾选删除、清空分区(隔离+键入确认)、「更新到最新」「重新全量下载」、批量预下载 |

| 弹窗 | 文件 | 完成度 | 摘要 |
|---|---|---|---|
| 期货交割单导入 | `dialogs/import_futures.py` | [x] | QThread 后台解析；inserted/ignored 防重报告；孤儿提醒；时间精度强选 |
| 手工录入 | `dialogs/manual_entry.py` | [x] | 账户仅真实列表+可新建；开仓时间选填(勾选才生效)；LONG/SHORT |
| 账户/策略管理 | `dialogs/list_manager.py` | [x] | 通用删除列表（带危险确认） |
| 批量预下载 | `dialogs/bulk_download.py` | [x] | 来源：指数预设(29)/指数成分股/粘贴代码列表/全市场A股；参数：起点/间隔/抖动/熔断/跳过已最新；进度+失败清单+中断 |

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
│   ├── smoke_chart.py   # 1162行 图表架构 + 控件/口径/标注/配方/周期/自选/复权/拖动/坐标轴
│   │                    #        + **成交真实性(§7-B5)** 断言（**356 项**）
│   │                    #       `py tests/smoke_chart.py`（在仓库根执行）
│   └── smoke_pages_overlay.py # 734行 回测页/工作台叠层 + 标注 + 互送 + 自选/周期/复权/坐标轴
│                        #       + 成交模型行/教学弹窗/导出口径**页面级**验收（**180 项**）
│                        #       ⚠ 会真建主窗口（开用户库），勿与 app 同时跑；末尾含"用户真实库未被写"自检
├── samples/             # 【私有样例：是数据不是代码】`.gitignore` 里 `samples/*` 整体忽略
│   ├── README.md        #     本目录规则说明（**唯一入库文件**）
│   └── 实例函数*.txt / 实例交割单*.xlsx   # 用户私有公式与交割单（**禁止入库**，见 §10-6）
├── config/
│   └── settings.py      #     全局常量：APP_NAME、APP_VERSION=1.20(跟随 git，与 version.json 同步)、颜色、
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
│   ├── preferences.py   #     Preferences 单例：~/.jian_data/preferences.json（唯一键 time_precision）
│   └── updater.py       #     UpdateCheckerThread(QThread)：远端 version.json 异步比对，静默失败
├── data/                # 【数据获取/存储层】
│   ├── data_feed.py     # 827行 CFMMC 解析：纯函数无副作用；成交/持仓/结算月报三页签；
│   │                    #      BaseTradeParser+PARSER_REGISTRY(扩展预留，无人调用，见 §9-K)；
│   │                    #      FIFO 缝合与孤儿分配；漏月检测
│   ├── akshare_feed.py  #     AkShareFeed：A股新浪/东财兜底、期货主连、指数日线(阶段C)、花名册、清洗路由
│   │                    #      + ★v6.13 ADJUST_QFQ/NONE：**两个源必须同一个 adjust**（降级不许静默换口径）
│   │                    #      ⚠ 供 UI 引用的仅限纯函数：is_stock_code/is_index_symbol/INDEX_PRESETS(29项)
│   ├── market_db.py     #     DataLakeManager：parquet 分区存取(exists/save/load/get_latest_date)
│   │                    #      + ★v6.13 新增 kline_daily_raw 分区（不复权，与前复权**各存一份**）
│   │                    #      + v5.8 清点删除(delete_data/clear_zone/list_zone/inventory 只读footer/zone_stats)
│   ├── sync_service.py  #     MarketSyncService(v5.8)：行情同步唯一门面 = 增量合并去重 + 温柔抓取
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
    │                    #      ConstituentsWorker(成分股)/FuturesImportWorker(交割单)
    ├── widgets/         # custom_widgets.py(K线图元/NoWheel控件族/悬浮删除/SPINBOX_QSS
    │                    #   + ★v6.9 **复合控件完整 QSS 契约**：combo_qss()/date_edit_qss() 生成器
    │                    #     & 8 个具名常量 COMBO_QSS* / LINE_COMBO_QSS / DATEEDIT_QSS_WARN /
    │                    #     DIALOG_INPUT_QSS —— 全 app 唯一的控件样式来源，§10-9)
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
    │                    #   / annotation_layer.py(★v6.10/P6 用户标注交互：画/选中/**逐个删除**；
    │                    #        v6.12 加 斐波那契(7 档附属图元随主图元同删) 与 文字(_ClickableText)；
    │                    #        v6.13 文字**可拖动**——pyqtgraph 覆写了 mouseMoveEvent 且不调父类，
    │                    #        故 ItemIsMovable 无效，必须自己实现 mousePress/Drag + 松手落盘)
    │                    #   / formula_library.py(★v6.11/P7 配方库窗口：列表/预览/载入/改名/删除，两页共用)
    ├── dialogs/         # import_futures / manual_entry / list_manager
    │                    #   / bulk_download(416 批量预下载；v6.10 成分股改走同步门面)
    │                    #   / formula_overlay.py(★v6.7 行情页公式编辑器：每段目标窗格+示例模板)
    │                    #   / fill_model_help.py(★v6.17 成交模型用户教学弹窗：三档口径 + T+1
    │                    #        用一套固定价格数字讲差别；**只读不写**，不改任何配置)
    └── views/           # dashboard / records
                         #   / review(1067 ★月/年双模态 + 回放 + 资金K线 + 截图画廊)
                         #   / trading_desk(898 ★v6.12/P8 行情工作台——旧 market.py 661 已删除)
                         #   / backtest_module + backtest(1691 ⚠ **全仓最大业务文件，§9-L 首选拆分**)
                         #   / data_manager(500 🗄数据管理, v5.8)
```

**体积红黑榜（v6.16 实测）· 口径与纪律：**
- **只给 ≥400 行的文件标行数（v6.16 用户拍板）**：行数的唯一用途是"提醒哪个文件快膨胀到
  不该再堆功能"，逐个文件维护精确数字只会定期返工（v6.15 那批实测已有 10+ 处对不上）。
  **<400 行的文件在 §4 一律不标数字**；要看体积请现测（口径 = **非空行**）。
- **业务文件 ≥400 行（当前实测降序）**：
  ⚠ `ui/views/backtest.py 1691` > `ui/views/review.py 1067` > ⚠ `ui/views/trading_desk.py 898` >
  `data/data_feed.py 827` > `ui/views/data_manager.py 500` > `core/backtest.py 495`（v6.17 新越线）>
  `core/database.py 435` > `ui/dialogs/bulk_download.py 416`。
- **验收脚本不参与"业务文件瘦身"**：`tests/smoke_chart.py 999`、`tests/smoke_pages_overlay.py 622`。
- ⚠ **`backtest.py 1570` 是 §9-L 首选拆分对象**；`trading_desk.py`（898）与 `review.py`（1067）
  同样偏大 —— 新能力一律落到 `ui/widgets/*` 或 `data/*_store`，**不许在页面里长肉**（§10-12）。
  `trading_desk.py` 若再动，优先把 provider 计算搬进 `adaptive_axis` 辅助函数或 `chart_layers`。
- （v6.6–v6.15 的**逐版行数涨落记录已移除**：它们大多指向已删除的 `market.py`，且正是本次
  "行数漂移"的主要来源；历史里程碑仍完整保留在 §8 changelog。
  另注：`adaptive_axis.py` 新建即 348、现 396，**尚未越 400 线，故按新口径不标数字**。）

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
- [x] **用户标注（v6.10 · §7-B3 P6 · 吸收并升级原 §7-A1）**：趋势线 / 水平线 / 垂直线，
  工具下拉 + 「➕ 添加标注」+「🧽 删除选中」+「🗑️ 清空本标的标注」(二次确认) + `Delete`/`Esc` 快捷键。
  **持久化**到 `(标的, 周期)`（`~/.jian_data/annotations.json`，原子写）；
  **逐个独立删除**；坐标存**日期**而非 bar 序号 ⇒ 数据窗口变化也不漂移；
  拖动松手自动保存（`sigRegionChangeFinished` / `sigPositionChangeFinished`）。
  渲染/交互全部在 `ui/widgets/annotation_layer.py`，页面只做接线。
  ⚠ **不做**（P8 再收）：斐波那契 / 文字标注（模型与存储已支持 `kind='text'`，只差交互入口）。
- [x] **自定义公式叠加（v6.6–v6.8 · §7-B3 P4 + P5）**：`🧮 自定义公式` 区
  （开关 + 「编辑公式…」+ 状态回执）；编辑器复用 `FunctionSegments`（多段共享变量池）+ 参数框，
  自检口径与回测页**同源**（`probe_missing_parameters`）。**内置指标与用户公式统一图层协议**：
  MA/BOLL 与公式都产出 `DrawData` → 同一个 `OverlayPainter`，对比度守卫/线型/空值处理自动一致。
  **每段可选目标窗格**（v6.8）：主图 或 副图 1/2/3（按需创建、独立 y 轴、x 联动、跨 0 给零轴）——
  副图量级函数（MACD/RSI/量能）不再把 K 线压扁；若误选主图，面板会提示改用副图
  （判据 `chart_layers.scale_mismatch_hint`）。**各段共用同一个变量池**（引擎一次求值、按段归位）。
  公式在某标的算不出来时**不打断整页渲染**，只在面板给 ❌ 提示。
- [x] **公式资产化 + 与回测页互送（v6.11 · §7-B3 P7）**：「💾 存为配方…」把「函数段 + 参数 +
  **每段目标窗格**」存进配方库（`~/.jian_data/formula_library.json`）；「📚 配方库…」载入/改名/删除；
  「📤 送去做回测」把函数与参数交回测页（**目标不随行**，回测没有副图）。
  **开机自动恢复上次用过的配方** ⇒ 彻底解决"公式重启就丢"。配方与策略分家：
  配方只有公式；策略 = 配方 + 条件 + 风控 + 区间（详见 `data/formula_store.py` 头注释）。
- [x] **行情工作台（v6.12 · §7-B3 P8「换壳不换芯」）**：新页 `ui/views/trading_desk.py`
  （**旧 `market.py` 已删除**）—— 左侧控制台（自选股 / 周期 / 主图叠加 / 附图 / 标注工具）
  + 右侧图表区。页面**不新增任何绘图逻辑**：窗格走 `ChartHost`、叠层走 `OverlayPainter`、
  内置指标走 `chart_layers`、标注走 `AnnotationLayer`、量能/MACD 走 `indicator_panes`。
  新增能力：**自选股**（`data/watchlist_store.py`）、**周期 日·周·月**（`core/utils.resample_ohlcv`
  就地聚合）、**画线 5 类**（斐波那契 7 档、文字标注）。
  **v6.13 收尾**：**复权 前复权/不复权**（不复权数据单独一个分区 `kline_daily_raw`；
  复权口径的规范化入口 = `sync_service.zone_for_adjust`，页面禁止自己拼分区名）、
  **文字标注可拖动**（pyqtgraph 覆写 `mouseMoveEvent` 不调父类 ⇒ `ItemIsMovable` 无效，
  必须自实现 `mousePress/Drag`，且**松手才落盘**）。
  ⚠ 待做仅剩：分钟周期（§7 D3 远期）。
- [x] **跨窗格十字光标（v6.9 · §9-T）**：行情页改为 `ChartHost(crosshair=True)` ——
  竖线在主图 / 量能 / MACD / 公式副图之间**同步贯穿**，横线只留在悬停窗格，顶部给数值回执。
  该能力本是 P2 产物，此前**只是没接线**（用户看不到）；重渲染走 `clear_pane_content()`，
  **不会误删光标**（`PlotItem.clear()` 会 —— 这正是当初单列该方法的原因）。

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
- [x] **公式资产化 + 互送（v6.11 · §7-B3 P7）**：① 函数卡右侧一排
  「📚 配方库 / 💾 存为配方 / 📤 送到行情页」；② 收到的外来函数**自动检测**（不是静默塞进去）；
  ③ 互送后自动切页；④ 「📤 送到行情页」让用户把刚调好的函数**放到真实 K 线上看它长什么样**
  （回测页只有哑行情，看不到形态 —— 这是互送最实际的价值）。
- [x] **回测结果导出（v5.14/v5.15 · §7-A2 半程）**：结果区「导出结果 ▾」下拉菜单 =
  `📄 导出 CSV 明细…`（表头参数块 + 逐笔明细，**无净值行**，utf-8-sig，溯源用）+
  `🖼 导出结果图 PNG…`（`ui/widgets/backtest_report.py`：KPI + 净值曲线 + 离场饼图 +
  参数简表，1120×660）。均基于 `_last_meta`（发起回测瞬间定格的配置快照）。
  **不做删除 / 不做存档**，详见 §7-A2 与 §7-A4。
- [x] **公式绘图落地（v6.4 · §7-B3 P1+P3）**：`execute_programs_with_draws` 同一次求值产出
  `(变量, [DrawData])`；回测页 K 线页签叠加公式线 / STICKLINE 状态柱 / DRAWICON 图标，
  带「显示公式叠层」开关与 y 自适应；渲染唯一走 `ui/widgets/draw_overlay.py`。
  对比度守卫保证黑底公式（COLORWHITE/COLORYELLOW）在白底上依然可见。
  验收：`tests/smoke_chart.py` + `tests/smoke_pages_overlay.py`（两脚本断言数随阶段递增，见 §11.7 自检清单）。
- [x] **回测成交真实性（§7-B5 P0 · v6.17 立项 / v6.18 落地）**：信号在 K 线**收盘后**判定，**成交时点三档可选** ——
  `次日开盘`（默认，最保守，与改动前一致）/ `当日收盘`（语义 = 尾盘看盘下单）/ `触发式条件单`
  （次日先突破信号根最高价 **+N 跳** 才买入、跌破最低价 **−N 跳** 才卖出，**未触达则本次信号作废**）。
  **T+1 硬约束默认开启且不提供关闭开关**（用户拍板"真实优先"）：出场根必须晚于入场根 ⇒
  ① 买入当根击穿止损 / 触及止盈 → **当日不得成交，顺延到最早可卖根的开盘价**（跳空低开就承受跳空）；
  ② `max_bars=1` 退化为"次日收盘离场"；③ 末根不建仓（杜绝"买完当天强平"的假交易）；
  ④ **同根不重建仓**（同一**成交根**卖出后不再按原价买回，掐掉"持续为真的条件每根空转"）。
  口径贯通：策略签名（默认口径归并为空串 ⇒ 旧存档不被误判）/ 旧存档兼容 / `_last_meta` /
  CSV 表头与逐笔「（T+1 顺延）」标记 / PNG 报告图；页面入口 = 「🎯 成交模型」参数行。

### 6.4 基础设施与演进
- [x] SQLite 迁移链：旧双时间表自动备份重建（COALESCE 归并）；v1.2 增量列走 `ALTER TABLE` 零损加列。
- [x] 纯 Pandas 指标引擎（零编译依赖，兼容 Py3.14+）。
- [x] Parquet 数据湖基础原语（读写/探针/最新日期探测）。
- [x] **数据湖治理（v5.8 / §7-A3）**：补 `delete_data` / `clear_zone` / `list_zone` /
  `inventory`（行数与日期范围一律只读 parquet footer 的列统计，**不把数据读进内存**，
  全市场 5000+ 文件也能秒级清点）/ `zone_stats`。
- [x] **行情同步唯一门面（v5.8）**：`data/sync_service.py` 的 `MarketSyncService`。
  增量 = 本地末日+1 天起拉 → concat → 按 `date` 去重(keep=last，**新数据优先=顺带修正前复权漂移**)
  → 排序落盘；「强制全量重拉」入口必须保留（增量修不回历史价格）。
  `ThrottlePolicy` 温柔抓取：间隔+随机抖动 / 指数退避重试 / 连续失败熔断 / 跳过已最新(断点续传)。
- [x] **代码物理拆分纪律**（v5.13 复核）：
  - [x] **弹窗全独立、`DataEngine` 单一门面**；
  - [x] **UI 直连底层已收敛**（§9-H）：行情页（当为 `market.py`，现 `trading_desk.py`）/ `backtest.py` 均走 `SingleSyncWorker`，
    两处 `engine.db.search_symbol` 已改走 `engine.search_symbol`。
  - [x] **线程收口完成（v5.13 · §9-O2）**：`ui/workers.py` 是全 app 唯一 QThread 定义处，
    唯一例外是 core 层的 `UpdateCheckerThread`（非 UI 职责）。
  - [x] **图表样式 4 合 1（v5.13 · §9-O7）**：统一到 `ui/widgets/chart_style.py`。
  - [x] **复合控件样式收口（v6.9 · §10-9）**：`ui/widgets/custom_widgets.py` 新增
    `combo_qss()` / `date_edit_qss()` 两个生成器 + 8 个具名常量，业务页面**零就地 QSS**；
    顺带治好"只写 `::drop-down` 不给 `::down-arrow` ⇒ 下拉箭头整个消失"的长期隐形 Bug。
  - [ ] **大文件拆分未动**：`backtest.py 1570`（**全仓最大，§9-L 首选**）/ `review.py 1067` / `trading_desk.py 898`（§9-L，第三梯队）。

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
  ✅ **v6.9 补齐遗漏项**：新增 `NoWheelDateTimeEdit`；复盘页孤儿补录日期（原裸 `QDateEdit`）、
  手工录入弹窗的交易/开仓时间（原裸 `QDateTimeEdit`）与 5 个数值框（原裸 `QSpinBox/QDoubleSpinBox`）
  全部换入 NoWheel 族 —— 此前悬停滚轮会误改关键参数。
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
- **A1 [x] 行情涂鸦板持久化（✅ v6.10 由 §7-B3 的 P6 吸收并升级完成）**：
  旧的"内存趋势线"（`drawn_lines` 随重渲染清空、无落盘）已被
  `data/annotations.py` + `ui/widgets/annotation_layer.py` 取代 —— 三类标注、
  按 `(标的, 周期)` 持久化、**逐个独立删除**、坐标按日期锚定（不漂移）。
  复盘页复用（回放图上标注）属 P8 之后的事：API 已按 `(symbol, period, id)` 解耦，**只换调用方**。
- **A2 [~] 回测结果导出（半程）** `ui/views/backtest.py`：
  ✅ **v5.14 已做"导出当前结果"**（§6.3）：CSV 含表头参数块 + 逐笔明细 + 净值曲线。
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

### B 类 · 市场回测扩展（规格 §9 已定稿，占位就绪待填充）
- **B1 [ ] M2 全市场单日横截面筛选**：`backtest_module.py` `page_scan` 现为 `_ComingSoonPage`。
  依赖 A3（预下载全市场湖）。需 `scan_cache` zone（公式哈希+日期维中间结果缓存）。
- **B2 [ ] M3 全市场广度家数折线 + 指数双轴叠加**：`page_breadth` 占位；指数日线能力已就绪
  （阶段C：`fetch_index_daily`/`index_daily`），缺广度统计实现与双轴 UI。
- **B3 [ ] ⭐最高优先级（P0 · v6.0 用户定稿）公式统一绘图** ——
  完整主案见下方「§7-B3 主案规格」，含 引擎 IR → 统一渲染器 → 回测页接入 三步。
  现状（待消除）：`program.py` 把 `STICKLINE/DRAWICON/颜色线型` 一律 SKIP，
  导致用户的 QSD/GLX/状态柱"算得出、没得画"——K线页签与导出 PNG 均看不到。
- **B4 [ ] P1c 回测进阶（部分）**：结果长期入库已有雏形(A2)，缺 复用 `TradeAnalyzer` 绩效维度
  与每回合明细的持久化侧写。
- **B5 [~] ⭐回测成交真实性（v6.17 立项 · 用户拍板）**：**P0 待做** = 成交时点三档
  （次日开盘 / **当日收盘** / **触发式条件单**）+ **T+1 硬约束**（修掉"当日买当日卖"的
  低估风险缺陷）；**P1/P2 挂起** = 账户+容量+成本 / 盘中即时成交（分钟级）。
  完整规格、实测证据与验收断言见 **§7-B5 主案**。用户口径：**宁可变难看，也要真**。

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

### §7-B3 主案规格：图表架构总纲（v6.11：**P0–P7 已全部落地** · 最高优先级 P0）

> **定位一句话**：把"公式 / 指标 / 画线怎么显示"从**散落在各 UI 文件的手工绘图**，
> 收成一条管线：**引擎产出统一"绘图指令"（IR）→ 图表宿主安排窗格 → 唯一渲染器解释**。
> 终极形态 = **通达信级行情工作台**：主图叠加用户函数（像 MA/BOLL）、副图显示用户指标、
> 画线工具按标的持久化并可**逐个独立删除**、行情页调好的函数**一键送去做回测**。
> ⚠ v6.1 是把 v6.0 的"公式叠层单点方案"**升级为骨架**：补上原规格完全没有的
> **图表宿主（多窗格）** 与 **用户标注对象** 两根柱子，并厘清"两条管线"。
> **进度（v6.15）**：**P0–P8 全部 ✅** + **§7-B4 坐标轴自适应 ✅**（3 处静态 ticks 收敛完成，
> 全 app 只剩 `adaptive_axis.py` 一处算刻度/量程）。⚠ **`ui/views/` 不再改结构**：
> 新需求一律落到 `ui/widgets/*` 与 `data/*_store`（`trading_desk.py` 已 847 行，偏大）。
> 下一批候选（待用户指定）：§9-L 大文件拆分（`backtest.py 1568`）、分钟周期（§7 D3）、
> §7-B1/B2（M2 全市场筛选 / M3 广度统计）。

#### A. 为什么必须引擎级（v6.0 结论，不变）
- 绘图语句依赖**同一共享变量池**（STATE_BLUE/DYN_INDEX/最终优选…），只能在
  `EvalContext` 求值现场拿到真值；UI 层事后重读文本 = 二次解析 + 语义分裂。
- 引擎不画图，只产出**数据**；UI 不解析函数，只**消费 IR**（职责与 §10-3 一致）。

#### B. 四层架构（v6.1 · 铁律见 §10-12）

| 层 | 文件 | 职责 | 阶段 |
|---|---|---|---|
| ① 引擎 IR 层 | ✅ `core/formula/draw.py`（124 行） | 4 态语句分类 + `COLOR_TABLE` + `DrawSpec`/`DrawData`；只出数据，零 Qt | **P1 已完成** |
| ② 图表宿主层 | ✅ `ui/widgets/chart_pane.py`(76) + `chart_host.py`(262) | pane = 一个 PlotItem + 叠层/标注容器；host 管 主图 + N 副图 + **x 轴联动** + 日期轴 + 十字光标 | **P0 / P2 已完成** |
| ③ 渲染器层 | ✅ `ui/widgets/draw_overlay.py`(210) | **全 app 唯一** `OverlayPainter(pane, bars_x).render(draws)`：IR → pyqtgraph 图元 | **P3 已完成** |
| ④ 标注对象层 | ✅ `data/annotations.py`(255) + `ui/widgets/annotation_layer.py`(222) | 用户手绘对象模型（含 id）+ 持久化 CRUD + 选中/**逐个独立删除** | **P6 已完成（v6.10）** |

#### C. 两条管线（**最重要的一条纪律，防"混为一谈"**）

| | 管线 A · 公式叠层 | 管线 B · 用户标注 |
|---|---|---|
| 来源 | 用户函数求值出的 `DrawData` | 用户鼠标手绘 |
| 生命周期 | **随数据/参数重算，不持久** | **持久化到 `(标的, 周期)`** |
| 例子 | QSD 线 / STICKLINE 状态柱 / DRAWICON | 趋势线 / 水平线 / 斐波那契 / 文字 |
| 删除 | 关掉公式 / 换函数 | **逐个独立删除**（对象列表 / 右键） |
| 落点 | ①→②→③ | ④ |

> 二者**只共用「图表宿主」这块舞台**；禁止塞进同一个数据结构、禁止共用同一套生命周期。

#### D. 用户决策记录（2026-09-10 拍板 · 不得擅自回退）
1. **`ChartPane` 抽象（P0）插在 M2 之前** —— 避免渲染器一落地就写死成单图（否则 P4/P5 必返工）。
2. **首个落地验证场 = 回测页**（P3，改动面最小）；**行情页 = P4** 再上。
3. **标注存储先 JSON**（原子写 tmp+os.replace，与 `preferences`/`strategy_store` 同源）；
   但 `data/annotations.py` 的**对外 API 必须与存储实现解耦**
   （`load/list/upsert/delete` 按 `(symbol, period, id)` 键）——将来数据量大时**只换实现、不动调用方**（迁 DB 附表）。
4. **内置指标（`core/indicators.py` 的 MA/BOLL/MACD/KDJ）与用户公式在渲染层统一为一套"图层协议"**
   （都产出 `Series`/`DrawData` → 同一 pane 渲染）："像 MA 一样显示用户函数"是架构自然结果，
   **不得退化成特例硬编码**。

#### E. 阶段路线图 P0–P8（每阶段完成即回写本文档状态）

| 阶段 | 内容 | 产出 | 依赖 |
|---|---|---|---|
| **P0** ✅ | 图表宿主最小抽象 `ChartPane`（v6.2 已完成） | `ui/widgets/chart_pane.py`(76) | — |
| **P1** ✅ | 引擎 IR 契约 + 求值（= 原 M0+M1，**设计不变**；v6.2 已完成） | `core/formula/draw.py`(124) + `execute_programs_with_draws`；57 项断言全过 | — |
| **P2** ✅ | 宿主完整版：主图+N副图、x 联动、日期轴、十字光标、pane 增删/高度（v6.3 已完成） | `ui/widgets/chart_host.py`(262) | P0 |
| **P3** ✅ | 渲染器 + **回测页 K线页签**接入（叠层开关 + y 自适应）（v6.4 已完成） | `ui/widgets/draw_overlay.py`(210) + `backtest.py` 接线 | P1,P0 |
| **P4** ✅ | **行情页公式叠层**：函数段编辑器复用 + 参数 + 主图叠加；内置/用户指标统一图层（v6.6 已完成；页面 v6.12 起为 `trading_desk.py`） | `ui/dialogs/formula_overlay.py` + `ui/views/trading_desk.py` | P2,P3 |
| **P5** ✅ | **副图（附图指标）**：✅ 用户公式**每段可选**主图 / 副图 1/2/3（v6.8：多副图按需创建、独立 y 轴、x 联动）；⚠ 量柱/MACD 仍用原生 BarGraphItem（P5 明确保留的例外，P8 统一） | 基于 P2 | P2 |
| **P6** ✅ | **标注对象 + 持久化 + 独立删除**（吸收并升级 §7-A1；v6.10 已完成） | `data/annotations.py`(255)、`annotation_layer.py`(222)；趋势线/水平线/垂直线 + 逐个删除 | P0 |
| **P7** ✅ | **函数配置资产化 + 行情↔回测互送**（v6.11 已完成） | `data/formula_store.py`(213，零 Qt 配方库) + `ui/widgets/formula_library.py`(171 配方库窗口) + `main_window` 互送传话筒 | P4 |
| **P8** ✅ | **行情页整体重做**（v6.12 换壳 + 自选股 + 周期 日/周/月 + 画线 5 类；**v6.13 收尾：复权切换（`kline_daily_raw` 分区）+ 文字标注拖动**；旧 `market.py` 已删）。⚠ 分钟周期仍属 §7 D3 远期（`kline_min` 仅预留） | `ui/views/trading_desk.py`(898) + `data/watchlist_store.py` + `core/utils.resample_ohlcv` + `sync_service.zone_for_adjust` | P4,P5,P6,P7 |

> **P8 纪律**：那是"换壳不换芯" —— P0–P7 已把能力做成独立组件；**必须新建文件**，
> 禁止在已有的大页面上继续堆：`backtest.py 1570` / `trading_desk.py 898` / `review.py 1067`（§9-L 体积债）。

**1) 语句分类（`core/formula/program.py` 改造）**
`_classify` 由 3 态扩为 **4 态**（ASSIGN / OUTPUT / **DRAW** / SKIP→移除）：
- `DRAW` = 语句以"调用式"开头：一期 **STICKLINE / DRAWICON**；其余已知 TDX 绘图函数见下条。
- OUTPUT 语句（`NAME: expr`）逗号后缀解析出绘制属性 → 得到 **line 输出**：
  `QSD: DYN_INDEX, COLORWHITE, LINETHICK2;` = kind=line + color=白 + thickness=2；
  `最终优选: ..., NODRAW, COLORRED;` = kind=hidden（NODRAW 只算不画，但变量照常供 Gate 用）。
- **属性尾巴必须先摘掉再解析**（v6.5 · §9-Q-1）：`STICKLINE(...), COLORFF0000;` 是**合法写法**，
  顶层逗号之后是绘制属性。`_split_draw_attrs()` 与 OUTPUT 属性解析**同源**
  （都用括号深度扫描），绝不把整条语句送进 `parse()` —— 这正是让存量函数"突然全废"的元凶。
- **报错边界（v6.5 修订 v6.0 的"未知绘图函数一律报错"）**：
  ① `STICKLINE/DRAWICON` 参数 / 元数错 → **报错**；
  ② 已知但本期不实现的绘图函数（DRAWTEXT/DRAWBAND/DRAWLINE…）+ 尚未收录的调用式语句
     → 登记 `DrawSpec(kind='unsupported')`，**不阻断运行**，由 UI 汇总成
     "⚠ 本期不渲染 N 处: …"（完整文案进 tooltip）；
  ③ 只有**完全不像函数调用**的语句才报错（那才是真语法错误）。
- **零高度 STICKLINE 要画横杠**（v6.5 · §9-Q-3）：`STICKLINE(cond, P, P, w, 0)` 的 TDX 语义是
  "在该价位画一段横杠"，退化成 0 高度矩形会"什么都看不见"；渲染器须走 cosmetic 水平线分支。
- 变量语义零回归：ASSIGN/OUTPUT 产生的变量名照旧进共享池（`execute_programs` 契约不变）。

**2) 契约层（新增 `core/formula/draw.py`，纯计算，零 Qt）**
- `COLOR_TABLE`：通达信颜色名→hex（RED/GREEN/BLUE/YELLOW/WHITE/BLACK/GRAY/LIGRAY…）
  + `COLORRRGGBB` 直通；未知颜色抛友好错。
- `@dataclass DrawSpec`（编译期）：kind∈{line,stick,icon,hidden}、color、thickness、
  style(预留 DOTLINE 等)、各表达式的 AST。
- `@dataclass DrawData`（运行期）：kind、color、x(date/np)、数组
  （line: y；stick: cond×lo×hi×width；icon: cond×pos×icon_id）+ 常量备注。
- 执行 API（**与现有 execute_programs 兼容并存**）：
  - `execute_programs(...)` 保持不变（只出变量，供检测/条件）；
  - 新增 `execute_programs_with_draws(programs, df, params) -> (variables, draws)`
    —— 同一 EvalContext 顺序执行一遍同时产出两者，**不二次求值**；
  - 绘制语句的 cond/price 求值错误与变量同样以 `FormulaProgramError` 抛给 UI 展示。

**3) 渲染层（新增 `ui/widgets/draw_overlay.py`，本软件的"图表叠层唯一窗口"）**
- 对外唯一入口：`OverlayPainter(plot_item, bars_x, draws)` —— bars_x 是宿主已切好的
  x（bar 序号数组），draws 在整段数据轴求值、由宿主按 date_index 切片后喂入，
  防止"画错位/跨窗口漂移"（复用回测页 K线切窗那一套日期→索引映射思路）。
- 内部实现（与 CandlestickItem 同一套 Pokorny 画法：QPicture + 抗锯齿 + 去描边）：
  - line → `pg.PlotDataItem`（color/thickness）；预留 DOTLINE 样式表；
  - stick → 自绘 GraphicsObject（cond 为真处画 lo→hi 竖段，width=1 画细线、
    width>1 画小实体），K线配色纪律（去描边、单色高对比）照旧；
  - icon → `ScatterPlotItem`：`DRAWICON(cond, price, id)` 的 id→符号映射表（一期常用子集），
    未知 id 用默认菱形并 tooltip 提示，不崩溃；
  - 一律走 `chart_style` 的配色/抗锯齿约定，禁就地 inline 样式。
- 宿主只负责三件事：切窗口、喂 x 数组、把 y 范围扩到能盖住叠层（stick/icon 超出K线
  高低价时要纳入 range）。

**4) 消费方接入（首个落地点 = 回测页「🕯 K线买卖点」页签）· ✅ v6.4 已落地**
- ⚠ **入口铁律**：`OverlayPainter` 的宿主参数是 **`ChartPane`**（P0 产物），**不是裸 PlotItem**。
- `_on_data_ready` / `detect_function` 改走 `execute_programs_with_draws`（同一次求值出
  `(变量, draws)`；**检测期**就能报出写错的绘图语句）。
- `_render_kline` **不用 date_index 直接切** —— 它先按日期 `argsort` 得到
  「排序后位置 → 原始行号」映射，再取窗口行号喂 `slice_draws`；这样即使底层 df 未排序，
  叠层也与 K 线**严格同格**（§7-B3 反复强调的"跨窗口漂移"就是这么堵死的）。
- 提供「显示公式叠层」开关（默认开，**只切可见性、不重置缩放**）；
  stack 顺序：K线 → 公式叠层 → 买卖点标记。
- y 自适应：`overlay_extent()` 逐 bar 求叠层最低/最高，并入 `chk_follow` 的视口计算，
  超出 K 线高低价的叠层不会被裁。

**5) 验收 / 冒烟断言（必须，参照历史 §9-N1 风格）**
- 编译期：STICKLINE/DRAWICON 正反宽度、COLOR 名/hex、LINETHICK、NODRAW、未知颜色与
  未知函数各自报友好错；
- 求值期：draws 与变量同一次执行、分批/重复执行结果稳定；空 cond 不产出图形对象；
- 渲染期：离屏构造回测页 → 叠加 QSD/GLX/状态柱后 grab PNG 非空，x 对齐与 K线窗口一致
  （抽样断言若干 bar 的像素色/位置）。
- 回归：`execute_programs` 旧调用方（检测/条件/指数门控）行为不变（同断言）。

**6) 里程碑映射（v6.1 起以 §7-B3E 的 P0–P8 为准）**
- 原 **M0 契约层 + M1 求值层** = 现 **P1**，**设计不变**（`core/formula/draw.py` +
  `program.py` 4 态 + `execute_programs_with_draws`；纯单测、无 UI）。
- 原 **M2 渲染层 + 回测页接入** 拆为：**P0**（先抽 `ChartPane`）→ **P3**（渲染器 + 回测页）。
- 原 **M3 收尾** = P3 完成后的收敛（错误文案 + §11.4 登记 + §7-B3 标 [x]）。
- 原 **M4 远期全图复用** = **P4（行情页）→ P5（副图）→ P6（标注）→ P7（函数资产）→ P8（重做）**。

---

### §7-B4 主案规格：坐标轴自适应（v6.8 立项 · **v6.15 已全部落地 ✅** · 规格保留备查）

> **v6.15 收官结论**：新建 `ui/widgets/adaptive_axis.py`(348)；**3 处静态 ticks 全部收敛**
> （行情主图/副图、复盘 K线回放、复盘资金K线）；回测页两处改为调用公共纯函数
> （`chk_follow` 开关语义保留）；断言 `smoke_chart` 290→**312**（+22）、
> `smoke_pages_overlay` 139→**150**（+11 页面级）。
> 两个原始诉求均验证：**放大到 10 根仍有 ≥2 个刻度**（旧实现只剩 1 个）、
> **纵轴按可视区间重算**（副图不再被全量极值压成一条线）。
> ⚠ 实施中的两个新发现已固化：① `setYRange` 会偷加 padding（§11.5-21）；
> ② 复盘"资金 K 线"的 x 其实是**当月第几日的序数轴**（不是真日期），
> 故公共件增设 `compute_text_ticks` / `texts=` 入口（套 `%m-%d` 反而会说谎）。

> **定位一句话**：让全 App 的图表在**放大/缩小时，横轴刻度、纵轴量程、刻度密度与数字精度**
> 都跟着"用户此刻看到了什么"自动变化 —— 而不是渲染时一次性算好就固定不动。
> 根因与波及面见 §9-S；本节只写"怎么修、按什么顺序修、怎么验收"。

**方案（唯一来源 = 新增 `ui/widgets/adaptive_axis.py`，纯 UI、零业务、零网络）**

| 件 | 职责 |
|---|---|
| `attach_date_axis(pane, dates, *, target_ticks=8)` | 监听 `view_box.sigXRangeChanged`；每次按**可视 bar 区间**重算底部轴 ticks：按 `axis.width()` 估算能放几个刻度 → 自适应格式（跨年 `%Y-%m` / 同年 `%m-%d` / 将来日内 `%m-%d %H:%M`）。幂等、可重复 attach、可 detach。 |
| `follow_y(pane, provider, *, pad=0.06)` | 监听同一信号；按**可视窗口内**的数据极值重算 y 范围（= 把回测页「价格轴跟随可视区间」推广到所有窗格）。`provider(i0, i1)` 由页面给"该窗格在可视 bar 区间内的 (lo, hi)"——因为每个窗格的数据形状不同（K线用 high/low、公式用叠层 extent）。 |
| `attach_all(host, dates_by_pane, providers_by_pane)` | 便捷入口：给 ChartHost 的每个窗格一次性挂上。⚠ x 联动的窗格**只需最下者算 ticks**（其余横轴不显示值），但 **y 跟随必须逐窗格**。 |

**参考实现 = `backtest.py:1397-1475`**（`_refresh_kline_view` 的"重算 ticks + 自适应格式 +
按可视 bar 重算 y"）。**别重新发明，把它抽出来**。

**实施步骤（严格按序，每步有断言）**：
1. **抽公共件** `adaptive_axis.py`（纯函数 + 信号挂接；离屏可测）。
2. **回测页收敛**：`_refresh_kline_view` / `_refresh_equity_view` 的 ticks 逻辑改调公共件
   （**行为不变**，现有断言保护；「价格轴跟随可视区间」开关语义保留）。
3. **行情页接入**（这一步直接治好用户截图的两个问题）：主图 + vol/macd/公式副图全部
   `attach_date_axis` + `follow_y`。
4. **复盘页接入**：K 线回放图、资金 K 线图。
5. **验收断言**（进 `tests/smoke_chart.py`）✅ 已落地：离屏构造 → `setXRange` 到一个窄窗口 → 断言
   ① 底部轴 ticks **全部落在可视范围内**且格式正确（不再出现"A"）；
   ② 每个窗格的 y 范围 == 该窗格**可视数据极值** ± padding（副图不再压成一条线）；
   ③ `grab()` 像素随缩放变化（轴真的变了，不是嘴上说）。
6. **回写文档**：§11.4 登记"给图表加自适应坐标轴 = `adaptive_axis.py` 一处"；§11.5-16 落坑。

**边界（明确不修）**：
- 类别轴（策略对比图的"策略名"、年度复盘的"策略名"）**静态是合理的**，不改造。
- 回测页「价格轴跟随可视区间」的**开关语义保留**（用户可以关）。
- ChartHost 的十字光标与此**正交**，互不影响。
- 若将来做日内/分钟线（`kline_min` zone），只需在 `attach_date_axis` 加一种格式分支，
  **不改任何页面**（这正是抽公共件的意义）。

---

### §7-B5 主案规格：回测成交真实性（v6.17 立项 · **P0 待做 / P1·P2 挂起**）

> **定位一句话**：把"信号成立 → 次日开盘无脑成交"这个**唯一且偏乐观**的成交口径，升级为
> 「**可选成交时点 + T+1 硬约束 + 条件单触发**」三件套，让回测数字贴近真实操作。
> 用户 2026-09-15 原话："这个软件我是真的用来炒股和期货复盘的。**回测偏差太大就是完全不能用**。"
> 因此本主案的取舍原则是：**宁可变难看，也要真**（明确拒绝"允许当日平仓"之类的美化开关）。

#### A. 用户拍板记录（2026-09-15 · 不得擅自回退）
1. **T+1 修正：默认开启，且不提供旧口径兼容开关**（"数字难看无所谓，最重要的是贴合真实"）。
2. **「当日收盘」成交档：要做**（语义 = 尾盘看盘下单）。
3. **触发式委托（条件单）：要做**，按本主案 C3 规格（前高突破 / 前低跌破）。
4. **P1（账户 + 容量 + 成本）与 P2（盘中即时成交）：搁置** —— 依赖"账户模型 / 分钟数据"等
   尚不存在的基础设施，现阶段性价比低；**完整设计保留在本文 F 节**，将来要做直接从那里接。

#### B. 现状实测（立项前用合成 K 线探针实测 · 7 组实验；探针跑完即删）
| 编号 | 事实 | 证据 |
|---|---|---|
| **F1** | 信号 T 日**收盘**成立 → **T+1 开盘价**成交（买、卖同一规则） | 第 0 根出买入信号 → 成交在次日开盘 |
| **F2** | 引擎**没有资金、没有仓位**：`equity` 是"1 股"的复利因子，`shares` 恒为 `1.0` | `BacktestTrade.shares = 1.0`；`ret = pnl / entry_price` |
| **F3** | ⚠ **T+1 违规**：`stop_loss` / `take_profit` / `max_bars` 均可在**买入当天**离场 | 三组实验均输出"买入 01-03 → 卖出 01-03" |
| **F4** | 成本只有双边佣金（默认万三）：无印花税 / 过户费 / 滑点 / 最低 5 元 | `core/backtest.py` 的 `settle()` 与末根强平处 |
| **F5** | 数据湖只有 OHLCV（`akshare_feed.OHLCV_COLUMNS`），**没有成交额** ⇒ 真 VWAP 算不出来 | 想加"当日均价"档必须先扩抓取（暂不做） |

> ⚠ **F3 的方向是危险的：它低估风险。** 现实中"买入当天跌穿止损"你卖不掉，只能 T+1 卖，
> 而那时往往跳空低开。所以**带止损的策略，现在跑出来的回撤比真实情况好看**。

#### C. P0 定稿规格（本轮实施 · 零新增数据依赖）

**C1 成交时点模型（三档 · UI 下拉 · 默认 `next_open` 保兼容）**

| 档位 | 语义 | 成交价 | 备注 |
|---|---|---|---|
| `next_open`（默认） | 信号日收盘成立 → 次日开盘成交 | `open[i+1]` | **现状行为，逐位不变** |
| `close` | 信号日收盘成立 → **当日收盘**成交 | `close[i]` | 尾盘下单；不是未来函数（收盘时收盘价可见） |
| `trigger`（条件单） | 次日**触达触发价**才成交，未触达则本次信号作废 | 见 C3 | 只用日线数据，最贴近"挂条件单"的真实习惯 |

**C2 T+1 硬约束（对所有档位生效，优先级最高）**
- 通用规则：**出场 K 线必须严格晚于入场 K 线**（`exit_bar > entry_idx`）。
- 两种场景**分开处理**（本轮必须定义清楚的一点）：
  - **正常场景**（`i > entry_idx`）：盘中触达风控线 → **按线价成交**（现状算法，不改）；
  - **进场当根触达**（`i == entry_idx`，T+1 禁止卖出）→ 该次离场**顺延到 `entry_idx + 1` 根**，
    按**该根开盘价**成交（口径 = "最早可卖的时点"），`exit_reason` 保留原触发原因，
    明细另标「T+1 顺延」。
    · **为什么不用"忽略这次触发"**：那等于假设"今天卖不掉，明天价格回来了就当没跌过"——**那是美化**。
      现实中 T+1 一开盘你就得处理它。
- 连带定义（写进文档，防后人当 Bug 改回去）：
  - `max_bars = N` 在 T+1 下的最早离场根 = `entry_idx + 1`（`N=1` 退化为"次日收盘离场"）；
  - `close` 档入场时，**同一根的卖出信号不评估**（同一时刻既买又卖自相矛盾），从下一根起正常评估；
  - **末根不建仓**（保持现状），避免"买完立刻强平"的假交易；
  - **同根不重建仓**（v6.17 用户追加拍板，与 T+1 配套）：某一根"**成交过一笔离场**"，
    则该根**不再建仓**。理由：同一根 K 线同时命中买卖条件时，原行为会退化成
    "在次日开盘卖出、又在**同一开盘价**买回" —— 白付两次佣金而持仓毫无变化；
    若买卖条件里有"持续为真"的（如 `C > MA(C,20)` 同时出现在两侧），会**每根空转**
    并把结果严重低估。判据以**成交根**为准（不是"评估根"），三种成交时点一视同仁。

**C3 触发式委托（`trigger` 档）**
- 触发价：买入 `high[信号日] + tick × 0.01`；卖出 `low[信号日] − tick × 0.01`
  （`tick` 默认 1，A股 1 跳 = 0.01 元）。
- 成交价：**触达即按触发价**；若次日**开盘已越过**触发价 → 按**开盘价**成交
  （**与风控离场器同一套跳空处理**，禁止另起一套 —— §9-O7 教训）。
- 未触达：**本次信号作废**（默认口径；"顺延 N 根"列为后续可选，本轮不做，保持参数面简洁）。
- 卖出侧同理：次日跌破 `low[信号日] − tick` 才卖；未跌破 → 信号作废、继续持有。
- **末根不建仓**（同 C2）。

**C4 与风控离场器的关系（唯一口径）**
- 风控已有的"盘中触发 + 线价成交 + 跳空按开盘"是**对的**，本轮**不动其算法**，
  只补 T+1 闸门（C2）；
- 触发式委托的成交判定必须**复用同一套规则**；若实现时发现要复制代码，**先抽公共函数**。

**C5 验收断言（必须新增，否则不许合并）**
1. 三档成交时点各自落在正确的 K 线上（`next_open` → `open[i+1]`；`close` → `close[i]`）；
2. **T+1（核心）**：进场当根触达 `stop_loss` / `take_profit` → **不得当日离场**，
   必须在 `entry_idx + 1` **开盘价**成交且 `exit_reason` 保留；
   负向对照：临时关掉闸门 → 必须复现 §7-B5-B 的 F3 当日平仓（证明断言真的在测这件事）；
3. `max_bars = 1` 在 T+1 下等价于"次日收盘离场"；
4. 触发式：触达 → 按触发价；**开盘跳空越过 → 按开盘价**；未触达 → **零成交且信号作废**；
5. `close` 档下，入场当根的卖出信号被跳过（不产生当日平仓）；
6. **回归**：`next_open` + 风控全关 + 无同日冲突的样本 → 结果**逐位不变**
   （老策略数字不该因本轮改动而漂）；
7. 参数进 `_signature`：成交时点 / `tick` 不同 → 视为不同策略（防"不同口径互相污染对比"）；
8. **同根不重建仓**：同一根同时出现卖出与买入信号时 —— 离场照常，**该根不得重建仓**；
   负向对照：同一根**只有**买入信号（无卖出）时仍须正常建仓（证明不是"把建仓一并掐掉"）。

#### D. 影响面清单（动代码前先看这 5 条）
1. **`_signature`**（`ui/views/backtest.py`）必须计入新参数，否则策略对比与 `find_same` 会串档；
2. **策略存档兼容**：旧档 payload 无新字段 → 按 `next_open` + `tick=1` 读出（等价旧行为）；
3. **`_last_meta` / CSV / PNG 报告**：必须把"成交时点 + T+1 生效"写进参数块，
   否则导出报告**不可复现**（v5.14 的溯源义务）；
4. **UI**：回测页新增「成交模型」参数行（下拉 + tick 数值框）；控件一律走
   `custom_widgets` 的 NoWheel 族与具名 QSS（§6.6-U2 / §10-9）；
5. **冒烟**：两个 `tests/smoke_*.py` 都要加断言；
   ⚠ **任何影响 `BacktestEngine` 行为的改动，都必须拿 `samples/实例函数.txt` 端到端复跑**
   （§9-Q-4 事故教训：用户存量配置不能被打断）。

#### E. 实施步骤（每步独立可验收 · 逐步推进）
| 步 | 内容 | 产出 | 需用户参与 |
|---|---|---|---|
| **0** | **本文档**：拍板记录 + 现状实测 + P0 规格 + P1/P2 挂起设计 | 本节 §7-B5 | ✅ 确认口径 |
| **1** | **引擎核心**：`core/backtest.py` 落 C1/C2/C3（纯计算层，零 UI） | 三档成交时点 + T+1 闸门 + 触发式委托 + `run(...)` 新参数 | — |
| **2** | **口径连通**：`_signature` / 存档兼容 / `_last_meta` / CSV / PNG | 新参数全链路可溯源 | — |
| **3** | **UI**：回测页「成交模型」参数行 + tooltip 说人话 + 口径自检提示 | 页面上可切换并看到差异 | — |
| **4** | **验收**：两个冒烟脚本加断言 + `实例函数.txt` 端到端 + 主窗口离屏构造 | 全绿 | — |
| **5** | **收尾**：回写 §6.3 / §8 / §11.4 / §11.6 / §11.7 + §4 行数（若越 400 线） | 文档与磁盘一致 | ✅ 手动实测手感 |

> **【用户指引要求 · v6.17 用户实测反馈追加】** 这一行**必须有教学**，否则等于没做：
> · 下拉文案 = `FILL_MODE_LABELS`（人话，不含术语）；**行内常显说明** = `fill_mode_oneliner`
>   （把术语换算成"元"，并讲清"没碰到会怎样 = 不买也不卖"）；
> · **教学弹窗** = `ui/dialogs/fill_model_help.py`（📖 三档怎么选？用**一套固定价格数字**
>   三档对照 + T+1 大白话）；参数只在第三档可见（其余隐藏，不给看不懂的常驻项）；
> · **术语（跳 / 当根 / K线 / 条件单）只允许出现在 tooltip 与弹窗里当补充**。
> · 纪律已固化：**§10-10 追加条款** + **§11.5-22**；文案可懂性有可测代理断言（见 E 表步骤 4）。

> **进度（2026-09-15）**：**步骤 1 ✅ 已完成** —— `core/backtest.py` 315→**448** 行（已按 §4 新口径
> 登记）。新增 `FILL_*`/`FILL_MODE_LABELS`/`TICK_SIZE`/`normalize_fill`/`fill_summary`/`T1_SUMMARY`；
> `run(...)` 与 `_run_on_signals(...)` 增 `fill_mode`/`trigger_tick`（默认 `next_open`/`1`）；
> `BacktestTrade` 增 `deferred_t1`、`BacktestResult` 增 `fill_mode`/`trigger_tick`。
> **验收：一次性探针 34 项全过**（三档时点 / T+1 顺延含**非空对照** / max_bars 顺延 / 触发式三态 /
> close 档同根信号跳过 / **借 `git show HEAD:core/backtest.py` 载入改动前引擎做 40+40 组随机样本
> 逐位对比**：风控全关 **0 组非预期差异**、风控全开差异**只**来自 T+1 顺延）；
> 项目自带冒烟 `smoke_chart` **312** + `smoke_pages_overlay` **150** 全过 + 全仓 compileall 通过。
> ⚠ 探针按仓库纪律已删除，其断言清单 = 上文 C5，**步骤 4 需正式移植进 `tests/smoke_chart.py`**
> （移植时**不要**照抄 `git show` 那部分 —— 提交后 HEAD 会变，改为固化期望值或跳过）。
> **下一步 = 步骤 2（口径连通）**。
>
> **进度（2026-09-15 · 第二/三步）**：**步骤 2 + 3 ✅ 已完成**（二者耦合，合并实施 ——
> 签名/存档/导出都要取 UI 行的值，分开做会留半接线状态）。
> · **引擎追加一条**（用户拍板）：**同根不重建仓** —— 判据是"**成交根**重合"（不是评估根）；
>   效果 = 同一根 K 线卖出后不再在原价买回，掐掉"持续为真的条件每根空转、白付两次佣金"。
> · **UI**：回测页新增「🎯 成交模型」参数行（成交时点三档下拉 + 触发跳数 + 常显的
>   「🔒 T+1：买入当根不可卖出」），跳数仅在触发式下可用（`NoWheel` 族 + `COMBO_QSS`，
>   §6.6-U2/§10-9）。
> · **口径连通**：`strategy_store._fill_signature`（**默认口径归并为空串** ⇒ 旧存档签名不变，
>   不会被误判成另一套策略）；策略 payload 增 `fill`；`_on_strategy_selected` 还原（旧档回落
>   默认）；`_pending_fill` + `_last_meta["fill"]` 定格；CSV 表头增「成交模型 + T+1」两行、
>   逐笔「离场原因」列对顺延单追加「（T+1 顺延）」；PNG 报告图参数行同源。
> · **验收**：一次性探针 **22 项全过**（签名隔离 4 / UI 往返与存档兼容 8 / CSV 口径头·T+1 标记·
>   8 列结构不变 7 / PNG 1120×660 落盘 2 / 用户真实库未被写 1）；项目冒烟
>   `smoke_chart` **312** + `smoke_pages_overlay` **150** 全过 + 全仓 compileall。
> · 行数变化：`core/backtest.py` 315→**495**、`ui/views/backtest.py` 1570→**1691**（均已在 §4 登记）。
>
> **进度（2026-09-15 · 文案返工 · 用户实测反馈驱动）**：用户指出第一版把 **"触发式条件单 /
> 触发跳数"** 原样摆到界面上 —— 原话："**用户完完全全不知道**……要么改文字表述，
> 要么就要给用户教育和指引才行"。**修法（四步模板，已固化 §10-10 追加条款 + §11.5-22）**：
> ① 文案换量纲（1 跳 → **0.01 元**、当根 → **当天**、"信号作废" → **"就不买也不卖"**）；
> ② 新增**行内常显说明**（`fill_mode_oneliner`，随选择实时变化 —— **不是 tooltip**）；
> ③ 新增**教学弹窗** `ui/dialogs/fill_model_help.py`（📖 三档怎么选？用**一套固定价格数字**
>    三档对照 + T+1 大白话）；④「多等多少元」只在第三档可见，其余隐藏。
> **验收**：文案可懂性探针 **24 项全过** —— 含**正则级行话检测**（下拉项与行内说明不许出现
> `跳(?!空)` / 当根 / K线 / 条件单）、元↔跳往返、说明随选择变化、弹窗带具体数字。
> ⚠ 检测必须用 `跳(?!空)`：**「跳空」是交易者常用词**，第一版写粗了直接把它误判成行话。
> **下一步 = 步骤 4**（把 C5 / 口径 / 文案三套探针断言正式移植进 `tests/smoke_chart.py`，
> 并拿 `samples/实例函数.txt` 端到端复跑）+ **步骤 5**（收尾）+ **用户手动实测手感**。
>
> **进度（2026-09-15 · 步骤 4 ✅ 已完成）**：
> ① **断言正式移植进两个冒烟脚本**（都按仓库既有风格 `check(说明, 条件)` 接在文件尾）：
>    · `tests/smoke_chart.py` 312→**356 项**（引擎三档时点 / T+1 顺延含**非空对照** / max_bars 顺延 /
>      触发式三态 / **同根不重建仓**含非空对照 / 参数归一化与元↔跳 / **文案行话正则检测** /
>      签名兼容）；⚠ **原探针里"借 `git show HEAD` 旧引擎逐位回归"那段故意不移植** ——
>      提交后 HEAD 会变，断言会随仓库状态漂移；改为对**手算期望值**断言（强度等价）。
>    · `tests/smoke_pages_overlay.py` 150→**180 项**（成交模型行 UI 往返与旧档回落 / 跳数步长与显隐 /
>      行内说明随选择变 / 教学弹窗文案含具体数字 / CSV 口径头与「（T+1 顺延）」标记与 8 列结构 /
>      PNG 1120×660）；**防污染自检名单新增 `backtest_strategies.json`**。
> ② **用户真实资产端到端复跑**（临时脚本，跑完即删；**不打印公式内容**，§10-6）：
>    · 两个私有公式（`实例函数.txt` / `实例函数2.txt`）：**解析 + 求值均通过**，
>      产出 **27 / 17 个变量**、各 **7 条绘图指令**（kind = line / stick / icon 三种都在）；
>    · 用户**真实策略存档 2 套：签名全部不变**（fill 字段没有污染老存档）；
>    · 三档 + 风控全开（止损3%/止盈8%/移动4%/最长30根）在同一段行情上：
>      `next_open` 49 笔 / T+1 顺延 **10** 笔；`close` 41 笔 / 顺延 **0** 笔；
>      `trigger` **33** 笔 / 顺延 10 笔 ⇒ 三个观察全部符合设计
>      （**触发式笔数更少** = 未触达的信号确实作废；**close 档零顺延** = 当日收盘建仓时
>      当根盘中波动本来就不评估，不存在"进场当根触发"）。
>    · ⚠ 复跑中我自己踩了两个**探针**坑并已修正（写进 §11.5-24）：
>      `check` 参数顺序写反（全部断言被恒真字符串短路）+ 把 `execute_programs_with_draws`
>      的**扁平** draws 误当成分组列表。
> **步骤 5 ✅ 已完成**：§6.3 / §8 / §11.4 / §11.6 / §11.7 均已回写；**用户手动实测通过**
> （原话"现阶段没问题"）。**§7-B5 全部步骤 0–5 收官**；app 版本随本批升至 **`1.21`**（v6.19 发版）。

#### F. P1 / P2 挂起设计（⚠ **用户 2026-09-15 明确搁置，不许顺手做**）

**为什么搁置**：P1 需要"账户模型"（引擎现在连仓位都没有 —— 见 F2），P2 需要"分钟数据基础设施"
（`kline_min` 分区 + 抓取链路 + 历史深度未验证）。两者都**不是"加个参数"能解决的**，
且当前投入产出比明显低于 P0。

**F-1) P1 · 账户 + 容量 + 成本（治"大仓位影响价格"）—— 前置：账户模型**
1. **账户模型（必须最先做）**：固定本金 + 单笔仓位上限 + **100 股整手取整** + 剩余现金留存。
   ⚠ 这一步会把"1 股归一化"改成"真金白银"，**净值曲线 / KPI / 策略对比存档全部要重算** ——
   这正是它必须单独一轮的原因。
2. **参与率上限（容量）**：单根 K 线 `volume × 参与率`（建议默认 10%）为可成交上限；
   超限三选一：**截断**（部分成交 + 明细显示「计划/实际」，推荐先做）/ 顺延次根 / 整笔拒绝。
   ⚠ 诚实边界：日线 `volume` 是**全天量**、不是开盘那一刻的量，用它约束"开盘成交"是近似。
3. **成本补全**：卖出印花税（现 0.05%）、过户费（0.001%）、最低 5 元佣金、固定滑点（bps）；
   可选**冲击模型** `冲击% = k × (下单股数 / 当日成交量)^0.5`（平方根律，`k` 可调）。

**F-2) P2 · 盘中即时成交（最真实 · 依赖分钟数据）**
- 做法：日线出信号 → 到**分钟数据**里找"条件下首次成立 / 价格首次触及"的那一根，按那根成交；
  分钟 `volume` 天然给出更真实的容量约束。
- 前置：`kline_min` 分区（已预留）+ 抓取链路 + **三处登记**（`market_db.zones` /
  `data_manager.ZONE_ORDER` / `SYNCABLE`）。
- ⚠ **最大不确定性 = 历史深度**：1/5/15/30/60 分钟各自能回溯多久差异很大；
  **动工前必须先做一次"取数实测"**（拉几只票看实际可得区间），否则方案可能白定。
- ⚠ 数据量 → 只能单股/少量标的（与 M1 单股定位一致）。
- **与「分钟周期」候选共用同一套基础设施**：建议**合并立项**，一次做两件事。

**F-3) 本主案明确"不做"的事（防止后人顺手加）**
- ❌ **不提供"允许当日平仓"的兼容开关**（用户拍板：真实优先，拒绝美化）；
- ❌ P0 阶段**不引入**滑点 / 印花税 / 整手取整（属 P1；混做会让"数字为什么变"归因不清）；
- ❌ 不在日线数据上"模拟"分钟级成交（那只会造出假精度）。

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
| v1.4.1 | 数据管理页 + 同步收敛 | A3 落地：数据湖删除/清点原语；`MarketSyncService` 同步门面（增量合并 + 温柔抓取 ThrottlePolicy）；`ui/workers.py` 统一线程；第 6 导航页 + 批量预下载弹窗；§9-H 架构债清账；**含 v5.9 独立复查加固**（§9-M1~M4 时效/空增量/起点/竞态） |
| v5.12(文档v5.12) | 全仓通读对账（**无代码变更**） | 第二次"陌生代码"复查：核对 30 个 .py，产出 §9-O 系列 10 项发现；校正 §3/§4 的 KPI 项数与全量行数；§4 补 `.gitignore` 与 `core/formula/` 五个子文件；刷新 §11.6 下一步顺序 |
| v5.13(文档v5.13) | 第一/第二梯队落地 | O-1 盈亏筛选改净额（用户拍板）；O-2 三个 UI 线程迁入 `ui/workers.py`；O-3 同步 docstring 起点改 2010；O-4 云端同步改默认增量（本地有=增量/没数据=全量，改名 `sync_cloud`）+ 状态回执；O-5 回测页补竞态守卫×2；O-7 新增 `ui/widgets/chart_style.py`（4 合 1，PlotWidget/PlotItem 兼容）；O-8 复盘页三小坑 + 画廊失效路径不再静默丢弃。**25 项冒烟断言 + 离屏构造主窗口/全部弹窗通过**。APP_VERSION 未动（仍 1.4.1）。**修订**：O-4 新增的同步状态 QLabel 触发了 Qt 布局坑（顶部栏末尾 QLabel 会吞掉主区高度），已给 main_splitter 加 `stretch=1` 根治，并固化为 §11.5 第 13 条 |
| v5.14(文档v5.14) | §7-A2 导出落地（半程） | 回测页「导出明细」按钮 + `_last_meta` 配置快照（start_backtest 定格）+ `_compose_result_csv`（逐笔明细 + 净值曲线，utf-8-sig）。**只导出、不删除**（用户拍板）；「结果历史存档」列为 §7-A4 远期方案。**14 项导出断言全过** + 全仓编译通过。APP_VERSION 未动（仍 1.4.1）。⚠ 其"注释头裸写"做法已被 v5.16 推翻 |
| v5.15(文档v5.15) | 导出升级：PNG 报告图 | 用户拍板：① CSV 移除 200+ 行净值段（溯源=参数+逐笔，曲线由图承担）；② PNG 报告图含离场原因饼图；③ 导出按钮改下拉菜单（CSV/PNG 两动作）。新增 `ui/widgets/backtest_report.py`（单页 1120×660 = 标题 + KPI + 净值曲线 + 饼图 + 参数简表，离屏 grab 渲染）；离场原因 标签/配色/风控文案上收 `core/backtest.py` 三处同源。**16 项断言全过** + 全仓编译通过。APP_VERSION 未动（仍 1.4.1） |
| v5.16(文档v5.16) | CSV 兼容性修复（WPS 实测） | 用户用 WPS 打开 CSV 发现"函数段·第三部分图形绘制"被拆列成乱码：根因 = 表头注释行裸写，含英文逗号的 `STICKLINE(...), COLORFF0000;` 被表格软件当多列。修复：`_compose_result_csv` **逐行单格 csv 转义**（含逗号自动引号、空行 writerow([])）。**9 项 csv.reader 重解析断言全过**。APP_VERSION 未动（仍 1.4.1） |
| v6.0(规划) | §7-B3 公式统一绘图（**P0 · 设计定稿，无代码**） | 用户复盘定位"绘图语句从没被画出来"= `program.py` 长期 SKIP 的历史欠账；定稿"引擎产出统一绘图 IR + 唯一 OverlayPainter"为全图表统一修改窗口（避免未来逐图一对一改）。里程碑 M0 契约层 / M1 求值层 / M2 渲染+回测页 / M3 收尾 / M4 远期全图复用。完整规格见 §7-B3 主案；优先级见 §11.6 |
| v6.1(文档v6.1) | 图表架构总纲（**升级 B3 为骨架，无业务代码**） | 用户拍板：把 §7-B3 从"公式叠层单点方案"升级为**四层架构**（① 引擎 IR `core/formula/draw.py`；② 图表宿主 `chart_pane.py`+`chart_host.py`；③ 渲染器 `draw_overlay.py`；④ 标注对象 `data/annotations.py`+`annotation_layer.py`）；厘清**两条管线**（A 公式叠层=重算不持久 / B 用户标注=持久可单删）；定 **P0–P8 路线**（P0 ChartPane 插在 M2 之前 / P2 ChartHost 多窗格 / P3 回测页验证 / P4 行情页公式叠层 / P5 副图 / P6 标注 JSON 先行且 API 与存储解耦 / P7 函数资产互送 / P8 通达信式重做）；内置指标与用户公式**统一图层协议**（D4）。另据第三次核对新增 §9-P（净额展示层残留 / 行数漂移 / FUNCTIONS 计数）；§4 行数按 v6.1 实测重刷 |
| v6.2(文档v6.2) | **P0 + P1 落地** | §7-B3 总纲开工第一批。**P1**：新增 `core/formula/draw.py`(124 行：`COLOR_TABLE` 含 COLORRRGGBB 直通 / `DrawSpec`/`DrawData` IR / 属性校验)；`program.py` 113→**265 行**，语句分类 **3 态→4 态**（ASSIGN/OUTPUT/DRAW，**SKIP 移除**，未知函数/颜色/属性/元数一律报错）；新增 `execute_programs_with_draws()`（同一 EvalContext 一遍同时出变量+draws）。**P0**：新增 `ui/widgets/chart_pane.py`(76 行)，`ChartPane` = PlotItem + 公式叠层容器 + 标注容器，渲染器入参从此固定为 pane。**验收**：新增 `smoke_chart.py` 冒烟入口（当时 57 项断言全过）；全仓 compileall 通过；主窗口离屏构造通过；`execute_programs` 旧行为逐位不变（Gate/检测/指数门控零影响）。APP_VERSION 未动（仍 1.4.1）。下一步 P2/P3 |
| v6.3(文档v6.3) | **P2 多窗格落地** | 新增 `ui/widgets/chart_host.py`(262 行)：`ChartHost` = 主图 + **N 副图**，x 轴联动（`setXLink`，pyqtgraph 0.14 用 `ViewBox.linkedView(axis)` 判联动）、**只有最下窗格显示底部轴**、窗格增删（`QGraphicsGridLayout` 不自动塌缩 → 删后重排行）与行高度权重、`pg.DateAxisItem` 日期轴切换、**跨窗格同步十字光标**（竖线贯穿全部窗格 / 横线只留悬停窗格 / 顶部数值回执）。`chart_style.py` 抽出 `style_axis()`（换轴后重新着色的唯一来源，防 §10-9 类问题）+ `CROSSHAIR_COLOR`。十字光标**不进** `ChartPane` 的叠层/标注容器（否则 `clear_overlays()` 会误删）。**验收**：`smoke_chart.py` 扩到 **97 项断言全过**；全仓 compileall + 主窗口离屏构造通过。APP_VERSION 未动（仍 1.4.1）。下一步 P3 |
| v6.4(文档v6.4) | **P3 公式叠层渲染 + 回测页接入** | 新增 `ui/widgets/draw_overlay.py`(210 行)＝全 app 唯一叠层渲染器：`OverlayPainter(pane, bars_x).render(draws)`（line→PlotDataItem、stick→自绘 `_StickItem` 支持 width/空心、icon→ScatterPlotItem + 图标号映射），附 `slice_draws` / `overlay_extent` 宿主工具。新增 `chart_style.ensure_contrast()` **对比度守卫**（黑底公式的 COLORWHITE/COLORYELLOW 在白底仍可见；判据 = 亮度差 ≥0.30 且 WCAG 对比度 ≥3:1，不足则**保留色相**地压暗/提亮）。`chart_pane` 持有源控件强引用（防 Qt 对象被 GC）。**回测页接线**：`_on_data_ready`/`detect_function` 改走 `execute_programs_with_draws`（不二次求值、错语句检测期即报）；`_render_kline` 用 **"排序后位置→原始行号"映射**切窗口（防错位漂移）；`🕯 K线买卖点` 新增「显示公式叠层」开关（只切可见性不重置缩放）；y 范围纳入叠层。**验收**：`smoke_chart.py` **126 项** + 新增 `smoke_backtest_overlay.py` **20 项页面级**（含离屏 grab 像素差异证明真画上去）全过；全仓 compileall + 主窗口离屏构造通过。APP_VERSION 未动（仍 1.4.1）。下一步 P4 |
| v6.5(文档v6.5) | **事故修复：存量函数回归** | 用户实测反馈"已保存的函数突然跑不了"，报错 `无法识别的语句 'STICKLINE(...), COLORFF0000': 公式末尾存在无法解析的内容: ','`。**根因 = v6.4 回归**：`_compile_draw` 把整条绘图语句（含**尾部颜色属性**）直接喂 `parse()`，而通达信允许 `STICKLINE(...), COLORFF0000;`；旧版整行 SKIP 所以"能用"，且 `start_backtest` 依赖检测成功 ⇒ 函数彻底跑不起来（§9-Q-1）。**修三处**：① 新增 `_split_draw_attrs()` 按顶层逗号摘掉属性尾巴再解析（与 OUTPUT 同源）；② 未实现绘图函数**不再 hard fail**，登记 `kind='unsupported'` + 检测期非阻断提示（`CompiledProgram.unsupported`/`unsupported_count`，`_set_detect` 文案进 tooltip）；③ `STICKLINE(cond,P,P,w,0)` 零高度时改画 **cosmetic 横杠**（Q-3）。用**用户真实函数**端到端复验通过（解析 OK / 27 变量 / 2 线 + 4 色柱 + 1 图标）。断言：`smoke_chart.py` **134 项** + `smoke_backtest_overlay.py` **25 项** 全过；全仓 compileall 通过。APP_VERSION 未动（仍 1.4.1） |
| v6.6(文档v6.6) | **P4 落地：行情页公式叠加** | 新增 `ui/dialogs/formula_overlay.py`(144 行)：公式编辑器（复用 `FunctionSegments` + 参数框 + 检测/清空/应用），自检口径与回测页同源。`ui/views/market.py` 新增「🧮 自定义公式」区：`cb_formula`（与均线/布林带**同一个 `render_charts` 开关行为**）+「编辑公式…」+ 状态回执。**核心 = §7-B3 D4 统一图层**：`_builtin_layers()` 把 MA/BOLL 翻成 `DrawData`，`_formula_layers()` 把用户公式求值成 `DrawData`，二者交给**同一个 `OverlayPainter`** 上到同一个 `ChartPane` —— 对比度守卫/线型/粗细/空白处理**自动一视同仁**。抽出三件共用件消除跨页重复：`core.utils.parse_params_text`、`core.utils.synthetic_bars`、`core.formula.program.probe_missing_parameters`（`backtest.py` 全部改为委托，删除本地副本与 `import re`）。公式在某标的执行失败**不打断整页渲染**，只在面板给 ❌ 提示。`smoke_backtest_overlay.py` 更名 **`smoke_pages_overlay.py`**。**验收**：`smoke_chart.py` **146 项** + `smoke_pages_overlay.py` **36 项** 全过；全仓 compileall + 主窗口离屏构造通过。⚠ `market.py` 350→**425 行**（已越 400 线，P5/P8 必须新建文件）。APP_VERSION 未动（仍 1.4.1） |
| v6.7(文档v6.7) | **P5 前置：公式副图 + 对话框返工 + 共用组件修 Bug** | 用户实测驱动。**修 `ui/widgets/function_segments.py` 两个真实 Bug**：① 僵尸段（`removeWidget+deleteLater` 留下可见重复控件 → 对话框出现两个"函数段 1"）改为先 `setParent(None)`；② 版面塌陷（编辑框 `setFixedHeight` 让多余高度变成标签-编辑框之间的大空档）改为 `Expanding` + 最小高度 110，多余高度变成编辑区。**重做 `ui/dialogs/formula_overlay.py`**：删重复文案、加**目标窗格** + 随选动态说明 + **示例模板菜单**（选模板自动切目标）+ 编辑区入 `QScrollArea`。**行情页支持副图叠加**：`market.py` 新增「公式副图」窗格（x 联动、y 独立、跨 0 给零轴）。**新增 `ui/widgets/chart_layers.py`(65 行)**：`builtin_indicator_layers` + `layer_value_range` + `scale_mismatch_hint`。**验收**：`smoke_chart.py` **161 项** + `smoke_pages_overlay.py` **58 项** 全过。APP_VERSION 未动（仍 1.4.1） |
| v6.8(文档v6.8) | **P5 落地：多副图 + 窗格编排收编 ChartHost** | ① 每段可选目标窗格（主图/副图 1/2/3）：`FunctionSegments` 新增 `accessory_factory`（每段附件控件，回测页不传 ⇒ 零影响）。② 引擎新增 **`execute_programs_with_draws_grouped`**（draws 按函数段分组）—— 各段共用**同一个变量池**，所以"每段不同目标"只能**一次求值、再按段归位**；三个执行入口收敛到唯一的 `_run_programs`。③ **行情页窗格编排迁移到 ChartHost**（§10-12 违规清账）：`ChartHost` 补 `fixed_height` / `bottom_axis_mode`(hide/no_values) / `clear_sub_panes()` / `clear_pane_content()`（不会误删十字光标）/ `setBackground()`。④ **多副图按需创建**。⑤ 新增 `ui/widgets/indicator_panes.py`（成交量/MACD 内容构建搬出页面）；量柱/MACD 仍用原生 BarGraphItem（P5 明确保留的例外）。**验收**：`smoke_chart.py` **161 项** + `smoke_pages_overlay.py` **63 项** 全过（含跨段共享池/窗格顺序/x 联动/y 独立/钉死高度/刻度值只在最下窗格）。**market.py 463→448（首次下降）**。APP_VERSION 未动（仍 1.4.1） |
| v6.17(文档v6.17) | **§7-B5 立项：回测成交真实性（零业务代码变更）** | 用户提出"指标滞后 / 开盘容量限制 / 盘中信号要等次日"三个痛点，并拍板四项：① **T+1 修正默认开启且不给旧口径开关**（"数字难看无所谓，贴合真实最重要"）；② **「当日收盘」成交档照做**；③ **触发式委托（条件单）照做**；④ **P1（账户+容量+成本）/ P2（盘中即时成交）搁置**、设计留档。立项前用合成 K 线探针**实测 7 组**（跑完即删），坐实 5 条现状事实：F1 次日开盘成交 / F2 **引擎无资金无仓位**（1 股归一化）/ **F3 T+1 违规**（止损·止盈·max_bars 可当日买当日卖 ⇒ 低估风险）/ F4 成本只有佣金 / F5 数据无成交额。产出 **§7-B5 主案**：P0 规格（C1 三档成交时点、C2 T+1 闸门含"顺延到最早可卖根开盘价"、C3 触发价与跳空同源、C4 单一口径、C5 七条验收断言含**负向对照**）、影响面 5 条、实施步骤 0–5、以及 P1/P2 挂起设计（含明确"不做"清单）。APP_VERSION 未动（仍 1.20） |
| v6.18(文档v6.18) | **§7-B5 P0 落地（步骤 1–3）+ 用户指引返工** | ① **引擎**（`core/backtest.py` 315→**495**）：三档成交时点（`next_open` 默认 / `close` 当日收盘 / `trigger` 价格冲破·跌破才成交）+ **T+1 硬约束**（进场当根触发价格型风控 → 顺延到最早可卖根**开盘价**成交；`max_bars` 顺延到次根收盘；末根不建仓）+ **同根不重建仓**（判据 = **成交根**重合）。验收：C5 探针 **39 项**（含非空对照 + 借 `git show HEAD` 旧引擎做 40+40 组随机样本**逐位回归**，非预期差异 0）。② **口径连通 + UI**（`ui/views/backtest.py` 1570→**1691**、`data/strategy_store.py`、`ui/workers.py`、`ui/widgets/backtest_report.py`）：策略签名（**默认口径归并为空串** ⇒ 旧存档签名不变）、旧档回落、`_last_meta`、CSV 表头与「（T+1 顺延）」标记、PNG 报告图；新增「🎯 成交模型」行（探针 22 项全过）。③ **用户指引返工**（用户实测反馈"触发式条件单 / 触发跳数**完完全全看不懂**"）：文案全面换人话（`1 跳 → 0.01 元`、`当根 → 当天`、"信号作废"→"不买也不卖"）；新增**行内实时说明** + **教学弹窗** `ui/dialogs/fill_model_help.py`（一套固定价格数字三档对照）；参数只在第三档可见。纪律固化 **§10-10 追加条款** + **§11.5-22**；文案可懂性有正则级可测断言（24 项全过）。④ **步长 Bug 修复**（用户实测"买卖价要多等按一次上箭头就跳到 0.2 且无法继续上调"）：根因 = 公共工厂 `_risk_spin` 把步长写死成 `1 if decimals == 0 else 0.5`，对新的 2 位小数控件就是"一按顶到上限"；修为**随小数位自适应**（≥2 位 → `10^-decimals`）并把上限放宽到 1.00 元（§11.5-23）。回归：全仓 compileall 通过。⑤ **步骤 4 验收落地**：断言正式移植进两个冒烟脚本 —— `smoke_chart` 312→**356 项**、`smoke_pages_overlay` 150→**180 项**（含**文案行话正则检测**、**同根不重建仓非空对照**、CSV 8 列结构、教学弹窗文案、跳数步长；防污染名单加 `backtest_strategies.json`）；⚠ 原探针的 `git show HEAD` 逐位回归**故意不移植**（提交后 HEAD 会变），改为手算期望值。**用户真实资产端到端复跑**（临时脚本，跑完即删）：两个私有公式解析+求值通过（27/17 变量、各 7 条绘图指令 line/stick/icon）；**真实策略存档 2 套签名全部不变**；三档 + 风控全开对照 `next_open 49 笔(T+1 顺延 10)` / `close 41 笔(顺延 0)` / `trigger 33 笔(顺延 10)` —— 完全符合设计预期。⚠ 待办：**步骤 5 收尾 + 用户手动实测手感** |
| v6.19(文档v6.19) | **提交发版：app 版本 → 1.21（零业务代码变更）** | §7-B5 回测成交真实性的实现与验收已在 v6.17（立项）/ v6.18（落地）完成；本批只做**三处版本号同批同步**（§9-A 新纪律的首次实跑）：① commit message 首词 `1.21 回测策略更新`；② `config/settings.py:APP_VERSION` → **1.21**；③ 仓库根 `version.json` → **1.21**，`notes` 换成这一轮的用户可见变更（三档成交时点 / T+1 / 同根不重建仓 / 口径入签名与导出 / 教学弹窗 / 步长修复）。**用户手动实测手感已通过**（原话"现阶段没问题"）⇒ §7-B5 步骤 0–5 全部收官。回归：`smoke_chart` **356** + `smoke_pages_overlay` **180** 全过 + 全仓 compileall。⚠ 本批**只提交、未 push**；`version.json` 的 `url` 仍指向 Releases 列表页（用户决定：软件未完工，暂不制作 Release） |
| v6.16(文档v6.16) | **A 类文档欠账清账（零业务代码变更）** | ① **§4 行数口径改版**（用户拍板：**只标 ≥400 行的文件**，其余不标 —— 根治"每次大改全量重刷且必然漂移"的维护债；§4 目录树 + 体积红黑榜按实测重写）；② **失效文件引用**（`ui/views/market.py` v6.12 已删除：2 处**活引用**改为 `trading_desk.py` 的真实落点（`formula_overlay.py` 的渲染方、`backtest.py` 的 `_on_sync_finished`），4 处历史叙事保留原文 + 补注"该文件已删除"；文档 §11.4 两条活引用同批修正）；③ **版本号体系改版**（用户拍板：**统一跟随 git** = 最近一次 push 的 commit message 首词，**每次 push 递增 0.01**；`APP_VERSION` 与 `version.json` 由 `1.4.1` → **1.20**；新纪律写入 §9-A）。回归：`smoke_chart` **312** + `smoke_pages_overlay` **150** 全过 + 全仓 compileall。**附**：`version.json` 的 `url` 由占位符 `https://github.com` 改为**项目 Releases 列表页**（用户决定：软件尚未完工，暂不制作 Release，先占位；正式发版时换直链） |
| v6.15(文档v6.15) | **§7-B4 坐标轴自适应（全 App 收口）** | 用户截图驱动立项的全 App 缺陷收官。**新建 `ui/widgets/adaptive_axis.py`(348)**＝全 app 唯一的刻度与量程来源：纯函数 `compute_ticks`（日期格式梯子：日内/同年/跨年）/`compute_text_ticks`（序数轴）/`slice_span`（可视极值，NaN 忽略）+ `attach_date_axis`/`follow_y`/`attach_all`（监听 `sigXRangeChanged` 重算，**同轴重复 attach 自动替换旧跟随器**，弱引用登记表 + 非幂等保护 + `handle_for` 读口）。**3 处静态 ticks 全部收敛**：行情主图/量/MACD/公式副图逐窗格（`_adaptive_providers` 回答 provider 契约）、复盘 K线回放、复盘资金K线；**回测页两处改为调用公共纯函数**（K线 `chk_follow` 开关语义保留、净值轴）。两个原始诉求已验证：放大到 10 根仍有 ≥2 刻度、纵轴按可视区间重算（副图不再压成一条线）。实施中固化两条新知：① **`ViewBox.setYRange` 会偷加自己的 padding**（实测 2%~4.7% 且漂移）⇒ 一律 `padding=0`（§11.5-21）；② 复盘"资金 K 线"的 x 其实是**当月第几日的序数轴**⇒ 增设文本刻度入口（套 `%m-%d` 会说谎，§9-v6.15）。断言：`smoke_chart` 290→**312**（+22）、`smoke_pages_overlay` 139→**150**（+11 页面级）全过 + 全仓 compileall。APP_VERSION 未动（仍 1.4.1） |
| v6.14(文档v6.14) | **全仓文件归置（零业务变更）** | 用户指出"根目录存在许多未分类文件"。立 **§10-13 文件归置规范**：根目录收敛为白名单（`main.py`/`requirements.txt`/`version.json`/`JIAN_RULES.md`/`.gitignore` + `config|models|core|data|ui` + `scripts|tests|samples`）。新增三个角色目录（判据 = 谁调用它）：`scripts/`（`sync_roster.py`，人工运行、不进 import 图）/ `tests/`（两个冒烟脚本）/ `samples/`（`实例函数*.txt` + `实例交割单*.xlsx`，是数据不是代码）。删除根目录空壳 `screenshots/` 与全仓 `__pycache__`。**移动脚本同批修路径引导**（子目录必须 `__file__` 反推仓库根，否则 `from data...` ImportError；`smoke_chart` 的 `Path(ROOT)/"ui"` 源码级守门会静默失效）+ 修**用户可见文案**（"请先运行 `scripts/sync_roster.py`"）与 3 处 docstring/注释。`.gitignore` 收紧为 `samples/*` + `!samples/README.md`（整目录忽略只放行说明，优于逐文件名模式）+ `_tmp_*` 兜底。`ui/views/market.py` 的删除同批 `git rm`。回归：`py tests/smoke_chart.py` **290** + `py tests/smoke_pages_overlay.py` **139** 全过 + 全仓 compileall；`git ls-files` 核对**无死代码**。登记待办（暂缓）：`ui/widgets/` 可再分 `chart/` 子包（51 处 import）。APP_VERSION 未动（仍 1.4.1） |
| v6.13(文档v6.13) | **P8 收尾（复权切换 + 文字拖动）** | ① **复权**：`market_db` 新增 `kline_daily_raw` 分区（不复权与前复权**各存一份**——前复权随除权整体漂移、不复权不会，两者无法互推）；`akshare_feed` 两个源都按同一 `adjust` 拉取（**降级不许静默换口径**）+ `ADJUST_QFQ/ADJUST_NONE`；`sync_service` 新增 `zone_for_adjust/adjust_label/ADJUST_*`（UI 唯一入口）与 `ZONE_KLINE_RAW` 抓取分支；「数据管理」新增该分区并可单独同步/删除；工作台复权下拉 + "取数中/不含旧口径根数"的诚实回执。② **文字标注拖动**：`_ClickableText` 自实现 `mousePressEvent/mouseDragEvent`（pyqtgraph 覆写 `mouseMoveEvent` 不调父类 ⇒ ItemIsMovable 无效），松手才落盘、坐标按 (日期,价格) 回写。断言：`smoke_chart` 278→**290**、`smoke_pages_overlay` 132→**139** 全过 + 全仓 compileall；临时脚本与输出文件已清理。APP_VERSION 未动（仍 1.4.1） |
| v6.12(文档v6.12) | **P8 行情页整体重做（换壳不换芯）** | 新建 `ui/views/trading_desk.py`(734 "行情工作台")，**删除** `ui/views/market.py`(661 越线文件)；页面只做装配，绘图能力全部复用既有组件（ChartHost/OverlayPainter/chart_layers/annotation_layer/indicator_panes/formula_store/formula_library/workers）。新增 **自选股** `data/watchlist_store.py`(143，原子写/坏数据容忍/名称随花名册刷新)、**周期 日·周·月** `core/utils.resample_ohlcv`(日线就地聚合，date=该周期最后一根真实交易日，指标在聚合后再算)、**画线 3 类→5 类**(斐波那契 = 两端点+7 档+标签附属图元；文字 = `_ClickableText`，因 `pg.TextItem` 不发点击信号就**无法单独删除**)、**标注按 (标的,周期) 隔离**(新增 `annotations.period_key`)；`main_window.page_market` 指向新页。断言：`smoke_chart` 238→**278**、`smoke_pages_overlay` 111→**132** 全过 + 全仓 compileall。⚠ P8 收尾待做：复权切换 / 分钟周期(D3) / 锚点拖动。**附带加固**：页面级冒烟脚本补三条打桩（模态框立即返回 / 更新检查不联网 / 结尾 `os._exit`），治好了"脚本看似卡死无输出"（§11.5-20）。APP_VERSION 未动（仍 1.4.1） |
| v6.11(文档v6.11) | **P7 函数资产化 + 行情↔回测互送** | 新增 `data/formula_store.py`(213，零 Qt：函数段+参数+**每段目标窗格** → 有名字的配方；`~/.jian_data/formula_library.json` 原子写；按 `name` upsert、`touch/last_used`；`get_formula_store()` 单例) 与 `ui/widgets/formula_library.py`(171：列表/预览/载入/改名/删除，**两页共用**)。互送由 `main_window` 当唯一传话筒（两页面**互不 import**）：行情页「📤 送去做回测」(目标不随行) / 回测页「📤 送到行情页」(每段落主图)；两侧均自动切页+自动检测。行情页开机**自动恢复上次配方** ⇒ 治本"公式重启就丢"。配方≠策略：配方只有公式，策略=配方+条件+风控+区间。断言：`smoke_chart` 212→**238**、`smoke_pages_overlay` 84→**111**（含**防污染自检**：用户真实库不得被测试写）。APP_VERSION 未动（仍 1.4.1） |
| v6.10(文档v6.10) | **红线收编 + P6 标注持久化** | 用户拍板"红线不放宽 ⇒ 收编"：`MarketSyncService.fetch_index_constituents()` 成为**联网抓取唯一入口**（`ui/` 全层零 `AkShareFeed`，源码级断言守门），失败文案按"网络 / 行情源未收录"分类。**P6 落地**：新增 `data/annotations.py`(255，零 Qt：`KIND_*` 模型 + `(标的,周期,id)` 原子写 CRUD + `DateAxis` 日期↔序号映射) 与 `ui/widgets/annotation_layer.py`(222：绘制/选中/**逐个独立删除**)；`ChartPane` 补 `remove_annotation()`；行情页三件套（趋势线/水平线/垂直线）+ 工具下拉 + 删除选中 + 清空(二次确认) + Delete/Esc；**坐标存日期不存序号**（"前置 5 根 ⇒ 序号 +5 不漂移"有页面级断言）。§7-A1 欠账被吸收清零。断言：`smoke_chart.py` 178→**212**、`smoke_pages_overlay.py` 63→**84** 全过 + 全仓 compileall 通过；§4 行数重刷。APP_VERSION 未动（仍 1.4.1） |
| v6.9(文档v6.9) | **复查 + 小债清账（无新功能）** | 第三次全仓"陌生代码"对账后收尾四项：① **§9-P1 净额收尾** —— 新增 `core/utils.record_net_amount()`（全站唯一口径）+ 5 处逐笔展示层改净额（流水页盈亏列**改名「净盈亏」并显示净额**、复盘页当日清单/详情头/回放标记色）；② **§10-9 控件契约** —— `custom_widgets` 新增 `combo_qss()/date_edit_qss()` 生成器 + 8 具名常量 + `NoWheelDateTimeEdit`，清掉 7 处就地半截 QSS，**治好"只写 `::drop-down` 导致下拉箭头整个消失"的长期隐形 Bug**（复盘页时间选择器 / 手工录入弹窗）；③ NoWheel 补齐（复盘孤儿日期 + 手工录入时间与 5 个数值框）；④ 行情页接线**跨窗格十字光标**。断言：`smoke_chart.py` 161→**178**（+净额 6 / +样式契约 11，含负向对照）、`smoke_pages_overlay.py` **63** 全过、全仓 compileall 通过；§4 行数按实测重刷（口径 = 非空行）。APP_VERSION 未动（仍 1.4.1） |
| 远期 | 排期 | 组合级多标的引擎（指数择时后全市场挑股+资金分配，见 §6.5） |

---

## 9. 审计发现：文档 ↔ 代码不一致 / 技术债（本次 v5.0 核对产出）

- **A. ✅ 已修（v5.7）版本号滞后；🔁 编号体系于 v6.16 改版（用户拍板）**：
  `config/settings.py` 的 `APP_VERSION` 与 `version.json` 一度统一为 `1.4.0` / `1.4.1`
  —— 那是"回测总集"语义编号，与 git 提交里的 `1.07 … 1.20` **长期并行、互不同步**，**已废弃**。
  【★ v6.16 新纪律（2026-09-15 用户拍板）】**版本号统一跟随 git**：
  · 取值 = **最近一次 push 的 commit message 首词**（历史形如 `1.07`、`1.19`、`1.20`）；
  · **每次 push 递增 0.01**（1.21 → 1.22 → 1.23 …）：不跳号、不改三段式、不引入第四套编号；
  · **当前值 = `1.21`**（= §7-B5「回测成交真实性」这一轮：三档成交时点 + T+1 硬约束 + 用户指引）；
    上一轮 `1.20` = 图表架构 P0–P8 + 全仓文件归置 + 本版本号体系改版；更早的 `1.4.x` **已废弃**；
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
- **H. ✅ 已修（v5.8）~~【架构边界松动】UI 层 3 处直连底层~~**：
  修法 = 新增 `data/sync_service.py` 门面 + `ui/workers.py` 统一线程 + `DataEngine` 检索门面：
  ① `market.py` → `SingleSyncWorker(zone=…)`，删掉本地 `FetchDataThread`；
  ② `backtest.py` → 同一 `SingleSyncWorker`，删掉 `_StockSyncThread` / `_IndexSyncThread`；
  ③ 两处 `engine.db.search_symbol` → `engine.search_symbol`（新增 `engine.list_stock_symbols` 供全市场下载）。
  【仍然允许】UI 直接 import `akshare_feed` 的**纯常量/纯函数**（`INDEX_PRESETS` /
  `is_index_symbol` / `is_stock_code`）—— 它们无副作用、不联网；
  **任何联网抓取必须经 `MarketSyncService`**，这是本次划定的新红线。
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

### v5.9 独立复查产出（在 v5.8 基础上新发现并修复，全部有断言）
> 背景：会话中段更换过语言模型。为保证"两模型交替合作"不出夹生代码，把上一批改动当作
> 陌生代码整体重审。以下 4 个隐患都真实存在且已修复 —— 教训：**跨会话/跨模型的改动，
> 提交前必须做一次"不信自己人"的复查**。
- **M-1【时效 Bug】"增量永远滞后一天"**：原 `fresh_within_days=1` 会让"昨天收盘后已同步"
  的标的在今天的收盘后窗口被 `skip_fresh` 跳过 —— 而 A 股当日 bar 恰恰是收盘后才发布。
  **修复**：`fresh_within_days` 改为 **0**（只有末日==今天才算最新），宁可多花一次轻量增量，
  也不让当日数据漏掉。代价由"空增量不算失败"（M-2）兜住。
- **M-2【语义 Bug】休市/盘中的空增量被误判为失败**：增量区间拉不到新 bar（周末/节假日/
  未开盘）会被当成失败：白做 3 次退避重试、还计入熔断计数。**修复**：增量模式只请求一次、
  空返回即按 `skipped=True` 返回（非失败）；首拉/强制全量仍保留重试语义（坏代码=真的失败）。
- **M-3【数据回归】起点 2010→2016 的静默缩水**：迁移到 `MarketSyncService` 时默认起点写成
  "回测评估窗 2016"，但市场行情页"云端同步"历史上拉的是 2010 起 —— 用户曾经能看到的
  2010~2016 历史 K 线会凭空消失。**修复**：`DEFAULT_MIN_DATE=20100101`（数据窗与评估窗解耦：
  数据窗=2010 全历史，评估窗=`core/backtest.DEFAULT_START_DATE`=2016）。批量预下载默认仍给
  2016 平衡下载量，但起点控件下沿放宽到 2010 让用户可选。
- **M-4【竞态/崩溃】**：① `ScanWorker` 结果不带 zone，数据管理页快速切换分区时旧扫描结果
  晚到会覆盖新分区 → 信号改为携带 `(zone, items)`，接收方校验；② 勾选集合曾存在表内、
  搜索过滤即丢失 → 独立 `_checked: set` 并跨过滤保留；③ 批量下载弹窗右上角 X 关闭时
  QThread 仍在运行、随对话框销毁会崩溃 → `closeEvent` 走"取消→wait(15s)→仍不停则保持窗口
  存活并提示"，绝不带着活线程销毁；④ 成分股解析按钮连点 → token 序号只认最后一次结果。

【固化到 §11.5 的第 8 条坑，禁止回退】同步语义两大铁则：
  A. "本地已最新"的判据是 **末日==今天**（`fresh_within_days=0`），任何放宽都会制造滞后一天；
  B. **空增量 = 已最新，不是失败**（增量模式不重试、不计熔断、`skipped=True`）。
  数据窗起点 2010 不得再缩水（§9-H 同源红线）。

### v5.10 UX 加固产出（用户实测反馈驱动，均已断言）
- **N-1【复选框 Bug】"点不出勾 / 点了就消失" —— v5.11 最终方案**：
  第一轮修法（v5.10）只解决了"列宽≈0 看不到指示器"，改用"原生 indicator + cellClicked 整格
  切换"后反而引入**双重触发**：点击 indicator 时 Qt 自动切换一次、`cellClicked` 又切一次
  → 净效果等于没点，怎么点都打不出勾；且加 `ItemIsSelectable` + `SelectRows` 出现蓝色行高亮。
  **最终方案（v5.11，已用 QTest 真实鼠标事件断言）**：
  ① **彻底不用 Qt 原生 checkbox** —— 第 0 列自绘 `☐/☑` 字符，颜色区分（勾=主题蓝/未勾=浅灰），
  ② `cellClicked` 是**唯一切换入口**（点击一次 = 状态翻转一次，绝无双路径），
  ③ `setSelectionMode(NoSelection)` —— 整表无行/格选中，彻底消除蓝色高亮。
  表头「☑」提示列用途。教训写进 §11.5 第 9 条坑。
- **N-2【行错位 Bug】过滤搜索时单元格错位/漏填**：`_render_items` 用
  `enumerate(self._items)` 再跳过不匹配项来定行号，过滤后行号与 `setRowCount` 的真实行不一致。
  **修复**：直接对「过滤后的可见列表」按 0..n-1 铺行。
- **N-3【防呆层级】"清空分区"与"删除选中"同排、区分度不足**：大面积不可逆操作必须物理隔离。
  **修复**：右侧主操作行只留「更新到最新 → 重新全量下载 → | 删除选中」（高频、有选中才可点）；
  「清空当前分区…」**移到左侧分区栏底部**的低调小字链接，且执行前先弹后果说明、
  再要求键入「清空」二字 —— 双重闸门。
- **N-4【文案】用户看不懂"增量更新/强制全量重拉"**：一律改用户语言并给 tooltip：
  「🔄 更新到最新」= 只下缺失的最新几天（日常）；
  「⟳ 重新全量下载」= 丢弃本地从 2010 整段重拉（慢，仅数据异常时用，tooltip 说明前复权）。
- **N-5【误导文案】退市股报错像"代码错了"**：600277（2024-06 退市）这类股行情源不再提供，
  原提示"代码不存在/网络抖动"纯属误导。**修复**：`refresh_one` 结果增加 `reason` 维度
  （`ok/fresh/no_new/network/no_data/error`），新增 `friendly_fetch_message()` /
  `short_fetch_reason()` 统一生成人话文案；行情页 / 回测页 / 批量弹窗 / 管理页全部接入，
  `no_data` 明确列出"①代码有误 ②已退市/长期停牌（本地缓存历史仍可用）③行情源未收录"。

【固化到 §10-10 的新铁律】危险动作物理隔离 + 面向用户说人话（见下）。

### v5.12 全仓通读核对产出（第二次"陌生代码"复查，10 项）

> 背景：会话中再次更换过语言模型。按 §9-M 立下的规矩——**跨会话/跨模型的改动，
> 提交前必须做一次"不信自己人"的复查**——本次把全部 30 个 .py 重读一遍，
> 逐项对账"文档说的"与"代码做的"。结论：**核心链路（净额/幂等/FIFO/孤儿/同步语义）
> 全部健在**，下面 10 项都是"边缘漂移"，不影响主链路正确性。

> **✅ v5.13 状态：O-1 ~ O-8 全部已修**（共 25 项冒烟断言 + 离屏构造主窗口/全部弹窗通过）。
> 下面保留原文是为了让未来的我知道"当时为什么这么改"；每项标题后标了最终做法。

- **O-1【口径漂移】✅ 已修（改为净额）** —— 流水页 / 复盘页的「仅盈利 / 仅亏损」过滤器
  用的是毛利 `net_profit`，违反 §5.3-B 净额铁律：
  - `ui/views/records.py:274-275`（`仅盈利`→`net_profit > 0`；`仅亏损`→`net_profit <= 0`）
  - `ui/views/review.py:491-492`（同样的两行）
  - 后果：一笔"毛利 +100、手续费 150"的交易真实净额是 **−50**，却会被算进「仅盈利」，
    与 Dashboard / `core/analyzer.py` 的净额口径**自相矛盾**（用户会看到"盈利筛选里
    混着亏钱的单子"）。
  - 修法：改为先算 `net_amount = net_profit − commission.fillna(0)` 再判正负。
  - ✅ **v5.13 用户拍板：改净额**。两处均先算 `net_amount` 再判正负，
    并给下拉加 tooltip「按净额 = 平仓盈亏 − 手续费判断」。断言：毛利 +100 / 手续费 150
    的单子现在正确落进「仅亏损」。

- **O-2【架构债残留】✅ 已修（三个线程迁入 workers.py）** ——
  `ui/workers.py` 只收口了"行情同步类"线程，§2 的宣称不成立：
  以下 4 个 QThread 仍定义在各自业务文件里 ——
  | 线程 | 位置 | 用途 |
  |---|---|---|
  | `_BacktestRunThread` | `ui/views/backtest.py:121` | 回测计算 |
  | `_ConstituentsWorker` | `ui/dialogs/bulk_download.py:47` | 指数成分股解析 |
  | `FuturesImportWorker` | `ui/dialogs/import_futures.py:19` | 交割单解析（子线程内还读 SQLite） |
  | `UpdateCheckerThread` | `core/updater.py:9` | 版本检测（落点在 core，非 UI） |

  **现状判定**：`ui/workers.py` 现有 `ScanWorker` / `SyncWorker` / `SingleSyncWorker` 三个，
  全是"数据湖同步"这一类。所以准确说法是**"行情同步类线程已收口"**，不是"线程已收口"。
  ✅ **v5.13 修法：② 全搬**（三个 UI 线程都进 workers.py，`UpdateCheckerThread` 留在
  core/updater.py 因为它本就不属于 UI 层；§2 表述已同步改成准确版本）。
  新名字：`BacktestRunWorker` / `ConstituentsWorker` / `FuturesImportWorker`。

- **O-3【文档字符串失真 · 回归隐患】✅ 已修** ——
  `data/sync_service.py:118` 把数据起点写成了 2016-01-01：
  `refresh_one` 的 docstring 写着 `默认 DEFAULT_MIN_DATE(2016-01-01)`，而该文件第 47 行的
  实际值是 `DEFAULT_MIN_DATE = "20100101"`（§9-M3 修正后的正确值）。
  **危害不在当下在未来**：下一个人（或下个模型的我）照着 docstring 就会把起点"修"回 2016，
  §9-M3 的数据静默缩水**原样复发**。
  ✅ **v5.13 已改**：docstring 改成 2010-01-01，并显式注明"数据窗 2010 ≠ 评估窗 2016"。

- **O-4【行为与文案不符】✅ 已修（改默认增量）** ——
  行情页「☁️ 云端同步」恒为全量重拉，用户没有增量选项：
  `ui/views/market.py:174-184` 的 `force_sync_cloud()` 固定传 `force_full=True`，
  所以对**已缓存**的标的点一次 = 从 2010 整段重下一次（慢、浪费请求、有被限流风险）。
  这与数据管理页已经做好的「🔄 更新到最新 / ⟳ 重新全量下载」双按钮体验**不一致**。
  ✅ **v5.13 已修**：`force_sync_cloud` 改名 `sync_cloud`（名字不再撒谎），
  `force_full` 恒为 **False** —— 本地有数据=增量补最新、没数据=自动全量。
  另加 `lbl_sync_status` 回执（「已是最新，无需更新」/「已更新，新增 N 行」/「同步失败」），
  杜绝"点了没反应"。全量下载仍只在「🗄 数据管理」页（§10-10）。

- **O-5【竞态防护缺失】✅ 已修** —— 回测页的同步结果没有"标的是否已被切换"的校验：
  `ui/views/backtest.py:1042-1053` `_on_synced` 拿到结果就直接落库渲染；
  而 `market.py:190-192` 有一模一样场景却写了守卫（`if symbol != self.current_symbol: return`）。
  后果：拉取期间用户切了标的，旧标的的数据会渲染到新标的上。
  ✅ **v5.13 已修**：`_on_synced` 比对 `symbol != self.current_symbol` 即丢弃并复位 busy；
  `_on_index_synced` 比对 `result["symbol"] != self._pending_index["symbol"]` 即丢弃。
  **这是"同一类防护只做了一半"的典型** —— 加防护时务必全局搜一遍同一场景还有几处
  （已固化为 §11.5 第 11 条）。

- **O-6【文档过时】✅ 已修** —— §4 目录树的行数与版本号全面与磁盘不符：
  `data_feed.py` 文档 965 / 实际 827，`database.py` 479/437，`backtest.py` 1403/1253，
  `review.py` 1248/1122，`engine.py` 157/158；`config/settings.py` 的 `APP_VERSION`
  早就是 **1.4.1**，旧文档仍写 1.1.0(⚠)。**§4 现在带行数，每次大改后务必重跑一次行数统计。**

- **O-7【重复代码】✅ 已修（4 合 1）** —— 图表样式函数被复制了 **四份**（通读时只数出三份，
  漏了 market.py；**教训：数重复要全局 grep 函数名，别靠记忆**）：
  - `_apply_pokorny_style`：`ui/views/review.py` 与 `ui/widgets/yearly_review.py`
  - `_apply_pokorny_axis`：`ui/views/backtest.py` 与 `ui/views/market.py`
  - 净值"排序→cumsum→按盈亏选色→plot+fillLevel"：review / yearly_review / backtest / dashboard
  - ✅ **v5.13**：新增 **`ui/widgets/chart_style.py`**，收敛为
    `apply_pokorny_style(chart, title, background, grid_alpha, margins)` 与
    `plot_equity_curve(chart, values, fill_base, width, positive)`。
    ⚠ **坑**：行情页的 `GraphicsLayoutWidget.addPlot()` 返回的是 **PlotItem** 不是 PlotWidget，
    所以新函数两种类型都要能吃（`hasattr(chart,'getPlotItem')` 分流）。
    改外观请只改 chart_style.py。

- **O-8【小坑】✅ 已修（4 项全清）** —— §9-J 三项未修 + 一处文档描述有误：
  - ✅ `review.py`：`engine.df` 为空时也走 `refresh_time_picker`（不再残留陈旧月份项）。
  - ✅ `review.py`：「仅日期」分支解析异常改为 `continue`（算不出就不参与统计，绝不塞 0）。
  - ✅ `review.py`：`toggle_review_mode` 切到年视图时先 `playback_chart.clear()`，
    杜绝回放残留。
  - 文档纠错（v5.12 已记录，v5.13 顺带处理）：`screenshot_gallery.py` 的
    `path.rsplit('.', 1)[-1]` 对无扩展名文件**不会抛 IndexError**（`rsplit` 返回整串），
    只是拿到错误的"扩展名"。
  - ✅ `screenshot_gallery.py`：`set_paths` 不再静默丢弃磁盘上已失效的截图路径 ——
    现在**保留条目并标注「⚠ 已丢失」+ tooltip 给出文件路径**，由用户自己决定是否删除；
    `get_paths` 照常序列化，杜绝"用户无感知、保存时把路径写没"的变相删数据。

- **O-9【文档过时】✅ 已修（§3 改 17 项）** —— Dashboard KPI 是 17 项，不是 18 项：
  `ui/views/dashboard.py` 的 `metric_keys` 实测 17 个
  （净额/毛利/手续费/收益率/胜率/盈亏比/最大回撤/交易次数/盈利次数/亏损次数/初始资金/
  平均盈利/平均亏损/最大单笔赚/最大单笔亏/平均持仓/最长持仓）。

- **O-10【性能 · 未动，列入第三梯队】复盘页回放与交易日历反复全量读 Parquet**：
  `_render_trade_playback`（`review.py:999-1007`）每选中一笔交易就
  `data_lake.load_data("kline_daily", root)` 读整份历史；
  `_trading_dates_for`（`:607-621`）首次访问某品种时也要读一份（虽有 `_trading_cal` 缓存日期，
  但读文件这一步没省）。同月内连点 20 笔交易 = 20 次全量 IO。
  建议：按 symbol 做一份 LRU 缓存（只缓存 df 或只缓存 date 列），或至少复用
  `_trading_dates_for` 已经读过的那份。

- **✅ v5.12 已逐项核对"通过"（未来的我不必再查）**：
  ① 净额口径：`analyzer.py` / `dashboard.py` / `review.py` 图表 / `yearly_review.py` 四处全对；
  ② 幂等：`INSERT OR IGNORE` + `internal_id` MD5（切片 `#i` 盐）仍在；
  ③ FIFO 全局排序只跑一次（`data_feed.py:767-771`）；
  ④ 孤儿四层防御齐全（标记/黄条/补录/自动缝合）；
  ⑤ 同步两大铁则：`fresh_within_days=0`、空增量=skipped 均健在（`sync_service.py:68/159-186`）；
  ⑥ 数据起点 2010 未被改回；
  ⑦ 勾选中自绘 ☐/☑ + 唯一切换入口 + `NoSelection`（`data_manager.py:202/360/403`）；
  ⑧ 危险动作隔离 + 键入「清空」二次确认；
  ⑨ 退市/无数据的人话文案（`friendly_fetch_message`）已接入 4 处；
  ⑩ 版本号两处同步（1.4.1 = 1.4.1）；⑪ `scan_cache` zone 仍不存在（属 B1 前置，非欠账）。

### v6.1 第三次核对产出（"文档 ↔ 磁盘"第三次全仓对账 · 无业务代码变更）

> 背景：为 §7-B3 新架构动工前做的一次全仓复核。**结论：核心链路（净额统计 / 幂等 /
> FIFO / 孤儿 / 同步语义 / 线程收口 / 导出 / 图表样式收敛）全部健在**，下列均为
> "展示层 / 文档"级别漂移。

- **P-1【口径漂移 · 净额】✅ 已修（v6.9）** —— §5.3-B 宣称"全站再无例外"，但**逐笔展示层**
  仍有 3 处用毛利 `net_profit` 判正负（复查时实测确认**仍全部存在**，共 5 个代码点）：
  - `ui/views/records.py:389`：盈亏列**着色** `net_profit > 0`；
  - `ui/views/review.py:731/746/752`：当日交易列表的 `+` 前缀与颜色；
  - `ui/views/review.py:1062-1063`：回放图标记色 / 高亮带方向。
  后果：毛利 +100、手续费 150 的单子（净额 −50）会显示成**绿色盈利**。
  **v6.9 修法**：新增 `core/utils.record_net_amount(record)`（全站唯一取值口径），
  上述 5 点 + 复盘页详情头（`review.py:835`，本轮新发现）全部改净额；
  且流水页盈亏列**改显示净额并把列名改为「净盈亏」**（否则"数字是 +100、行是红的"自相矛盾）。
  回归断言进 `smoke_chart.py`（Series/dict/TradeRecord/NaN/缺失键 6 项）。
- **P-2【文档数字错】** §4 曾写 `FUNCTIONS(17)`，实际 `core/formula/runtime.py` 注册表
  为 **16 个**（§5.2 的"16 个"是对的）。**§4 已改**。
- **P-3【行数漂移】** §4 / §6.4 / §11.4 的行数已按 v6.1 实测重刷（见 §4）。

### v6.5 事故记录（存量函数回归 —— 由 v6.4 的"静默→报错"改造引发）

> 本项目迄今**用户体感最差**的一次回归，完整记录以便永不再犯。
> 触发链：v6.4(P1) 把 SKIP 改成"报错" → 用户**已保存的函数**报错 → 检测失败 →
> `start_backtest` 依赖检测成功、直接 return ⇒ 用户感受是"函数突然全废"。

- **Q-1【根因·解析】绘图语句的"尾部颜色属性"没被摘掉就送进了解析器**
  通达信允许 `STICKLINE(状态, P1, P2, 3, 0), COLORFF0000;` —— 逗号后的 `COLORFF0000`
  是**绘制属性**，不属于表达式。v6.4 的 `_compile_draw` 却把**整条语句**丢给 `parse()`，
  解析器在顶层逗号处必炸：`公式末尾存在无法解析的内容: ',' (位置 49)`。
  旧版整行 SKIP（虽然"画不出图"，但至少能跑），所以这是**行为收窄导致的破坏性回归**。
  **修法**：新增 `_split_draw_attrs()`，先按**顶层逗号**（`_find_top_level`，括号外）
  把尾巴切出来交给 `draw.parse_attrs()`，只把 `call_text` 送进 `parse()`。
  **纪律（§11.5-14①）**：OUTPUT 与 DRAW 都**必须先摘属性尾巴再解析**。

- **Q-2【策略】"未知绘图函数硬报错"过于激进**
  v6.0 定稿时写的是"未知绘图函数一律报错"，但真实存量函数里含 `DRAWTEXT/DRAWBAND`
  这类**本期不实现**的函数时，用户会再次"全废"。
  **修法（v6.5 修订 v6.0 该条）**：已知但未渲染的绘图函数 + 尚未收录的"调用式"语句 →
  登记 `DrawSpec(kind='unsupported')`，UI 在检测结果里给**非阻断提示**
  （"⚠ 本期不渲染 N 处: DRAWTEXT、DRAWBAND"，完整文案进 tooltip）。
  只有**完全不像函数调用**的语句才报错 —— 这样"绝不静默"与"不掐死存量"同时成立。

- **Q-3【隐患·渲染】`STICKLINE(cond, P, P, w, 0)`（价1==价2）会画出"看不见的图"**
  这种写法在通达信里是"在该价位画一段**横杠**"（用户那 4 根彩色状态柱就是这么写的），
  而 v6.4 的 `_StickItem` 会得到 0 高度矩形 → 渲染为空 ⇒ 即便解析修好了，
  用户**依然看不到状态柱**。**修法**：`y1-y0 ≈ 0` 时改画 cosmetic（像素宽、不随缩放变粗）
  的**水平线**，粗细按 `width` 取 1~3 px —— 既忠于 TDX 语义、又保证可见。

- **Q-4【流程教训】"把警告升级为错误"的改动，必须拿存量样本回归**
  本次是靠用户实测才暴露的。此后任何影响 `parse_program` 行为的改动，
  **上线前必须拿 `实例函数.txt` 端到端跑一遍**（已加入 §11.7 自检清单）。
  ⚠ 同时注意 §10-6 隐私铁律：用户私有公式**不得**写进仓库/示例/smoke 脚本，
  只能临时脚本验证后立即删除。

### v6.7 用户实测反馈产出（P5 前置 · 对话框返工）

> 用户原话："自定义公式叠加里的 UI 存在重大的设计与排版问题……内容重复，使用无引导，
> 界面设计丑陋"；以及"函数只能添加到主图……副图函数叠加到主图，坐标轴差距特别大时严重影响使用"。
> 下面 3 条都是**真实缺陷**（不是审美偏好），已修并固化成断言。

- **R-1【Bug · 僵尸控件】`FunctionSegments.set_texts()` 会留下可见的重复段**
  现象：对话框里出现两个「· 函数段 1」（用户截图）。
  根因：`layout.removeWidget(w) + w.deleteLater()` —— `removeWidget` 只解除**布局管理**，
  控件仍是父控件的**可见子对象**，直到事件循环真正删除它。诊断证据：
  `_seg_box` 下 2 个 `has_editor=True` 且 `isVisible=True` 的子控件，而布局只管理 1 个。
  **修法**：`w.setParent(None)`（立刻脱离父级 → 不可见）**再** `deleteLater()`。
  同一处 `_remove_segment()` 一并修。**固化**：断言"直接子控件数 == 布局管理数"。

- **R-2【Bug · 版面塌陷】多余高度被塞进段内部，标签与编辑框之间出现大片空白**
  现象：`wrap` 实测高度 **378**，而其 `sizeHint` 只有 **115**（膨胀 3.3 倍）；
  标签停在顶部、编辑框被推到下面。根因：编辑框 `setFixedHeight(96)` ⇒
  段容器分到多余高度时**没有任何子控件能承接**，Qt 只能把空档摊在段内部。
  为什么回测页没发现：那里 `FunctionSegments` 包在 `QScrollArea` 里，子控件只拿到 sizeHint。
  **修法**：`Expanding` 纵向策略 + `setMinimumHeight(110)` —— 多余高度**直接变成编辑面积**。
  **固化**：断言"编辑框 top < 60"且"编辑框高度 ≥ 110"。

- **R-3【设计 · 无引导】用户不知道该把函数放主图还是副图 ⇒ 主图被压扁**
  现象："副图函数叠加到主图，坐标轴差距特别大，严重影响使用"。
  **修法（三层）**：
  ① **入口引导**：对话框新增「目标窗格」下拉 + **随选动态说明**（选主图/副图分别解释适用场景）；
  ② **示例模板**：📋 菜单内置「主图指标示例（均线叠加）」与「副图指标示例（MACD 柱+线）」，
     选模板会**自动把目标窗格切到对应值** —— 用例子教，比堆说明文字有效；
  ③ **事后兜底**：应用后若目标=主图但数值量级明显不对（差 3 倍 / 完全错位），
     面板直接提示"⚠ 数值与股价量级相差很大 · 建议改用副图"，完整解释进 tooltip。
  判据落在纯函数 `ui/widgets/chart_layers.scale_mismatch_hint()`（可单测）。

- **R-4【能力 · 副图叠加】公式从"只能进主图"升级为"可选主图/副图"**
  `market.py` 在既有窗格体系上新增「公式副图」窗格：`setXLink` 联动主图、
  **y 轴独立**（这正是治好"压扁 K 线"的根因）、数值跨 0 时给一条零轴参考线。
  渲染仍走**同一个** `OverlayPainter`，只是换了 pane —— 没有为副图新开一条绘制路径（§10-11）。
  ⚠ 该窗格沿用 market.py 既有的 `addPlot` 写法（与 vol/macd 一致）；
  **P8 重做时统一收编进 `ChartHost`**（§10-12），此处不为赶进度做半截迁移。

### v6.8 收工前用户反馈（全 App 坐标轴普遍性缺陷 · 立项 §7-B4）

> 用户原话："行情数据中心的图表确实抓取了很完整的股票数据，也顺利展现了出来，
> 但用户一旦**放大去看局部时间**，对应的**横竖坐标轴都会固定**……关键坐标轴数据标注不清，
> 放大后的**比例控制完全失衡**。这一点不仅在这个地方，在 Jian 里**普遍存在**。"
> （附两张截图：全量视图正常；放大后横轴只剩一个无意义刻度"A"、公式副图整段历史压成一条线。）

- **S-1【横轴 · 静态刻度表】** `AxisItem.setTicks([...])` 在渲染时按**全量数据**算一次，
  之后**不随缩放更新**。放大到局部后，预设刻度全落在可视范围之外 → 横轴没有可读时间。
  波及：`ui/views/market.py`（行情主图，`range(0, len(df), step)` + `%Y-%m` 一次性写死）、
  `ui/views/review.py`（K 线回放 / 资金 K 线，两处）。
- **S-2【纵轴 · 量程不随可视窗口重算】** pyqtgraph 的 autoRange 天然"装下全部数据"，
  **不会**因为 x 被放大就重算 y。放大时间轴后 y 轴"固定"在全量极值上 ——
  副图最明显：跨 6 年的公式指标被压成一条看不见的线。
  波及：行情页（无任何 y 跟随）、复盘页。**只有回测页做了**
  （「价格轴跟随可视区间」`chk_follow` → 按可视 bar 的 high/low 重算 y）。
- **S-3【密度与精度不自适应】** 横轴日期格式（年/月/日）、纵轴小数位都是写死的；
  缩放级别变了，刻度该变密/变疏、该换格式，但没人管。
- **为什么"普遍"**：全 App 的 x 轴都是 **bar 序号**，日期只是"序号 → 文本"的映射，
  pyqtgraph 不知道这层映射；而我们只在**回测页**手写对了一次
  （`backtest.py:1397-1475`：`sigXRangeChanged → 重算 ticks + 自适应格式`）——
  **正确方案存在，但没抽成公共件**，于是"改一处漏三处"（§9-O7 的同款教训）。
  ✅ 已对（参考实现）：回测页 K 线页签 + 净值曲线。
  ✅ **已收敛（v6.15 · §7-B4 收官）**：行情工作台主图/量/MACD/公式副图、复盘页 K 线回放、
     复盘页资金 K 线 —— 全部改走 `ui/widgets/adaptive_axis.py`；回测页两处也改为调用其纯函数。
     **全 app 只剩 `adaptive_axis.py` 一处"算"刻度与量程**（业务页面不再自己算；
     回测页仍把公共函数算好的结果推给轴 —— 页面只是搬运工，算法只有一个副本）。
  ➖ 静态但**合理**（不修）：策略对比图的"策略名"轴、年度复盘的"策略名"轴（类别轴本就静态）、
     复盘页持仓时长直方图的"可读时间刻度"（对数参考轴，锚点固定才是可读的）。

### v6.9 第三次"陌生代码"复查产出（文档 ↔ 磁盘对账 + 小债清账）

> 背景：按 §9-M 立下的规矩（跨会话/跨模型改动前先"不信自己人"地重审），本轮把全仓 31 个 .py
> 与文档逐条对账。**结论：核心链路（净额统计 / 幂等 / FIFO / 孤儿 / 同步语义 / 线程收口 /
> 导出 / 图表四层 / P0–P5）全部健在**；发现 4 项，其中 3 项已修、1 项登记待办。

- **T-1【控件 · 已修】"半截 QSS"让下拉箭头**整个消失**（不只是图标漂移）**：
  `QComboBox / QDateEdit / QDateTimeEdit` 是复合控件 —— 一旦用 QSS 触碰 `::drop-down`，
  Qt 就切到样式化绘制路径；此时**若不同时给出 `::down-arrow`，箭头不会被绘制**。
  **离屏实测证据**：右侧 30px 带内最小亮度 —— 原生 93 / 仅写本体 85（有箭头）/
  加 `::drop-down` 后 **230（零深色像素 = 没有箭头）**。
  线上受害点：`review.py:81`（复盘页**时间选择器**）、`manual_entry.py`（手工录入弹窗的
  下拉与日期时间控件）。
  **修法**：`custom_widgets` 新增 `combo_qss()` / `date_edit_qss()` 生成器，**强制**
  `::drop-down` 与 `::down-arrow` 成对出现；箭头用 **border 三角**绘制（纯 QSS、无图片资源、
  不引入二进制文件）。负向对照断言已固化（"只写 `::drop-down` 就看不到箭头"）。

- **T-2【体验 · 已修】NoWheel 替换留了尾巴**：`review.py` 的孤儿补录日期用裸 `QDateEdit`、
  `manual_entry.py` 的时间与 5 个数值框用裸控件 —— 悬停滚轮会**误改关键参数**。
  已新增 `NoWheelDateTimeEdit` 并全部换入（§6.6-U2 补齐）。

- **T-3【能力闲置 · 已修】行情页没接线十字光标**：`ChartHost` 的跨窗格十字光标是 P2 产物，
  但 `market.py` 构造时没传 `crosshair=True` ⇒ 用户实际看不到。已接线（一条参数）。

- **T-4【登记待办】✅ ① 已修（v6.10 · 用户拍板"红线不放宽"）**：
  ① ~~`ConstituentsWorker` 直接调 `AkShareFeed.fetch_index_constituents()` 绕过门面~~
  → **收编**：`MarketSyncService.fetch_index_constituents()` 成为**联网抓取唯一入口**，
  `ConstituentsWorker` 只调度、不再 import 行情源；`ui/` 全层零 `AkShareFeed`
  （`smoke_chart.py` 有源码级断言守门）。失败文案分类：网络 vs 行情源未收录（§10-10）。
  **口径定稿**：§9-H 红线维持绝对措辞 —— **任何联网抓取（含一次性名单查询）都必须经
  `MarketSyncService`**，不得以"它不是行情序列"为由开例外。
  ② 【仍待办】`FuturesImportWorker` 的 docstring 声称"只做 Excel 解析、落库交主线程"，但
  `run()` 调 `engine.parse_cfmmc()`，其内部会读 SQLite（`load_open_legs`）—— docstring
  与事实不符（§9-J 同类）。⚠ 它**不是**"UI 直连联网"问题（读库、且 `engine` 是门面），
  下次顺手改 docstring 或把 `load_open_legs` 移到解析后。
  ③ 【仍待办】§9-O10 复盘页 Parquet 无缓存（文档已如实登记，仍属第三梯队）。
  ④ **行数口径澄清**：§4 的行数一律为**非空行**（实测确认）。重算命令：
  `Get-Content <file> | Where-Object { $_.Trim() -ne '' } | Measure-Object`。
  ⑤ 【新坑 · 已固化 §11.5-18】`dates or []` / `points or []` 遇到 pandas Series 会抛
  `truth value is ambiguous` —— 首次接线标注层时真实踩到（行情页直接把 `df['date']` 传进来）。

### v6.15 §7-B4 坐标轴自适应落地产出（用户截图驱动 · 全 App 收口）
- **S 类问题全部清零**：v6.8 记的 3 处"待修静态 ticks"（行情主图 / 复盘 K线回放 / 复盘资金K线）
  已全部改为自适应；回测页两处（已是对的）也收敛到公共件，**"正确实现只有一个副本"**。
  类别轴 2 处 + 对数参考轴 1 处按 §7-B4 边界**不动**（类别轴静态是合理的）。
- **【新发现 1 · 会咬人的默认值】`ViewBox.setYRange` 偷偷加 padding**：写完断言当场撞上 ——
  期望 99.4~110.6，实测 98.77~111.23。探针定位（一次性脚本，跑完即删）证实 pyqtgraph 在我们
  给的范围上**再叠一层 defaultPadding**，且幅宽随 `autoPadding` 状态漂移（同调用不同顺序差 0.2%）。
  ⇒ 统一 `padding=0`，量程完全由自己算；已固化 §11.5-21。**教训：凡"设了范围又要断言"的 API，
  先确认它有没有隐藏加成。**
- **【新发现 2 · 名字骗人】"资金 K 线"不是日期轴**：它的 x 是 `trade_time.dt.day` 分组后的
  **当月第几日**（`2日 / 5日 / 9日…`，只含当月有交易的日），标签格式"N日"是**正确**的语义。
  套 `%m-%d` 反而会说谎 ⇒ 公共件增设 `texts=` / `compute_text_ticks`（只做**密度自适应**：
  原来把当月每个交易日的标签全写上，窄窗口必定互相压字）。
- **【设计选择】provider 契约而不是"公共件猜业务"**：每个窗格的数据形状不同（K线用 high/low、
  量柱以 0 为基线、MACD 必须含 0、公式副图用 `overlay_extent`、复盘回放要并入入场/出场参考线），
  因此公共件只负责"拿到 (lo, hi) 后加 6% 落到轴上"，**"是什么范围"由页面回答**（一行 lambda）。
  这样新增图表类型不必改公共件。
- **【幂等保护】重复 attach 同一条轴 = 自动替换旧跟随器**（`weakref` 登记表）：
  页面每次重渲染都是"无脑 attach"，不会累积信号连接（这类泄漏在 Qt 里表现为"越用越卡"，
  且缩一次触发 N 次重算）。`handle_for(pane)` 是登记表唯一对外读口，供断言与后续调参。

### v6.14 全仓文件归置复查产出（用户发起 · 零业务代码变更）
- **触发**：用户反馈"根目录存在许多未分类文件"。全仓扫描后定性为**三类**问题，逐类处理如下。
- **A【位置不对】根目录混放了四类完全不同的东西**：代码入口、运维脚本、验收脚本、私有样例
  全平铺在同一层。**修法**：立 §10-13 规范 → 新建 `scripts/` `tests/` `samples/` 三个角色目录，
  根目录收敛为白名单（5 文件 + 4 层目录 + 3 角色目录）。移动一律走 `git mv`（保留历史）。
- **B【乱放无用文件】两处**：① 根目录 `screenshots/` 空壳目录（§9-C 早在 v6.1 就记为"历史遗留"，
  一直没人删 —— **登记不等于清掉**，这次删）；② 全仓 `__pycache__`（10 个）在编译校验后残留。
- **C【分类不细致】`ui/widgets/` 17 文件平铺**（图表件 7 / 控件 3 / 业务展示 4 / 公式 1 / 其它 2）：
  可再分 `ui/widgets/chart/` 子包，但**涉 51 处 import 点**且会牵动 §7-B3 四层表的路径锚点，
  收益中成本中 → **登记待办、本轮不做**（避免为整理而整理，耽误 §7-B4 坐标轴）。
- **D【移动脚本的连带坑 · 已固化 §10-13】**：`smoke_*.py` 从根目录挪进 `tests/` 后
  `sys.path[0]` 从"仓库根"变成"tests/"，`from core.formula import ...` 会当场 ImportError；
  `smoke_chart.py` 里还有 `Path(ROOT) / "ui"` 的**源码级扫描断言**（§9-H 守门），
  ROOT 一旦定义错，这条断言会静默扫到空目录 → **守门失效而不报错**。
  修法：`ROOT = dirname(dirname(abspath(__file__)))`，两个脚本 + `sync_roster.py` 三处同批改。
- **E【用户可见文案也要跟着改】**：`bulk_download.py` 的空态提示原为"请先运行 sync_roster.py"，
  文件挪走后这句会**指向不存在的路径**（用户照做必然失败）。同批修 `core/engine.py` docstring、
  `data/watchlist_store.py` 注释。**教训：路径改名要按"引用图"过一遍，不能只改 import。**
- **F【无死代码】**：用"模块名全仓引用扫描"核对 —— 除两个独立入口脚本外，**所有 py 都被引用**；
  `ui/views/backtest_module.py`(83) 看似可疑，实为 M1/M2/M3 子页容器（`main_window` 在用），**保留**。
- **G【.gitignore 收紧】**：原来靠"逐个文件名模式"（`实例函数.txt` / `*交割单*.xlsx` …）防隐私泄露，
  **漏一个模式就泄露一个文件**；改为 `samples/*` + `!samples/README.md`（整目录忽略、只放行说明）。
  另新增 `_tmp_*` 兜底：会话期一次性探针脚本/重定向输出**不允许沉淀在仓库**（v6.13/v6.14 都曾出现）。

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
   - **根目录白名单（只允许这 5 个文件 + 4 个层目录 + 3 个角色目录）**：
     `main.py`（唯一入口）、`requirements.txt`、`version.json`（发布物，直链指向此处 **禁止移动**）、
     `JIAN_RULES.md`（唯一权威记忆，**故意**放根：第一眼要看见）、`.gitignore`；
     层目录 `config/ models/ core/ data/ ui/`；角色目录 `scripts/ tests/ samples/`。
     **其它任何文件出现在根目录 = 归置错误。**
   - **三个角色目录的判据**（这是最容易搞混的一步，按"谁去调用它"分，不按它像什么分）：
     | 目录 | 判据 | 例子 |
     |---|---|---|
     | `scripts/` | **只给人手动敲命令**、不进 app 的 import 图 | `sync_roster.py`（花名册同步） |
     | `tests/` | 人工运行的**验收/冒烟**脚本 | `smoke_chart.py`、`smoke_pages_overlay.py` |
     | `samples/` | **是数据不是代码**、且属用户私有/隐私 | 实例函数 `.txt`、实例交割单 `.xlsx` |
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
| 给页面加后台任务 | `ui/workers.py` —— 全 app 唯一 QThread 定义处（Scan/Sync/SingleSync/BacktestRun/Constituents/FuturesImport 六个 Worker），**禁止页面自造线程类**（§9-O2） |
| 改版本号 | **三处同批同步（§9-A v6.16 新纪律）**：git commit message 首词 · `config/settings.py` 的 `APP_VERSION` · 仓库根 `version.json`。取值 = 上次 push 的版本 **+0.01**（形如 `1.20` → `1.21`） |
| 回测页 UI | `ui/views/backtest.py`（⚠ **1570 行，全仓最大业务文件**，先想清楚插在哪一段；结构顺序=顶部工具栏→①函数→②条件→③指数→运行条→风控行→KPI→K线控制→结果页签→导出按钮。**§9-L 拆分首选对象**） |
| 行情工作台页面 UI / 公式叠加 / 自选 / 周期 / 画线工具栏 | `ui/views/trading_desk.py`（⚠ **898 行，P8 新页；旧 `market.py` 已删除，别再"找回"它**）+ 编辑器 `ui/dialogs/formula_overlay.py` |
| 自选股（增删/排序/名称） | `data/watchlist_store.py` —— 顺序 = 用户关注顺序；`update_name()` 在花名册刷新后同步名称（旧名不当真相）。⚠ 与"花名册 `market_symbols`（全市场）"是两回事 |
| 行情周期（日/周/月） | `core/utils.resample_ohlcv`（纯本地聚合，列名与日线一致 ⇒ 下游零改动）。**纪律：指标必须在聚合之后算**，否则"周线 MA5"会变成"日线 MA5 被抽样" |
| 行情复权（前复权/不复权） | **`data/sync_service.zone_for_adjust(adjust)`** → 分区（`kline_daily` / `kline_daily_raw`）+ `ADJUST_QFQ/NONE` + `adjust_label`。**页面禁止自己拼分区名**（§11.5-19）。⚠ 想加第三种口径（如后复权）= 加一个常量 + 一个分区，**不要**在原分区里加列 |
| 抓取时的复权口径 | `akshare_feed` 的 `adjust` 参数，必须**透传到新浪与东财两个源**（`fetch_a_share_daily` 内部两个分支都用同一个 `adjust`）—— 否则主源失败降级时会**静默换一种复权**，这是最阴的数据事故 |
| 让图元"跟着鼠标走"（pyqtgraph） | `ItemIsMovable` **不管用**：pyqtgraph 覆写了 `mouseMoveEvent` 且不调父类实现，Qt 内建移动逻辑根本不执行。必须自己实现 `mousePressEvent`（记起点）→ `mouseDragEvent`（按 `scenePos − buttonDownScenePos` 改坐标）→ **`isFinish()` 时才回调落盘**。参考 `annotation_layer._ClickableText` |
| 加一种新的画线类型 | ① `data/annotations.py`：加 `KIND_*` + `REQUIRED_POINTS`（+ 若有序语义常量，像 `FIB_RATIOS` 一样放模型层）；② `ui/widgets/annotation_layer.py`：加进 `DRAWABLE_KINDS`，并在 `_draw_item`/`_points_from_graphic` 各加分支；③ 工具栏下拉**自动跟着变**（它读的就是 `DRAWABLE_KINDS`，别手写第二份）。⚠ 附属图元必须登记 `_extras`，随主图元一起删 |
| 标注的"周期键" | `data/annotations.period_key()`（任何写法 → `daily`/`weekly`/`monthly`）；页面只管传 `'D'/'W'/'M'`。**别绕过它直接拼字符串**（§11.5-19） |
| 内置指标 → 绘图 IR / "该放主图还是副图" | **`ui/widgets/chart_layers.py`**（v6.7）：`builtin_indicator_layers()` / `layer_value_range()` / `scale_mismatch_hint()`。**别在页面里自己算**（页面只留开关与窗格编排） |
| 多段函数编辑器（含"段"的增删） | **`ui/widgets/function_segments.py`** —— 回测页与行情页公式编辑器**共用**；⚠ 改它前请读 §11.5-15（删控件必须 `setParent(None)`；容器给多余高度时必须有可伸缩子控件） |
| 复盘页 UI | `ui/views/review.py`（⚠ **1067 行**；`_build_monthly_mode` 月视图 / `YearlyReviewPanel` 年视图 / `_render_trade_playback` 回放三块最重） |
| M2/M3 新子页 | `ui/views/backtest_module.py` 里换掉 `_ComingSoonPage` |
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
| 改回测结果导出 | CSV：`ui/views/backtest.py` `_compose_result_csv`（纯函数）+ `_last_meta`（配置快照，`start_backtest` 定格）；PNG 报告图：**`ui/widgets/backtest_report.py`**（离屏 grab 渲染）；标签/配色/风控文案只改 **`core/backtest.py`**（三处同源） |
| 判断"这笔是赚还是亏"（任何着色/正负号/标记色） | **`core/utils.record_net_amount(record)`**（v6.9）—— 净额 = 平仓盈亏 − 手续费的**唯一取值口径**。**禁止**再手写 `net_profit > 0` 或 `net_profit - commission`（§5.3-B / §9-P1） |
| 改下拉/日期等复合控件的外观 | **`ui/widgets/custom_widgets.py`**：用生成器 `combo_qss()` / `date_edit_qss()` 造新变体，或直接引用 8 个具名常量（`COMBO_QSS` / `COMBO_QSS_SMALL` / `COMBO_QSS_ACCENT` / `COMBO_QSS_EDIT` / `COMBO_QSS_EDIT_OK` / `LINE_COMBO_QSS` / `DATEEDIT_QSS_WARN` / `DIALOG_INPUT_QSS`）。**业务页面禁止就地 setStyleSheet**，且 `::drop-down` 与 `::down-arrow` 必须成对（v6.9：否则箭头消失，§10-9） |
| **给图表加自适应坐标轴**（刻度随缩放变密/换格式、纵轴跟随可视区间） | **`ui/widgets/adaptive_axis.py`（§7-B4 · v6.15）一处**：`attach_date_axis(pane, dates / texts, y_provider=…)`、`follow_y(pane, provider)`、`attach_all(host, dates, providers_by_pane)`。页面只写 `provider(i0, i1) -> (lo, hi)`（回答"这个窗格在可视区间内数值范围是多少"）。**禁止再手写 `setTicks` / `setYRange`**；日期格式梯子只在该文件的 `choose_date_format`（将来分钟线只改这里） |

### 11.5 最容易踩的坑（血泪，别重犯，**持续累积** — 不写条数上限，写了必然滞后）
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
8. **行情同步两大铁则**（§9-M，改 `sync_service.py` 前必读）：
   ① "已最新"判据必须是**末日==今天**（`fresh_within_days=0`）——放宽=增量永远滞后一天拿不到当日 bar；
   ② **空增量 = 已最新不是失败**——增量模式只请求一次、空返回即 `skipped`，不重试不熔断。
   数据起点保持 2010（个股全历史），评估窗才是 2016，两者别混。
9. **别让两套机制同时 toggle 同一个选择状态**（§9-N1）：Qt 原生 indicator 点击会**自动切换**，
   若你再监听 `cellClicked` 手动切换一次 = 双重触发 = 等于没点。要么只用原生、要么（推荐）
   完全自绘（☐/☑ 字符 + 整格点击唯一入口），且关掉行选择以免出现难看的选中高亮。
10. **别照着 docstring 改常量**（§9-O3 血的教训）：`sync_service.refresh_one` 的 docstring
    一度把数据起点写成 2016 而实际常量是 2010（v5.13 已改正）。**改任何常量前先看代码本体，
    再从代码反向修文档**；反过来做就是"静默回归"。
11. **同类防护要做就做全套**：`market.py` 有"同步结果 vs 当前标的"的竞态守卫，
    `backtest.py` 同场景却漏了（§9-O5，v5.13 已补齐）。加防护时全局搜一遍同一场景还有几处。
12. **图表样式只改 `ui/widgets/chart_style.py`**（§9-O7）：此前 4 处重复、改一处漏三处。
    且行情页传的是 **PlotItem**（`GraphicsLayoutWidget.addPlot()` 的返回值）不是 PlotWidget ——
    给图表封装公共函数前先想清楚"调用方手里到底是哪种类型"。
13. **【v5.13 修订 · Qt 布局坑】顶部栏末尾的 `QLabel` 会"吞掉"主区高度**：
    页面顶部一条 `QHBoxLayout`（搜索栏/标题/工具按钮），下方是 `QSplitter` 主区，
    只要顶部栏的**末尾**多了一个 `QLabel`（vertical sizePolicy = Preferred，而按钮/复选框是 Fixed），
    Qt 会把整段富余垂直空间全部分给顶部栏，标题会被拉到几百像素高、主区被压成 sizeHint。
    触发条件是"QLabel 在末尾"，换位置/换按钮都不会。
    **根治**：主区 widget 永远显式 `layout.addWidget(main_widget, 1)` 给 stretch>0，
    富余空间才不受 Qt 启发式影响。`backtest.py` 本来就这么写所以没翻车，
    `market.py` 原本忘了写，被 v5.13 新增的同步状态 QLabel 一脚踢翻。
14. **【v6.5 · 最贵的一条】把"静默跳过"改成"报错"之前，先问一句"存量函数会不会被掐死"**
    （真实事故，详见 §9-Q）：P1 为了让"画不出图"不再静默，把 `program.py` 的 SKIP 换成报错
    —— 结果**用户已保存的函数**里 `STICKLINE(...), COLORFF0000;`（通达信允许的**尾部颜色属性**）
    被解析器拒收，而 `start_backtest` 依赖检测成功 ⇒ 用户"函数突然全废"。
    三条纪律：
    ① **解析任何语句前，先把"属性尾巴"摘掉**（顶层逗号之后），别把整条语句喂给 `parse()`；
    ② **容忍优先于报错**：已知但本期不实现的绘图函数 → 登记成"未渲染"并**提示**，
       不要 hard fail；只有"完全不像函数调用"的垃圾才报错；
    ③ 任何"把警告升级成错误"的改动，**上线前必须拿存量样本跑一遍**（本次是 `实例函数.txt`）。
15. **【v6.7 · Qt 动态控件的两条硬纪律】**（真实 Bug，用户截图驱动，见 §9-R）
    - **删除子控件必须 `setParent(None)` 再 `deleteLater()`**：只写
      `layout.removeWidget(w) + w.deleteLater()` 的话，在事件循环真正删除前，
      `w` 仍作为**可见子控件**挂在父控件上（只是不再受布局管理）—— 表现为
      "界面上凭空多出一个一模一样的控件"（本次 = 对话框里两个"函数段 1"）。
      **自检**：`parent.findChildren(QWidget, FindDirectChildrenOnly)` 的个数
      必须等于"布局里管着的个数"。
    - **容器分到多余高度时，必须有可伸缩的子控件来承接**：若子控件都是固定高度，
      Qt 会把空档**塞进容器内部**（标签被顶到最上、输入框被推到几百像素之外）。
      修法二选一：① 让真正该变大的控件 `Expanding`（**优先**，多余空间变成可用面积）；
      ② 在末尾 `addStretch(1)`（保底，只把空档赶到尾部）。
      ⚠ 这类问题**在滚动容器里不会显形**（子控件拿到的是 sizeHint），
      同一个组件搬到普通对话框就会暴露 —— 所以**给容器换环境时要重新看版面**。
16. **【v6.8 立项 / v6.15 已根治 · pyqtgraph 坐标轴的三个默认行为，全都不是我们要的】**
   （§7-B4 已落地，见 §9-S / §9-v6.15）
   ① `AxisItem.setTicks([...])` 是**一次性静态数据**，**不会随缩放更新** —— 我们的 x 是
   "bar 序号 + 日期映射"，pyqtgraph 不知道这层映射；放大后预设刻度全跑到可视范围外，
   横轴就只剩一个无意义刻度。**必须自己监听 `sigXRangeChanged` 重算**。
   ② `ViewBox` 的 autoRange 以**全量数据**为基准，**不随可视 x 窗口重算** —— 放大时间轴后
   y 轴"看起来坏了/固定了"，其实是没人告诉它"用户现在只看得到这一段"。
   ③ 刻度密度与数字精度**不会**随缩放级别自适应，得按轴的像素长度和可视跨度自己算。
   → **统一解法（已落地）= `ui/widgets/adaptive_axis.py`**：
   `attach_date_axis(pane, dates|texts, y_provider=…)` / `attach_all(host, dates, providers)`；
   **禁止再在业务页面里手写 `setTicks` 或 `setYRange`** —— 页面只需回答
   "该窗格在可视区间内的数值范围"（provider 契约）。
   现存 3 处静态 ticks 已全部收敛（行情主图 / 复盘 K线回放 / 复盘资金K线，v6.15）；
   回测页两处（K线 / 净值）也已改为调用公共纯函数；另有 2 处类别轴（策略对比 / 年度复盘）
   与 1 处对数参考轴属"合理静态"，**不改造**（§7-B4 边界）。
17. **【v6.9 · 复合控件样式的"半截"会让箭头彻底消失】**（真实 Bug，§9-T1）：给
    `QComboBox / QDateEdit / QDateTimeEdit` 写 QSS 时，**只给 `::drop-down` 而不给
    `::down-arrow`，Qt 切到样式化绘制路径后箭头根本不会绘制**（离屏实测：箭头区域
    零深色像素）。这比"图标样式漂移"更隐蔽 —— 界面上看不出报错，只是**下拉控件看起来
    不像能点**（复盘页时间选择器、手工录入弹窗长期如此）。
    → **纪律**：① 复合控件样式**只准**用 `custom_widgets.combo_qss()/date_edit_qss()`
    或 8 个具名常量；② 要手写就必须 `::drop-down` + `::down-arrow` **成对**，箭头可用
    **border 三角**画（无需图片资源）；③ 新增变体后跑 `py tests/smoke_chart.py`，
    里面已有"箭头可见"的**像素级断言 + 负向对照**。
    附带教训：**凡是"样式改完看起来没问题"的判断，都要用离屏 grab 量像素证实一次** ——
    "肉眼没看出来"与"真的没坏"是两回事。
18. **【v6.10 · pandas Series 不能做布尔判断】**（真实踩到，P6 接线首日就炸）：
    写 `dates or []`、`points or []`、`x if x else y` 这类"空值兜底"时，只要 `x` 可能是
    **pandas Series**，就会抛
    `ValueError: The truth value of a Series is ambiguous`。
    本项目里 **UI 会把 `df['date']` 直接传进公共组件**（行情页 → 标注层 → `DateAxis`），
    所以公共件里**一律用 `x if x is not None else []`**，禁用 `or []`。
    同类高危写法：`if series:`、`series and ...`、`return series or default`。
    教训泛化：**公共件的入参要按"最脏的可能"来防御**（Series / list / None 都当输入），
    因为在页面里测不出来 —— 一接线才暴露。
19. **【v6.12 · 跨模块共享的"键"必须有规范化函数】**：周期在全 app 有三种写法 ——
    数据层 `'D'/'W'/'M'`、UI 中文 `日线/周线`、存储 `daily/weekly`。
    若各处自己拼字符串，就会出现"日线画的线跑到周线上""同一只票的标注读不出来"这类
    **静默串档**（数据没坏、界面上就是少了东西，最难查）。
    解法：`data/annotations.period_key()` 一个入口兜住**所有**写法，
    调用方（页面/图层）只管传自己那套；**禁止绕过它直接拼**。
    同类需要"规范化入口"的键：symbol（`watchlist_store.normalize_symbol`，大小写/空白）、
    日期（`annotations.normalize_date`）。新增任何跨模块键，先给它写一个 `normalize_*`。
20. **【v6.12 · 离屏 GUI 脚本的三条打桩铁律】"脚本看起来卡死、毫无输出"几乎总是这三件事**
    （本轮真实发生，用户以为是 VPN/网络问题，其实与网络无关）：
    - ① **模态框必须打桩**：`QMessageBox.*` / `QInputDialog.getText` 在离屏环境
      **没有用户可点 ⇒ 永久阻塞**。一条"浏览模式下点添加应给提示"的断言就足以让整个脚本挂死。
      做法：在脚本开头把 4 个 `QMessageBox` 静态方法 + `QInputDialog.getText` 换成
      "记录一下立刻返回"，并**把弹出的内容当断言素材**（比弹窗本身更有价值）。
    - ② **测试不碰网络**：主窗口构造会起 `UpdateCheckerThread`（请求 GitHub）。
      做法：构造窗口**之前**把 `ui.main_window.UpdateCheckerThread` 换成空实现
      （带一个 `update_available.connect()` 的哑信号）。测试不该依赖网络，也不该被网络拖慢。
    - ③ **结尾必须 `os._exit()`**：只要还有**非守护 QThread** 存活，解释器就不退出；
      而 `| Select-Object -Last N` / `| tail -n N` 会**缓冲到进程结束**才显示 ——
      于是"断言全过了"也表现为"长时间无响应"。做法：`sys.stdout.flush()` 后 `os._exit(code)`。
21. **【v6.15 · `ViewBox.setYRange` 会偷偷加自己的 padding】"y 怎么总比预期宽一点"**（真实踩到）：
   `view_box.setYRange(lo, hi)` 之后 `viewRange()` 拿到的**不是** `(lo, hi)` ——
   pyqtgraph 会在此基础上**再叠一层它自己的 defaultPadding**（实测 ≈2%~4.7%，还随
   `autoPadding` 状态漂移；同一次调用先后顺序不同，幅宽能差出 0.2%）。
   后果：凡是"我按可视极值 ±6% 设的"这类**可验证的口径**，都变成"永远差一点"的幽灵数值 ——
   断言没法写、调参也调不准（本次写 §7-B4 断言时当场撞上：期望 99.4~110.6，实测 98.77~111.23）。
   解法：**量程一律 `setYRange(lo, hi, padding=0)`**，把 padding 完全掌控在自己手里
   （`adaptive_axis` 已如此，且自己给 6%）。**凡是"设了范围又想断言它"的地方，都要显式 `padding=0`。**
    → **自检口诀**：离屏脚本"无输出"时，先怀疑**模态框**、再怀疑**残留线程**，
      **最后才怀疑业务代码**（尤其别一上来就怪网络/VPN）。
    22. **【v6.17 · 内部术语不许当"唯一解释"】**（用户实测反馈倒逼，详见 §10-10 追加条款）：
     成交模型第一版把 **"触发式条件单 / 触发跳数 / 买入当根不可卖出"** 原样摆到界面上，
     用户原话：**"用户完完全全都不知道"**。教训不是"功能不行"，而是**没做用户指引**。
     **可复制的四步模板**：
     ① **换量纲**：把内部单位翻译成用户单位（1 跳 → **0.01 元**；当根 → **当天**；
        "信号作废" → **"就不买也不卖"**）；
     ② **行内常显一句说明**，随选择**实时变化**（不是 tooltip —— tooltip 等于没解释）；
     ③ **配一个问句式教学弹窗**，用**一套固定数字**把几个档位摆在一起对照
        （§6.6-R3 已验证："用例子教"比堆说明文字有效）；
     ④ **参数按需出现**：只在真正有意义的档位可见，其余隐藏 —— 不给用户看不懂的常驻项。
     **可测代理指标**（写进验收脚本）：用正则断言"用户第一眼看到的文案里不出现行话"。
     ⚠ **检测要精确**：`「跳空」是交易者常用词`（用户自己就这么说），
     必须用 `跳(?!空)` 这类模式，否则会把常用词误判成行话。
     23. **【v6.18 · 复用公共工厂时，"写死的默认值"会咬人】**（用户实测倒逼）：
     `ui/views/backtest.py._risk_spin` 是回测页数值控件的**公共工厂**，里面把步长写死成
     `1 if decimals == 0 else 0.5` —— 对 1 位小数的百分比控件没问题，但新加的 **2 位小数**
     控件（成交模型的「买卖价要多等」，范围 0.01~0.20）**按一次上箭头就 +0.5 → 被上限夹住**。
     用户原话：「**直接跳到 0.2 并且无法继续上调，没有过度价格**」（差点被当成"图标坏了"）。
     **修法**：步长随 `decimals` 自适应（`0 → 1` / `1 → 0.5` / `≥2 → 10^-decimals`），
     并把上限由 0.20 放宽到 **1.00 元**（高价股的绝对价差也放得下）。
     **教训泛化**：公共工厂里的"经验默认值"一旦被用在**新的量纲**上就可能荒谬 ——
     新增一类控件时，把工厂里**每一个 `setXxx` 的隐含假设**都读一遍；
     数值控件**必须能逐级调节**，"一按就顶到边界"用户会直接判定为坏了。
     （断言：`singleStep` 随小数位自适应 + 连续 `stepUp` 逐级过渡 + 下限按到底不越界。）
24. **【v6.18 · 一次性探针的 `check(说明, 条件)` 参数顺序写反 = 全部断言形同虚设】**
    （本轮真实踩到，靠"**输出里说明文字变成了 `True`**"抓到）：探针里把 helper 定义成
    `def check(cond, desc)`，而所有调用处都是 `check(说明, 条件)` —— 于是**条件参数收到了一个
    恒真的字符串**，全部 `[OK]`，看上去"18 项全过"，实际什么都没验证。
    **三条纪律**：
    ① 探针的 `check()` 一律与仓库两个冒烟脚本保持**同一签名 `(desc, cond)`**，别自创顺序；
    ② **看输出**：断言说明必须是**人话**；一旦打印出 `[OK] True` 就说明参数顺序错了；
    ③ **凡"一次全过"都要警惕**：先挑一条**故意会失败**的条件跑一遍（或在心里过一遍
       "这条要怎样才能失败"），确认它不是恒真 —— 这与 §11.5-2 的"负向对照"是同一种疫苗。

### 11.6 当前"下一步做什么"的推荐顺序（历史刷新**倒序**排列：主清单之下**第一块就是最新**）

> ✅ ~~O-3/O-5/O-7/O-2/O-8 · O-1/O-4~~（v5.13） · ✅ ~~§7-A2 导出（CSV+PNG）~~（v5.14/5.15/5.16）
> **→ ⭐ 唯一主线 = §7-B3 图表架构总纲（P0–P8，2026-09-10 用户拍板）**：
> ✅ ~~**P0** `ChartPane` 最小抽象~~ · ✅ ~~**P1** 引擎 IR + 求值~~（v6.2 落地）
> ✅ ~~**P2** `ChartHost` 多窗格（主图+N副图 / x 联动 / 日期轴 / 十字光标）~~（v6.3 落地）
> ✅ ~~**P3** 渲染器 `draw_overlay.py` + 回测页 K 线接入（叠层开关 + y 自适应）~~（v6.4 落地）
> ✅ ~~**P4** 行情页公式叠层 + 内置/用户指标统一图层~~（v6.6 落地）
> ✅ ~~**P5** 多副图 + 窗格编排收编 ChartHost~~（v6.8 落地；量柱/MACD 仍用原生 BarGraphItem
>    是**明确保留的例外**，P8 统一）
> **→ 下一步：P6 标注持久化**（图形对象模型 + 按 `(标的, 周期)` 存 JSON + **逐个独立删除**；
> P0 的 ChartPane 已就位）→ **P7** 函数资产互送（公式配置持久化，顺手解决"公式重启就丢"）
> → **P8** 行情页重做。
> **→ P8 之后立即：§7-B4 坐标轴自适应**（全 App 普遍性缺陷；用户 2026-09-10 明确要求
>   "改完 P 步骤后一定要全面解决"）—— 行情页/复盘页的静态 ticks + 纵轴不随可视窗口重算。
> （⚠ `market.py` 仍 448 行越线：P6/P8 一律新建文件，不许再往里堆。）
> 主线之外的小修 / 常规项（**每项先聊方案再动手**）：

- 0. **§9-P1 净额残留 3 处**（records 着色 / review 当日清单 / review 回放标记）——
   纯展示层小改、无耦合，可随时插入主线之间。
- 1. §7-A4 回测结果历史存档（远期；动工前先问要"复现"还是"留档"）。
- 2. §9-O10 复盘页 Parquet LRU 缓存（体验向）。
- 3. §9-L 大文件拆分（`backtest.py 1570` / `review.py 1067` / `trading_desk.py 898`）—— 纯重构，与功能错开。
- 4. §7-B1/B2（M2/M3 真实功能）—— B1 需先建 `scan_cache` zone。
- 5. §6.5「远期」组合级多标的引擎 —— 全新模块，勿并入 M1。
> ⚠ §7-A1 涂鸦板持久化 **已被 §7-B3 的 P6 吸收并升级**（见总纲 B/C 两根柱子），不再单列。

**v6.19 刷新（提交发版 `1.21` 收工 · **下一轮 = 回测页 UI 大改**）：**
> ✅ ~~**§7-B5 回测成交真实性**~~：**步骤 0–5 全部收官**（立项 v6.17 / 落地 v6.18 / 发版 v6.19），
>   用户手动实测通过（原话"现阶段没问题"）。app 版本 = **`1.21`**（commit `1.21 回测策略更新`），
>   **已提交、未 push**。
> **→ 下一轮（用户 2026-09-15 已定方向）= `1.22`：回测页 UI 大改**：
>   · 范围 = `ui/views/backtest.py`（⚠ **1691 行，全仓最大业务文件**）+ `ui/views/backtest_module.py`；
>   · ⚠ **先出方案再动手**（§7 惯例），且它与 **§9-L 大文件拆分高度重合** ——
>     **拆页面与拆文件要一次规划**，否则"先改 UI 再拆"等于改两遍；
>   · 施工前必读：§11.4「回测页 UI」落点行、§10-12（不许在页面里长肉）、
>     §6.6（卡片/收起/滚动区契约）、§10-9（控件样式唯一来源）、§11.5-15/§11.5-20（布局与离屏打桩坑）、
>     §10-10 追加条款（新增参数必须配**行内说明 + 教学入口**，不许只给 tooltip）。
> **其余候选（按文档价值排序，待用户指定）**：§9-L 大文件拆分 / 分钟周期（§7 D3）/
> §7-B1·B2（M2·M3）/ §9-O10 复盘页 LRU / §9-T4-② docstring 与实现不符。

**v6.17 刷新（§7-B5 回测成交真实性 —— 立项 + 步骤 1/2/3 已落地）：**
> ✅ ~~**立项与现状实测**~~（§7-B5：7 组合成 K 线探针坐实 F1–F5；用户拍板四项 ——
>   T+1 默认开启且不给旧口径开关 / 当日收盘档要做 / 触发式委托要做 / P1·P2 搁置留档）
> ✅ ~~**步骤 1 引擎核心**~~（`core/backtest.py`：三档成交时点 + T+1 闸门 + 触发式委托 +
>   **同根不重建仓**；C5 探针 **39 项**含负向对照，并用 `git show HEAD` 的旧引擎做 40+40 组
>   随机样本逐位回归）
> ✅ ~~**步骤 2 + 3 口径连通与 UI**~~（策略签名/存档兼容/`_last_meta`/CSV/PNG 全链路带口径；
>   回测页「🎯 成交模型」行；探针 **22 项**全过）
> ✅ ~~**用户指引返工（v6.18 · 用户实测反馈）**~~：文案换人话 + 行内实时说明 +
>   教学弹窗 `ui/dialogs/fill_model_help.py`；纪律固化 §10-10 追加条款 / §11.5-22；
>   文案可懂性探针 **24 项**全过（含正则级行话检测）
> **→ 下一步（唯一主线）= §7-B5 步骤 4–5**：
>   ① ✅ ~~**步骤 4 验收**~~：断言已移植进两个冒烟脚本（`smoke_chart` **356** /
>      `smoke_pages_overlay` **180**，⚠ 未照抄 `git show` 那段 —— 提交后 HEAD 会变；
>      文案检测用 `跳(?!空)` 精确模式）；`samples/实例函数.txt` 端到端复跑通过
>      （§9-Q-4：两个私有公式 27/17 变量 + 各 7 条绘图指令；真实策略存档 2 套签名不变）；
>   ② **步骤 5 收尾**：回写 §6.3 / §8 / §11.7 自检清单（§4 行数与断言数已同批刷新）；
>   ③ ⚠ **需用户手动实测手感**：三档口径切一遍、点一次「📖 三档怎么选？」，
>      看 T+1 之后数字变化是否符合直觉，**文案是否终于看得懂**（§11.7「让用户手动测一把」）。
> ⚠ **口径铁律：宁可变难看也要真；不提供"允许当日平仓"的兼容开关**（用户 2026-09-15 拍板）。
> 挂起：§7-B5-F 的 **P1（账户+容量+成本）/ P2（盘中即时成交）—— 不许顺手做**。
> 其余候选（待用户指定）：§9-L 大文件拆分（`backtest.py 1570`）、分钟周期（§7 D3）、
> §7-B1/B2、§9-O10 LRU 缓存、§9-T4-② docstring 与实现不符。

**v6.16 刷新（A 类文档欠账清账 · 零业务代码变更）：**
> ✅ ~~**§4 行数口径改版**~~（用户拍板：**只给 ≥400 行的文件标行数**，其余一律不标 ——
>   根治"每次大改都要全量重刷、且必然漂移"的维护债；§4 与体积红黑榜已按实测重写）
> ✅ ~~**失效文件引用**~~（`market.py` 早于 v6.12 删除：2 处**活引用**已改为 `trading_desk.py`
>   的真实落点（`formula_overlay.py` 的渲染方、`backtest.py` 的 `_on_sync_finished`），
>   4 处历史叙事保留原文 + 补注"该文件已删除"；文档 §11.4 两条活引用同批修正）
> ✅ ~~**版本号体系改版**~~（用户拍板：版本号**统一跟随 git** = 最近一次 push 的 commit
>   message 首词，**每次 push 递增 0.01**；`APP_VERSION` 与 `version.json` 已由 `1.4.1`
>   迁到 **1.20**；新纪律写入 §9-A）
> **→ 仍挂着的事（按价值排序，待用户指定）**：
>   ① ℹ `version.json` 的 `url` 现指向**项目 Releases 列表页**（用户 2026-09-15 决定：
>      软件尚未完工，**暂不制作 Release**，先用它占位）—— **将来正式发版时换成具体版本的
>      下载直链**；在那之前老用户点「是」只会到 Releases 列表（§9-A 末条）；
>   ② **§9-L 大文件拆分**（`backtest.py 1570` 超线最多；纯重构，与功能错开）；
>   ③ **分钟周期（§7 D3）**——`kline_min` 分区已预留；日期格式只需改
>      `adaptive_axis.choose_date_format` 一处；
>   ④ §7-B1/B2（M2 全市场单日筛选 / M3 广度统计）—— B1 需先建 `scan_cache` zone；
>   ⑤ §9-O10 复盘页 Parquet LRU 缓存（体验向）；
>   ⑥ §9-T4-② `FuturesImportWorker` 的 docstring 与实现不符（读库那段）。
> ⚠ **体积铁律**：`backtest.py 1570`、`trading_desk.py 898`、`review.py 1067` 都偏大 ——
> 新能力一律落到 `ui/widgets/*` 或 `data/*_store`，**不许在页面里长肉**（§9-L / §10-12）。

**v6.15 刷新（§7-B4 坐标轴自适应收官 —— 用户截图驱动的全 App 缺陷已清零）：**
> ✅ ~~**§7-B4 坐标轴自适应**~~（v6.15：`ui/widgets/adaptive_axis.py` 一处收口；
>   行情页/复盘页共 3 处静态 ticks 全部收敛，回测页两处也改为调用公共纯函数；
>   断言 `smoke_chart` **312** + `smoke_pages_overlay` **150** 全过）
> **→ 下一批候选（按价值排序，待用户指定）**：
>   ① **§9-L 大文件拆分**（`backtest.py 1570` 超线最多；纯重构，与功能错开）；
>   ② **分钟周期（§7 D3）**——`kline_min` 分区已预留；⚠ 一旦做，**日期格式只改
>      `adaptive_axis.choose_date_format` 一处**（这正是这次抽公共件的意义，§7-B4 边界原文）；
>   ③ §7-B1/B2（M2 全市场单日筛选 / M3 广度统计）—— B1 需先建 `scan_cache` zone；
>   ④ §9-O10 复盘页 Parquet LRU 缓存（体验向）。
> ⚠ **体积铁律**：`backtest.py 1570`、`trading_desk.py 898`、`review.py 1067` 都偏大 ——
> 新能力一律落到 `ui/widgets/*` 或 `data/*_store`，**不许在页面里长肉**（§9-L / §10-12）。
> 登记待办：§9-T4-② `FuturesImportWorker` 的 docstring 与实现不符（读库那段）。

**v6.14 刷新（文件归置收官，下一站坐标轴）：**
> ✅ ~~**§9-P1 净额残留**~~（v6.9）· ✅ ~~**§10-9 就地半截 QSS**~~（v6.9）· ✅ ~~NoWheel 遗漏~~（v6.9）
> ✅ ~~行情页十字光标未接线~~（v6.9）· ✅ ~~**§9-T4-① 成分股联网绕过门面**~~（v6.10 收编）
> ✅ ~~**P6 标注持久化**~~（v6.10）· ✅ ~~**P7 函数资产化 + 互送**~~（v6.11）
> ✅ ~~**P8 整体重做 + 收尾**~~（v6.12 换壳/自选/周期/画线 5 类；**v6.13 复权切换 + 文字拖动**）
> ✅ ~~**全仓文件归置**~~（v6.14：`scripts/` `tests/` `samples/` 三目录 + 根目录白名单 + §10-13 规范）
> **→ 下一步（用户已指定）：§7-B4 坐标轴自适应** —— 新建 `ui/widgets/adaptive_axis.py`，
>   把三处**静态 ticks** 收敛为公共件（这也是给 809 行的 `trading_desk.py` 减负的机会）：
>   ① `trading_desk._apply_date_ticks`（行情主图，随周期/缩放变化的日期刻度）；
>   ② `review.py` K 线回放；③ `review.py` 资金 K 线。
>   另需处理的两点（§7-B4 原始诉求）：**放大后横轴只剩一个刻度**、**纵轴不随可视区自适应**。
>   ⚠ 类别轴（策略对比 / 年度复盘）与对数参考轴属"合理静态"，**不改造**。
> ⚠ **体积铁律**：`backtest.py 1591`、`trading_desk.py 809` 都偏大 ——
> 新能力一律落到 `ui/widgets/chart_*` 或 `data/*_store`，**不许在页面里长肉**（§9-L / §10-12）。
> 登记待办：§9-T4-② `FuturesImportWorker` 的 docstring 与实现不符（读库那段）。
> 远期：分钟周期（`kline_min` 分区已预留，§7 D3）。

### 11.7 收工前自检清单
- [ ] 改动的模块状态（`[x]` / `[~]` / `[ ]`）在 §6 / §7 同步了吗？
- [ ] 有没有引入新的"UI 直连 SQL/爬虫"？（§9-H）
- [ ] 净额口径有没有被绕过？（§5.3-B）
- [ ] 虚构数据了吗？（时间 / 价格 / 持仓）
- [ ] 耗时 I/O 走 QThread 了吗？
- [ ] 新发现的技术债写进 §9 了吗？本次摘要写进 §8 了吗？
- [ ] **改了常量/数值，同文件与跨文件的 docstring / 注释同步改了吗？**（§9-O3、§11.5-10）
- [ ] **改了文件规模？** → 只有**越线（≥400 行）**的文件才需要在 §4 更新行数（v6.16 新口径：
      <400 行一律不标数字，**不必**为了行数返工）；越线了就在§4 标上并注意别再往里堆。
- [ ] **要 push 了吗？→ 版本号 +0.01，且三处同批同步**（v6.16 新纪律 · §9-A）：
      ① git commit message 首词（形如 `1.21`）；② `config/settings.py:APP_VERSION`；
      ③ 仓库根 `version.json`。⚠ 顺便确认 `version.json` 的 `url` 仍指向
      **项目 Releases 页**（正式发版时才需要换成具体版本的下载直链）。
- [ ] 同类防护（竞态守卫 / 口径 / 文案）是不是只改了一处、漏了另一处？（§11.5-11）
- [ ] **改了公式引擎 / 图表渲染 / 图层公共件 / 控件样式 / 标注模型 / 配方库 / 周期重采样 / 自选股 / 复权口径 / 图元拖动 / 坐标轴 / 回测成交口径（§7-B5），跑过 `py tests/smoke_chart.py` 吗？**（**356 项**，纯组件、离屏）
- [ ] **改了行情工作台页面（`trading_desk.py`）/ 回测页「成交模型」行 / 标注交互层？** → 跑 `py tests/smoke_pages_overlay.py`（**180 项**）；
      并在其收尾的防污染自检名单里**加上任何新写的 `~/.jian_data/*.json`**（现在有 annotations /
      formula_library / watchlist 三个）
- [ ] **动了图表的刻度或量程吗？** → 一律走 `ui/widgets/adaptive_axis.py`（§7-B4），
      **禁止页面手写 `setTicks` / `setYRange`**；要改日期格式只改 `choose_date_format`；
      设了 y 范围又想断言它 → 必须 `setYRange(..., padding=0)`（§11.5-21：pyqtgraph 会偷加 padding）
- [ ] **新增或修改了任何"盈利 / 亏损"判定吗？**（着色、正负号、标记色、高亮带方向）
      必须走 `core.utils.record_net_amount(record)`，**不许**手写 `net_profit > 0`（§5.3-B / §9-P1）
- [ ] **改了 `QComboBox` / `QDateEdit` / `QDateTimeEdit` 的样式吗？**
      → 只能用 `custom_widgets` 的常量（`::drop-down` 与 `::down-arrow` 必须成对，否则箭头消失）；
      改完跑 `py tests/smoke_chart.py` 看**箭头像素断言**（§11.5-17）
- [ ] **改了回测页/工作台的叠层、检测、图层开关、公式对话框、窗格编排、用户标注、配方库/互送、自选股/周期/复权、成交模型行，跑过 `py tests/smoke_pages_overlay.py` 吗？**（**180 项**，页面级；标注与配方一律用**临时库**，脚本末尾还有"用户真实库未被写"的**防污染自检**（现含 `backtest_strategies.json`）；三条离屏打桩见 §11.5-20，**别删**）
- [ ] **新加了"往用户数据目录写文件"的功能吗？** → ① 用 `tmp + os.replace` 原子写；② 给 `tests/smoke_pages_overlay.py` 的收尾自检加一行文件名（§11.7 上一条）；③ 单条坏数据必须**跳过自己**而不是拖垮整库
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
- [ ] **改了 `ui/widgets/function_segments.py` 吗？**（回测页与行情页**共用**）
      → 两个 smoke 都要跑，并按 §11.5-15 检查"子控件数 == 布局管理数"
- [ ] ⚠ **动了 `parse_program` 的接受/拒绝行为（尤其"警告升级为报错"），
      拿 `samples/实例函数.txt` 端到端跑过一遍吗？**（§9-Q-4 事故教训：用户存量函数不能被打断；
      验证用临时脚本，跑完即删 —— 用户私有公式不入仓库，§10-6）
