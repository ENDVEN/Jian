# main.py
import sys
import logging
import os
import pyqtgraph as pg  # <--- 新增：导入图表库用于全局配置
from PyQt6.QtWidgets import QApplication

# 从包内导入主窗口
from ui.main_window import JianMainWindow

def setup_env():
    """初始化运行环境、全局配置和日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 1. 确保截图目录存在
    if not os.path.exists("screenshots"): 
        os.makedirs("screenshots")
        logging.info("已创建 screenshots 目录")
        
    # 2. 【修复】配置 PyQtGraph 全局主题 (白底黑字，抗锯齿)
    pg.setConfigOption('background', '#FFFFFF')
    pg.setConfigOption('foreground', '#424242')
    pg.setConfigOptions(antialias=True)

def main():
    setup_env()
    app = QApplication(sys.argv)
    
    logging.info("正在启动 Jian 复盘系统...")
    window = JianMainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()