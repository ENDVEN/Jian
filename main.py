# main.py
import sys
import logging
import os
import pyqtgraph as pg  
from PyQt6.QtWidgets import QApplication

from config import settings
from ui.main_window import JianMainWindow
from ui.widgets.custom_widgets import ui_font_status

def _attach_log_file() -> None:
    """★v6.74：日志**落文件（轮转）** —— 唯一出处。

    【为什么要它】此前只有 `basicConfig` 到控制台（没有 FileHandler）⇒ 用户复现问题时，我们只能
      靠他手工复制控制台（2026-09-26 23:5x 那次失败正是如此，事后无法回看全链路："哪些请求成功 /
      哪一个被拒 / 何时进入冷却"全靠拼）。落到 `~/.jian_data/logs/app.log`（UTF-8 · 5MB × 3 备份）后，
      限流诊断与"用户说抓不到"都能自己查。
    ⚠ 只记日志、不记凭据（`em_auth` 已保证日志里永远没有 cookie 值）。
    """
    try:
        log_dir = os.path.join(settings.USER_DATA_DIR, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(os.path.join(log_dir, 'app.log'),
                                      maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        # ★v6.75 S2-5：级别取设置页（`storage.log_level`，唯一真源）—— 改完即时生效，重启靠这里恢复
        from core.preferences import preferences as _prefs
        _level = getattr(logging,
                         str((_prefs.get('storage') or {}).get('log_level') or 'INFO').upper(),
                         logging.INFO)
        handler.setLevel(_level)
        logging.getLogger().setLevel(_level)
        logging.getLogger().addHandler(handler)
        logging.info(f"日志已落文件（轮转 5MB×3）: {os.path.join(log_dir, 'app.log')}")
    except Exception as e:                                # noqa: BLE001 —— 落盘失败不该拦启动
        logging.warning(f"日志落文件失败（只影响排障，不影响使用）: {type(e).__name__}: {e}")


def setup_env():
    """初始化运行环境、全局配置和日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    _attach_log_file()
    
    # 在系统的安全区域创建业务目录 (exist_ok 保证并发/重入安全)
    for directory in (settings.USER_DATA_DIR, settings.SCREENSHOT_DIR):
        os.makedirs(directory, exist_ok=True)
    logging.info(f"数据目录已就绪: {settings.USER_DATA_DIR}")

    # ★v6.72：行情取数的**网络策略**（地址族限定 IPv4 + 代理策略）—— 唯一出口在 `data/net_env.py`。
    #   实测（2026-09-26）：本机 DNS 优先 IPv6，而东财的 IPv6 端点不通（IPv4 直连 200 /
    #   IPv6 000）⇒ 不限定就"额度充足也莫名失败"；系统代理按偏好跟随（默认跟随，代理报错才降级直连）。
    from data import net_env
    _net = net_env.apply()
    logging.info(f"网络策略已应用: {net_env.describe()}（force_ipv4={_net['force_ipv4']}）")
        
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