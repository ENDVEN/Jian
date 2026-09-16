# ui/widgets/desk_watch.py
"""★ 自选股（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【职责】自选列表的刷新 / 增删 / 调序 / 双击切换 —— 只走 `WatchlistStore` 门面
（UI 不碰文件、不碰 SQL，§10-3）。

【约定（与 1.22 拆 `backtest.py` 同款）】**状态留页面、行为搬模块**：
  · 页面持有 `watchlist`（store）、`lst_watch`（列表）、`current_symbol/current_name`
    与 `lbl_sync_status`（回执）；
  · 本模块只承载行为，读写一律走 `self.page.X` ⇒ 断言与主窗口看到的永远是同一份状态，
    不会出现"模块里存一份、页面上又存一份"。
线程/信号：`itemDoubleClicked` 连的是**页面的同名方法**（薄壳转发到这里），签名不变。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem, QMessageBox


class DeskWatch:
    """自选股行为（页面持有的"状态" + 本类提供的"行为"）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 列表刷新 / 选中
    # ==========================================
    def _refresh_watchlist(self):
        p = self.page
        p.lst_watch.clear()
        for entry in p.watchlist.entries_all():
            item = QListWidgetItem(f"{entry['name'] or entry['symbol']}　{entry['symbol']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["symbol"])
            p.lst_watch.addItem(item)

    def _selected_watch_symbol(self) -> str:
        p = self.page
        item = p.lst_watch.currentItem()
        return "" if item is None else str(item.data(Qt.ItemDataRole.UserRole) or "")

    # ==========================================
    # 增 / 删 / 调序 / 激活
    # ==========================================
    def add_to_watchlist(self):
        p = self.page
        if not p.current_symbol:
            QMessageBox.information(p, "先选一个标的", "请先查阅一个标的，再把它加入自选。")
            return
        try:
            added = p.watchlist.add(p.current_symbol, p.current_name)
        except ValueError as e:
            QMessageBox.warning(p, "无法加入自选", str(e))
            return
        self._refresh_watchlist()
        p.lbl_sync_status.setText(
            f"已加入自选：{p.current_name or p.current_symbol}" if added
            else "该标的已在自选里")

    def remove_from_watchlist(self):
        p = self.page
        symbol = self._selected_watch_symbol()
        if not symbol or not p.watchlist.remove(symbol):
            p.lbl_sync_status.setText("请先在自选列表里选中一项")
            return
        self._refresh_watchlist()
        p.lbl_sync_status.setText(f"已从自选移除：{symbol}")

    def move_watchlist(self, delta: int):
        p = self.page
        symbol = self._selected_watch_symbol()
        if not symbol or not p.watchlist.move(symbol, delta):
            return
        self._refresh_watchlist()
        for row in range(p.lst_watch.count()):
            if p.lst_watch.item(row).data(Qt.ItemDataRole.UserRole) == symbol:
                p.lst_watch.setCurrentRow(row)
                break

    def _on_watch_activated(self, item: QListWidgetItem):
        """双击自选 => 切换标的（走 `load_symbol`：湖优先，没有才联网）。"""
        p = self.page
        symbol = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if symbol:
            p.load_symbol(symbol, p.watchlist.display_name(symbol))
