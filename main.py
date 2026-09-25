# main.py
import sys
import logging
import os
import pyqtgraph as pg  
from PyQt6.QtWidgets import QApplication

from config import settings
from ui.main_window import JianMainWindow
from ui.widgets.custom_widgets import ui_font_status

def setup_env():
    """初始化运行环境、全局配置和日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 在系统的安全区域创建业务目录 (exist_ok 保证并发/重入安全)
    for directory in (settings.USER_DATA_DIR, settings.SCREENSHOT_DIR):
        os.makedirs(directory, exist_ok=True)
    logging.info(f"数据目录已就绪: {settings.USER_DATA_DIR}")
        
    pg.setConfigOption('background', settings.COLOR_BACKGROUND)
    pg.setConfigOption('foreground', settings.COLOR_TEXT_PRIMARY)
    pg.setConfigOptions(antialias=True)

def main():
    setup_env()
    app = QApplication(sys.argv)

    # 诚实报告本机**实际用上**的界面字体：开源栈命中 / 回落系统默认（§10-9 字体只此一处）。
    # 用户反馈"字体不对"时，看这一行即可判断要不要装「思源黑体 / Noto Sans CJK SC」。
    logging.info(ui_font_status())
    logging.info(f"正在启动 {settings.APP_NAME} v{settings.APP_VERSION}...")
    window = JianMainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()