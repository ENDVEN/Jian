from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QListWidget, QListWidgetItem, QWidget)

class ListManagerDialog(QDialog):
    def __init__(self, title, items, delete_callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(350, 450)
        self.setStyleSheet("QDialog { background-color: #FAFAFA; font-family: -apple-system, sans-serif; } QListWidget { background: white; border: 1px solid #E0E0E0; border-radius: 8px; outline: none; } QListWidget::item { border-bottom: 1px solid #F5F5F5; }")
        self.delete_callback = delete_callback
        
        layout = QVBoxLayout(self)
        lbl_desc = QLabel("⚠️ 注意：删除操作不可逆，请谨慎操作。")
        lbl_desc.setStyleSheet("color: #F44336; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(lbl_desc)
        
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        for item_text in items: 
            self.add_item(item_text)
            
        btn_close = QPushButton("完成")
        btn_close.setStyleSheet("background-color: #1976D2; color: white; padding: 10px; font-weight: bold; border-radius: 6px;")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def add_item(self, text):
        item = QListWidgetItem()
        widget = QWidget()
        h_layout = QHBoxLayout(widget)
        h_layout.setContentsMargins(15, 10, 15, 10)
        
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #424242;")
        
        btn = QPushButton("🗑️")
        btn.setStyleSheet("QPushButton { border: none; color: #F44336; font-size: 16px; padding: 5px; } QPushButton:hover { background: #FFEBEE; border-radius: 6px; }")
        btn.clicked.connect(lambda checked, t=text, i=item: self.on_delete(t, i))
        
        h_layout.addWidget(lbl)
        h_layout.addStretch()
        h_layout.addWidget(btn)
        
        item.setSizeHint(widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)

    def on_delete(self, text, item):
        if self.delete_callback(text): 
            row = self.list_widget.row(item)
            self.list_widget.takeItem(row)