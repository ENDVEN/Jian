# data/em_throttle.py
"""东财取数的**退避闸门**（★v6.69 起；★v6.74 改为**按通道**）—— 全仓库唯一出处。

【为什么必须有它】实测（§11.5-99）：东财 `push2` 有**频次窗** —— 连打几十次即**整段拒绝**
  （RST），静置约 30 分钟自恢复；而我们的旧接线一度"一次扫描同时起两串各 ~56 页的全市场请求"
  ⇒ **自己把自己的额度打光**（用户 2026-09-26 19:37 的两条日志正是这个形态）。

【★v6.74 为什么必须**按通道**】实测 2026-09-26 23:59（用户真机）：
      23:59:32  行业分页拉取失败(page=11) ⇒ 冷却 10 分钟 [clist]
      23:59:53  批量报价跳过（东财限流冷却中）        ← **ulist 被 clist 的冷却连坐了**
  而同一时段（冷却中）带 Cookie 的 `ulist` 仍然 **HTTP 200** ⇒ **两个端点各自限额、互不连坐**。
  ⇒ 现在状态**按 `kind` 分桶**（`clist` / `ulist` / `hist` …）；`kind=None` 的查询给"**最坏的那个**"
    （界面总览用）。这样"行业分页失败"再也停不掉"估值 / 秒补 / 按池取行业"。

【口径（★v6.74 收紧）】① 退避阶梯 10 → 20 → 40 → 60 分钟封顶（比实测恢复窗 30 分钟更保守）；
  ② **任何失败后该通道至少静默 `MIN_RETRY_GAP_SECONDS`(60s)** —— 不再"0.15s 密集重试"；
  ③ 连续成功 `SUCCESS_STREAK_TO_CLEAR` 次才清该通道（防间歇故障骗过，§11.5-104）；
  ④ **代理类失败单列**（固定 5 分钟 + "去查代理、重试无用"，§10-10 直说）；
  ⑤ 状态**跨重启**（存 `preferences['em_throttle']`），兼容 v6.73 以前的**单桶旧格式**。
"""
from __future__ import annotations

import logging
import time

from core.preferences import preferences

logger = logging.getLogger(__name__)

THROTTLE_KEY = 'em_throttle'
COOLDOWN_BASE_SECONDS = 10 * 60      # 首次失败：冷却 10 分钟
COOLDOWN_MAX_SECONDS = 60 * 60       # 上限：60 分钟
FAILS_CAP = 4                        # 退避倍数的封顶台阶（10 → 20 → 40 → 60 分钟）
SUCCESS_STREAK_TO_CLEAR = 2          # ★v6.72 抗抖动：**连续**成功几次才认为窗已恢复
PROXY_COOLDOWN_SECONDS = 5 * 60      # ★v6.72 代理类失败：固定冷却 5 分钟（不是限流、别指数退避）
MIN_RETRY_GAP_SECONDS = 60           # ★v6.74 任何失败后，该通道至少静默 1 分钟

ALL_CHANNELS = ('clist', 'ulist', 'hist')    # 已知通道（仅用于展示；别的 kind 会自动分桶）


# ==========================================
# 读（一切"能不能打"的判断都问这里）
# ==========================================
def _raw() -> dict:
    raw = preferences.get(THROTTLE_KEY)
    return raw if isinstance(raw, dict) else {}


def _norm(st) -> dict:
    """单通道状态 ⇒ 统一字段（坏值一律当 0/空，绝不抛给上层）。"""
    st = st if isinstance(st, dict) else {}
    def _num(key, cast, default):
        try:
            return cast(st.get(key) or default)
        except (TypeError, ValueError):
            return cast(default)
    return {'fails': max(0, _num('fails', int, 0)),
            'cooldown_until': max(0.0, _num('cooldown_until', float, 0.0)),
            'streak': max(0, _num('streak', int, 0)),
            'last_fail_ts': max(0.0, _num('last_fail_ts', float, 0.0)),
            'fail_class': str(st.get('fail_class') or ''),
            'last_reason': str(st.get('last_reason') or '')[:200]}


def channels() -> dict:
    """`{通道: 状态}`（只读视图）。

    兼容 **v6.73 以前的单桶旧格式**：老数据是顶层 `fails`/`cooldown_until`，按 `last_kind`
      迁进对应通道（只读迁移、不写盘 —— 下次 `note_*` 落盘时自然变成新格式）。
    """
    raw = _raw()
    box = raw.get('channels')
    if isinstance(box, dict):
        return {str(k): _norm(v) for k, v in box.items()}
    if raw.get('fails') or raw.get('cooldown_until'):
        return {str(raw.get('last_kind') or '*'): _norm(raw)}
    return {}


def _save(box: dict) -> None:
    preferences.set(THROTTLE_KEY, {'channels': {k: _norm(v) for k, v in box.items()},
                                   'updated_at': time.time()})


def cooldown_left(now: float = None, kind: str = None) -> float:
    """还剩多少秒才允许再打（0 = 可以打）。

    `kind=None` ⇒ 取**所有通道里最久**的那个（界面总览 / 无通道信息的旧调用点用）。
    """
    t = time.time() if now is None else float(now)
    box = channels()
    if kind:
        st = box.get(str(kind))
        return max(0.0, st['cooldown_until'] - t) if st else 0.0
    return max([max(0.0, s['cooldown_until'] - t) for s in box.values()] or [0.0])


def is_cooling(now: float = None, kind: str = None) -> bool:
    return cooldown_left(now, kind) > 0


def _worst(now: float = None) -> dict:
    """冷却最久的那条通道（含 `channel` 名）—— 供无 kind 的展示用。"""
    box = channels()
    if not box:
        return {}
    key = max(box, key=lambda c: box[c]['cooldown_until'])
    return dict(box[key], channel=key)


def describe(now: float = None, kind: str = None) -> str:
    """给人话的冷却说明（不在冷却 ⇒ 空串）。回执里直接拼它，别再自己算分钟。"""
    left = cooldown_left(now, kind)
    if left <= 0:
        return ''
    st = (channels().get(str(kind)) or {}) if kind else _worst(now)
    tag = f"[{kind}]" if kind else (f"[{st.get('channel')}]" if st.get('channel') else '')
    if st.get('fail_class') == 'proxy':
        return (f"疑似本机代理问题{tag}（已冷却 {int(left // 60) + 1} 分钟）—— 重试无用："
                "请检查代理软件 / 切换节点 / 临时关闭系统代理")
    return f"东财限流冷却中{tag}（约 {int(left // 60) + 1} 分钟后再试）"


def describe_all(now: float = None) -> str:
    """所有通道一行总览（设置页 / 回执用）—— 让用户看到"是哪一个通道在冷却"。"""
    t = time.time() if now is None else float(now)
    box = channels()
    if not box:
        return '东财取数：正常（无退避）'
    parts = []
    for key in sorted(box):
        left = max(0.0, box[key]['cooldown_until'] - t)
        parts.append(f"{key} " + (f"冷却 {int(left // 60) + 1} 分钟" if left > 0 else '正常'))
    return '东财取数：' + ' · '.join(parts)


# ==========================================
# 写（成功 / 失败）
# ==========================================
def _dirty(st: dict) -> bool:
    return bool(st.get('fails') or st.get('cooldown_until') or st.get('streak'))


def note_success(kind: str = '') -> None:
    """成功一次 ⇒ 该通道累计连击；**连续 `SUCCESS_STREAK_TO_CLEAR` 次**才清零。

    【为什么要连击】间歇故障下（本机代理抖动 / 频次窗边缘）失败与成功会交替出现：实测日志里
      4 毫秒内就完成了 `冷却 → 清零 → 再冷却` ⇒ 冷却永远攒不起来、退避等于没有（§11.5-104）。
    `kind` 为空 ⇒ 对**当前所有有计数的通道**都记一次（旧调用点的"全局一次成功"语义）。
    """
    box = channels()
    keys = [str(kind)] if kind else [k for k, st in box.items() if _dirty(st)]
    changed = False
    for key in keys:
        st = box.get(key)
        if not st:
            continue
        streak = int(st.get('streak') or 0) + 1
        if streak < SUCCESS_STREAK_TO_CLEAR:
            box[key] = dict(st, streak=streak, cooldown_until=st['cooldown_until'])
            changed = True
            logger.info(f"东财取数[{key}]成功 1 次（连击 {streak}/{SUCCESS_STREAK_TO_CLEAR}）"
                        "⇒ 暂不清零（间歇故障时「一成功就清零」会让冷却失效）")
            continue
        box.pop(key, None)
        changed = True
        logger.info(f"东财取数[{key}]恢复正常（连续成功）⇒ 该通道退避清零")
    if changed:
        _save(box)


def _bump(kind: str, wait: float, fail_class: str, reason: str, tag: str) -> dict:
    """失败记账的**唯一落点**（限流 / 代理两类都走它）。"""
    box = channels()
    key = str(kind or '*')
    fails = min(int((box.get(key) or {}).get('fails') or 0) + 1, FAILS_CAP)
    now = time.time()
    wait = max(float(wait), float(MIN_RETRY_GAP_SECONDS))     # ★v6.74 至少静默 1 分钟
    box[key] = {'fails': fails, 'cooldown_until': now + wait, 'last_fail_ts': now,
                'fail_class': fail_class, 'streak': 0, 'last_reason': str(reason or '')[:200]}
    _save(box)
    logger.warning(f"东财取数失败[{key}] ⇒ {tag} {wait / 60:.0f} 分钟（第 {fails} 次）: {reason}")
    return dict(box[key], channel=key)


def note_failure(kind: str = '', reason='') -> dict:
    """失败一次 ⇒ 该通道记一次**限流**退避（指数增长）；返回新状态，便于上层就地说明。"""
    fails = min(int((channels().get(str(kind or '*')) or {}).get('fails') or 0) + 1, FAILS_CAP)
    wait = min(COOLDOWN_BASE_SECONDS * (2 ** (fails - 1)), COOLDOWN_MAX_SECONDS)
    return _bump(kind, wait, 'limit', reason, '冷却')


def note_proxy_failure(kind: str = '', reason='') -> dict:
    """★v6.72：**代理类**失败 ⇒ 固定冷却 `PROXY_COOLDOWN_SECONDS`（并按代理口径说话）。

    【为什么与限流分开】`ProxyError` 说明请求**根本没出去**（本机代理那一跳断了，§7-E2）；
      既不是东财在限流，也就没有"等 10 分钟额度就回来"的道理 —— 该做的是**用户去查代理**。
    """
    return _bump(kind, PROXY_COOLDOWN_SECONDS, 'proxy', reason, '疑似**本机代理问题**，冷却')


def forget(kind: str) -> None:
    """只清某个通道（"手动重试该通道"用）。"""
    box = channels()
    if str(kind) in box:
        box.pop(str(kind), None)
        _save(box) if box else reset()


def reset() -> None:
    """清空全部退避（测试与"手动重试"用）。"""
    preferences.set(THROTTLE_KEY, {'channels': {}, 'fails': 0, 'cooldown_until': 0,
                                   'streak': 0, 'fail_class': ''})
