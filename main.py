# main.py
import sys
import logging
import os
import time
import traceback
import pyqtgraph as pg  
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from config import settings
from ui.main_window import JianMainWindow
from ui.widgets.styles import apply_app_palette, ui_font, ui_font_status

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


def _install_excepthook() -> None:
    """★1.95：**未捕获异常不许让进程消失**（发布前硬化，2026-11-02 实测）。

    【为什么必须装】离屏对照实验：槽函数里 `raise ValueError`，**不装** excepthook 时
      PyQt 走 `qFatal` ⇒ 进程 **fastfail（RC 0xC0000409）**，用户只看到"软件自己关了"，
      `app.log` 里连栈都没有；**装上**之后异常被兜住、事件循环继续（实测 `app.exec()` 返回 0）。
      这也是冒烟脚本那个"固定点硬崩"的同一个机制（断言在 Qt 槽里抛出）。

    【口径】① 一律记日志（含完整栈）；② 弹一次可关闭的提示（3 秒内连环异常只弹一次，
      避免刷屏）；③ **绝不在异常里再抛**（弹窗失败就只留日志）；④ 离屏/无界面环境只记日志。
    """
    state = {"last": 0.0, "busy": False}

    def _hook(exc_type, exc_value, exc_tb):
        try:
            logging.error("未捕获异常（界面继续运行，已记日志）",
                          exc_info=(exc_type, exc_value, exc_tb))
        except Exception:                       # noqa: BLE001 —— 记日志失败也不许再炸
            pass
        if state["busy"]:
            return
        if time.monotonic() - state["last"] < 3.0:
            return
        state["last"] = time.monotonic()
        state["busy"] = True
        try:
            if str(os.environ.get("QT_QPA_PLATFORM", "")).lower() == "offscreen":
                return                          # 无界面环境不弹窗（只记日志）
            from PyQt6.QtWidgets import QMessageBox

            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("刚才有一步出错了（程序没退出）")
            box.setText("这一步操作出错了，已经记进日志；其余功能可以继续使用。")
            box.setInformativeText(f"{exc_type.__name__}: {exc_value}")
            box.setDetailedText("".join(
                traceback.format_exception(exc_type, exc_value, exc_tb))[-4000:])
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
        except Exception:                       # noqa: BLE001 —— 弹窗失败只影响提示
            pass
        finally:
            state["busy"] = False

    sys.excepthook = _hook
    try:                                        # 非 Qt 线程（极少）也兜一层
        import threading

        def _thread_hook(args):
            _hook(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = _thread_hook
    except Exception:                           # noqa: BLE001
        pass


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

    # ★1.69 / §10-16：高 DPI **分数缩放归整** —— 必须在 `QApplication` 构造**之前**设，晚一行无效。
    #
    # 【为什么必须做】用户实测（2026-10-11，2048x1280 屏 + Windows 125% 缩放）暴露两个后果：
    #   ① **窗口放不下**：dpr=1.25 ⇒ 可用区只剩 1638x986 DIP，而主窗口最小宽 1647 DIP
    #      （左侧栏 200 固定 + 内容区被"市场回测页"的摘要条撑到 1447）⇒ 窗口比屏幕还宽，
    #      右侧内容被挤出屏外，且 Qt 强制压缩布局 ⇒ 弹窗文字被压成一列、分组框边框错位；
    #   ② **1px 边框错位**：1.25 是分数倍率，1px 边框落在分数设备像素上 ⇒ 圆角/分隔线出现
    #      双线、错位（实测截图证据见 §10-16）。
    #   归整到整数倍率后：125% → 100%（可用宽度 1638 → 2048 DIP，窗口装得下），
    #   且所有 1px 线条落在整数设备像素上，观感与本项目设计样板一致。
    #
    # ⚠ 为什么取 RoundPreferFloor 而不是 RoundNearest：150% 缩放下 RoundNearest 会**向上**取到
    #   2.0（界面被放大一倍、可用 DIP 反而腰斩）；PreferFloor 取 1.0，方向始终对用户友好。
    #   代价是界面按 100% 渲染（比 125% 视觉略小）——这是"能完整显示"与"看起来大一点"之间的
    #   取舍，用户 2026-10-11 拍板取前者。
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
    app = QApplication(sys.argv)
    # ★1.95：**最早**装兜底（越早越好：建窗前后任何槽里漏出来的异常都不许闪退）
    _install_excepthook()

    # ★1.69 / §10-15：全站字体**在应用层钉一次**（唯一出口）—— 必须在建窗 / 建页**之前**。
    # 【为什么不能只"在窗口根 setFont"】页内大量 QSS 只写 `font-size`，字体族靠**继承**，
    #   而继承发生在控件**创建时**；离屏实测：构造完再对窗口根 `apply_ui_font` ⇒ 窗口字体已是
    #   Noto Sans SC，`content_area` 仍是 **Microsoft YaHei UI**（子件早已各自定型，改不动）。
    #   应用层设默认字体后，之后建的每一棵树都以开源栈为基准 ⇒ 与设计样板一致。
    app.setFont(ui_font())

    # ★1.69 / §10-17：把应用调色板**钉死浅色** —— 系统深色模式下这是"黑块 + 白底白字"的唯一解。
    #   实测（2026-10-11，本机 `AppsUseLightTheme=0`）：交易流水表 `Text=#ffffff / Base=#ffffff`
    #   ⇒ 对比度 **1.00**（整列不可读）；未设背景的容器透出 `#1e1e1e` ⇒ 用户看到的"黑块"。
    #   ⚠ 必须在建窗 / 建页**之前**（调色板按继承生效，晚一步子件已经定型）。
    apply_app_palette(app)

    # ★1.61 / §7-B16：函数总库**一次性资产收编**（幂等）—— 把 M1 策略 / M2·M3 方案里的
    #   公式导进资产库并写回 asset_id。必须在**各页面构造之前**做：页面随后 load 才能带上引用。
    #   只增字段不删不改、坏条目跳过、跑过一次就短路（铁律见 data/hub_migration.py）。
    try:
        from data.hub_migration import ensure_hub_migration
        _mig = ensure_hub_migration()
        if _mig.get("migrated"):
            logging.info(f"函数总库迁移：收编单股回测策略 {_mig['m1']} 条 / 筛选与广度方案 {_mig['scan']} 条")
    except Exception as _e:                            # noqa: BLE001 —— 迁移失败不拦启动（总库打开时兜底重试）
        logging.warning(f"函数总库迁移失败（总库打开时会重试）: {type(_e).__name__}: {_e}")

    logging.info(f"正在启动 {settings.APP_NAME} v{settings.APP_VERSION}...")
    window = JianMainWindow()
    # ★1.69 / §10-15：字体自检**挪到窗口构造之后**，并把窗口传进去 ——
    #   传 widget 才报得准"界面**实际**用上哪一款"；旧版对新造的 QFont 取 QFontInfo，
    #   报的是"字体栈**会**解析成谁"，于是出现过"日志说开源字体、界面其实跑在雅黑上"。
    logging.info(ui_font_status(window))
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()