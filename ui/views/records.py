# ui/views/records.py
import pandas as pd
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QTabWidget, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QComboBox, QMenu, QFrame, QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from config import settings
from core.preferences import TIME_PRECISION_DATE, TIME_PRECISION_FILL, preferences
from core.utils import (extract_root_symbol, format_fill_time, format_points,
                        format_price, format_trade_time, row_points)

# 表格列定义（单一事实来源：新增/调整列只需改这里）
COLUMNS = ["单号", "账户", "品种", "买卖", "开仓价", "平仓价", "点数", "交易时间", "手数", "盈亏", "手续费"]
COL_POINTS = COLUMNS.index("点数")
COL_PNL = COLUMNS.index("盈亏")


class RecordsView(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # ==========================================
        # 顶部操作栏
        # ==========================================
        top_bar_1 = QHBoxLayout()
        title = QLabel("交易流水明细")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        
        # 【修改点】将导入按钮升级为带下拉菜单的按钮
        self.btn_import = QPushButton("📥 导入数据")
        self.btn_import.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; } QPushButton::menu-indicator { image: none; }")
        
        import_menu = QMenu(self.btn_import)
        import_menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #E0E0E0; border-radius: 4px; padding: 5px; } 
            QMenu::item { padding: 8px 25px; font-size: 14px; color: #333; } 
            QMenu::item:selected { background-color: #E3F2FD; color: #1976D2; border-radius: 4px;}
        """)
        
        action_futures = import_menu.addAction("📊 导入期货交割单")
        action_futures.triggered.connect(self.main_win.open_futures_import)

        self.btn_import.setMenu(import_menu)
        
        self.btn_manual = QPushButton("✍️ 录入")
        self.btn_manual.setStyleSheet(f"QPushButton {{ background-color: {settings.COLOR_PROFIT}; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }}")
        self.btn_manual.clicked.connect(self.main_win.open_manual_entry)
        
        self.btn_export = QPushButton("📤 导出")
        self.btn_export.setStyleSheet("QPushButton { background-color: #FF9800; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }")
        self.btn_export.clicked.connect(self.main_win.export_data)
        
        self.btn_manage_acc = QPushButton("🗑️ 清空账户")
        self.btn_manage_acc.setStyleSheet(f"QPushButton {{ background-color: white; color: {settings.COLOR_LOSS}; border: 1px solid {settings.COLOR_LOSS}; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }}")
        self.btn_manage_acc.clicked.connect(self.main_win.manage_accounts)
        
        top_bar_1.addWidget(title)
        top_bar_1.addStretch()
        top_bar_1.addWidget(self.btn_import)
        top_bar_1.addWidget(self.btn_manual)
        top_bar_1.addWidget(self.btn_export)
        top_bar_1.addWidget(self.btn_manage_acc)
        
        # ==========================================
        # 【v1.2】待缝合平仓常驻提醒
        # ==========================================
        self.orphan_banner = QFrame()
        self.orphan_banner.setStyleSheet(
            "QFrame { background: #FFF8E1; border: 1px solid #FFE082; border-radius: 6px; }")
        banner_layout = QHBoxLayout(self.orphan_banner)
        banner_layout.setContentsMargins(14, 8, 10, 8)
        
        self.lbl_orphan = QLabel()
        self.lbl_orphan.setStyleSheet("color: #EF6C00; font-size: 13px; border: none;")
        banner_layout.addWidget(self.lbl_orphan)
        banner_layout.addStretch()
        
        self.btn_help_orphan = QPushButton("❓ 如何补录")
        self.btn_help_orphan.setStyleSheet(
            "QPushButton { border: none; color: #E65100; background: transparent; "
            "text-decoration: underline; padding: 4px 6px; font-size: 12px; }")
        self.btn_help_orphan.clicked.connect(self.show_orphan_help)
        banner_layout.addWidget(self.btn_help_orphan)

        self.btn_view_orphans = QPushButton("仅看这些")
        self.btn_view_orphans.setStyleSheet(
            "QPushButton { border: 1px solid #FFB74D; color: #E65100; background: white; "
            "border-radius: 4px; padding: 4px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #FFE0B2; }")
        self.btn_view_orphans.clicked.connect(self.focus_orphans)
        banner_layout.addWidget(self.btn_view_orphans)
        self.orphan_banner.setVisible(False)
        
        # ==========================================
        # 【新增】高级多条件过滤器 (Advanced Filters)
        # ==========================================
        top_bar_2 = QHBoxLayout()
        
        top_bar_2.addWidget(QLabel("账户:"))
        self.cb_acc = QComboBox(); self.cb_acc.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_acc)
        
        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("品种主体:"))
        self.cb_sym = QComboBox(); self.cb_sym.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_sym)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("买卖:"))
        self.cb_dir = QComboBox()
        self.cb_dir.addItems(["全部", "买入开仓 (做多)", "卖出开仓 (做空)"])
        self.cb_dir.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_dir)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("盈亏结果:"))
        self.cb_res = QComboBox()
        self.cb_res.addItems(["全部", "仅盈利", "仅亏损"])
        self.cb_res.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_res)

        # v1.2：区分"完整闭环"与"待缝合（开仓腿缺失）"
        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("完整度:"))
        self.cb_stitch = QComboBox()
        self.cb_stitch.addItems(["全部", "仅完整闭环", "仅待缝合"])
        self.cb_stitch.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_stitch)

        top_bar_2.addStretch()

        # v1.2：时间精度开关（长线用户关、日内用户开，随时可切换）
        self.btn_toggle_time = QPushButton()
        self.btn_toggle_time.setCheckable(True)
        self.btn_toggle_time.setToolTip(
            "切换交易时间的显示粒度：\n"
            "关 = 只显示到某一天（适合波段 / 长线）\n"
            "开 = 附加真实成交时刻（适合日内 / 高频）")
        self.btn_toggle_time.clicked.connect(self.toggle_time_precision)
        top_bar_2.addWidget(self.btn_toggle_time)

        # NOTE(v1.1)：原"持仓时间"过滤依赖开/平仓双时间，交割单不再提供该数据，已删除
        
        self.records_tab_widget = QTabWidget()
        self.records_tab_widget.setStyleSheet("QTabWidget::pane { border: 1px solid #E0E0E0; border-radius: 8px; background: white; top: -1px; } QTabBar::tab { background: #F5F5F5; color: #757575; padding: 10px 25px; border: 1px solid #E0E0E0; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 4px; font-weight: bold; } QTabBar::tab:selected { background: white; color: #1976D2; border-bottom: 2px solid white; }")
        
        layout.addLayout(top_bar_1)
        layout.addWidget(self.orphan_banner)
        layout.addLayout(top_bar_2)
        layout.addSpacing(10)
        layout.addWidget(self.records_tab_widget)

        self._sync_time_button()

    # ==========================================
    # 时间精度开关
    # ==========================================
    def _sync_time_button(self):
        using = preferences.use_fill_time()
        self.btn_toggle_time.setChecked(using)
        self.btn_toggle_time.setText("⏱ 时刻：开" if using else "⏱ 时刻：关")
        if using:
            self.btn_toggle_time.setStyleSheet(
                "QPushButton { border: 1px solid #90CAF9; color: #1565C0; background: #E3F2FD; "
                "border-radius: 4px; padding: 5px 12px; font-size: 12px; font-weight: bold; }")
        else:
            self.btn_toggle_time.setStyleSheet(
                "QPushButton { border: 1px solid #E0E0E0; color: #757575; background: white; "
                "border-radius: 4px; padding: 5px 12px; font-size: 12px; }")

    def toggle_time_precision(self):
        """切换时间显示粒度 —— 数据始终完整保存，切换零成本且立即生效"""
        new_value = TIME_PRECISION_FILL if not preferences.use_fill_time() else TIME_PRECISION_DATE
        preferences.set_time_precision(new_value)
        self._sync_time_button()
        self.apply_filters()

    def focus_orphans(self):
        """把筛选器切到"仅待缝合"，让用户一眼看清是哪些单子缺开仓信息"""
        idx = self.cb_stitch.findText("仅待缝合")
        if idx >= 0:
            self.cb_stitch.setCurrentIndex(idx)

    def show_orphan_help(self):
        """向用户说明：待缝合单的正确补录路径（表格本身不可编辑）"""
        QMessageBox.information(
            self,
            "如何补录开仓信息",
            "「待缝合」表示这笔平仓在已导入的数据里找不到对应开仓记录。\n\n"
            "① 若开仓仓位建于更早月份：点击「导入数据 → 导入期货交割单」，"
            "补导更早月份的交割单，系统会自动完成缝合（无需手工填写）。\n\n"
            "② 若确实没有更早的交割单：\n"
            "　· 点击左下角「仅看这些」，选中这笔待缝合单；\n"
            "　· 进入左侧「💡 深度复盘」，点选该交易；\n"
            "　· 编辑区会出现橙色补录条，填写「开仓日期 + 开仓价」，"
            "点「补录并缝合」即永久保存。\n\n"
            "⚠️ 提示：本流水表格仅作查看，直接在单元格里敲数字不会被保存。")


    # ==========================================
    # 数据刷新
    # ==========================================
    def refresh_records_filters(self):
        """主窗口数据变动时，刷新这里的下拉框选项"""
        for cb in (self.cb_acc, self.cb_sym):
            cb.blockSignals(True)
        try:
            self._populate_record_filter_options()
        finally:
            # 【健壮性】异常时也必须恢复信号，避免下拉框"假死"
            for cb in (self.cb_acc, self.cb_sym):
                cb.blockSignals(False)
        # 数据为空时 apply_filters 会清空表格，统一走同一出口
        self.apply_filters()

    def _populate_record_filter_options(self):
        df = self.main_win.engine.df

        self.cb_acc.clear(); self.cb_acc.addItem("全账户", "ALL")
        if not df.empty:
            for acc in df['account'].dropna().unique():
                self.cb_acc.addItem(str(acc), str(acc))

        self.cb_sym.clear(); self.cb_sym.addItem("全品种", "ALL")
        if not df.empty:
            roots = {extract_root_symbol(sym) for sym in df['symbol'].dropna().unique()}
            for r in sorted(roots):
                self.cb_sym.addItem(r, r)

    def apply_filters(self):
        """执行高级多维过滤矩阵，并将结果输出给表格"""
        df = self.main_win.engine.df.copy()
        if df.empty:
            self.clear_view()
            self.orphan_banner.setVisible(False)
            return

        # 【兼容性】加列迁移前导入的老记录 is_orphan 为 NULL，统一按"已闭环"处理
        if 'is_orphan' in df.columns:
            df['is_orphan'] = pd.to_numeric(df['is_orphan'], errors='coerce').fillna(0).astype(int)
        else:
            df['is_orphan'] = 0

        self._update_orphan_banner(df)

        # 1. 账户过滤
        acc_sel = self.cb_acc.currentData()
        if acc_sel != "ALL" and acc_sel is not None: 
            df = df[df['account'] == acc_sel]
            
        # 2. 品种过滤
        sym_sel = self.cb_sym.currentData()
        if sym_sel != "ALL" and sym_sel is not None: 
            df['root_sym'] = df['symbol'].apply(extract_root_symbol)
            df = df[df['root_sym'] == sym_sel]
            
        # 3. 买卖方向过滤
        dir_sel = self.cb_dir.currentText()
        if "买入开仓" in dir_sel: df = df[df['direction'] == 'LONG']
        elif "卖出开仓" in dir_sel: df = df[df['direction'] == 'SHORT']
            
        # 4. 盈亏过滤
        res_sel = self.cb_res.currentText()
        if res_sel == "仅盈利": df = df[df['net_profit'] > 0]
        elif res_sel == "仅亏损": df = df[df['net_profit'] <= 0]

        # 5. 数据完整度过滤
        stitch_sel = self.cb_stitch.currentText()
        if stitch_sel == "仅完整闭环": df = df[df['is_orphan'] == 0]
        elif stitch_sel == "仅待缝合": df = df[df['is_orphan'] == 1]

        self._populate_table_internal(df)

    def _update_orphan_banner(self, df):
        """待缝合平仓的常驻提醒 —— 用户必须知情，但绝不阻断任何功能"""
        count = int((df['is_orphan'] == 1).sum()) if not df.empty else 0
        self.orphan_banner.setVisible(count > 0)
        if count:
            self.lbl_orphan.setText(
                f"⚠️ 有 {count} 笔平仓未找到开仓记录（开仓价显示为「待补录」）"
                f"　·　这些仓位很可能建于尚未导入的月份，补导后系统会自动缝合")

    def clear_view(self):
        self.records_tab_widget.clear()

    def _populate_table_internal(self, df):
        self.clear_view()
        if df.empty: return
        
        # 动态创建页签：第一个永远是符合筛选条件的总览
        self._create_table_for_tab(f"筛选结果 ({len(df)}笔)", df)
        
        # 如果没有按账户筛选，就额外生成每个账户的分类页签
        account_filter = self.cb_acc.currentData()
        if account_filter == "ALL" or account_filter is None:
            for acc in df['account'].unique():
                if pd.notna(acc): 
                    acc_df = df[df['account'] == acc]
                    self._create_table_for_tab(f"{acc} ({len(acc_df)}笔)", acc_df)

    @staticmethod
    def _display_time(record) -> str:
        """
        按用户的时间精度偏好渲染交易时间。

        trade_time 主锚点永远是纯日期，成交时刻单独存放在 exit_fill_time；
        只有偏好为"精确到时分"且该笔确实存在时分时才附加 HH:MM，
        绝不因为偏好而凭空造出一个时刻。
        """
        base = format_trade_time(record.get('trade_time'))
        if preferences.use_fill_time():
            fill = format_fill_time(record.get('exit_fill_time'))
            if fill:
                return f"{base} {fill}"
        return base

    def _create_table_for_tab(self, tab_name, df_subset):
        table = QTableWidget()
        table.setColumnCount(len(COLUMNS))
        table.setHorizontalHeaderLabels(COLUMNS)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("QTableWidget { background-color: white; alternate-background-color: #FAFAFA; border: none; gridline-color: #EEEEEE; } QHeaderView::section { background-color: #F5F5F5; color: #757575; font-weight: bold; border: none; border-bottom: 1px solid #E0E0E0; padding: 10px; text-align: left; }")
        table.setRowCount(len(df_subset))
        
        df_reversed = df_subset.iloc[::-1].reset_index(drop=True) 
        for row in range(len(df_reversed)):
            record = df_reversed.iloc[row]
            is_orphan = int(record.get('is_orphan', 0) or 0) == 1
            is_long = record.get('direction') == 'LONG'

            # 买卖分类：开仓腿方向 + 待缝合标记
            action_text = "买入开仓" if is_long else "卖出开仓"
            if is_orphan:
                action_text += " *"

            # 开仓价：待缝合时明确显示"待补录"，绝不显示 0.00 制造假象
            if is_orphan:
                entry_text = "待补录"
            else:
                entry_text = format_price(record.get('entry_price'))

            points = row_points(record)

            items = [
                QTableWidgetItem(str(record.get('trade_id', '-'))), 
                QTableWidgetItem(str(record.get('account', '-'))), 
                QTableWidgetItem(str(record.get('symbol', '-'))), 
                QTableWidgetItem(action_text), 
                QTableWidgetItem(entry_text),
                QTableWidgetItem(format_price(record.get('exit_price'))),
                QTableWidgetItem(format_points(points)),
                QTableWidgetItem(self._display_time(record)),
                QTableWidgetItem(str(record.get('lots', 0))), 
                QTableWidgetItem(f"￥{record.get('net_profit', 0):,.2f}"), 
                QTableWidgetItem(f"￥{record.get('commission', 0):.2f}")
            ]

            # 待缝合行的开仓价用灰色斜体，并附上可操作的提示
            if is_orphan:
                items[4].setForeground(QColor("#BDBDBD"))
                items[4].setFont(QFont("Arial", 10, -1, True))
                items[4].setToolTip(
                    "未找到开仓记录。可导入更早月份的交割单自动缝合，"
                    "或在「深度复盘」中选中此单手工补录开仓价。")

            # 点数与盈亏同色（绿盈红亏），盈亏列加粗
            pnl_color = settings.COLOR_PROFIT_TEXT if record.get('net_profit', 0) > 0 else settings.COLOR_LOSS_TEXT
            items[COL_PNL].setForeground(QColor(pnl_color))
            items[COL_PNL].setFont(QFont("Arial", 10, QFont.Weight.Bold))
            if points is not None:
                items[COL_POINTS].setForeground(
                    QColor(settings.COLOR_PROFIT_TEXT if points > 0 else settings.COLOR_LOSS_TEXT))

            # 买卖分类的 tooltip 展示完整动作链
            close_action = "卖出平仓" if is_long else "买入平仓"
            items[3].setToolTip(f"{action_text.strip(' *')} → {close_action}")
            
            for col, item in enumerate(items): 
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, col, item)
                
        self.records_tab_widget.addTab(table, tab_name)
