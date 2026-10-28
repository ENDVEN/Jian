# 场内基金（ETF / LOF）接入方案 · ★1.92（2026-10-29 拍板，未实现）

> **范围（用户 2026-10-29 明确）**：**只做场内 ETF / LOF**。
> **不做**：港股通（币种 / 港历 / 汇率三件前置未解）· 场外 QDII 基金（无日线，只有 T+1 净值）· 货币 ETF（价格恒 ~100，收益靠份额折算，价格曲线无意义）。
> **已接受的两个取舍**：① ETF 允许**不复权**（源限制），但软件要**尽力自行补齐跳空**（见 §2.2）；② ETF **不进** A 股的全市场扫描 / 广度统计（避免改口径）。

---

## 1. 实测基线（2026-10-29，匿名档 · 本机）

| 事项 | 实测 | 结论 |
|---|---|---|
| ETF 名单 `fund_etf_category_sina('ETF基金')` | **1714 只** · 2.4s · 1 个请求 | 名单+中文名一次拿全 |
| LOF 名单 `fund_etf_category_sina('LOF基金')` | **359 只** · 2.2s | 同一条通道 |
| ETF 日线 `fund_etf_hist_sina('sh510300')` | 3503 行 · **0.6s** | 匿名可通，比 A 股快 |
| 跨境 ETF `sh513100` / `sz159920` | 3217 行 2.2s / 3404 行 2.7s | QDII/恒生 ETF 同样可通 |
| **当前路径** `stock_zh_a_daily('sh510300')` | **JSONDecodeError** | 这是"填了 ETF 却画不出线"的直接原因 |
| ETF 分红表 `fund_etf_dividend_sina('sh510300')` | 14 条 · 0.7s · 列 = `日期, 累计分红` | **本地算前复权的数据源已具备** |
| 成交量单位 | `close × volume ≈ amount`（4.5615e9 vs 4.5586e9，差 0.06%） | **volume = 股**，禁止 ×100（§9-V） |
| 多出的列 | `postVol / postAmt`（盘后） | 落盘时裁掉 |
| 分类占比（1714 只） | 货币 19 · 债券 52 · 黄金 13 · 跨境/QDII 223 | 货币 ETF 默认排除 |
| 规模估算 | 2073 只 × ~3300 行 ≈ 700 万行 · 几十 MB | 存储无压力 |
| 首次全量耗时 | 2073 × 0.3s（全局节流）≈ **15~30 分钟** | 按 1.92 的 ETA 口径如实告知 |

---

## 2. 口径决议

### 2.1 分区隔离（硬要求）

新增 **`etf_daily`** 分区（`data_lake/etf/daily`），**不复用** `kline_daily` / `kline_daily_raw`：

- ETF 无"前复权历史漂移"这回事（我们自算，见 §2.2），混进 `kline_daily` 会让股票那套
  `_qfq_factor_drifted` 自愈逻辑误判；
- 与 `kline_daily_raw`（股票的**不复权**备份）语义不同：那个是"同一标的的第二口径"，
  这个是"另一类资产"；
- 独立分区 ⇒ 数据管理页能单独看/删（数据主权）。

### 2.2 跳空：**本地等比前复权**（本轮新增结论）

来源只给不复权，但 `fund_etf_dividend_sina` 给了**累计分红**（日期 + 累计值），
⇒ 可在本地算前复权，**不需要东财登录**：

```
d_e   = cumdiv(e) − cumdiv(e_prev)            # 该次每份分红
p_e   = 除息日 e 的**前一交易日不复权收盘**
f_t   = Π_{e > t} (1 − d_e / p_e)             # 前复权因子（最新日 f = 1）
P'_t  = P_t × f_t                             # 前复权价
```

- 复权结果**落盘**（读的时候不再算），并在元数据里记 `div_last`（最后事件日）；
  分红表出现新事件 ⇒ 整段重算一次（与股票"除权整段重算"同思路，频率约 1 次/年）。
- **可信度闸门**（不通过就退回不复权 + 显式标注，绝不猜）：
  - `累计分红` 必须**单调不减**；
  - 首个事件日的累计值应 ≈ 首个 `d`（说明表从成立起完整）；
  - 若首条记录晚于本地日线首日 ⇒ 更早区间**无法复权** ⇒ 该段保持不复权并在卡面标注分界日。
- 已知不覆盖：**份额拆分 / 折算**（ETF 少见；货币 ETF 就是极端案例）⇒ 检测到单日比例异常（如 ≈0.5 / ≈2）
  时**标记"疑似拆分"**并停止在该段复权，**不自动改数**。

### 2.3 其余口径

| 项 | 决议 |
|---|---|
| 交易日历 | **复用 A 股日历**（场内基金与 A 股同日历），`expected_latest` 直接可用 |
| 快照秒补（`spot`） | **ETF 禁用**（东财 `ulist` 的基金口径与场内成交价不同） |
| 市值权重 | ETF **无流通股本** ⇒ 该只记「数据不足」，权重 0 + 点名（复用 1.91 机制） |
| 行业分布 | ETF 无行业 ⇒ 记「未分类（场内基金）」并**说明原因**，不瞎猜 |
| 基准 | 仍只用 A 股指数（ETF→跟踪指数映射表不在本轮） |
| 全市场扫描 / 广度 / 就绪度 | **只认 A 股**（名单函数不变，见 §4-5） |
| 行情页 / 回测 / 参数研究 | **P2 再接**（它们 8 处写死 `kline_daily`，需统一走 `load_daily`） |

---

## 3. 数据流

```
名单：fund_etf_category_sina('ETF基金'/'LOF基金')
   → fetch_fund_roster() → {symbol(6位): name} → DB 表 fund_symbols(symbol,name,kind)

日线：fund_etf_hist_sina('sh510300')
   → 裁列（丢 postVol/postAmt）→ 单位断言（close×volume≈amount，>5% 报警）
   → merge(旧, 新)（同股票：keep='last'）

复权：fund_etf_dividend_sina → 因子 → 前复权序列（可失败 ⇒ 不复权 + 标记）
   → 落盘 etf_daily/<symbol>.parquet

读取：DataLakeManager.daily_zone_for(symbol)  # 股票 kline_daily / 基金 etf_daily
   → load_daily(symbol)（唯一出处）
```

---

## 4. 底层改动清单（按依赖顺序）

| # | 文件 | 改动 | 备注 |
|---|---|---|---|
| 1 | `data/market_db.py` | `zones` 加 `etf_daily`；新增 `daily_zone_for(symbol)` | **唯一出处**（§11.5-19），别在 UI 里写死分区名 |
| 2 | `data/lake_schema.py` | `SCHEMA['etf_daily']`：required 同 `DAILY`，optional 只 `amount`（**无 turnover / outstanding_share**） | 声明"算不出换手率/流通市值"，下游记「数据不足」 |
| 3 | `data/akshare_feed.py` | `is_fund_code()` · `fetch_etf_daily()` · `fetch_fund_roster()` · `fetch_etf_dividends()`；`fetch_daily_auto` **先判基金再判股票** | 否则 510300 永远走 `stock_zh_a_daily`（JSONDecodeError） |
| 4 | `data/sync_service.py` | `ZONE_ETF`；`DAILY_ZONES` 加它；`_fetch` 分支；`refresh_one` 对 ETF 走"日线+复权"两段；`spot` 对 ETF 禁用 | 定稿裁剪/新鲜度判定要覆盖新分区 |
| 5 | `core/database.py` + `data/roster_sync.py` | **新表** `fund_symbols(symbol TEXT PRIMARY KEY, name TEXT, kind TEXT)`；`update_fund_roster()` **只 UPSERT** | ⚠ 绝不能塞进 `market_symbols`：那张表 `update_market_roster` 是 `replace`（下次同步名册会把 ETF 冲掉），且 `list_stock_symbols` 会把 6 位 ETF 当股票 ⇒ 污染全市场下载/扫描/广度 |
| 6 | `core/engine.py` | `list_fund_symbols()` / `fund_names()` | UI 不碰 DB（§9-H） |
| 7 | `ui/dialogs/bulk_download.py` | 来源加「场内基金（ETF/LOF）」；`_collect_symbols` 走基金名单；`_zones_to_download` 返回 `etf_daily` | 预估按只数如实说（1.92 已修 ETA） |
| 8 | `ui/views/portfolio_view.py` | `_frames` 改 `load_daily`；行业/市值对 ETF 记「数据不足 + 原因」；卡面注明复权口径 | 组合里加 ETF 才有曲线 |
| 9 | `ui/views/data_manager.py` | 分区中文名加「场内基金日线」 | 可见 / 可删 |

**不需要改**：`DownloadHub`（zone 透传，去重按 `(symbols, zone)` 天然支持）· `ThrottlePolicy` / `RateGovernor` · 交易日历。

---

## 5. 步骤拆分（P1，可执行）

| 步骤 | 内容 | 验收 | 估时 |
|---|---|---|---|
| **P1-1** | 分区 + schema + `daily_zone_for` | 断言：分区存在；`etf_daily` 缺 `turnover` 不算错 | 0.2 轮 |
| **P1-2** | `is_fund_code` / `fetch_etf_daily` / 路由前移 / 单位断言 | 真机 3 只探针（510300 / 159920 / 513100）；`close×volume≈amount` | 0.3 轮 |
| **P1-3** | `fund_symbols` + 名单同步 + `engine` 门面 | 断言：名单 2000+；二次同步不丢行；`list_stock_symbols` 条数不变 | 0.2 轮 |
| **P1-4** | 批量预下载新来源 | 弹窗出现「场内基金」；预估按 N×interval | 0.2 轮 |
| **P1-5** | 组合接入（`load_daily` + 口径标注） | 组合加 510300 有曲线/持仓/调仓；市值记「数据不足」 | 0.3 轮 |
| **P1-6** | 数据管理分区名 | 页面出现「场内基金日线」，可查看/删除 | 0.1 轮 |
| **P1-7** | 前复权（分红表 + 因子 + 闸门） | 510300 除息日无跳空；表不可信时**退回不复权并标注** | 0.3 轮 |
| **P1-8** | 冒烟断言 §1.93（约 10 条）+ 文档回写 | 全绿；断点/HISTORY/PLAYBOOK 同步 | 0.2 轮 |

合计 **≈1.5 轮**（两次会话）。

---

## 6. 风险与规避

| 风险 | 规避 |
|---|---|
| ETF 被当股票写进 `kline_daily`（污染前复权） | 路由**先判基金**；分区隔离；断言钉住 |
| 名册 `replace` 把基金行冲掉 | 独立表 + 只 UPSERT |
| 全市场扫描混入 2073 只基金 | `list_stock_symbols` 不变（分开表） |
| 成交量 100× 事故 | 落盘前断言 `close×volume≈amount`（>5% 报警并拒写） |
| 分红表不全 ⇒ 复权算错 | 三道闸门（单调/首值/起点）；不通过就**不复权 + 标注** |
| 拆分/折算造成假暴跌 | 检测比例异常 ⇒ 标记「疑似拆分」并停复权，**不改数** |
| 清盘/无成交基金 | 复用 1.92「死票不重试」：空表 1 次即「数据不足」 |
| 首下 2000 只耗时被低估 | 独立入口 + 按 `N × interval` 如实预估 |

---

## 7. 延申（本轮不做，留档）

- **P2 · 行情页 / K 线**：`desk_data` 改走 `load_daily`；`search_symbol` UNION 基金表（ETF 可搜、可看图）。
- **P2 · 回测 / 参数研究**：8 处 `load_data("kline_daily", …)` 统一换 `load_daily`；单标的回测即天然支持 ETF。
- **P2 · 基准**：ETF → 跟踪指数映射（`510300 → sh000300`），需要一张人工核对的映射表（不靠名字猜）。
- **P3 · 港股通**（用户明确暂不做）：前置三件 = **币种（HKD/CNY 汇率）** · **港股日历** · **港股通名册**；
  数据源 `stock_hk_daily` 实测可通（5499 行 / 1.9s），但混币种不接汇率 = 假数据，不能上。
- **P3 · 场外 QDII**：无日线（T+1 净值），明确不支持，界面写清"只支持场内"。

---

## 8. 待确认（3 条，实现前定稿）

1. **货币 ETF（19 只）**：默认**排除**（价格恒 ~100，收益靠份额折算，价格曲线无意义）—— 是否同意？
2. **前复权口径**：默认**等比前复权（以最新价为基准）**，与股票 qfq 一致 —— 认可吗？
3. **ETF 复权失败时**：默认"不复权 + 卡面标注分界日"（不猜、不填 0）—— 认可吗？
