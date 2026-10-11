# data/roster_sync.py
"""花名册同步的**唯一入口**（app 内一键按钮 / 运维脚本共用 · ★1.70 / §11.5-125）。

【为什么必须收成一个门面】
  花名册（`market_symbols` = 全市场 A 股 + 期货的"代码→名称"对照表）是"**按名字搜标的**"的前提。
  新机器上它**天然是空的** ⇒ 行情工作台/回测页"按名字搜"全部落空。此前同步动作只存在于
  `scripts/sync_roster.py`（**命令行 = 新用户门槛**：他连该跑哪个脚本都不知道）。
  收进门面后：① 脚本 = 薄壳；② app 内可给"一键同步"（新用户第一次的出口）；
  ③ **数量安全闸只有一份** —— 半份名单覆盖整表会让名称大面积丢失且无法自愈（§9-G）。

【纪律】本模块是 data 层：不碰 Qt、不碰控件；UI 侧一律经 `ui/workers.RosterSyncWorker` 调它。
"""
from __future__ import annotations

import logging
import time

import pandas as pd

from core.database import DatabaseManager
from data.akshare_feed import AkShareFeed
from data.net_env import apply as _apply_net

logger = logging.getLogger(__name__)

# ★数量安全闸：A 股正常规模 4500~5500；低于此一律判"残缺名单"，**拒绝覆写**。
#   为什么不能只判"空"：官方三源里若只成功两家（例如上交所被拒），照样会拿残缺名单覆盖整表。
MIN_A_SHARE_ROWS = 3000


def sync_roster() -> dict:
    """拉取并**覆写**花名册 ⇒ 返回报告 dict（**绝不抛**；失败在 `ok=False` + `reason` 里说清）。

    报告字段：`ok` / `reason` / `elapsed` / `a_share` / `futures` / `total`。
    ⚠ `ok=False` ⇒ **数据库一个字节都没动**（调用方据此如实回执，绝不假装成功）。
    """
    _apply_net()                     # 网络策略（IPv4 优先 + requests 层硬超时）—— 脚本与按钮同一套
    t0 = time.time()
    df_a = AkShareFeed.fetch_a_share_roster()
    df_f = AkShareFeed.fetch_futures_roster()
    n_a = 0 if df_a is None else len(df_a)
    n_f = 0 if df_f is None else len(df_f)

    if n_a == 0 or n_f == 0:
        missing = "、".join(name for name, n in (("A股", n_a), ("期货", n_f)) if n == 0)
        return {"ok": False, "reason": f"{missing}名单为空（疑似断网或接口变更）"
                                       f"⇒ 已中止入库，既有花名册保持原样",
                "elapsed": time.time() - t0, "a_share": n_a, "futures": n_f, "total": 0}

    if n_a < MIN_A_SHARE_ROWS:
        return {"ok": False, "reason": f"A股名单只有 {n_a} 条（正常 4500+）"
                                       f"⇒ 判为残缺名单，已中止入库，既有花名册保持原样",
                "elapsed": time.time() - t0, "a_share": n_a, "futures": n_f, "total": 0}

    DatabaseManager().update_market_roster(pd.concat([df_a, df_f], ignore_index=True))
    total = n_a + n_f
    logger.info(f"花名册已同步：A股 {n_a} + 期货 {n_f} = {total} 条")
    return {"ok": True, "reason": "", "elapsed": time.time() - t0,
            "a_share": n_a, "futures": n_f, "total": total}
