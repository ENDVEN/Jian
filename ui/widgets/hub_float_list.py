# ui/widgets/hub_float_list.py
"""浮窗里的**统一列表**：本页方案 + 函数资产（★1.61 / §7-B16 · H7「用户实测后重做交互」）。

【为什么改（用户实测原话大意）】
  ① "库里面的函数在对应页面**双击**根本没有办法点进对应的函数页面" —— 旧版把列表行做成了
     "只选中"，而「⤓ 载入到本页」住在**详情页**，从列表**没有入口**进去（`show_detail()` 只有
     "存完"和"返回"两个触发点）⇒ 整个浮窗对用户就是**死胡同**：M1/M2·M3 里点了半天，
     页面纹丝不动（摘要条永远停在"完成检测并配置买卖条件后即可运行"）。
  ② "ƒ 函数 / 📚 本页方案 两个区**多此一举**" —— 在哪个页面打开，就列哪个页面该看到的
     方案与函数 ⇒ 现在**并成一个列表**（方案行带「📚 方案」徽标，函数行照旧带来源），
     不再分区、不再切换。

【交互就三条（其余都是它的投影）】
  · **单击** = 选中（下方三个按钮作用于它）；
  · **双击** = **用起来**：函数 ⇒ 回填当前页的函数区；方案 ⇒ 整体还原进当前页；
  · 「⤓ 载入到本页」= 与双击**同一个动作**（不习惯双击的人也走得到）。

【红线】① 本区没有任何"运行"入口（载入之后跑图 / 跑回测 / 跑扫描都在功能页完成）；
  ② 载入**只认内联快照**：函数只回填函数段 + 参数，条件 / 风控 / 阈值 / 范围**一字不动**。
【与总库 A 页是**同一个库**】列表行 / 编辑器 / 删除确认 / 保存落库全部复用同一批实现
  （`hub_layout` / `hub_editor` / `hub_flow`）—— 浮窗是"随手存 / 随手取"，A 页是"坐下来整理"。
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from data import hub_assets
from data.formula_store import get_formula_store
from data.hub_migration import ensure_hub_migration
from ui.widgets.custom_widgets import FLAT_QSS, NoWheelComboBox, OUTLINE_QSS
from ui.widgets.hub_editor import FormulaAssetEditor
from ui.widgets.hub_flow import (TARGET_LABELS, confirm_and_delete_asset,
                                 save_editor_asset)
from ui.widgets.hub_layout import build_asset_row, build_plain_row, build_segment_card

_SRC_CHOICES = (('all', '全部来源'), ('market', '行情页'), ('backtest', '回测页'),
                ('scan', '扫描页'), ('hub', '总库'))

_LIST, _EDIT = 0, 1
_FN, _PLAN = 'f', 'p'          # 行 id 前缀 —— 两类同处一个列表，**绝不能撞号**
FN_KIND = _FN                  # 对外：主窗口判"选中的是不是函数行"（`_open_hub_page`）
PLAN_KIND = _PLAN
PLAN_BADGE = '📚 方案'


class FloatHubList(QWidget):
    """浮窗内容 = **一个列表**（本页方案 + 函数资产）+ 一个紧凑编辑器（同一套零件）。"""

    sig_load = pyqtSignal(dict)      # ⤓ 载入到本页（函数资产；路由在主窗口）
    sig_open_hub = pyqtSignal()      # ✏ 去总库（A 页）编辑
    sig_say = pyqtSignal(str)        # 一行回执（由浮层壳显示，**只此一处**）

    # 由浮层壳注入的两个取口（"当前页是谁"只有主窗口知道）
    draft_provider = None            # () -> 当前页函数草稿 | None
    plan_provider = None             # () -> 当前页方案 API | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sel_row = ''
        self._rows: dict[str, dict] = {}          # 行 id -> {'kind','id','name'}
        self._row_widgets: dict[str, object] = {}
        self._refs: dict = {}
        # 「💾 存当前函数」带过来的草稿来源（新建时用它，别把"行情页存的"记成"总库新建"）
        self._draft_source = 'hub'

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_list())
        self.stack.addWidget(self._build_edit())
        root.addWidget(self.stack, 1)

        # ---------------- 接线 ----------------
        self.search.textChanged.connect(self._on_filter)
        self.cmb_src.currentIndexChanged.connect(self._on_filter)
        self.btn_new.clicked.connect(self.begin_new)
        self.btn_save_fn.clicked.connect(self._on_save_current)
        self.btn_save_plan.clicked.connect(self._on_save_plan)
        self.btn_load.clicked.connect(self._on_load)
        self.btn_edit.clicked.connect(self.begin_edit)
        self.btn_del.clicked.connect(self._on_delete)
        self.btn_back2.clicked.connect(self.show_list)
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
        self.cmb_src.setToolTip('只筛**函数资产**的来源；本页方案恒列在最前（不受它影响）')
        row.addWidget(self.cmb_src, 1)
        self.btn_new = QPushButton('＋ 新建函数')
        self.btn_new.setStyleSheet(FLAT_QSS)
        self.btn_new.setToolTip('在浮窗里新建一条函数（与总库页新建的是**同一份库**）')
        row.addWidget(self.btn_new)
        lay.addLayout(row)

        # 存放动作一行 —— ⚠ 「存为方案」**按页面能力显隐**（行情页没有方案库就不显示，
        #   不是禁用后摆着让人点不着）。
        store_row = QHBoxLayout()
        store_row.setSpacing(6)
        self.btn_save_fn = QPushButton('💾 存当前函数')
        self.btn_save_fn.setStyleSheet(FLAT_QSS)
        self.btn_save_fn.setToolTip(
            '把**当前页面上正在编辑的函数**取过来预填进编辑器，确认后再「💾 保存」。\n'
            '这样在 M1 / M2·M3 / 行情页写好的函数不必跑去总库重抄一遍。')
        store_row.addWidget(self.btn_save_fn)
        self.btn_save_plan = QPushButton('📚 存为方案')
        self.btn_save_plan.setStyleSheet(FLAT_QSS)
        self.btn_save_plan.setToolTip(
            '把当前页的**整套配置**（函数 + 条件 / 阈值 / 范围 / 区间）存成命名方案；'
            '下次在同一个列表里选中它、双击即整体还原。')
        store_row.addWidget(self.btn_save_plan)
        store_row.addStretch()
        lay.addLayout(store_row)

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

        acts = QHBoxLayout()
        acts.setSpacing(6)
        self.btn_load = QPushButton('⤓ 载入到本页')
        self.btn_load.setStyleSheet(FLAT_QSS)
        self.btn_load.setToolTip(
            '把选中的这条**用起来**（与双击列表行是同一个动作）：\n'
            '· 函数 ⇒ 回填当前页的函数段与参数（条件 / 风控 / 阈值 / 范围一字不动）；\n'
            '· 方案 ⇒ 把整套配置整体还原进当前页。')
        acts.addWidget(self.btn_load)
        acts.addStretch()
        self.btn_edit = QPushButton('✏ 编辑函数')
        self.btn_edit.setStyleSheet(FLAT_QSS)
        self.btn_edit.setToolTip('进这条函数的编辑面（与总库页**同一个编辑器**，不是第二套表单）')
        acts.addWidget(self.btn_edit)
        self.btn_del = QPushButton('🗑 删除')
        self.btn_del.setStyleSheet(FLAT_QSS)
        self.btn_del.setToolTip('删除选中这条：函数按引用分级确认；方案二次确认')
        acts.addWidget(self.btn_del)
        lay.addLayout(acts)
        return page

    def _build_edit(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.btn_back2 = QPushButton('← 返回列表')
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

    def show_edit(self) -> None:
        self.stack.setCurrentIndex(_EDIT)

    # ==========================================
    # 数据 / 渲染
    # ==========================================
    def store(self):
        return get_formula_store()

    def _plan_api(self):
        return self.plan_provider() if callable(self.plan_provider) else None

    def refresh(self, keep: str = None) -> None:
        """重建列表（迁移兜底：幂等，已迁移 = 纯读）。"""
        ensure_hub_migration()
        self._refs = hub_assets.ref_map()          # 一次读盘（列表 + 详情共用）
        assets = hub_assets.query(self.store(), str(self.cmb_src.currentData() or 'all'),
                                  self.search.text(), 'used', self._refs)
        api = self._plan_api()
        plans: list = []
        if api:
            plans_fn = api.get('plans')
            plans = list(plans_fn() if callable(plans_fn) else [])
        self._rebuild_list(plans, assets, api)
        want = self._norm(keep if keep is not None else self._sel_row)
        if want not in self._rows:
            want = next(iter(self._rows), '')      # 列表顺序 = 本页方案在前、函数资产在后
        self._sel_row = want
        self._apply_selection()
        self.btn_save_plan.setVisible(api is not None)
        total = len(self.store().all())
        self.lbl_count.setText(
            f'函数 {total} 个 · 显示 {len(assets)} 个'
            + (f' · 本页方案 {len(plans)} 条' if api else ' · 本页没有方案库（只有函数可载入）'))

    def _norm(self, row_id) -> str:
        """把**三种写法**归一成行 id：带前缀 / 裸资产 id / 裸方案 id（外部只认裸 id）。"""
        rid = str(row_id or '')
        if rid in self._rows:
            return rid
        for prefix in (_FN, _PLAN):
            if f'{prefix}:{rid}' in self._rows:
                return f'{prefix}:{rid}'
        return rid

    def _on_filter(self, *_a) -> None:
        self.refresh(keep=self._sel_row)

    def _rebuild_list(self, plans: list, assets: list, api) -> None:
        lay = self.list_lay
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows = {}
        self._row_widgets = {}
        label_of = api.get('plan_label') if api else None
        if api:
            for plan in plans:
                rid = f'{_PLAN}:{plan.get("id")}'
                name = str(plan.get('name') or '未命名')
                meta = label_of(plan) if callable(label_of) else ''
                self._rows[rid] = {'kind': _PLAN, 'id': str(plan.get('id')), 'name': name}
                self._row_widgets[rid] = build_plain_row(
                    rid, name, meta, self._on_row_pick, False,
                    badge=PLAN_BADGE, on_double=self._on_row_double)
                lay.addWidget(self._row_widgets[rid])
        for asset in assets:
            rid = f'{_FN}:{asset["id"]}'
            refs = hub_assets.ref_counts(asset['id'], self._refs)
            self._rows[rid] = {'kind': _FN, 'id': asset['id'],
                               'name': str(asset.get('name') or '')}
            self._row_widgets[rid] = build_asset_row(
                asset, len(refs['m1']) + len(refs['m2m3']), self._on_row_pick, False,
                on_double=self._on_row_double, row_id=rid)
            lay.addWidget(self._row_widgets[rid])
        if not self._rows:
            empty = QLabel('这里还没有可用的内容 —— 点「＋ 新建函数」，'
                           '或点「💾 存当前函数」把页面上写好的存进来。')
            empty.setWordWrap(True)
            empty.setStyleSheet('font-size:11.5px; color:#8A94A6;')
            lay.addWidget(empty)
        lay.addStretch()

    def _apply_selection(self) -> None:
        for rid, widget in self._row_widgets.items():
            widget.set_selected(rid == self._sel_row)
        row = self._rows.get(self._sel_row)
        is_fn = bool(row) and row['kind'] == _FN
        self.btn_load.setEnabled(bool(row))
        self.btn_edit.setEnabled(is_fn)          # 方案不是"一条函数"，编辑在页面上
        self.btn_del.setEnabled(bool(row))

    def select(self, row_id) -> None:
        """选中一行（容忍带前缀行 id / 裸 id —— 主窗口只存裸 id）。"""
        self._sel_row = self._norm(row_id)
        self._apply_selection()

    def selected_id(self) -> str:
        row = self._rows.get(self._sel_row)
        return str(row['id']) if row else ''

    def selected_kind(self) -> str:
        row = self._rows.get(self._sel_row)
        return str(row['kind']) if row else ''

    def _on_row_pick(self, row_id: str) -> None:
        self.select(row_id)

    def _on_row_double(self, row_id: str) -> None:
        """双击 = 用起来（**本浮窗存在的理由**：找到了就直接用到本页）。"""
        self.select(row_id)
        self._on_load()

    # ==========================================
    # 载入（双击 / 「⤓ 载入到本页」的唯一落点）
    # ==========================================
    def _on_load(self) -> None:
        row = self._rows.get(self._sel_row)
        if not row:
            self.sig_say.emit('⚠ 先在列表里选一条（或直接双击它）')
            return
        if row['kind'] == _FN:
            asset = self.store().get(row['id'])
            if asset is None:
                self.sig_say.emit('⚠ 这条函数已经不在库里了 —— 已刷新列表')
                self.refresh()
                return
            self.sig_load.emit(asset)             # 回执由主窗口写（它知道当前页落哪儿）
            return
        api = self._plan_api()
        if not api:
            return
        noun = str(api.get('noun') or '方案')
        ok = api['load'](str(row['id']))
        self.sig_say.emit(f'📚 已把{noun}「{row["name"]}」整体还原进本页' if ok
                          else f'⚠ 没能载入这个{noun}（可能已被删除）')
        self.refresh(keep=f'{_PLAN}:{row["id"]}')

    # ==========================================
    # 新建 / 编辑 / 保存
    # ==========================================
    def begin_new(self) -> None:
        """＋ 新建：空表单（给一行出厂示例）。"""
        self._sel_row = ''
        self.editor.new_asset()
        self.show_edit()

    def begin_save_current(self, draft: dict) -> None:
        """把**当前页的函数草稿**预填进编辑器（「💾 存当前函数」的落点）。

        ⚠ 只预填、不落库 —— 用户还要点「💾 保存」才真正入库（防手残，§10-10）。
        """
        segs = [s for s in (draft.get('segments') or []) if str(s.get('text') or '').strip()]
        self._sel_row = ''
        self._draft_source = str(draft.get('source') or 'hub')
        # 走编辑器自己的预填口（**不改私有字段**）—— 逐段窗格照原样带过去
        #   （行情页草稿是有 `sub1`/`main` 之分的，不能压平）。
        self.editor.load_segments(str(draft.get('name_hint') or ''), segs,
                                  str(draft.get('params_text') or ''))
        self.show_edit()

    def begin_edit(self) -> None:
        """✏ 编辑：把选中**函数**填进同一个编辑器。"""
        row = self._rows.get(self._sel_row)
        if not row:
            return
        if row['kind'] != _FN:
            self.sig_say.emit('⚠ 这是**本页方案**（整套配置）—— 要改就在页面上改，'
                              '或在列表中选一条函数再编辑')
            return
        asset = self.store().get(row['id'])
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

    def _on_save_plan(self) -> None:
        api = self._plan_api()
        if api:
            api['save']()                 # 名字输入 / 空内容提示都在桥接里（同一实现）
            self.refresh()

    def _on_check(self) -> None:
        state, msg = self.editor.check()
        self.editor.show_check(state, msg)

    def _on_save(self) -> None:
        saved, note = save_editor_asset(self.store(), self.editor, self._draft_source)
        if saved is None:
            self.sig_say.emit(note)
            return
        self._draft_source = 'hub'          # 存完了：下一次新建默认按"总库"记来源
        self.show_list()
        self._sel_row = f'{_FN}:{saved["id"]}'
        self.refresh(keep=self._sel_row)
        self.sig_say.emit(f'✅ 已保存到函数库「{saved["name"]}」{note}')

    # ==========================================
    # 删除
    # ==========================================
    def _on_delete(self) -> None:
        row = self._rows.get(self._sel_row)
        if not row:
            return
        if row['kind'] == _FN:
            if confirm_and_delete_asset(self, self.store(), row['id'], self.sig_say.emit):
                self._sel_row = ''
                self.refresh()
            return
        api = self._plan_api()
        if not api:
            return
        noun = str(api.get('noun') or '方案')
        # ⚠ 二次确认在桥接里（`delete_plan`）—— 闸门挂在**动作的唯一入口**上，不靠调用方自觉
        if api['delete'](str(row['id'])):
            self.sig_say.emit(f'✅ 已删除{noun}「{row["name"]}」')
            self._sel_row = ''
        else:
            self.sig_say.emit(f'⚠ 没删除{noun}（取消，或它已经不在了）')
        self.refresh()

    def delete_selected(self) -> None:
        self._on_delete()


__all__ = ['FloatHubList', 'PLAN_BADGE', 'TARGET_LABELS', 'build_segment_card']
