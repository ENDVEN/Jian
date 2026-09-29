# ui/widgets/hub_float_fn.py
"""浮窗的「ƒ 函数」区（★1.61 / §7-B16 · H6 · 设计稿 = `design/1.60-formula-hub/b-全局浮窗`）。

【形态】照设计稿 B：**列表 → 详情 → 紧凑编辑** 三态单列切换（浮窗窄，不分栏）。

【与总库 A 页是**同一个库**，不是第二套】（用户要求：样式统一，用户才知道背后是一回事）
  · 列表行 = `hub_layout.build_asset_row`（与 A 页**同一张脸**）；
  · 编辑器 = `hub_editor.FormulaAssetEditor`（**同一个编辑器**，不是另写一份表单）；
  · 保存落库 = `hub_flow.save_editor_asset()`；删除确认 = `hub_flow.confirm_and_delete_asset()`；
  · 过滤/排序 = `hub_assets.query()`；引用数 = `hub_assets.ref_map()`（**一次读盘**）。
  ⇒ 浮窗是"随手存 / 随手取"的入口，A 页是"坐下来整理"的管理台 —— 两者不会各说各话。

【红线①】本区没有任何"运行"入口：载入之后跑图 / 跑回测 / 跑扫描都在功能页完成。
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from data import hub_assets
from data.formula_store import SOURCE_LABELS, get_formula_store
from data.hub_migration import ensure_hub_migration
from ui.widgets.custom_widgets import FLAT_QSS, NoWheelComboBox, OUTLINE_QSS
from ui.widgets.hub_editor import FormulaAssetEditor
from ui.widgets.hub_flow import (TARGET_LABELS, confirm_and_delete_asset,
                                 save_editor_asset)
from ui.widgets.hub_layout import build_asset_row, build_segment_card

_SRC_CHOICES = (('all', '全部来源'), ('market', '行情页'), ('backtest', '回测页'),
                ('scan', '扫描页'), ('hub', '总库'))

_LIST, _DETAIL, _EDIT = 0, 1, 2


class FloatFunctionPane(QWidget):
    """「ƒ 函数」区：列表 ⇄ 详情 ⇄ 紧凑编辑。"""

    sig_load = pyqtSignal(dict)      # ⤓ 载入到本页（路由在主窗口）
    sig_open_hub = pyqtSignal()      # ✏ 去总库编辑（切到 A 页并选中）
    sig_say = pyqtSignal(str)        # 一行回执（由浮层壳显示）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_id = ''
        self._refs: dict = {}
        # 「💾 存当前函数」带过来的草稿来源（新建资产时用它，别把"行情页存的"记成"总库新建"）
        self._draft_source = 'hub'
        # 由浮层壳注入：`() -> 当前页的函数草稿 | None`（「💾 存当前函数」用）
        self.draft_provider = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_list())
        self.stack.addWidget(self._build_detail())
        self.stack.addWidget(self._build_edit())
        root.addWidget(self.stack, 1)

        # ---------------- 接线 ----------------
        self.search.textChanged.connect(self._on_filter)
        self.cmb_src.currentIndexChanged.connect(self._on_filter)
        self.btn_new.clicked.connect(self.begin_new)
        self.btn_save_current.clicked.connect(self._on_save_current)
        self.btn_back.clicked.connect(self.show_list)
        self.btn_edit.clicked.connect(self.begin_edit)
        self.btn_load.clicked.connect(self._on_load)
        self.btn_del.clicked.connect(self.delete_selected)
        self.btn_back2.clicked.connect(self.show_detail)
        self.btn_check.clicked.connect(self._on_check)
        self.btn_save.clicked.connect(self._on_save)
        self.refresh()

    # ==========================================
    # 装配
    # ==========================================
    def _build_list(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索名称 / 参数 / 函数文本…')
        lay.addWidget(self.search)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.cmb_src = NoWheelComboBox()
        for value, label in _SRC_CHOICES:
            self.cmb_src.addItem(label, value)
        row.addWidget(self.cmb_src, 1)
        self.btn_new = QPushButton('＋ 新建')
        self.btn_new.setStyleSheet(FLAT_QSS)
        self.btn_new.setToolTip('在浮窗里新建一条函数（与总库页新建的是**同一份库**）')
        row.addWidget(self.btn_new)
        lay.addLayout(row)

        # ★ 用户口径：**页面写好的函数必须能就地存**（不能逼用户跑去总库重抄一遍）
        self.btn_save_current = QPushButton('💾 存当前函数')
        self.btn_save_current.setStyleSheet(FLAT_QSS)
        self.btn_save_current.setToolTip(
            '把**当前页面上正在编辑的函数**取过来预填进编辑器，确认后再「💾 保存」。\n'
            '这样在 M1 / M2·M3 / 行情页写好的函数不必跑去总库重抄一遍。')
        lay.addWidget(self.btn_save_current)

        host = QWidget()
        self.list_lay = QVBoxLayout(host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        self.lbl_count = QLabel('')
        self.lbl_count.setStyleSheet('font-size:11px; color:#8A94A6;')
        lay.addWidget(self.lbl_count)
        return page

    def _build_detail(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.btn_back = QPushButton('← 返回列表')
        self.btn_back.setStyleSheet(OUTLINE_QSS)
        top.addWidget(self.btn_back)
        top.addStretch()
        self.btn_edit = QPushButton('✏ 编辑')
        self.btn_edit.setStyleSheet(OUTLINE_QSS)
        self.btn_edit.setToolTip('在浮窗里直接改（用的是与总库页**同一个**编辑器）')
        top.addWidget(self.btn_edit)
        outer.addLayout(top)

        self.d_name = QLabel('—')
        self.d_name.setStyleSheet('font-size:13.5px; font-weight:700; color:#20242C;')
        self.d_name.setWordWrap(True)
        outer.addWidget(self.d_name)
        self.d_meta = QLabel('')
        self.d_meta.setStyleSheet('font-size:11.3px; color:#8A94A6;')
        self.d_meta.setWordWrap(True)
        outer.addWidget(self.d_meta)

        host = QWidget()
        self.d_segs_lay = QVBoxLayout(host)
        self.d_segs_lay.setContentsMargins(0, 0, 0, 0)
        self.d_segs_lay.setSpacing(5)
        segs_scroll = QScrollArea()
        segs_scroll.setWidgetResizable(True)
        segs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        segs_scroll.setWidget(host)
        outer.addWidget(segs_scroll, 1)

        acts = QHBoxLayout()
        acts.setSpacing(6)
        self.btn_load = QPushButton('⤓ 载入到本页')
        self.btn_load.setStyleSheet(FLAT_QSS)
        self.btn_load.setToolTip('把选中函数回填到当前页的函数区（**配置区一字不动**）；'
                                 '跑图 / 跑回测 / 跑扫描在功能页完成')
        acts.addWidget(self.btn_load)
        acts.addStretch()
        self.btn_del = QPushButton('🗑 删除')
        self.btn_del.setStyleSheet(FLAT_QSS)
        self.btn_del.setToolTip('删除这条函数（无引用要二次确认；有引用要键入「删除」）')
        acts.addWidget(self.btn_del)
        outer.addLayout(acts)
        return page

    def _build_edit(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.btn_back2 = QPushButton('← 返回详情')
        self.btn_back2.setStyleSheet(OUTLINE_QSS)
        top.addWidget(self.btn_back2)
        top.addStretch()
        self.btn_check = QPushButton('🔎 检测')
        self.btn_check.setStyleSheet(OUTLINE_QSS)
        top.addWidget(self.btn_check)
        self.btn_save = QPushButton('💾 保存')
        self.btn_save.setStyleSheet(FLAT_QSS)
        self.btn_save.setToolTip('存进函数库（同名即覆盖）—— 与总库页「💾 保存到函数库」同一套落库')
        top.addWidget(self.btn_save)
        outer.addLayout(top)

        self.editor = FormulaAssetEditor()      # **同一个编辑器**（不是第二套表单）
        outer.addWidget(self.editor, 1)
        return page

    # ==========================================
    # 状态切换
    # ==========================================
    def show_list(self) -> None:
        self.stack.setCurrentIndex(_LIST)

    def show_detail(self) -> None:
        self.stack.setCurrentIndex(_DETAIL)

    def show_edit(self) -> None:
        self.stack.setCurrentIndex(_EDIT)

    # ==========================================
    # 数据
    # ==========================================
    def store(self):
        return get_formula_store()

    def refresh(self, keep: str = None) -> None:
        """重建列表 + 详情（迁移兜底：幂等，已迁移 = 纯读）。"""
        ensure_hub_migration()
        self._refs = hub_assets.ref_map()          # 一次读盘（列表 + 详情共用）
        assets = hub_assets.query(self.store(), str(self.cmb_src.currentData() or 'all'),
                                  self.search.text(), 'used', self._refs)
        self._rebuild_list(assets)
        selected = keep or self._selected_id
        if selected not in {f['id'] for f in self.store().all()}:
            selected = assets[0]['id'] if assets else ''
        self._selected_id = selected
        self._render_detail()
        total = len(self.store().all())
        self.lbl_count.setText(f'共 {total} 个函数 · 显示 {len(assets)} 个')

    def _on_filter(self, *_a) -> None:
        self.refresh(keep=self._selected_id)

    def _rebuild_list(self, assets: list) -> None:
        lay = self.list_lay
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not assets:
            empty = QLabel('没有匹配的函数 —— 点「＋ 新建」，'
                           '或点「💾 存当前函数」把页面上写好的存进来。')
            empty.setWordWrap(True)
            empty.setStyleSheet('font-size:11.5px; color:#8A94A6;')
            lay.addWidget(empty)
        for asset in assets:
            refs = hub_assets.ref_counts(asset['id'], self._refs)
            lay.addWidget(build_asset_row(asset, len(refs['m1']) + len(refs['m2m3']),
                                          self.select, asset['id'] == self._selected_id))
        lay.addStretch()

    def select(self, asset_id: str) -> None:
        self._selected_id = asset_id
        self.refresh(keep=asset_id)

    def selected_id(self) -> str:
        return self._selected_id

    def _render_detail(self) -> None:
        asset = self.store().get(self._selected_id)
        while self.d_segs_lay.count():
            item = self.d_segs_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if asset is None:
            self.d_name.setText('还没有选中任何函数')
            self.d_meta.setText('点上方列表挑一条；或点「＋ 新建」/「💾 存当前函数」。')
            self.btn_load.setEnabled(False)
            self.btn_edit.setEnabled(False)
            self.btn_del.setEnabled(False)
            return
        self.btn_load.setEnabled(True)
        self.btn_edit.setEnabled(True)
        self.btn_del.setEnabled(True)
        segs = asset.get('segments') or []
        self.d_name.setText(str(asset.get('name') or '未命名'))
        self.d_meta.setText(
            f"{SOURCE_LABELS.get(asset.get('source'), '—')} · {len(segs)} 段 · "
            f"参数：{asset.get('params_text') or '—'} · "
            f"最近使用：{asset.get('used_at') or '—（从未载入）'}")
        for i, seg in enumerate(segs):
            target = str(seg.get('target') or 'main')
            self.d_segs_lay.addWidget(build_segment_card(
                i, str(seg.get('text') or ''), TARGET_LABELS.get(target, target)))
        self.d_segs_lay.addStretch()

    # ==========================================
    # 新建 / 编辑 / 保存
    # ==========================================
    def begin_new(self) -> None:
        """＋ 新建：空表单（给一行出厂示例）。"""
        self._selected_id = ''
        self.editor.new_asset()
        self.show_edit()

    def begin_save_current(self, draft: dict) -> None:
        """把**当前页的函数草稿**预填进编辑器（「💾 存当前函数」的落点）。

        ⚠ 只预填、不落库 —— 用户还要点「💾 保存」才真正入库（防手残，§10-10）。
        """
        segs = [s for s in (draft.get('segments') or []) if str(s.get('text') or '').strip()]
        self._selected_id = ''
        self._draft_source = str(draft.get('source') or 'hub')
        # 走编辑器自己的预填口（**不改私有字段**）—— 逐段窗格照原样带过去
        # （行情页草稿是有 `sub1`/`main` 之分的，不能压平）。
        self.editor.load_segments(str(draft.get('name_hint') or ''), segs,
                                  str(draft.get('params_text') or ''))
        self.show_edit()

    def begin_edit(self) -> None:
        """✏ 编辑：把选中资产填进**同一个**编辑器。"""
        asset = self.store().get(self._selected_id)
        if asset is None:
            return
        self.editor.load_asset(asset)
        self.show_edit()

    def _on_save_current(self) -> None:
        draft = self.draft_provider() if callable(self.draft_provider) else None
        if not draft or not [s for s in (draft.get('segments') or [])
                             if str(s.get('text') or '').strip()]:
            self.sig_say.emit('⚠ 当前页没有可保存的函数 —— 先在页面上写好函数，'
                              '或切到行情 / 回测 / 扫描页')
            return
        self.begin_save_current(draft)
        self.sig_say.emit('已把当前页的函数取过来 —— 起个名字后点「💾 保存」')

    def _on_check(self) -> None:
        state, msg = self.editor.check()
        self.editor.show_check(state, msg)

    def _on_save(self) -> None:
        saved, note = save_editor_asset(self.store(), self.editor, self._draft_source)
        if saved is None:
            self.sig_say.emit(note)
            return
        self._selected_id = saved['id']
        self._draft_source = 'hub'          # 存完了：下一次新建默认按"总库"记来源
        self.show_detail()
        self.refresh(keep=saved['id'])
        self.sig_say.emit(f'✅ 已保存到函数库「{saved["name"]}」{note}')

    # ==========================================
    # 载入 / 删除 / 去总库
    # ==========================================
    def _on_load(self) -> None:
        asset = self.store().get(self._selected_id)
        if asset is not None:
            self.sig_load.emit(asset)

    def delete_selected(self) -> None:
        if confirm_and_delete_asset(self, self.store(), self._selected_id, self.sig_say.emit):
            self._selected_id = ''
            self.show_list()
            self.refresh()
