# data/net_env.py
"""行情取数的**网络环境策略**（★v6.72）—— **地址族**与**代理指纹**两件事的唯一出处。

【为什么要有它】用户实测 2026-09-26 22:13（"只点了一次扫描，抓了一部分就开始失败"）的日志是
  `ProxyError('Unable to connect to proxy')`。逐层实测下来是**两件事叠在一起**：

  ① **DNS 把 IPv6 排在前面，而东财的 IPv6 端点不通**（同一时刻对照）：
        DNS: push2.eastmoney.com → [IPv6 240e:e1:8000:1b04::25d, IPv4 117.184.38.132]
        curl -4（IPv4 直连）→ HTTP 200 · 0.18 秒
        curl -6（IPv6 直连）→ HTTP 000（连接即被断）
     而 `requests` / `urllib3` **没有可靠的 Happy-Eyeballs 回退**：第一次连 IPv6 被断就直接抛
     `RemoteDisconnected` ⇒ **额度充足也会"莫名失败"** ⇒ 本模块把地址族**限定为 IPv4**。

  ② **系统代理在中间**（clash-verge 写 WinINET：`ProxyEnable=1 / ProxyServer=127.0.0.1:7897`），
     而 `requests` 读的是 **WinINET + 环境变量**（⚠ `netsh winhttp show proxy` **看不到**它 ——
     v6.68 那轮据此判"不是代理"，是**判据选错了工具**，详见 §11.5-103）⇒ 代理那一跳不稳时
     表现为 `ProxyError`。⚠ 用户工作环境**常常必须走代理** ⇒ **绝不默认绕过**，只在代理**报错时**
     降级直连（见 `data/em_market.py` 的传输层）。

【为什么地址族是"进程级"改】`urllib3` 的地址族偏好是解释器级的，而两条链路里还有 akshare
  自带的 `requests`（改不到它的 session）⇒ 只能在这一层统一。正因为影响面是整个进程，
  它必须有**单一出口 + 可回退开关**（偏好 `net`）。

【口径】偏好 `net = {"force_ipv4": true, "proxy_mode": "auto"}`（键缺/脏值一律逐项回落默认）：
  · `force_ipv4` 默认 **true** —— 实测 IPv4 直连 0.18 秒、IPv6 不通；关掉即恢复系统默认；
  · `proxy_mode` 三档：`auto`（默认：跟随系统代理，**代理报错才降级直连**）/
    `direct`（永不代理）/ `proxy`（只走代理，不降级 —— 给"必须走代理"的网络）。
"""
from __future__ import annotations

import logging
import socket

from core.preferences import preferences

logger = logging.getLogger(__name__)

NET_KEY = 'net'
DEFAULT_FORCE_IPV4 = True
DEFAULT_PROXY_MODE = 'auto'
PROXY_MODES = ('auto', 'direct', 'proxy')

# 已生效的地址族设置（幂等：重复 apply 不会反复 patch/还原）
_applied_ipv4 = None

# ★v1.38 / §7-E2 的**本机代理问题**指纹（原住 `data/sync_service.py`，v6.72 搬到本模块 ——
#   因为 `em_market` 也要用它，而 sync_service → akshare_feed → em_market 是既有的单向链，
#   反向 import 会成环）。`sync_service` 仍 **re-export** 同一个对象 ⇒ 老调用点零改动。
PROXY_HINTS = (
    "proxyerror",                      # requests.exceptions.ProxyError 的类名
    "unable to connect to proxy",      # 实测报错原文（§9.3）
    "cannot connect to proxy",
    "proxy",                           # 兜底：消息里出现 proxy 这个词基本就是代理问题
)


def _error_text(value) -> str:
    """异常或文本 ⇒ 小写文本（`ProxyError.__str__` 里带着原始 cause，够判）。"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value.lower()
    parts = [type(value).__name__, str(value)]
    cause = getattr(value, '__cause__', None) or getattr(value, '__context__', None)
    if cause is not None:
        parts.append(str(cause))
    return ' '.join(parts).lower()


def looks_like_proxy_error(value) -> bool:
    """是不是**本机代理问题**的失败指纹（§7-E2）—— 纯函数，文案层 / 传输层 / 熔断层共用。

    【为什么要单独一个判据】§9.3 实测：本机系统代理（Clash 类）瞬断时，一轮同步里**每一只**
    都报 `ProxyError('Unable to connect to proxy')`。用户该做的动作是"**去查代理软件**"，
    而不是"稍后重试 / 调大间隔" —— 与普通断网、被限流**必须分开安抚**（§10-10）。

    :param value: 异常实例，或已经是文本（大小写不敏感）
    """
    text = _error_text(value)
    return any(h in text for h in PROXY_HINTS)


def settings_dict() -> dict:
    """当前网络策略（逐项回落默认，绝不因偏好脏了而报错）。"""
    raw = preferences.get(NET_KEY)
    d = raw if isinstance(raw, dict) else {}
    return {'force_ipv4': bool(d.get('force_ipv4', DEFAULT_FORCE_IPV4)),
            'proxy_mode': (d.get('proxy_mode') if d.get('proxy_mode') in PROXY_MODES
                           else DEFAULT_PROXY_MODE)}


def force_ipv4_enabled() -> bool:
    return settings_dict()['force_ipv4']


def proxy_mode() -> str:
    return settings_dict()['proxy_mode']


def _set_ipv4_only(flag: bool) -> None:
    """把 `urllib3` 的地址族偏好设成"只要 IPv4"（或还原系统默认）—— **幂等**。

    ⚠ 进程级：影响本进程**所有** `requests`/`urllib3` 出网（含 akshare 内部）——这正是目的
      （拿不到 akshare 的 session），也正是必须留开关的原因。
    """
    global _applied_ipv4
    if flag == _applied_ipv4:
        return
    try:
        import urllib3.util.connection as _u3c
    except Exception as e:                                # noqa: BLE001 —— 改不了就诚实放弃
        logger.warning(f"无法调整 urllib3 地址族偏好（保持系统默认）: {e}")
        return
    if flag:
        if getattr(_u3c, '_JIAN_ORIG_GAI', None) is None:
            _u3c._JIAN_ORIG_GAI = _u3c.allowed_gai_family
        _u3c.allowed_gai_family = (lambda: socket.AF_INET)
    else:
        _orig = getattr(_u3c, '_JIAN_ORIG_GAI', None)
        if _orig is not None:
            _u3c.allowed_gai_family = _orig
            _u3c._JIAN_ORIG_GAI = None
    _applied_ipv4 = flag


def apply() -> dict:
    """应用当前策略（幂等、零网络）⇒ 返回生效设置。**每次取数前调一次**也无所谓（很便宜）。"""
    s = settings_dict()
    _set_ipv4_only(s['force_ipv4'])
    return s


def describe() -> str:
    """给人话的一行（日志 / tooltip 用）：`IPv4 优先 · 代理=自动（失败即降级直连）`。"""
    s = settings_dict()
    _ip = "IPv4 优先" if s['force_ipv4'] else "地址族=系统默认"
    _proxy = {'auto': "代理=自动（失败即降级直连）", 'direct': "代理=直连",
              'proxy': "代理=只用系统代理"}.get(s['proxy_mode'], s['proxy_mode'])
    return f"{_ip} · {_proxy}"
