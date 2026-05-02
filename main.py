# main.py
import sys
import logging
import os
import pyqtgraph as pg  
from PyQt6.QtWidgets import QApplication

from config import settings
from ui.main_window import JianMainWindow

def setup_env():
    """初始化运行环境、全局配置和日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 在系统的安全区域创建业务目录
    if not os.path.exists(settings.USER_DATA_DIR):
        os.makedirs(settings.USER_DATA_DIR)
    if not os.path.exists(settings.SCREENSHOT_DIR): 
        os.makedirs(settings.SCREENSHOT_DIR)
        logging.info(f"已创建安全数据目录: {settings.USER_DATA_DIR}")
        
    pg.setConfigOption('background', settings.COLOR_BACKGROUND)
    pg.setConfigOption('foreground', settings.COLOR_TEXT_PRIMARY)
    pg.setConfigOptions(antialias=True)

def main():
    setup_env()
    app = QApplication(sys.argv)
    
    logging.info(f"正在启动 {settings.APP_NAME} v{settings.APP_VERSION}...")
    window = JianMainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()