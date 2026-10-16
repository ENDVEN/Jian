# ui/widgets/breadth_relation_flow.py
"""M3「与指数的关系」视图流程（★1.77 从 `breadth_flow` 拆出 · 拆件候选①）。

三视图（多行小图 / 事件对齐 / 关系卡）的切换（`current_view` / `on_view_changed` / `_refresh_views`）、
关系报告唯一出口（`relation_report`：前向收益 / 事件对齐 / 领先滞后 / Rank IC / 置换检验 p）、
指数收盘序列（`_index_close`）与**导出 PNG / CSV**（落盘在本件；按钮在 `relation_card`）。

⚠ **只搬代码、不改行为**：仍通过 `self` 访问 `BreadthFlow` 其余部分（MRO 不变）。
"""

from __future__ import annotations

import os
import datetime as _dt
import pandas as pd
from PyQt6.QtWidgets import QFileDialog
from ui.widgets.breadth_layout import VIEW_CARD, VIEW_EVENT, VIEW_INDEX, VIEW_ROWS
from core.relation_stats import MODE_UNKNOWN, conditional_forward_returns, event_study, lead_lag_corr, permutation_p, rank_ic_of
from ui.widgets.relation_card import WINDOWS as RELATION_WINDOWS

class BreadthRelationFlowMixin:
    """关系视图流程（★1.77 拆件；方法通过 `self` 与 `BreadthFlow` 协作）。"""

    # ==========================================
    # ★1.75 / §7-B16 期 3：三视图（多行小图 / 事件对齐 / 关系卡）+ "与指数的关系"报告
    #   用户 2026-10-15 确认：**L1 分段控件切三视图（不新开页面）** · 色带做副图叠加 ·
    #   关系卡**要导出 PNG/CSV**。三视图共用同一份结果 ⇒ 切换/刷新全是**纯计算**，**不重扫**。
    # ==========================================
    def current_view(self, p=None) -> str:
        """当前视图 key —— **状态只在分段控件一处**（`SegmentedControl.current_key()`，
        §7-B6-D-6：禁止从控件外观反推业务状态）。"""
        p = p or self.page
        seg = getattr(p, 'seg_view', None)
        key = str(seg.current_key() if seg is not None else VIEW_ROWS)
        return key if key in VIEW_INDEX else VIEW_ROWS

    def _index_close(self, p=None):
        """副图那个指数的收盘序列（index = 交易日）—— 没有就返回 None（报告如实说"缺指数"）。"""
        p = p or self.page
        df = getattr(p, '_index_df', None)
        if df is None or getattr(df, 'empty', True):
            return None
        if 'date' not in getattr(df, 'columns', []) or 'close' not in df.columns:
            return None
        data = df[['date', 'close']].copy()
        data['date'] = pd.to_datetime(data['date'], errors='coerce')
        data['close'] = pd.to_numeric(data['close'], errors='coerce')
        data = data.dropna().drop_duplicates(subset='date', keep='last').sort_values('date')
        return None if data.empty else data.set_index('date')['close']

    def relation_report(self, p=None) -> dict:
        """把"与指数的关系"算成一份**可渲染 · 可导出**的报告（纯计算，**零重扫**）。

        `{'items': [...], 'index_label', 'range_label', 'windows', 'missing'}`；每项含
        `fwd`（条件 vs 基线，逐窗口）· `event`（事件对齐原始 dict，含两个 n）· `leadlag`（逐 lag 相关）
        · `lead_peak`（峰值 (lag, r)）· `ic`（逐窗口 Rank IC）· `perm`（置换检验）· `verdict_text`
        （三道闸结论，供关系卡"结论"列直接引用 —— 不自造措辞）。
        """
        p = p or self.page
        out = {'items': [], 'index_label': '', 'range_label': '', 'missing': '', 'note': ''}
        idx = self._index_close(p)
        if idx is None:
            out['missing'] = ('没有指数数据 ⇒ 算不了关系：请在「🌐 统计范围」里选一个指数，'
                             '并确保副图已取到数据（缺数据时会自动补拉一次）。')
            return out
        out['index_label'] = str(p._display_pane.cb_overlay_code.currentText() or '').split(' ')[0]
        out['range_label'] = str(p.cb_range.currentText() or '')
        # ⚠ 不直接抓 `_RANGE_OFFSET`（那个常量随**多方案**块搬去了 `breadth_plan_flow`）：
        #   走 mixin 链上的 `_range_offset(p)` —— 同一套口径、且**只存一处**（§11.5-112）。
        offsets = self._range_offset(p)
        outcome = p._outcome
        if outcome is None:
            out['missing'] = '还没有扫描结果 —— 先点「▶ 开始扫描」。'
            return out
        verdicts = self.gate_verdicts(p)
        labels = {}
        for it in self.active_items(p):
            key = str(it.get('key') or '')
            full = self.item_frame(p, it, sliced=False)       # ★1.76 期 4：按项取它自己那个方案
            if full is None or getattr(full, 'empty', True):
                continue
            frame = full if offsets is None else full[full.index >= full.index[-1] - offsets]
            if frame.empty:
                frame = full
            hits, ratio = frame.get('hits'), frame.get('ratio')
            if hits is None or ratio is None:
                continue
            ev = event_study(hits, idx, window=20)
            ll = lead_lag_corr(ratio, idx, lags=range(-10, 11))
            _valid = {k: abs(v) for k, v in ll.items() if v == v}
            peak = (max(_valid, key=_valid.get), _valid[max(_valid, key=_valid.get)]
                    if _valid else (None, None))
            dec = verdicts.get(key) or {}
            labels[key] = str(it.get('label') or key)
            out['items'].append({
                'key': key, 'label': labels[key],
                'color': str(it.get('color') or '#1E88E5'),
                'ratio_pct': float(frame['hits'].gt(0).mean() * 100.0),
                'fwd': conditional_forward_returns(hits, idx, RELATION_WINDOWS),
                'event': ev,
                'leadlag': ll,
                'lead_peak': [peak[0], (ll.get(peak[0]) if peak[0] is not None else None)],
                'ic': {str(w): rank_ic_of(ratio, idx, window=w) for w in RELATION_WINDOWS},
                'perm': dict(permutation_p(hits, idx, window=20, draws=1000),
                             n=int(ev.get('n_hit_days') or 0)),
                'verdict_text': str(dec.get('reason') or ''),
                # ★1.75 期 3：闸结论一并带上 —— 事件对齐图**据此跳过**不适用项（用户认可的口径：
                #   "被闸拦住的项在事件图里显示『已跳过 + 为什么』"，而不是硬画一条读不出来的线）
                'mode': str(dec.get('mode') or MODE_UNKNOWN),
                'event_ok': bool(dec.get('event_ok', False)),
                'n_hit_days': int(ev.get('n_hit_days') or 0),
                'n_independent': int(ev.get('n_independent') or 0),
            })
        if not out['items']:
            out['missing'] = '上屏的统计项都没有可用帧 —— 先扫描一次。'
        return out

    def _refresh_views(self, p=None, *, notify: bool = False) -> None:
        """按**当前视图**刷新（切换视图、扫描回包、换区间、增删统计项都走这里）。

        ⚠ 只在"需要它的视图"上做重活：多行小图由 `refresh()` 画（主路径），
          事件对齐 / 关系卡才去算报告（含 1000 次置换）—— 不让人白白等。
        """
        p = p or self.page
        key = self.current_view(p)
        stack = getattr(p, 'view_stack', None)
        if stack is not None:
            stack.setCurrentIndex(VIEW_INDEX.get(key, 0))
        if key == VIEW_ROWS:
            return
        report = self.relation_report(p)
        if report.get('missing'):
            p.event_chart.render([])
            p.event_chart.lbl_note.setText(str(report['missing']))
            p.relation_card.set_report(None)
            if notify:
                p.lbl_receipt.setText(str(report['missing']))
            return
        # ⚠ 事件图**只画闸允许的条件**（用户认可的口径）：被闸拦下的项在这里"已跳过 + 为什么"，
        #   而不是硬画一条"命中日连成片、读不出东西"的线（那等于用图骗人）。
        _ok = [it for it in report['items'] if it.get('event_ok')]
        _skip = [it for it in report['items'] if not it.get('event_ok')]
        p.event_chart.render([(it['label'], it['color'], it.get('event') or {}) for it in _ok])
        if _skip:
            _why = '；'.join(f"{it['label']}（{it.get('verdict_text') or '太频繁'}）"
                            for it in _skip[:3])
            p.event_chart.lbl_note.setText(
                p.event_chart.lbl_note.text()
                + f'　·　⛔ 已跳过 {len(_skip)} 项（事件图不适用，请看「🧮 关系卡」的占比分档 / IC）：'
                + _why)
        p.relation_card.set_report(report)

    def on_view_changed(self, key: str) -> None:
        """L1 分段控件切换视图 —— **纯渲染**（不进线程、不读盘、**不重扫**）。"""
        p = self.page
        self._refresh_views(p)
        names = {VIEW_ROWS: '多行小图', VIEW_EVENT: '事件对齐', VIEW_CARD: '关系卡'}
        self._refresh_views(p, notify=True)
        p.lbl_receipt.setText(f'已切到「{names.get(str(key), key)}」——'
                              '同一份扫描结果换一种看法，**没有重扫**。')
        p.save_breadth_ui()

    # ---------- 导出（用户 2026-10-15 拍板：要）----------
    def on_export_png(self) -> None:
        """导出关系卡（PNG）—— 卡长什么样就存什么样（`grab()`，不重画、不重算）。"""
        p = self.page
        default = os.path.join(os.path.expanduser('~'),
                               f'jian-m3-relation-{_dt.date.today().isoformat()}.png')
        path, _sel = QFileDialog.getSaveFileName(p, '导出关系卡（PNG）', default,
                                                 'PNG 图片 (*.png)')
        if not path:
            p.lbl_receipt.setText('已取消导出（没有写任何文件）。')
            return
        ok = bool(p.relation_card.grab().save(path))
        p.lbl_receipt.setText(f'已导出关系卡：{path}' if ok
                              else f'导出失败：{path}（目录不可写？）—— 没有静默成功。')

    def on_export_csv(self) -> None:
        """导出关系数字（CSV，utf-8-sig ⇒ Excel 直接开不乱码）。**导出的就是卡上那些数**。"""
        p = self.page
        rows = p.relation_card.rows_for_csv()
        if not rows:
            p.lbl_receipt.setText('没有可导出的关系数字 —— 先扫描一次，并切到「🧮 关系卡」视图。')
            return
        default = os.path.join(os.path.expanduser('~'),
                               f'jian-m3-relation-{_dt.date.today().isoformat()}.csv')
        path, _sel = QFileDialog.getSaveFileName(p, '导出关系数字（CSV）', default,
                                                 'CSV 表格 (*.csv)')
        if not path:
            p.lbl_receipt.setText('已取消导出（没有写任何文件）。')
            return
        try:
            pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8-sig')
        except OSError as e:                       # noqa: PERF203 —— 磁盘/权限问题如实说
            p.lbl_receipt.setText(f'导出失败：{path}（{e}）—— 没有静默成功。')
            return
        p.lbl_receipt.setText(f'已导出 {len(rows)} 行关系数字：{path}'
                              '（口径：前向收益与 IC 的单位见表头；样本不足的行标了"样本足够=False"）')

