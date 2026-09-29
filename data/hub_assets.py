# data/hub_assets.py
"""ƒ 函数总库的**数据层助手**（★1.61 / §7-B16 · 实现方案书 `docs/JIAN_HUB_PLAN.md`）。

【为什么单列一个件】总库要回答的四个问题都横跨"资产库 ↔ M1 策略库 ↔ M2/M3 方案库"，
  放进任何一个 store 都会造成反向依赖；这里只做**纯数据操作**（零 Qt），三个 store 各自
  保持边界（§7-B12 拍板"各存各的"不变 —— 本模块只是读它们、按 `asset_id` 把关系算出来）。

【四个职责】
  ① 内容命中 `find_by_content` —— 把"页面当前的函数段+参数"对到资产库里的同一条；
  ② 资产收编 `upsert_asset` —— 保存策略/方案时把函数导成资产（同名同内容 = 复用，
     同名**不同**内容 = 加后缀新建，绝不静默覆盖用户手存配方）；
  ③ 引用计数 `ref_counts` —— 扫两库里 `asset_id` 的命中（**动态计算，绝不落盘**；
     行情页的 `used_at` 是"最近使用"，不算引用）；
  ④ 快照时效 `stale_snapshot` / 删除清引用 `delete_asset`。
"""
from __future__ import annotations

from data.formula_store import (SOURCE_BACKTEST, SOURCE_HUB, SOURCE_SCAN,
                                normalize_segments)
from data.formula_store import get_formula_store
from data.scan_strategy_store import get_scan_strategy_store
from data.strategy_store import StrategyStore

# 同名但内容不同时的命名后缀（诚实标注来源，防"按名覆盖"误伤用户手存配方）
_ORIGIN_SUFFIX = {SOURCE_BACKTEST: " ·M1", SOURCE_SCAN: " ·扫描", SOURCE_HUB: ""}


def asset_texts(asset: dict) -> list[str]:
    """资产的函数段文本列表（归一化后取 text，段序 = 保存序）。"""
    return [seg["text"] for seg in normalize_segments((asset or {}).get("segments"))]


def _signature(texts, params_text: str) -> str:
    """内容签名：段文本（去空白后）+ 参数文本。命中判定只认这个，绝不按名字猜。"""
    body = "|".join(str(t or "").strip() for t in (texts or []) if str(t or "").strip())
    return body + "##" + str(params_text or "").strip()


def query(store, src: str = "all", text: str = "", sort_key: str = "used",
          refs: dict = None) -> list[dict]:
    """按 **来源 + 关键词 + 排序** 过滤资产 —— **唯一口径**（总库 A 页与浮窗都调它）。

    【为什么必须是函数】两个界面各写一份过滤/排序，用户切页面就会看到"同一个库、两种顺序"，
      甚至一边搜得到一边搜不到（§11.5-11）。
    :param refs: `ref_map()` 的结果（排序键 `refs` 会用到）；`None` = 现算一次。
    """
    items = [f for f in store.all()
             if src in (None, "", "all") or f.get("source") == src]
    key = str(text or "").strip().lower()
    if key:
        def _blob(f):
            return " ".join([f.get("name", ""), f.get("params_text", "")]
                            + [seg.get("text", "") for seg in f.get("segments", [])]).lower()
        items = [f for f in items if key in _blob(f)]
    if sort_key == "name":
        items.sort(key=lambda f: f.get("name", ""))
    elif sort_key == "refs":
        if refs is None:
            refs = ref_map()
        items.sort(key=lambda f: -sum(len(v) for v in ref_counts(f["id"], refs).values()))
    else:
        items.sort(key=lambda f: (f.get("used_at") or "", f.get("name", "")), reverse=True)
    return items


def find_by_content(store, texts, params_text: str = "") -> dict | None:
    """按**内容**（段文本 + 参数）在资产库找同一条；没有 = None（调用方决定新建）。"""
    want = _signature(texts, params_text)
    for asset in store.all():
        if _signature(asset_texts(asset), asset.get("params_text")) == want:
            return asset
    return None


def upsert_asset(store, name_hint: str, segments, params_text: str = "",
                 origin: str = SOURCE_HUB) -> dict:
    """把一份函数收编成资产（保存策略/方案时调用；**幂等**）。

    规则：
      · 内容命中已有资产 ⇒ 直接复用它（`touch` 不做 —— "保存"不是"使用"）；
      · 名字相同但内容不同 ⇒ 资产名追加来源后缀（` ·M1` / ` ·扫描`）新建，
        **绝不按名覆盖**用户手存的同名配方；
      · 名字空 / 冲突后仍重名 ⇒ 用 `hub` 前缀兜底命名（资产名只用于展示，唯一性由 id 保证）。
    """
    texts = [str(t or "").strip() for t in _texts_of(segments) if str(t or "").strip()]
    params_text = str(params_text or "").strip()
    hit = find_by_content(store, texts, params_text)
    if hit is not None:
        return hit
    base = str(name_hint or "").strip() or "未命名函数"
    candidate = base
    n = 0
    while store.get_by_name(candidate) is not None:
        # 名字被占：内容不同（内容相同早就命中返回了）⇒ 首次按来源加后缀，之后加序号。
        # ⚠ `hub` 来源的后缀是**空串**（总库新建的不必再标"来自总库"）⇒ 别把空后缀当成一次改名，
        #   否则会白跑一轮查询；空后缀直接进序号档。
        n += 1
        suffix = _ORIGIN_SUFFIX.get(origin, "") if n == 1 else ""
        candidate = f"{base}{suffix}" if suffix else f"{base} ·{n + 1}"
        if n > 50:                                   # 兜底：极端重名也别死循环
            candidate = f"hub {base} {n}"
            break
    name = candidate
    return store.upsert({"name": name, "segments": [{"text": t, "target": "main"} for t in texts],
                         "params_text": params_text, "source": origin})


def _texts_of(segments) -> list[str]:
    """容忍三种形态：[text] / [(text,target)] / [{text,target}]（照 formula_store 的口径）。"""
    out = []
    for entry in (segments if segments is not None else []):
        if isinstance(entry, dict):
            out.append(str(entry.get("text") or ""))
        elif isinstance(entry, (tuple, list)):
            out.append(str(entry[0] or ""))
        else:
            out.append(str(entry or ""))
    return out


# ==========================================
# 引用计数（动态计算 —— 两库里的 `asset_id` 是唯一事实来源）
# ==========================================
def ref_map() -> dict:
    """**一次**扫完两个库 → `{asset_id: {"m1": [...], "m2m3": [...]}}`。

    【为什么必须有它（性能，不是风格）】`ref_counts(id)` 每调一次就**现开一次** `StrategyStore()`
    （= 读一次 JSON 文件）。总库里每条资产都要显示引用数（排序键 `refs` 还要再算一遍）
    ⇒ N 条资产 = **2N 次读盘**；而 `HubFlow.refresh()` 挂在搜索框 `textChanged` 上
    ⇒ **用户每敲一个字就要读盘几十次**（库一大直接卡手）。
    列表刷新一律走本函数：一次读盘，算一张表，之后按 id 查。
    """
    out: dict[str, dict] = {}
    try:
        for s in StrategyStore().data.get("strategies", []):
            aid = s.get("asset_id")
            if aid:
                out.setdefault(str(aid), {"m1": [], "m2m3": []})["m1"].append(
                    str(s.get("name") or "未命名"))
    except Exception:                                  # noqa: BLE001 —— 计数坏了不拖垮总库
        pass
    try:
        for s in get_scan_strategy_store().data.get("strategies", []):
            cfg = s.get("config")
            aid = cfg.get("asset_id") if isinstance(cfg, dict) else None
            if aid:
                out.setdefault(str(aid), {"m1": [], "m2m3": []})["m2m3"].append(
                    str(s.get("name") or "未命名"))
    except Exception:                                  # noqa: BLE001
        pass
    return out


def ref_counts(asset_id: str, mapping: dict = None) -> dict:
    """`(M1 策略名列表, M2/M3 方案名列表)`。

    :param mapping: `ref_map()` 的结果。**列表刷新一律传它**（否则每次调用都读一遍盘）；
                    单点查询（删除前确认之类）可以省略 —— 那时代价只有一次读盘。
    """
    if not asset_id:
        return {"m1": [], "m2m3": []}
    if mapping is None:
        mapping = ref_map()
    return mapping.get(str(asset_id)) or {"m1": [], "m2m3": []}


def stale_snapshot(asset_id: str, texts, params_text: str = "") -> dict | None:
    """资产内容 vs 方案里的内联快照是否已分叉。

    返回**资产**（= 总库有更新版）；None = 一致 / 没有引用 / 资产已删（回落快照即可，不算"有更新"）。
    供 M1 / M2·M3 载入时提示用（红线②：绝不静默改变已存方案的函数）。
    """
    if not asset_id:
        return None
    asset = get_formula_store().get(asset_id)
    if asset is None:
        return None
    if _signature(asset_texts(asset), asset.get("params_text")) == _signature(texts, params_text):
        return None
    return asset


def delete_asset(store, asset_id: str) -> tuple[bool, dict]:
    """从资产库删除一条，并**尽力清空**两库里的悬挂引用（引用方的内联快照原样保留）。

    ⚠ 删除确认（键入「删除」）在 UI 层做（§10-10 分级）；这里只管数据：
      返回 `(是否删除, 引用清单)`。引用方在**别处的内存实例**不受影响 —— 它们之后保存时
      payload 不带 asset_id 会自然丢弃（M1 `item.update(payload)` 保留旧键的问题：
      悬挂 asset_id 无害 —— 载入时资产查不到即回落快照，ref_counts 也按现存资产过滤）。
    """
    asset = store.get(asset_id)
    if asset is None:
        return False, {"m1": [], "m2m3": []}
    refs = ref_counts(asset_id)
    removed = store.delete(asset_id)
    # 尽力清引用：现开现写现关（页面各自持有的实例之后保存时不会带 asset_id —— payload 不含它）
    try:
        m1 = StrategyStore()
        changed = False
        for s in m1.data.get("strategies", []):
            if s.get("asset_id") == asset_id:
                s.pop("asset_id", None)
                changed = True
        if changed:
            m1.save()
    except Exception:                                  # noqa: BLE001 —— 清引用失败不拦删除
        pass
    try:
        scan = get_scan_strategy_store()
        changed = False
        for s in scan.data.get("strategies", []):
            cfg = s.get("config")
            if isinstance(cfg, dict) and cfg.get("asset_id") == asset_id:
                cfg.pop("asset_id", None)
                changed = True
        if changed:
            scan.save()
    except Exception:                                  # noqa: BLE001
        pass
    return removed, refs
