# ui/widgets/scan_enrich_flow.py
"""扫描后的**行业 / 估值补全调度**（★2.04 / P2 拆件）。

从 `ui/widgets/scan_flow.py` 抽出：按轮补全、行业映射分批抓取与断点、补全回执。
宿主 = `ScanView`（Mixin 依赖 `self.page` / `self.refresh()`），不碰扫描主链。
"""
from __future__ import annotations

import logging

import pandas as pd

from core.preferences import preferences
from data import em_market, em_throttle, net_env
from data.industry_store import get_industry_store
from ui import settings_registry as reg
from ui.widgets.scan_enrich import EnrichScheduler
from ui.workers import IndustryMapWorker

__all__ = ["ScanEnrichMixin", "INDUSTRY_PROGRESS_KEY"]

INDUSTRY_PROGRESS_KEY = 'industry_fetch'   # preferences 里的断点：{next_page, pages_total}
_setting = reg.get_setting

logger = logging.getLogger(__name__)


class ScanEnrichMixin:
    """★v6.74 扫描后**按轮补全**（行业 + 估值）+ ★P6 细分行业分批抓取。"""

    _enrich_scheduler = None

    def _start_enrich(self, outcome) -> bool:
        """起补全调度器；**返回是否接管**（`False` ⇒ 调用方走旧路径兜底）。"""
        p = self.page
        if not bool(_setting('enrich.enabled', True)):
            return False
        symbols = [str(s).strip() for s in (getattr(p, '_symbols', None) or []) if str(s).strip()]
        if not symbols:
            return False
        old = self._enrich_scheduler
        if old is not None and old.isRunning():
            old.cancel()                                    # 新扫描 ⇒ 停掉上一轮（回包靠身份校验丢弃）
        sched = EnrichScheduler(symbols,
                                per_round=int(_setting('enrich.requests', 3)),
                                gap=int(_setting('enrich.gap', 30)), parent=p)
        sched.progress.connect(
            lambda done, total, nxt, s=sched: self._on_enrich_progress(s, done, total, nxt))
        sched.rows.connect(lambda got, s=sched: self._on_enrich_rows(s, got))
        sched.finished.connect(lambda why, s=sched: self._on_enrich_finished(s, why))
        self._enrich_scheduler = sched
        sched.start()
        return True

    def _on_enrich_progress(self, sched, done: int, total: int, next_in: int) -> None:
        if sched is not self._enrich_scheduler:
            return                                          # 迟到的旧调度器 ⇒ 丢弃
        self._note_enrich(sched.progress_text(next_in))

    def _on_enrich_rows(self, sched, got) -> None:
        """一轮回来 ⇒ **并进持久缓存 + 更新表内两列**（渐进刷新）。"""
        p = self.page
        if sched is not self._enrich_scheduler or not got:
            return
        ind = {sym: str((rec or {}).get('industry') or '').strip()
               for sym, rec in got.items()}
        ind = {k: v for k, v in ind.items()
               if len(k) == 6 and k.isdigit() and v and v != '-'}
        if ind:
            try:
                get_industry_store().merge(ind)             # 与分页通道**同一套校验口径**
            except Exception as e:                          # noqa: BLE001
                logger.warning('补全写行业缓存失败（忽略）: %s', e)
        p._valuation = dict(p._valuation or {}, **{sym: dict(rec or {}) for sym, rec in got.items()})
        if p._valuation_date is None:                       # 口径与旧路径一致：只在最新交易日填
            # ★2.02 / TEST-HARNESS：**迟到的补全回包可能在新扫描之后到** —— 那时
            #   `_drop_stale_result` 已把 `_outcome` 置 None。旧写法直接 `.result` 会
            #   AttributeError（冒烟 guard 实测抓到），这里逐层取默认值：拿不到日期就
            #   不填（诚实留空），绝不为了不报错去猜。
            _outcome = getattr(p, '_outcome', None)
            dates = getattr(getattr(_outcome, 'result', None), 'dates', None)
            p._valuation_date = (pd.Timestamp(dates[-1]).normalize()
                                 if dates is not None and len(dates) else None)
        self.refresh()                                      # 重画（不重测列宽）

    def _on_enrich_finished(self, sched, why: str) -> None:
        if sched is not self._enrich_scheduler:
            return
        self._note_enrich(f'行业/估值补全结束：{why}')

    def _note_enrich(self, text: str) -> None:
        """把补全进度写进回执（**替换上一句补全语**，既不覆盖扫描结论、也不会越长越乱）。"""
        p = self.page
        base = p.lbl_receipt.text() or ''
        head = base.split('行业/估值补全')[0].rstrip(' ·')
        p.lbl_receipt.setText(f'{head} · {text}'.strip(' ·'))

    # ==========================================
    # ★P6 细分行业（本地缓存 industry_map.json；为空时后台抓一次，扫描只读缓存）
    # ==========================================
    def _industry_progress(self) -> dict:
        """行业映射的**断点**（存 `preferences`，跨重启有效）：`{next_page, pages_total}`。"""
        prog = preferences.get(INDUSTRY_PROGRESS_KEY)
        return prog if isinstance(prog, dict) else {}

    def _set_industry_progress(self, next_page: int, pages_total: int) -> None:
        """记下断点（上层只经本函数读写，别处禁止自己拼键）。"""
        preferences.set(INDUSTRY_PROGRESS_KEY,
                        {"next_page": int(next_page), "pages_total": int(pages_total)})

    def _note_industry_failure(self, err: str = '') -> None:
        """行业映射拿不到 ⇒ 回执**追加**（不覆盖）原因与出路 —— 唯一出处（两处调用点都用它）。

        ★v6.69：`err` 带上退避原因（例："东财限流冷却中（约 9 分钟后再试）"）—— 用户据此知道
          **该等，而不是反复点**（反复点 = 继续压住额度，越点越死，§11.5-100）。
        v6.68 的初衷（拿到空表**绝不静默**，否则界面只剩一列 '—'、用户只能怀疑自己）保持不变。
        """
        p = self.page
        _note = (" · ⚠ 行业映射未取到（东财接口暂时不可用）—— 该列暂显 '—'；"
                 + (f"{err}；" if err else "")
                 + "再点一次「▶ 开始扫描」会重试（从断点续抓）")
        if '行业映射未取到' not in (p.lbl_receipt.text() or ''):
            p.lbl_receipt.setText((p.lbl_receipt.text() or '') + _note)
        _tip = ('行业 = 细分板块，取自东财全市场列表的「所属行业」字段（分页抓取：单页 100 行、'
                '全市场约 56 页 ⇒ 每批补几页，抓满即长期缓存）。\n'
                '抓不到就诚实留 \'—\'，**绝不拿别的口径瞎猜板块**。\n'
                '常见原因：① 东财对**匿名高频**请求有"频次窗"（连打几十次会整段拒绝、约 30 分钟'
                '自恢复）—— 现已改成"分批 + 失败冷却"，**过一会儿再点一次扫描**即可从断点继续，'
                '不必连点（连点只会把额度继续压住）；② **本机代理 / IPv6** 也会让请求"根本没出去"'
                '（表现为 ProxyError 或不回包的断连）—— 这一块已由网络策略兜住：\n'
                f'当前网络策略：{net_env.describe()}')
        p.lbl_receipt.setToolTip(((p.lbl_receipt.toolTip() or '') + '\n' + _tip).strip())

    def _maybe_fetch_industry(self) -> None:
        """行业映射**分批**补齐（每批 `em_market.pages_per_scan()` 页；补齐后长期缓存、不再联网）。

        ★v6.68 改造（用户实测"行业一直是空的" + 探针结论 · §11.5-99）：
          · 旧写法 = "板块清单 + 逐板块成分" ≈ **80+ 连击** ⇒ 正踩东财**匿名高频风控**（连打几十次
            后整段拒绝、静置约 30 分钟自恢复）⇒ 几乎必然失败；
          · 新写法 = 从**全市场列表**分页取 `f100`（与"快照 / 估值"同源同端点），**每批只抓几页** +
            页间隔，分几次扫描摊平；**进度存 preferences** ⇒ 下次扫描**从断点续抓**；
          · 补齐（`next_page > pages_total`）⇒ 以后不再联网（长期缓存）。
        """
        p = self.page
        if p._industry_worker is not None and p._industry_worker.isRunning():
            return
        prog = self._industry_progress()
        next_page = int(prog.get('next_page') or 1)
        pages_total = int(prog.get('pages_total') or 0)
        if pages_total and next_page > pages_total:
            return                                   # 已补齐 ⇒ 只读缓存（不联网）
        # ★v6.69：冷却中（东财限流退避）⇒ **一个请求都不打**，并把"还要等多久"写进回执。
        #   注意顺序：这一关放在"已补齐 ⇒ 不联网"**之后** —— 缓存补齐了就该安静，不该报冷却。
        #   旧版每次扫描都从第 1 页重打 ⇒ 用户越点越死（正是 19:37 那条"连第 1 页都拒"）。
        _cool = em_throttle.describe()
        if _cool:
            self._note_industry_failure(_cool)
            return
        job = p._industry_guard.next()
        # ★v6.73 S2-1：页数按**当前档位**取（登录档可多抓）—— 判据/额度都在 em_market 一处
        # ★2.04：兼容旧的打桩点 `ui.widgets.scan_flow.IndustryMapWorker`（测试/旧代码在模块上替换）；
        #   惰性取，避免 import 环（scan_flow 在模块加载时 import 本 mixin）。
        from ui.widgets import scan_flow as _scan_flow_mod
        _worker_cls = getattr(_scan_flow_mod, 'IndustryMapWorker', IndustryMapWorker)
        p._industry_worker = _worker_cls(next_page, em_market.pages_per_scan(), parent=p)
        p._industry_worker.finished.connect(
            lambda data, token=job: self._on_industry_ready(data, token))
        p._industry_worker.start()

    def _on_industry_ready(self, data, token: int) -> None:
        """行业回包：过守卫 → **并入**缓存 + 记断点 + 重画；**拿不到就出声**（绝不静默）。

        ★v6.68：旧版拿到空就**什么都不做**（界面只剩一列 '—'，用户只能怀疑自己）⇒ 现在失败与出路
          都写在回执上；分批抓取则"并入 + 记断点"（下一批从断点继续，不覆盖已抓到的好数据）。
        """
        p = self.page
        if not p._industry_guard.accept(token):
            return
        payload = data if isinstance(data, dict) else {}
        got = payload.get('map') or {}
        pages_done = int(payload.get('pages_done') or 0)
        if got or pages_done:
            store = get_industry_store()
            store.merge(got)                         # ★分批 ⇒ **并入**（不是整体替换）
            prog = self._industry_progress()
            nxt = int(prog.get('next_page') or 1) + pages_done
            total = int(payload.get('total_pages') or prog.get('pages_total') or 0)
            self._set_industry_progress(nxt, total)
            self.refresh()
            if total and nxt > total:                # 补齐 ⇒ 说一声（用户知道以后不用再等）
                if '行业映射已补齐' not in (p.lbl_receipt.text() or ''):
                    p.lbl_receipt.setText(
                        (p.lbl_receipt.text() or '')
                        + f" · ✅ 行业映射已补齐（{store.coverage()} 只）")
            return
        # 失败（None / 空）：**可见回执 + 出路**（下次扫描会从断点继续 —— 缓存命中也算）
        # ★v6.69：把退避原因一起说出来（"东财限流冷却中（约 N 分钟后再试）"）⇒ 用户该等、不必连点
        self._note_industry_failure(str(payload.get('error') or ''))
