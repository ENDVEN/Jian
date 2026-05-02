# config/settings.py
import os
from pathlib import Path

# ==========================================
# 基础配置 (Base Settings)
# ==========================================
APP_NAME = "Jian - 专业交易复盘系统"
APP_VERSION = "1.0.0"

# ==========================================
# 界面配置 (UI Settings)
# ==========================================
MAIN_WINDOW_WIDTH = 1500
MAIN_WINDOW_HEIGHT = 950

COLOR_PROFIT = "#4CAF50"         
COLOR_LOSS = "#F44336"           
COLOR_PROFIT_TEXT = "#2E7D32"    
COLOR_LOSS_TEXT = "#C62828"      
COLOR_TEXT_PRIMARY = "#212121"   
COLOR_BACKGROUND = "#FFFFFF"     

RGB_PROFIT = (76, 175, 80)
RGB_LOSS = (244, 67, 54)
RGB_PROFIT_FILL = (76, 175, 80, 50) 
RGB_LOSS_FILL = (244, 67, 54, 50)

# ==========================================
# 业务逻辑配置 (Business Logic Settings)
# ==========================================
DEFAULT_STRATEGY = "未分类"
DEFAULT_ACCOUNTS = ["默认手工账户", "国内长线", "国内短线"]

# ==========================================
# 路径与存储配置 (物理隔离：防数据丢失)
# ==========================================
# 将数据保存在系统的用户目录下，例如 C:\Users\YourName\.jian_data
# 这样即便软件被卸载重装或版本覆盖，数据依然绝对安全！
USER_HOME = Path.home()
USER_DATA_DIR = os.path.join(USER_HOME, ".jian_data")

DB_PATH = os.path.join(USER_DATA_DIR, "jian_trades.db")
SCREENSHOT_DIR = os.path.join(USER_DATA_DIR, "screenshots")