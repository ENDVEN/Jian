# ui/widgets/review_editor.py
"""复盘页的**当日清单 + 编辑卡 + 孤儿单缝合**（1.25 自 `ui/views/review.py` 拆出 · §9-L）。

【职责】把一个"已选中的日期/交易"变成可读可改的界面，并把用户改动写回引擎：
  · 当日清单：按日历选中的日期铺列表（净额着色 + 📝 复盘标记 + tooltip 口径说明）；
  · 详情头：品种 + 动作链 + 开/平价格 + 点数 + 净额（孤儿单如实标注"待补录"）；
  · 选中交易：回填策略 / 进场逻辑 / 离场反思 / 截图画廊，并触发 K 线回放；
  · 孤儿单补录：按盈亏反推开仓价 + 缝合（写库仍走引擎 `stitch_orphan_trade`）；
  · 复盘保存 / 删除此单 / 静默改归属策略。

【设计约定（与 desk_*.py 同源）】**状态全部留在页面** —— `current_editing_idx`、
  `current_view_df`、各控件都是页面属性；本模块只读写 `self.page.X`，不另存副本。
"""
from datetime import datetime

import pandas as pd
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QListWidgetItem, QMessageBox

from config import settings
from core.preferences import preferences
from core.utils import (format_fill_time, format_points, format_price,
                        format_trade_time, record_net_amount, row_points)
from ui.widgets.custom_widgets import COMBO_QSS_EDIT, COMBO_QSS_EDIT_OK


class ReviewEditor:
    """复盘页"清单 → 编辑"链路（页面持状态，本类承载行为）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 日历点击 → 铺当日清单
    # ==========================================
    def on_calendar_day_clicked(self, row, col):
        p = self.page
        item = p.review_calendar.item(row, col)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        qdate = item.data(Qt.ItemDataRole.UserRole)
        p.lbl_selected_date.setText(f"👇 选定日期: {qdate.toString('yyyy年MM月dd日')}")
        p.lbl_selected_date.setStyleSheet("font-weight: bold; color: #1976D2; font-size: 14px;")

        p.day_trades_list.clear()
        p.txt_reason.clear()
        p.txt_reflection.clear()
        p.gallery.clear()

        p.lbl_trade_detail.setText("请在下方列表选择一笔特定交易...")
        p.lbl_trade_detail.setStyleSheet("font-size: 14px; color: #9E9E9E; border: none;")
        p.orphan_bar.setVisible(False)

        p.current_editing_idx = None
        day_df = p.current_view_df[p.current_view_df['trade_time'].dt.day == qdate.day()]
        for idx, record in day_df.iterrows():
            # 【v6.9 · §9-P1 收尾】当日清单的金额与正负号一律用**净额**（真实到手），
            # 与过滤器 / Dashboard / core/analyzer 同口径，见 core.utils.record_net_amount。
            pnl, sym = record_net_amount(record), record['symbol']
            is_orphan = int(record.get('is_orphan', 0) or 0) == 1
            action = "买开" if record.get('direction') == 'LONG' else "卖开"
            entry_txt = format_price(record.get('entry_price')) if not is_orphan else "?"
            exit_txt = format_price(record.get('exit_price'))
            pts = row_points(record)
            pts_txt = format_points(pts) if pts is not None else "—点"
            arrow = "→" if not is_orphan else "?"
            time_tag = ""
            if preferences.use_fill_time():
                fill = format_fill_time(record.get('exit_fill_time'))
                if fill:
                    time_tag = f"@{fill}"

            txt = (f"{sym} | {action}{time_tag} {entry_txt}{arrow}{exit_txt} "
                   f"{pts_txt} ￥{'+' if pnl > 0 else ''}{pnl:,.0f}")
            if pd.notna(record.get('reflection')) and str(record.get('reflection')).strip() != "":
                txt += " 📝"

            list_item = QListWidgetItem(txt)
            list_item.setData(Qt.ItemDataRole.UserRole, idx)
            list_item.setForeground(QColor(settings.COLOR_PROFIT_TEXT) if pnl > 0 else QColor(settings.COLOR_LOSS_TEXT))
            tip = "金额为「净额」= 平仓盈亏 − 手续费（真实到手），颜色按净额正负判定。"
            if is_orphan:
                tip += "\n\n待缝合：未找到开仓记录。可补导更早月份交割单，或在选中后手工补录开仓价。"
            list_item.setToolTip(tip)
            p.day_trades_list.addItem(list_item)

    # ==========================================
    # 详情头文案
    # ==========================================
    @staticmethod
    def _display_time(record) -> str:
        """
        渲染主时间列（平仓锚点）。按用户的时间精度偏好附加真实时分。
        trade_time 主锚点永远是纯日期，时分来自独立的 exit_fill_time 字段。
        """
        base = format_trade_time(record.get('trade_time'))
        if preferences.use_fill_time():
            fill = format_fill_time(record.get('exit_fill_time'))
            if fill:
                return f"{base} {fill}"
        return base

    @staticmethod
    def _format_leg_time(value) -> str:
        """渲染某一腿的真实成交时刻；信息缺失时返回空串"""
        if value is None:
            return ""
        try:
            parsed = pd.to_datetime(value)
            return "" if pd.isna(parsed) else format_trade_time(parsed)
        except Exception:
            return ""

    def _update_detail_header(self, record, is_orphan: bool, pnl: float):
        """详情头：品种 + 动作链 + 开/平价格 + 点数 + 盈亏（孤儿单如实标注待补录）"""
        col_hex = settings.COLOR_PROFIT_TEXT if pnl > 0 else settings.COLOR_LOSS_TEXT
        is_long = record.get('direction') == 'LONG'
        action = "买入开仓" if is_long else "卖出开仓"
        close = "卖出平仓" if is_long else "买入平仓"
        entry_time_txt = self._format_leg_time(record.get('entry_time'))
        entry_price = format_price(record.get('entry_price'))
        exit_price = format_price(record.get('exit_price'))
        pts = row_points(record)

        html = (
            f'<span style="font-size:16px; font-weight:bold; color:#212121;">{record["symbol"]}</span>'
            f'<span style="color:#757575; font-size:12px;">&nbsp;|&nbsp; {action} → {close}</span><br/>'
            f'<span style="font-size:12px; color:#616161;">'
            f'平仓 {self._display_time(record)}'
            + (f'　·　开仓 {entry_time_txt}' if entry_time_txt else '')
            + '</span>'
        )
        if is_orphan:
            html += (
                '<br/><span style="font-size:13px; color:#757575;">开仓价: </span>'
                '<span style="font-size:13px; color:#F57C00; font-style:italic;">待补录（缝合前点数不可算）</span>'
                f'　→　平仓价 <b style="color:#212121;">{exit_price}</b>'
                '<span style="color:#757575;">　|　净额: </span>'
                f'<b style="color:{col_hex}; font-size:16px;">￥{pnl:,.2f}</b>'
            )
        else:
            pts_txt = format_points(pts) if pts is not None else "—"
            html += (
                '<br/><span style="font-size:13px; color:#757575;">开仓价 </span>'
                f'<b style="color:#212121;">{entry_price}</b>'
                '<span style="color:#616161;"> → </span>'
                f'<b style="color:#212121;">{exit_price}</b>'
                '<span style="color:#757575;">　|　盈亏 </span>'
                f'<b style="color:{col_hex};">{pts_txt} 点</b>'
                '<span style="color:#757575;">　|　净额: </span>'
                f'<b style="color:{col_hex}; font-size:16px;">￥{pnl:,.2f}</b>'
            )
        self.page.lbl_trade_detail.setText(html)

    # ==========================================
    # 选中交易 → 回填 + 触发回放
    # ==========================================
    def on_review_trade_selected(self, current, previous):
        p = self.page
        if not current:
            return
        df_idx = current.data(Qt.ItemDataRole.UserRole)
        if df_idx not in p.main_win.engine.df.index:
            return

        record = p.main_win.engine.df.loc[df_idx]
        p.current_editing_idx = df_idx

        is_orphan = int(record.get('is_orphan', 0) or 0) == 1
        # 头部的「结果」金额与颜色同样按净额（真实到手），§9-P1
        self._update_detail_header(record, is_orphan, record_net_amount(record))

        p.txt_reason.setPlainText(str(record.get('entry_reason', '')))
        p.txt_reflection.setPlainText(str(record.get('reflection', '')))

        p.cb_edit_strategy.blockSignals(True)
        p.cb_edit_strategy.setCurrentText(str(record.get('strategy_tag', settings.DEFAULT_STRATEGY)))
        p.cb_edit_strategy.blockSignals(False)

        # 孤儿补录条：仅孤儿单显示，开仓日期默认给到平仓日前一天（用户自行核对）
        p.orphan_bar.setVisible(is_orphan)
        if is_orphan:
            close_dt = pd.to_datetime(record['trade_time']) - pd.Timedelta(days=1)
            p.inp_orphan_date.setDate(QDate(close_dt.year, close_dt.month, close_dt.day))
            p.inp_orphan_price.clear()
            p.inp_orphan_price.setFocus()

        # 绑定归属交易后重建画廊，后续粘贴/导入的截图都会挂到这笔交易名下
        p.gallery.set_owner(record.get('internal_id'))
        p.gallery.set_paths(record.get('screenshot_paths', ''))

        # ==========================================
        # 【终极杀器】触发 K 线回放渲染引擎！
        # ==========================================
        p._render_trade_playback(record)

    # ==========================================
    # 孤儿单：反推开仓价 + 缝合
    # ==========================================
    @staticmethod
    def _guess_orphan_entry_price(record):
        """
        按盈亏反推理论开仓价（快速指引的可行性实现）。

        方向公式：
          LONG : 盈亏 = (平仓价 − 开仓价) × 乘数 × 手数  ⇒  开仓价 = 平仓价 − 盈亏/(乘数×手数)
          SHORT: 盈亏 = (开仓价 − 平仓价) × 乘数 × 手数  ⇒  开仓价 = 平仓价 + 盈亏/(乘数×手数)

        【诚实边界】仅在开仓价未知且整笔平仓可归因时足够准确；
        若一笔平仓混有多个开仓（含匹配片），反推值是加权近似，
        必须提示用户与真实交割单核对后使用。
        """
        try:
            exit_price = float(record.get('exit_price'))
            pnl = float(record.get('net_profit', 0.0))
            lots = int(record.get('lots', 0) or 0)
            multiplier = float(record.get('multiplier', 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        if exit_price <= 0 or lots <= 0 or multiplier <= 0:
            return None
        per_lot = pnl / (multiplier * lots)
        if record.get('direction') == 'LONG':
            return exit_price - per_lot
        return exit_price + per_lot

    def guess_orphan_entry_price(self):
        """点击「↩ 按盈亏推算」：把反推出的开仓价填入输入框供用户核对"""
        p = self.page
        idx = getattr(p, 'current_editing_idx', None)
        if idx is None or idx not in p.main_win.engine.df.index:
            return
        record = p.main_win.engine.df.loc[idx]
        if int(record.get('is_orphan', 0) or 0) != 1:
            return

        guess = self._guess_orphan_entry_price(record)
        if guess is None:
            QMessageBox.information(
                p, "无法推算",
                "这笔交易缺少足够的平仓价 / 手数 / 合约乘数，无法按盈亏反推开仓价。\n"
                "请对照交割单手动填写真实开仓价。")
            return

        p.inp_orphan_price.setText(format_price(guess))
        p.inp_orphan_price.setFocus()
        p.lbl_orphan_guide.setText(
            f"已按盈亏反推：开仓价约 {format_price(guess)}（依据盈亏 {record['net_profit']:,.2f} ÷ "
            f"乘数 {record.get('multiplier', 0):.0f} ÷ 手数 {int(record.get('lots', 0) or 0)}）。\n"
            "该值仅供快速参考 —— 若此平仓同时对应多个开仓价位，结果会是加权近似值，"
            "请务必与交割单核对后再点「补录并缝合」。")

    def stitch_current_orphan(self):
        """孤儿单手工补录：开仓日期 + 开仓价 → 缝合为完整闭环"""
        p = self.page
        idx = getattr(p, 'current_editing_idx', None)
        if idx is None or idx not in p.main_win.engine.df.index:
            return
        record = p.main_win.engine.df.loc[idx]
        if int(record.get('is_orphan', 0) or 0) != 1:
            return

        price_text = p.inp_orphan_price.text().strip().replace(',', '')
        try:
            price = float(price_text)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            QMessageBox.warning(p, "请输入有效开仓价",
                                "请填写该笔平仓对应的开仓成交价（例如 6010.6）。")
            p.inp_orphan_price.setFocus()
            return

        qdate = p.inp_orphan_date.date()
        entry_dt = datetime(qdate.year(), qdate.month(), qdate.day())
        internal_id = record.get('internal_id')

        ok = p.main_win.engine.stitch_orphan_trade(internal_id, price, entry_time=entry_dt)
        if not ok:
            QMessageBox.critical(p, "缝合失败", "数据库更新失败，请重试。")
            return

        QMessageBox.information(
            p, "缝合成功",
            "已补录开仓信息，该笔交易已缝合为完整闭环。\n"
            "现在可显示开仓价与点数，并支持双点锚定回放。")
        p.orphan_bar.setVisible(False)
        p.current_editing_idx = None
        p.main_win.render_all_data()

    # ==========================================
    # 保存 / 删除 / 改归属策略
    # ==========================================
    def save_review_text(self):
        p = self.page
        if getattr(p, 'current_editing_idx', None) is None:
            QMessageBox.warning(p, "提示", "请先选择一笔交易！")
            return

        reason = p.txt_reason.toPlainText()
        reflection = p.txt_reflection.toPlainText()
        self._save_image_paths_to_df()

        paths = p.main_win.engine.df.at[p.current_editing_idx, 'screenshot_paths']
        p.main_win.engine.update_trade_review(p.current_editing_idx, reason, reflection, paths)

        if p.current_editing_idx in p.current_view_df.index:
            p.current_view_df.at[p.current_editing_idx, 'entry_reason'] = reason
            p.current_view_df.at[p.current_editing_idx, 'reflection'] = reflection
            p.current_view_df.at[p.current_editing_idx, 'screenshot_paths'] = paths

        p._render_calendar()

        original_style = p.btn_save_review.styleSheet()
        p.btn_save_review.setText("✅ 保存成功")
        p.btn_save_review.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; border: none; border-radius: 6px; padding: 10px; font-weight: bold; }")

        def reset_btn():
            p.btn_save_review.setText("💾 保存复盘文字与截图")
            p.btn_save_review.setStyleSheet(original_style)

        QTimer.singleShot(1500, reset_btn)

    def _save_image_paths_to_df(self):
        """将画廊当前内容同步进内存 DataFrame (真正的落库时机由“保存复盘”按钮决定)"""
        p = self.page
        if getattr(p, 'current_editing_idx', None) is None:
            return
        p.main_win.engine.df.at[p.current_editing_idx, 'screenshot_paths'] = p.gallery.get_paths()

    def delete_current_trade(self):
        p = self.page
        if getattr(p, 'current_editing_idx', None) is None:
            return
        if QMessageBox.question(p, "危险操作", "永久删除此交易记录？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if p.main_win.engine.delete_trade(p.current_editing_idx):
                p.current_editing_idx = None
                p.main_win.render_all_data()

    def silent_update_strategy(self, *args):
        p = self.page
        if getattr(p, 'current_editing_idx', None) is None:
            return
        new_st = p.cb_edit_strategy.currentText().strip()
        new_st = settings.DEFAULT_STRATEGY if new_st == "" else new_st

        if p.current_editing_idx not in p.main_win.engine.df.index:
            return
        old_st = str(p.main_win.engine.df.at[p.current_editing_idx, 'strategy_tag']).strip()

        if new_st == old_st:
            return
        p.main_win.engine.update_trade_strategy(p.current_editing_idx, new_st)

        if p.current_editing_idx in p.current_view_df.index:
            p.current_view_df.at[p.current_editing_idx, 'strategy_tag'] = new_st

        p.refresh_review_filters()

        p.cb_edit_strategy.setStyleSheet(COMBO_QSS_EDIT_OK)
        QTimer.singleShot(1000, lambda: p.cb_edit_strategy.setStyleSheet(COMBO_QSS_EDIT))
