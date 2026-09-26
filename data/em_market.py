# data/em_market.py
"""东财 `push2` 的**两条取数通道**（★v6.69）—— 全仓库唯一的东财行情明细出口。

【为什么独立成文件】§11.7 纪律：`data/akshare_feed.py` 再加新源前先分文件（它已 665 行）。
  而东财这套"字段码 → 语义 + 单位"的映射是一整块独立知识，混在日线清洗里最容易踩 §9-V 的 100× 事故。

【两条通道（都只干"取数 + 单位归一"：不落库、不判"该算哪一天"）】
  ① **分页全市场列表** `clist/get` → `fetch_industry_page()`：一次能拿全市场「代码→所属行业」(`f100`)。
     实测硬约束：**单页上限 100 行**（请求 1000 也只回 100）；全市场 ~5560 只 ⇒ **~56 页**
     ⇒ 必须**分批 + 断点续抓**（上层每批抓几页，分几次扫描摊平；补齐后长期缓存、零请求）。
  ② **批量报价** `ulist.np/get` → `fetch_quotes()`：一次可带**多个代码**，`f9/f20/f21/f23`（市盈率 /
     市净率 / 总市值 / 流通市值）与价量全在（实测 2026-09-26：2 只一次 200，字段全有）
     ⇒ 估值列与"当天秒补"**只需按标的取**（池子多大就打几个"100 只"的包）。

【为什么 ② 是这次的关键】旧写法 `ak.stock_zh_a_spot_em()` 内部 `pz=100` + **逐页翻** ⇒
  它本身就是一串 **~56 页的隐藏突发**；而它（估值/秒补）与行业分页**同时开火** ⇒ 匿名额度被
  自己打光（§11.5-100）。改成按标的批量后，**常见场景 1 个请求**（单只同步）到 2–3 个请求（几百只池子）。

【★v6.73 双档（登录 / 匿名）】`clist`/`ulist` 都支持带 `Cookie`；实测**带 Cookie = 200、同刻匿名 = RST**
  ⇒ 登录档常速（页间隔 0.15s / 每批 10 页）、匿名档保持 v6.69 的慢速（0.5s / 每批 3 页 + 退避冷却）。
  档位与页数**只在本文件判定**（`current_tier()` / `pages_per_scan()` / `page_interval()`），
  并叠一层**每日取数额度**闸门（`budget_blocked()`：超了"停在缓存档"，不拿账号去硬试）。
【单位归一（§9-V 命门，只在这里换一次）】成交量 `f5` = **手** ⇒ ×`EM_VOLUME_UNIT` 成股；
  换手率 `f8` = **百分数** ⇒ ÷100 成小数；市值 `f20`/`f21` = 元。
【失败口径】一律**不上抛**（回空表 / 空 map）+ 记一次退避（`em_throttle.note_failure`）；
  上层据此保留旧缓存并显示 '—'，绝不因一个源挂了而中断整批。
"""
from __future__ import annotations

import logging
import random
import time

import pandas as pd
import requests

from data import em_auth, em_throttle, net_env

logger = logging.getLogger(__name__)

# 系统内部统一的标准量价列名 (Canonical OHLCV Schema) —— 与 akshare_feed 同口径
EM_VOLUME_UNIT = 100                       # 东财「成交量」单位 = 手（1 手 = 100 股）

EM_TIMEOUT_SECONDS = 15
EM_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://quote.eastmoney.com/",
}
EM_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EM_ULIST_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EM_UT = "bd1d9ddb04089700cf9c27f6f7426281"

EM_PAGE_SIZE = 100                         # clist 单页上限（实测：pz=1000 也只回 100 行）
QUOTE_BATCH_SIZE = 100                     # ulist 一批带多少代码（与单页上限同量级）
INDUSTRY_PAGE_INTERVAL = 0.5               # 页间等待（**匿名档**默认；见 TIER_PAGE_INTERVAL）
QUOTE_BATCH_INTERVAL = 0.15                # 包间等待（批量通道默认）

# ==========================================
# ★v6.73 双档（登录 / 匿名）—— **档位参数的唯一出处**（页面与上层别再自己写死 3 / 0.5）
#   【判据（2026-09-26 同刻对照实测）】带 Cookie `clist`/`ulist` = HTTP 200 + 真实数据；
#     同一刻匿名 = `RemoteDisconnected`（被 RST）⇒ **门槛是"登录态"，不是无差别封 IP**。
#   【所以】登录 ⇒ 常速（页间隔更短、每批更多页）；匿名 ⇒ 现有慢速档（0.5s / 每批 3 页 + 退避冷却）。
#   ⚠ 登录档也**绝不做全市场高频轮询**（产品级风控纪律，见 `data/em_auth.py` 文件头）。
# ==========================================
TIER_AUTH = 'auth'
TIER_ANON = 'anon'
TIER_BATCH_PAGES = {TIER_AUTH: 10, TIER_ANON: 3}          # 行业：每次扫描最多补几页
TIER_PAGE_INTERVAL = {TIER_AUTH: 0.15, TIER_ANON: INDUSTRY_PAGE_INTERVAL}   # 行业：页间隔秒


def current_tier() -> str:
    """当前档位：登录三元组齐 ⇒ `auth`；否则 `anon`。**只读凭据状态，不发请求**。"""
    try:
        return TIER_AUTH if em_auth.is_logged_in() else TIER_ANON
    except Exception as e:                                # noqa: BLE001 —— 判据坏了按匿名档（最保守）
        logger.warning(f"登录态判据失败（按匿名慢速档处理）: {type(e).__name__}: {e}")
        return TIER_ANON


def tier_text() -> str:
    """给人话（设置页 / 回执用）。"""
    return "登录档（常速）" if current_tier() == TIER_AUTH else "匿名档（慢速分批）"


def pages_per_scan() -> int:
    """本次扫描最多补几页行业 —— **唯一出处**（页面别写死页数）。"""
    return int(TIER_BATCH_PAGES.get(current_tier(), TIER_BATCH_PAGES[TIER_ANON]))


def page_interval() -> float:
    """行业页间隔（按档位）。"""
    return float(TIER_PAGE_INTERVAL.get(current_tier(), INDUSTRY_PAGE_INTERVAL))


def budget_blocked() -> str:
    """今日额度用完 ⇒ 回一句人话；**空串 = 没被挡**。

    【为什么要挡】用户拍板"要避免被反爬系统盯上" —— 反复点扫描会把额度（乃至账号）打进风控。
    挡住的语义是"**停在缓存档**"：已抓到的行业/报价照常从缓存读，明天自动恢复。
    """
    who = current_tier()
    try:
        if em_auth.budget_left(who) > 0:
            return ''
        return (f"今日东财取数额度已用完（{em_auth.budget_text(who)}）—— 明天自动恢复；"
                f"已抓到的数据仍从缓存读，不必反复点")
    except Exception as e:                                # noqa: BLE001 —— 判据坏了不挡（别因它停工）
        logger.warning(f"取数额度判据失败（本次不拦）: {type(e).__name__}: {e}")
        return ''

# 全市场 A 股（沪/深主板 + 创业板 + 科创板），与"快照 / 估值"同一 `fs`
EM_FS_A = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

INDUSTRY_FIELDS = "f12,f14,f100"
# ★v6.74：批量报价**带上行业 `f100`** —— 实测（2026-09-27 00:0x · 带 Cookie）同一个 `ulist` 请求
#   同时返回「行业 + 市盈率/市净率/市值 + 价量」（`600000→银行Ⅱ`、`300750→电池`，HTTP 200）。
#   ⇒ 沪深300 的**行业只要 3 个请求**（100 只/请求）、全 A 也只要 **56 个**；而"全市场分页"要 56 页
#   且按代码序补齐时小池子命中率极低（沪深300 里的沪市票根本轮不到）。
#   ⇒ 行业 / 估值 / 秒补**共用同一次请求**（这才是"一条通道喂三处"的正确形态）。
QUOTE_FIELDS = "f12,f14,f2,f17,f15,f16,f18,f5,f6,f8,f9,f20,f21,f23,f100"

# 字段码 → 系统标准列名（**唯一映射**；上层拿到的都是标准名）
QUOTE_RENAME = {
    'f12': 'symbol', 'f14': 'name', 'f2': 'close', 'f17': 'open', 'f15': 'high',
    'f16': 'low', 'f18': 'prev_close', 'f5': 'volume', 'f6': 'amount', 'f8': 'turnover',
    'f9': 'pe', 'f23': 'pb', 'f20': 'total_mktcap', 'f21': 'outstanding_share',
    'f100': 'industry',
}
QUOTE_COLUMNS = ('symbol', 'name', 'close', 'open', 'high', 'low', 'prev_close', 'volume',
                 'amount', 'turnover', 'pe', 'pb', 'total_mktcap', 'outstanding_share',
                 'industry')
_NUMERIC_COLUMNS = ('open', 'high', 'low', 'close', 'prev_close', 'volume', 'amount',
                    'turnover', 'pe', 'pb', 'total_mktcap', 'outstanding_share')


def secid(symbol: str) -> str:
    """`600000 → 1.600000`（沪） / `000001 → 0.000001`（深、北）。

    东财 `secids` 的约定：`1` = 沪市（含 5/6/9 开头的基金与 B 股），`0` = 深市（含北交所）。
    本函数只服务**批量报价**这一条通道，不参与任何落库键的构造。
    """
    code = str(symbol).strip()
    return f"1.{code}" if code[:1] in ('5', '6', '9') else f"0.{code}"


def empty_quotes() -> pd.DataFrame:
    """空表也带**完整列名**（上层 `set(columns) <= 白名单` 的断言才不会因缺列而误红）。"""
    return pd.DataFrame(columns=list(QUOTE_COLUMNS))


# ==========================================
# ★v6.72 传输层：**地址族 + 代理策略 + 失败分类**的唯一出口
#   【为什么要有它】用户实测（2026-09-26 22:13 "只点了一次扫描，抓了一部分就开始失败"）：
#     `requests` 默认吃**系统代理**（clash-verge 写 WinINET：`ProxyEnable=1 / 127.0.0.1:7897`），
#     且 DNS 把 **IPv6 排在前面**，而东财的 IPv6 端点不通（同一时刻：`curl -4` HTTP 200 /
#     `curl -6` HTTP 000）⇒ 每次先撞 IPv6 再抛 `RemoteDisconnected`；代理那一跳不稳则是
#     `ProxyError`。两件事都在 `data/net_env.py` 里统一处置。
#   【口径】`proxy_mode='auto'`（默认）：跟随系统代理 ⇒ **只在代理报错时**降级**直连重试一次**；
#     直连成功后**本轮会话**都直连（`_direct_locked`，不再每次白撞一跳）。
#     ⚠ 用户工作环境常常**必须**走代理 ⇒ **绝不默认绕过代理**（那是 `proxy_mode='direct'` 的事）。
# ==========================================
_SESSIONS: dict = {}
_STATE = {'direct_locked': False, 'proxy_err': ''}

PROXY_HINT = ("疑似本机代理问题（已尝试直连仍失败）—— 重试无用：请检查代理软件是否在运行 / "
              "切换节点 / 临时关闭系统代理")

# ★v6.74 全局最小间隔：**任意两个东财请求之间 ≥ `MIN_REQUEST_GAP_SECONDS`**（跨通道统一）。
#   【为什么要跨通道】三条通道各自"看起来不快"，叠在同一秒里就是密集突发 —— 实测 clist 页间隔
#     0.15s（一秒内 6+ 个请求）⇒ 第 11 页被 RST。这里收口成"**全进程一条节流线**"，并带小抖动
#     （避免"完美等间隔"的机器特征）。测试可把 `_sleep_fn` 换成 `lambda _s: None`。
MIN_REQUEST_GAP_SECONDS = 0.8
MIN_GAP_JITTER_SECONDS = 0.25
_LAST_REQ = {'ts': 0.0}
_sleep_fn = time.sleep


def _respect_min_gap() -> float:
    """等够最小间隔（返回实际等待秒数 —— 断言/日志用）。"""
    now = time.monotonic()
    wait = MIN_REQUEST_GAP_SECONDS - (now - _LAST_REQ['ts'])
    if wait > 0:
        wait += random.uniform(0, MIN_GAP_JITTER_SECONDS)
        try:
            _sleep_fn(wait)
        except Exception:                                 # noqa: BLE001 —— 睡不了也别卡死，继续发
            pass
    _LAST_REQ['ts'] = time.monotonic()
    return max(0.0, wait)


def _session(use_proxy: bool):
    """按模式取（并缓存）`requests.Session`：复用连接 + 显式决定"吃不吃系统代理"。

    ⚠ `trust_env=False` = **忽略环境变量与系统(WinINET)代理** ⇒ 真直连；`True` = 跟随系统。
    """
    key = 'proxy' if use_proxy else 'direct'
    sess = _SESSIONS.get(key)
    if sess is None:
        sess = requests.Session()
        sess.trust_env = bool(use_proxy)
        sess.headers.update(EM_HEADERS)
        _SESSIONS[key] = sess
    return sess


def _do_get(url: str, params: dict, use_proxy: bool) -> dict:
    """发一次请求（唯一真正碰网络的地方）⇒ JSON 字典。

    ★v6.73 双档：登录 ⇒ 每请求带 `Cookie`（`em_auth.cookie_header()`）；未登录 ⇒ 不带。
      同时**记一次真实请求**（按天计入每日预算 ⇒ 防"狂点把账号打进风控"）。
    ⚠ 凭据只进请求头：**永远不进日志、回执、文档、断言**（只报名字与条数）。
    """
    headers = None
    try:
        cookie = em_auth.cookie_header() or ''
    except Exception as e:                                # noqa: BLE001 —— 读不出来就按匿名档发
        logger.warning(f"读登录凭据失败（本次按匿名档发请求）: {type(e).__name__}: {e}")
        cookie = ''
    if cookie:
        headers = {'Cookie': cookie}
    _respect_min_gap()                                    # ★v6.74 全进程节流线（跨通道统一）
    em_auth.note_request(current_tier())
    resp = _session(use_proxy).get(url, params=params, headers=headers,
                                   timeout=EM_TIMEOUT_SECONDS)
    return resp.json() or {}


def _http_get(url: str, params: dict, *, kind: str) -> dict:
    """唯一 HTTP 出口：应用网络策略 → 发一次 → **代理报错则降级直连重试一次**。"""
    net_env.apply()
    mode = net_env.proxy_mode()
    use_proxy = (mode != 'direct') and not _STATE['direct_locked']
    if mode == 'proxy':
        use_proxy = True                      # 用户明说"只走代理" ⇒ 不降级
    try:
        return _do_get(url, params, use_proxy)
    except Exception as e:                    # noqa: BLE001 —— 分类后可能降级重试
        if not (use_proxy and mode == 'auto' and net_env.looks_like_proxy_error(e)):
            raise
        logger.warning(f"东财取数[{kind}]经代理失败（疑似本机代理问题）⇒ 降级直连重试一次: {e}")
        _STATE['proxy_err'] = str(e)[:200]
        try:
            data = _do_get(url, params, False)
        except Exception as e2:               # noqa: BLE001 —— 直连也不行 ⇒ 按"代理问题"报上去
            logger.warning(f"东财直连重试也失败: {e2}")
            raise e from e2
        _STATE['direct_locked'] = True
        logger.warning("东财取数临时改用**直连**（本轮会话；代理修好后重启应用即恢复走代理）")
        return data


def direct_locked() -> bool:
    """本轮会话是否已因代理报错而降级直连（回执里说一句，用户才知道发生了什么）。"""
    return bool(_STATE['direct_locked'])


def _record_failure(kind: str, err) -> str:
    """失败记账的**唯一出口**：代理类 ⇒ 代理口径（不算限流）；其余 ⇒ 限流退避。

    :return: 给人话的一句（上层回执直接拼它，别自己拼分钟数）
    """
    if net_env.looks_like_proxy_error(err):
        em_throttle.note_proxy_failure(kind, err)
        return PROXY_HINT + ("（本轮已临时改用直连）" if direct_locked() else "")
    em_throttle.note_failure(kind, err)
    return em_throttle.describe() or str(err)


# ==========================================
# HTTP 边界（**测试只打桩这两个函数**，编排逻辑一律可离网验证）
# ==========================================
def clist_page(page: int, pz: int = EM_PAGE_SIZE) -> tuple:
    """取 `clist` 一页 ⇒ `(rows, total)`；网络/接口异常**上抛**给编排层去记退避。"""
    params = {"pn": max(1, int(page)), "pz": max(1, int(pz)), "po": 1, "np": 1,
              "ut": EM_UT, "fltt": 2, "invt": 2, "fid": "f12", "fs": EM_FS_A,
              "fields": INDUSTRY_FIELDS}
    payload = _http_get(EM_CLIST_URL, params, kind='clist')
    data = (payload or {}).get("data") or {}
    return (data.get("diff") or []), int(data.get("total") or 0)


def ulist_page(codes) -> list:
    """取**一批**代码的报价 ⇒ rows；网络/接口异常**上抛**给编排层去记退避。"""
    params = {"fltt": 2, "invt": 2, "ut": EM_UT,
              "secids": ",".join(secid(c) for c in codes), "fields": QUOTE_FIELDS}
    payload = _http_get(EM_ULIST_URL, params, kind='ulist')
    data = (payload or {}).get("data") or {}
    return data.get("diff") or []


# ==========================================
# 行 → 标准列（映射 + 单位归一）
# ==========================================
def rows_to_industry(rows) -> dict:
    """`[{f12, f100}]` ⇒ `{code: 行业}`（空名 / `'-'` / 非 6 位码一律不入库）。"""
    out = {}
    for row in rows or []:
        code = str(row.get('f12') or '').strip()
        name = str(row.get('f100') or '').strip()
        if len(code) == 6 and code.isdigit() and name and name != '-':
            out[code] = name
    return out


def rows_to_quotes(rows) -> pd.DataFrame:
    """报价 rows ⇒ 标准列（**单位已归一**：成交量 手→股、换手率 百分数→小数）。"""
    if not rows:
        return empty_quotes()
    df = pd.DataFrame(list(rows)).rename(columns=QUOTE_RENAME)
    df = df[[c for c in QUOTE_COLUMNS if c in df.columns]].copy()
    if 'symbol' not in df.columns:
        return empty_quotes()
    df['symbol'] = df['symbol'].astype(str).str.strip()
    df = df[df['symbol'].str.match(r'^\d{6}$', na=False)]
    for col in _NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')   # 东财缺值是 '-' ⇒ NaN
    if 'volume' in df.columns:
        df['volume'] = df['volume'] * EM_VOLUME_UNIT            # 手 → 股（§9-V）
    if 'turnover' in df.columns:
        df['turnover'] = df['turnover'] / 100.0                 # 百分数 → 小数
    if 'industry' in df.columns:                                # ★v6.74 行业是**文本**列
        df['industry'] = (df['industry'].fillna('').astype(str).str.strip()
                          .replace({'-': '', 'nan': '', 'None': ''}))
    return df.reset_index(drop=True)


def industry_from_quotes(df) -> dict:
    """从 `fetch_quotes` 的结果里抽 `{code: 行业}`（空 / `-` / 非 6 位码一律不入库）。

    ★v6.74：这是"**按池补行业**"的入口 —— 与 `rows_to_industry`（分页通道）**同一套校验口径**，
      上层拿到就能直接 `industry_store.merge()`。
    """
    if df is None or getattr(df, 'empty', True) or 'industry' not in getattr(df, 'columns', ()):
        return {}
    out = {}
    for rec in df.to_dict('records'):
        code = str(rec.get('symbol') or '').strip()
        name = str(rec.get('industry') or '').strip()
        if len(code) == 6 and code.isdigit() and name and name != '-':
            out[code] = name
    return out


# ==========================================
# ★v6.74 / §7-B13 · S2-1b「网络与取数自检」
#   【为什么只发 1 个请求】用户拍板"避免被反爬系统盯上" ⇒ 自检**不刷量**：
#     策略 / 代理 / DNS / 登录 / 档位 / 额度 / 退避 全部**零请求**（读本机状态）；
#     只有 `probe=True` 时发 **1 个** `ulist`（1 只票）来验"现在这一刻能不能取到数"。
#   【为什么自检**不记退避**】诊断不是生产流量 —— 免得用户点一次自检就把自己关 10 分钟。
# ==========================================
_PROBE_SYMBOL = '600000'      # 自检只问这一只（浦发银行：老牌大盘股，字段最全）


def _proxy_info() -> dict:
    """本机代理指纹（**零请求**）：`requests` 实际会吃的代理（环境变量 + WinINET，§11.5-103）。"""
    env = {}
    try:
        import requests
        env = dict(requests.utils.getproxies() or {})
    except Exception as e:                                    # noqa: BLE001
        logger.warning(f"读代理设置失败（不影响自检）: {type(e).__name__}: {e}")
    return {'env': env, 'present': bool(env),
            'note': ('检测到本机代理 —— 请求会经它；代理不稳就会 ProxyError' if env
                     else '未检测到代理 —— 直连')}


def _dns_info() -> dict:
    """解析 `push2.eastmoney.com` 的 A/AAAA（**零请求**，只看本机 DNS 怎么答）。

    【为什么要看它】实测坑（§11.5-103）：本机 DNS 把 **IPv6 排在前面**，而东财 IPv6 端点不通
      ⇒ 不限定地址族就会"额度充足也莫名失败"。
    """
    import socket

    host = 'push2.eastmoney.com'
    out = {'host': host, 'ipv4': [], 'ipv6': []}
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except Exception as e:                                    # noqa: BLE001
        out['error'] = f'{type(e).__name__}: {str(e)[:120]}'
        return out
    for fam, _t, _p, _c, addr in infos:
        ip = addr[0]
        if fam == socket.AF_INET and ip not in out['ipv4']:
            out['ipv4'].append(ip)
        elif fam == socket.AF_INET6 and ip not in out['ipv6']:
            out['ipv6'].append(ip)
    return out


def _probe_once() -> dict:
    """发 **1 个** `ulist`（1 只票）验"现在能不能取到数"（如实计入每日额度，但**不记退避**）。"""
    t0 = time.monotonic()
    try:
        rows = ulist_page([_PROBE_SYMBOL])
    except Exception as e:                                    # noqa: BLE001 —— 自检绝不上抛
        return {'ok': False, 'ms': int((time.monotonic() - t0) * 1000),
                'symbol': _PROBE_SYMBOL,
                'error': f'{type(e).__name__}: {str(e)[:160]}'}
    return {'ok': bool(rows), 'ms': int((time.monotonic() - t0) * 1000),
            'symbol': _PROBE_SYMBOL, 'rows': len(rows or []),
            'note': '' if rows else '请求成功但**没有数据**（可能被限流，或该代码无返回）'}


def self_check(probe: bool = True) -> dict:
    """**网络与取数自检** ⇒ 结构化结果（键固定，便于断言与展示）。

    `probe=False` ⇒ **完全零请求**（只读本机状态）；`probe=True` ⇒ 额外发 1 个请求。
    """
    _net = net_env.settings_dict()
    out = {'policy': {'text': net_env.describe(), 'force_ipv4': bool(_net.get('force_ipv4')),
                      'proxy_mode': _net.get('proxy_mode')},
           'proxy': _proxy_info(),
           'dns': _dns_info(),
           'probe': {'skipped': True, 'ok': None},
           'auth': em_auth.status(),
           'tier': {'tier': current_tier(), 'text': tier_text(),
                    'pages_per_scan': pages_per_scan(), 'page_interval': page_interval()},
           'budget': {'auth_left': em_auth.budget_left('auth'),
                      'anon_left': em_auth.budget_left('anon'),
                      'used': em_auth.budget_text(current_tier())},
           'throttle': {'text': em_throttle.describe_all(),
                        'cooling': em_throttle.is_cooling(),
                        'fails': {k: v.get('fails') for k, v in em_throttle.channels().items()}},
           'direct_locked': direct_locked()}
    if probe:
        out['probe'] = _probe_once()
    return out


def _verdict(r: dict) -> str:
    """一句话结论 + 建议（自检的**真正价值**：告诉用户"现在该做什么"）。"""
    if r['throttle'].get('cooling'):
        return f"当前受限：{r['throttle']['text']} —— 等它过去再扫（不必连点）"
    if r['policy'].get('force_ipv4') is False:
        return '建议在设置里打开「地址族限定 IPv4」（本机 IPv6 端点不通会让请求莫名失败）'
    p = r.get('probe') or {}
    if p.get('skipped'):
        return '未做连通性探测（本轮零请求）'
    if p.get('ok'):
        return f"取数正常（{p.get('ms')} 毫秒）—— 可以按现在的节奏扫"
    if not r['auth'].get('logged_in'):
        return '取数失败且**未登录** —— 可粘贴东财凭据提升稳定性（登录档常速）'
    return '取数失败但**登录态正常** —— 多为本机代理/网络问题，见上方代理与 DNS 两行'


def self_check_text(probe: bool = True) -> str:
    """自检的**人话报告**（多行）—— 写日志、显示在设置页状态行/tooltip 都用它。"""
    r = self_check(probe=probe)
    dns, px, au = r['dns'], r['proxy'], r['auth']
    p = r.get('probe') or {}
    if p.get('skipped'):
        probe_line = '· 连通性：未探测（本轮零请求）'
    elif p.get('ok'):
        probe_line = (f"· 连通性：✅ {p.get('symbol')} 取到 {p.get('rows')} 行 · "
                      f"{p.get('ms')} 毫秒")
    else:
        probe_line = (f"· 连通性：❌ {p.get('error') or p.get('note') or '无数据'}"
                      f"（{p.get('ms')} 毫秒）")
    money = '已加密（DPAPI）' if au.get('encrypted') else ('⚠ 明文存储' if au.get('present') else '—')
    lines = [
        '【网络与取数自检】',
        f"· 网络策略：{r['policy']['text']}",
        f"· 代理：{px['note']}" + (f"（{', '.join(px['env'].values())}）" if px['env'] else ''),
        f"· DNS：IPv4 {len(dns.get('ipv4') or [])} 条 / IPv6 {len(dns.get('ipv6') or [])} 条"
        + (f" · 解析失败：{dns.get('error')}" if dns.get('error') else ''),
        probe_line,
        f"· 登录：{'已登录 ' + str(au.get('count')) + ' 条 · ' + money if au.get('logged_in') else '未登录'}",
        f"· 档位：{r['tier']['text']} · 行业每批 {r['tier']['pages_per_scan']} 页 · "
        f"页间隔 {r['tier']['page_interval']}s",
        f"· 额度：{r['budget']['used']}",
        f"· 退避：{r['throttle']['text']}",
        f"· 结论：{_verdict(r)}",
    ]
    return '\n'.join(lines)


# ==========================================
# 编排层 ①：行业分页（分批 + 断点续抓 + 退避）
# ==========================================
def fetch_industry_page(page_start: int = 1, pages: int = 1,
                        sleep_fn=time.sleep, interval: float = None,
                        should_stop=None) -> dict:
    """从东财 `clist` 分页取**全市场**「代码→所属行业」（字段 `f100`）。

    :param page_start: 从第几页开始（1-based）—— **断点续抓**用
    :param pages:      本次最多抓几页（**页面用 `pages_per_scan()` 取，别写死**）
    :param sleep_fn:   页间等待（可注入；测试传 `lambda _s: None`）
    :param interval:   页间间隔秒；**None ⇒ 按档位**（`page_interval()`：登录 0.15 / 匿名 0.5）
    :param should_stop: 可调用对象；返回 True ⇒ **在页与页之间**收手（关窗/取消用）
    :return: `{"map", "page_start", "pages_done", "total_pages", "done", "error"}`；
             `error` 非空 = 本次没抓成（已按退避规则记一笔），上层据此保留旧缓存并出声。
    ⚠ 失败（网络/风控/接口变更）⇒ `map` 为空 dict、`done=False`，**绝不上抛**。
    """
    empty = {"map": {}, "page_start": max(1, int(page_start)), "pages_done": 0,
             "total_pages": 0, "done": False, "error": ""}
    cooling = em_throttle.describe(kind='clist')          # ★v6.74 只看**本通道**的冷却
    if cooling:
        logger.info(f"行业分页跳过（{cooling}）")
        return dict(empty, error=cooling)
    blocked = budget_blocked()
    if blocked:                                          # ★v6.73 预算：停在缓存档（一个请求都不打）
        logger.info(f"行业分页跳过（{blocked}）")
        return dict(empty, error=blocked)
    if interval is None:                                 # ★v6.73 档位间隔（登录才敢快一点）
        interval = page_interval()

    out, total, pages_done = {}, 0, 0
    page = max(1, int(page_start))
    want = max(1, int(pages))
    for i in range(want):
        if should_stop is not None and should_stop():
            break
        try:
            rows, total = clist_page(page, EM_PAGE_SIZE)
        except Exception as e:                   # noqa: BLE001 —— 单页失败 ⇒ 停在这页（下次续）
            logger.warning(f"行业分页拉取失败(page={page}): {e}")
            return dict(empty, error=_record_failure('clist', e))
        if not rows:
            break
        out.update(rows_to_industry(rows))
        em_throttle.note_success('clist')
        pages_done += 1
        page += 1
        if total and (page - 1) * EM_PAGE_SIZE >= total:
            break                                # 已到末页
        if i + 1 < want:
            sleep_fn(interval)
    total_pages = (-(-int(total) // EM_PAGE_SIZE)) if total else 0
    return {"map": out, "page_start": max(1, int(page_start)), "pages_done": pages_done,
            "total_pages": total_pages,
            "done": bool(total_pages and page > total_pages), "error": ""}


# ==========================================
# 编排层 ②：批量报价（按标的；估值 / 秒补共用）
# ==========================================
def fetch_quotes(symbols, sleep_fn=time.sleep, interval: float = QUOTE_BATCH_INTERVAL,
                 should_stop=None) -> pd.DataFrame:
    """**按标的**批量取报价（`{symbol: 价量 + pe/pb/市值}`）⇒ 标准列 DataFrame（单位已归一）。

    :param symbols: 标的清单（去重保序）；**空/None ⇒ 回空表**（本通道不做"全市场一把抓"）
    :param should_stop: 包与包之间检查（关窗/取消用）
    ⚠ 失败 ⇒ 已拿到的部分照常返回（上层对缺的标的诚实回退逐只），空表 = 一个都没拿到。
    """
    codes = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    codes = list(dict.fromkeys(codes))           # 去重保序（同一只票重复请求白费额度）
    if not codes:
        return empty_quotes()
    cooling = em_throttle.describe(kind='ulist')          # ★v6.74 只看**本通道**（clist 失败不再连坐）
    if cooling:
        logger.info(f"批量报价跳过（{cooling}）")
        return empty_quotes()
    blocked = budget_blocked()                           # ★v6.73 预算：共用同一条闸门
    if blocked:
        logger.info(f"批量报价跳过（{blocked}）")
        return empty_quotes()

    frames = []
    for i in range(0, len(codes), QUOTE_BATCH_SIZE):
        if should_stop is not None and should_stop():
            break
        chunk = codes[i:i + QUOTE_BATCH_SIZE]
        try:
            rows = ulist_page(chunk)
        except Exception as e:                   # noqa: BLE001 —— 退避 + 交回已拿到的部分
            logger.warning(f"批量报价失败（{len(chunk)} 只）: {e}")
            _record_failure('ulist', e)
            break
        em_throttle.note_success('ulist')
        frames.append(rows_to_quotes(rows))
        if i + QUOTE_BATCH_SIZE < len(codes):
            sleep_fn(interval)
    got = [f for f in frames if f is not None and not f.empty]
    if not got:
        return empty_quotes()
    return pd.concat(got, ignore_index=True)
