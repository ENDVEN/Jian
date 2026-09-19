# ui/widgets/review_flow.py
"""复盘页的**筛选 + 时间导航 + 视图刷新**（1.25 自 `ui/views/review.py` 拆出 · §9-L）。

【职责】回答"现在看哪一段时间、筛哪些单"，并把结果落进页面状态：
  · 月 / 年模态切换（切年视图必须清空回放画布，§9-O8）；
  · 五个筛选下拉的重建与回填（账户 / 策略 / 品种主体 / 方向 / 结果）；
  · 时间导航（◀ ▶ / 下拉跳转 / 「最新」）；
  · `update_review_view()` = 唯一汇总点：过滤 → 更新 `current_view_df` →
    刷新时间选择器 → 触发日历 / 月度图表 / 持仓时长（或年视图面板）渲染。

【设计约定（与 desk_*.py 同源）】**状态全部留在页面** —— `current_review_date`、
  `is_yearly_view`、`current_view_df`、`current_editing_idx` 都是页面属性；
  本模块只读写 `self.page.X`。
"""
from datetime import datetime

import pandas as pd

from config import settings
from core.utils import extract_root_symbol


class ReviewFlow:
    """复盘页筛选与导航（页面持状态，本类承载行为）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 月 / 年模态切换
    # ==========================================
    def toggle_review_mode(self):
        p = self.page
        p.is_yearly_view = not p.is_yearly_view
        if p.is_yearly_view:
            p.btn_mode_toggle.setText("切换月视图 🔍")
            p.btn_mode_toggle.setStyleSheet(f"QPushButton {{ font-size: 14px; font-weight: bold; color: {settings.COLOR_PROFIT_TEXT}; padding: 5px 15px; border: 1px solid #A5D6A7; border-radius: 6px; background: #E8F5E9; margin-right: 15px;}} QPushButton:hover {{ background: #C8E6C9; }}")
            p.review_stack.setCurrentIndex(1)
            # 【v5.12 修正 · §9-O8】年视图不存在"交易回放"，切过去必须清空画布，
            # 否则下次切回月视图会残留上一次的 K 线回放（看起来像"数据没刷新"）。
            p.playback_chart.clear()
        else:
            p.btn_mode_toggle.setText("切换年视图 📅")
            p.btn_mode_toggle.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #FF9800; padding: 5px 15px; border: 1px solid #FFCC80; border-radius: 6px; background: #FFF3E0; margin-right: 15px;} QPushButton:hover { background: #FFE0B2; }")
            p.review_stack.setCurrentIndex(0)

        p.update_review_view()

    # ==========================================
    # 筛选下拉重建
    # ==========================================
    def refresh_review_filters(self):
        """数据变动后重建筛选下拉框。数据为空时重置为默认项，绝不残留旧选项。"""
        p = self.page
        combos = [p.cb_rev_account, p.cb_rev_strategy, p.cb_rev_symbol, p.cb_edit_strategy]
        for cb in combos:
            cb.blockSignals(True)
        try:
            self._populate_review_filter_options()
        finally:
            # 【健壮性】即使中途抛异常也必须恢复信号，否则控件会“假死”
            for cb in combos:
                cb.blockSignals(False)

    def _populate_review_filter_options(self):
        p = self.page
        df = p.main_win.engine.df

        p.cb_rev_account.clear()
        p.cb_rev_account.addItem("全账户", "ALL")
        if not df.empty:
            for acc in df['account'].dropna().unique():
                p.cb_rev_account.addItem(str(acc), str(acc))

        # engine.strategies 已汇总默认策略与历史出现过的策略，数据为空时自动退化为默认项
        p.cb_rev_strategy.clear()
        p.cb_rev_strategy.addItem("全策略", "ALL")
        p.cb_edit_strategy.clear()
        for st in p.main_win.engine.strategies:
            p.cb_rev_strategy.addItem(str(st), str(st))
            p.cb_edit_strategy.addItem(str(st))

        p.cb_rev_symbol.clear()
        p.cb_rev_symbol.addItem("全品种", "ALL")
        if not df.empty:
            roots = {extract_root_symbol(sym) for sym in df['symbol'].dropna().unique()}
            for r in sorted(roots):
                p.cb_rev_symbol.addItem(r, r)

    # ==========================================
    # 时间选择器
    # ==========================================
    def refresh_time_picker(self, is_year=False):
        p = self.page
        p.cb_time_picker.blockSignals(True)
        p.cb_time_picker.clear()
        if p.main_win.engine.df.empty:
            p.cb_time_picker.blockSignals(False)
            return

        dates = pd.to_datetime(p.main_win.engine.df['trade_time'])

        if is_year:
            data_years = set(dates.dt.year.dropna().unique())
            all_years = sorted(list(data_years | {p.current_review_date.year}), reverse=True)
            for y in all_years:
                txt = f"{y}年" if y in data_years else f"{y}年 (无记录)"
                p.cb_time_picker.addItem(txt, datetime(y, 1, 1))
        else:
            data_months = set([d.to_timestamp() for d in dates.dt.to_period('M').dropna().unique()])
            current_m = pd.Timestamp(p.current_review_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
            all_months = sorted(list(data_months | {current_m}), reverse=True)
            for dt in all_months:
                txt = dt.strftime("%Y年 %m月") if dt in data_months else dt.strftime("%Y年 %m月 (无记录)")
                p.cb_time_picker.addItem(txt, dt.to_pydatetime())

        p.cb_time_picker.blockSignals(False)

    def quick_jump_time(self):
        p = self.page
        selected_dt = p.cb_time_picker.currentData()
        if selected_dt:
            p.current_review_date = selected_dt
            p.update_review_view()

    def change_review_time(self, delta):
        p = self.page
        if p.is_yearly_view:
            y = p.current_review_date.year + delta
            p.current_review_date = p.current_review_date.replace(year=y, month=1, day=1)
        else:
            m = p.current_review_date.month - 1 + delta
            y = p.current_review_date.year + m // 12
            m = m % 12 + 1
            p.current_review_date = p.current_review_date.replace(year=y, month=m, day=1)
        p.update_review_view()

    def jump_to_latest(self):
        p = self.page
        if p.main_win.engine.df.empty:
            return
        latest_date = pd.to_datetime(p.main_win.engine.df['trade_time']).dropna().max()
        if pd.notna(latest_date):
            p.current_review_date = latest_date.to_pydatetime()
            p.update_review_view()

    # ==========================================
    # 唯一汇总点：过滤 → 落状态 → 渲染
    # ==========================================
    def update_review_view(self):
        p = self.page
        p.lbl_selected_date.setText("当前视图已改变，请在日历重新选择日期...")
        p.day_trades_list.clear()
        p.txt_reason.clear()
        p.txt_reflection.clear()
        p.gallery.clear()

        p.lbl_trade_detail.setText("等待选择交易...")
        p.lbl_trade_detail.setStyleSheet("font-size: 14px; color: #9E9E9E; border: none;")
        p.orphan_bar.setVisible(False)

        p.current_editing_idx = None

        # 【v5.12 修正 · §9-O8】数据为空时也必须刷新时间选择器：
        # 旧代码在这里直接 return，导至清空账户/删完最后一条后，
        # 下拉框仍残留着已经不存在的月份项（陈旧 UI）。
        if p.main_win.engine.df.empty:
            p.refresh_time_picker(p.is_yearly_view)
            return

        p.refresh_time_picker(p.is_yearly_view)

        p.cb_time_picker.blockSignals(True)
        for i in range(p.cb_time_picker.count()):
            item_data = p.cb_time_picker.itemData(i)
            dt = item_data.toPyDateTime() if hasattr(item_data, 'toPyDateTime') else item_data

            if p.is_yearly_view:
                if dt.year == p.current_review_date.year:
                    p.cb_time_picker.setCurrentIndex(i)
                    break
            else:
                if dt.year == p.current_review_date.year and dt.month == p.current_review_date.month:
                    p.cb_time_picker.setCurrentIndex(i)
                    break
        p.cb_time_picker.blockSignals(False)

        df = p.main_win.engine.df.copy()

        # 【v5.12 · §9-O1 净额口径统一】"仅盈利 / 仅亏损"按真实到手判断，
        # 与流水页、Dashboard、core/analyzer 保持同一口径（§5.3-B）。
        if {'net_profit', 'commission'}.issubset(df.columns):
            df['net_amount'] = df['net_profit'] - df['commission'].fillna(0)
        else:
            df['net_amount'] = df['net_profit']

        acc_sel = p.cb_rev_account.currentData()
        if acc_sel != "ALL" and acc_sel is not None:
            df = df[df['account'] == acc_sel]

        str_sel = p.cb_rev_strategy.currentData()
        if str_sel != "ALL" and str_sel is not None:
            df = df[df['strategy_tag'] == str_sel]

        sym_sel = p.cb_rev_symbol.currentData()
        if sym_sel != "ALL" and sym_sel is not None:
            df['root_sym'] = df['symbol'].apply(extract_root_symbol)
            df = df[df['root_sym'] == sym_sel]

        dir_sel = p.cb_rev_direction.currentText()
        if dir_sel == "做多":
            df = df[df['direction'] == 'LONG']
        elif dir_sel == "做空":
            df = df[df['direction'] == 'SHORT']

        res_sel = p.cb_rev_result.currentText()
        if res_sel == "仅盈利":
            df = df[df['net_amount'] > 0]
        elif res_sel == "仅亏损":
            df = df[df['net_amount'] <= 0]

        df['trade_time'] = pd.to_datetime(df['trade_time'])

        y = p.current_review_date.year
        if p.is_yearly_view:
            p.current_view_df = df[df['trade_time'].dt.year == y].copy()
            p.yearly_panel.render(p.current_view_df)
        else:
            m = p.current_review_date.month
            p.current_view_df = df[(df['trade_time'].dt.year == y) & (df['trade_time'].dt.month == m)].copy()
            p.lbl_cal_month_title.setText(f"📅 {y}年 {m}月 复盘热力图")
            p._render_calendar()
            p._render_monthly_charts()
            p._render_duration_analysis()
