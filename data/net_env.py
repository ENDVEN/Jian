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

# ★1.70 / §11.5-124：**进程级 socket 默认超时（秒）** —— 终结"无超时网络调用永久挂起"。
# 【为什么必须落在 socket 层】akshare 的**新浪**日线接口（`stock_zh_a_daily`）**不接受 timeout 参数**，
#   内部 6 处 `requests.get(...)` 全裸奔 ⇒ 对端"连上了却不回 TLS 响应"时 `recv` **永久阻塞**。
#   用户 2026-10-11 实测（py-spy 抓栈）：两个下载线程卡在 `ssl.do_handshake`，CPU 4 秒纹丝不动、
#   点「中断」毫无反应、连关窗都要等它 —— 因为取消只在请求**之间**检查。
#   `socket.setdefaulttimeout()` 是**唯一**能同时管住"连接 / TLS 握手 / 读取"的层，且作用于整个进程
#   （含 akshare 内部）。与 `_set_ipv4_only` 同性质：正因影响面大，所以必须可配置、且进启动日志。
DEFAULT_TIMEOUT_SECONDS = 20
TIMEOUT_MIN, TIMEOUT_MAX = 5, 120

# 已生效的地址族设置（幂等：重复 apply 不会反复 patch/还原）
_applied_ipv4 = None

# 已生效的进程级 socket 默认超时（★1.70，幂等）
_applied_timeout = None

# ★1.70：**当前生效的 requests 默认超时**（注入的包装函数闭包读它 ⇒ 改设置无需重打补丁）
_req_timeout = DEFAULT_TIMEOUT_SECONDS

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
    try:
        timeout = int(d.get('timeout', DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    return {'force_ipv4': bool(d.get('force_ipv4', DEFAULT_FORCE_IPV4)),
            'proxy_mode': (d.get('proxy_mode') if d.get('proxy_mode') in PROXY_MODES
                           else DEFAULT_PROXY_MODE),
            # ★1.70：夹进合理区间 —— 脏偏好**不可能**把超时设成 0/负数/999（那就等于没有超时，
            #   正是本轮要根除的形态）；越界一律夹回边界，绝不静默放行。
            'timeout': max(TIMEOUT_MIN, min(TIMEOUT_MAX, timeout))}


def force_ipv4_enabled() -> bool:
    return settings_dict()['force_ipv4']


def proxy_mode() -> str:
    return settings_dict()['proxy_mode']


def default_timeout() -> int:
    """单次网络操作的**进程级**超时秒数（唯一真源 = 偏好 `net.timeout`，默认 20）。"""
    return settings_dict()['timeout']


def _install_requests_default_timeout(seconds: int) -> None:
    """给 `requests` 注入**默认超时**（幂等）—— 这才是真正管住 akshare 的那一层。

    【为什么 socket 默认超时不够（实测打脸，别删这段）】`socket.setdefaulttimeout()` 看着万能，
      但 `requests`/`urllib3` 建连接时会**显式**调 `sock.settimeout(self.timeout)`，而调用方不传
      timeout 时它就是 `None` ⇒ **把进程默认超时覆盖回"永久阻塞"**。2026-10-11 用本地黑洞端口实测：
      `socket 默认超时 = 20.0` 的前提下，`requests.get(url)` 与 `requests.get(url, timeout=None)`
      **30 秒都不返回**（= 等于没修）。⇒ 结论：**必须在 requests 层注入**（akshare 内部全是
      `requests.get(...)`，全部经 `Session.request` 这一处）；socket 默认超时只当"非 requests 通道"的兜底。

    【注入口径】只在调用方**没给** timeout（或显式给了 None）时补 `(n, n)`（连接与读取各自计时）；
      调用方自己指定的（如东财的 `timeout=15`）**一律尊重**，绝不覆盖 —— 否则会悄悄改写其它模块的口径。
    """
    try:
        import requests
    except Exception as e:                                # noqa: BLE001
        logger.warning(f"无法给 requests 注入默认超时（保持各调用点原样）: {e}")
        return
    session_cls = requests.sessions.Session
    if getattr(session_cls, '_jian_orig_request', None) is None:
        session_cls._jian_orig_request = session_cls.request

    def _request_with_default_timeout(self, method, url, *args, **kwargs):
        # `timeout` 在 `Session.request` 里是第 7 个位置参数 ⇒ 位置传了就绝不碰（防"重复赋值"）
        if len(args) < 7 and kwargs.get('timeout') is None:
            kwargs['timeout'] = (_req_timeout, _req_timeout)
        return session_cls._jian_orig_request(self, method, url, *args, **kwargs)

    session_cls.request = _request_with_default_timeout
    logger.info(f"已为 requests 注入默认超时 = {seconds}s（连接与读取各自计时）")


def _set_default_timeout(seconds: int) -> None:
    """设**进程级**网络超时（幂等）：① requests 层注入（**主**）；② socket 默认超时（兜底）。

    ⚠ 影响本进程**所有**出网请求（含 akshare 内部没写 timeout 的调用）—— 这正是目的；
      代价是"慢但会成功"的长请求也会被判超时，所以区间夹在 5~120 秒、且可在设置里改。
    ⚠ 只管**新建立**的连接（两者都是"创建/发起时"生效），存量连接不动。
    """
    global _applied_timeout, _req_timeout
    if seconds == _applied_timeout:
        return
    _req_timeout = seconds                                 # 闭包读它 ⇒ 改值无需重打补丁
    if not getattr(_install_requests_default_timeout, '_patched', False):
        _install_requests_default_timeout(seconds)
        _install_requests_default_timeout._patched = True
    socket.setdefaulttimeout(float(seconds))               # 兜底：非 requests 通道（裸 socket 等）
    _applied_timeout = seconds
    logger.info(f"网络默认超时 = {seconds}s（requests 注入为主 + 进程级 socket 兜底）")


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
    _set_default_timeout(s['timeout'])          # ★1.70 / §11.5-124：进程级 socket 默认超时
    return s


def describe() -> str:
    """给人话的一行（日志 / tooltip 用）：`IPv4 优先 · 代理=自动（失败即降级直连）· 超时=20s`。"""
    s = settings_dict()
    _ip = "IPv4 优先" if s['force_ipv4'] else "地址族=系统默认"
    _proxy = {'auto': "代理=自动（失败即降级直连）", 'direct': "代理=直连",
              'proxy': "代理=只用系统代理"}.get(s['proxy_mode'], s['proxy_mode'])
    return f"{_ip} · {_proxy} · 超时={s['timeout']}s"
