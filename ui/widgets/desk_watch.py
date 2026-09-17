# ui/widgets/desk_watch.py
"""★ 自选股（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6；v6.24 加分组 · §7-B8 R1/R2）。

【职责】自选清单的刷新 / 增删 / 移组 / 调序 / 双击切换 —— 只走 `WatchlistStore` 门面
（UI 不碰文件、不碰 SQL，§10-3）。

【v6.24 的新不变量：**"分组筛选"是"看"的状态，不是"存"的状态**】
  · `page.watch_group`（None = 全部）只决定"清单里显示哪些"；
  · 它是**页面状态**、不进存储 —— 存储里只回答"这只票属于哪一组"（§11.5-11 单一状态源）；
  · 分组胶囊与目标下拉**每次都从 store 重建**（不是增量改）⇒ "增删分组后胶囊不同步"
    这类 bug 在结构上就不可能发生。

【为什么"移出本组"与"从自选删除"是两件事】前者只改归类（票还在），后者才删记录。
  混成一个动作的后果是：用户想给票换个组，结果把它从自选里弄丢了。所以：
  · 清单下那个按钮**按上下文**在两者间切换（正在看真实分组 ⇒ 移出本组；看"全部" ⇒ 删除）；
  · 右键菜单**两条都给**，与按钮是同一套实现（不写第二份逻辑）。

【约定（与 1.22 拆 `backtest.py` 同款）】**状态留页面、行为搬模块**：
  · 页面持有 `watchlist`（store）、`watch_group`（当前筛选）、`lst_watch`、`current_symbol/current_name`
    与 `lbl_sync_status`（回执）；
  · 本模块只承载行为，读写一律走 `self.page.X` ⇒ 断言与主窗口看到的永远是同一份状态，
    不会出现"模块里存一份、页面上又存一份"。
线程/信号：`itemDoubleClicked` 连的是**页面的同名方法**（薄壳转发到这里），签名不变。
"""
import pandas as pd
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QInputDialog, QListWidgetItem, QMenu, QMessageBox

from data.sync_service import ADJUST_NONE, ADJUST_QFQ, zone_for_adjust
from data.watchlist_change import (ChangeSnapshot, baseline_date, direction_of,
                                   format_pct, group_summary)
from data.watchlist_store import DEFAULT_GROUP
from ui.dialogs.watchlist_picker import WatchlistPickerDialog
from ui.widgets.custom_widgets import AddChip, GroupChip
from ui.widgets.watch_row_delegate import ROLE_SYMBOL, set_change


class DeskWatch:
    """自选股行为（页面持有的"状态" + 本类提供的"行为"）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 小工具
    # ==========================================
    def _set_status(self, text: str) -> None:
        """回执统一写顶栏的 `lbl_sync_status` —— 别在各处自己找地方显示。"""
        self.page.lbl_sync_status.setText(text)

    def _group_is_real(self) -> bool:
        """当前是否正在看**某个真实分组**。

        "全部"与默认分组都不算："全部"是聚合视图；默认分组是所有解绑动作的**落点**，
        从它再往外挪无处可去（所以看默认分组时，那个按钮的含义是"从自选删除"）。
        """
        p = self.page
        return bool(p.watch_group) and p.watch_group != DEFAULT_GROUP

    def _resolve_keyword(self, keyword: str):
        """关键词 → (代码, 名称)。走主窗口门面取花名册（UI 不碰 DAO，§10-3）。"""
        p = self.page
        engine = getattr(p.main_win, "engine", None)
        if engine is None:
            return "", ""
        try:
            result = engine.search_symbol(keyword)
        except Exception as e:              # noqa: BLE001 —— 取数失败不该把整个页面崩掉
            print(f"自选快添加：查询失败 {e}")
            return "", ""
        if result is None or len(result) == 0:
            return "", ""
        row = result.iloc[0]
        return str(row["symbol"]), str(row.get("name", "") or "")

    # ==========================================
    # 组合当日涨跌（§7-B8 R3）—— 算法全在 data/watchlist_change（零 Qt、可单独验收）
    # ==========================================
    def _load_daily_for_change(self, symbol: str):
        """"这只票**今天真实涨跌**多少" ⇒ 固定读**前复权**日线。

        【为什么与顶部那个"复权"选择无关】顶部选择管的是"图上给你看哪一份"；
        而"今天涨跌多少"问的是**市场表现** —— 除权日不复权会凭空多出一个假跌
        （价格被除权砍掉一截），前复权才是经济真相。这两件事不该互相牵连。
        兜底：本地只有不复权数据时回落到不复权分区（否则整页都显示"没数据"）。
        """
        p = self.page
        for adjust in (ADJUST_QFQ, ADJUST_NONE):
            zone = zone_for_adjust(adjust)
            if p.data_lake.exists(zone, symbol):
                return p.data_lake.load_data(zone, symbol)
        return pd.DataFrame()

    def _change_snapshot(self) -> dict:
        """当前自选里每只票的当日涨跌（带 TTL 缓存 ⇒ 反复刷新是零 IO）。"""
        p = self.page
        if getattr(p, "watch_change", None) is None:
            p.watch_change = ChangeSnapshot(loader=self._load_daily_for_change)
        return p.watch_change.build([e["symbol"] for e in p.watchlist.entries_all()])

    def invalidate_change_cache(self) -> None:
        """数据变过（同步完成 / 切换复权）时清缓存 —— 否则会拿旧读数当"今天"。"""
        if getattr(self.page, "watch_change", None) is not None:
            self.page.watch_change.clear()

    def _missing_tooltip(self, summary) -> str:
        """⚠ 的说明 = **哪几只没算进去、为什么**（说不出原因的数字就是假口径）。"""
        p = self.page
        items = summary.get("missing") or []
        lines = [f"· {p.watchlist.display_name(symbol)}：{why}" for symbol, why in items[:5]]
        more = f"\n（还有 {len(items) - 5} 只，同上）" if len(items) > 5 else ""
        return (f"本组 {summary['total']} 只里有 {len(items)} 只**没算进去**"
                f"（不计入平均，绝不拿 0% 冲淡数字）：\n" + "\n".join(lines) + more)

    # ==========================================
    # 列表刷新 / 选中
    # ==========================================
    def _refresh_watchlist(self) -> None:
        """重画整页（清单 + 胶囊 + 卡头 + 目标下拉）—— **只有这一个入口**。

        单一入口的好处：不可能出现"清单刷新了、胶囊没刷新"这种半更新状态。
        """
        p = self.page
        if p.watch_group and not p.watchlist.has_group(p.watch_group):
            # 组被删了 / 被改名了 ⇒ 自动退回"全部"，**绝不留下悬空的筛选条件**
            # （悬空筛选 = 清单空白但用户不知道自己做错了什么）
            p.watch_group = None
        selected = self._selected_watch_symbol()
        # 行右侧的涨跌与胶囊共用**同一份快照**（不重算、不另取数 ⇒ 两处数字必然一致）
        snapshot = self._change_snapshot()
        p.lst_watch.clear()
        for entry in p.watchlist.entries_in(p.watch_group):
            item = QListWidgetItem(entry["name"] or entry["symbol"])
            item.setData(ROLE_SYMBOL, entry["symbol"])
            row = snapshot.get(entry["symbol"]) or {}
            # 算不出来就写 "—"：**没数据就说没数据**，绝不显示 0.00% 那种假数（§10-4）
            set_change(item, format_pct(row.get("pct")) or "—", direction_of(row.get("pct")))
            p.lst_watch.addItem(item)
        # 选中项还在清单里就保持选中（刷新不该把用户的选中弄丢）
        for row in range(p.lst_watch.count()):
            if p.lst_watch.item(row).data(ROLE_SYMBOL) == selected:
                p.lst_watch.setCurrentRow(row)
                break
        self._refresh_group_chips()
        self._refresh_watch_headers()

    def _refresh_group_chips(self) -> None:
        """重建分组胶囊 + 目标下拉（两者同源，一起刷新）。

        「全部」是**聚合视图**：它是 chip，但**不写进存储**（写进去就会变成一只
        永远算不出涨跌的假分组）。
        """
        p = self.page
        while p.watch_chip_lay.count():
            item = p.watch_chip_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        counts = p.watchlist.group_counts()
        chips = [GroupChip(None, "全部", count=p.watchlist.count())]
        for name in p.watchlist.groups():
            chips.append(GroupChip(name, name, count=counts.get(name, 0)))
        snapshot = self._change_snapshot()
        baseline = baseline_date(snapshot)
        p.card_watch_groups.setToolTip(
            f"组合涨跌的基准日（即「最近一天」）：{baseline or '—'}\n"
            "口径：组内每只票当日涨跌幅**等权平均**；某只票今天没数据时**不算它**（打 ⚠）。")
        for chip in chips:
            # 每个分组（含"全部"）都是一只"自建基金"：**等权平均 + 缺数据的票不算 + 打 ⚠**
            summary = group_summary(snapshot, p.watchlist.symbols_in(chip.key),
                                    baseline=baseline)
            if chip.key is None:
                # 「全部」是**聚合视图**：显示只数（与样板一致，也免得胶囊虚胖）
                chip.set_count(summary["total"])
                chip.set_value("")
            else:
                value = format_pct(summary["pct"])
                chip.set_value(value, direction_of(summary["pct"]))
                # 算不出涨跌（空组 / 一只都没数据）⇒ **退回显示只数**：
                # 胶囊上永远得有一点信息，不能是一片空白（样板没涵盖这个情形）
                chip.set_count(None if value else summary["total"])
            if summary["missing"]:
                chip.set_warn(self._missing_tooltip(summary))
            chip.set_selected(chip.key == p.watch_group)
            chip.sigPicked.connect(p.watch_group_selected)
        add_chip = AddChip()
        add_chip.sigClicked.connect(p.create_watch_group)
        for widget in (chips + [add_chip]):
            p.watch_chip_lay.addWidget(widget)
        # 重建完立刻按当前宽度把"需要几行"钉进最小高度（否则第二行会被卡片裁掉）
        p.watch_chip_host.sync_height()
        p.card_watch_groups.updateGeometry()
        self._refresh_target_combo()

    def _refresh_target_combo(self) -> None:
        """目标分组下拉：与胶囊**同源**（都从 store 重建，不存第二份状态 §11.5-11）。"""
        p = self.page
        current = p.cmb_watch_group.currentData()
        p.cmb_watch_group.blockSignals(True)
        p.cmb_watch_group.clear()
        for name in (p.watchlist.groups() or [DEFAULT_GROUP]):
            p.cmb_watch_group.addItem(name, name)
        if current:
            index = p.cmb_watch_group.findData(current)
            if index >= 0:
                p.cmb_watch_group.setCurrentIndex(index)
        p.cmb_watch_group.blockSignals(False)

    def _refresh_watch_headers(self) -> None:
        """卡头即状态行（A 方案的核心）：**收起时也能看见"在看哪一组、有几只"**。"""
        p = self.page
        groups = p.watchlist.groups()
        p.card_watch_groups.set_state(f"{len(groups)} 组 · {p.watchlist.count()} 只")
        label = "全部自选" if p.watch_group is None else p.watch_group
        count = len(p.watchlist.entries_in(p.watch_group))
        p.card_watch_list.set_title(f"{label} · {count} 只")

        # 排序模式时卡头让位给"正在排序"——它比涨跌更该被看见（顺序正在被改动）
        if getattr(p, "watch_sort_mode", False):
            p.card_watch_list.set_state(
                "排序中 · 拖 ⣿", "warn",
                "排序模式：只认行首 ⣿ 手柄（点行本体不会误拖）；\n"
                "拖过一次就已落盘，拖错可点「↺ 撤销」回到原顺序。")
            p.btn_watch_remove.setText("↗ 移出本组" if self._group_is_real() else "🗑 移除")
            return

        # 卡头右侧 = **这一组的组合涨跌**（收起时照样看得见 —— A 方案的核心价值就在这）
        snapshot = self._change_snapshot()
        summary = group_summary(snapshot, p.watchlist.symbols_in(p.watch_group),
                                baseline=baseline_date(snapshot))
        text = format_pct(summary["pct"])
        if not text:
            # 一只都没算出来 ⇒ **什么都不写**（写 0.00% 等于把"没数据"伪装成"没涨没跌"）
            p.card_watch_list.set_state("")
        else:
            direction = direction_of(summary["pct"])
            kind = ("warn" if summary["missing"]
                    else "ok" if direction is True else "bad" if direction is False else "")
            p.card_watch_list.set_state(
                f"组合 {text}", kind,
                tooltip=self._missing_tooltip(summary) if summary["missing"] else "")
        p.btn_watch_remove.setText("↗ 移出本组" if self._group_is_real() else "🗑 移除")

    def _selected_watch_symbol(self) -> str:
        p = self.page
        item = p.lst_watch.currentItem()
        return "" if item is None else str(item.data(ROLE_SYMBOL) or "")

    # ==========================================
    # 添加（两条入口：敲代码/名称 · 加入当前图上标的）
    # ==========================================
    def add_to_watchlist(self):
        """「★ 加入」：输入框有内容 ⇒ 按内容加入；为空 ⇒ 加入**当前图上正在看**的标的。

        ⚠ 两条入口共用**同一个按钮**是刻意的：用户的心智是"我要把某只票加进来"，
        而不是"我要用哪种方式加"。回车与点按钮也走**同一条**代码路径。
        """
        p = self.page
        keyword = p.txt_watch_quick.text().strip()
        if keyword:
            symbol, name = self._resolve_keyword(keyword)
            if not symbol:
                QMessageBox.warning(p, "未找到", f"花名册里找不到「{keyword}」。\n"
                                                 "请确认花名册已更新，或直接输入代码。")
                return
        else:
            symbol = str(p.current_symbol or "")
            name = str(p.current_name or "")
            if not symbol:
                QMessageBox.information(p, "先选一个标的",
                                        "输入框为空时，加入的是「当前图上正在看」的标的 —— 请先查阅一个。")
                return
        target = p.cmb_watch_group.currentData() or DEFAULT_GROUP
        try:
            added = p.watchlist.add(symbol, name, group=target)
        except ValueError as e:
            QMessageBox.warning(p, "无法加入自选", str(e))
            return
        p.txt_watch_quick.clear()
        # 加完就切到它所在的分组：否则"加进去了却看不见"是必然的困惑
        p.watch_group = target
        self._refresh_watchlist()
        self._set_status(f"已加入「{target}」：{name or symbol}" if added
                         else f"「{name or symbol}」已在「{target}」里（已刷新名称）")

    def watch_quick_add(self):
        """输入框回车 ⇒ 与点「★ 加入」完全同一条路径（一个入口只有一个实现）。"""
        return self.add_to_watchlist()

    # ==========================================
    # 第二种添加入口：从自选里挑选 → 批量移组（§7-B8 R2）
    # ==========================================
    def pick_watch_into_group(self) -> None:
        """「📋 从自选股里挑选…」：弹窗问"选哪些、移到哪"，落库交给 `move_selected_to_group`。

        ⚠ 弹窗只负责**问用户**，不碰 store ⇒ 两者可分开验收（弹窗不用真库也能测）。
        """
        p = self.page
        if p.watchlist.count() == 0:
            self._set_status("自选里还没有股票，先加几只再整理分组")
            return
        dialog = WatchlistPickerDialog(
            entries=p.watchlist.entries_all(), groups=p.watchlist.groups(),
            current_group=p.cmb_watch_group.currentData() or DEFAULT_GROUP, parent=p)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        symbols = dialog.selected_symbols()
        target = dialog.target_group()
        if not target:
            return
        moved = self.move_selected_to_group(symbols, target)
        self._set_status(f"已把 {moved} 只移入「{target}」" if moved
                         else f"这 {len(symbols)} 只本来就在「{target}」里")

    def move_selected_to_group(self, symbols, group) -> int:
        """批量移组的**唯一实现**（弹窗与测试都走这里）。返回真正移动的条数。

        移完**切到目标分组** —— 否则"移进去了却看不见"，用户会以为没生效。
        """
        p = self.page
        moved = p.watchlist.move_symbols_to_group(symbols, group)
        if moved:
            p.watch_group = group
            self._refresh_watchlist()
        return moved

    # ==========================================
    # 移出本组 / 从自选删除（两条路，一个实现）
    # ==========================================
    def remove_from_watchlist(self):
        """清单下那个按钮：**按当前上下文**决定含义。

        · 正在看某个真实分组 ⇒ **只移出本组**（挪回默认分组，票还在自选里）；
        · 正在看"全部"/默认分组 ⇒ 从自选里删除（这才是真的删除记录）。

        ⚠ 删除不弹二次确认：它不是不可逆操作（重新加入即可，行情数据一个字都不动，
        见 §10-10 的"只对不可逆动作用确认框"）。真正的结构改动（删分组）才有确认框。
        """
        p = self.page
        symbol = self._selected_watch_symbol()
        if not symbol:
            self._set_status("请先在自选列表里选中一项")
            return
        if self._group_is_real():
            p.watchlist.set_group(symbol, DEFAULT_GROUP)
            self._refresh_watchlist()
            self._set_status(f"已把 {p.watchlist.display_name(symbol)} 移出本组"
                             f"（仍留在「{DEFAULT_GROUP}」里）")
            return
        self._delete_symbol(symbol)

    def _delete_symbol(self, symbol: str) -> None:
        """从自选里删除一条记录（"移出本组"与它共享同一处刷新与回执）。"""
        p = self.page
        if p.watchlist.remove(symbol):
            self._refresh_watchlist()
            self._set_status(f"已从自选删除：{symbol}")

    def watch_list_menu(self, pos) -> None:
        """右键菜单：**两条路都给**（换组 / 删除），避免只有一个按钮时"想换组却删了票"。

        与按钮共用 `remove_from_watchlist` / `_delete_symbol`，不写第二份逻辑。
        """
        p = self.page
        item = p.lst_watch.itemAt(pos)
        if item is None:
            return
        p.lst_watch.setCurrentItem(item)
        symbol = str(item.data(ROLE_SYMBOL) or "")
        name = p.watchlist.display_name(symbol)
        menu = QMenu(p.lst_watch)
        if self._group_is_real():
            menu.addAction(f"↗ 把「{name}」移出本组").triggered.connect(p.remove_from_watchlist)
        menu.addAction(f"🗑 从自选删除「{name}」").triggered.connect(
            lambda: self._delete_symbol(symbol))
        menu.exec(p.lst_watch.mapToGlobal(pos))

    # ==========================================
    # 调序 / 激活
    # ==========================================
    def move_watchlist(self, delta: int):
        """上/下移 —— `WatchlistStore.move` **只在同组内**移动（不会把票挪进别的组）。

        `_refresh_watchlist` 会按"刷新前选中的那个 symbol"重新选中 ⇒ 移完之后
        高亮跟着票走，用户能连续点 ⬆ 而不用每移一次就重新点一行。
        """
        p = self.page
        symbol = self._selected_watch_symbol()
        if not symbol or not p.watchlist.move(symbol, delta):
            return
        self._refresh_watchlist()

    # ==========================================
    # 拖拽排序（§7-B8 R15 · 三道闸）
    # ==========================================
    def set_watch_sort_mode(self, on: bool) -> None:
        """闸 1 的入口（⇅ 按钮的 `toggled`）。

        ⚠ **只在真实分组里允许**："全部"里各分组的股票是**交错**的，
        拖一行跨过组边界就等于**顺手改了分组**（`WatchlistStore.move` 那条教训的同族）。
        """
        p = self.page
        if not on:
            self.finish_watch_sort()
            return
        if p.watch_group is None:
            p.btn_watch_sort.blockSignals(True)      # 回弹：**不做个假开关**
            p.btn_watch_sort.setChecked(False)
            p.btn_watch_sort.blockSignals(False)
            p.card_watch_list.set_state(
                "先选一个分组再排序", "warn",
                "「全部」里各分组的股票是交错的：在它上面拖动会跨过组边界，\n"
                "那等于顺手改了分组。请先点一个分组，再进排序模式。")
            return
        p.watch_sort_mode = True
        p._watch_sort_snapshot = p.watchlist.symbols_in(p.watch_group)   # 闸 3 的底片
        p.lst_watch.set_sort_mode(True)
        p.watch_row_delegate.set_sort_mode(True)
        p.lst_watch.viewport().update()
        p.watch_sort_bar.setVisible(True)
        p.btn_watch_sort.setText("⇅ 排序中")
        self._refresh_watch_headers()

    def undo_watch_sort(self) -> None:
        """闸 3：一键回到进排序模式之前的顺序（对"拖歪了一格"最有效，且不打断心流）。"""
        p = self.page
        snapshot = list(getattr(p, "_watch_sort_snapshot", []) or [])
        if p.watch_group is not None and snapshot:
            p.watchlist.reorder_group(p.watch_group, snapshot)
        self.finish_watch_sort()

    def finish_watch_sort(self) -> None:
        """退出排序模式（顺序**已经落盘**，这里只收摊；可安全重复调用）。"""
        p = self.page
        p.watch_sort_mode = False
        p._watch_sort_snapshot = []
        p.lst_watch.set_sort_mode(False)
        p.watch_row_delegate.set_sort_mode(False)
        p.lst_watch.viewport().update()
        p.watch_sort_bar.setVisible(False)
        p.btn_watch_sort.blockSignals(True)
        p.btn_watch_sort.setChecked(False)
        p.btn_watch_sort.setText("⇅ 排序")
        p.btn_watch_sort.blockSignals(False)
        self._refresh_watchlist()

    def on_watch_rows_moved(self, *_args) -> None:
        """拖拽**结束**才落盘（不在 dragover 里一路写文件 —— 同 §7-B8 R7 的纪律）。

        ⚠ 必须**推迟到下一轮事件循环**：此刻列表模型正处在"行已移动"的信号里，
        直接在信号处理里重建列表 = 一边发信号一边改模型（Qt 会崩或丢行）。
        """
        p = self.page
        if not p.watch_sort_mode or p.watch_group is None:
            return
        QTimer.singleShot(0, self.apply_watch_sort)

    def apply_watch_sort(self) -> None:
        """把**当前列表顺序**写回 store（只在本组内重排，其它组一格不动）。"""
        p = self.page
        if p.watch_group is None:
            return
        order = [str(p.lst_watch.item(row).data(ROLE_SYMBOL) or "")
                 for row in range(p.lst_watch.count())]
        if p.watchlist.reorder_group(p.watch_group, order):
            self._refresh_watchlist()

    def _on_watch_activated(self, item: QListWidgetItem):
        """双击自选 => 切换标的（走 `load_symbol`：湖优先，没有才联网）。"""
        p = self.page
        symbol = str(item.data(ROLE_SYMBOL) or "")
        if symbol:
            p.load_symbol(symbol, p.watchlist.display_name(symbol))

    # ==========================================
    # 分组（看 / 建 / 改名 / 删）—— 删组绝不删股票（§5 铁律）
    # ==========================================
    def watch_group_selected(self, key) -> None:
        """点分组胶囊 ⇒ 切换"我在看哪一组"（**只改看什么，一个字的数据都不改**）。"""
        p = self.page
        p.watch_group = key
        self._refresh_watchlist()

    def create_watch_group(self) -> None:
        """「＋ 新建分组」。建完**立刻切过去** —— 否则用户"建了个组却看不见它"。"""
        p = self.page
        name, confirmed = QInputDialog.getText(p, "新建分组", "分组名（最多 12 字）：")
        if not confirmed:
            return
        if not p.watchlist.create_group(name):
            QMessageBox.warning(p, "无法新建",
                                "分组名为空、超长、已存在，或分组数量已达上限。")
            return
        p.watch_group = " ".join(str(name).split())
        self._refresh_watchlist()
        self._set_status(f"已新建分组「{p.watch_group}」")

    def rename_watch_group(self) -> None:
        """重命名当前分组（组内成分跟着一起改；与已有分组重名时**拒绝**，不静默合并）。"""
        p = self.page
        if not self._group_is_real():
            self._set_status("请先选中一个分组（「全部」与默认分组不可改名）")
            return
        old = p.watch_group
        name, confirmed = QInputDialog.getText(p, "重命名分组", "新名称：", text=old)
        if not confirmed:
            return
        if not p.watchlist.rename_group(old, name):
            QMessageBox.warning(p, "无法重命名", "名称为空、超长，或已经有同名的分组。")
            return
        p.watch_group = " ".join(str(name).split())
        self._refresh_watchlist()
        self._set_status(f"分组「{old}」已改名为「{p.watch_group}」")

    def delete_watch_group(self) -> None:
        """删除当前分组：**成分解绑回默认分组，股票一只都不删**（§5 铁律）+ 二次确认。"""
        p = self.page
        if not self._group_is_real():
            self._set_status("请先选中一个分组（默认分组是所有解绑动作的落点，不可删）")
            return
        group = p.watch_group
        count = len(p.watchlist.entries_in(group))
        answer = QMessageBox.question(
            p, "删除分组",
            f"删除分组「{group}」？\n\n"
            f"· 组里 {count} 只股票**不会**被删除，会自动归入「{DEFAULT_GROUP}」\n"
            f"· 只丢掉「它们属于哪一组」这个归类信息")
        if answer != QMessageBox.StandardButton.Yes:
            return
        moved = p.watchlist.delete_group(group)
        p.watch_group = None
        self._refresh_watchlist()
        self._set_status(f"已删除分组「{group}」，{moved} 只股票归入「{DEFAULT_GROUP}」")
