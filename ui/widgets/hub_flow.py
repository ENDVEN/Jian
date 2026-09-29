# ui/widgets/hub_flow.py
"""ƒ 函数总库的**行为层**（★1.61 / §7-B16 · H2；约定同 scan_flow：状态在页面，行为在这）。

【红线（方案书 §1）】① 总库只管资产不管运行 —— "送 ↗"只切页+回填，绝不触发运行；
  ② 资产删除分级（§10-10）：无引用 = 红色二次确认；有引用 = 键入「删除」+ 引用清单；
  ③ 编辑落点唯一 —— 保存走 `formula_store.upsert`（同名覆盖 = 用户直觉），保存前先过真引擎。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QInputDialog, QLabel, QMessageBox

from data import hub_assets
from data.formula_store import SOURCE_LABELS, get_formula_store
from data.hub_migration import ensure_hub_migration
from ui.dialogs.formula_overlay import TARGET_CHOICES
from ui.widgets.hub_layout import HubItem, build_asset_row, build_segment_card

_SRC_FILTER = {  # 来源筛选值 → (资产 source 值, 空态文案)
    'all': None, 'market': 'market', 'backtest': 'backtest', 'scan': 'scan', 'hub': 'hub',
}


def save_editor_asset(store, editor, default_source: str = 'hub') -> tuple[dict | None, str]:
    """**编辑器 → 资产**（唯一实现：总库 A 页与浮窗共用）。

    【为什么必须是函数而不是各写一遍】"先过真引擎、err 拦下、逐段窗格、同名覆盖保留来源"
    这几条一旦在浮窗里被写成第二份，两边就会漂（§11.5-11）。

    :param default_source: **新建**资产的来源（覆盖已有资产时一律保留它原来的来源）。
        浮窗「💾 存当前函数」会把**当前页**的来源带进来（行情页=market / M1=backtest / M2M3=scan），
        否则"在行情页存的公式"会被记成"总库新建"，来源筛选里就找不到了。
    :return: `(资产, 一行补充说明)`；失败 = `(None, 给人看的原因)`
    """
    payload = editor.to_payload()
    if payload is None:
        return None, '⚠ 名称和函数段都不能是空的'
    state, msg = editor.check()
    editor.show_check(state, msg)
    if state == 'err':
        return None, '⚠ 语法未通过 —— 先看检测结果'
    existing = store.get_by_name(payload['name'])
    targets = list(payload['targets'])
    # ⚠ **逐段**带窗格（由编辑器给出）—— 全塞同一个 target 会把行情页配方的
    #   `sub1`/`main` 分段压成同一个（静默丢数据，§11.5-110）。
    segments = [{'text': t, 'target': g} for t, g in zip(payload['texts'], targets)]
    saved = store.upsert({'name': payload['name'], 'segments': segments,
                          'params_text': payload['params_text'],
                          'source': (existing.get('source') if existing is not None
                                     else (default_source or 'hub'))})
    note = ''
    if len(set(targets)) > 1:
        note = '；逐段窗格：' + ' / '.join(TARGET_LABELS.get(g, g) for g in targets)
    return saved, note


TARGET_LABELS = {value: label for label, value in TARGET_CHOICES}


def confirm_and_delete_asset(parent, store, asset_id: str, say) -> bool:
    """带**分级确认**的删除（§10-10）：无引用 = 二次确认；有引用 = 键入「删除」+ 列引用清单。

    **唯一实现** —— 总库 A 页与浮窗都调它。两套确认 = 迟早有一处忘了要"键入删除"，
    而那正是防手残的最后一道闸。
    :return: 是否真的删掉了
    """
    asset = store.get(asset_id)
    if asset is None:
        return False
    refs = hub_assets.ref_counts(asset_id)
    m1, m2m3 = refs['m1'], refs['m2m3']
    if m1 or m2m3:
        lines = (['M1 策略 ' + '、'.join(f'「{x}」' for x in m1)] if m1 else []) \
              + (['M2/M3 方案 ' + '、'.join(f'「{x}」' for x in m2m3)] if m2m3 else [])
        typed, ok = QInputDialog.getText(
            parent, '删除被引用的函数',
            f"⚠ 「{asset.get('name')}」正被 {' 和 '.join(lines)} 引用。\n\n"
            "删除后这些方案仍用各自保存时的旧版函数（不受影响），"
            "但会失去与总库的关联。\n\n请键入「删除」确认：")
        if not ok or (typed or '').strip() != '删除':
            say('已取消删除')
            return False
    else:
        reply = QMessageBox.question(
            parent, '删除函数',
            f"确定删除「{asset.get('name')}」？\n它没有被任何方案引用，删除后不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return False
    removed, _refs = hub_assets.delete_asset(store, asset_id)
    say('✅ 已删除' if removed else '⚠ 删除失败（见日志）')
    return removed


class HubFlow:
    """总库行为：刷新 / 选中 / 编辑 / 保存 / 删除 / 复制 / 全库体检 / 送 ↗。"""

    def __init__(self, page):
        self.p = page
        self._selected_id = ''
        self._editing = False
        # ★1.61 / §7-B16：引用表（一次读盘的结果，见 `hub_assets.ref_map`）。
        #   列表每条都要引用数 ⇒ 绝不能在循环里逐条 `ref_counts()`（那是每敲一个字读盘几十次）。
        self._refs: dict = {}

    # ---------------- 数据 ----------------
    def store(self):
        return get_formula_store()

    def _assets(self) -> list[dict]:
        """按筛选 + 排序给出当前应显示的资产（**口径在 `hub_assets.query`，与浮窗共用**）。"""
        return hub_assets.query(self.store(), _SRC_FILTER.get(self.p.filter_src, None),
                                self.p.filter_text, self.p.sort_key, self._refs)

    # ---------------- 列表 / 详情 ----------------
    def refresh(self, keep: str = None) -> None:
        """重建列表 + 详情（迁移兜底：幂等，已迁移 = 纯读）。"""
        ensure_hub_migration()
        self._refs = hub_assets.ref_map()      # 一次读盘（列表 + 排序 + 详情共用这一张表）
        assets = self._assets()
        self._rebuild_list(assets)
        selected = keep or self._selected_id
        if selected not in {f['id'] for f in self.store().all()}:
            selected = assets[0]['id'] if assets else ''
        self._selected_id = selected
        self._render_detail()
        total = len(self.store().all())
        self.p.lbl_stat.setText(f'共 {total} 个函数 · 显示 {len(assets)} 个')

    def _rebuild_list(self, assets: list[dict]) -> None:
        lay = self.p.list_lay
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not assets:
            empty = QLabel('没有匹配的函数 —— 点「＋ 新建函数」，或去行情/回测页把现成的存进来。')
            empty.setWordWrap(True)
            empty.setStyleSheet("font-size:12px; color:#8A94A6; padding:6px 2px;")
            lay.addWidget(empty)
        for asset in assets:
            lay.addWidget(self._build_item(asset))
        lay.addStretch()

    def _build_item(self, asset: dict) -> HubItem:
        """一行资产 —— **画法在 `hub_layout.build_asset_row`**（与浮窗列表同一张脸）。"""
        refs = hub_assets.ref_counts(asset['id'], self._refs)
        n_refs = len(refs['m1']) + len(refs['m2m3'])
        return build_asset_row(asset, n_refs, self.select, asset['id'] == self._selected_id)

    def select(self, asset_id: str) -> None:
        self._selected_id = asset_id
        self._editing = False
        self.p.show_detail()
        self.refresh(keep=asset_id)

    def _render_detail(self) -> None:
        asset = self.store().get(self._selected_id)
        if asset is None:
            self.p.d_name.setText('—')
            self.p.d_meta.setText('还没有任何函数 —— 点左侧「＋ 新建函数」。')
            self.p.d_segs_clear()
            self.p.d_refs.setText('')
            self.p.d_src.setText('')
            self.p.d_state.setText('')
            return
        self.p.d_name.setText(str(asset.get('name') or '未命名'))
        self.p.d_src.setText(f"<span style='background:#EEF1F6; color:#616B7A;"
                             f"border-radius:8px; padding:1px 8px;'>"
                             f"{SOURCE_LABELS.get(asset.get('source'), '—')}</span>")
        self.p.d_state.setText('')
        segs = asset.get('segments') or []
        self.p.d_meta.setText(
            f"{len(segs)} 段 · 参数：{asset.get('params_text') or '—'} · "
            f"最近使用：{asset.get('used_at') or '—（从未载入）'} · 更新于：{asset.get('updated_at') or '—'}")
        self.p.d_segs_clear()
        for i, seg in enumerate(segs):
            self.p.d_segs_add(build_segment_card(
                i, str(seg.get('text') or ''),
                self.p.target_label(str(seg.get('target') or 'main'))))
        refs = hub_assets.ref_counts(asset['id'], self._refs)
        m1, m2m3 = refs['m1'], refs['m2m3']
        if m1 or m2m3:
            lines = (['M1 策略：' + '、'.join(f'「{x}」' for x in m1)] if m1 else []) \
                  + (['M2/M3 方案：' + '、'.join(f'「{x}」' for x in m2m3)] if m2m3 else [])
            self.p.d_refs.setText('被引用（只读；删除前会先提示）—— ' + '；'.join(lines))
        else:
            self.p.d_refs.setText('被引用（只读）：暂无 —— 独立的自由函数，删除只需二次确认。')

    # ---------------- 编辑 / 保存 ----------------
    def new_asset(self) -> None:
        self._selected_id = ''
        self._editing = True
        self.p.editor.new_asset()
        self.p.show_editor()

    def edit(self) -> None:
        asset = self.store().get(self._selected_id)
        if asset is None:
            return
        self._editing = True
        self.p.editor.load_asset(asset)
        self.p.show_editor()

    def cancel_edit(self) -> None:
        self._editing = False
        self.p.show_detail()
        self.refresh(keep=self._selected_id)

    def save(self) -> None:
        """保存（同名覆盖 = 用户直觉）；**先过真引擎**，err 拦下、warn 放行并点名。

        ⚠ 落库实现只有一份 = 模块级 `save_editor_asset()`（浮窗的「💾 保存」也调它）。
        """
        saved, note = save_editor_asset(self.store(), self.p.editor)
        if saved is None:
            self.p.say(note)
            return
        self._selected_id = saved['id']
        self._editing = False
        self.p.show_detail()
        self.refresh(keep=saved['id'])          # 先刷新（顺带重算 `_refs`），再取引用数
        refs = hub_assets.ref_counts(saved['id'], self._refs)
        n_refs = len(refs['m1']) + len(refs['m2m3'])
        extra = (f'；{n_refs} 个方案引用它，仍用各自保存时的旧版（载入时会提示更新）'
                 if n_refs else '')
        self.p.say(f'✅ 已保存到函数库「{saved["name"]}」{extra}{note}')

    # ---------------- 删除 / 复制 / 体检 ----------------
    def delete(self) -> None:
        """删除（分级确认在 `confirm_and_delete_asset`，与浮窗共用）。"""
        if confirm_and_delete_asset(self.p, self.store(), self._selected_id, self.p.say):
            self._selected_id = ''
            self.refresh()

    def copy(self) -> None:
        import copy as _copy
        asset = self.store().get(self._selected_id)
        if asset is None:
            return
        clone = _copy.deepcopy(asset)
        clone['id'] = ''
        clone['name'] = f"{asset.get('name')} 副本"
        clone['used_at'] = ''
        saved = self.store().upsert(clone)
        self._selected_id = saved['id']
        self.refresh(keep=saved['id'])
        self.p.say(f'✅ 已复制为「{saved["name"]}」')

    def check_all(self) -> None:
        """全库体检：逐条跑真引擎（纯计算毫秒级；实测变慢再议异步 —— 不许顺手加线程）。"""
        from core.formula.program import parse_program
        store = self.store()
        n_err = n_warn = 0
        for asset in store.all():
            text = '\n'.join(hub_assets.asset_texts(asset))
            state = ''
            if not text.strip():
                state = 'err'
            else:
                try:
                    program = parse_program(text)
                    state = 'warn' if program.unsupported_count else 'ok'
                except Exception:                       # noqa: BLE001 —— 编译失败 = err
                    state = 'err'
            asset['syntax_state'] = state
            n_err += state == 'err'
            n_warn += state == 'warn'
        store.save()
        self.refresh(keep=self._selected_id)
        self.p.say(f'🩺 全库体检完成：{len(store.all())} 个函数，'
                   f'{n_err} 个语法错误、{n_warn} 个非阻断提示'
                   + ('—— 列表已标 ✗/⚠' if (n_err or n_warn) else ''))

    # ---------------- 送 ↗（只切页+回填，绝不运行）----------------
    def send(self, target: str) -> None:
        asset = self.store().get(self._selected_id)
        if asset is None:
            return
        n = self.p.main_win.send_asset_to_page(asset, target)
        self.p.say(f'✅ 已切到{self.p.page_label(target)}并载入「{asset.get("name")}」（{n} 段）'
                   if n else '⚠ 目标页不在可载入状态 —— 先切到行情 / 回测 / 扫描页')
