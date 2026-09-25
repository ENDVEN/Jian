# data/scan_store.py
"""M2 / M3 的**会话内存缓存**（§7-B1/B2 主案 D3 · v6.35）

【为什么不做落盘面板】P1 实测 IO **不是**瓶颈（全市场 `dataset` 一次扫 ≈2.6 s；列投影只省 4%；
row group 全 = 1 ⇒ 尾部窗口无收益）⇒ "落盘派生面板 `kline_panel`"的首要理由不成立（主案 B2 第 1 条）。

【为什么"只缓存结果"就够】**一次扫描产出的状态矩阵本来就是全日期的**（`asof` 不参与公式求值，
只用来取某一行 —— 见主案 D2）。所以切换基准日、切换 M3 统计窗口**天然免费**，
真正值得缓存的是"**读盘 + 逐标的求值**"那一段（单只成本的大头）。
矩阵体积 = `交易日 × 标的 × 1 B`（uint8 四态）⇒ 全市场 ≈ **22 MB**；
而把价量宽表留在内存要 **≈500 MB（f64）/ 250 MB（f32）** —— 省 20 倍，且**进程退出即消失**。

【失效必须含"数据版本"】否则"下了新数据却不重算" = **静默陈旧**（§5 / §10 铁律）。
本模块把它做进**键**里：数据一动 ⇒ 键就变 ⇒ **自动不命中** —— 不需要另写一套"检查是否过期"的逻辑，
也就不会出现"忘了检查"这种漏。

⚠ **本模块只碰内存，不写任何文件**（`~/.jian_data/*` 一个都不碰）⇒ 无需进防污染自检名单。
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import OrderedDict
from dataclasses import dataclass, replace as _dc_replace
from time import perf_counter

import numpy as np
import pandas as pd

from core.cross_section import (
    CrossSectionResult, ScanThresholds, scan_lake, tally_status,
)

__all__ = [
    'ScanKey', 'ScanStore', 'ScanOutcome', 'get_scan_store',
    'formula_fingerprint', 'thresholds_fingerprint', 'universe_fingerprint',
    'data_version', 'kline_zone_dir', 'scan_key', 'scan_cached', 'merge_tail',
]

DEFAULT_MAX_ENTRIES = 2                      # 会话里同时留两套（比如"自选"与"全市场"各一）
DEFAULT_MAX_BYTES = 256 * 1024 * 1024        # 256 MB（全市场一套 ≈22 MB，留足冗余）


# ==========================================
# 1) 键的五样（少一样就是静默陈旧）
# ==========================================
def formula_fingerprint(text: str, params: dict = None) -> str:
    """公式指纹：**忽略注释 / 空白 / 大小写**。

    为什么忽略这三样：用户把 `COND := C > REF(C,1);` 改成 `cond:=c>ref(c,1); // 备注`，
    语义一模一样，**不该重算**（重算一次全市场要几十秒，用户会以为卡了）。
    """
    from core.formula.program import strip_comments       # 复用引擎的注释剥离，不另写一套
    normalized = re.sub(r'\s+', '', strip_comments(text or '')).upper()
    extra = ''
    if params:
        extra = '|' + '&'.join(f'{key}={params[key]}' for key in sorted(params))
    return hashlib.sha1((normalized + extra).encode('utf-8')).hexdigest()[:16]


def thresholds_fingerprint(thresholds: ScanThresholds = None) -> str:
    """粗筛阈值指纹。

    ★【v6.35 修订】**阈值必须进键**：它决定四态里的「**被粗筛剔除**」那一桶 ——
      若不进键，用户改了阈值、界面却还在展示旧分桶 ⇒ **静默陈旧**（正是本键要防的那类事故）。
    """
    items = sorted((thresholds or ScanThresholds()).to_dict().items())
    return hashlib.sha1(repr(items).encode('utf-8')).hexdigest()[:16]


def universe_fingerprint(symbols=None) -> str:
    """标的域指纹（自选 / 指数成分 / 全市场）—— 换域必须失效，否则"自选的结果"会被当成"全市场"。"""
    if symbols is None:
        return 'all'
    keys = sorted(str(item) for item in symbols)
    return f'{len(keys)}-' + hashlib.sha1('\n'.join(keys).encode('utf-8')).hexdigest()[:12]


def data_version(zone_dir: str) -> str:
    """分区"数据版本"指纹 = 文件数 + 每个文件的 `(名, 字节, mtime_ns)` 摘要。

    ★ **不能只看公式哈希**：只看公式 ⇒ "新下载了数据但不重算" = 静默陈旧（§5 / §10 铁律）。
    ⚠ 局限：若文件被替换成**同名同字节且 mtime 被还原**的内容，这里察觉不到。
      对"下载/删除/增量补齐"这三类真实动作（都会改 size 或 mtime）足够。
    ⚠ 成本：全市场 5400 个文件的 `scandir` ≈0.1–0.3 s ⇒ **只在用户主动发起扫描时算一次**
      （日期切换走 `ScanOutcome.status_on()`，不碰这个函数）。
    """
    if not zone_dir or not os.path.isdir(zone_dir):
        return 'missing'
    rows: list[str] = []
    try:
        entries = list(os.scandir(zone_dir))
    except OSError:
        return 'unreadable'
    for entry in entries:
        if not entry.name.lower().endswith('.parquet'):
            continue
        try:
            info = entry.stat()
        except OSError:              # 单个坏文件不该让整次指纹计算失败
            continue
        rows.append(f'{entry.name}:{info.st_size}:{info.st_mtime_ns}')
    rows.sort()
    return f'{len(rows)}-' + hashlib.sha1('\n'.join(rows).encode('utf-8')).hexdigest()[:16]


def kline_zone_dir(zone: str = 'kline_daily') -> str:
    """日线分区目录。

    ⚠ 分区名 → 目录的**权威映射在 `data/market_db.py:DataLakeManager.zones`**；
      这里刻意**不实例化那个类**（它的 `__init__` 会 `makedirs` 所有分区 ——
      "拼一个缓存键"不该有建目录这种副作用）。两处一致性由 `smoke_chart` 的断言钉住。
    """
    from config import settings
    leaf = 'daily' if zone in ('', 'kline_daily', None) else 'daily_raw'
    return os.path.join(settings.USER_DATA_DIR, 'data_lake', 'kline', leaf)


@dataclass(frozen=True)
class ScanKey:
    """会话缓存的键（frozen ⇒ 可做字典键）。六样见 `scan_key()`。"""

    formula: str
    thresholds: str
    universe: str
    adjust: str
    data_version: str
    snapshot: str = ''

    def label(self) -> str:
        """给日志 / 界面回执看的短标识"""
        return (f'{self.formula[:8]}/{self.thresholds[:6]}/{self.universe}'
                f'/{self.adjust}/{self.data_version}')


def scan_key(formula: str, thresholds: ScanThresholds = None, symbols=None,
             adjust: str = 'qfq', zone_dir: str = None, params: dict = None,
             snapshot_columns=()) -> ScanKey:
    """构造缓存键（跨模块的"键"必须有**唯一规范入口** —— §11.5-19 同级纪律）。

    进键的**六样**（少一样 = 静默陈旧）：
      ① 公式指纹（忽略注释/空白/大小写）
      ② **粗筛阈值**（决定"被剔除"桶 —— v6.35 修订，见 `thresholds_fingerprint`）
      ③ 标的域（自选 / 指数成分 / 全市场）
      ④ 复权口径
      ⑤ **数据版本**（分区文件指纹）
      ⑥ 快照列（结果里的 `snapshot` 是按这几个列取的，列不同 ⇒ 内容不同 ⇒ 不能共用）

    ⚠ `asof` **不进键**：一次扫描的矩阵本来就是全日期的 ⇒ "切日期"天然命中（D2 / D3）。

    ⚠⚠ 由此而来的**使用纪律**（STEP 4 界面必须遵守）：命中时 `result.status` / `result.counts`
      / `result.snapshot` / `result.detail` 都是"**扫描时那个 `asof`**"的产物，
      **切日期后一律不要读它们**，改用 `ScanOutcome.status_on(date)` / `counts_on(date)`；
      要展示当日的数值快照，另走"按需取数"（STEP 4 决策项，见主案 D3 的修订注）。
    """
    return ScanKey(
        formula=formula_fingerprint(formula, params),
        thresholds=thresholds_fingerprint(thresholds),
        universe=universe_fingerprint(symbols),
        adjust=str(adjust or 'qfq'),
        data_version=data_version(zone_dir),
        snapshot='-'.join(sorted(str(col) for col in (snapshot_columns or ()))),
    )


# ==========================================
# 2) 缓存本体（LRU + 占用可见可清）
# ==========================================
def _nbytes(result: CrossSectionResult) -> int:
    """粗略估算一条缓存的占用（矩阵是绝对大头；dict 里的短字符串按 200 B/条 估）"""
    total = 0
    for array in (getattr(result, 'status_matrix', None), getattr(result, 'counters', None)):
        total += int(getattr(array, 'nbytes', 0))
    total += len(getattr(result, 'status', {}) or {}) * 200
    return total


class ScanStore:
    """会话内存缓存（**单例**，走 `get_scan_store()`；别自己 `ScanStore()` —— 那会各存各的）。

    · `max_entries` / `max_bytes` 双闸：会话内存**不许无限涨**；
    · 至少留一条（单条就超配额时也留），否则永远缓存不上、白跑；
    · `stats()` 对外暴露占用与命中数 —— §10-10：占用要**看得见、能清**。
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES,
                 max_bytes: int = DEFAULT_MAX_BYTES):
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1, int(max_bytes))
        self.hits = 0
        self.misses = 0
        self._items: 'OrderedDict[ScanKey, CrossSectionResult]' = OrderedDict()

    # ---------- 基本读写 ----------
    def put(self, key: ScanKey, result: CrossSectionResult) -> None:
        self._items[key] = result
        self._items.move_to_end(key)          # 最新用过的排最后
        self._evict()

    def get(self, key: ScanKey):
        result = self._items.get(key)
        if result is None:
            self.misses += 1
            return None
        self.hits += 1
        self._items.move_to_end(key)
        return result

    def find_base(self, key: ScanKey):
        """找「**同配置、旧数据版本**」的条目（⚡ 增量到最新的继承基座，主案 D7）。

        匹配口径 = 键六样里**除数据版本外的那五样**（公式 / 粗筛 / 标的域 / 复权 / 快照列）
        **逐字相等**，且 `data_version` **不同**（相同的那次命中走 `get()`，轮不到这里）。
        多条命中取**最近使用**的那条（LRU 顺序即新鲜度）。找不到返回 None。
        """
        for item_key, result in reversed(self._items.items()):
            if (item_key.formula == key.formula and item_key.thresholds == key.thresholds
                    and item_key.universe == key.universe and item_key.adjust == key.adjust
                    and item_key.snapshot == key.snapshot
                    and item_key.data_version != key.data_version):
                return result
        return None

    # ---------- 维护 ----------
    def _evict(self) -> None:
        while len(self._items) > 1 and (len(self._items) > self.max_entries
                                        or self.bytes_used() > self.max_bytes):
            self._items.popitem(last=False)   # 淘汰最久未用的

    def entries(self) -> int:
        return len(self._items)

    def bytes_used(self) -> int:
        return sum(_nbytes(result) for result in self._items.values())

    def keys(self) -> list:
        return list(self._items.keys())

    def clear(self) -> int:
        """释放全部缓存（"⟳ 全量重算" / 内存体检按钮的后端）；返回清掉几条。"""
        count = len(self._items)
        self._items.clear()
        return count

    def stats(self) -> dict:
        return {
            'entries': len(self._items),
            'bytes': self.bytes_used(),
            'mb': round(self.bytes_used() / 1024 / 1024, 1),
            'hits': self.hits,
            'misses': self.misses,
            'max_entries': self.max_entries,
        }


_STORE: ScanStore | None = None


def get_scan_store() -> ScanStore:
    """进程内单例（与 `data/formula_store.get_formula_store()` 同款约定）"""
    global _STORE
    if _STORE is None:
        _STORE = ScanStore()
    return _STORE


# ==========================================
# 3) 一站式入口（Worker / 页面用这个，别自己拼键）
# ==========================================
@dataclass
class ScanOutcome:
    """带缓存的扫描结果。

    ⚠ **命中时不要看 `result.status` / `result.counts`** —— 它们是"上次扫描时那个 `asof`"的，
      请统一走 `status_on(date)` / `counts_on(date)`（命中与未命中都正确）。

    `note` 是给人看的**一句话过程说明**（M3 的 ⚡ 增量 / ⟳ 重算回执用，§10-10）：
    全量扫描为空串；增量路径会写"增量 +N 个交易日"或"为什么退化为全量"。
    """

    result: CrossSectionResult
    key: ScanKey
    cached: bool = False
    asof: pd.Timestamp | None = None
    elapsed_ms: float = 0.0
    note: str = ''

    def status_on(self, date=None) -> dict:
        stamp = self.asof if date is None else date
        if self.result.status_matrix is None or self.result.dates is None:
            # 没有矩阵（如整份名单都无本地文件，v6.42）⇒ 只能回答基准日那天，
            # 直接用 scan() 当日产出的 status（含「无文件 ⇒ 数据不足」的逐只名单）。
            # ⚠ 早退路径的 result.asof 是 None，界面传来的 stamp 可能是 NaT ——
            #   两者都按"问的就是基准日"处理，否则永远回空表。
            if stamp is None or pd.isna(stamp):
                return dict(self.result.status)
            if (self.result.asof is not None
                    and pd.Timestamp(stamp) == self.result.asof):
                return dict(self.result.status)
            return {}
        return self.result.status_on(stamp)

    def counts_on(self, date=None) -> dict:
        stamp = self.asof if date is None else date
        return tally_status(self.status_on(stamp))

    def breadth_frame(self, start=None) -> pd.DataFrame:
        return self.result.breadth_frame(start)


def merge_tail(base: CrossSectionResult, fresh: CrossSectionResult) -> CrossSectionResult | None:
    """把一次**新扫**的结果里"晚于 `base` 最后交易日"的尾段，接到 `base` 的矩阵后面（D7）。

    ★ 这是「⚡ 增量到最新」的矩阵续接：**历史一天都不动**（`breadth[date]` 只依赖 ≤ date 的数据，
      增量同步只追加新行 ⇒ 旧日期的矩阵仍然逐位正确）；新交易日取自 `fresh`（它的求值
      用的是全历史 —— 引擎逐只的口径不允许"热身窗口"这类静默近似）。

    :returns: 合并后的**新**结果（不改两个入参）；**没有新增交易日时返回 None**（调用方据此
      走"沿用原矩阵"的快速路径）。⚠ 前置条件（调用方必须先保证，这里不再重复断言）：
      `base.symbols == fresh.symbols`（矩阵行序一致）且两者的矩阵/轴线都非空。
    """
    if base.dates is None or base.counters is None or base.status_matrix is None:
        return None
    if fresh.dates is None or fresh.counters is None or fresh.status_matrix is None:
        return None
    tail_mask = fresh.dates > base.dates[-1]
    if not bool(tail_mask.any()):
        return None
    return _dc_replace(
        fresh,
        dates=base.dates.append(fresh.dates[tail_mask]),
        counters=np.concatenate([base.counters, fresh.counters[tail_mask]], axis=0),
        status_matrix=np.concatenate(
            [base.status_matrix, fresh.status_matrix[:, tail_mask]], axis=1),
        symbols=list(base.symbols),                 # 行序以 base 为准（与 fresh 已验证相等）
    )


def scan_cached(zone_dir: str, formula: str, symbols=None, params: dict = None,
                thresholds: ScanThresholds = None, asof=None, names: dict = None,
                adjust: str = 'qfq', store: ScanStore = None, force: bool = False,
                snapshot_columns=(), incremental: bool = False, **kwargs) -> ScanOutcome:
    """带会话缓存的扫描（M2 / M3 的唯一入口）。

    · **命中** ⇒ 完全不读盘、不求值（只用缓存矩阵切片）—— "切日期 / 换统计窗口"走这条；
    · **未命中** ⇒ 走 `scan_lake`（`keep_matrix=True`），结果落缓存；
    · `force=True` ⇒ 强制重扫（"⟳ 全量重算"按钮 / 调试）；
    · `incremental=True` ⇒ **⚡ 增量到最新**（主案 D7）：先 `find_base()` 找同配置旧条目，
      找到就用"新扫全量 + `merge_tail` 尾段续接"——**历史沿用旧矩阵**，界面回执说明增量了几天；
      找不到 / 标的集合变了 / 没有新增交易日，各自有明确回执，**绝不静默**。

    ⚠ **日期切换不要再调本函数**：`asof` 不进键，所以再调一次也只是**换个日期切片**；
      直接 `outcome.status_on(date)` / `outcome.counts_on(date)` 即可（零成本）。

    ⚠ 增量的诚实边界：**求值仍是全历史逐只**（引擎路径的固定开销主导，见 B3 复核），
      "增量"省的是**旧日期的矩阵重算**并保证历史逐位不动 —— 小范围（自选 / 指数成分）确实
      秒级；全市场耗时以回执实测为准。数据被**修订**（非追加）不走这里，用「⟳ 全量重算」。
    """
    store = store or get_scan_store()
    th = thresholds or ScanThresholds()
    key = scan_key(formula, th, symbols, adjust=adjust, zone_dir=zone_dir, params=params,
                   snapshot_columns=snapshot_columns)

    if not force:
        hit = store.get(key)
        if hit is not None:
            want = pd.Timestamp(asof).normalize() if asof is not None else None
            # 缓存命中且“要的就是快照那天”（或没指定 asof）⇒ 直接复用（切日期/换窗口零成本）。
            # ⚠ 但用户显式选了**另一个基准日**去扫 ⇒ 缓存里的数值快照属于旧那天，直接复用
            #   会让结果表数值列全 '—'（用户实测 bug：选历史日 + 开始扫描 = 缓存命中 → 全空）。
            #   这时**必须往下重扫**，为新基准日算出快照（状态矩阵本就全日期，重扫只为补数值）。
            if want is None or hit.asof is None or want == pd.Timestamp(hit.asof).normalize():
                note = ('矩阵已算到最新，无需增量' if incremental else '')
                return ScanOutcome(result=hit, key=key, cached=True,
                                   asof=want if want is not None else hit.asof, note=note)

    started = perf_counter()

    base = store.find_base(key) if (incremental and not force) else None
    if base is not None and base.symbols:
        fresh = scan_lake(zone_dir, formula, symbols=symbols, params=params, thresholds=th,
                          asof=asof, names=names, keep_matrix=True,
                          snapshot_columns=snapshot_columns, **kwargs)
        if fresh.symbols != base.symbols:            # 有标的 newly 有了数据 / 读了不出来 ⇒ 结构变了
            store.put(key, fresh)
            return ScanOutcome(result=fresh, key=key, cached=False, asof=fresh.asof,
                               elapsed_ms=(perf_counter() - started) * 1000,
                               note='参与计算的标的集合变了 ⇒ 已全量重扫')
        merged = merge_tail(base, fresh)
        if merged is None:                           # 数据版本变了但没有新交易日（重下 / 补齐无新增）
            store.put(key, base)
            return ScanOutcome(result=base, key=key, cached=True, asof=base.asof,
                               note='数据没有新增交易日 —— 沿用原矩阵'
                                    '（若怀疑历史被修订，请用「⟳ 全量重算」）')
        store.put(key, merged)
        n_new = int((merged.dates > base.dates[-1]).sum())
        first, last = merged.dates[-n_new], merged.dates[-1]
        return ScanOutcome(result=merged, key=key, cached=False, asof=fresh.asof,
                           elapsed_ms=(perf_counter() - started) * 1000,
                           note=(f'增量 +{n_new} 个交易日'
                                 f'（{pd.Timestamp(first).date()} → {pd.Timestamp(last).date()}）'
                                 f'，历史沿用原矩阵'))

    result = scan_lake(zone_dir, formula, symbols=symbols, params=params, thresholds=th,
                       asof=asof, names=names, keep_matrix=True,
                       snapshot_columns=snapshot_columns, **kwargs)
    store.put(key, result)
    return ScanOutcome(result=result, key=key, cached=False, asof=result.asof,
                       elapsed_ms=(perf_counter() - started) * 1000,
                       note=('没有可继承的旧结果 ⇒ 全量扫描' if incremental else ''))
