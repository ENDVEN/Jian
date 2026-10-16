# ui/widgets/breadth_plan_flow.py
"""M3「多方案」流程（★1.77 从 `breadth_flow` 拆出 · RULES §4 拆件候选①）。

一项统计项可来自**另一个已存方案**（各自的条件 / 参数 / 粗筛阈值）：本件管
"**项 → 它那个方案的结果**"的路由（`plan_field` / `plan_digest` / `item_uid` / `item_frame`）、
`ScanStore` 会话缓存的取用、**方案队列**逐个补扫（`scan_plan_queue` / `_run_queued_plan`），
以及「＋ 从其他方案添加…」的落地（`on_import_item` / `_add_imported_item`）。

⚠ **只搬代码、不改行为**：这些方法仍通过 `self` 访问 `BreadthFlow` 其余部分（MRO 不变），
   页面与冒烟的调用点一字未改。`_RANGE_OFFSET`（区间档 → Timedelta）随本件搬来。
"""

from __future__ import annotations

import pandas as pd
from PyQt6.QtWidgets import QInputDialog, QMessageBox
from core.cross_section import ScanThresholds
from core.utils import parse_params_text
from data.scan_store import kline_zone_dir
from ui.widgets.breadth_rows import ROW_COLORS
from ui.workers import CrossSectionWorker

_RANGE_OFFSET = {
    '3m': pd.DateOffset(months=3), '6m': pd.DateOffset(months=6),
    '1y': pd.DateOffset(months=12), '3y': pd.DateOffset(years=3),
    '5y': pd.DateOffset(years=5),
}

class BreadthPlanFlowMixin:
    """多方案流程（★1.77 拆件；方法通过 `self` 与 `BreadthFlow` 协作）。"""

    # ==========================================
    # ★1.76 / §7-B16 期 4：**多方案**（统计项可来自不同方案）
    #   【口径】项不带 `plan` ⇒ **本页方案**（老行为零变化）；带了 ⇒ 去它自己那个方案的结果里取数。
    #   【范围与复权 —— 已知偏差（记方案书 §3 期 4）】借别的方案时取它的**条件 / 参数 / 粗筛阈值**，
    #     而**统计范围与复权仍用本页当前设置**：范围解析依赖本页 🌐 卡的一整串状态，
    #     复制一份解析器 = 第二套真源（§11.5-112）⇒ 明确"范围跟本页"，并在回执里说出来。
    #   【绝不静默】某个方案还没扫过 ⇒ 该项**不画、徽标「未扫描」**，回执告诉用户点扫描会一起补。
    # ==========================================
    @staticmethod
    def plan_field(plan, key: str, default=None):
        """取方案字段 —— **先顶层、再 `config`**。

        ⚠ 用户 2026-10-16 实测报的 bug（症状 B「从其他方案添加」永远说加不了）根因就在这里：
          真实的筛选方案记录是 `{'config': {'formula','params','thresholds','scope','adjust'},
          'name','id','created_at','updated_at'}` —— **公式在 `config['formula']`**，
          而本模块第一版读的是 `plan['formula']`（永远空）⇒ 解析出 0 个可判定变量 ⇒ "加不了"。
          ⇒ 一个访问器管住"存哪都读得到"（**一处修好**，调用方不再各自记字段位置）。
        """
        if not isinstance(plan, dict):
            return default
        if plan.get(key) not in (None, ''):
            return plan.get(key)
        cfg = plan.get('config')
        if isinstance(cfg, dict) and cfg.get(key) not in (None, ''):
            return cfg.get(key)
        return default

    @staticmethod
    def _as_thresholds(raw):
        """方案里那坨阈值 → `ScanThresholds`（**用引擎自己的 `from_dict`**）。

        ⚠ 用户 2026-10-16 实测报的第二个 bug 就在这里：方案记录里 `thresholds` 是**普通 dict**
          （`to_dict()` 落盘的），而 `thresholds_fingerprint` 只吃 `ScanThresholds` 或 `None`
          ⇒ 直接喂 dict = `AttributeError: 'dict' object has no attribute 'to_dict'`（控制台 traceback）。
        ⚠ 顺带修掉一个**更坏**的：我第一版手搓了 6 个字段的白名单 ⇒ `min_turnover` /
          `min_float_mktcap` / `max_float_mktcap` / `min_change_pct` / `max_change_pct`
          **被悄悄丢掉** ⇒ 借来的方案会**用本页的换手率/市值/涨跌幅阈值**去扫（静默换口径 ✗）。
          ⇒ 一律走 `ScanThresholds.from_dict`（**唯一还原口径**，且坏数据逐字段回落默认）。
        """
        from core.cross_section import ScanThresholds

        if raw is None or raw == '':
            return None
        if isinstance(raw, ScanThresholds):
            return raw
        if isinstance(raw, dict):
            return ScanThresholds.from_dict(raw)
        return None

    @classmethod
    def plan_digest(cls, plan: dict = None) -> str:
        """方案指纹 = **条件 + 参数 + 粗筛阈值**（决定"要不要单独扫一次"）；空方案（本页）⇒ `'page'`。

        ⚠ **本函数绝不许抛**：它用在面板/添加/排队的半路，抛出去就是"点了没反应"（用户实测）。
          真取不到指纹时回落到**方案内容自身的摘要**（仍然"不同方案不同键" ⇒ 不会把两个方案
          混成一份数据 —— 那比崩溃坏得多）。
        """
        if not plan:
            return 'page'
        import hashlib as _hl

        try:
            from data.scan_store import formula_fingerprint, thresholds_fingerprint

            _f = formula_fingerprint(str(cls.plan_field(plan, 'formula', '') or ''),
                                     cls.plan_field(plan, 'params') or None)
            _t = thresholds_fingerprint(cls._as_thresholds(cls.plan_field(plan, 'thresholds')))
            return _hl.sha1(f'{_f}|{_t}'.encode('utf-8')).hexdigest()[:12]
        except Exception:                     # noqa: BLE001 —— 指纹只是分组键，绝不拖垮交互
            return 'raw' + _hl.sha1(repr(plan).encode('utf-8')).hexdigest()[:12]

    def saved_plans(self, p=None) -> list[dict]:
        """可"借"的**已存筛选方案**（M2/M3 共用池，唯一真源 —— 页面不许另存一份）。"""
        p = p or self.page
        try:
            return list(p._strategy.store.list_strategies() or [])
        except Exception:                     # noqa: BLE001 —— 方案库不可用不该拖垮页面
            return []

    def item_uid(self, p, item) -> str:
        """项的**身份** = `方案指纹 + 变量名`。

        【为什么必须有它】用户 2026-10-16 实测：四个方案里的判定变量**同名**（都叫 `COND`）——
          凡是"按变量名建字典"的地方（帧表 / 闸判决表）都会**互相覆盖** ⇒ 四条线画成同一条
          （读数都是 282 只 / 34.1%）。⇒ 一切"按项索引"的容器都必须用本函数。
          （§11.5-134 同族：数字必须能追到它属于谁。）
        """
        return f'{self.plan_digest(self.plan_for_item(p, item))}|{str((item or {}).get("key") or "")}'

    def plan_for_item(self, p, item) -> dict:
        """项的来源方案（无 ⇒ `{}` = 本页方案）。"""
        plan = (item or {}).get('plan')
        return dict(plan) if isinstance(plan, dict) else {}

    def outcome_for(self, p, item):
        """项该去哪个结果取数：带 `plan` ⇒ 查 `p._outcomes[digest]`；**没有就 `None`（不回落）**。"""
        if not self.plan_for_item(p, item):
            return p._outcome
        return (getattr(p, '_outcomes', None) or {}).get(
            self.plan_digest(self.plan_for_item(p, item)))

    @staticmethod
    def _range_offset(p=None):
        """当前区间档对应的 `Timedelta`（`None` = 全历史）—— 切区间只切片、不重算（D3）。"""
        return _RANGE_OFFSET.get(p._range_key) if p is not None else None

    def item_frame(self, p, item, *, sliced: bool = True):
        """该项的广度帧（**按它自己的方案**取；`sliced=False` = 全历史）。

        ⚠ 取不到 ⇒ `None`/空 —— **绝不回落成"当前页那套"**（§11.5-134 的同族纪律：
          静默拿别人的数据冒充自己，比缺数据坏得多）。
        """
        outcome = self.outcome_for(p, item)
        if outcome is None:
            return None
        full = outcome.breadth_frame(signal=(item or {}).get('key'))
        if full is None or getattr(full, 'empty', True):
            return None
        if not sliced:
            return full
        offset = self._range_offset(p)
        if offset is None:
            return full
        frame = full[full.index >= full.index[-1] - offset]
        return frame if not frame.empty else full

    def scan_plan_queue(self, p=None) -> list[dict]:
        """本次「▶ 开始扫描」要跑的**方案队列**（第一项恒为**本页方案**）。

        每项 = `{'digest','plan','label','signal_names'}`；`signal_names` = **属于该方案**的上屏判定变量。
        只有本页方案时队列长度 = 1 ⇒ **老路径逐字不变**（先跑本页，再补借来的方案）。
        """
        p = p or self.page
        items = self.active_items(p)
        # ⚠ 用户 2026-10-16 实测报的 bug（症状 A）：**换了条件之后旧统计项还留在屏上**时，
        #   把它们的名字当 `signal_names` 交给内核 ⇒ 内核**严格报错**（"筛选条件里没有变量 X"）
        #   ⇒ **整次扫描失败**（不是"少一行"，是全军覆没）。⇒ 这里**先按当前条件过滤**：
        #   只把当前条件里确实存在的判定变量交下去，不在的**如实记下来**交给回执说清。
        _declared = set(self.formula_signals(p))
        _page_keys = [str(it.get('key') or '') for it in items
                      if not self.plan_for_item(p, it)]
        _usable = [k for k in _page_keys if k in _declared] if _declared else _page_keys
        _skipped = [k for k in _page_keys if k not in _usable]
        queue = [{'digest': 'page', 'plan': {}, 'label': '本页方案',
                  'signal_names': _usable, 'skipped': _skipped}]
        for it in items:
            plan = self.plan_for_item(p, it)
            if not plan:
                continue
            dg = self.plan_digest(plan)
            hit = next((q for q in queue if q['digest'] == dg), None)
            if hit is None:
                hit = {'digest': dg, 'plan': plan,
                       'label': str(plan.get('name') or '其他方案'), 'signal_names': []}
                queue.append(hit)
            hit['signal_names'].append(str(it.get('key') or ''))
        return queue

    def _item_computed(self, p, item) -> bool:
        """该项**在它自己那个方案的结果里**算过没有（没有 ⇒ 回执要说"点扫描把它一起算进来"）。"""
        oc = self.outcome_for(p, item)
        if oc is None:
            return False
        return str((item or {}).get('key') or '') in {
            str(s) for s in (oc.result.signals() or [])}

    def _queue_step(self, p=None) -> dict:
        """队列里**当前**那一步（越界 ⇒ 给一个安全的"本页"步，绝不抛）。"""
        p = p or self.page
        queue = list(getattr(p, '_scan_queue', None)
                     or [{'digest': 'page', 'plan': {}, 'label': '本页方案',
                          'signal_names': []}])
        idx = int(getattr(p, '_scan_index', 0))
        return queue[idx] if 0 <= idx < len(queue) else queue[-1]

    def _has_more_plans(self, p) -> bool:
        return int(getattr(p, '_scan_index', 0)) + 1 < len(
            getattr(p, '_scan_queue', None) or [])

    @staticmethod
    def _plan_scan_kwargs(plan: dict, fallback_params, fallback_thresholds) -> tuple:
        """借来的方案给什么用：**它的条件 / 参数 / 粗筛阈值**；缺哪样沿用本页那一样。"""
        from core.cross_section import ScanThresholds

        params = fallback_params
        # ⚠ 用**本 mixin**的名字（搬过来之后旧模块名 `BreadthFlow` 已不在本名字空间里）
        _ptext = BreadthPlanFlowMixin.plan_field(plan, 'params')
        if _ptext:
            params = parse_params_text(str(_ptext))
        # ⚠ 一律走 `_as_thresholds`（= 引擎的 `from_dict`）—— 手搓白名单会**悄悄丢字段**：
        #   换手率 / 流通市值 / 涨跌幅 三项曾被我漏掉 ⇒ 借来的方案会拿本页阈值去扫（静默换口径）。
        th = BreadthPlanFlowMixin._as_thresholds(BreadthPlanFlowMixin.plan_field(plan, 'thresholds'))
        if th is None:
            th = fallback_thresholds
        return params, th

    def _run_queued_plan(self, busy_text: str = '') -> bool:
        """起线程跑队列里的**当前**方案（跑完由 `_on_finished` 续下一个；**一次只起一个线程**）。"""
        p = self.page
        step = self._queue_step(p)
        plan = step.get('plan') or {}
        formula = str(self.plan_field(plan, 'formula', '')
                      or p._formula_pane.txt_formula.toPlainText()).strip()
        if not formula:
            p.lbl_receipt.setText('（借来的方案）筛选条件是空的 ⇒ 跳过它。')
            return False
        params, th = self._plan_scan_kwargs(plan, getattr(self, '_scan_params', {}),
                                           p._thresholds)
        job = p._guard.next()                             # 取号：迟到的旧回包会被丢弃（§9-O5）
        p._worker = CrossSectionWorker(
            job, kline_zone_dir('kline_daily'), formula, symbols=list(p._symbols),
            params=params, thresholds=th, asof=None, names=dict(p._names),
            force=bool(getattr(self, '_scan_force', False)),
            incremental=bool(getattr(self, '_scan_incremental', False)), store=p._store,
            # ★1.73 期 1：把**属于这个方案**的判定变量一起算（一次读盘全部拿到）
            signal_names=list(step.get('signal_names') or []))
        p._worker.progress.connect(self._on_progress)
        p._worker.finished.connect(self._on_finished)
        p._worker.failed.connect(self._on_failed)
        p._worker.start()
        _idx = int(getattr(p, '_scan_index', 0))
        _n = len(getattr(p, '_scan_queue', None) or [])
        if _idx > 0:
            p.lbl_receipt.setText(f'正在补第 {_idx + 1}/{_n} 个方案的扫描'
                                  f'（{step.get("label")}）…')
        elif busy_text:
            p.lbl_receipt.setText(busy_text)
        return True

    # ---------- 多方案：UI 入口（从已存方案借一个判定变量）----------
    def on_import_item(self) -> None:
        """「＋ 从其他方案添加」——**任何失败都要看得见**（绝不"点了没反应"，§10-4）。

        ⚠ 用户 2026-10-16 实测："换了不同名的变量 ⇒ 直接没有反应" —— 根因是槽函数里抛异常
          （见 `plan_digest` 那条 dict/ScanThresholds 的类型错），异常一抛，用户什么也看不到。
          ⇒ 入口包一层：出错 ⇒ **弹窗 + 回执**都写清（用户知道发生了什么、可以重试）。
        """
        try:
            self._on_import_item_impl()
        except Exception as e:                # noqa: BLE001 —— 方案库/解析/取字段任一步都可能出错
            p = self.page
            p.lbl_receipt.setText(f'从其他方案添加失败：{type(e).__name__}: {e}')
            QMessageBox.warning(
                p, '从其他方案添加失败',
                f'{type(e).__name__}: {e}\n\n'
                '（这一步只**读**方案库、不改你的配置 ⇒ 可以重试或换一个方案。）')

    def _on_import_item_impl(self) -> None:
        """「＋ 从其他方案添加」正文：选方案 → 选它的判定变量 → 上屏（**没算过 ⇒ 回执说要扫描**）。

        ⚠ **只读**方案池、**不改**本页配置（不是"载入方案"：载入会把本页条件换掉）。
        """
        p = self.page
        plans = self.saved_plans(p)
        if not plans:
            QMessageBox.information(
                p, '从其他方案添加',
                '还没有保存过筛选方案 —— 先在「ƒ 库」浮窗的「📚 本页方案」区把当前配置存一个。')
            return
        names = [str(pl.get('name') or '未命名') for pl in plans]
        name, ok = QInputDialog.getItem(p, '从其他方案添加', '选择方案：', names, 0, False)
        if not ok or not name:
            return
        plan = next((pl for pl in plans if str(pl.get('name') or '未命名') == name), None)
        if plan is None:
            return
        from core.cross_section import signal_names as _sig_names
        try:
            signals = list(_sig_names(str(self.plan_field(plan, 'formula', '') or '')))
        except Exception:                     # noqa: BLE001 —— 方案里的公式解析不了 ⇒ 如实说
            signals = []
        if not signals:
            QMessageBox.information(p, '从其他方案添加',
                                    f'方案「{name}」里没有可当判定变量的输出 ⇒ 加不了。')
            return
        sig, ok2 = QInputDialog.getItem(p, '从其他方案添加', '选它的判定变量：', signals,
                                        len(signals) - 1, False)
        if not ok2 or not sig:
            return
        self._add_imported_item(plan, str(sig))

    def _add_imported_item(self, plan: dict, sig: str) -> None:
        """把"借来的判定变量"落成一个统计项（存**方案快照**：条件/参数/粗筛阈值 ⇒ 可独立成一次扫描）。"""
        p = self.page
        plan = dict(plan or {})
        # ⚠ 一律走访问器（真实记录的公式在 `config['formula']` —— 读错位置就会存出一个**空公式**，
        #   那样"借来的项"这一步扫描会**悄悄用本页公式**算（静默错数据，§11.5-134 同族））
        descriptor = {'plan_id': str(self.plan_field(plan, 'id', '') or ''),
                      'name': str(self.plan_field(plan, 'name', '') or ''),
                      'formula': str(self.plan_field(plan, 'formula', '') or ''),
                      'params': str(self.plan_field(plan, 'params', '') or ''),
                      'thresholds': self.plan_field(plan, 'thresholds') or {}}
        items = [dict(it) for it in ((p._items or []) or self.active_items(p))]
        _dg = self.plan_digest(descriptor)
        if any(str(it.get('key')) == str(sig)
               and self.plan_digest(it.get('plan')) == _dg for it in items):
            p.lbl_receipt.setText(f'「{sig}」已经在屏上了（同一个方案）。')
            return
        items.append({'key': str(sig), 'label': f'{sig}（{descriptor["name"]}）',
                      'color': ROW_COLORS[len(items) % len(ROW_COLORS)], 'visible': True,
                      'focus': False, 'plan': descriptor,
                      'source_label': f'来自方案：{descriptor["name"]}'})
        p._items = items
        self._after_items_changed(
            f'已从方案「{descriptor["name"]}」添加判定变量「{sig}」'
            '（**条件 / 参数 / 粗筛阈值取该方案**；统计范围与复权仍用本页当前设置）')

