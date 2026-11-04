---
status: active
topic: 计划总表（哪份方案书是"在途"、哪份已经完成）
read_when: 找"现在有哪几件事在办"或"某份方案书还算不算数"
skip_if: 只想改一个具体文件（直接看 CODEMAP）
verified: 2026-11-02
---

# 计划总表（唯一清单）

**规则**（已生效）：

1. `plans/active/` **只放未完成**的方案书；完成即 `git mv` 到 `plans/done/`（**不删**，历史要能查）。
2. 每份计划**头部必须带 `status:`**（模板见 `docs/_TEMPLATE.md`）。
3. 本表是唯一清单：新增计划先在表里加一行，再建文件。
4. "已完成"的判据（三条同时满足）：① 条目里没有未勾选项；② 软件里真的能用；③ 冒烟有对应断言。

---

## 一、在途（active · 四件）

| 计划 | 一句话 | 状态 |
|---|---|---|
| [`active/DATA-PLATFORM.md`](active/DATA-PLATFORM.md) | 数据底层平台与下载提速：provider 抽象 / 日更批量快照 / 目录与调度 / 存储 benchmark / 资产扩展 | **P1/P2 完成**（2.07：能力表 / registry / 备源 / 登录直连 / 一次性 bootstrap 4605 只）；P3 待开工 |
| [`active/ETF-LOF.md`](active/ETF-LOF.md) | 场内 ETF/LOF 接入：`etf_daily` 独立分区 · 基金代码路由 · 名册分表 · **本地等比前复权补跳空** · 不进 A 股扫描/广度 | **未实现**（方案已拍板） |
| [`active/ARCH-PERF.md`](active/ARCH-PERF.md) | 架构与启动性能：4.05s → ≤2.2s 的 P0 四件 + 测试分层 + 文档分卷 | **P0 已完成**（2.03：构造 3.6s→0.27s；探针 2.145s）；P1/P2 未做 |
| [`active/TEST-HARNESS.md`](active/TEST-HARNESS.md) | 测试基建：overlay 偶发 fastfail（`0xC0000409`）与"跑完不退出"的根因排查 | **进行中**：fastfail 已定位并修复（10/10 绿）；挂死未复现，退出路径已加观测 |

---

## 二、已完成（done · 保留可查，**不该再被当活文档读**）

| 计划 | 一句话 | 为什么还能查 |
|---|---|---|
| [`done/PORTFOLIO.md`](done/PORTFOLIO.md) | 组合页 P0–P4（净值 / 持仓 / 分布 / 调仓记录 / 口径） | **口径真源**：权重、现金、再平衡的定义仍以此为准 |
| [`done/SWEEP.md`](done/SWEEP.md) | 参数稳健性研究（MVP + R0–R7 + 池化） | 参数研究的取数与折数口径 |
| [`done/HUB.md`](done/HUB.md) | 函数总库（A 管理台 + 统一浮窗） | 公式资产的模型说明 |
| [`done/M3-MULTI.md`](done/M3-MULTI.md) | M3 多统计项叠加 + 与指数关系量化 | 结论仍有效（此前是孤儿文档，现已归位） |
| [`done/CLEANUP.md`](done/CLEANUP.md) | B14 第一轮大扫除台账（删了什么 / 凭什么） | 追溯"为什么这个文件没了" |

---

## 三、长期参考（reference / history，不是计划 —— **D2c 才搬**）

| 文件 | 性质 | 目标位置 |
|---|---|---|
| `docs/reference/CODEMAP.md`（61k） | 逐文件职责地图 | `docs/reference/CODEMAP.md`（改脚本生成） |
| `docs/reference/SETUP.md` | 换机迁移手册 | `docs/reference/SETUP.md` |
| `docs/playbook/INDEX.md`（87k） | 149 条踩坑手册 | `docs/playbook/{INDEX,ui,data,process}.md` |
| `docs/history/README.md`（173k） | 版本叙事 | `docs/history/2026.md`（按年分卷） |
| `docs/archive/README.md`（242k） | 旧主案正文 / 旧审计 | `docs/archive/ARCHIVE-{1,2,3}.md` |

---

## 四、迁移进度

| 批次 | 内容 | 状态 |
|---|---|---|
| D2a | `RULES` → `docs/RULES.md` + 76 处引用 | ✅ 2026-11-02 |
| D2b | 7 份方案书分流 `active/` / `done/` + 补 `status:` 头 + 49 处引用 | ✅ 2026-11-02 |
| D2c | HISTORY / PLAYBOOK / ARCHIVE 分卷（内容手术，单独一轮） | ✅ 2026-11-02（见 `STATUS.md` §7） |

**为什么已完成的不删**：纪律要求"历史数字冻结、永不回改"——删掉就再也说不清"当年为什么这么定"。
搬家只是把它从"每次都要扫"变成"要查才翻"。
