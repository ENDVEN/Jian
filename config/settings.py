# config/settings.py
import os
from pathlib import Path

# ==========================================
# 基础配置 (Base Settings)
# ==========================================
APP_NAME = "Jian - 专业交易复盘系统"
# 版本演进：v1.1 交易时间契约重构 → v1.2 交割单字段补全 → v1.2.1 微观测算修正
#          → v1.3 范围聚焦 + 持仓时长三级口径回归
#          → v1.4.0 回测能力总集（多函数段共享池 / 条件组 Gate / 风控离场器 / 指数 regime 门控）
#                   + 单股回测 UX 硬化 + 年度面板净额口径统一 + Dashboard 每日净额日历
# ⚠ 必须与仓库根目录 version.json 保持同步：自动更新以二者比对为准（见 core/updater.py）
APP_VERSION = "1.4.0"

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
# NOTE(v1.2.1): 已删除 DEFAULT_ACCOUNTS —— 手工录入的"归属账户"只应列出真实存在
# 的账户（来自已导入数据），不预置"国内长线/国内短线"这类虚构账户。

# 绩效统计的虚拟初始资金 (用于计算收益率与回撤基准)
INITIAL_CAPITAL = 1000000

# ==========================================
# 路径与存储配置 (物理隔离)
# ==========================================
USER_HOME = Path.home()
USER_DATA_DIR = os.path.join(USER_HOME, ".jian_data")

DB_PATH = os.path.join(USER_DATA_DIR, "jian_trades.db")
SCREENSHOT_DIR = os.path.join(USER_DATA_DIR, "screenshots")

# ==========================================
# 更新检测配置 (Update Settings)
# ==========================================
# 这里填写你存放在云端的 version.json 文件的直链地址
# 格式要求形如：{"version": "1.1.0", "notes": "修复了Bug", "url": "https://下载链接"}
# 测试阶段，我们先用一个安全的占位符，一会教你怎么在本地测试它
UPDATE_CHECK_URL = "https://raw.githubusercontent.com/ENDVEN/Jian/refs/heads/main/version.json"