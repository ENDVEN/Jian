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
2. **Python 3.13+ 64 位**（预检机 = 3.14.4；Windows 下统一用 `py` 启动器）；
3. 仓库根目录执行 `py -m pip install -r requirements.txt`
   （PyQt6 / pyqtgraph / pandas / numpy / pyarrow / akshare / openpyxl）。

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
