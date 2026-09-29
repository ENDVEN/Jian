# ui/widgets/hub_layout.py
"""ƒ 函数总库的**版式装配**（★1.61 / §7-B16 · H2 · 设计稿 = `design/1.60-formula-hub/a-双栏管理台`）。

【约定（scan_view 三件套同款）】状态全在页面（`ui/views/formula_hub.py`），本模块只建控件、
  读写 `p.X`，不存副本；行为在 `hub_flow.py`；编辑器在 `hub_editor.py`。
【版式分层（§10-14）】左 = 列表面板（L1 操作轴：搜索/筛选/排序 ≤3 行 + 列表）；右 = 详情（L0）
  ⇄ 编辑器（L3 性质的整页切换，不是抽屉 —— 总库页没有"结果区"可保护）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from data.formula_store import SOURCE_LABELS
from ui.widgets.custom_widgets import (FLAT_QSS, NoWheelComboBox, OUTLINE_QSS,
                                       mini_label, mono_font_css)
from ui.widgets.hub_editor import FormulaAssetEditor

HUB_LIST_WIDTH = 318

_PANEL_QSS = ("QFrame#HubPanel { background:#FFFFFF; border:1px solid #E6EAF0;"
              " border-radius:14px; }"
              "QFrame#HubItem { background:#FFFFFF; border:1px solid #E6EAF0;"
              " border-radius:11px; }"
              "QFrame#HubItem:hover { border-color:#BBDEFB; background:#FAFCFF; }"
              "QFrame#HubItem[selected=\"true\"] { border-color:#1976D2; background:#E8F1FB; }"
              "QLabel { background:transparent; }")
_ITEM_QSS_NORM = "QFrame#HubItem { border:1px solid #E6EAF0; background:#FFFFFF; }"
_ITEM_QSS_ON = "QFrame#HubItem { border:1px solid #1976D2; background:#E8F1FB; }"


class HubItem(QFrame):
    """列表里的一条（可点选中）。

    ⚠ 必须子类覆写 `mousePressEvent` —— 给实例赋属性不参与 Qt 的 C++ 事件派发
      （`download_queue_panel._ClickableLabel` 同款教训）。
    """

    def __init__(self, asset_id: str, on_pick, parent=None):
        super().__init__(parent)
        self.setObjectName('HubItem')
        self._asset_id = asset_id
        self._on_pick = on_pick
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def asset_id(self) -> str:
        return self._asset_id

    def set_selected(self, on: bool) -> None:
        self.setProperty('selected', 'true' if on else 'false')
        self.setStyleSheet(_ITEM_QSS_ON if on else _ITEM_QSS_NORM)

    def mousePressEvent(self, event):  # noqa: N802 —— Qt 命名
        if callable(self._on_pick):
            self._on_pick(self._asset_id)
        event.accept()


# ==========================================
# 列表行的**唯一**画法（A 页与浮窗共用 —— 样式不统一 = 用户看不出是同一个库）
# ==========================================
def syntax_chip(asset: dict) -> str:
    """语法状态标记（`✗` / `⚠` 才显示；通过 / 未检测不占地方）。"""
    st = asset.get('syntax_state')
    if st == 'err':
        return '✗'
    if st == 'warn':
        return '⚠'
    return ''


def asset_row_meta(asset: dict, n_refs: int) -> str:
    """行的元信息一行（来源 · 段数 · 引用数 · 最近使用 · 语法标记）。

    ⚠ **唯一口径**：A 页卡片与浮窗列表都调它。两处各写一份文案，用户就会觉得
      "这是两个不同的东西" —— 而我们要的恰恰是"背后同一个库"的感知。
    """
    src = SOURCE_LABELS.get(asset.get('source'), asset.get('source') or '—')
    used = str(asset.get('used_at') or '')
    return (f"{src} · {len(asset.get('segments') or [])} 段 · "
            f"{'引用 ' + str(n_refs) if n_refs else '未被引用'} · "
            f"{'用过 ' + used[5:10] if used else '未使用'} {syntax_chip(asset)}").strip()


def build_plain_row(row_id: str, title: str, meta: str, on_pick, selected: bool) -> HubItem:
    """一行"普通条目"（标题 + 元信息）—— **资产行与方案行共用同一张脸与选中态**。

    ⚠ 统一的意义：用户在不同地方看到**同一种行**，才会认得出"背后是同一个库在管"。
    """
    item = HubItem(row_id, on_pick)
    item.set_selected(bool(selected))
    lay = QVBoxLayout(item)
    lay.setContentsMargins(9, 7, 9, 7)
    lay.setSpacing(2)
    name = QLabel(str(title or '未命名'))
    name.setStyleSheet("font-size:13px; font-weight:600; color:#20242C;")
    name.setWordWrap(True)
    lay.addWidget(name)
    meta_lbl = QLabel(str(meta or ''))
    meta_lbl.setStyleSheet("font-size:11.3px; color:#8A94A6;")
    meta_lbl.setWordWrap(True)
    lay.addWidget(meta_lbl)
    return item


def build_asset_row(asset: dict, n_refs: int, on_pick, selected: bool) -> HubItem:
    """造一行资产（**唯一实现处**）—— A 页与浮窗都调它，防"两处各画一张脸"。"""
    return build_plain_row(asset['id'], str(asset.get('name') or '未命名'),
                           asset_row_meta(asset, n_refs), on_pick, selected)


class HubLayout:
    """总库页装配：只建控件并挂到 page，不接业务（接线在 hub_flow）。"""

    def __init__(self, page):
        self.p = page
        page.setStyleSheet(_PANEL_QSS)
        # ⚠ 绝不能 `QHBoxLayout(page)`：页面自己已有根布局（`QVBoxLayout`），
        #   而 Qt 里**一个 widget 只允许一个布局** ⇒ 第二个被静默丢弃
        #   （报错 "QLayout: Attempting to add ... which already has a layout"），
        #   左右两栏根本挂不上页面（真事故：整页只剩标题一行）。
        #   照 `scan_view` 三件套范式：本模块只**造容器**，页面自己 `root.addWidget(self.root, 1)`。
        self.root = QWidget()
        root = QHBoxLayout(self.root)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(self._build_list_panel())
        root.addWidget(self._build_right(), 1)
        # 控件全部**转挂到页面**（约定：widgets 模块只读写 `p.X`，本模块不留私有副本；
        # hub_flow 一律 `self.p.d_name` 这样访问 —— 挂错地方就是全段 AttributeError）
        for _name in ('search', 'cmb_src', 'cmb_sort', 'list_lay', 'btn_new', 'btn_checkall',
                      'lbl_stat', 'stack', 'd_name', 'd_src', 'd_state', 'd_meta',
                      'd_segs_lay', 'd_refs', 'btn_edit', 'btn_send_market',
                      'btn_send_backtest', 'btn_send_scan', 'btn_copy', 'btn_delete',
                      'btn_cancel', 'btn_save', 'editor'):
            setattr(self.p, _name, getattr(self, _name))

    # ==========================================
    # 左：列表面板
    # ==========================================
    def _build_list_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName('HubPanel')
        panel.setFixedWidth(HUB_LIST_WIDTH)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索名称 / 参数 / 函数文本…')
        lay.addWidget(self.search)

        filt = QHBoxLayout()
        filt.addWidget(mini_label('来源'))
        self.cmb_src = NoWheelComboBox()
        for value, label in (('all', '全部'), ('market', '行情页'), ('backtest', '回测页'),
                             ('scan', '扫描页'), ('hub', '总库')):
            self.cmb_src.addItem(label, value)
        filt.addWidget(self.cmb_src, 1)
        lay.addLayout(filt)

        sort = QHBoxLayout()
        sort.addWidget(mini_label('排序'))
        self.cmb_sort = NoWheelComboBox()
        for value, label in (('used', '最近使用'), ('name', '名称'), ('refs', '被引用数')):
            self.cmb_sort.addItem(label, value)
        sort.addWidget(self.cmb_sort, 1)
        lay.addLayout(sort)

        # 列表：滚动区 + 纵向重建（条目数 = 资产数，量级很小，重建毫秒级）
        host = QWidget()
        self.list_lay = QVBoxLayout(host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(6)
        self.list_lay.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        row = QHBoxLayout()
        self.btn_new = QPushButton('＋ 新建函数')
        self.btn_new.setStyleSheet(FLAT_QSS)
        self.btn_checkall = QPushButton('🩺 全库体检')
        self.btn_checkall.setStyleSheet(OUTLINE_QSS)
        self.btn_checkall.setToolTip('对全部资产跑一遍真引擎语法体检（纯计算，毫秒级）')
        row.addWidget(self.btn_new)
        row.addWidget(self.btn_checkall)
        lay.addLayout(row)

        self.lbl_stat = QLabel('')
        self.lbl_stat.setStyleSheet("font-size:11.5px; color:#8A94A6;")
        lay.addWidget(self.lbl_stat)
        return panel

    # ==========================================
    # 右：详情 ⇄ 编辑器（QStackedWidget 两页）
    # ==========================================
    def _build_right(self) -> QWidget:
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_detail())       # index 0 = 查看态
        self.stack.addWidget(self._build_editor())       # index 1 = 编辑态
        return self.stack

    def _build_detail(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName('HubPanel')
        body = QVBoxLayout(card)
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(8)

        head = QHBoxLayout()
        self.d_name = QLabel('—')
        self.d_name.setStyleSheet("font-size:15px; font-weight:700; color:#20242C;")
        head.addWidget(self.d_name)
        self.d_src = QLabel('')
        head.addWidget(self.d_src)
        self.d_state = QLabel('')
        head.addWidget(self.d_state)
        head.addStretch()
        self.btn_edit = QPushButton('✏ 编辑')
        self.btn_edit.setStyleSheet(OUTLINE_QSS)
        head.addWidget(self.btn_edit)
        body.addLayout(head)

        self.d_meta = QLabel('')
        self.d_meta.setStyleSheet("font-size:12px; color:#8A94A6;")
        self.d_meta.setWordWrap(True)
        body.addWidget(self.d_meta)

        body.addWidget(self._sep())
        self.d_segs_title = QLabel('函数段（每段目标窗格在标签上）')
        self.d_segs_title.setStyleSheet("font-size:13px; color:#616B7A; font-weight:600;")
        body.addWidget(self.d_segs_title)
        segs_host = QWidget()
        self.d_segs_lay = QVBoxLayout(segs_host)
        self.d_segs_lay.setContentsMargins(0, 0, 0, 0)
        self.d_segs_lay.setSpacing(6)
        segs_scroll = QScrollArea()
        segs_scroll.setWidgetResizable(True)
        segs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        segs_scroll.setWidget(segs_host)
        body.addWidget(segs_scroll, 1)

        body.addWidget(self._sep())
        self.d_refs = QLabel('')
        self.d_refs.setWordWrap(True)
        self.d_refs.setStyleSheet("font-size:12px; color:#616B7A;")
        body.addWidget(self.d_refs)

        acts = QHBoxLayout()
        self.btn_send_market = QPushButton('📈 送行情页')
        self.btn_send_backtest = QPushButton('📐 送回测页（M1）')
        self.btn_send_scan = QPushButton('🌐 送扫描页（M2/M3）')
        for b in (self.btn_send_market, self.btn_send_backtest, self.btn_send_scan):
            b.setStyleSheet(OUTLINE_QSS)
            acts.addWidget(b)
        acts.addStretch()
        self.btn_copy = QPushButton('⧉ 复制一份')
        self.btn_copy.setStyleSheet(FLAT_QSS)
        self.btn_delete = QPushButton('🗑 删除')
        self.btn_delete.setStyleSheet(FLAT_QSS)
        acts.addWidget(self.btn_copy)
        acts.addWidget(self.btn_delete)
        body.addLayout(acts)
        hint = QLabel('「送 ↗」= 切到对应页并载入该函数（回填函数段与参数）；'
                      '跑图 / 跑回测 / 跑扫描都在那边完成 —— 总库只管资产，不管运行。')
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:11.5px; color:#8A94A6;")
        body.addWidget(hint)

        outer.addWidget(card)
        return page

    def _build_editor(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName('HubPanel')
        body = QVBoxLayout(card)
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel('编辑函数')
        title.setStyleSheet("font-size:15px; font-weight:700; color:#20242C;")
        head.addWidget(title)
        head.addStretch()
        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.setStyleSheet(OUTLINE_QSS)
        head.addWidget(self.btn_cancel)
        body.addLayout(head)

        self.editor = FormulaAssetEditor()
        body.addWidget(self.editor, 1)

        acts = QHBoxLayout()
        acts.addStretch()
        self.btn_save = QPushButton('💾 保存到函数库')
        self.btn_save.setStyleSheet(FLAT_QSS)
        acts.addWidget(self.btn_save)
        body.addLayout(acts)
        outer.addWidget(card)
        return page

    @staticmethod
    def _sep() -> QFrame:
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#F2F5F9;")
        return line


def build_segment_card(index: int, text: str, target_label: str) -> QFrame:
    """详情里的一段 = 头（#序号 + 窗格标签）+ 等宽代码块（只读展示）。"""
    card = QFrame()
    card.setObjectName('HubSeg')
    card.setStyleSheet("QFrame#HubSeg { border:1px solid #F2F5F9; border-radius:10px; }")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(1, 1, 1, 1)
    lay.setSpacing(0)
    head = QLabel(f"　#{index + 1}　{target_label}")
    head.setStyleSheet("font-size:11.5px; color:#8A94A6; padding:4px 8px;"
                       " background:#F7F9FC; border-top-left-radius:10px;"
                       " border-top-right-radius:10px;")
    lay.addWidget(head)
    code = QLabel(text)
    code.setWordWrap(True)
    code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    code.setStyleSheet("QLabel { " + mono_font_css() + " font-size:12.3px;"
                       " padding:8px 12px; background:#FBFCFE; }")
    lay.addWidget(code)
    return card
