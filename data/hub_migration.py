# data/hub_migration.py
"""ƒ 函数总库的**一次性资产收编**（★1.61 / §7-B16 · H1 · 方案书 `docs/JIAN_HUB_PLAN.md` §3）。

【做什么】把 M1 策略库与 M2/M3 方案库里**已有的公式**导进资产库（`formula_store`），
  并把 `asset_id` 写回各条 —— 之后"总库引用计数 / 更新提示 / B15 取函数"才有数据可算。

【三铁律（红线③，写进冒烟）】
  ① **绝不猜拆**：老 M1 档只有 `function` 拼接文本 ⇒ **整体一段**（绝不按 `;` 拆 ——
     段文本本身就可能含分号语义，猜拆必错）；
  ② **绝不丢数据**：只**增** `asset_id`，不删不改任何既有字段（内联快照原样保留）；
     坏条目跳过自己并记日志，绝不拖垮整库；
  ③ **幂等**：跑 N 次 = 跑 1 次（已有 `asset_id` 的条目直接跳过；迁移标记存资产库顶层）。

【触发】`main.py` 启动时调一次；总库页/浮窗打开时兜底再调（幂等，开销 = 读两个小 JSON）。
"""
from __future__ import annotations

import logging

from data.formula_store import SOURCE_BACKTEST, SOURCE_SCAN, get_formula_store
from data.hub_assets import asset_texts, find_by_content, upsert_asset
from data.scan_strategy_store import get_scan_strategy_store
from data.strategy_store import StrategyStore

logger = logging.getLogger(__name__)


def ensure_hub_migration() -> dict:
    """幂等迁移。返回 `{'m1': 新收编条数, 'scan': 新收编条数, 'migrated': 是否本次做的}`。"""
    store = get_formula_store()
    if store.hub_migrated:
        return {"m1": 0, "scan": 0, "migrated": False}
    n_m1 = _migrate_m1(store)
    n_scan = _migrate_scan(store)
    store.hub_migrated = True
    store.save()
    logger.info(f"函数总库资产收编完成：M1 策略 {n_m1} 条、M2/M3 方案 {n_scan} 条")
    return {"m1": n_m1, "scan": n_scan, "migrated": True}


def _migrate_m1(store) -> int:
    """M1 策略 → 资产。只有 `function` 拼接文本的老档 = 整体一段（**绝不按分号猜拆**）。"""
    n = 0
    try:
        m1 = StrategyStore()
    except Exception as e:                             # noqa: BLE001 —— 库坏了不拖启动
        logger.warning(f"函数总库迁移：M1 策略库读不了，跳过（{type(e).__name__}: {e}）")
        return 0
    changed = False
    for s in m1.data.get("strategies", []):
        if not isinstance(s, dict) or s.get("asset_id"):
            continue
        segments = s.get("segments")
        if isinstance(segments, list) and segments:
            texts = [str(t or "").strip() for t in segments if str(t or "").strip()]
        else:
            whole = str(s.get("function") or "").strip()
            texts = [whole] if whole else []
        if not texts:
            continue
        try:
            asset = _import(store, texts, s.get("params_text"),
                            str(s.get("name") or ""), SOURCE_BACKTEST)
            s["asset_id"] = asset["id"]
            changed = True
            n += 1
        except Exception as e:                         # noqa: BLE001 —— 坏条目跳过自己
            logger.warning(f"函数总库迁移：策略「{s.get('name')}」跳过（{type(e).__name__}: {e}）")
    if changed:
        m1.save()
    return n


def _migrate_scan(store) -> int:
    """M2/M3 方案 → 资产（`config.formula` 一段；target=main，扫描无窗格概念）。"""
    n = 0
    try:
        scan = get_scan_strategy_store()
    except Exception as e:                             # noqa: BLE001
        logger.warning(f"函数总库迁移：方案库读不了，跳过（{type(e).__name__}: {e}）")
        return 0
    changed = False
    for s in scan.data.get("strategies", []):
        if not isinstance(s, dict):
            continue
        cfg = s.get("config")
        if not isinstance(cfg, dict) or cfg.get("asset_id"):
            continue
        formula = str(cfg.get("formula") or "").strip()
        if not formula:
            continue
        try:
            asset = _import(store, [formula], cfg.get("params"),
                            str(s.get("name") or ""), SOURCE_SCAN)
            cfg["asset_id"] = asset["id"]
            changed = True
            n += 1
        except Exception as e:                         # noqa: BLE001
            logger.warning(f"函数总库迁移：方案「{s.get('name')}」跳过（{type(e).__name__}: {e}）")
    if changed:
        scan.save()
    return n


def _import(store, texts, params_text, name_hint: str, origin: str) -> dict:
    """收编一条；**先按内容找**（老配方库里可能早就有同一份函数）——有就复用，没有才新建。"""
    hit = find_by_content(store, texts, str(params_text or ""))
    if hit is not None:
        return hit
    return upsert_asset(store, name_hint, texts, str(params_text or ""), origin)


__all__ = ['ensure_hub_migration', 'asset_texts']
