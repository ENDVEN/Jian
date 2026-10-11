# Jian 换机迁移手册（`docs/JIAN_SETUP.md`）

> 用途：把 Jian 完整搬到另一台电脑（新笔记本 / 重装系统）。随 `1.68`（2026-10-04）落地，预检记录见 §5。
> **隐私铁律（§10-6）：用户数据只走 U 盘 / 局域网，绝不上传网盘或任何公共远端。**

## 0. 迁移就三样东西

| 东西 | 从哪来 | 说明 |
|---|---|---|
| **代码** | `git clone https://github.com/ENDVEN/Jian.git` | 仓库 pack 仅 ≈3.3 MB；历史/文档/护栏全在里面 |
| **数据** | U 盘拷 `~/.jian_data` **整目录** | ≈186 MB；**不在 git 里**（数据主权铁律：程序与数据物理隔离） |
| **私有样例** | U 盘拷仓库旁 `samples/` | 被 `.gitignore` 整体忽略，clone 不带；只是"喂给 app 的输入样例"，可不拷 |

## 1. 装环境（新机器一次性）

1. **Git**（默认选项即可）；
2. **Python 3.12+ 64 位**（预检机 = 3.14.4；**3.12.0 已实测全绿**：`compileall` 全过 +
   冒烟 990/0 + 主窗口能起。原先写「3.13+」是白挡掉 3.11/3.12 用户，已下调；
   Windows 下统一用 `py` 启动器）；
3. 仓库根目录执行 `py -m pip install -r requirements.txt`
   （PyQt6 / pyqtgraph / pandas / numpy / pyarrow / akshare / openpyxl）；
4. **换机 / 要求与他人逐位一致**时，改用 `py -m pip install -r requirements.lock.txt`
   （精确版本锁 = 本机实测全绿那一套，含全部传递依赖）。

> 两份文件都**只写 ASCII 注释**：pip 在 Windows 上先按 cp936（GBK）解码 requirements 文件，
> 中文注释的字节序列一旦不合法就直接抛 `UnicodeDecodeError`，连安装都起不来。
> 中文说明一律放本文档。

## 1.1 依赖版本策略（为什么每个包都有上界）

**Jian 是交付给人跑的应用，不是给别人 import 的库**，所以 `requirements.txt` 里每一项都是
「下界 + 上界」而不是只写下界。上界买的不是保守，是**复现性**：pip 默认装最新匹配版本，
不钉上界就会出现「我这儿能跑、你那儿不能跑」且无从复现的故障。

**上界不是永远不动**，而是走「升级窗口」，且必须过闸：

1. 抬上界（或删上界）→ 装 → 跑两份冒烟；
2. `tests/smoke_chart.py` 基准 **990 通过 / 0 失败**、`tests/smoke_pages_overlay.py` 全绿才放行；
3. 把结果记进下表，不绿就退回原上界。

> ⚠ 注意：`smoke_pages_overlay.py` 在**空数据**机器上会有 8 条环境性失败（本地日线分区无数据、
> 花名册为空等），与依赖版本无关，判定时以「不新增失败」为准。

**当前禁区：pandas 3.x**（2026-10-04 实测）：

| 版本 | smoke_chart | smoke_pages_overlay | 结论 |
|---|---|---|---|
| pandas 2.3.3 | 990 / 0 | 980 通过 + 8 条环境性失败 | ✅ 现行 |
| pandas 3.0.6 | 980 / **1** | **918** 通过（62 条断言被异常截断） | ❌ 禁用 |

失败形态最危险的一类：**数据湖扫描路径静默返回空**（`result.dates` 变 `None`，随后
`dates[-1]` 抛 `TypeError`）——界面不报错，只表现为一片空白。根因是 3.0 的大版本语义变更：
Copy-on-Write 默认开启（链式赋值静默失效）、默认 `str` dtype（`object` 判定失效）、
时间单位由 `ns` 改为推断 `us`。要跨需单独做一轮迁移（先升 2.3 清干净 FutureWarning 再上 3.0）。

**其它上界的口径**：`PyQt6<7` / `pyqtgraph<0.15` / `numpy<3` / `pyarrow<26` / `akshare<2` /
`openpyxl<4` —— 均为「下一个大版本可能有 breaking change」的护栏，抬之前按上面的窗口走一遍。

## 2. 拷数据（老机器 → U 盘 → 新机器）

1. **先关掉老机器上正在运行的 app**（避免拷到写一半的 SQLite）；
2. 拷 `C:\Users\<老机器用户名>\.jian_data\` **整个目录**进 U 盘；
3. 新机器放到 `C:\Users\<新机器用户名>\.jian_data\` —— 代码固定读**用户主目录**下的 `.jian_data`
   （`config/settings.py: USER_DATA_DIR = os.path.join(USER_HOME, ".jian_data")`），
   放对位置即插即用；**已实测零绝对路径引用，两台机器用户名不同也不受影响**。

**`.jian_data` 里有什么（捡重点）**：

| 文件/目录 | 是什么 |
|---|---|
| `jian_trades.db` | 交割单业务库（流水 / 持仓腿 / 覆盖度 / 花名册） |
| `data_lake/` | 行情数据湖（parquet 9 分区；**180+ MB 的体积大头**） |
| `formula_library.json` / `backtest_strategies.json` / `scan_strategies.json` | 函数配方 / M1 策略 / M2·M3 筛选方案 |
| `preferences.json` / `watchlist.json` / `annotations.json` | 偏好 / 自选股 / 画线标注 |
| `sweep_results/` + `index_regimes.json` | 参数研究快照 + 上证切块缓存 |
| `backtest_results/` | 回测 / 扫描运行历史存档 |
| `em_cookie.json` | 东财登录凭据（**别外传**） |
| `market_data/` | A 股辅助数据（≈0.2 MB） |
| `screenshots/` / `logs/` / `trade_calendar.json` / `industry_map.json` | 截图 / 日志 / 交易日历缓存 / 行业映射 |

## 3. 启动与验证（30 秒过一遍）

`py main.py` 启动后：

- [ ] 📊 仪表盘：KPI 与日历热力图有**你的真实数据**；
- [ ] 📈 行情工作台：查一个自选股，K 线能出来（读的是拷过来的数据湖）；
- [ ] 🗄 数据管理：分区清单行数 / 日期范围非空；
- [ ] 🧪 参数研究（📐 市场回测第 2 个子页签）：能选到标的与策略；
- [ ] ⚙ 设置：版本号与仓库一致。

## 4. 日常注意（两台机器交替开发）

- **开工先 `git pull`**；已推送的历史**永不 `--amend`**（§11.5-105 血泪：只追加提交 + 顺推版本号）；
- 笔记本首次提交前配身份：`git config --global user.name ENDVEN`（邮箱与台式机同）；push 需 GitHub 凭据（PAT / SSH）；
- **数据以"最近拷贝的那台"为准**：别在两台机器各自写数据湖后互拷（会交叉出裂缝）；
  出行前 / 回来后各做一次「⬆ 更新到最新」即可，路上增量补；
- 行情批量拉取遇「批量同错 + `ProxyError`」⇒ **先查系统代理**（§9.3 老经验），不是行情源的错；程序已有熔断与人话文案兜底。

## 5. 预检记录（2026-10-04 · 台式机实测）

- 干净 clone（`git clone --no-local`，等价 GitHub 拉取）：`compileall` 全过；
  `smoke_chart` **990/0** · `smoke_pages_overlay` **990/0**；
- 代码**零机器绑定路径**（`USER_DATA_DIR` 走用户主目录 / `UPDATE_CHECK_URL` 指远端 `version.json`）；`version.json` 合法；
- `~/.jian_data`（186 MB，其中数据湖 183 MB）**零绝对路径引用**（偏好 / 标注 / 策略 / `trades.screenshot_paths` 逐一查过）；
- 台式机**有意留守**（不随 clone 走）：本地 stash×2（1.34 时代 R7 换序半成品备份，无法编译）
  与 7 个 `backup-*` / `wip` 备份分支——留在台式机即可，别 `git push --all`。

## 6. 显示异常 / 高分屏（v1.69 修 · 2026-10-11 笔记本实测）

**症状**：窗口**右侧/底部被切**、弹窗文字被**压成一列**、分组框**边框错位**（换机后"跟另一台完全不一样"）。

**根因**（实测：屏 2048x1280 + Windows **125% 缩放**）：Qt 里 `QStackedWidget` 的最小宽度 = **所有页里最宽的
那页**（与当前显示哪页无关）⇒ 单页版式把**整窗**顶宽：市场回测页摘要条最小 **1391 DIP** ⇒ 整窗最小 **1653 DIP**；
而 125% 缩放下该屏可用宽只剩 **1638 DIP** ⇒ **窗口比屏幕还宽**，右侧内容被挤出屏外、Qt 再强制压缩布局。

**已修两条（v1.69）**：

1. `main.py` 在 `QApplication` **之前**设 `setHighDpiScaleFactorRoundingPolicy(RoundPreferFloor)`
   ⇒ 125% 归 1.0（可用宽 1638 → **2560** DIP），顺带消掉分数倍率下 1px 边框的错位/重影；
2. `JianMainWindow._clamp_to_screen()` ⇒ 初始尺寸 = 设计尺寸 ∩ 可用区域，最小尺寸夹到屏幕内
   （`QLayout.SetNoConstraint` 解开"内容最小宽 ⇒ 窗口最小宽"的传递）。

**取舍**：界面按 **100%** 渲染，视觉上比 125% 略小 —— 用户拍板"**能完整显示**优先于看起来更大"。
**仍存在的边界**：可用宽 **< 1653 DIP** 的窄屏（如 1366×768），回测页摘要条会**页内横向截断**
（它是设计锁定的**单行**，§10-14）—— 不在本轮修复范围。

**字体**：界面字体在**应用层**钉一次（`app.setFont(ui_font())`，必须在建窗/建页之前）。此前 4 处 QSS 写了
macOS 专有名 `-apple-system`（主窗口 + 导入交割单 + 列表管理 + `DIALOG_INPUT_QSS`）⇒ Windows 静默回落
**微软雅黑 UI**、开源栈永不生效；而启动日志当时**谎报**"Noto Sans SC"（`ui_font_status()` 测的是"字体栈会
解析成谁"，不是"界面实际用了谁"）⇒ v1.69 已清干净 + 自检改为传 widget 实测 + 加源码级断言盯住 macOS 专有名。

### 6.1 「黑块 / 表格文字不可读」的真凶：**Windows 深色模式**（v1.69 修 · §10-17）

**症状**（用户 2026-10-11 实测截图）：设置页下半、函数总库面板、复盘页分栏**间隙**、预下载弹窗整片**发黑**；
交易流水表的**账户/品种/买卖/开仓价/平仓价/手数/交易时间整列空白**（看着像没数据）；下拉列表点开一片空白。

**根因**：本项目**没有主题系统**（无 `theme.py`、无全局 `setPalette`，各页背景色靠**内联 QSS 各自声明**），
所以"没写背景色 / 没写文字色"的控件**全部吃系统调色板**。本机 `AppsUseLightTheme = 0`（**Windows 深色**）⇒

| 现象 | 机制 | 实测数字（修复前） |
|---|---|---|
| 表格整列不可读 | 内联 QSS 只写了白底、没写文字色 ⇒ 文字吃 `Palette.Text = #ffffff` | `Text/Base` 对比度 **1.00**；账户/品种/买卖/开仓价/平仓价/手数逐列墨迹像素 = **0** |
| 页面黑块 | 未设背景的容器透出 `Palette.Window = #1e1e1e` / `Base = #2d2d2d` | 暗像素占比：设置页 **32.0%**、函数总库 **49.6%** |

**已修**：`main.py` 建窗**之前**调 `ui.widgets.styles.apply_app_palette(app)`（唯一出口）——
先 `styleHints().setColorScheme(Light)`（连标题栏一起回浅色），再显式 `setPalette`（颜色取自 `config.settings`）。
修后实测：最差页暗像素 **0.62%**、表格对比度 **5.85**、逐列墨迹像素全部 >0。
**判据与纪律入 §10-17；冒烟增补断言**（源码顺序 + 调色板实测对比度）。

> ⚠ **离屏冒烟默认看不到这类问题**：`QT_QPA_PLATFORM=offscreen` **不读** Windows 深色调色板。
> 复现本类缺陷必须手动 `app.styleHints().setColorScheme(Qt.ColorScheme.Dark)`（见 `§10-17` 末条）。
> **排查口诀**：遇到"离屏正常、用户机上不对"的外观问题，先问三件事 —— **系统深浅色 / 显示缩放 / 字体**。
