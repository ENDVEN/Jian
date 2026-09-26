# data/em_throttle.py
"""东财匿名额度的**退避闸门**（★v6.69）—— 全仓库唯一出处。

【为什么必须有它】实测（§11.5-99）：东财 `push2` 对**匿名**请求有**频次窗** —— 连打几十次即
  **整段拒绝**（0.7s 内 RST），静置约 30 分钟自恢复。而我们的旧接线比这更糟：**一次扫描完成会
  同时起两串各 ~56 页的全市场请求**（估值 `ak.stock_zh_a_spot_em` + 行业分页直取）⇒
  **自己把自己的额度打光**。用户实测 2026-09-26 19:37 的日志正是这个形态：

      19:37:04  行业分页拉取失败(page=1): RemoteDisconnected
      19:37:11  全市场估值快照(spot_em)失败: RemoteDisconnected

  两条相隔 7 秒，且**连第 1 页都拒** ⇒ 额度在行业那次开始之前就已经被占掉了。

【这个模块解决什么】① 失败即**冷却**（指数退避）；② 冷却期内**不联网**、并把原因**说出来**
  （回执/tooltip 拿 `describe()`）；③ 冷却状态**跨重启**（存 `preferences['em_throttle']`）
  ⇒ 重启后不会立刻又去打一串；④ 成功一次就清零（额度是"连打才拒"，单次能过就说明窗已恢复）。

【口径】冷却上限 60 分钟（比实测恢复窗 30 分钟更保守 —— 宁可少打，不再自伤）。
  只记状态、不做判断；"要不要联网"由各通道在动手前问 `cooldown_left()`。
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


def _state() -> dict:
    """当前退避状态（任何异常/旧版本残留 ⇒ 当作"没有状态"）。"""
    raw = preferences.get(THROTTLE_KEY)
    return raw if isinstance(raw, dict) else {}


def cooldown_left(now: float = None) -> float:
    """还剩多少秒才允许再打（0 = 可以打）。"""
    try:
        until = float(_state().get('cooldown_until') or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, until - (time.time() if now is None else float(now)))


def is_cooling(now: float = None) -> bool:
    return cooldown_left(now) > 0


def describe(now: float = None) -> str:
    """给人话的冷却说明（不在冷却 ⇒ 空串）。回执里直接拼它，别再自己算分钟。"""
    left = cooldown_left(now)
    if left <= 0:
        return ''
    return f"东财限流冷却中（约 {int(left // 60) + 1} 分钟后再试）"


def note_success() -> None:
    """成功一次 ⇒ 清零。**没有失败记录时什么都不写**（省一次落盘）。"""
    st = _state()
    if st.get('fails') or st.get('cooldown_until'):
        preferences.set(THROTTLE_KEY, {'fails': 0, 'cooldown_until': 0,
                                       'last_ok_ts': time.time()})
        logger.info("东财取数恢复正常 ⇒ 退避计数清零")


def note_failure(kind: str = '', reason='') -> dict:
    """失败一次 ⇒ 记一次退避（返回新状态，便于上层就地说明）。"""
    st = _state()
    try:
        fails = int(st.get('fails') or 0) + 1
    except (TypeError, ValueError):
        fails = 1
    fails = min(fails, FAILS_CAP)
    wait = min(COOLDOWN_BASE_SECONDS * (2 ** (fails - 1)), COOLDOWN_MAX_SECONDS)
    state = {'fails': fails, 'cooldown_until': time.time() + wait,
             'last_fail_ts': time.time(), 'last_kind': str(kind or ''),
             'last_reason': str(reason or '')[:200]}
    preferences.set(THROTTLE_KEY, state)
    logger.warning(f"东财取数失败[{kind or '-'}] ⇒ 冷却 {wait / 60:.0f} 分钟"
                   f"（第 {fails} 次）: {reason}")
    return state


def reset() -> None:
    """清空退避（测试与"手动重试"用）。"""
    preferences.set(THROTTLE_KEY, {'fails': 0, 'cooldown_until': 0})
