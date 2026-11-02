# scripts/probe_startup.py
"""启动耗时探针（★2.03 / ARCH-PERF P0-5）—— **同一把尺子**，不参与运行。

用法（仓库根目录）：
    py scripts/probe_startup.py

输出三段：`import`（导入 ui.main_window 及其依赖）/ `construct`（建主窗口）/
`paint`（show + processEvents 首绘）。另报"已建页面数"，用于验证惰性建页：
P0 之前是 9/9，P0 之后构造完应只有首屏 1/9。

约定：
- **离屏**跑（`QT_QPA_PLATFORM=offscreen`）：可重复、不弹窗；真机数值会略高（字体/显卡）。
- 不写用户数据：只构造 + 首绘，不触发导入/下载/改偏好；更新检查打桩为不联网。
- 墙钟只用于人工对比，**断言一律用行为**（已建页面集合 / stat 次数 / 逐位一致）。
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    t0 = time.perf_counter()
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    t_qt = time.perf_counter()

    from ui import main_window as mw

    t_import = time.perf_counter()

    class _Signal:
        def connect(self, *_a, **_k):
            pass

    class _NoUpdate:
        """更新检查打桩：探针不联网（真实检查仍走 core/updater）。"""

        def __init__(self, *args, **kwargs):
            self.update_available = _Signal()

        def start(self):
            pass

    mw.UpdateCheckerThread = _NoUpdate

    win = mw.JianMainWindow()
    t_construct = time.perf_counter()

    win.show()
    app.processEvents()
    t_paint = time.perf_counter()

    built = list(win._built_pages)
    report = {
        "qt": round(t_qt - t0, 3),
        "import": round(t_import - t_qt, 3),
        "construct": round(t_construct - t_import, 3),
        "paint": round(t_paint - t_construct, 3),
        "total": round(t_paint - t0, 3),
        "built_pages": built,
        "built_count": len(built),
        "page_total": len(mw._PAGE_ORDER),
        "content_widgets": win.content_area.count(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("已建页面：%d/%d %s" % (len(built), len(mw._PAGE_ORDER), built))

    win.close()
    app.processEvents()
    sys.stdout.flush()
    os._exit(0)          # 跳过 Qt 卸载期清理（只影响退出耗时，不影响上面的数字）


if __name__ == "__main__":
    main()
