# ui/views/formula_hub.py
"""ƒ 函数总库 —— 页面本体（★1.61 / §7-B16 · 方案书 `docs/JIAN_HUB_PLAN.md`）。

把散在三处的用户函数（行情配方库 = 资产库本体 / M1 策略 / M2·M3 方案）收进一个**统一管理页**：
增删查改 + 编写 + 语法体检 + 引用管理 + 互送到各功能页。**总库只管资产，不管运行** ——
图表叠加 / 回测运行 / 扫描执行仍在各自功能页（红线①）。

【约定（scan_view 三件套同款）】状态全在页面（`_selected_id` / `_editing` / 筛选排序三键），
  版式装配 → `hub_layout.py`，行为 → `hub_flow.py`，编辑器 → `hub_editor.py`；
  数据层助手（内容命中 / 引用计数 / 快照时效）→ `data/hub_assets.py`（零 Qt）。
【落点唯一】编辑面只有本页编辑器；浮窗只许"载入 / 去总库编辑"；功能页只许"载入 / 同步最新"。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from data.formula_store import get_formula_store
from ui.dialogs.formula_overlay import TARGET_CHOICES
from ui.widgets.hub_flow import HubFlow
from ui.widgets.hub_layout import HubLayout

_TARGET_LABELS = {value: label for label, value in TARGET_CHOICES}


class FormulaHubView(QWidget):
    """ƒ 函数总库（左轨第 6 项 · 落位 = 📐市场回测 与 🗄数据管理 之间）。"""

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win

        # ---------------- 状态（全部在页面；widgets 模块只读写 p.X） ----------------
        self.filter_text = ''                        # 搜索框内容
        self.filter_src = 'all'                      # 来源筛选（all/market/backtest/scan/hub）
        self.sort_key = 'used'                       # used / name / refs

        # ---------------- 装配 ----------------
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)
        root.addWidget(self._build_title())
        self._layout = HubLayout(self)
        root.addWidget(self._layout.root, 1)        # 左右两栏（列表 + 详情/编辑器）由容器挂进来
        self.lbl_status = QLabel('')
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size:12px; color:#616B7A;")
        root.addWidget(self.lbl_status)

        self._flow = HubFlow(self)

        # ---------------- 接线（版式只建控件；业务在这里连） ----------------
        self.search.textChanged.connect(self._on_search)
        self.cmb_src.currentIndexChanged.connect(self._on_src)
        self.cmb_sort.currentIndexChanged.connect(self._on_sort)
        self.btn_new.clicked.connect(self._flow.new_asset)
        self.btn_checkall.clicked.connect(self._flow.check_all)
        self.btn_edit.clicked.connect(self._flow.edit)
        self.btn_cancel.clicked.connect(self._flow.cancel_edit)
        self.btn_save.clicked.connect(self._flow.save)
        self.btn_copy.clicked.connect(self._flow.copy)
        self.btn_delete.clicked.connect(self._flow.delete)
        self.btn_send_market.clicked.connect(lambda: self._flow.send('market'))
        self.btn_send_backtest.clicked.connect(lambda: self._flow.send('backtest'))
        self.btn_send_scan.clicked.connect(lambda: self._flow.send('scan'))

        self._flow.refresh()

    # ==========================================
    # 装配小件
    # ==========================================
    def _build_title(self) -> QWidget:
        head = QLabel('ƒ 函数总库　'
                      '<span style="color:#8A94A6; font-size:12px;">'
                      '管理只在这里；图表叠加 / 回测运行 / 全市场扫描仍在各自功能页</span>')
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setStyleSheet("font-size:16px; font-weight:700; color:#20242C;")
        return head

    # ==========================================
    # 供 hub_flow / hub_layout 使用的页面 API（widgets 只读写 p.X）
    # ==========================================
    def say(self, text: str) -> None:
        """底部回执一行（多行也收，tooltip 看全文）。"""
        self.lbl_status.setText(text or '')
        if text and '\n' in text:
            self.lbl_status.setToolTip(text)

    def show_detail(self) -> None:
        self.stack.setCurrentIndex(0)

    def show_editor(self) -> None:
        self.stack.setCurrentIndex(1)

    def d_segs_clear(self) -> None:
        while self.d_segs_lay.count():
            item = self.d_segs_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def d_segs_add(self, widget: QWidget) -> None:
        self.d_segs_lay.addWidget(widget)

    @staticmethod
    def target_label(target: str) -> str:
        return _TARGET_LABELS.get(target, target)

    @staticmethod
    def page_label(key: str) -> str:
        return {'market': '行情工作台', 'backtest': '回测页（M1）',
                'scan': '扫描页（M2/M3）'}.get(key, key)

    def store(self):
        """资产库单例（总库/浮窗/各页共用同一份内存实例 —— formula_store 的既有纪律）。"""
        return get_formula_store()

    # ==========================================
    # 筛选三键（薄壳：只回写状态，重建交给 flow）
    # ==========================================
    def _on_search(self, text: str) -> None:
        self.filter_text = str(text or '')
        self._flow.refresh(keep=self._flow._selected_id)

    def _on_src(self, _index: int) -> None:
        self.filter_src = str(self.cmb_src.currentData() or 'all')
        self._flow.refresh(keep=self._flow._selected_id)

    def _on_sort(self, _index: int) -> None:
        self.sort_key = str(self.cmb_sort.currentData() or 'used')
        self._flow.refresh(keep=self._flow._selected_id)

    # ==========================================
    # 对外入口（浮窗 / 主窗口用）
    # ==========================================
    def reveal_asset(self, asset_id: str) -> None:
        """浮窗「✏ 去总库编辑」的落点：切到查看态并选中该函数。"""
        self.show_detail()
        self._flow.select(asset_id)

    def refresh_assets(self) -> None:
        self._flow.refresh(keep=self._flow._selected_id)
