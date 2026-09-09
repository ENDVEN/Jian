# ui/widgets/screenshot_gallery.py
import os
import shutil
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QFileDialog, QMessageBox, QDialog,
                             QApplication, QListWidgetItem)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from pyqtgraph import QtGui

from config import settings
from ui.widgets.custom_widgets import HoverDeleteListWidget

# 截图默认缩放比 (超出屏幕 80% 才等比缩放，避免小图被拉伸)
MAX_SCREEN_RATIO = 0.8


class ScreenshotGallery(QWidget):
    """
    复盘截图画廊组件 (SRP 拆分自 ReviewView)。

    职责边界非常清晰：
    - 只负责单笔交易截图集合的 粘贴 / 导入 / 缩略图 / 预览 / 删除 / 序列化
    - 通过 paths_changed 信号把变更抛给宿主，自身完全不感知数据库与业务状态
    """
    PATH_SEPARATOR = ';'

    # 截图集合发生增删时发射，由宿主决定何时落库
    paths_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.owner_id = None  # 关联的 internal_id，用于生成唯一文件名
        self._build_ui()

    # ==========================================
    # 界面构建
    # ==========================================
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        lbl_img = QLabel("📸 画廊:")
        lbl_img.setStyleSheet("font-weight: bold; color: #424242;")
        header.addWidget(lbl_img)
        header.addStretch()

        self.btn_paste = QPushButton("📋 粘贴")
        self.btn_import = QPushButton("📁 导入")
        for btn in (self.btn_paste, self.btn_import):
            btn.setStyleSheet(
                "QPushButton { background-color: #F5F5F5; color: #424242; "
                "border: 1px solid #E0E0E0; border-radius: 4px; padding: 4px 10px; font-weight: bold; } "
                "QPushButton:hover { background-color: #EEEEEE; }"
            )
        self.btn_paste.clicked.connect(self.paste_image)
        self.btn_import.clicked.connect(self.import_images)

        header.addWidget(self.btn_paste)
        header.addWidget(self.btn_import)
        layout.addLayout(header)

        self.list_widget = HoverDeleteListWidget(self._on_delete_requested, self)
        self.list_widget.itemDoubleClicked.connect(self._view_full_image)
        # 便捷操作：聚焦画廊时直接 Ctrl+V 粘贴剪贴板截图
        shortcut = QtGui.QShortcut(QKeySequence("Ctrl+V"), self.list_widget)
        shortcut.activated.connect(self.paste_image)
        layout.addWidget(self.list_widget)

    # ==========================================
    # 对外接口 (Host API)
    # ==========================================
    def set_owner(self, owner_id):
        """绑定当前编辑的交易 (internal_id)，用于生成截图文件名"""
        self.owner_id = str(owner_id) if owner_id else None

    def set_paths(self, paths_str):
        """按持久化的路径串重建画廊 (纯展示同步，不触发变更信号)"""
        self.list_widget.clear()
        raw = str(paths_str) if paths_str else ""
        if not raw or raw == 'nan':
            return
        for path in raw.split(self.PATH_SEPARATOR):
            if path:
                # 【v5.12 修正 · §9-O8】旧代码在这里静默丢弃磁盘上已失效的路径：
                # 用户毫无感知，而下次"保存复盘"会把丢过的路径写回库 = 变相删数据。
                # 现在一律保留条目，只是把它标成「已丢失」由用户自己决定要不要清。
                self._add_thumbnail(path)

    def get_paths(self) -> str:
        """将当前画廊内容序列化为可持久化的路径串"""
        paths = [
            self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list_widget.count())
        ]
        return self.PATH_SEPARATOR.join(p for p in paths if p)

    def clear(self):
        """彻底重置 (切换交易或刷新视图时使用)，不触发变更信号"""
        self.owner_id = None
        self.list_widget.clear()

    # ==========================================
    # 内部实现 (Image Actions)
    # ==========================================
    def _build_filepath(self, ext: str) -> str:
        """生成 归属交易_毫秒时间戳 的唯一文件名，天然避免覆盖"""
        timestamp = int(datetime.now().timestamp() * 1000)
        owner = self.owner_id or "UNKNOWN"
        return os.path.join(settings.SCREENSHOT_DIR, f"{owner}_{timestamp}.{ext}")

    def _add_thumbnail(self, filepath):
        missing = not os.path.exists(filepath)
        # 文件已不在磁盘上时不画缩略图，但要保留条目 + 明确标注，
        # 让"数据里记着、磁盘上没了"这件事对用户可见。
        icon = QtGui.QIcon() if missing else QtGui.QIcon(filepath)
        item = QListWidgetItem(icon, "⚠ 已丢失" if missing else "")
        item.setData(Qt.ItemDataRole.UserRole, filepath)
        if missing:
            item.setToolTip(f"该截图文件已不存在于磁盘：\n{filepath}\n"
                            f"（如需彻底移除，请点缩略图右上角的删除按钮）")
        self.list_widget.addItem(item)

    def paste_image(self):
        """从系统剪贴板写入截图"""
        if not self.owner_id:
            QMessageBox.warning(self, "提示", "请先选择交易！")
            return

        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if not mime_data.hasImage():
            QMessageBox.warning(self, "提示", "剪贴板无图片！")
            return

        filepath = self._build_filepath("png")
        clipboard.image().save(filepath)
        self._add_thumbnail(filepath)
        self.paths_changed.emit()

    def import_images(self):
        """从磁盘批量导入截图 (复制进用户数据目录，原文件保持不动)"""
        if not self.owner_id:
            return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择截图", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        for path in file_paths:
            ext = path.rsplit('.', 1)[-1]
            target = self._build_filepath(ext)
            shutil.copy(path, target)
            self._add_thumbnail(target)

        if file_paths:
            self.paths_changed.emit()

    def _on_delete_requested(self, item, filepath):
        reply = QMessageBox.question(
            self, "删除截图", "确定要永久删除截图吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))

        self.list_widget.takeItem(self.list_widget.row(item))
        self.paths_changed.emit()

    def _view_full_image(self, item):
        filepath = item.data(Qt.ItemDataRole.UserRole)
        if not filepath or not os.path.exists(filepath):
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("查看截图")
        dialog.setStyleSheet("QDialog { background-color: #212121; }")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        pixmap = QtGui.QPixmap(filepath)
        screen = QApplication.primaryScreen().geometry()
        if (pixmap.width() > screen.width() * MAX_SCREEN_RATIO
                or pixmap.height() > screen.height() * MAX_SCREEN_RATIO):
            pixmap = pixmap.scaled(
                int(screen.width() * MAX_SCREEN_RATIO),
                int(screen.height() * MAX_SCREEN_RATIO),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

        label = QLabel()
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        dialog.exec()
