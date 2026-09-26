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

【单位归一（§9-V 命门，只在这里换一次）】成交量 `f5` = **手** ⇒ ×`EM_VOLUME_UNIT` 成股；
  换手率 `f8` = **百分数** ⇒ ÷100 成小数；市值 `f20`/`f21` = 元。
【失败口径】一律**不上抛**（回空表 / 空 map）+ 记一次退避（`em_throttle.note_failure`）；
  上层据此保留旧缓存并显示 '—'，绝不因一个源挂了而中断整批。
"""
from __future__ import annotations

import logging
import time

import pandas as pd
import requests

from data import em_throttle

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
INDUSTRY_PAGE_INTERVAL = 0.5               # 页间等待（分页通道默认）
QUOTE_BATCH_INTERVAL = 0.15                # 包间等待（批量通道默认）

# 全市场 A 股（沪/深主板 + 创业板 + 科创板），与"快照 / 估值"同一 `fs`
EM_FS_A = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

INDUSTRY_FIELDS = "f12,f14,f100"
QUOTE_FIELDS = "f12,f14,f2,f17,f15,f16,f18,f5,f6,f8,f9,f20,f21,f23"

# 字段码 → 系统标准列名（**唯一映射**；上层拿到的都是标准名）
QUOTE_RENAME = {
    'f12': 'symbol', 'f14': 'name', 'f2': 'close', 'f17': 'open', 'f15': 'high',
    'f16': 'low', 'f18': 'prev_close', 'f5': 'volume', 'f6': 'amount', 'f8': 'turnover',
    'f9': 'pe', 'f23': 'pb', 'f20': 'total_mktcap', 'f21': 'outstanding_share',
}
QUOTE_COLUMNS = ('symbol', 'name', 'close', 'open', 'high', 'low', 'prev_close', 'volume',
                 'amount', 'turnover', 'pe', 'pb', 'total_mktcap', 'outstanding_share')
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
# HTTP 边界（**测试只打桩这两个函数**，编排逻辑一律可离网验证）
# ==========================================
def clist_page(page: int, pz: int = EM_PAGE_SIZE) -> tuple:
    """取 `clist` 一页 ⇒ `(rows, total)`；网络/接口异常**上抛**给编排层去记退避。"""
    params = {"pn": max(1, int(page)), "pz": max(1, int(pz)), "po": 1, "np": 1,
              "ut": EM_UT, "fltt": 2, "invt": 2, "fid": "f12", "fs": EM_FS_A,
              "fields": INDUSTRY_FIELDS}
    resp = requests.get(EM_CLIST_URL, params=params, headers=EM_HEADERS,
                        timeout=EM_TIMEOUT_SECONDS)
    data = (resp.json() or {}).get("data") or {}
    return (data.get("diff") or []), int(data.get("total") or 0)


def ulist_page(codes) -> list:
    """取**一批**代码的报价 ⇒ rows；网络/接口异常**上抛**给编排层去记退避。"""
    params = {"fltt": 2, "invt": 2, "ut": EM_UT,
              "secids": ",".join(secid(c) for c in codes), "fields": QUOTE_FIELDS}
    resp = requests.get(EM_ULIST_URL, params=params, headers=EM_HEADERS,
                        timeout=EM_TIMEOUT_SECONDS)
    data = (resp.json() or {}).get("data") or {}
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
    return df.reset_index(drop=True)


# ==========================================
# 编排层 ①：行业分页（分批 + 断点续抓 + 退避）
# ==========================================
def fetch_industry_page(page_start: int = 1, pages: int = 1,
                        sleep_fn=time.sleep, interval: float = INDUSTRY_PAGE_INTERVAL,
                        should_stop=None) -> dict:
    """从东财 `clist` 分页取**全市场**「代码→所属行业」（字段 `f100`）。

    :param page_start: 从第几页开始（1-based）—— **断点续抓**用
    :param pages:      本次最多抓几页（上层按"每次扫描补几页"摊平）
    :param sleep_fn:   页间等待（可注入；测试传 `lambda _s: None`）
    :param interval:   页间间隔秒
    :param should_stop: 可调用对象；返回 True ⇒ **在页与页之间**收手（关窗/取消用）
    :return: `{"map", "page_start", "pages_done", "total_pages", "done", "error"}`；
             `error` 非空 = 本次没抓成（已按退避规则记一笔），上层据此保留旧缓存并出声。
    ⚠ 失败（网络/风控/接口变更）⇒ `map` 为空 dict、`done=False`，**绝不上抛**。
    """
    empty = {"map": {}, "page_start": max(1, int(page_start)), "pages_done": 0,
             "total_pages": 0, "done": False, "error": ""}
    cooling = em_throttle.describe()
    if cooling:
        logger.info(f"行业分页跳过（{cooling}）")
        return dict(empty, error=cooling)

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
            em_throttle.note_failure('clist', e)
            return dict(empty, error=em_throttle.describe() or str(e))
        if not rows:
            break
        out.update(rows_to_industry(rows))
        em_throttle.note_success()
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
    cooling = em_throttle.describe()
    if cooling:
        logger.info(f"批量报价跳过（{cooling}）")
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
            em_throttle.note_failure('ulist', e)
            break
        em_throttle.note_success()
        frames.append(rows_to_quotes(rows))
        if i + QUOTE_BATCH_SIZE < len(codes):
            sleep_fn(interval)
    got = [f for f in frames if f is not None and not f.empty]
    if not got:
        return empty_quotes()
    return pd.concat(got, ignore_index=True)
