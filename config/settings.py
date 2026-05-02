# config/settings.py
import os

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

# 全局主题颜色 (Hex)
COLOR_PROFIT = "#4CAF50"         # 盈利绿 (主色)
COLOR_LOSS = "#F44336"           # 亏损红 (主色)
COLOR_PROFIT_TEXT = "#2E7D32"    # 盈利深绿 (用于白底文字保证对比度)
COLOR_LOSS_TEXT = "#C62828"      # 亏损深红 (用于白底文字保证对比度)
COLOR_TEXT_PRIMARY = "#212121"   # 主文字色
COLOR_BACKGROUND = "#FFFFFF"     # 图表背景色

# 图表专用 RGB 元组 (用于 PyQtGraph 画笔和填充)
RGB_PROFIT = (76, 175, 80)
RGB_LOSS = (244, 67, 54)
RGB_PROFIT_FILL = (76, 175, 80, 50) # 最后的 50 代表透明度 Alpha
RGB_LOSS_FILL = (244, 67, 54, 50)

# ==========================================
# 业务逻辑配置 (Business Logic Settings)
# ==========================================
DEFAULT_STRATEGY = "未分类"
DEFAULT_ACCOUNTS = ["默认手工账户", "国内长线", "国内短线"]

# ==========================================
# 路径与存储配置 (Path & Storage Settings)
# ==========================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")