# main.py
import sys
import logging
import os
import pyqtgraph as pg  
from PyQt6.QtWidgets import QApplication

# 引入全局配置
from config import settings

# 从包内导入主窗口
from ui.main_window import JianMainWindow

def setup_env():
    """初始化运行环境、全局配置和日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 1. 使用配置中心定义好的截图路径
    if not os.path.exists(settings.SCREENSHOT_DIR): 
        os.makedirs(settings.SCREENSHOT_DIR)
        logging.info(f"已创建截图目录: {settings.SCREENSHOT_DIR}")
        
    # 2. 使用配置中心定义好的颜色主题
    pg.setConfigOption('background', settings.COLOR_BACKGROUND)
    pg.setConfigOption('foreground', settings.COLOR_TEXT_PRIMARY)
    pg.setConfigOptions(antialias=True)

def main():
    setup_env()
    app = QApplication(sys.argv)
    
    # 使用配置中心定义好的软件名称和版本
    logging.info(f"正在启动 {settings.APP_NAME} v{settings.APP_VERSION}...")
    window = JianMainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()