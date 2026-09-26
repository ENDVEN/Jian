# tests/smoke_chart.py —— 图表架构冒烟断言（P0 / P1 / P2），验证后可直接复跑
#   用法：py tests/smoke_chart.py  （在仓库根目录执行）
import os
import sys

# 【§11.7】Windows 控制台默认 GBK：带 ↔ / ⇒ 这类符号的 print 会抛 UnicodeEncodeError，
# 表现为"某个分节整段被跳过 + 假报若干失败"（1.23 修）。统一按 UTF-8 输出。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 —— 被重定向的流不支持 reconfigure 就跳过
        pass

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pandas as pd

# 本文件在 tests/ 子目录里，**仓库根 = 本文件的父目录**：
# 由 `__file__` 反推而非相对路径 —— 从任何 cwd 运行都能找到包（§10-13 文件归置规范）。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.formula import draw
from core.formula.program import (
    parse_program, execute_programs, execute_programs_with_draws,
    missing_parameter_names, FormulaProgramError,
)

# 【§11.5-20 铁律①】模态框打桩：离屏环境没有用户可点，弹出即**永久阻塞**。
# 本脚本目前不构造主窗口，但公共件将来若增加"出错弹提示"的分支，这里能兜住。
from PyQt6.QtWidgets import QInputDialog, QMessageBox  # noqa: E402

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QInputDialog.getText = staticmethod(lambda *a, **k: ("测试输入", True))

OK, BAD = [], []


def check(desc, cond):
    (OK if cond else BAD).append(desc)
    print(("  [OK] " if cond else "  [!!] ") + desc)


def expect_error(desc, fn, *frags):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if all(f in msg for f in frags):
            check(desc, True)
        else:
            check(f"{desc} —— 文案不符({frags}) -> {type(e).__name__}: {msg}", False)
        return
    check(f"{desc} —— 未按要求报错", False)


n = 30
close = np.arange(1.0, n + 1)
df = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=n, freq='D'),
    'open': close - 0.5, 'high': close + 1.0,
    'low': close - 1.0, 'close': close,
    'volume': np.full(n, 1000.0),
})

SRC = """
DIF := EMA(C,2) - EMA(C,5);
STATUS: DIF, COLORWHITE, LINETHICK2;
HID: DIF, NODRAW;
STICKLINE(DIF > 0, 0, DIF, 3, 0);
DRAWICON(DIF > 0, H, 1);
"""

print("== P1 · M0 契约层（语句分类 / 属性 / 颜色）==")
prog = parse_program(SRC)
check("output_names = 变量(ASSIGN+OUTPUT)", prog.output_names == ['DIF', 'STATUS', 'HID'])
check("STATUS 为 line 规格", prog.line_specs['STATUS'].kind == 'line')
check("STATUS 颜色=白", prog.line_specs['STATUS'].color == '#FFFFFF')
check("STATUS 线宽=2", prog.line_specs['STATUS'].thickness == 2)
check("HID 为 hidden(NODRAW)", prog.line_specs['HID'].kind == 'hidden')
check("draws 共 2 条", len(prog.draws) == 2)
check("draws kinds = stick/icon", [d.kind for d in prog.draws] == ['stick', 'icon'])
check("STICKLINE 参数数=5", len(prog.draws[0].args) == 5)
check("DRAWICON 参数数=3", len(prog.draws[1].args) == 3)

p2 = parse_program("X: MA(C,5), COLORFF00AA, LINETHICK3;")
check("COLORRRGGBB 直通", p2.line_specs['X'].color == '#FF00AA')
check("LINETHICK3 生效", p2.line_specs['X'].thickness == 3)
check("默认线宽=1", parse_program("Y: C;").line_specs['Y'].thickness == 1)
check("DOTLINE 线型", parse_program("Z: C, DOTLINE;").line_specs['Z'].style == 'dot')
check("VOLSTICK 已识别(不报错)", parse_program("V: C, VOLSTICK;").line_specs['V'].kind == 'line')

p4 = parse_program("STICKLINE(C > 0, 0, 1, 1, 0);")
check("纯绘图函数可编译(不再报'函数为空')", p4.output_names == [] and len(p4.draws) == 1)
check("注释剥离 + 空语句容忍", parse_program("{c}\nA := 1; // x\n").output_names == ['A'])

expect_error("未知颜色报错", lambda: parse_program("X: MA(C,5), COLORRRED;"), "未知颜色")

# v6.5：绘图语句**尾部的颜色/线型属性**必须能切分（这是让存量函数重新可用的根因修复）
p_suffix = parse_program("STICKLINE(C > 0, 0, C, 3, 0), COLORFF0000;")
check("绘图语句尾部颜色被切分(不再送进解析器)",
      len(p_suffix.draws) == 1 and p_suffix.draws[0].color == '#FF0000'
      and len(p_suffix.draws[0].args) == 5)
check("绘图语句尾部多属性同样可切分",
      parse_program("DRAWICON(C>0, H, 1), COLORRED, LINETHICK2;").draws[0].thickness == 2)
expect_error("绘图语句尾部颜色非法仍报错",
             lambda: parse_program("STICKLINE(C>0, 0, C, 3, 0), COLORRRED;"), "未知颜色")

# v6.5（§9-Q）：已知但本期不渲染的绘图函数 —— **不阻断**，只登记成提示
p_defer = parse_program("DRAWTEXT(C>0, H, 1), COLORRED;\nDRAWBAND(C>0, 1, 0);")
check("未实现绘图函数不再阻断运行", p_defer.unsupported == ['DRAWTEXT', 'DRAWBAND'])
check("未渲染语句条数可统计", p_defer.unsupported_count == 2)
check("含未渲染语句时变量照常可用", p_defer.output_names == [])
expect_error("元数不符报错", lambda: parse_program("STICKLINE(C>0, 0, 1);"), "需要 5 个参数")
expect_error("垃圾语句报错(不再静默)", lambda: parse_program("hello world;"), "无法识别")
expect_error("裸表达式报错并给指引", lambda: parse_program("MA(C,5);"), "赋值")
expect_error("空函数报错", lambda: parse_program("   "), "函数为空")
expect_error("未知属性报错", lambda: parse_program("X: MA(C,5), FOO;"), "无法识别的绘图属性")
expect_error("线宽非法报错", lambda: parse_program("X: MA(C,5), LINETHICK12;"), "线宽属性")
check("COLOR_TABLE 常用色", draw.COLOR_TABLE['RED'] == '#FF0000' and draw.COLOR_TABLE['LIGRAY'] == '#C0C0C0')
expect_error("resolve_color 非法名报错", lambda: draw.resolve_color('COLORXYZ'), "未知颜色")

print("== P1 · M1 求值层（变量 + draws 同一次执行）==")
vars_only = execute_programs([prog], df, {})
vars2, draws = execute_programs_with_draws([prog], df, {})
check("新旧入口变量名一致", set(vars_only) == set(vars2) == {'DIF', 'STATUS', 'HID'})
check("新旧入口变量值一致", np.allclose(vars_only['DIF'].to_numpy(), vars2['DIF'].to_numpy()))
check("draws 共 3 条(STATUS线+stick+icon)", len(draws) == 3)
check("draws kinds = line/stick/icon", [d.kind for d in draws] == ['line', 'stick', 'icon'])

line, stick, icon = draws
check("line y 与 STATUS 等长且同值", len(line.y) == n and np.allclose(line.y, vars2['STATUS'].to_numpy()))
check("line 带颜色/线宽", line.color == '#FFFFFF' and line.thickness == 2)
check("stick cond = DIF>0", np.array_equal(stick.cond, (vars2['DIF'] > 0).to_numpy()))
check("stick cond 为 bool", stick.cond.dtype == bool)
check("stick lo/hi/width", np.allclose(stick.lo, 0.0)
      and np.allclose(stick.hi, vars2['DIF'].to_numpy()) and np.allclose(stick.width, 3.0))
check("icon icon_id=1", icon.icon_id == 1)
check("icon pos = H", np.allclose(icon.pos, df['high'].to_numpy()))
check("NODRAW 变量不产出绘图", all(d.name != 'HID' for d in draws))
check("x 轴取 date 列", np.array_equal(line.x, df['date'].to_numpy()))

_, again = execute_programs_with_draws([prog], df, {})
check("重复执行结果稳定", np.array_equal(again[1].cond, stick.cond))

seg1 = parse_program("A := C * 2;")
seg2 = parse_program("B: A + 1, COLORRED;")
vars3, draws3 = execute_programs_with_draws([seg1, seg2], df, {})
check("多段共享变量池", 'B' in vars3 and np.allclose(vars3['B'].to_numpy(), close * 2 + 1))
check("多段 draws 含 1 条 line", len(draws3) == 1 and draws3[0].kind == 'line' and draws3[0].name == 'B')

check("旧入口忽略绘图语句", execute_programs([parse_program("STICKLINE(C>0,0,1,1,0);")], df, {}) == {})
check("旧入口数值回归 Z=C+100",
      np.allclose(execute_programs([parse_program("Z := C + 100;")], df, {})['Z'].to_numpy(), close + 100))

_, d0 = execute_programs_with_draws([parse_program("STICKLINE(C < 0, 0, 1, 1, 0);")], df, {})
check("空 cond 全 False 不崩", int(d0[0].cond.sum()) == 0)

expect_error("DRAWICON 图标号=序列应报错",
             lambda: execute_programs_with_draws([parse_program("DRAWICON(C>0, H, C);")], df, {}),
             "常数")
expect_error("DRAWICON 图标号非整数应报错",
             lambda: execute_programs_with_draws([parse_program("DRAWICON(C>0, H, K);")], df, {"K": 1.5}),
             "必须是整数")

try:
    execute_programs([parse_program("X := N1 + 1;")], df, {})
    check("缺参探测仍可用", False)
except FormulaProgramError as e:
    check("缺参探测仍可用", missing_parameter_names(e) == ['N1'])

print("== P4 · 行情页共用件（参数解析 / 缺参探测 / 哑行情）==")
from core.formula.program import probe_missing_parameters
from core.utils import parse_params_text, synthetic_bars

check("参数文本解析", parse_params_text("L1=5, L2 = 20 , 乱写, N=-3") ==
      {'L1': 5.0, 'L2': 20.0, 'N': -3.0})
check("空参数文本 → 空字典", parse_params_text("") == {} and parse_params_text(None) == {})

bars = synthetic_bars(60)
check("哑行情列名与真实日线一致",
      list(bars.columns) == ['date', 'open', 'high', 'low', 'close', 'volume'])
check("哑行情长度可控且无空值", len(bars) == 60 and bars['close'].notna().all())
check("哑行情确定性（同参同值）", np.allclose(synthetic_bars(10)['close'], synthetic_bars(10)['close']))

progs = [parse_program("A := MA(C, N1);\nB: A + N2, COLORRED;")]
given = {}
missing, attempt = probe_missing_parameters(progs, given)
check("缺参探测：N1/N2 都被找出", set(missing) == {'N1', 'N2'})
check("缺参探测：不改调用方 params", given == {})
check("缺参探测：占位值只在返回副本里", attempt.get('N1') == 5.0 and attempt.get('N2') == 5.0)
check("参数齐了就不再报缺参", probe_missing_parameters(progs, {'N1': 5, 'N2': 1})[0] == [])
check("未定义的名称一律当缺失参数收集（与回测页口径一致）",
      probe_missing_parameters([parse_program("X: NOT_A_COL + 1;")], {})[0] == ['NOT_A_COL'])
expect_error("非缺参类错误照样抛出",
             lambda: probe_missing_parameters([parse_program("X: MA(C);")], {}),
             "需要 2 个参数")
check("哑行情能被真实函数消费",
      len(execute_programs_with_draws([parse_program("M: MA(C,5), COLORRED;")],
                                      synthetic_bars(30), {})[1]) == 1)

print("== P0/P2 · 图表宿主（离屏）==")
try:
    import pyqtgraph as pg
    from PyQt6.QtWidgets import QApplication

    from ui.widgets.chart_pane import ChartPane
    from ui.widgets.chart_host import ChartHost

    app = QApplication.instance() or QApplication([])

    # ---- P0 ChartPane ----
    pw = pg.PlotWidget()
    pane = ChartPane.wrap(pw, name='main', role='main')
    check("wrap(PlotWidget) -> ChartPane", isinstance(pane, ChartPane))
    check("plot_item 是 PlotItem", isinstance(pane.plot_item, pg.PlotItem))
    check("wrap(ChartPane) 幂等", ChartPane.wrap(pane) is pane)
    check("ChartPane(PlotItem) 可用", ChartPane(pg.PlotItem()).plot_item is not None)
    pane.add_overlay(pg.PlotDataItem([0, 1, 2], [0, 1, 0]))
    check("add_overlay 后 1 项", len(pane.overlay_items) == 1)
    pane.clear_overlays()
    check("clear_overlays 后 0 项", len(pane.overlay_items) == 0)
    pane.add_annotation(pg.PlotDataItem([0, 1], [1, 0]))
    check("add_annotation 后 1 项", len(pane.annotation_items) == 1)
    pane.clear_annotations()
    check("clear_annotations 后 0 项", len(pane.annotation_items) == 0)
    expect_error("非图表对象应拒绝", lambda: ChartPane(object()), "PlotItem")

    # ---- P2 ChartHost：多窗格 / x 联动 / 底部轴 ----
    host = ChartHost(sub_panes=['vol'])
    check("窗格顺序 = main/vol", host.pane_names == ['main', 'vol'])
    check("main_pane 角色 = main", host.main_pane.role == 'main')
    check("副图角色 = sub", host.pane('vol').role == 'sub')
    check("副图 x 轴已联动主图", host.x_linked('vol'))
    check("主图不联动", host.x_linked('main') is False)
    check("底部轴归最下窗格", host.bottom_axis_pane == 'vol')
    check("主图底部轴已隐藏", host.main_pane.plot_item.getAxis('bottom').isVisible() is False)
    check("最下窗格底部轴可见", host.pane('vol').plot_item.getAxis('bottom').isVisible() is True)

    host.add_pane('macd')
    check("追加第 2 张副图", host.pane_names == ['main', 'vol', 'macd'])
    check("新副图自动联动", host.x_linked('macd'))
    check("底部轴下移到 macd", host.bottom_axis_pane == 'macd')
    check("旧副图底部轴转为隐藏", host.pane('vol').plot_item.getAxis('bottom').isVisible() is False)
    expect_error("重名窗格应报错", lambda: host.add_pane('vol'), "已存在")

    check("主图不可删", host.remove_pane('main') is False)
    check("删除副图 vol", host.remove_pane('vol') is True)
    check("删除后剩 main/macd", host.pane_names == ['main', 'macd'])
    check("删除后仍联动", host.x_linked('macd'))
    check("删除后底部轴=mach", host.bottom_axis_pane == 'macd')
    check("删不存在的窗格返回 False", host.remove_pane('nope') is False)

    check("主图默认高度权重=3", host.pane_stretch('main') == 3)
    check("副图默认高度权重=1", host.pane_stretch('macd') == 1)
    check("set_pane_stretch 生效", host.set_pane_stretch('macd', 2) and host.pane_stretch('macd') == 2)
    check("set_pane_stretch 未知窗格返回 False", host.set_pane_stretch('nope', 2) is False)

    # ---- P2 日期轴 ----
    check("默认非日期轴", host.date_axis is False)
    host.set_date_axis(True)
    check("切换后全部窗格为 DateAxisItem",
          all(isinstance(p.plot_item.getAxis('bottom'), pg.DateAxisItem) for p in host.panes))
    host.set_date_axis(False)
    check("可切回普通轴", not isinstance(host.pane('macd').plot_item.getAxis('bottom'), pg.DateAxisItem))

    # ---- P2 十字光标 ----
    check("默认十字光标关闭", host.crosshair_enabled is False)
    check("每窗格已有 2 条光标线", all(
        len([i for i in p.plot_item.items if isinstance(i, pg.InfiniteLine)]) == 2 for p in host.panes))
    host.set_crosshair(True)
    check("开启十字光标", host.crosshair_enabled is True)
    v_main, h_main = host.crosshair_lines('main')
    v_macd, h_macd = host.crosshair_lines('macd')
    host.update_crosshair('main', 5.0, 12.3)
    check("悬停窗格竖+横线均可见", v_main.isVisible() and h_main.isVisible())
    check("竖线位置 = x", v_main.value() == 5.0)
    check("横线位置 = y", abs(h_main.value() - 12.3) < 1e-9)
    check("非悬停窗格只有竖线", v_macd.isVisible() and not h_macd.isVisible())
    check("非悬停竖线同步同一 x", v_macd.value() == 5.0)
    check("readout 含 Y 值", '12.30' in host.readout_text)
    host.set_crosshair(False)
    check("关闭后光标全部隐藏", not v_main.isVisible() and not v_macd.isVisible())
    check("关闭后 readout 清空", host.readout_text == "")

    # ---- v6.21 · §7-B6 STEP 2：读数条 provider（业务读数由页面给，宿主不猜业务）----
    host.set_crosshair(True)
    host.update_crosshair('main', 5.0, 12.3)
    check("未设 provider 时文案与旧格式**逐字一致**（既有行为零变化）",
          host.readout_text == "main   X=#5   Y=12.30")
    _seen = []
    host.set_readout_provider(lambda name, x, y: _seen.append((name, x, y)) or
                              f"2024-01-05 开 10.00 高 12.30")
    host.update_crosshair('main', 5.0, 12.3)
    check("设了 provider ⇒ 文案来自页面，且拿到 (窗格, x, y)",
          host.readout_text == "2024-01-05 开 10.00 高 12.30"
          and _seen and _seen[-1][0] == 'main' and abs(_seen[-1][2] - 12.3) < 1e-9)
    host.set_readout_provider(lambda *_: "")          # 空串 ⇒ 回退
    host.update_crosshair('main', 5.0, 12.3)
    check("provider 返回空串 ⇒ 回退内置文案", host.readout_text == "main   X=#5   Y=12.30")

    def _boom(*_a):
        raise RuntimeError("读数不该把图表搞崩")

    host.set_readout_provider(_boom)
    host.update_crosshair('main', 5.0, 12.3)
    check("provider 抛异常 ⇒ 静默回退内置文案（图表不受连累）",
          host.readout_text == "main   X=#5   Y=12.30")
    host.set_readout_provider(None)
    check("provider 可清除（回到纯内置口径）", host.readout_text == "main   X=#5   Y=12.30")

    host.set_readout_visible(True)
    host.set_crosshair(False)
    check("读数条可**常显**（不依赖十字光标开关，工作台要它常驻）",
          host._readout.isVisibleTo(host))
    host.set_readout_visible(False)
    check("取消常显后回到「跟十字光标走」", not host._readout.isVisibleTo(host))

    # ---- P2 clear：只清内容，不伤结构/光标 ----
    host.pane('main').add_overlay(pg.PlotDataItem([0, 1], [0, 1]))
    host.pane('main').add_annotation(pg.PlotDataItem([0, 1], [1, 0]))
    host.clear()
    check("clear 清空叠层与标注",
          host.pane('main').overlay_items == [] and host.pane('main').annotation_items == [])
    check("clear 不动窗格结构", host.pane_names == ['main', 'macd'])
    check("clear 不误删十字光标", host.crosshair_lines('main') is not None)

except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"图表宿主离屏测试执行失败: {type(e).__name__}: {e}", False)

print("== P3 · 公式叠层渲染器 draw_overlay（离屏）==")
try:
    from dataclasses import replace

    import pyqtgraph as pg
    from PyQt6.QtWidgets import QApplication

    from ui.widgets.chart_pane import ChartPane
    from ui.widgets.chart_style import (DARK_BACKGROUND, DEFAULT_OVERLAY_COLOR,
                                        LIGHT_BACKGROUND, ensure_contrast, luminance)
    from ui.widgets.draw_overlay import (DEFAULT_ICON_SYMBOL, ICON_SYMBOLS,
                                         OverlayPainter, overlay_extent, slice_draws)

    app = QApplication.instance() or QApplication([])

    # ---- 对比度守卫（黑底公式搬到白底不能"画了看不见"）----
    c_white = ensure_contrast('#FFFFFF', LIGHT_BACKGROUND)
    check("白底白线被压暗到可见",
          c_white != '#FFFFFF' and abs(luminance(c_white) - luminance(LIGHT_BACKGROUND)) >= 0.28)
    check("红线上白底保持原色", ensure_contrast('#FF0000', LIGHT_BACKGROUND) == '#FF0000')
    c_yellow = ensure_contrast('#FFFF00', LIGHT_BACKGROUND)
    r, g, b = (int(c_yellow[1:3], 16), int(c_yellow[3:5], 16), int(c_yellow[5:7], 16))
    check("黄线压暗后保留色相(R=G>B)", c_yellow != '#FFFF00' and r == g and r > b)
    c_black = ensure_contrast('#000000', DARK_BACKGROUND)
    check("黑底黑线被提亮到可见",
          c_black != '#000000' and abs(luminance(c_black) - luminance(DARK_BACKGROUND)) >= 0.28)
    check("默认叠层色本身已达标(不被改样子)",
          ensure_contrast(DEFAULT_OVERLAY_COLOR, LIGHT_BACKGROUND) == DEFAULT_OVERLAY_COLOR)
    check("空颜色回落默认叠层色", ensure_contrast('', LIGHT_BACKGROUND) == DEFAULT_OVERLAY_COLOR)

    # ---- slice_draws：按窗口切片（不二次求值 / 不改引擎产物）----
    prog3 = parse_program("A: C, COLORRED;\n"
                          "STICKLINE(C > 0, 0, C, 3, 0);\n"
                          "DRAWICON(C > 0, H, 1);")
    _, draws_all = execute_programs_with_draws([prog3], df, {})
    sliced = slice_draws(draws_all, np.array([0, 1, 2]))
    check("slice_draws: 3 条且 kinds 不变", [d.kind for d in sliced] == ['line', 'stick', 'icon'])
    check("slice_draws: line y 长度=3", len(sliced[0].y) == 3)
    check("slice_draws: stick cond/lo/hi 长度=3",
          len(sliced[1].cond) == 3 and len(sliced[1].lo) == 3 and len(sliced[1].hi) == 3)
    check("slice_draws: icon cond/pos 长度=3", len(sliced[2].cond) == 3 and len(sliced[2].pos) == 3)
    check("slice_draws 不改原对象", len(draws_all[0].y) == n)
    check("slice_draws 取值正确", float(sliced[0].y[2]) == float(draws_all[0].y[2]))
    check("slice_draws 保留标量字段", sliced[2].icon_id == 1 and sliced[1].hollow is False)

    _, draws_hollow = execute_programs_with_draws(
        [parse_program("STICKLINE(C > 0, 0, C, 3, 1);")], df, {})
    check("STICKLINE 第5参=1 → hollow=True", draws_hollow[0].hollow is True)

    # ---- overlay_extent：逐 bar 叠层范围（供宿主扩 y）----
    ext_lo, ext_hi = overlay_extent(sliced, 3)
    check("overlay_extent 长度=3", len(ext_lo) == 3 and len(ext_hi) == 3)
    # bar0: 线=1.0 / 状态柱 0→1.0 / 图标 2.0  ⇒ 最低 0、最高 2
    check("overlay_extent[0]=(0, 2)", abs(ext_lo[0]) < 1e-9 and abs(ext_hi[0] - 2.0) < 1e-9)
    check("无叠层的 bar 为 NaN", np.isnan(overlay_extent([], 3)[0]).all())

    # ---- OverlayPainter：IR → 图元 ----
    pane3 = ChartPane(pg.PlotWidget(), name='kline', role='main')
    painter = OverlayPainter(pane3, np.arange(3))
    items = painter.render(sliced)
    check("渲染出 3 个图元", len(items) == 3)
    check("line → PlotDataItem", isinstance(items[0], pg.PlotDataItem))
    check("stick → 自绘图元 _StickItem", items[1].__class__.__name__ == '_StickItem')
    check("icon → ScatterPlotItem", isinstance(items[2], pg.ScatterPlotItem))
    check("图标符号按 id 映射", items[2].opts['symbol'] == ICON_SYMBOLS[1])
    check("图元登记进 pane 叠层容器", len(pane3.overlay_items) == 3)
    painter.clear()
    check("painter.clear() 清空 pane 叠层", pane3.overlay_items == [])

    bad = [replace(sliced[0], y=np.arange(5, dtype=float))]
    check("数组长度与窗口不符 → 不画(防错位)",
          OverlayPainter(ChartPane(pg.PlotWidget()), np.arange(3)).render(bad) == [])

    _, draws_empty = execute_programs_with_draws(
        [parse_program("STICKLINE(C < 0, 0, 1, 3, 0);")], df, {})
    check("cond 全 False → 不产出图元",
          OverlayPainter(ChartPane(pg.PlotWidget()), np.arange(n)).render(draws_empty) == [])

    _, draws_unknown = execute_programs_with_draws(
        [parse_program("DRAWICON(C > 0, H, 999);")], df, {})
    items_unknown = OverlayPainter(ChartPane(pg.PlotWidget()), np.arange(n)).render(draws_unknown)
    check("未知图标号 → 默认菱形且不崩", items_unknown[0].opts['symbol'] == DEFAULT_ICON_SYMBOL)

    # ---- 端到端：函数文本 → 变量 + draws（NODRAW 只算不画）----
    _, e2e = execute_programs_with_draws([parse_program(
        "X := C * 2;\nQSD: X, COLORWHITE, LINETHICK2;\n"
        "HID: X, NODRAW;\nSTICKLINE(X > 0, 0, X, 3, 0);")], df, {})
    check("端到端 draws = 线+柱（NODRAW 不画）", [d.kind for d in e2e] == ['line', 'stick'])
    check("白线在白底被自动压暗",
          luminance(painter._color(e2e[0])) < 0.5)

    # ---- 零高度状态柱：STICKLINE(状态, P, P, w, 0)（用户状态柱的实际写法）----
    _, flat = execute_programs_with_draws([parse_program(
        "P := 5 * C / C;\nSTICKLINE(C > 0, P, P, 3, 0), COLORFFFF00;")], df, {})
    check("价1==价2 仍产出 stick（且带尾部颜色）",
          [d.kind for d in flat] == ['stick'] and flat[0].color == '#FFFF00')
    check("零高度柱 lo==hi", np.allclose(flat[0].lo, flat[0].hi))
    items_flat = OverlayPainter(ChartPane(pg.PlotWidget()), np.arange(n)).render(flat)
    rect_flat = items_flat[0].boundingRect()
    check("零高度柱渲染成横杠(不被退化成空图元)",
          (not rect_flat.isNull()) and rect_flat.width() > 0.1)

except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"叠层渲染器离屏测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.7 · 图层公共件（内置指标→IR / 数值量级引导）==")
try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QSizePolicy, QWidget

    from core.formula.draw import DrawData
    from core.indicators import TAEngine
    from ui.widgets.chart_layers import (builtin_indicator_layers, layer_value_range,
                                         scale_mismatch_hint)
    from ui.widgets.chart_style import MA_SERIES

    app = QApplication.instance() or QApplication([])

    ind_df = TAEngine.apply(synthetic_bars(60), ['ma', 'boll'])
    ma_layers = builtin_indicator_layers(ind_df, ma=True, boll=False)
    check("内置 MA → 3 条 line IR", len(ma_layers) == 3 and all(l.kind == 'line' for l in ma_layers))
    check("内置 IR 的颜色来自 chart_style 唯一来源", ma_layers[0].color == MA_SERIES[0][1])
    check("BOLL → 2 条虚线 IR",
          [l.style for l in builtin_indicator_layers(ind_df, boll=True)] == ['dash', 'dash'])
    check("开关全关 → 不产出任何图层", builtin_indicator_layers(ind_df) == [])

    check("layer_value_range 汇总全部数组",
          layer_value_range([DrawData(kind='line', y=np.array([1.0, 5.0])),
                             DrawData(kind='stick', lo=np.array([0.0]), hi=np.array([2.0]))])
          == (0.0, 5.0))
    check("layer_value_range 忽略 NaN", layer_value_range(
        [DrawData(kind='line', y=np.array([np.nan, np.nan]))]) is None)

    macd_like = [DrawData(kind='line', y=np.array([-1.5, 1.2]))]
    check("副图量级误放主图 → 给出提示",
          scale_mismatch_hint(macd_like, 100.0, 110.0) is not None)
    check("同量级 → 不打扰用户",
          scale_mismatch_hint([DrawData(kind='line', y=np.array([101.0, 108.0]))], 100.0, 110.0) is None)
    check("价格区间退化(全平) → 不误报", scale_mismatch_hint(macd_like, 100.0, 100.0) is None)

    print("== v6.7 · FunctionSegments 两个 Bug 的回归防护 ==")
    from ui.widgets.function_segments import FunctionSegments

    segs = FunctionSegments("测试")
    segs.set_texts(["A := 1;", "B := 2;"])
    check("set_texts 后段数正确", len(segs.texts()) == 2)
    check("标签连续编号", [w.lbl.text() for w in segs._iter_wraps()]
          == ['· 函数段 1', '· 函数段 2'])
    kids = segs._seg_box.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
    check("无僵尸子控件（Bug①：重复出现同名函数段）", len(kids) == 2)
    segs.set_texts(["A := 1;"])
    kids = segs._seg_box.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
    check("再次 set_texts 仍无僵尸残留", len(kids) == 1 and segs.texts() == ["A := 1;"])
    segs.append_segment("C := 3;")
    segs._remove_segment(list(segs._iter_wraps())[-1])
    kids = segs._seg_box.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
    check("删除段后同样无僵尸", len(kids) == len(list(segs._iter_wraps())))
    check("编辑框纵向可伸缩（Bug②：多余高度变成编辑面积，而非标签-编辑框之间的大空档）",
          list(segs._iter_wraps())[0].editor.sizePolicy().verticalPolicy()
          == QSizePolicy.Policy.Expanding)
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"图层公共件/FunctionSegments 测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.9 · 净额口径（§5.3-B / §9-P1 收尾）==")
try:
    from core.utils import record_net_amount

    class _Row:
        """模拟 TradeRecord 这类「有属性、没有 get」的记录对象。"""
        def __init__(self, net_profit, commission):
            self.net_profit = net_profit
            self.commission = commission

    check("毛利的 100 为正，但净额为负（口径分歧的真实场景）",
          100.0 > 0 and record_net_amount({'net_profit': 100.0, 'commission': 150.0}) == -50.0)
    check("Series 入参同样口径",
          record_net_amount(pd.Series({'net_profit': 100.0, 'commission': 150.0})) == -50.0)
    check("TradeRecord 式对象（无 get）同样口径",
          record_net_amount(_Row(100.0, 150.0)) == -50.0)
    check("手续费 NaN 按 0 处理（不因脏值抛异常/变 NaN）",
          record_net_amount({'net_profit': 80.0, 'commission': float('nan')}) == 80.0)
    check("字段缺失按 0 处理", record_net_amount({}) == 0.0)
    check("脏字符串按 0 处理", record_net_amount({'net_profit': 'abc', 'commission': None}) == 0.0)
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"净额口径测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.9 · 复合控件样式契约（§10-9：半截 QSS 会让下拉箭头消失）==")
try:
    from PyQt6.QtWidgets import QApplication, QComboBox, QDateEdit
    from PyQt6.QtCore import QDate
    from PyQt6.QtTest import QTest

    from ui.widgets import custom_widgets as cw

    app = QApplication.instance() or QApplication([])

    def _arrow_visible(widget, qss):
        """离屏实测：右侧 30px 带内存在深色像素 ⇒ 箭头被画出来了。"""
        widget.setStyleSheet(qss)
        widget.resize(160, 30)
        widget.show()
        QTest.qWait(60)
        app.processEvents()
        img = widget.grab().toImage()
        band = [(x, y) for x in range(img.width() - 30, img.width())
                for y in range(img.height())]
        return min(img.pixelColor(x, y).lightness() for x, y in band) < 200

    preset_names = ['COMBO_QSS', 'COMBO_QSS_SMALL', 'COMBO_QSS_ACCENT', 'COMBO_QSS_EDIT',
                    'COMBO_QSS_EDIT_OK', 'LINE_COMBO_QSS', 'DATEEDIT_QSS_WARN',
                    'DIALOG_INPUT_QSS']
    check("样式常量齐备（COMBO / 线+框 / 日期 / 弹窗表单）",
          all(hasattr(cw, name) for name in preset_names))
    check("每个常量都成对给出 ::drop-down 与 ::down-arrow（防半截 QSS 回退）",
          all('::drop-down' in getattr(cw, name) and '::down-arrow' in getattr(cw, name)
              for name in preset_names))
    check("SPINBOX_QSS 仍为空串（数值控件保持原生渲染，§10-9）", cw.SPINBOX_QSS == "")
    check("生成器：combo_qss 与 date_edit_qss 均产出成对子控件",
          '::down-arrow' in cw.combo_qss() and '::down-arrow' in cw.date_edit_qss())

    check("COMBO_QSS 箭头可见", _arrow_visible(QComboBox(), cw.COMBO_QSS))
    check("COMBO_QSS_SMALL 箭头可见", _arrow_visible(QComboBox(), cw.COMBO_QSS_SMALL))
    check("COMBO_QSS_ACCENT 箭头可见", _arrow_visible(QComboBox(), cw.COMBO_QSS_ACCENT))
    check("DATEEDIT_QSS_WARN 箭头可见", _arrow_visible(QDateEdit(QDate.currentDate()), cw.DATEEDIT_QSS_WARN))
    check("DIALOG_INPUT_QSS 下的下拉箭头可见", _arrow_visible(QComboBox(), cw.DIALOG_INPUT_QSS))
    check("DIALOG_INPUT_QSS 下的日期时间箭头可见",
          _arrow_visible(QDateEdit(QDate.currentDate()), cw.DIALOG_INPUT_QSS))

    # 反例（负向对照）：这正是 v6.9 前的真实写法 —— 只写 ::drop-down，箭头会消失
    half = "QComboBox { border: 1px solid #E0E4EC; } QComboBox::drop-down { border: none; width: 22px; }"
    check("反例：半截 QSS（只给 ::drop-down）确实看不到箭头 —— 证明本契约必要性",
          not _arrow_visible(QComboBox(), half))
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"复合控件样式契约测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.21 · §7-B6 STEP 1：分段控件 + 表单构件上收（样式单一来源）==")
try:
    from PyQt6.QtWidgets import QApplication
    import ui.widgets.custom_widgets as cw  # noqa: F401
    from ui.widgets.custom_widgets import (TAB_QSS_OFF, TAB_QSS_ON, SegmentedControl,
                                           hint_icon, mini_label, segment_button_qss,
                                           segment_qss)

    _app = QApplication.instance() or QApplication([])

    # ---- 1) 上收：定义只有一处，旧导入路径（回测页）仍可用 ----
    import ui.widgets.backtest_panes as bp
    check("mini_label / hint_icon 定义已上收，回测页是**再导出**（同一函数对象）",
          bp.mini_label is mini_label and bp.hint_icon is hint_icon)
    check("页签 QSS 同样上收（回测页再导出同一字符串）",
          bp.TAB_QSS_ON is TAB_QSS_ON and bp.TAB_QSS_OFF is TAB_QSS_OFF)
    check("Dashboard 的「?」角标也走同一处（消除第二份复制实现）",
          "hint_icon" in open(os.path.join(ROOT, "ui", "views", "dashboard.py"),
                              encoding="utf-8").read())

    # ---- 2) 样式契约：完整 QSS（首尾圆角 + 中段分隔线成套出现）----
    check("容器 QSS 带圆角与描边", "border-radius" in segment_qss() and "1px solid" in segment_qss())
    _first = segment_button_qss("first")
    _last = segment_button_qss("last")
    _mid = segment_button_qss("middle")
    check("首按钮只给左圆角（右圆角留给尾按钮）",
          "border-top-left-radius" in _first and "border-top-right-radius" not in _first)
    check("尾按钮只给右圆角", "border-top-right-radius" in _last
          and "border-top-left-radius" not in _last)
    check("中段有分隔线、首段没有（否则外框会与按钮边框叠成双线）",
          "border-left" in _mid and "border-left" not in _first)
    check("选中态样式齐备（:checked 有底色 + 字色 + 加粗）",
          ":checked" in _mid and "font-weight: bold" in _mid)
    check("单段 = only：四角全圆且无分隔线",
          "border-top-left-radius" in segment_button_qss("only")
          and "border-left" not in segment_button_qss("only"))
    try:
        segment_button_qss("瞎写")
        check("非法位置应报错（防拼错位置导致半截样式）", False)
    except ValueError as _e:
        check(f"非法位置报错（{_e}）", True)

    # ---- 3) 行为：单一状态源 + 幂等 + 信号 ----
    seg = SegmentedControl([("D", "日"), ("W", "周"), ("M", "月")])
    check("默认选中第一段", seg.current_key() == "D" and seg.current_index() == 0)
    check("按钮数与段数一致且只有一项 checked",
          seg.count() == 3 and sum(1 for b in seg.buttons() if b.isChecked()) == 1)
    _fired = []
    seg.sigChanged.connect(_fired.append)
    seg.buttons()[1].click()                     # 模拟真实点击
    check("点击第 2 段 → 状态与信号都跟上",
          seg.current_key() == "W" and _fired == ["W"])
    check("点击后仍只有一项 checked（互斥由 QButtonGroup 保证）",
          sum(1 for b in seg.buttons() if b.isChecked()) == 1)
    check("set_current 幂等：切到已是当前段 → 不发信号",
          seg.set_current("W") is True and _fired == ["W"])
    check("set_current(emit=True) 才会补发", seg.set_current("M", emit=True) is True
          and _fired == ["W", "M"])
    check("非法 key 被拒绝且状态不变（不静默乱切）",
          seg.set_current("Q") is False and seg.current_key() == "M")
    check("current 参数可在构造时定位（开机记忆上次口径用）",
          SegmentedControl([("af", "前复权"), ("nf", "不复权")], current="nf").current_key() == "nf")
    check("单段控件也能构造（避免边界崩）",
          SegmentedControl([("only", "唯一")]).count() == 1)
    _empty = SegmentedControl([])
    check("空段列表不崩、状态为空串", _empty.count() == 0 and _empty.current_key() == "")
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"分段控件/构件上收测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.9 · 架构红线（§9-H：UI 层不得直连行情源 / 数据库）==")
try:
    from pathlib import Path

    from data.sync_service import MarketSyncService, friendly_constituent_message

    ui_dir = Path(ROOT) / "ui"
    ui_sources = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
                  for p in ui_dir.rglob("*.py")}

    check("ui/ 全层不再出现 AkShareFeed（联网抓取已收编到 MarketSyncService）",
          not [n for n, t in ui_sources.items() if "AkShareFeed" in t])
    check("ui/ 全层无 sqlite3（UI 不得直连数据库）",
          not [n for n, t in ui_sources.items() if "sqlite3" in t])
    check("ui/ 全层无 `import akshare`",
          not [n for n, t in ui_sources.items() if "import akshare" in t])

    check("MarketSyncService 暴露唯一成分股入口",
          callable(getattr(MarketSyncService, "fetch_index_constituents", None)))
    check("成分股失败文案按原因分类（网络 vs 行情源未收录）",
          "网络请求失败" in friendly_constituent_message("000300", {"reason": "network"})
          and "行情源未返回名单" in friendly_constituent_message("000300", {"reason": "no_data"}))
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"架构红线扫描失败: {type(e).__name__}: {e}", False)

print("== v6.9 · 用户标注模型（P6 管线 B：按 (标的, 周期) 持久化 + 逐个删除）==")
try:
    import tempfile
    from pathlib import Path

    from data.annotations import (KIND_HLINE, KIND_TREND, KIND_VLINE, PERIOD_DAILY,
                                  AnnotationStore, DateAxis, make_annotation)

    # ---- 1) 归一化与校验（脏数据绝不入库）----
    item = make_annotation("sh600000", KIND_TREND,
                           [[pd.Timestamp("2024-03-01"), 10.5],
                            ["2024-03-08 15:00:00", "11.2"]])
    check("日期被归一化为 YYYY-MM-DD（原始是 Timestamp / 带时分字符串）",
          item["points"] == [["2024-03-01", 10.5], ["2024-03-08", 11.2]])
    check("坐标存的是日期而不是 bar 序号（防增量后漂移）",
          isinstance(item["points"][0][0], str) and "-" in item["points"][0][0])
    check("新对象自带 id / 时间戳",
          bool(item["id"]) and bool(item["created_at"]) and bool(item["updated_at"]))
    check("默认周期 = 日线", item["period"] == PERIOD_DAILY)

    # ⚠ v6.25：`arrow` 已经是**真实类型**了（目录里 27 种已实现）⇒ 这里换一个
    #   永远不会被实现的假名字，**别拿目录里的真类型当"未知类型"的样本**（会被扩容打脸）。
    expect_error("未知标注类型报错",
                 lambda: make_annotation("s", "__no_such_kind__", [[1, 2]]), "不支持")
    expect_error("趋势线锚点数不符报错",
                 lambda: make_annotation("s", KIND_TREND, [["2024-01-01", 1.0]]), "需要 2 个")
    expect_error("价格非法（NaN）被丢弃后报错",
                 lambda: make_annotation("s", KIND_HLINE, [["2024-01-01", float("nan")]]), "需要 1 个")
    check("水平线只需 1 个锚点",
          make_annotation("s", KIND_HLINE, [["2024-01-01", 3.0]])["points"] == [["2024-01-01", 3.0]])

    # ---- 1b) v6.12 新增的斐波那契 / 文字（P8 画线工具栏）----
    from data.annotations import FIB_RATIOS, KIND_FIB, KIND_TEXT, fib_levels

    fib = make_annotation("s", KIND_FIB, [["2024-01-01", 100.0], ["2024-02-01", 200.0]])
    check("斐波那契 = 两端点标注", len(fib["points"]) == 2 and fib["kind"] == "fib")
    check("斐波那契按档位线性插值（起点=0%、终点=100%）",
          fib_levels(fib["points"])[0][1] == 100.0
          and fib_levels(fib["points"])[-1][1] == 200.0
          and abs(fib_levels(fib["points"])[3][1] - 150.0) < 1e-9)   # 50% 档
    check("斐波那契档位数量 = FIB_RATIOS 数量（图上画几档与常量同源）",
          len(fib_levels(fib["points"])) == len(FIB_RATIOS) == 7)
    check("斐波那契锚点非法时不画半截（返回空列表）",
          fib_levels([["2024-01-01", 100.0]]) == [])
    expect_error("斐波那契锚点数不符报错",
                 lambda: make_annotation("s", KIND_FIB, [["2024-01-01", 1.0]]), "需要 2 个")

    text_item = make_annotation("s", KIND_TEXT, [["2024-01-01", 5.0]], text="  这里是压力位  ")
    check("文字标注：内容被 trim 后入库", text_item["text"] == "这里是压力位")
    expect_error("文字标注内容为空报错",
                 lambda: make_annotation("s", KIND_TEXT, [["2024-01-01", 5.0]], text="   "),
                 "需要填写内容")
    check("文字标注只需 1 个锚点", len(text_item["points"]) == 1)

    # ---- 1c) v6.25（§7-B8 R11）：27 种画线类型的**模型侧**口径 ----
    from data.annotations import (FIB_ARC_RATIOS, FIB_EXT_RATIOS, FIB_FAN_RATIOS,
                                  FIB_TIME_RATIOS, GANN_FACTORS, KIND_LABELS, PERCENT_RATIOS,
                                  REG_SIGMA, REQUIRED_POINTS, SUPPORTED_KINDS, WAVE_POINTS,
                                  fib_ext_levels, glyph_of, initial_text, percent_levels,
                                  price_text, regression_channel, requires_text)
    from ui.widgets.annotation_shapes import DRAWABLE_KINDS, SHAPES, spec_of

    check("★ 模型支持的类型 == 画得出来的类型（目录不许说谎，也不许有画不出的孤儿）",
          set(SUPPORTED_KINDS) == set(DRAWABLE_KINDS) == set(SHAPES) and len(SHAPES) == 32)
    check("★ 依赖视图的只剩**斐波弧**（甘氏扇形已改为「用户两点定比例」，不再依赖视图）",
          {kind for kind, spec in SHAPES.items() if spec.view_dependent} == {"fib_arc"}
          and len(GANN_FACTORS) == 9 and len(FIB_ARC_RATIOS) == 3
          and REG_SIGMA == 2.0 and WAVE_POINTS == 5)
    check("★ 每一种类型四件套齐全（锚点数 / 中文名 / 画法 / 回读 / 默认落点）",
          all(kind in REQUIRED_POINTS and KIND_LABELS.get(kind)
              and spec_of(kind).make and spec_of(kind).read and spec_of(kind).place
              for kind in DRAWABLE_KINDS))
    check("★ 锚点数与模型**逐位一致**（规格表说要 3 个点，模型就必须收 3 个点）",
          all(spec_of(kind).points == REQUIRED_POINTS[kind] for kind in DRAWABLE_KINDS))
    check("★ 档位是**语义常量**：百分比线八等分 / 斐波扩展 5 档 / 斐波扇形 4 条 / 时间 4 条",
          len(percent_levels(fib["points"])) == len(PERCENT_RATIOS) == 9
          and len(fib_ext_levels(fib["points"])) == len(FIB_EXT_RATIOS) == 5
          and len(FIB_FAN_RATIOS) == 4 and len(FIB_TIME_RATIOS) == 4)
    check("★ 斐波扇形含用户点名要的 **1×8 那条**（= 1/8 = 0.125，最缓的那条）",
          FIB_FAN_RATIOS[0] == 0.125 and min(FIB_FAN_RATIOS) == 0.125)
    check("★ 斐波扩展真的外推到 100% 之外（不然它跟回撤是同一个东西）",
          fib_ext_levels(fib["points"])[-1][1] > 200.0)
    check("文字口径：只有文字标注 / 评论气泡要用户填，价格标签的字由价位派生",
          requires_text(KIND_TEXT) and requires_text("comment")
          and not requires_text(KIND_HLINE) and not requires_text("price_tag"))
    check("符号类自带字形（箭头标记 ▲ / 标记点 ●），价格标签的字就是价位",
          glyph_of("marker") == "▲" and glyph_of("dots") == "●"
          and initial_text("price_tag", 12.345) == "12.35" == price_text(12.345)
          and initial_text(KIND_HLINE, 1.0) == "")

    # ---- 2) 仓库 CRUD（走临时文件，**绝不碰用户真实标注库**）----
    tmp = Path(tempfile.mkdtemp(prefix="jian_annot_smoke_"))
    store = AnnotationStore(str(tmp / "annotations.json"))
    check("空库初始为空", store.all() == [])

    saved = store.upsert(item)
    check("upsert 新建后 1 条", store.count("sh600000") == 1)
    check("文件已落盘且无 .tmp 残留",
          (tmp / "annotations.json").exists() and not (tmp / "annotations.json.tmp").exists())

    item_edit = dict(saved, points=[["2024-03-01", 9.9], ["2024-03-08", 12.0]])
    store.upsert(item_edit)
    check("同 (标的, 周期, id) 再 upsert = 更新而非新增", store.count("sh600000") == 1)
    check("更新后的坐标已生效", store.get("sh600000", PERIOD_DAILY, saved["id"])["points"][0][1] == 9.9)
    check("更新保留 created_at", store.get("sh600000", PERIOD_DAILY, saved["id"])["created_at"]
          == saved["created_at"])

    other = store.upsert(make_annotation("sh600000", KIND_VLINE, [["2024-03-05", 5.0]]))
    store.upsert(make_annotation("sz000001", KIND_HLINE, [["2024-03-05", 7.0]]))
    check("按 (标的, 周期) 隔离查询",
          store.count("sh600000") == 2 and store.count("sz000001") == 1)
    check("symbols() 汇总已有标注的标的", store.symbols() == ["sh600000", "sz000001"])

    check("delete 只删指定一条", store.delete("sh600000", PERIOD_DAILY, other["id"])
          and store.count("sh600000") == 1)
    check("delete 命中不了时返回 False",
          not store.delete("sh600000", PERIOD_DAILY, "不存在的id"))
    check("clear 只清该标的、不影响别人",
          store.clear("sh600000") == 1 and store.count("sh600000") == 0
          and store.count("sz000001") == 1)

    # ---- 3) 重启读回 + 坏数据容忍（单条坏数据不拖垮整库）----
    reloaded = AnnotationStore(str(tmp / "annotations.json"))
    check("从磁盘读回（等价重启）", reloaded.count("sz000001") == 1)
    with open(tmp / "annotations.json", "w", encoding="utf-8") as f:
        f.write('{"version": 1, "items": [{"symbol": "bad", "kind": "fib", "points": []},'
                ' {"id": "ok1", "symbol": "sh600000", "kind": "hline",'
                ' "points": [["2024-05-06", 8.8]]}]}')
    tolerant = AnnotationStore(str(tmp / "annotations.json"))
    check("坏数据行被跳过、好数据照常读出（不崩库）",
          tolerant.count("bad") == 0 and tolerant.count("sh600000") == 1)

    # ---- 4) DateAxis：日期 ↔ bar 序号（停牌/缺失日取最近一根）----
    axis = DateAxis(["2024-01-02", "2024-01-03", "2024-01-08", "2024-01-09"])
    check("精确命中", axis.date_to_index("2024-01-08") == 2)
    check("停牌/缺失日取时间上最近的一根（01-05 -> 01-03 更近）",
          axis.date_to_index("2024-01-05") == 1)
    check("缺失日另一侧（01-06 -> 01-08 更近）", axis.date_to_index("2024-01-06") == 2)
    check("早于首根 -> 夹到第一根", axis.date_to_index("2023-12-01") == 0)
    check("晚于末根 -> 夹到最后一根", axis.date_to_index("2030-01-01") == 3)
    check("非法日期 -> None", axis.date_to_index("") is None and axis.date_to_index("nonsense") is None)
    check("序号 -> 日期（越界夹取）",
          axis.index_to_date(0) == "2024-01-02" and axis.index_to_date(-5) == "2024-01-02"
          and axis.index_to_date(99) == "2024-01-09")
    check("空轴的一切查询都安全", DateAxis([]).date_to_index("2024-01-02") is None
          and DateAxis([]).index_to_date(3) == "")
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"用户标注模型测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.11 · 公式配方库（P7 函数资产化）==")
try:
    from pathlib import Path

    from data.formula_store import (SOURCE_BACKTEST, SOURCE_MARKET, VALID_TARGETS,
                                    FormulaStore, get_formula_store, make_formula,
                                    normalize_segments, segments_as_texts,
                                    segments_as_tuples)

    # ---- 1) 三种入参形态统一（页面各自传的东西不一样，公共件必须都能吃）----
    check("元组形态（行情页）",
          normalize_segments([("A: C;", "sub1"), ("B: O;", "main")])
          == [{"text": "A: C;", "target": "sub1"}, {"text": "B: O;", "target": "main"}])
    check("纯文本形态（回测页）→ 目标默认主图",
          normalize_segments(["A: C;", "B: O;"])
          == [{"text": "A: C;", "target": "main"}, {"text": "B: O;", "target": "main"}])
    check("字典形态（存储）原样保留",
          normalize_segments([{"text": "A: C;", "target": "sub2"}])[0]["target"] == "sub2")
    check("空段被丢弃", len(normalize_segments(["", "  ", "A: C;"])) == 1)
    check("非法 target 回落主图而**不丢整段**",
          normalize_segments([("A: C;", "sub9")]) == [{"text": "A: C;", "target": "main"}])
    check("pandas Series 也能吃（§11.5-18 的坑）",
          len(normalize_segments(pd.Series(["A: C;", "B: O;"]))) == 2)

    formula = make_formula("我的配方", [("A: C;", "sub1")], params_text="L1=5",
                           source=SOURCE_MARKET)
    check("segments_as_tuples / segments_as_texts 两种取用方式一致",
          segments_as_tuples(formula) == [("A: C;", "sub1")]
          and segments_as_texts(formula) == ["A: C;"])
    expect_error("空名称报错", lambda: make_formula("  ", ["A: C;"]), "名称不能为空")
    expect_error("没有任何有效函数段报错", lambda: make_formula("x", ["", " "]), "没有可保存")

    # ---- 2) 仓库 CRUD（临时文件，不碰用户真实配方库）----
    tmp = Path(tempfile.mkdtemp(prefix="jian_formula_smoke_"))
    store = FormulaStore(str(tmp / "formula_library.json"))
    check("空库初始为空", store.count() == 0)
    saved = store.upsert(formula)
    check("upsert 新建后 1 条，且落盘无 .tmp 残留",
          store.count() == 1 and (tmp / "formula_library.json").exists()
          and not (tmp / "formula_library.json.tmp").exists())

    overwritten = store.upsert(make_formula("我的配方", [("A: C;", "sub3"), ("B: O;", "main")],
                                            params_text="L1=9", source=SOURCE_BACKTEST))
    check("同名 upsert = 覆盖（不新增条目）", store.count() == 1)
    check("覆盖保留原 id", overwritten["id"] == saved["id"])
    check("覆盖保留 created_at 并写入新内容",
          overwritten["created_at"] == saved["created_at"]
          and len(overwritten["segments"]) == 2 and overwritten["params_text"] == "L1=9")

    store.upsert(make_formula("另一个配方", ["C: H;"], source=SOURCE_BACKTEST))
    check("不同名 → 新增", store.count() == 2)

    check("touch 记录使用时间", store.touch(saved["id"])
          and bool(store.get(saved["id"])["used_at"]))
    check("last_used 取最近用过的那个", store.last_used()["id"] == saved["id"])
    check("list_formulas 把最近用过的排前面",
          store.list_formulas()[0]["id"] == saved["id"])

    check("rename 成功", store.rename(saved["id"], "改名后") and store.get(saved["id"])["name"] == "改名后")
    check("重名 rename 被拒绝（否则按名覆盖会误伤）",
          not store.rename(saved["id"], "另一个配方"))
    check("delete 生效且只删一条", store.delete(saved["id"]) and store.count() == 1)

    # ---- 3) 重启读回 + 坏数据容忍 ----
    reloaded = FormulaStore(str(tmp / "formula_library.json"))
    check("从磁盘读回（等价重启）", reloaded.count() == 1)
    with open(tmp / "formula_library.json", "w", encoding="utf-8") as f:
        f.write('{"version":1,"formulas":[{"name":"坏的","segments":[]},'
                '{"id":"ok1","name":"好的","segments":[{"text":"A: C;","target":"main"}]}]}')
    tolerant = FormulaStore(str(tmp / "formula_library.json"))
    check("坏数据行被跳过、好数据照常读出",
          tolerant.count() == 1 and tolerant.all()[0]["name"] == "好的")

    # ---- 4) 单例（两个页面必须同一个实例，否则互相覆盖）----
    check("get_formula_store 是单例（同一对象）", get_formula_store() is get_formula_store())

    # ---- 5) 目标窗格取值必须与 UI 下拉一致（防"两处各写一份"漂移）----
    from ui.dialogs.formula_overlay import TARGET_CHOICES
    check("VALID_TARGETS 与编辑器下拉完全一致",
          set(VALID_TARGETS) == {value for _label, value in TARGET_CHOICES})

    # ---- 6) 配方库预览文案（列表右侧给人看的东西）----
    from ui.widgets.formula_library import preview_text
    preview = preview_text(make_formula("预览用", [("A: C;", "sub2")], source=SOURCE_MARKET))
    check("预览含名称/来源/段数/正文",
          all(token in preview for token in ("预览用", "行情页", "A: C;", "函数段 1")))
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"公式配方库测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.12 · 周期重采样（P8 行情工作台）==")
try:
    from core.utils import (PERIOD_ORDER, normalize_period, period_label,
                            resample_ohlcv)

    check("周期归一化：D/W/M + 中英文别名",
          normalize_period("D") == "D" and normalize_period("周线") == "W"
          and normalize_period("month") == "M" and normalize_period("") == "D"
          and normalize_period("乱写") == "D")
    # v6.21：`PERIOD_ORDER` 扩了分钟档位（§7 D3）；前三位仍是 日/周/月，顺序与取值都钉死
    check("周期中文标签与顺序（含分钟档位）",
          period_label("W") == "周线"
          and period_label("1m") == "1分钟"
          and PERIOD_ORDER == ("D", "W", "M", "1m", "5m", "15m", "30m", "60m"))

    daily = pd.DataFrame({
        'date': pd.bdate_range('2024-01-01', periods=10),      # 两周（2024-01-01 是周一）
        'open': [10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
        'high': [15, 16, 17, 18, 19, 25, 26, 27, 28, 29],
        'low': [9, 10, 11, 12, 13, 19, 20, 21, 22, 23],
        'close': [11, 12, 13, 14, 15, 21, 22, 23, 24, 25],
        'volume': [100] * 10,
    })
    check("周期 D 原样返回（不动数据）",
          len(resample_ohlcv(daily, "D")) == 10 and resample_ohlcv(daily, "D") is not daily)

    weekly = resample_ohlcv(daily, "W")
    check("周线：2 周 → 2 根", len(weekly) == 2)
    check("周线 OHLC 口径正确（开=首 高=max 低=min 收=末 量=和）",
          list(weekly['open']) == [10, 20] and list(weekly['close']) == [15, 25]
          and list(weekly['high']) == [19, 29] and list(weekly['low']) == [9, 19]
          and list(weekly['volume']) == [500, 500])
    check("周线日期 = 该周最后一个交易日（不是 resample 的周日标签）",
          weekly['date'].iloc[0] == daily['date'].iloc[4]
          and weekly['date'].iloc[1] == daily['date'].iloc[9])
    check("列名与日线完全一致 ⇒ 下游渲染零改动",
          list(weekly.columns) == list(daily.columns))

    monthly = resample_ohlcv(pd.concat([daily, daily.assign(
        date=daily['date'] + pd.Timedelta(days=40))]), "M")
    check("月线：跨两个月 → 2 根", len(monthly) == 2)
    check("空数据 / 无 date 列不炸",
          len(resample_ohlcv(pd.DataFrame(), "W")) == 0
          and len(resample_ohlcv(daily.drop(columns=['date']), "W")) == 10)
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"周期重采样测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.21 · §7-B6 STEP 3 / §7 D3：分钟周期数据链路（不联网）==")
try:
    import inspect

    from core.utils import (MINUTE_DEPTH_DAYS, MINUTE_PERIODS, PERIOD_ORDER,
                            is_aggregate_period, is_minute_period, normalize_period,
                            period_label, resample_ohlcv)
    from data.akshare_feed import AkShareFeed
    from data.sync_service import (ZONE_MIN, MarketSyncService, minute_key,
                                   split_minute_key)

    # ---- 1) 周期归一：分钟是**新增档位**，但不许污染既有 D/W/M 口径 ----
    check("分钟档位齐全且顺序稳定",
          MINUTE_PERIODS == ("1m", "5m", "15m", "30m", "60m") and PERIOD_ORDER[:3] == ("D", "W", "M"))
    check("归一：'5m'/'M5'/'5min'/'5分钟'/整数 5 都进 5m",
          all(normalize_period(v) == "5m" for v in ("5m", "M5", "5min", "5分钟", 5)))
    check("裸 'M' 仍是**月线**（历史口径不许被分钟抢走）",
          normalize_period("M") == "M" and period_label("M") == "月线")
    check("日/周写法的归一没被破坏",
          [normalize_period(v) for v in ("D", "W", "周线", "日线", "")] == ["D", "W", "W", "D", "D"])
    check("未知写法回落 D（不猜不报错）", normalize_period("瞎写") == "D")
    check("label 与 is_minute / is_aggregate 判据一致",
          period_label("15m") == "15分钟" and is_minute_period("15m")
          and not is_aggregate_period("15m") and is_aggregate_period("W"))

    # ---- 2) 重采样：周/月聚合，分钟**直通**（各档位独立取数）----
    bars = pd.DataFrame({
        "date": pd.bdate_range("2024-01-01", periods=30),
        "open": [10.0] * 30, "high": [11.0] * 30, "low": [9.0] * 30,
        "close": [10.5] * 30, "volume": [100] * 30})
    check("周线仍然聚合（既有行为零变化）", len(resample_ohlcv(bars, "W")) < len(bars))
    check("分钟周期 resample 是**直通** —— 绝不把 1m 聚合成 5m（那会把历史从 42 天缩到 9 天）",
          resample_ohlcv(bars, "5m").equals(resample_ohlcv(bars, "D")))
    check("深度提示表与档位一一对应、且单调（1m 最浅 / 60m 最深）",
          set(MINUTE_DEPTH_DAYS) == set(MINUTE_PERIODS)
          and MINUTE_DEPTH_DAYS["1m"] < MINUTE_DEPTH_DAYS["60m"])

    # ---- 3) 分钟键：同一标的按档位各存一份 ----
    check("minute_key 往返", split_minute_key(minute_key("600519", "5m")) == ("600519", "5m"))
    check("minute_key 归一档位写法", minute_key("600519", "M5") == "600519@5m")
    check("非分钟键原样返回（日线键不受影响）", split_minute_key("600519") == ("600519", ""))
    check("非法档位不伪造分钟键", split_minute_key("600519@瞎写") == ("600519@瞎写", ""))
    check("1m 与 5m 是两个键（不会互相覆盖）",
          minute_key("600519", "1m") != minute_key("600519", "5m"))

    # ---- 4) 源层：签名就是"口径声明"（分钟只有真实价一种）----
    check("fetch_a_share_minute **没有 adjust 参数** —— 从签名上杜绝'顺手加前复权'"
          "（实测 adjust 不生效，加了就是假口径）",
          "adjust" not in inspect.signature(AkShareFeed.fetch_a_share_minute).parameters)
    check("非股票代码取分钟返回空表（不联网、不抛异常）",
          AkShareFeed.fetch_a_share_minute("IF2401", "5m").empty)
    check("非分钟周期被拒绝（不拿日线冒充分钟）",
          AkShareFeed.fetch_a_share_minute("600519", "W").empty)

    # ---- 5) 门面：分派 / 快照合并 / 分钟不做 skip_fresh（全部用内存湖，不碰用户数据）----
    calls = []
    original_fetch = MarketSyncService._fetch

    def _fake_fetch(symbol, zone, start_date, period=None):
        calls.append((symbol, zone, start_date, period))
        if symbol == "EMPTY":
            return pd.DataFrame()
        step = pd.Timedelta(minutes=5)
        base = pd.Timestamp("2026-09-16 15:00")
        rows = 3 if len(calls) == 1 else 5
        return pd.DataFrame({
            "date": [base - step * (rows - 1 - i) for i in range(rows)],
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
            "volume": 100, "symbol": symbol})

    class _MemLake:
        """内存湖：只实现门面用到的方法（**绝不碰用户真实数据**）"""

        def __init__(self):
            self.store = {}

        def exists(self, zone, key):
            return key in self.store

        def load_data(self, zone, key):
            return self.store.get(key, pd.DataFrame())

        def save_data(self, zone, key, df):
            self.store[key] = df.copy()
            return True

        def get_latest_date(self, zone, key):
            df = self.store.get(key)
            return "" if df is None or df.empty else str(df["date"].max())

    svc = MarketSyncService()
    svc.lake = _MemLake()
    MarketSyncService._fetch = staticmethod(_fake_fetch)
    _no_sleep = (lambda _s: None)
    try:
        first = svc.refresh_one("600519", zone=ZONE_MIN, period="5m", sleep_fn=_no_sleep)
        check("分钟同步落到 `600519@5m` 这个键上（不是裸代码，日线那份不受影响）",
              "600519@5m" in svc.lake.store and "600519" not in svc.lake.store)
        check("回包给的是**纯标的**（页面竞态守卫照旧可用）+ 键与档位单列",
              first["symbol"] == "600519" and first["key"] == "600519@5m"
              and first["period"] == "5m")
        check("档位被传到源层（而不是让源层猜）",
              calls[-1][1] == ZONE_MIN and calls[-1][3] == "5m")
        check("分钟同步成功回执", first["ok"] and first["rows"] == 3)

        second = svc.refresh_one("600519", zone=ZONE_MIN, period="5m", sleep_fn=_no_sleep)
        check("第二次同步 = 整段快照**合并去重**（新增 2 根、旧的 3 根不丢）",
              second["ok"] and second["rows"] == 5 and second["added"] == 2)

        svc._is_fresh = lambda *a, **k: True          # 强行"本地已最新"
        today = svc.refresh_one("600519", zone=ZONE_MIN, period="5m", sleep_fn=_no_sleep)
        check("⚠ 分钟**不做**'已是最新就跳过'（盘中每分钟都在变，跳了就会拿旧快照）",
              today["ok"] and not today.get("skipped"))

        empty = svc.refresh_one("EMPTY", zone=ZONE_MIN, period="5m", sleep_fn=_no_sleep)
        check("分钟空返回 = 真失败（不退化成'已最新'，保住重试与熔断语义）",
              (not empty["ok"]) and not empty.get("skipped"))

        one = svc.refresh_one("600519", zone=ZONE_MIN, period="1m", sleep_fn=_no_sleep)
        check("换档位 ⇒ 另存一份，互不覆盖（1m 不会读到 5m 的数据）",
              one["key"] == "600519@1m" and "600519@1m" in svc.lake.store)
    finally:
        MarketSyncService._fetch = staticmethod(original_fetch)
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"分钟周期数据链路测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.21 · §7-B6 STEP 3c：工具行 chips「最近使用优先」（纯函数）==")
try:
    import ui.widgets.custom_widgets as _cw_chip
    from ui.widgets.chip_mru import (CHIP_LIMIT, CHIP_POOLS, chip_kind, chip_label,
                                     hidden_keys, normalize_recent, push_recent,
                                     resolve_chips)

    check("两个候选池与 §7-B6-D 一致（主图 3 / 副图 5）",
          CHIP_POOLS["main"] == ("ma", "boll", "formula")
          and CHIP_POOLS["sub"] == ("volume", "macd", "sub1", "sub2", "sub3"))
    check("chip_kind 认得出归属、认不出返回空",
          chip_kind("ma") == "main" and chip_kind("sub2") == "sub" and chip_kind("瞎写") == "")
    check("push_recent：新用的排最前 + 去重 + 超长截断",
          push_recent(["boll", "ma"], "ma") == ["ma", "boll"]
          and push_recent(["ma"], "ma") == ["ma"]
          and push_recent(["ma", "boll", "formula"], "volume", history=3)
          == ["volume", "ma", "boll"])
    check("normalize_recent 丢掉池外键（坏偏好不许污染界面）",
          normalize_recent(["ma", "瞎写", "ma", "sub1"]) == ["ma", "sub1"]
          and normalize_recent(None) == [])
    check("resolve：**已启用项一定看得见**（即使最近顺序靠后）",
          "boll" in resolve_chips(["ma", "volume", "macd"], ["boll"], limit=3))
    check("resolve：顺序 = 最近使用倒序",
          resolve_chips(["macd", "ma", "volume"], ["ma", "volume", "macd"], limit=3)
          == ["macd", "ma", "volume"])
    check("resolve：已启用优先占位，关闭的灰态项用空位补上（规则 3）",
          resolve_chips(["ma", "boll", "volume", "macd"], ["ma"], limit=3)
          == ["ma", "boll", "volume"])
    check("resolve：上限生效（溢出的交给「＋ 更多」）",
          len(resolve_chips(["ma", "boll", "formula"], ["ma", "boll", "formula"], limit=2)) == 2)
    check("resolve：已启用数 > 上限时按**最近序**裁剪",
          resolve_chips(["formula", "boll", "ma"], ["ma", "boll", "formula"], limit=2)
          == ["formula", "boll"])
    check("resolve：pool 会过滤掉不存在的项（如公式里根本没有副图 2）",
          resolve_chips(["sub2", "volume"], [], limit=3, pool=("volume", "macd")) == ["volume"])
    check("resolve：空输入不崩、结果为空",
          resolve_chips([], [], limit=3) == [] and resolve_chips(None, None) == [])
    check("hidden_keys = 池内但没显示出来的（正是「＋ 更多」要列的东西）",
          set(hidden_keys(["ma", "boll", "formula"], [], limit=2, pool=CHIP_POOLS["main"]))
          == {"formula"})
    check("chip_label 有中文名、未知键原样回显",
          chip_label("ma") == "MA" and chip_label("sub1") == "公式副图 1"
          and chip_label("自定义") == "自定义")
    check("chip 样式的唯一定义处 = custom_widgets（§10-9）",
          all(hasattr(_cw_chip, name) for name in ("CHIP_QSS_ON", "CHIP_QSS_OFF",
                                                   "CHIP_MORE_QSS")))
    check("池上限常量就是 3（与 §7-B6-D 的「最近前 3」一字对应）", CHIP_LIMIT == 3)
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"工具行 chips 纯函数测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.12 · 自选股（P8）+ 斐波那契/文字标注的绘制与删除 ==")
try:
    import tempfile
    from pathlib import Path

    from data.watchlist_store import WatchlistStore, normalize_symbol

    check("代码归一化（去空白 + 大写）", normalize_symbol(" sh600000 ") == "SH600000"
          and normalize_symbol(None) == "")

    tmp = Path(tempfile.mkdtemp(prefix="jian_watch_smoke_"))
    watch = WatchlistStore(str(tmp / "watchlist.json"))
    check("空自选初始为空", watch.count() == 0)
    check("add 返回 True 表示新增", watch.add("sh600000", "浦发银行") is True)
    check("重复 add 返回 False（只刷新名称，不重复占位）",
          watch.add("SH600000", "浦发银行") is False and watch.count() == 1)
    check("add 时大小写会被归一",
          watch.add("sz000001", "平安银行") and watch.symbols() == ["SH600000", "SZ000001"])
    check("落盘无 .tmp 残留且可重启读回",
          (tmp / "watchlist.json").exists() and not (tmp / "watchlist.json.tmp").exists()
          and WatchlistStore(str(tmp / "watchlist.json")).count() == 2)
    check("contains / display_name 大小写不敏感",
          watch.contains("sh600000") and watch.display_name("sz000001") == "平安银行")

    watch.add("600519", "贵州茅台")
    check("move 上移改变顺序（顺序 = 用户排序）",
          watch.move("600519", -1) and watch.symbols()[1] == "600519")
    check("move 到边界返回 False（不越界、不崩）",
          not watch.move("600519", -5) and not watch.move("SH600000", -1))
    check("update_name 刷新旧名（花名册更新后不当真相）",
          watch.update_name("600519", "贵州茅台酒") and watch.display_name("600519") == "贵州茅台酒")
    check("remove 生效", watch.remove("sz000001") and watch.count() == 2)
    check("clear 返回删除条数并清空", watch.clear() == 2 and watch.count() == 0)

    with open(tmp / "watchlist.json", "w", encoding="utf-8") as f:
        f.write('{"version":1,"entries":[{"symbol":""},{"symbol":"sh600000","name":"A"},'
                '{"symbol":"SH600000","name":"重复"},{"symbol":"sz000001"}]}')
    tolerant = WatchlistStore(str(tmp / "watchlist.json"))
    check("坏数据（空代码）与重复项被跳过，好数据照常读出",
          tolerant.symbols() == ["SH600000", "SZ000001"])

    # ---- 分组（v6.24 · §7-B8 R1）：分类语义 + 删组不删股票 + 组内移动 ----
    from data.watchlist_store import DEFAULT_GROUP, GROUP_NAME_MAX, normalize_group

    check("分组名归一化：空白折叠 + 空值落到默认组（**绝不产生空串分组**）",
          normalize_group("  核心  白马 ") == "核心 白马"
          and normalize_group("") == DEFAULT_GROUP and normalize_group(None) == DEFAULT_GROUP)
    check("旧文件（v1，无 group 字段）读进来自动归到默认分组 —— 向后兼容",
          tolerant.group_of("SH600000") == DEFAULT_GROUP
          and tolerant.groups() == [DEFAULT_GROUP])

    grouped = WatchlistStore(str(tmp / "grouped.json"))
    grouped.add("600519", "贵州茅台")
    grouped.add("000858", "五 粮 液")
    check("不传 group 的新增落到默认分组",
          grouped.group_of("600519") == grouped.group_of("000858") == DEFAULT_GROUP)
    check("新建分组生效", grouped.create_group("核心白马") and "核心白马" in grouped.groups())
    check("重名 / 空名 / 超长名一律拒绝（不静默改名、不静默截断）",
          not grouped.create_group("核心白马") and not grouped.create_group("   ")
          and not grouped.create_group("长" * (GROUP_NAME_MAX + 1)))
    check("空分组也留得住（chips 要能显示 0 只，否则用户以为新建失败）",
          grouped.group_counts().get("核心白马") == 0)

    check("显式给 group 的新增直接进该组",
          grouped.add("601318", "中国平安", group="核心白马")
          and grouped.group_of("601318") == "核心白马")
    check("已存在的股票显式给组 ⇒ 移组（返回 False = 本来就在，不是新增）",
          grouped.add("000858", "五 粮 液", group="核心白马") is False
          and grouped.group_of("000858") == "核心白马")
    check("★ 已存在的股票**不传** group ⇒ 保持原组不动（不许静默改用户的分类）",
          grouped.add("000858", "五 粮 液") is False
          and grouped.group_of("000858") == "核心白马")

    check("entries_in / symbols_in / group_counts 三者一致",
          grouped.symbols_in("核心白马") == ["000858", "601318"]
          and grouped.group_counts()["核心白马"] == 2
          and len(grouped.entries_in()) == 3)

    # ★组内移动：跨组边界**不许**把票挪进别的组
    check("组内上移生效（核心白马内 601318 上移到 000858 之前）",
          grouped.move("601318", -1) is True
          and grouped.symbols_in("核心白马") == ["601318", "000858"])
    check("★ 组内移动不会把票挪进别的组（总表顺序变了，分组归属一个没变）",
          grouped.group_of("601318") == "核心白马" and grouped.group_of("000858") == "核心白马"
          and grouped.group_of("600519") == DEFAULT_GROUP)
    check("组内边界返回 False（已到组内首尾 / 组里只有自己）",
          not grouped.move("601318", -1) and not grouped.move("000858", 1)
          and not grouped.move("600519", -1) and not grouped.move("600519", 1))

    check("set_group 把单只移进已存在的组",
          grouped.set_group("600519", "核心白马") and grouped.group_of("600519") == "核心白马")
    check("★ set_group 对**不存在的组**返回 False（不顺手建一个错别字组 = 脏数据）",
          grouped.set_group("600519", "查无此组") is False
          and "查无此组" not in grouped.groups())
    check("批量移组返回真实移动条数",
          grouped.move_symbols_to_group(["600519", "601318"], DEFAULT_GROUP) == 2
          and grouped.group_counts()[DEFAULT_GROUP] == 2)

    check("重命名分组：连带成员一起改",
          grouped.rename_group("核心白马", "白马") and grouped.group_of("000858") == "白马"
          and "核心白马" not in grouped.groups())
    check("★ 重命名到已存在的组 ⇒ 拒绝（不静默合并两个分组 = 不可逆的分类丢失）",
          grouped.create_group("科技") and not grouped.rename_group("白马", "科技")
          and grouped.group_of("000858") == "白马")

    check("★ 删分组 = 成员解绑回默认组，**股票一条都不少**（§5 铁律：不连带删数据）",
          grouped.delete_group("白马") == 1 and grouped.count() == 3
          and grouped.group_of("000858") == DEFAULT_GROUP and "白马" not in grouped.groups())
    check("默认分组不可删（它是所有解绑动作的落点）",
          grouped.delete_group(DEFAULT_GROUP) == 0 and grouped.count() == 3)
    check("删不存在的组返回 0（不误伤）", grouped.delete_group("查无此组") == 0)

    _reopened = WatchlistStore(str(tmp / "grouped.json"))
    check("分组名与成员的归属一起落盘、可重启读回",
          _reopened.group_of("000858") == DEFAULT_GROUP and "科技" in _reopened.groups()
          and _reopened.count() == 3)

    # ---- 拖拽排序的落盘入口（v6.24 · §7-B8 R15）：**只重排本组，其它组一格不动** ----
    drag_store = WatchlistStore(str(tmp / "drag.json"))
    drag_store.create_group("A组")
    drag_store.create_group("B组")
    for _symbol in ("600000", "600001", "600002"):
        drag_store.add(_symbol, group="A组")
    for _symbol in ("000001", "000002"):
        drag_store.add(_symbol, group="B组")
    _b_before = drag_store.symbols_in("B组")
    _a_before = drag_store.symbols_in("A组")

    check("重排某组：本组顺序真的变了", drag_store.reorder_group("A组", list(reversed(_a_before)))
          and drag_store.symbols_in("A组") == list(reversed(_a_before)))
    check("★ 重排一个组时，**另一个组在总表里的相对位置一格不动**（只改写本组占的槽位）",
          drag_store.symbols_in("B组") == _b_before)
    check("★ 成员集合对不上就拒绝：多给 / 少给 / 重复 一律不动（不猜、不补、不删）",
          drag_store.reorder_group("A组", ["600000", "600001"]) is False
          and drag_store.reorder_group("A组", ["600000", "600001", "600002", "600003"]) is False
          and drag_store.reorder_group("A组", ["600000", "600000", "600001"]) is False)
    check("顺序没变化 ⇒ 返回 False（不白写一次盘）",
          drag_store.reorder_group("A组", drag_store.symbols_in("A组")) is False)
    check("不存在的组 ⇒ 拒绝（不顺手建组）",
          drag_store.reorder_group("查无此组", ["600000"]) is False)
    check("默认分组也能重排（它就是普通分组的一个特例）",
          drag_store.add("600004", "四号") and drag_store.add("600005", "五号")
          and drag_store.reorder_group(DEFAULT_GROUP, ["600005", "600004"])
          and drag_store.symbols_in(DEFAULT_GROUP) == ["600005", "600004"])
    _drag_reopened = WatchlistStore(str(tmp / "drag.json"))
    check("重排结果落盘、可重启读回",
          _drag_reopened.symbols_in("A组") == list(reversed(_a_before)))

    # ---- 组合当日涨跌（v6.24 · §7-B8 R3）：等权 + 缺数据不算 + ⚠ ----
    import pandas as _pd

    from data.watchlist_change import (ChangeSnapshot, baseline_date, direction_of,
                                       format_pct, group_summary, last_bar)

    def _bars(pairs):
        """`[(日期, 收盘), ...]` → 日线表（只造组合涨跌用得到的列）。"""
        return _pd.DataFrame({"date": [d for d, _c in pairs],
                              "close": [c for _d, c in pairs]})

    check("单只：末根涨跌幅 = 末收 / 前收 − 1",
          abs(last_bar(_bars([("2026-09-16", 100.0), ("2026-09-17", 101.23)]))[1] - 1.23) < 1e-9)
    check("单只：只有 1 根 / 空表 / None ⇒ 涨跌幅 None（**算不出来 ≠ 0%**）",
          last_bar(_bars([("2026-09-17", 10.0)]))[1] is None
          and last_bar(_bars([]))[1] is None and last_bar(None)[1] is None)
    check("单只：日期截到 YYYY-MM-DD（带时间的值也截）",
          last_bar(_bars([("2026-09-16", 10.0), ("2026-09-17 00:00:00", 11.0)]))[0] == "2026-09-17")
    check("单只：收盘缺失的行被跳过，日期跟着**有效根**走",
          last_bar(_pd.DataFrame({"date": ["2026-09-15", "2026-09-16", "2026-09-17"],
                                  "close": [10.0, None, 11.0]}))[0] == "2026-09-17")

    _snap = {
        "AAA": {"date": "2026-09-17", "pct": 1.0, "reason": ""},
        "BBB": {"date": "2026-09-17", "pct": 3.0, "reason": ""},
        "CCC": {"date": "", "pct": None, "reason": "没有行情数据（还没下载？）"},
        "DDD": {"date": "2026-09-10", "pct": 99.0, "reason": ""},   # 停牌：最后一天不是基准日
    }
    check("基准日 = 快照里最新的最后交易日（**不用系统时钟**，周末/节假日不会错）",
          baseline_date(_snap) == "2026-09-17" and baseline_date({}) == "")
    _sum = group_summary(_snap, ["AAA", "BBB", "CCC", "DDD"])
    check("★ 等权平均：只对「算得出来」的票取平均（+1% / +3% ⇒ +2.00%）",
          abs(_sum["pct"] - 2.0) < 1e-9 and _sum["counted"] == 2 and _sum["total"] == 4)
    check("★ 缺数据的票**从分母里剔除**：绝不是拿 0% 冲淡（否则会变成 +1.00%）",
          abs(_sum["pct"] - 1.0) > 0.5)
    check("★ 停牌的票也不冒充今天：最后一天 ≠ 基准日的 ⇒ 不算它",
          "DDD" in dict(_sum["missing"]) and abs(_sum["pct"] - 50.0) > 1.0)
    check("⚠ 明细说得出「是哪一只、为什么」（未下载 vs 最后一天不是基准日）",
          dict(_sum["missing"])["CCC"].startswith("没有行情数据")
          and "最后一天是 2026-09-10" in dict(_sum["missing"])["DDD"])
    check("一只都算不出来 ⇒ pct is None（**与「涨跌 0%」必须能分辨**）",
          group_summary(_snap, ["CCC", "DDD"])["pct"] is None
          and group_summary({}, ["AAA"])["pct"] is None)
    check("空分组 ⇒ 0 只、pct None（不崩）",
          group_summary(_snap, [])["pct"] is None and group_summary(_snap, [])["total"] == 0)
    check("给了权重就按权重算（为「组合配置」R4 留的口子）",
          abs(group_summary(_snap, ["AAA", "BBB"],
                            weights={"AAA": 3.0, "BBB": 1.0})["pct"] - 1.5) < 1e-9)
    check("格式化：涨带 +、跌用 U+2212、平写 0.00%、**None 写空串**",
          format_pct(0.823) == "+0.82%" and format_pct(-0.314) == "\u22120.31%"
          and format_pct(0.0) == "0.00%" and format_pct(None) == "")
    check("方向：平**不是涨**（把 0.00% 画成绿的会让人以为它在涨）",
          direction_of(1.0) is True and direction_of(-1.0) is False
          and direction_of(0.0) is None and direction_of(None) is None)

    _calls = []
    _cached = ChangeSnapshot(
        lambda symbol: (_calls.append(symbol) or
                        _bars([("2026-09-16", 10.0), ("2026-09-17", 11.0)])))
    _cached.build(["AAA", "BBB"])
    _cached.build(["AAA", "BBB"])
    check("★ 快照带 TTL 缓存：同一分钟内反复刷新**零 IO**（loader 只被调 2 次）",
          _calls == ["AAA", "BBB"])
    _cached.build(["AAA", "BBB"], force=True)
    check("force=True 绕过缓存（数据刚更新时用）", len(_calls) == 4)
    _cached.clear()
    _cached.build(["AAA"])
    check("clear 之后重新读（同步完成 / 换复权时清）", len(_calls) == 5)
    _broken = ChangeSnapshot(lambda symbol: (_ for _ in ()).throw(RuntimeError("boom")))
    check("单只读失败**不会让整页崩**：变成一条带原因的缺失",
          _broken.build(["AAA"])["AAA"]["pct"] is None
          and "读取失败" in _broken.build(["AAA"])["AAA"]["reason"])

    # ---- 图层/配方**单一真源**（v6.24 · §7-B8 R13）：内置 + 用户混排 ----
    from ui.widgets.layer_model import (BUILTIN_KEYS, DEFAULT_ENABLED, LayerModel,
                                        TARGET_MAIN, TARGET_SUB, formula_key,
                                        recipe_target)

    _recipes = [
        {"id": "r1", "name": "我的均线", "segments": [{"text": "MA(C,10)", "target": "main"}]},
        {"id": "r2", "name": "RSI 超买超卖",
         "segments": [{"text": "RSI(C,14)", "target": "sub1"}]},
        {"id": "r3", "name": "ma",        # ★ 故意与内置同名的配方
         "segments": [{"text": "MA(C,5)", "target": "sub2"}]},
        {"id": "r4", "name": "多段混的旧档",
         "segments": [{"text": "A", "target": "main"}, {"text": "B", "target": "sub1"}]},
        {"id": "r5", "name": "", "segments": [{"text": "空名", "target": "main"}]},
    ]
    _model = LayerModel(formulas=_recipes)
    check("模型 = 内置 4 项 + 用户配方，且**内置在前、你的在后**（用户原话的顺序）",
          _model.keys()[:4] == list(BUILTIN_KEYS)
          and _model.keys()[4:] == ["formula:r1", "formula:r2", "formula:r3", "formula:r4"])
    check("空名配方不进列表（坏数据不占位）", not _model.has(formula_key({"id": "r5"})))
    check("★ 用户配方 key 带前缀 ⇒ **把配方起名叫「ma」也不会与内置撞库**",
          _model.has("formula:r3") and _model.label("formula:r3") == "ma"
          and _model.label("ma") == "均线 MA" and _model.is_builtin("ma"))
    check("去处只有两类：全 main 段 ⇒ 主图；含副图段 ⇒ 副图",
          recipe_target(_recipes[0]) == TARGET_MAIN
          and recipe_target(_recipes[1]) == TARGET_SUB
          and recipe_target(_recipes[3]) == TARGET_SUB)
    check("分类与顺序：主图区 = 内置 MA/BOLL + 我的均线；副图区 = 内置量/MACD + 三条配方",
          [item["key"] for item in _model.items_for(TARGET_MAIN)]
          == ["ma", "boll", "formula:r1"]
          and [item["key"] for item in _model.items_for(TARGET_SUB)]
          == ["volume", "macd", "formula:r2", "formula:r3", "formula:r4"])
    check("★ chips 候选池**从模型动态取**（配方库加一条，工具行立刻能选到）",
          _model.pool_for(TARGET_SUB) == ("volume", "macd", "formula:r2", "formula:r3",
                                          "formula:r4")
          and _model.pool_of_key("formula:r2") == TARGET_SUB
          and _model.pool_of_key("ma") == TARGET_MAIN)
    check("默认开启与改造前初始态一致（量 = 开，MA/BOLL/MACD = 关）",
          _model.enabled_keys() == list(DEFAULT_ENABLED) == ["volume"])
    check("开关：未知 key 一律拒绝**且不记忆**（不许出现幽灵项）",
          _model.set_enabled("查无此项", True) is False
          and _model.enabled("查无此项") is False)
    _model.toggle("ma")
    check("toggle 返回操作后的状态，且按列表顺序枚举（顺序可预期）",
          _model.enabled("ma") and _model.enabled_keys() == ["ma", "volume"])
    check("内置项名称来自内置表（内置不改名 —— 改不了，也没有改名入口）",
          _model.label("boll") == "布林带 BOLL" and _model.is_builtin("boll")
          and not _model.is_builtin("formula:r1"))
    check("★ 有参数才有 ⚙：成交量没有参数 ⇒ **不给假入口**",
          _model.has_params("macd") and not _model.has_params("volume")
          and not _model.has_params("formula:r1"))
    check("参数默认值来自内置表（MA 5/20/60、MACD 12/26/9）",
          _model.params_of("ma") == {"周期1": 5, "周期2": 20, "周期3": 60}
          and _model.params_of("macd") == {"快线": 12, "慢线": 26, "信号": 9})
    check("★ 参数越界 / 非数字一律**拒绝且不改动**（R16 闸②的判据）",
          _model.set_param("macd", "快线", 0) is False
          and _model.set_param("macd", "快线", "abc") is False
          and _model.set_param("macd", "快线", 999) is False
          and _model.params_of("macd")["快线"] == 12)
    check("合法修改生效，且**引擎形参映射按名字走**（MA 三个参数打进 windows 元组）",
          _model.set_param("ma", "周期1", 8) and _model.set_param("ma", "周期3", 120)
          and _model.engine_options()["ma"] == {"windows": (8, 20, 120)})
    check("BOLL / MACD 的形参名各自独立（不共用一张映射表）",
          _model.set_enabled("boll", True) and _model.set_enabled("macd", True)
          and _model.engine_options()["boll"] == {"window": 20, "num_std": 2.0}
          and _model.engine_options()["macd"] == {"fast": 12, "slow": 26, "signal": 9})
    check("★ 未启用的内置项**不进引擎参数**（开关真的在起作用，不是摆设）",
          _model.set_enabled("boll", False)
          and "boll" not in _model.engine_options())
    check("整组参数体检给人话结果（带该参数自己的范围）",
          _model.validate_params("macd")[0] is True
          and _model.validate_params("volume") == (True, ""))
    check("一键恢复默认（R16 闸③）",
          _model.reset_params("ma") == {"周期1": 5, "周期2": 20, "周期3": 60})
    check("参数快照只含**有参数的**内置项（用户配方没有参数，不该混进去）",
          set(_model.params_snapshot()) == {"ma", "boll", "macd"})

    _dirty = LayerModel(formulas=_recipes, enabled=["ma", "查无此项", "formula:r2"],
                        params={"ma": {"周期1": 0, "查无此参数": 1}, "查无此项": {"a": 1}})
    check("★ 坏偏好被清洗：未知 key 丢掉、越界参数回落默认（绝不把脏值带进界面）",
          _dirty.enabled_keys() == ["ma", "formula:r2"]
          and _dirty.params_of("ma")["周期1"] == 5
          and "查无此参数" not in _dirty.params_of("ma"))
    check("分区枚举跳过空类（UI 不为空类画分区）",
          LayerModel(formulas=[]).items_by_target()
          and [target for target, _items in LayerModel(formulas=[]).items_by_target()]
          == [TARGET_MAIN, TARGET_SUB])

    # ---- 副图格位顺序（v6.24 · §7-B8 R7 第 1 步：换序只改格位、绝不改 target）----
    _om = LayerModel(formulas=_recipes)
    check("默认副图先后 = 内置量/MACD + 三条配方（顺序可预期）",
          _om.sub_order_keys()
          == ["volume", "macd", "formula:r2", "formula:r3", "formula:r4"])
    check("set_sub_order 重排副图返回 True（确有变化）",
          _om.set_sub_order(["formula:r4", "volume", "macd", "formula:r2", "formula:r3"]) is True)
    check("副图先后真的变了",
          _om.sub_order_keys()
          == ["formula:r4", "volume", "macd", "formula:r2", "formula:r3"])
    check("★ 换序**只改格位、绝不改 target**：副图成员全部仍是副图（R7 一致性口径）",
          all(_om.target_of(k) == TARGET_SUB for k in _om.sub_order_keys()))
    check("★ 换序不动主图集合（成员与顺序都不受影响）",
          [i["key"] for i in _om.items_for(TARGET_MAIN)] == ["ma", "boll", "formula:r1"])
    _om.set_enabled("macd", True)
    _om.set_enabled("formula:r4", True)
    check("enabled_keys(target=SUB) **按换序后的格位**枚举已启用项（渲染就吃这个顺序）",
          _om.enabled_keys(target=TARGET_SUB) == ["formula:r4", "volume", "macd"])
    check("set_sub_order 原地不动返回 False（不做无意义重排）",
          _om.set_sub_order(_om.sub_order_keys()) is False)
    _om2 = LayerModel(formulas=_recipes)
    check("move_sub 上移：macd 从第 2 格换到最前",
          _om2.move_sub("macd", -1) is True and _om2.sub_order_keys()[0] == "macd")
    check("move_sub 已在边界返回 False（上移越界不动）",
          _om2.move_sub("macd", -1) is False)
    check("move_sub 拒绝非副图条目（ma 在主图 ⇒ 不许跨类挪）",
          _om2.move_sub("ma", 1) is False)
    _om3 = LayerModel(formulas=_recipes, order=["formula:r2", "macd", "volume"])
    check("构造期 order 生效：偏好的三条排前面",
          _om3.sub_order_keys()[:3] == ["formula:r2", "macd", "volume"])
    check("★ 未出现在 order 里的副图**保持原相对顺序排到末尾**（新配方不会丢）",
          _om3.sub_order_keys()[3:] == ["formula:r3", "formula:r4"])
    check("order 里的未知 key 被忽略（坏偏好不产生幽灵格位）",
          LayerModel(formulas=_recipes, order=["查无此项", "volume"]).sub_order_keys()[0]
          == "volume")
    check("round-trip：拿快照再构造，顺序稳定不动（可安全持久化）",
          LayerModel(formulas=_recipes,
                     order=_om3.sub_order_keys()).sub_order_keys() == _om3.sub_order_keys())

    # ---- 斐波那契 / 文字：绘制 + **附属图元随主图元一起删**（§11.5-15 同类风险）----
    from data.annotations import KIND_FIB, KIND_TEXT, KIND_TREND
    from ui.widgets import chart_style as _chart_style
    from ui.widgets.annotation_layer import AnnotationLayer
    from ui.widgets.chart_host import ChartHost

    host = ChartHost(bottom_axis_mode='no_values', crosshair=True)
    host.resize(640, 420)
    host.move(200, 200)          # 钉死窗口位置：offscreen 下 viewport 尺寸会随窗口落点 ±1px 漂移，
                                 # 而 vline 的鼠标命中容差就是 1px 级（"时灵时不灵"的根源，v6.42 实锤）
    host.show()
    app.processEvents()
    annot_store = AnnotationStore(str(tmp / "annotations.json"))
    layer = AnnotationLayer(host, annot_store, period='daily')
    layer.bind('sh600000', pd.bdate_range('2024-01-01', periods=60))
    host.main_pane.view_box.setYRange(90, 120)
    app.processEvents()

    layer.set_tool(KIND_FIB)
    fib_item = layer.create_default()
    check("斐波那契落库", fib_item is not None and annot_store.count('sh600000') == 1)
    check("斐波那契主图元 = 可拖的两端手柄（LineSegmentROI）",
          layer._items[fib_item["id"]].__class__.__name__ == 'LineSegmentROI')
    check("斐波那契附属图元 = 7 档水平位 + 7 个标签",
          len(layer._extras[fib_item["id"]]) == 14)
    check("附属图元也挂进了窗格标注容器（不留无主图元）",
          len(host.main_pane.annotation_items) == 15)

    layer.delete(fib_item["id"])
    check("删除斐波那契：存储清空且**附属水平位一并消失**",
          annot_store.count('sh600000') == 0 and len(host.main_pane.annotation_items) == 0
          and fib_item["id"] not in layer._extras)

    layer.set_tool(KIND_TEXT)
    text_item = layer.create_default(text="压力位")
    check("文字标注落库并画出", text_item is not None
          and len(host.main_pane.annotation_items) == 1
          and layer._items[text_item["id"]].__class__.__name__ == '_ClickableText')
    check("文字标注可点选（有 clicked 回调 → 才能单独删）",
          callable(getattr(layer._items[text_item["id"]], "_on_click", None)))
    check("文字内容为空 → 不落库也不画（返回 None）",
          layer.create_default(text="   ") is None and annot_store.count('sh600000') == 1)

    # ---- v6.25：新类型的**回读坐标**（拖完存的是"日期 + 价"，不是图元内部状态）----
    layer.clear_all()
    layer.set_tool("rect")
    rect_item = layer.create_default()
    rect_graphic = layer._items[rect_item["id"]]
    rect_graphic.setPos((10.0, 95.0))
    rect_graphic.setSize((12.0, 10.0))
    layer._persist_from_view(rect_item["id"])
    _rect_pts = annot_store.get('sh600000', 'daily', rect_item["id"])["points"]
    check("★ 矩形回读 = 外接矩形两角点（存的是日期 + 价，不是 ROI 内部状态）",
          abs(_rect_pts[0][1] - 95.0) < 1e-6 and abs(_rect_pts[1][1] - 105.0) < 1e-6
          and _rect_pts[0][0] != _rect_pts[1][0])

    layer.clear_all()
    layer.set_tool("hband")
    band_item = layer.create_default()
    layer._items[band_item["id"]].setRegion((96.0, 106.0))
    layer._persist_from_view(band_item["id"])
    _band_pts = annot_store.get('sh600000', 'daily', band_item["id"])["points"]
    check("★ 价格带回读 = 两条价位（横向贯穿全图，日期只是锚点不被改写）",
          abs(_band_pts[0][1] - 96.0) < 1e-6 and abs(_band_pts[1][1] - 106.0) < 1e-6)

    layer.clear_all()
    layer.set_tool("cross")
    cross_item = layer.create_default()
    check("交叉线 = 水平线（主）+ 垂直线（附属），两条都能拖",
          len(layer._extras[cross_item["id"]]) == 1
          and layer._items[cross_item["id"]].__class__.__name__ == 'InfiniteLine')
    _cross_date = cross_item["points"][0][0]
    layer._items[cross_item["id"]].setValue(101.0)
    layer._persist_from_view(cross_item["id"])
    _cross_pts = annot_store.get('sh600000', 'daily', cross_item["id"])["points"]
    check("★ 交叉线回读 = 新价位 + 原日期（拖横线不该把日期也带走）",
          abs(_cross_pts[0][1] - 101.0) < 1e-6 and _cross_pts[0][0] == _cross_date)

    layer.clear_all()
    layer.set_tool("hray")
    hray_item = layer.create_default()
    _hx0 = layer._axis.date_to_index(hray_item["points"][0][0])
    _hx1 = layer._axis.date_to_index(hray_item["points"][1][0])
    _hy = hray_item["points"][0][1]
    layer._items[hray_item["id"]].setPoints([(_hx0, _hy), (_hx1, _hy + 7.0)])   # 故意拖歪
    layer._persist_from_view(hray_item["id"])
    _hray_pts = annot_store.get('sh600000', 'daily', hray_item["id"])["points"]
    _hray_view = [layer._host.main_pane.view_box.mapSceneToView(p)
                  for _h, p in layer._items[hray_item["id"]].getSceneHandlePositions()]
    check("★ 水平射线被拖歪：存的是水平的、**图上也回正成水平**（斜着就是骗人）",
          _hray_pts[0][1] == _hray_pts[1][1] == _hy
          and abs(_hray_view[0].y() - _hray_view[1].y()) < 1e-6)
    # 水平射线：把"延伸起点"拖回中途 ⇒ 附属射线必须**继续延伸到数据末尾**（代表"未来"）
    layer._items[hray_item["id"]].setPoints([(_hx0, _hy), (_hx0 + 12, _hy)])
    layer._rebuild(hray_item["id"])
    _hray_xs, _ = layer._extras[hray_item["id"]][0].getData()
    check("★ 水平射线**延伸到数据末尾**（它代表「未来」，第二点只是「从哪开始延伸」）",
          abs(_hray_xs[-1] - (layer._axis.size - 1)) < 1e-6
          and abs(_hray_xs[0] - (_hx0 + 12)) < 1e-6)

    layer.clear_all()
    layer.set_tool("channel")
    channel_item = layer.create_default()
    _channel_primary = layer._items[channel_item["id"]]
    check("★ 平行通道 = 基线（2 个可拖手柄）+ 宽度点（**不是**四角自由变形的多边形）",
          len(channel_item["points"]) == 3
          and len(_channel_primary.getSceneHandlePositions()) == 2)

    def _channel_geometry():
        """基线斜率 + 两条线的竖直间距（用来验证"平行"和"宽度"各自独立）。"""
        stored = annot_store.get('sh600000', 'daily', channel_item["id"])
        pts = stored["points"]
        xs = [layer._axis.date_to_index(p[0]) for p in pts]     # 存的是日期 ⇒ 先换回序号
        ys = [float(p[1]) for p in pts]
        return ((ys[1] - ys[0]) / (xs[1] - xs[0]) if xs[1] != xs[0] else 0.0,
                ys[2] - ys[0])

    _slope0, _width0 = _channel_geometry()
    _channel_primary.movePoint(_channel_primary.getHandles()[0],
                               (_channel_primary.getHandles()[0].pos().x(),
                                _channel_primary.getHandles()[0].pos().y() + 6.0),
                               finish=False)
    layer._rebuild(channel_item["id"])
    _slope1, _width1 = _channel_geometry()
    check("★ 拖基线端点 ⇒ **间距不变**（通道整体跟着走，这才是平行通道）",
          abs(_width1 - _width0) < 1e-6)
    _width_handle = next(e for e in layer._extras[channel_item["id"]]
                         if getattr(e, "_role", "") == "width")
    _width_handle.setPos(_width_handle.pos().x(), _width_handle.pos().y() + 4.0)
    layer._rebuild(channel_item["id"])
    _slope2, _width2 = _channel_geometry()
    check("★ 拖 ⇕ 宽度手柄 ⇒ **只改间距**（基线不动、斜率不变）",
          abs(_width2 - _width1 - 4.0) < 1e-6 and abs(_slope2 - _slope1) < 1e-9)
    check("★ 通道带填充（用户拍板：跟普通线要有区别、视觉上粗一档）",
          any(g.__class__.__name__ == '_FillBand'
              for g in layer._extras[channel_item["id"]]))
    # ---- v6.26 H-7 护栏（用户截图抓包：下线画成了水平线）----
    _par_xs, _par_ys = layer._extras[channel_item["id"]][2].getData()
    _par_slope = (_par_ys[-1] - _par_ys[0]) / (_par_xs[-1] - _par_xs[0])
    check("★ 平行通道的**下线与上线平行**（第一版把下线画成 `y1+dy` 的水平线 —— 基线越陡越明显）",
          abs(_par_slope - _slope2) < 1e-9)
    check("★ 填充画在两条线**底下**（顺序错 = 线被半透明色块罩住发灰）",
          layer._extras[channel_item["id"]][0].__class__.__name__ == '_FillBand'
          and layer._extras[channel_item["id"]][1].__class__.__name__ == 'PlotDataItem')
    check("★ 填充透明度**封顶**（用户实测高饱和填充盖住 K 线 ⇒ 唯一口径在 chart_style）",
          _chart_style.FILL_ALPHA <= 25 and _chart_style.FILL_ALPHA_ON <= 45
          and layer._extras[channel_item["id"]][0].brush().color().alpha() <= 45)

    # ---- v6.26 STEP 4：最后 5 种（回归通道 / 甘氏扇形 / 斐波弧 / 波浪 / 头肩）----
    # 回归通道需要收盘价 ⇒ 重新 bind 一次（与页面 `render_charts` 的喂法一致）
    _closes = [100.0 + 0.2 * i for i in range(60)]          # 一条干净的直线（斜率 0.2）
    layer.bind('sh600000', pd.bdate_range('2024-01-01', periods=60), closes=_closes)
    layer.set_tool("reg_channel")
    reg_item = layer.create_default()
    check("★ 回归通道：中线（主图元）+ 上下轨 + 填充带（±2σ 由**收盘价回归**算出来）",
          reg_item is not None and len(layer._extras[reg_item["id"]]) >= 4
          and any(g.__class__.__name__ == '_FillBand'
                  for g in layer._extras[reg_item["id"]]))

    # ★v6.29（用户拍板："正常通道线应该分为三端：起点、终点、还有通道区间"）：
    #   带噪声的收盘价才看得出"带宽"，用干净直线会把 σ 算成 0（通道退化成一条线）。
    _noisy = [100.0 + 0.2 * i + (2.0 if i % 3 == 0 else -1.0) for i in range(60)]
    layer.bind('sh600000', pd.bdate_range('2024-01-01', periods=60), closes=_noisy)
    vb = host.main_pane.view_box
    layer.set_tool("reg_channel")
    reg_item = layer.create_default()
    reg_id = reg_item["id"]
    reg_graphic = layer._items[reg_id]

    def _reg_rails():
        """两条轨（虚线）—— 附属图元里只有它俩带数据曲线。"""
        return [g for g in layer._extras[reg_id] if hasattr(g, "getData")]

    def _reg_band():
        """图上真实的带宽（两条轨在中线两侧的间距 / 2），**不看存储**。"""
        rails = _reg_rails()
        return None if len(rails) < 2 else abs(
            rails[0].getData()[1][0] - rails[1].getData()[1][0]) / 2.0

    check("★ 回归通道 = **三端**（起点 / 终点定拟合区间 + 第三点=通道区间）",
          len(reg_item["points"]) == 3)
    _default_xs = sorted([layer._axis.date_to_index(p[0]) for p in reg_item["points"][:2]])
    _sigma_band = regression_channel(_noisy, _default_xs[0], _default_xs[1])["band"]
    _visible_floor = (vb.viewRange()[1][1] - vb.viewRange()[1][0]) * 0.05
    check("★ 通道区间点默认落在**自动 ±2σ** 上（σ 小到看不见时兜一个 5% 屏高，"
          "否则通道退化成一条线）",
          abs(_reg_band() - max(_sigma_band, _visible_floor)) < 1e-6)

    # （a）拖宽度手柄 ⇒ 整个通道按新带宽重画
    _reg_handle = next(g for g in layer._extras[reg_id]
                       if getattr(g, "_role", "") == "width")
    _reg_handle.setPos(_reg_handle.pos().x(), _reg_handle.pos().y() + 4.0)
    _dragged_y = float(_reg_handle.pos().y())
    layer._rebuild(reg_id)
    _reg_pts_band = annot_store.get('sh600000', 'daily', reg_id)["points"]
    _band_xs = sorted([layer._axis.date_to_index(p[0]) for p in _reg_pts_band[:2]])
    _band_fit = regression_channel(_noisy, _band_xs[0], _band_xs[1])
    _x3 = layer._axis.date_to_index(str(_reg_pts_band[2][0]))
    _mid3 = _band_fit["start"] + _band_fit["slope"] * (_x3 - _band_xs[0])
    check("★ 拖「通道区间」（第三端 / ⇕）⇒ 带宽点落库 + 上下轨按新带宽重画",
          abs(float(_reg_pts_band[2][1]) - _dragged_y) < 1e-6
          and abs(_reg_band() - abs(_dragged_y - _mid3)) < 1e-6)

    # （b）拖起点/终点 ⇒ 区间变了，**中线必须重新贴回回归结果**
    #     （用户原话："一旦调整回归通道线后整个通道也并不会进行相对应的调整"）
    _h0 = reg_graphic.getHandles()[0]
    reg_graphic.movePoint(_h0, (_h0.pos().x() - 8.0, _h0.pos().y() + 3.0), finish=False)
    layer._rebuild(reg_id)
    _reg_pts = annot_store.get('sh600000', 'daily', reg_id)["points"]
    _new_xs = sorted([layer._axis.date_to_index(p[0]) for p in _reg_pts[:2]])
    _fit = regression_channel(_noisy, _new_xs[0], _new_xs[1])
    _handle_views = [vb.mapSceneToView(p) for _h, p in
                     reg_graphic.getSceneHandlePositions()]
    check("★ 拖起点/终点后：中线**重新贴回回归结果**（否则出现「中线在 A、上下轨在 B」的分裂）",
          abs(float(_reg_pts[0][1]) - _fit["start"]) < 1e-6
          and abs(float(_reg_pts[1][1]) - _fit["end"]) < 1e-6
          and sorted(round(view.y(), 6) for view in _handle_views)
          == sorted([round(_fit["start"], 6), round(_fit["end"], 6)]))
    check("★ 拖起点/终点后：上下轨跟着**新区间**走（整个通道一起动，不是只有中线动）",
          abs(_reg_rails()[0].getData()[0][0] - _new_xs[0]) < 1e-6)
    check("回归通道没数据/区间退化时**画不出来**（不编造数据，§10-4）",
          regression_channel(None, 0, 10) is None
          and regression_channel([1.0, 2.0], 0, 0) is None
          and regression_channel([1.0, 2.0], 0, 1)["band"] == 0.0)  # 2 根 ⇒ 退化成连线
    check("回归通道：最小二乘对直线**精确**（斜率/截距无偏）",
          abs(regression_channel([10.0, 11.0, 12.0, 13.0], 0, 3)["slope"] - 1.0) < 1e-9
          and abs(regression_channel([10.0, 11.0, 12.0, 13.0], 0, 3)["band"]) < 1e-9)

    # ---- 甘氏扇形（★v6.28 重做：两点可拖，参考线 = 1×1，方向/比例全由用户定）----
    from data.annotations import GANN_FACTORS as _GANN_FACTORS
    from data.annotations import gann_label as _gann_label

    layer.clear_all()
    vb = host.main_pane.view_box
    vb.setXRange(0, 59, padding=0)
    vb.setYRange(60.0, 160.0, padding=0)
    app.processEvents()
    layer.set_tool("fan")
    fan_item = layer.create_default()
    fan_graphic = layer._items[fan_item["id"]]

    def _rays():
        return [g for g in layer._extras[fan_item["id"]] if hasattr(g, "getData")]

    def _slopes():
        return sorted((g.getData()[1][-1] - g.getData()[1][0])
                      / (g.getData()[0][-1] - g.getData()[0][0]) for g in _rays())

    def _ref_slope():
        """用户画的那条参考线（= 1×1）的数据斜率。"""
        stored = annot_store.get('sh600000', 'daily', fan_item["id"])["points"]
        xs = [layer._axis.date_to_index(p[0]) for p in stored]
        ys = [float(p[1]) for p in stored]
        return (ys[1] - ys[0]) / (xs[1] - xs[0])

    check("★ 扇形 = **两点可拖**（起点 + 参考点）⇒ 用户能调整（不是只读的自动图形）",
          len(fan_graphic.getSceneHandlePositions()) == 2)
    check("★ 扇形 = 9 条经典倍率射线，方向**完全跟着用户拖的参考线**（不再自动上下对称）",
          len(_rays()) == 9 and all(s > 0 for s in _slopes()))
    check("★ 1×1 那条 = 用户画的参考线本身（拖第二点 = 直接改比例）",
          any(abs(s - _ref_slope()) < 1e-9 for s in _slopes())
          and len(_GANN_FACTORS) == 9 and _gann_label(1.0) == "1×1"
          and _gann_label(2.0) == "2×1" and _gann_label(0.125) == "1×8")
    _gann_xs, _ = _rays()[0].getData()
    check("★ 扇形的射线**延伸到数据末尾**（画的就是未来支撑/压力位）",
          abs(_gann_xs[-1] - (layer._axis.size - 1)) < 1e-6)

    _pivot_price = float(annot_store.get('sh600000', 'daily', fan_item["id"])["points"][0][1])
    _ref_handle = fan_graphic.getHandles()[1]
    fan_graphic.movePoint(_ref_handle, (_ref_handle.pos().x(), _pivot_price - 8.0), finish=False)
    layer._rebuild(fan_item["id"])
    check("★ 把参考点往**下**拖（低于起点）⇒ 整个扇形翻到下方（未来支撑；不自动上下对称）",
          len(_rays()) == 9 and all(s < 0 for s in _slopes()))

    layer.clear_all()
    layer.set_tool("fib_fan")
    ffan_item = layer.create_default()
    _ffan_xs, _ = layer._extras[ffan_item["id"]][0].getData()
    check("★ 斐波扇形同样是**射线**（用户：扇形的线段代表未来可能的支撑位，必须延伸）",
          abs(_ffan_xs[-1] - (layer._axis.size - 1)) < 1e-6)

    # ★v6.27 真事故（用户报"扇形线无法在图片中画出"）：**预览图元压在光标下时，点图必须仍能落点**
    #   根因：`_ClickableText` 家族"按下就 accept"，场景**根本不会发 `sigMouseClicked`**
    #   （实测：压在文字图元上 = 收不到；压在 ROI 手柄上 = 收得到）⇒ 预览标记正好画在光标处
    #   ⇒ 用户"怎么点都落不了地"。修法 = 预览图元一律 `setAcceptedMouseButtons(NoButton)`。
    #   ⚠ 这条必须用**真实鼠标事件**测：`session.on_click()` 是绕开事件系统的，测不出这个坑。
    from PyQt6.QtTest import QTest

    layer.clear_all()
    layer.set_tool("marker")     # 单点 + 文字类主图元（预览同样画在光标下，同一种坑）
    _vb = host.main_pane.view_box
    _target = _vb.mapViewToScene(pg.QtCore.QPointF(20.0, 100.0))
    _center = pg.QtCore.QPoint(int(_target.x()), int(_target.y()))
    # 等价"鼠标移到这里"：让预览真的出现在光标下（离屏环境 QTest.mouseMove 不产生 mousemove）
    layer._session.on_move(layer._axis.index_to_date(20.0), 100.0)
    app.processEvents()
    _preview_before = len(layer._session._preview)
    QTest.mouseClick(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                     pg.QtCore.Qt.KeyboardModifier.NoModifier, _center)
    app.processEvents()
    check("★ 预览压在光标下，点图**仍能落点**（修前：预览把点击吃掉 ⇒ 怎么点都画不出来）",
          _preview_before > 0 and layer.count() == 1 and not layer.drawing)

    # ★v6.28：**文字类图元的"拖动 + 点选"必须用真实鼠标事件验**（旧断言手搓假事件 ⇒
    #   两条路径其实一次都没跑过，用户实测"写上去后无法移动"——§11.5-49/50）。
    from PyQt6.QtTest import QTest as _QTest

    layer.clear_all()
    layer.set_tool("marker")
    _drag_item = layer.create_default()
    layer.set_tool("")          # 画完回浏览模式（页面就是这么做的）⇒ 图元恢复响应鼠标
    _drag_graphic = layer._items[_drag_item["id"]]
    _before_xy = (_drag_graphic.pos().x(), _drag_graphic.pos().y())
    _scene_pt = _drag_graphic.mapToScene(_drag_graphic.boundingRect().center())
    _start = pg.QtCore.QPoint(int(_scene_pt.x()), int(_scene_pt.y()))
    _QTest.mousePress(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                      pg.QtCore.Qt.KeyboardModifier.NoModifier, _start)
    for _step in (30, 60, 90):
        _QTest.mouseMove(host._glw.viewport(),
                         pg.QtCore.QPoint(_start.x() + _step, _start.y() - _step // 2))
    _QTest.mouseRelease(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                        pg.QtCore.Qt.KeyboardModifier.NoModifier,
                        pg.QtCore.QPoint(_start.x() + 90, _start.y() - 45))
    app.processEvents()
    _after_xy = (_drag_graphic.pos().x(), _drag_graphic.pos().y())
    _stored_after = annot_store.get('sh600000', 'daily', _drag_item["id"])["points"][0]
    check("★ 文字类标注（标记/文字/价格标签）**用真实鼠标能拖动**，且松手后坐标落库",
          abs(_after_xy[0] - _before_xy[0]) > 1e-6 and abs(_after_xy[1] - _before_xy[1]) > 1e-6
          and abs(float(_stored_after[1]) - _after_xy[1]) < 1e-6)

    # ★v6.28：**32 种逐个**用真实鼠标验"拖得动 + 选得中"。
    #   为什么要有这条：扇形线的"拖不动/选不中"就是因为"只断言了能画出来、没断言能操作"。
    layer.clear_all()
    vb.setXRange(0, 59, padding=0)
    vb.setYRange(60.0, 160.0, padding=0)
    app.processEvents()

    def _grab_point(graphic):
        """从哪儿下爪：区间带取边线、ROI 取第一个手柄、无限直线取"窗口中线处"、其余取中心。

        ⚠ 坐标一律用**图元自己的映射**（`mapToScene`），不要自己拿 `view_box` 反算 ——
        后者在"布局还没落定/视图被别处改过"时会差几像素，1px 宽的线就点不中了（实测踩过）。
        ⚠ **handle 也可能在视图上下边缘**（vline 的拖点贴顶/底，1px 舍入就飘出绘图区 ——
        v6.42 实锤的 flaky 根源）：贯穿型图元（InfiniteLine）的垂直坐标一律拉回
        主 viewbox 中心 —— 线上任何一点都能拖，取中线永远命中。
        """
        if graphic.__class__.__name__ == "_RegionBand":
            graphic = graphic.lines[0]
        handles = getattr(graphic, "getSceneHandlePositions", None)
        if handles:
            positions = [p for _h, p in handles()]
            if positions:
                p0 = positions[0]
                if hasattr(graphic, "value") and getattr(graphic, "angle", None) is not None:
                    vb_c = host._glw.mapFromScene(vb.sceneBoundingRect().center())
                    if abs(getattr(graphic, "angle", 1)) == 90:      # 竖线：y 取中线
                        return pg.QtCore.QPoint(round(p0.x()), round(vb_c.y()))
                    if getattr(graphic, "angle", 1) == 0:            # 横线：x 取中线
                        return pg.QtCore.QPoint(round(vb_c.x()), round(p0.y()))
                return pg.QtCore.QPoint(round(p0.x()), round(p0.y()))
        rect = host._glw.viewport().rect()
        if hasattr(graphic, "value"):                    # InfiniteLine
            vertical = abs(getattr(graphic, "angle", 0)) == 90
            (vx0, vx1), (vy0, vy1) = vb.viewRange()
            probe = (pg.QtCore.QPointF(graphic.value(), (vy0 + vy1) / 2.0) if vertical
                     else pg.QtCore.QPointF((vx0 + vx1) / 2.0, graphic.value()))
            pt = graphic.mapToScene(probe)
            # ⚠ 垂直方向取**主 viewbox 中心的视口坐标**（必定在绘图区内、线上），
            #   旧版用 viewport().center() —— 窗口位置一变就踩到 1px 命中容差边缘（v6.42）；
            #   坐标用 round 而非 int 截断。
            vb_c = host._glw.mapFromScene(vb.sceneBoundingRect().center())
            point = (pg.QtCore.QPoint(round(pt.x()), round(vb_c.y())) if vertical
                     else pg.QtCore.QPoint(round(vb_c.x()), round(pt.y())))
            if rect.contains(point):
                return point
        pt = graphic.mapToScene(graphic.boundingRect().center())
        return pg.QtCore.QPoint(int(pt.x()), int(pt.y()))

    from ui.widgets.annotation_shapes import DRAWABLE_KINDS as _SWEEP_KINDS
    from ui.widgets.annotation_shapes import spec_of as _spec_of

    layer._ask_text = lambda _kind: "扫描测试"      # 文字/评论气泡要内容，别让它弹窗
    _drag_bad, _select_bad = [], []
    for _kind in _SWEEP_KINDS:
        layer.clear_all()
        layer.set_tool(_kind)
        _spec = _spec_of(_kind)
        _spots = [(20.0, 100.0), (40.0, 120.0), (30.0, 80.0), (50.0, 130.0), (55.0, 70.0)]
        _item = None
        for _index in range(_spec.points):
            _x, _y = _spots[_index % len(_spots)]
            _item = layer._session.on_click(layer._axis.index_to_date(_x), _y)
        if _item is None:
            _drag_bad.append(_kind + "(建不出来)")
            continue
        layer.set_tool("")                       # 画完回浏览模式
        _before = annot_store.get('sh600000', 'daily', _item["id"])["points"]
        _start = _grab_point(layer._items[_item["id"]])
        _QTest.mousePress(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                          pg.QtCore.Qt.KeyboardModifier.NoModifier, _start)
        app.processEvents()
        _end = pg.QtCore.QPoint(_start.x() + 50, _start.y() + 25)
        for _ratio in (0.5, 1.0):
            _QTest.mouseMove(host._glw.viewport(),
                             pg.QtCore.QPoint(int(_start.x() + 50 * _ratio),
                                              int(_start.y() + 25 * _ratio)))
            app.processEvents()
        _QTest.mouseRelease(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                            pg.QtCore.Qt.KeyboardModifier.NoModifier, _end)
        app.processEvents()
        if annot_store.get('sh600000', 'daily', _item["id"])["points"] == _before:
            _drag_bad.append(_kind)
        layer.select("")
        _QTest.mouseClick(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                          pg.QtCore.Qt.KeyboardModifier.NoModifier,
                          _grab_point(layer._items[_item["id"]]))
        app.processEvents()
        if layer.selected_id != _item["id"]:
            _select_bad.append(_kind)

    check(f"★ {len(_SWEEP_KINDS)} 种**逐个**用真实鼠标验：拖得动（{_drag_bad or '全通过'}）",
          not _drag_bad)
    check(f"★ {len(_SWEEP_KINDS)} 种**逐个**用真实鼠标验：点得中、能单独删"
          f"（{_select_bad or '全通过'}）", not _select_bad)
    layer.clear_all()

    # 单独再放一个标记验证"点一下就选中"（上面的扫描把图元都清掉了）
    layer.clear_all()
    layer.set_tool("marker")
    _drag_item = layer.create_default()
    layer.set_tool("")
    _drag_graphic = layer._items[_drag_item["id"]]
    app.processEvents()
    layer.select("")
    _now_pt = _drag_graphic.mapToScene(_drag_graphic.boundingRect().center())
    _QTest.mouseClick(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                      pg.QtCore.Qt.KeyboardModifier.NoModifier,
                      pg.QtCore.QPoint(int(_now_pt.x()), int(_now_pt.y())))
    app.processEvents()
    check("★ 文字类标注**点一下就选中**（原地点击 = 选中，不是拖动）",
          layer.selected_id == _drag_item["id"])
    layer.clear_all()
    layer.clear_all()

    layer.set_tool("fib_arc")
    arc_item = layer.create_default()
    check("★ 斐波弧：按**屏幕半径**画同心弧（数据坐标里画圆会被拉扁 ⇒ 采样成折线）",
          arc_item is not None and len(layer._extras[arc_item["id"]]) >= 2
          and len(layer._extras[arc_item["id"]][0].getData()[0]) > 10)
    # ★v6.29 自查：斐波弧是**最后一个**"依赖视图"的类型 ⇒ 缩放必须真的重算
    #   （否则"屏幕半径"这个换算就是画一次算死，缩放后弧就变形了）
    _arc_id = arc_item["id"]

    def _arc_shape():
        """把每条弧的 x/y 都抓下来（⚠ 只有 y 会随纵向缩放变 —— 只抓 x 会"看着没变"）。"""
        return [(list(seg.getData()[0]), list(seg.getData()[1]))
                for seg in layer._extras[_arc_id] if hasattr(seg, "getData")]

    _arc_before = _arc_shape()
    vb.setYRange(90.0, 110.0, padding=0)     # 纵向放大 ⇒ 每 1 元的像素数变了
    app.processEvents()
    layer._view_scale = (0.0, 0.0)           # 绕开 2% 节流（不然断言测的是节流不是重算）
    layer._on_view_changed(_arc_id)
    _arc_after = _arc_shape()
    check("★ 斐波弧：缩放后**真的重算**（「屏幕半径」的换算变了，弧就必须跟着变）",
          _arc_before != _arc_after)

    # ★v6.29 自查（用户："画线工具还有没有其他问题…自查自改"）①
    #   通道的 ⇕ 宽度手柄**用真实鼠标能拖** —— 这是"三端可调"唯一入口，
    #   拖不动的话"通道区间"就是画给人看的（v6.28 修 `_ClickableText` 之前它一直是死的）。
    layer.clear_all()
    # ⚠ ① 先把可视区间摆正：**画在屏幕外的图元，真实鼠标永远点不到**（这条咬过我两次）；
    #   ② 第三点要**离开前两个手柄**（宽度手柄若压在中线端点上，真实鼠标会先抓到 ROI 手柄，
    #      测的就不是"带宽可调"了）
    vb.setXRange(0, 59, padding=0)
    vb.setYRange(60.0, 160.0, padding=0)
    app.processEvents()
    for _kind, _spots in (("channel", ((20.0, 100.0), (40.0, 120.0), (20.0, 110.0))),
                          ("reg_channel", ((20.0, 100.0), (40.0, 120.0), (55.0, 145.0)))):
        layer.set_tool(_kind)
        _conf = None
        for _x, _y in _spots:
            _conf = layer._session.on_click(layer._axis.index_to_date(_x), _y)
        layer.set_tool("")
        _handle = next((g for g in layer._extras[_conf["id"]]
                        if getattr(g, "_role", "") == "width"), None)
        _p0 = annot_store.get('sh600000', 'daily', _conf["id"])["points"][2][1]
        if _handle is None:
            check(f"★ {_kind}：有 ⇕ 宽度手柄（通道区间可调）", False)
            continue
        _pt = _handle.mapToScene(_handle.boundingRect().center())
        _down = pg.QtCore.QPoint(int(_pt.x()), int(_pt.y()))
        _QTest.mousePress(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                          pg.QtCore.Qt.KeyboardModifier.NoModifier, _down)
        app.processEvents()
        _QTest.mouseMove(host._glw.viewport(),
                         pg.QtCore.QPoint(_down.x(), _down.y() + 30))
        app.processEvents()
        _QTest.mouseRelease(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                            pg.QtCore.Qt.KeyboardModifier.NoModifier,
                            pg.QtCore.QPoint(_down.x(), _down.y() + 30))
        app.processEvents()
        _p1 = annot_store.get('sh600000', 'daily', _conf["id"])["points"][2][1]
        check(f"★ {_kind}：⇕ 宽度手柄**用真实鼠标拖得动**、松手后通道区间落库"
              f"（{round(float(_p0), 3)} → {round(float(_p1), 3)}）",
              abs(float(_p1) - float(_p0)) > 1e-6)
        layer.clear_all()

    # ★v6.29 自查 ②：点选容差必须按**像素**算。
    #   旧实现把 6 当"数据单位"用 ⇒ 在 y 量程只有几元（甚至 0~1）的图上，
    #   6 个数据单位等于半屏，"点哪儿都算命中"（两条远处的线会互相抢选中）。
    vb.setXRange(0, 59, padding=0)
    vb.setYRange(60.0, 160.0, padding=0)
    app.processEvents()
    layer.set_tool("hline")          # ⚠ 每放一条都要重新选工具（画完自动回浏览模式，拍板①）
    _low = layer._session.on_click(layer._axis.index_to_date(20.0), 90.0)
    layer.set_tool("hline")
    _high = layer._session.on_click(layer._axis.index_to_date(20.0), 140.0)
    layer.set_tool("")

    def _click_price(price):
        _scene = vb.mapViewToScene(pg.QtCore.QPointF(20.0, float(price)))
        _QTest.mouseClick(host._glw.viewport(), pg.QtCore.Qt.MouseButton.LeftButton,
                          pg.QtCore.Qt.KeyboardModifier.NoModifier,
                          pg.QtCore.QPoint(int(_scene.x()), int(_scene.y())))
        app.processEvents()
        return layer.selected_id

    _pixel_y = vb.viewPixelSize()[1]
    check("★ 点上面那条就选上面那条、点下面那条就选下面那条（不是「谁先建谁被选中」）",
          _click_price(140.0) == _high["id"] and _click_price(90.0) == _low["id"])
    layer.select("")
    check("★ 离两条线都很远的地方点一下 ⇒ **谁都不该被选中**（容差是像素，不是数据单位）",
          _click_price(115.0) == "")
    layer.select("")
    check("★ 线**旁边 4 像素**内仍点得中（1px 的线肉眼根本点不准）",
          _click_price(140.0 + _pixel_y * 4.0) == _high["id"])
    layer.clear_all()

    layer.clear_all()
    layer.set_tool("wave")
    wave_item = layer.create_default()
    check("★ 波浪（降级版）：5 个拐点连成折线 + 浪序标签（**不做**自动识别）",
          wave_item is not None and len(wave_item["points"]) == WAVE_POINTS == 5
          and len(layer._items[wave_item["id"]].getSceneHandlePositions()) == 5)

    layer.clear_all()
    layer.set_tool("head_shoulder")
    hs_item = layer.create_default()
    check("★ 头肩形态（降级版）：左肩/头/右肩 三点 + 颈线（**写明「近似」，不假装精确**）",
          hs_item is not None and len(hs_item["points"]) == 3
          and len(layer._extras[hs_item["id"]]) >= 2)

    # ---- v6.26 H-7 护栏（用户实测：改了点位，文字标注停在原地不动）----
    # 波浪 / 头肩这类"带文字的类型"在 v6.26 第一版没有接"拖动 ⇒ 重建附属图元"，
    # 根因 = `rebuild` 靠每种类型自觉声明 ⇒ 现已删掉该字段，改成"有 deco 就重建"。
    def _hs_label_ys():
        return [round(g.pos().y(), 6) for g in layer._extras[hs_item["id"]]
                if isinstance(g, pg.TextItem)]

    _hs_graphic = layer._items[hs_item["id"]]
    _hs_handle = _hs_graphic.getHandles()[1]                  # "头"那个顶点
    _before = _hs_label_ys()
    _hs_graphic.movePoint(_hs_handle, (_hs_handle.pos().x(), _hs_handle.pos().y() + 8.0),
                          finish=False)
    layer._rebuild(hs_item["id"])
    _after = _hs_label_ys()
    check("★ 拖动顶点后，**文字标注跟着动**（左肩/头/右肩/颈线不能停在原地）",
          _after != _before and abs(_after[2] - _before[2]) > 1)

    layer.clear_all()
    layer.set_tool("wave")
    wave_item2 = layer.create_default()
    _w = layer._items[wave_item2["id"]]
    _w.movePoint(_w.getHandles()[2], (_w.getHandles()[2].pos().x(),
                                      _w.getHandles()[2].pos().y() + 5.0), finish=False)
    layer._rebuild(wave_item2["id"])
    _wave_label_ys = [g.pos().y() for g in layer._extras[wave_item2["id"]]
                      if isinstance(g, pg.TextItem)]
    check("★ 波浪的浪序标签同样**跟着拐点走**", len(_wave_label_ys) == WAVE_POINTS
          and abs(_wave_label_ys[2] - (float(wave_item2["points"][2][1]))) < 1e-6)
    layer.clear_all()

    layer.clear_all()
    layer.set_tool("arrow")
    arrow_item = layer.create_default()
    check("★ 箭头 = 线段 + 一个箭头头（附属图元，随主图元一起删）",
          len(layer._extras[arrow_item["id"]]) == 1
          and layer._extras[arrow_item["id"]][0].__class__.__name__ == 'ArrowItem')
    layer.delete(arrow_item["id"])
    check("删箭头：箭头头跟着一起消失（不留没人管的小三角）",
          len(host.main_pane.annotation_items) == 0)

    # ★ 每种类型都要能"拖完写回存储"（读法不齐全 = 用户拖半天白拖，还不报错 ⇒ 最阴的 bug）
    from data.annotations import requires_text as _requires_text
    from ui.widgets.annotation_shapes import DRAWABLE_KINDS as _KINDS

    layer.clear_all()
    _read_fail = []
    for _kind in _KINDS:
        layer.set_tool(_kind)
        _it = layer.create_default(text="回读测试" if _requires_text(_kind) else "")
        if _it is None:
            _read_fail.append(f"{_kind}(建不出来)")
            continue
        layer._persist_from_view(_it["id"])
        _stored = annot_store.get('sh600000', 'daily', _it["id"])
        if _stored is None or len(_stored["points"]) != len(_it["points"]):
            _read_fail.append(_kind)
        layer.delete(_it["id"])
    check(f"★ {len(_KINDS)} 种**每一种**拖完都能把坐标写回存储（读法齐全）{_read_fail}",
          not _read_fail)

    layer.clear_all()
    layer.set_tool(KIND_TREND)
    layer.create_default()
    layer.set_tool("rect")
    layer.create_default()
    check("不同类型可共存", annot_store.count('sh600000') == 2)
    check("clear_all 把图元与存储一起清干净",
          layer.clear_all() == 2 and len(host.main_pane.annotation_items) == 0)
    host.close()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"自选股/新标注类型测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.13 · 复权口径（P8 收尾）+ 文字标注拖动 ==")
try:
    # ---- 1) 复权 -> 分区（UI 只认 zone_for_adjust，禁止自己拼字符串，§11.5-19）----
    from data.akshare_feed import ADJUST_NONE, ADJUST_QFQ, AkShareFeed
    from data.market_db import DataLakeManager
    from data.sync_service import (ADJUST_LABELS, ZONE_KLINE, ZONE_KLINE_RAW,
                                   adjust_label, zone_for_adjust)

    check("复权常量与 akshare 的 adjust 参数取值一致（不自己造枚举）",
          ADJUST_QFQ == "qfq" and ADJUST_NONE == "")
    check("复权 -> 分区映射", zone_for_adjust(ADJUST_QFQ) == ZONE_KLINE
          and zone_for_adjust(ADJUST_NONE) == ZONE_KLINE_RAW
          and zone_for_adjust("乱写") == ZONE_KLINE_RAW)
    check("复权中文名", adjust_label("qfq") == "前复权" and adjust_label("") == "不复权"
          and ADJUST_LABELS[ADJUST_NONE] == "不复权")
    check("两个日线分区都已注册进数据湖",
          ZONE_KLINE in DataLakeManager().zones and ZONE_KLINE_RAW in DataLakeManager().zones)
    check("不复权分区与前复权分区**不是同一个目录**（否则会互相覆盖）",
          DataLakeManager().zones[ZONE_KLINE] != DataLakeManager().zones[ZONE_KLINE_RAW])

    # ---- 2) 抓取链路的 adjust 透传（打桩，不联网）----
    from data.sync_service import MarketSyncService
    captured = {}
    _orig_auto = AkShareFeed.fetch_daily_auto

    def _fake_auto(symbol, start_date=None, end_date=None, adjust=ADJUST_QFQ):
        captured.update(symbol=symbol, start_date=start_date, adjust=adjust)
        return pd.DataFrame()
    AkShareFeed.fetch_daily_auto = staticmethod(_fake_auto)
    try:
        MarketSyncService._fetch("600519", ZONE_KLINE, "20100101")
        qfq_adjust = captured.get("adjust")
        MarketSyncService._fetch("600519", ZONE_KLINE_RAW, "20100101")
        raw_adjust = captured.get("adjust")
    finally:
        AkShareFeed.fetch_daily_auto = staticmethod(_orig_auto)
    check("前复权分区 -> 拉取时显式传 adjust='qfq'", qfq_adjust == ADJUST_QFQ)
    check("不复权分区 -> 拉取时显式传 adjust=''", raw_adjust == ADJUST_NONE)

    # ---- 3) 文字标注拖动（直接测处理器：拖动跟随 + 松手才落盘）----
    from PyQt6.QtCore import QPointF

    from ui.widgets.annotation_layer import _ClickableText

    class _PressEvent:
        """⚠ v6.28：`_ClickableText` 现在走 **Qt 三件套**（press/move/release），
        不再需要手搓 pyqtgraph 假事件 —— 那段假事件测试正是因为"绕开真实事件系统"
        而让"拖不动"活了三个版本（§11.5-49）。这两个桩类保留只为兼容旧引用，不再使用。
        """
    # ---- 4) 拖完存到哪：x 映射回日期、y 存真实价（回读一致）----
    #   ★v6.28：**改用真实鼠标事件**。旧版是"手搓假事件直接调 mouseDragEvent"，
    #   于是"拖动"这条路径其实一次都没跑过（真机上根本收不到 drag），用户实测"无法移动"。
    from data.annotations import KIND_TEXT as _KIND_TEXT
    from pathlib import Path as _Path

    from ui.widgets.annotation_layer import AnnotationLayer
    from ui.widgets.chart_host import ChartHost

    drag_host = ChartHost(bottom_axis_mode='no_values', crosshair=True)
    drag_host.resize(640, 420)
    drag_host.show()
    app.processEvents()

    tmp_drag = _Path(tempfile.mkdtemp(prefix="jian_drag_smoke_"))
    drag_store = AnnotationStore(str(tmp_drag / "annotations.json"))
    drag_layer = AnnotationLayer(drag_host, drag_store, period='daily')
    drag_dates = pd.bdate_range('2024-01-01', periods=60)
    drag_layer.bind('sh600000', drag_dates)
    drag_layer.set_tool(_KIND_TEXT)
    drag_item = drag_layer.create_default(text="箱体上沿")
    drag_layer.set_tool("")          # 画完回浏览模式（页面就是这么做的）⇒ 图元恢复响应鼠标
    drag_graphic = drag_layer._items[drag_item["id"]]
    # ⚠ 起点必须落在**可视区内**（这张图没画数据 ⇒ y 量程就是 [0,1]）：
    #   真实鼠标事件打不到屏幕外的图元（旧版用 `setPos(25.5, 88.8)` 是"程序性摆放"，看不出这点）
    drag_layer._host.main_pane.view_box.setXRange(0, 59, padding=0)
    drag_layer._host.main_pane.view_box.setYRange(0.0, 1.0, padding=0)
    drag_graphic.setPos(25.5, 0.5)
    drag_layer._persist_from_view(drag_item["id"])   # 让"基线"就是 0.5（下面要验拖动前后）
    app.processEvents()

    _vp = drag_host._glw.viewport()
    _pt = drag_graphic.mapToScene(drag_graphic.boundingRect().center())
    _down = pg.QtCore.QPoint(int(_pt.x()), int(_pt.y()))
    _QTest.mousePress(_vp, pg.QtCore.Qt.MouseButton.LeftButton,
                      pg.QtCore.Qt.KeyboardModifier.NoModifier, _down)
    _QTest.mouseMove(_vp, pg.QtCore.QPoint(_down.x() + 10, _down.y() + 6))
    app.processEvents()
    _mid = drag_store.get('sh600000', 'daily', drag_item["id"])["points"][0][1]
    check("拖动过程中**不落盘**（拖动途中疯狂写文件是另一种坏）", _mid == 0.5)
    _QTest.mouseRelease(_vp, pg.QtCore.Qt.MouseButton.LeftButton,
                        pg.QtCore.Qt.KeyboardModifier.NoModifier,
                        pg.QtCore.QPoint(_down.x() + 40, _down.y() + 24))
    app.processEvents()
    stored = drag_store.get('sh600000', 'daily', drag_item["id"])
    check("★ 文字拖到哪就存哪（真实鼠标拖动 → x 按日期存、y 按真实价存）",
          stored["points"][0][1] != 0.5
          and abs(float(stored["points"][0][1]) - drag_graphic.pos().y()) < 1e-6
          and stored["points"][0][0] == drag_layer._axis.index_to_date(drag_graphic.pos().x()))
    reopened = AnnotationStore(str(tmp_drag / "annotations.json"))
    reloaded = reopened.get('sh600000', 'daily', drag_item["id"])
    check("重启后文字与位置都在（文字内容丢失会被模型层直接拒收，能读回=没丢）",
          reloaded is not None and reloaded["text"] == "箱体上沿"
          and reloaded["points"][0][1] == stored["points"][0][1])
    drag_host.close()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"复权/文字拖动测试执行失败: {type(e).__name__}: {e}", False)

print("== v6.15 · 坐标轴自适应（§7-B4）==")
try:
    from PyQt6.QtTest import QTest

    from ui.widgets.adaptive_axis import (attach_all, attach_date_axis, compute_ticks,
                                          compute_text_ticks, slice_span, visible_span)

    def _axis_strip_signature(image, rows=24):
        """底部若干像素的采样指纹 —— 轴重画过 ⇒ 指纹必变（"像素层面真的变了"）。"""
        step = max(1, rows // 8)
        return tuple(image.pixelColor(x, y).rgba()
                     for y in range(max(0, image.height() - rows), image.height(), step)
                     for x in range(0, image.width(), 4))

    # ---- 1) 纯函数：刻度密度 / 格式梯子（"放大后只剩一个刻度"的回归断言）----
    axis_dates = pd.bdate_range('2021-01-01', periods=800)
    wide_ticks = compute_ticks(axis_dates, 0, 799, width_px=900)
    narrow_ticks = compute_ticks(axis_dates, 300, 309, width_px=900)     # 只放 10 根
    check("放大到 10 根时仍有 ≥2 个刻度（不再只剩一个）", len(narrow_ticks) >= 2)
    check("刻度全部落在可视范围内", all(300 <= index <= 309 for index, _ in narrow_ticks))
    check("两端一定有刻度（左端 = 区间首、右端 = 区间尾）",
          narrow_ticks[0][0] == 300 and narrow_ticks[-1][0] == 309)
    check("同年 → 月-日格式（5 字符）", all(len(text) == 5 for _, text in narrow_ticks))
    check("跨年且 >90 根 → 年-月格式（不再年年重复）",
          all(len(text) == 7 and text[4] == '-' for _, text in wide_ticks))
    check("跨年但 ≤90 根 → 年-月-日（哪一天必须能辨）",
          all(len(text) == 10 for _, text in compute_ticks(axis_dates, 250, 330, width_px=900)))
    check("轴宽参与密度决策（同区间：宽轴刻度数 >= 窄轴）",
          len(compute_ticks(axis_dates, 0, 799, width_px=1200))
          >= len(compute_ticks(axis_dates, 0, 799, width_px=300)))
    check("轴上不出现 NaT / 空标签",
          all(text and 'NaT' not in text for _, text in wide_ticks + narrow_ticks))
    check("日期序列为空 → 不给刻度（不抛异常）", compute_ticks([], 0, 5) == [])

    intraday = pd.date_range('2025-06-03 09:30', periods=240, freq='min')
    check("日内数据 → 时分格式（将来分钟线只改公共件一处）",
          all(':' in text for _, text in compute_ticks(intraday, 0, 239, width_px=700)))

    ordinal = [f"{day}日" for day in range(1, 32)]
    ordinal_ticks = compute_text_ticks(ordinal, 0, 30, width_px=600)
    check(f"序数轴（资金 K 线「5日」）密度自适应：31 个标签自动稀疏到 "
          f"{len(ordinal_ticks)} 个（原来全写上会互相压字）",
          len(ordinal_ticks) <= 10 and ordinal_ticks[-1][1] == '31日'
          and len(compute_text_ticks(ordinal, 0, 30, width_px=120)) < len(ordinal_ticks))
    check("slice_span：NaN 自动忽略 / 全 NaN 返回 None",
          slice_span([1.0, np.nan, 3.0], [2.0, 9.0, np.nan], 0, 2) == (1.0, 9.0)
          and slice_span([np.nan], [np.nan], 0, 0) is None)

    # ---- 2) 整机：每个窗格的 y 跟随**可视区间**（"副图压成一条线"的回归）----
    from ui.widgets.chart_host import ChartHost

    axis_host = ChartHost(bottom_axis_mode='no_values', crosshair=False)
    axis_host.resize(700, 460)
    axis_host.show()
    app.processEvents()
    sub_pane = axis_host.add_pane('ind', fixed_height=120)
    app.processEvents()

    bars = 600
    axis_bars = pd.bdate_range('2022-01-03', periods=bars)
    price_low = np.full(bars, 100.0)
    price_high = np.full(bars, 110.0)
    sub_low = np.zeros(bars)
    sub_high = np.full(bars, 2.0)
    sub_high[500:] = 40.0          # 后段一根尖峰：全量 span 40，前段只有 2

    axes = attach_all(axis_host, axis_bars, {
        'main': lambda i0, i1: slice_span(price_low, price_high, i0, i1),
        'ind': lambda i0, i1: slice_span(sub_low, sub_high, i0, i1),
    })
    check("总管给每个窗格都挂了跟随器（含不显示刻度的副图）",
          set(axes.pane_names) == {'main', 'ind'})
    check("横轴刻度只挂在最下窗格（x 联动，其余窗格不重复写字）",
          axes.ticks_of('ind') != [] and axes.ticks_of('main') == [])

    main_vb = axis_host.main_pane.plot_item.getViewBox()
    main_vb.setXRange(400, 409, padding=0)
    app.processEvents()
    main_lo, main_hi = axes.handle('main').y_range
    ind_lo, ind_hi = axes.handle('ind').y_range
    check(f"主图 y 范围 == 可视窗口极值 ± padding（100~110 ⇒ 期望 99.4~110.6，"
          f"实测 {main_lo:.2f}~{main_hi:.2f}）",
          abs(main_lo - 99.4) < 0.3 and abs(main_hi - 110.6) < 0.3)
    check("副图 y 只跟可视窗口（前段极值 0~2 ⇒ 不再被后段 40 压成一条线）",
          (ind_hi - ind_lo) < 3.0)

    ticks_before = [text for _, text in axes.ticks_of('ind')]
    main_vb.setXRange(500, 509, padding=0)
    app.processEvents()
    spike_lo, spike_hi = axes.handle('ind').y_range
    check("缩放后 y 跟着变（尖峰区间 0~40 ⇒ 量程放大）", (spike_hi - spike_lo) > 30.0)
    check("缩放后刻度文本也变了（不是画完就冻住）",
          [text for _, text in axes.ticks_of('ind')] != ticks_before)

    main_vb.setXRange(0, 99, padding=0)
    QTest.qWait(30)
    app.processEvents()
    before_image = axis_host.grab().toImage()
    main_vb.setXRange(400, 409, padding=0)
    QTest.qWait(30)
    app.processEvents()
    after_image = axis_host.grab().toImage()
    check("底部轴像素随缩放变化（真的重画了，不是嘴上说）",
          _axis_strip_signature(before_image) != _axis_strip_signature(after_image))
    axis_host.close()

    # ---- 3) 幂等：同一条轴重复 attach 不会累积信号连接 ----
    idem_host = ChartHost()
    idem_host.resize(520, 320)
    idem_host.show()
    app.processEvents()
    idem_pane = idem_host.main_pane.plot_item
    idem_first = attach_date_axis(idem_pane, axis_bars)
    idem_second = attach_date_axis(idem_pane, axis_bars)
    check("重复 attach 同一条轴 → 旧跟随器自动摘掉（幂等，不泄漏信号连接）",
          idem_second.attached and not idem_first.attached)
    idem_second.detach()
    check("detach 之后彻底不再监听", not idem_second.attached)

    idem_vb = idem_host.main_pane.plot_item.getViewBox()
    idem_vb.setXRange(-50, 5000, padding=0)
    check("visible_span 把越界视图夹到 [0, n-1]（不会算出非法 bar 序号）",
          visible_span(idem_vb, 100) == (0, 99))
    idem_host.close()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"坐标轴自适应测试执行失败: {type(e).__name__}: {e}", False)

# ==========================================
# §7-B5 回测成交真实性：三档成交时点 / T+1 闸门 / 触发式委托 / 同根不重建仓（v6.18）
#   落地时先以一次性探针验证；此处是**正式移植版**。
#   ⚠ 原探针里"借 `git show HEAD` 的旧引擎做逐位回归"那段**故意不移植**：
#     提交后 HEAD 会变，断言会随仓库状态漂移 —— 改为对**手算期望值**断言，
#     强度等价且不依赖 git 状态（旧引擎的对照结论已记录在 §7-B5-E）。
# ==========================================
try:
    import re as _re

    from core.backtest import (FILL_CLOSE, FILL_MODE_LABELS, FILL_NEXT_OPEN,
                               FILL_TRIGGER, BacktestEngine, fill_mode_oneliner,
                               fill_summary, normalize_fill, tick_to_yuan, yuan_to_tick)
    from data.strategy_store import _signature

    def _risk_off(**kw):
        base = {'max_bars': 0, 'stop_loss_pct': 0.0, 'take_profit_pct': 0.0,
                'trailing_pct': 0.0}
        base.update(kw)
        return base

    def _bars(opens, highs, lows, closes):
        return pd.DataFrame({
            'date': pd.date_range('2024-01-02', periods=len(opens), freq='D'),
            'open': opens, 'high': highs, 'low': lows, 'close': closes,
            'volume': [10000.0] * len(opens)})

    def _bt(dfx, buy, sell, risk=None, fill_mode=FILL_NEXT_OPEN, tick=1):
        return BacktestEngine._run_on_signals(
            data=dfx, buy_signal=np.array(buy), sell_signal=np.array(sell),
            symbol='T', buy_expression='', sell_expression='',
            start_date='2024-01-01', end_date='2024-12-31', params={},
            commission_rate=0.0003,
            risk=risk if risk is not None else _risk_off(),
            fill_mode=fill_mode, trigger_tick=tick)

    def _keys(res):
        return [(t.entry_date, t.exit_date, round(t.entry_price, 9),
                 round(t.exit_price, 9), t.exit_reason,
                 getattr(t, 'deferred_t1', False)) for t in res.trades]

    print("\n[§7-B5] 三档成交时点各自落在正确的 K 线上")
    df_a = _bars([10.0, 11.0, 12.0, 13.0], [10.5, 11.5, 12.5, 13.5],
                 [9.5, 10.5, 11.5, 12.5], [10.2, 11.2, 12.2, 13.2])
    r = _bt(df_a, [True, False, False, False], [False] * 4, fill_mode=FILL_NEXT_OPEN)
    check("next_open：成交价 == 次日开盘 11.00", abs(r.trades[0].entry_price - 11.0) < 1e-9)
    check("next_open：成交根 == 信号根 +1", r.trades[0].entry_date == df_a['date'].iloc[1])

    r = _bt(df_a, [True, False, False, False], [False] * 4, fill_mode=FILL_CLOSE)
    check("close：成交价 == 当日收盘 10.20", abs(r.trades[0].entry_price - 10.2) < 1e-9)
    check("close：成交根 == 信号根本身", r.trades[0].entry_date == df_a['date'].iloc[0])

    df_t = _bars([10.0, 10.3, 10.4, 10.5], [10.5, 10.8, 10.9, 11.0],
                 [9.9, 10.2, 10.3, 10.4], [10.2, 10.6, 10.7, 10.8])
    r = _bt(df_t, [True, False, False, False], [False] * 4, fill_mode=FILL_TRIGGER, tick=1)
    check("trigger：盘中触达 → 按触发价 10.51 成交（不追到最高价）",
          len(r.trades) == 1 and abs(r.trades[0].entry_price - 10.51) < 1e-9)

    df_g = _bars([10.0, 11.0, 11.0, 11.0], [10.5, 11.5, 11.5, 11.5],
                 [9.9, 10.9, 10.9, 10.9], [10.2, 11.0, 11.0, 11.0])
    r = _bt(df_g, [True, False, False, False], [False] * 4, fill_mode=FILL_TRIGGER, tick=1)
    check("trigger：开盘跳空越过触发价 → 按开盘价 11.00 成交（不占便宜）",
          abs(r.trades[0].entry_price - 11.0) < 1e-9)

    df_m = _bars([10.0] * 4, [10.1, 10.05, 10.05, 10.05], [9.9] * 4, [10.0] * 4)
    r = _bt(df_m, [True, False, False, False], [False] * 4, fill_mode=FILL_TRIGGER, tick=1)
    check("trigger：一整天未触达 → 本次信号作废、零成交", len(r.trades) == 0)

    print("[§7-B5] T+1 闸门：进场当根触发风控不得当日离场")
    df_s = _bars([10.0, 10.0, 9.0, 10.0], [10.2, 10.1, 9.5, 10.2],
                 [9.9, 9.0, 8.8, 9.9], [10.0, 9.2, 9.0, 10.0])
    r = _bt(df_s, [True, False, False, False], [False] * 4,
            risk=_risk_off(stop_loss_pct=0.05))
    t0 = r.trades[0]
    check("止损在进场当根触发 → 未当日离场", t0.exit_date != t0.entry_date)
    check("顺延到最早可卖根（入场根 +1）", t0.exit_date == df_s['date'].iloc[2])
    check("按该根开盘价成交 9.00 —— 跳空低开就承受跳空", abs(t0.exit_price - 9.0) < 1e-9)
    check("离场原因仍记录为 stop_loss（没有被吞掉）", t0.exit_reason == 'stop_loss')
    check("该笔带 deferred_t1 标记（UI 可提示 T+1 顺延）", t0.deferred_t1 is True)
    check("[非空对照] 进场当根 low 9.00 确实击穿止损线 9.50",
          float(df_s['low'].iloc[1]) <= t0.entry_price * 0.95)

    df_k = _bars([10.0, 10.0, 10.6, 10.0], [10.2, 11.0, 10.8, 10.2],
                 [9.9, 9.9, 10.5, 9.9], [10.0, 10.8, 10.7, 10.0])
    r = _bt(df_k, [True, False, False, False], [False] * 4,
            risk=_risk_off(take_profit_pct=0.05))
    tk = r.trades[0]
    check("止盈在进场当根触及 → 同样顺延到最早可卖根开盘价 10.60",
          tk.exit_date == df_k['date'].iloc[2] and abs(tk.exit_price - 10.6) < 1e-9)
    check("原因保留 take_profit 且带 deferred_t1",
          tk.exit_reason == 'take_profit' and tk.deferred_t1 is True)

    df_b = _bars([10.0] * 4, [10.2, 10.1, 10.1, 10.1], [9.9] * 4, [10.0, 10.2, 10.3, 10.4])
    r = _bt(df_b, [True, False, False, False], [False] * 4, risk=_risk_off(max_bars=1))
    tb = r.trades[0]
    check("max_bars=1 在 T+1 下 == 次根收盘离场 10.30",
          tb.exit_reason == 'max_bars' and tb.exit_date == df_b['date'].iloc[2]
          and abs(tb.exit_price - 10.3) < 1e-9)
    check("max_bars 属收盘评估型，不打 T+1 顺延标记", tb.deferred_t1 is False)

    print("[§7-B5] 触发式卖单：触达才卖 / 未触达信号作废")
    df_sell = _bars([10.0, 10.0, 10.2, 10.0], [10.2, 10.3, 10.3, 10.2],
                    [9.9, 9.9, 9.0, 8.5], [10.0, 10.1, 9.5, 8.6])
    r = _bt(df_sell, [True, False, False, False], [False, False, True, False],
            fill_mode=FILL_TRIGGER, tick=1)
    ts = r.trades[0]
    check("触发式卖出：跌破触发价 8.99 才成交，原因=signal",
          ts.exit_reason == 'signal' and abs(ts.exit_price - 8.99) < 1e-9)
    check("成交落在信号根的下一根", ts.exit_date == df_sell['date'].iloc[3])

    df_hold = _bars([10.0, 10.0, 10.2, 10.2, 10.2], [10.2, 10.3, 10.3, 10.3, 10.3],
                    [9.9, 9.9, 9.8, 9.9, 9.9], [10.0, 10.1, 10.1, 10.1, 10.1])
    r = _bt(df_hold, [True, False, False, False, False],
            [False, False, True, False, False], fill_mode=FILL_TRIGGER, tick=1)
    check("触发式卖单未触达 → 本次信号作废、持仓延续到期末强平",
          len(r.trades) == 1 and r.trades[0].exit_reason == 'force_close')

    print("[§7-B5] 同根不重建仓（用户 2026-09-15 追加拍板）")
    df_x = _bars([10.0] * 5, [10.2] * 5, [9.9] * 5, [10.0, 10.5, 10.6, 10.7, 10.8])
    res_x = _bt(df_x, [True, True, True, False, False], [False, True, False, False, False])
    check("同根卖出后未在同一成交根（bar2 开盘 10.00）重建仓 —— 空转被掐掉",
          not any(t.entry_date == df_x['date'].iloc[2]
                  and abs(t.entry_price - 10.0) < 1e-9 for t in res_x.trades))
    check("该笔正常建仓（bar1）未被波及 —— 规则只拦同成交根",
          any(t.entry_date == df_x['date'].iloc[1] for t in res_x.trades))
    check("离场之后下一根的合法再入场照常允许（bar3 建仓存在）",
          any(t.entry_date == df_x['date'].iloc[3] for t in res_x.trades))
    res_c = _bt(df_x, [True, False, True, False, False], [False, True, False, False, False])
    check("[非空对照] 去掉 bar1 买入信号 → 交易序列完全一致（证明它被规则抑制了）",
          _keys(res_c) == _keys(res_x))

    df_y = _bars([10.0] * 4, [10.2] * 4, [9.9] * 4, [10.0, 10.1, 10.2, 10.3])
    res_y = _bt(df_y, [True, True, False, False], [False, True, False, False],
                fill_mode=FILL_CLOSE)
    check("close 档：同一收盘价买回同样被拦（bar1 无建仓）",
          not any(t.entry_date == df_y['date'].iloc[1] for t in res_y.trades))

    print("[§7-B5] 参数归一化 / 元↔跳换算 / 文案可懂性 / 签名兼容")
    check("缺省参数回落 next_open + 1 跳",
          normalize_fill(None, None) == {'fill_mode': FILL_NEXT_OPEN, 'trigger_tick': 1})
    check("非法值一律回落默认，不炸",
          normalize_fill('瞎写', -9) == {'fill_mode': FILL_NEXT_OPEN, 'trigger_tick': 1})
    check("1 跳 → 0.01 元", abs(tick_to_yuan(1) - 0.01) < 1e-12)
    check("0.03 元 → 3 跳 / 0 元 → 回落 1 跳",
          yuan_to_tick(0.03) == 3 and yuan_to_tick(0) == 1)
    r = _bt(df_a, [True, False, False, False], [False] * 4, fill_mode=FILL_TRIGGER, tick=2)
    check("BacktestResult 携带实际生效口径",
          r.fill_mode == FILL_TRIGGER and r.trigger_tick == 2)

    # 用户实测反馈（v6.18）："触发式条件单 / 触发跳数 完完全全看不懂"。
    # 判据 = 用户第一眼看到的文案里**不许出现行话**；「跳空」是交易者常用词，必须放行。
    jargon = [r'跳(?!空)', r'当根', r'K\s*线', r'条件单', r'回测引擎']
    check("[自检] 「跳空」不算行话（避免误伤常用词）",
          not [p for p in jargon if _re.search(p, '跳空低开')])
    for _mode in (FILL_NEXT_OPEN, FILL_CLOSE, FILL_TRIGGER):
        _label, _one = FILL_MODE_LABELS[_mode], fill_mode_oneliner(_mode, 1)
        check(f"下拉项「{_label}」不含行话",
              not [p for p in jargon if _re.search(p, _label)])
        check(f"行内说明「{_one[:18]}…」不含行话",
              not [p for p in jargon if _re.search(p, _one)])
    check("第三档把术语换算成用户量纲（出现 0.01 元）",
          '0.01 元' in fill_mode_oneliner(FILL_TRIGGER, 1))
    check("第三档讲清「没碰到会怎样」（不买也不卖）",
          '不买也不卖' in fill_mode_oneliner(FILL_TRIGGER, 1))
    check("留档文案（CSV/PNG 用）与 UI 说明分工不同但同源",
          fill_summary(FILL_TRIGGER, 2).startswith('成交时点：价格冲破/跌破才成交')
          and '0.02 元' in fill_summary(FILL_TRIGGER, 2))

    _base = {'function': 'A:MA(C,5);', 'params_text': 'N=5', 'condition_buy': '{}',
             'condition_sell': '{}', 'risk': {}, 'index': {}}
    _old_sig = _signature(dict(_base))
    check("旧存档（无 fill 字段）与显式默认口径签名相同 —— 老策略不被误判成新策略",
          _old_sig == _signature({**_base, 'fill': {'fill_mode': FILL_NEXT_OPEN,
                                                    'trigger_tick': 1}}))
    for _fm, _tk, _tag in ((FILL_CLOSE, 1, '当日收盘'), (FILL_TRIGGER, 1, '触发式 1 跳'),
                           (FILL_TRIGGER, 3, '触发式 3 跳')):
        check(f"{_tag} 与默认口径签名不同（不同口径不互相污染对比）",
              _signature({**_base, 'fill': {'fill_mode': _fm, 'trigger_tick': _tk}})
              != _old_sig)
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check(f"§7-B5 成交真实性测试执行失败: {type(e).__name__}: {e}", False)

# ==========================================
# v6.23 · 数据物理护栏 + 读数条新字段（用户 2026-09-17 实测反馈驱动）
#   背景：本地 300750 的历史里混进了兜底源数据（成交量单位=手、前复权含负价），
#   表现为"量能副图 100× 台阶 + 一根负价把整张图压扁"。这里把两道护栏钉成断言。
# ==========================================
print("\n== v6.23 · 数据护栏（非正价 / 成交量单位）+ 读数条（涨跌幅 · 一字）==")
from data.akshare_feed import (EM_VOLUME_UNIT, drop_unusable_price_rows,  # noqa: E402
                              em_volume_to_shares)

_guard = pd.DataFrame({
    'date': pd.to_datetime(['2018-06-11', '2018-06-12', '2018-06-13']),
    'open': [-4.03, 1.33, 3.54], 'high': [-0.68, 1.33, 3.54],
    'low': [-4.03, 1.33, 3.54], 'close': [-0.68, 1.33, 3.54],
})
_kept = drop_unusable_price_rows(_guard, '300750')
check(f"非正价行被拦下（3 行 → {len(_kept)} 行；负价那行不再进湖）", len(_kept) == 2)
check("护栏只拦非正价/缺价，正常行一根不少（不误伤）",
      list(_kept['close']) == [1.33, 3.54])
check("缺价（NaN）行同样拦下",
      len(drop_unusable_price_rows(pd.DataFrame({
          'date': pd.to_datetime(['2024-01-02', '2024-01-03']),
          'open': [1.0, None], 'high': [1.1, None],
          'low': [0.9, None], 'close': [1.05, None]}), 'x')) == 1)
check("没有价格列时原样返回（不崩）",
      len(drop_unusable_price_rows(pd.DataFrame({'date': [1], 'volume': [2]}))) == 1)

_em = pd.DataFrame({'日期': ['2024-01-02'], '成交量': [1234]})
_converted = em_volume_to_shares(_em)
check(f"东财兜底源成交量「手 → 股」（×{EM_VOLUME_UNIT}）",
      float(_converted['成交量'].iloc[0]) == 1234 * EM_VOLUME_UNIT)
check("换算**只做一次**（重复调用不会越乘越大）",
      float(em_volume_to_shares(pd.DataFrame({'成交量': [1234]}))['成交量'].iloc[0])
      == 1234 * EM_VOLUME_UNIT)
check("没有「成交量」列时原样返回（新浪路径/异常帧都不崩）",
      list(em_volume_to_shares(pd.DataFrame({'close': [1.0]})).columns) == ['close'])

# ---- 量纲接缝判据（中位数比对：单日放量不算，持续换单位才算）----
from ui.widgets.desk_data import DeskData  # noqa: E402

_dd = DeskData(None)                       # 只调静态判据，不碰页面
_flat = pd.Series([1e6] * 40)
_seam = pd.concat([pd.Series([1e6] * 40), pd.Series([1e8] * 40)], ignore_index=True)
_spike = pd.concat([pd.Series([1e6] * 40), pd.Series([1e8]), pd.Series([1e6] * 39)],
                   ignore_index=True)
check("量纲接缝（×100 持续换单位）被识别", _dd._volume_seam(_seam) is not None)
check("单日放量（复牌/涨停放量）**不**误报 —— 它之后会回落到同一基线",
      _dd._volume_seam(_spike) is None)
check("量能平稳时不报", _dd._volume_seam(_flat) is None)

# ---- 读数条：涨跌幅 + 一字（纯数据事实，不猜涨跌停规则）----
from ui.widgets.desk_readout import DeskReadout  # noqa: E402

_row = pd.Series({'date': pd.Timestamp('2024-07-30'), 'open': 6.78, 'high': 6.78,
                  'low': 6.78, 'close': 6.78, 'volume': 23938437.0})
_line = DeskReadout._readout_text_for_row(_row, '%Y-%m-%d', prev_close=6.17)
check("读数条带涨跌幅（一字板那天 = +9.89%，一眼看出不是画错）", '+9.89%' in _line)
check("读数条带「一字」标签（当日最高 == 最低）", '一字' in _line)
_row2 = pd.Series({'date': pd.Timestamp('2024-07-31'), 'open': 6.90, 'high': 7.46,
                   'low': 6.80, 'close': 7.46, 'volume': 49885536.0})
_line2 = DeskReadout._readout_text_for_row(_row2, '%Y-%m-%d', prev_close=6.78)
check("有振幅的那天不给「一字」标签（不误报）", '一字' not in _line2 and '+10.03%' in _line2)
check("没有前收（第一根）时不显示涨跌幅（不编数字）",
      '%' not in DeskReadout._readout_text_for_row(_row, '%Y-%m-%d', prev_close=None)
      .replace('开 ', '').replace('高 ', '').replace('低 ', '').replace('收 ', ''))

# ==========================================
# v6.23 · 一字板可读性（用户 2026-09-17 二次反馈："一字板的显示问题"）
#   数据已用独立源逐根核对为**真连板**（600326：2025-07-21..24 四个一字板，
#   开=高=低=收 ⇒ 实体高度 0）；问题在**画法**：零高度实体只剩一条 1px 横线，
#   缩小时几乎看不见 ⇒ 一串一字板看起来像"虚点/断口"。这里把"必须画得出且比影线粗"钉住。
# ==========================================
print("\n== v6.23 · 一字板可读性（零高度实体必须画得出、且比普通影线粗）==")
from PyQt6 import QtCore  # noqa: E402
from PyQt6.QtGui import QImage, QPainter  # noqa: E402

from config import settings  # noqa: E402
from ui.widgets.custom_widgets import CandlestickItem  # noqa: E402

check("一字板（开=收=高=低）被判定为零高度实体", CandlestickItem.is_flat_bar(10.54, 10.54))
check("T 字板（开=收=高，带下影）同样按零高度处理", CandlestickItem.is_flat_bar(15.43, 15.43))
check("正常 K 线不按零高度处理（画法一字未改）", not CandlestickItem.is_flat_bar(9.66, 9.58))
check(f"横档线宽 ≥2px（常量 {CandlestickItem.FLAT_BAR_PEN_WIDTH}）—— 1px 缩小时是头发丝",
      CandlestickItem.FLAT_BAR_PEN_WIDTH >= 2.0)


def _ink(bars, scale=10):
    """把 K 线图元画到离屏画布上，数非白像素 = **看得见的笔迹**。"""
    img = QImage(240, 240, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    painter.scale(scale, scale)
    CandlestickItem(bars).paint(painter, None)
    painter.end()
    return sum(1 for _y in range(240) for _x in range(240)
               if img.pixelColor(_x, _y).lightness() < 200)


def _ink_of_pen(width, scale=10):
    """同一条横线，用指定线宽的**普通画笔**画 —— 作为"头发丝"参照。"""
    img = QImage(240, 240, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    painter.scale(scale, scale)
    painter.setPen(pg.mkPen(settings.COLOR_PROFIT, width=width))
    painter.drawLine(QtCore.QPointF(0.65, 20.0), QtCore.QPointF(1.35, 20.0))
    painter.end()
    return sum(1 for _y in range(240) for _x in range(240)
               if img.pixelColor(_x, _y).lightness() < 200)


_flat_ink = _ink([(0, 20.0, 20.0, 20.0, 20.0), (1, 20.0, 20.0, 20.0, 20.0)])
_hair_ink = _ink_of_pen(1.0)          # 老画法：1px 实体描边
_normal_ink = _ink([(0, 19.0, 20.0, 18.5, 20.5), (1, 19.0, 20.0, 18.5, 20.5)])
check(f"一字板在离屏画布上留下可见笔迹（{_flat_ink} 个非白像素）", _flat_ink >= 20)
check(f"一字板的横档**明显比 1px 头发丝粗**（{_flat_ink} vs {_hair_ink} 像素）",
      _flat_ink >= _hair_ink * 1.8)
check(f"普通 K 线照常画（{_normal_ink} 个非白像素），改画法没影响其它 bar",
      _normal_ink > _hair_ink)

# ==========================================
# v6.24 · §7-B8 R7/R8（用户 2026-09-17 反馈的两处**真实缺陷**）
#   R7 副图**不能调顺序** —— 旧实现只有 `add_pane`（永远追加到底部），没有任何换序手段；
#   R8 副图变多后**左侧坐标轴缩进不一致** —— pyqtgraph 的 `AxisItem` 宽度按**自己的**
#      刻度文本算：量柱 `3.1204e+06`(9 字符) vs MACD `-0.05`(5 字符) ⇒ 左槽不同宽。
#      离屏实测错位 24px（89px vs 65px），统一后两侧绘图区左边缘完全对齐。
# ==========================================
print("\n== v6.24 · §7-B8 R7/R8（副图可换序 + 纵轴共用固定左槽）==")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui.widgets import chart_style  # noqa: E402
from ui.widgets.chart_host import ChartHost  # noqa: E402

_app = QApplication.instance() or QApplication([])

_host = ChartHost(bottom_axis_mode='no_values')
for _n in ('vol', 'macd', 'rsi'):
    _host.add_pane(_n, fixed_height=120)
check("宿主具备 move_pane（旧实现只有 add_pane 追加 ⇒ 这正是「无法调顺序」的根因）",
      hasattr(_host, 'move_pane') and hasattr(_host, 'set_pane_order'))
check("初始顺序 = 主图 + 追加顺序", _host.pane_order == ['main', 'vol', 'macd', 'rsi'])

# ---- R8 根因：不同量级 ⇒ pyqtgraph 生成的刻度文本长度差很多（这就是错位的来源）----
_host.pane('vol').plot_item.setYRange(0, 3120400)
_host.pane('macd').plot_item.setYRange(-0.05, 0.05)
_ax_vol = _host.pane('vol').plot_item.getAxis('left')
_ax_macd = _host.pane('macd').plot_item.getAxis('left')
_lab_vol = [str(t) for t in _ax_vol.tickStrings([0, 3120400], 1.0, 780100)]
_lab_macd = [str(t) for t in _ax_macd.tickStrings([-0.05, 0.05], 1.0, 0.025)]
check("根因钉住：量柱刻度文本比 MACD 长得多（'%s' vs '%s'）" % (_lab_vol[-1], _lab_macd[-1]),
      max(len(t) for t in _lab_vol) >= max(len(t) for t in _lab_macd) + 2)

# ---- R8 复现：先**真的画一次**（pyqtgraph 的轴宽只有画过才会按刻度文本展开）----
_host.resize(760, 560)
_host.show()
_host.grab()                        # 公共 API 触发绘制 → AxisItem 按自己的刻度文本算宽
_app.processEvents()


def _left_widths():
    return [_host.pane(n).plot_item.getAxis('left').width() for n in _host.pane_order]


def _left_edges():
    return [_host.pane(n).plot_item.getViewBox().sceneBoundingRect().left()
            for n in _host.pane_order]


_before = _left_widths()
check("★ 复现缺陷：改前各窗格左轴宽度**本来互不相同**（%s）—— 这正是「缩进不一致」的根因"
      % _before, len(set(_before)) > 1)
check("★ 复现缺陷：改前绘图区左边缘本来错位 %.1f px" % (max(_left_edges()) - min(_left_edges())),
      max(_left_edges()) - min(_left_edges()) > 1.0)

# ---- R8 修法（第二版）：统一**预留文本宽度**，而不是 setWidth(最宽的那根) ----
_width = _host.align_axis_widths()
_app.processEvents()
_after = _left_widths()
check("统一左槽后：四根左轴宽度**完全相等**（%s → %s）" % (_before, _after),
      len(set(_after)) == 1)
check("★ 不再留大片空白：统一宽度只比**最窄**那根多 %d px（第一版是撑到最宽那根 = 多 %d px）"
      % (max(_after) - min(_before), max(_before) - min(_before)),
      max(_after) - min(_before) <= 20)
check("预留宽度是合理的布局常量（AXIS_TEXT_WIDTH=%d ≤ 64）" % chart_style.AXIS_TEXT_WIDTH,
      chart_style.AXIS_TEXT_WIDTH <= 64)
check("幂等：再调一次宽度不变（第二版不再依赖「画过一次」，也不会越调越宽）",
      _host.align_axis_widths() == _width)
check("★ 统一后绘图区左边缘**对齐**（最大错位 %.1f px）"
      % (max(_left_edges()) - min(_left_edges())),
      max(_left_edges()) - min(_left_edges()) < 1.0)
_host.grab()
_app.processEvents()
check("对齐不会被重绘顶回来（再画一次宽度仍相等）", len(set(_left_widths())) == 1)
check("空输入安全：没有窗格时返回 0.0 且不抛（装饰性逻辑绝不连累渲染）",
      chart_style.unify_axis_width([]) == 0.0)

# ---- R7 修法：换序 ----
check("move_pane 把 rsi 挪到主图下面第一格", _host.move_pane('rsi', 1) is True)
check("顺序真的变了", _host.pane_order == ['main', 'rsi', 'vol', 'macd'])
check("主图不可移动（返回 False，且它仍是第 0 张）",
      _host.move_pane('main', 2) is False and _host.pane_order[0] == 'main')
check("原地不动返回 False（不做无意义重排）", _host.move_pane('rsi', 1) is False)
check("越界自动夹到合法区间（不会 IndexError）",
      _host.move_pane('rsi', 99) is True and _host.pane_order[-1] == 'rsi')
check("不存在的窗格名返回 False", _host.move_pane('查无此格', 1) is False)
check("★ 换序后「最下面那张显示刻度值」的归属**跟着重算**",
      _host.bottom_axis_pane == _host.pane_order[-1])
check("★ 换序后只有最下窗格 showValues=True（漏算这一步 ⇒ 日期轴会挂在中间那张副图上）",
      [_host.pane(n).plot_item.getAxis('bottom').style['showValues']
       for n in _host.pane_order] == [False, False, False, True])
check("换序没有打断 x 轴联动（每张副图仍链到主图）",
      all(_host.x_linked(n) for n in _host.pane_order[1:]))

check("set_pane_order 给全 ⇒ 生效",
      _host.set_pane_order(['macd', 'vol', 'rsi']) is True
      and _host.pane_order == ['main', 'macd', 'vol', 'rsi'])
_keep = list(_host.pane_order)
check("★ set_pane_order 少给一个 ⇒ 拒绝且**顺序原样不动**（绝不静默丢窗格）",
      _host.set_pane_order(['macd']) is False and _host.pane_order == _keep)
check("set_pane_order 给一模一样的顺序 ⇒ False（不做无意义改动）",
      _host.set_pane_order(['macd', 'vol', 'rsi']) is False)

# ==========================================
# §7-B1/B2 STEP 1 · 横截面内核 `core/cross_section.py`（M2 横截面 / M3 广度）
#   判据来自主案 D2 / D5 + 「三态铁律」+ §9.1 读数纪律：
#     ① 与 M1 **同口径**：prepare_frame 的准备块与 BacktestEngine.run **逐字相同**（源码级断言）
#     ② 三态：**数据不足 ≠ 未命中**（新上市 / 停牌 / 缺列 / 当日无行，一律不许算成未命中）
#     ③ 粗筛：能生效、能关掉、能恢复默认、坏偏好逐字段回落
#     ④ M2 逐位可验 + M3 分母 = **有效样本**（不是全市场只数）
#     ⑤ 缓存矩阵 status_on(d) 与 scan(asof=d) 逐位一致（这是「改日期秒回」的前提）
# ==========================================
print("\n== §7-B1/B2 STEP 1 · 横截面内核：三态 / 粗筛 / 广度 / 缓存 ==")
try:
    import pathlib as _pathlib  # noqa: E402
    from time import perf_counter as _now  # noqa: E402

    from config import settings as _settings  # noqa: E402
    from core import backtest as _bt_mod  # noqa: E402
    from core import cross_section as _cs  # noqa: E402
    from core.formula.program import execute_programs, parse_program  # noqa: E402

    # ---------- ① 与 M1 同口径（源码级：任一侧改动都会红）----------
    def _prep_block(module):
        """取模块源码里「数据准备」那一小段（标准化文本）"""
        lines = _pathlib.Path(module.__file__).read_text(encoding='utf-8').splitlines()
        head = next(i for i, line in enumerate(lines) if line.strip() == 'data = df.copy()')
        return [line.strip() for line in lines[head:head + 7]]

    check("★ 与 M1 同口径：`cross_section.prepare_frame` 的准备块与 `core/backtest.py` **逐字相同**"
          "（谁改一处漏另一处 ⇒ 立刻红）",
          _prep_block(_cs) == _prep_block(_bt_mod))

    # ---------- 合成数据（不依赖本地行情，任何机器都能跑）----------
    _days = pd.bdate_range('2024-01-01', periods=300)
    _FORMULA = 'COND := C > REF(C, 1);'          # 上行=真 / 下行=假（无热身期歧义）

    def _mk(closes, *, i0=0, amount=1e8, scale=1.0, with_amount=True,
            turnover=None, share=None):
        values = np.asarray(closes, dtype=float) * scale
        frame = pd.DataFrame({
            'date': list(_days[i0:i0 + len(values)]), 'open': values,
            'high': values * 1.02, 'low': values * 0.98, 'close': values, 'volume': 1e6,
        })
        if with_amount:
            frame['amount'] = amount
        if turnover is not None:
            frame['turnover'] = turnover
        if share is not None:
            frame['outstanding_share'] = share
        return frame

    _up = np.linspace(10.0, 20.0, 300)           # 单调上行 ⇒ 公式恒真
    _down = np.linspace(20.0, 10.0, 300)         # 单调下行 ⇒ 公式恒假
    _groups = {
        'UP': _mk(_up),                          # 命中
        'DOWN': _mk(_down),                      # 未命中
        'NEW': _mk(_up[-100:], i0=200),          # 只有 100 个交易日 ⇒ 数据不足
        'NOAMT': _mk(_up, with_amount=False),    # 缺 amount 列 ⇒ 数据不足（§9.1）
        'PENNY': _mk(_up, scale=0.05),           # 0.5 ~ 1.0 元的低价股 ⇒ 被粗筛剔除
        'GAP': _mk(_up[:-1]),                    # 基准日**没有行** ⇒ 数据不足
    }
    _asof = _days[-1]
    _res = _cs.scan(_groups, _FORMULA, asof=_asof, snapshot_columns=('close', 'amount'))

    check("③ 命中：数据够 + 公式为真", _res.status['UP'] == _cs.HIT)
    check("③ 未命中：数据够 + 公式为假", _res.status['DOWN'] == _cs.MISS)
    check("★ 新上市（只有 100 个交易日）⇒ **数据不足**，不是「未命中」"
          "（算成未命中会把广度系统性压低估）",
          _res.status['NEW'] == _cs.INSUFFICIENT and '100' in _res.detail['NEW'])
    check("★ 这只票**没有 amount 列** ⇒ **数据不足**，绝不能变成「成交额不符」"
          f"（现状 {_res.status['NOAMT']} / {_res.detail['NOAMT']}）",
          _res.status['NOAMT'] == _cs.INSUFFICIENT and 'amount' in _res.detail['NOAMT'])
    check("★ 低价股（0.1 元）⇒ **被粗筛剔除**（数据是好的，只是不满足阈值）",
          _res.status['PENNY'] == _cs.FILTERED and '价格' in _res.detail['PENNY'])
    check("★ 基准日**无行**（停牌 / 未下载 / 已退市）⇒ 数据不足",
          _res.status['GAP'] == _cs.INSUFFICIENT and _res.detail['GAP'].startswith('当日无数据'))
    check("★ 有效样本 = 命中 + 未命中 = 2（数据不足与被剔除**不进分母**）",
          _res.valid_count == 2 and _res.counts['valid'] == 2)
    check("★ 四态**分类完备**：命中 + 未命中 + 数据不足 + 被剔除 == 总数（一个新桶都不许漏）",
          _res.counts['hit'] + _res.counts['miss'] + _res.counts['insufficient']
          + _res.counts['filtered'] == _res.counts['total'] == len(_groups))
    check("④ M2 命中名单逐位可验", _res.hits == ['UP'])
    check("④ 快照只给**基准日真有行**的标的（不许拿上一交易日的值冒充当日）",
          set(_res.snapshot) == {'UP', 'DOWN', 'NEW', 'NOAMT', 'PENNY'}
          and abs(_res.snapshot['UP']['close'] - 20.0) < 1e-9)

    # ★P2 派生指标：当日/当月/当年涨幅与市值口径（就地算、缺基准返 None、不硬凑 0）
    _dm = pd.DataFrame({
        'date': pd.to_datetime(['2023-12-29', '2024-05-31', '2024-06-25', '2024-06-26', '2024-06-28']),
        'close': [10.0, 11.0, 12.0, 13.0, 14.0],
        'outstanding_share': [1e8] * 5})
    _d4 = _cs._derived_metrics(_dm, 4)          # 2024-06-28 收盘 14
    check("★ P2 当日涨幅 = 今收/昨收-1", abs(_d4['day_pct'] - (14 / 13 - 1)) < 1e-9)
    check("★ P2 当月涨幅基准 = 上月末(5/31=11)，非昨收", abs(_d4['month_pct'] - (14 / 11 - 1)) < 1e-9)
    check("★ P2 当年涨幅基准 = 上年末(2023-12-29=10)", abs(_d4['year_pct'] - (14 / 10 - 1)) < 1e-9)
    check("★ P2 流通市值 = 收盘×流通股本", abs(_d4['float_mktcap'] - 14 * 1e8) < 1e-3)
    _d0 = _cs._derived_metrics(_dm, 0)          # 首日：无昨收/无上期基准
    check("★ P2 首日无上期基准 ⇒ 三项涨幅均 None（诚实不拿 0 冒充）",
          _d0['day_pct'] is None and _d0['month_pct'] is None and _d0['year_pct'] is None)
    _dno = _cs._derived_metrics(_dm.drop(columns=['outstanding_share']), 4)
    check("★ P2 缺流通股本列 ⇒ float_mktcap None（不抛、不假造）", _dno['float_mktcap'] is None)

    check("④ asof 缺省 = **全市场最新交易日**（不是每个标的自己的最后一天）",
          _cs.scan(_groups, _FORMULA).asof == _asof)

    # ---------- ③ 粗筛：关掉 / 恢复默认 / 坏偏好 ----------
    _off = _cs.scan(_groups, _FORMULA, asof=_asof, thresholds=_cs.ScanThresholds(min_price=None))
    check("③ 关掉「价格 ≥ 2 元」⇒ 那只 0.1 元的票**重新进样本**（关掉 = 不参与漏斗）",
          _off.status['PENNY'] == _cs.HIT and _off.valid_count == 3)

    _default = _cs.ScanThresholds()
    check("③ 「↺ 恢复默认」= 出厂值（成交额 5000 万 / 价格 2 元 / 250 天 / 非停牌 / 剔 ST / 剔一字板）",
          _default.min_amount == 5e7 and _default.min_price == 2.0 and _default.min_bars == 250
          and _default.exclude_suspended and _default.exclude_st and _default.exclude_limit
          and _default.min_turnover is None
          and _default.reset().to_dict() == _default.to_dict())
    check("③ 阈值单位走**用户量纲**（文案里出现「5 千万元」这类，不出现 50000000）",
          '万元' in _cs.human_amount(5e7) and '亿元' in _cs.human_amount(3.2e8))

    _bad = _cs.ScanThresholds.from_dict({'min_price': '3.5', 'min_bars': None, 'exclude_st': 0,
                                         'nonsense': 1, 'min_amount': 'abc'})
    check("③ 坏偏好**逐字段回落**（'3.5' 转得动 / None 保留 / 假布尔 / 未知键与坏数字忽略）",
          _bad.min_price == 3.5 and _bad.min_bars is None and _bad.exclude_st is False
          and _bad.min_amount == 5e7)
    check("③ 偏好不是 dict ⇒ 整份回默认（一条坏偏好不能拖垮整页，§9-D）",
          _cs.ScanThresholds.from_dict('nope').to_dict() == _cs.ScanThresholds().to_dict())
    check("③ problems() 抓「下限 > 上限」这类笔误（**非阻断**，只提示）",
          bool(_cs.ScanThresholds(min_change_pct=0.1, max_change_pct=-0.1).problems())
          and not _cs.ScanThresholds().problems())

    # ---------- §9.1：换手率 / 流通市值「有就用、没有就数据不足」 ----------
    _turn = _cs.scan({'UP': _mk(_up, turnover=0.02), 'DOWN': _mk(_down)},
                     _FORMULA, asof=_asof, thresholds=_cs.ScanThresholds(min_turnover=0.01))
    check("★ 换手率可用（D5 修正）：有该列且达标 ⇒ 正常命中", _turn.status['UP'] == _cs.HIT)
    check("★ 同一轮里**没有 turnover 列**的票 ⇒ 数据不足（**绝不当 0 误杀**，§9.1）",
          _turn.status['DOWN'] == _cs.INSUFFICIENT and 'turnover' in _turn.detail['DOWN'])

    _mkt = _cs.scan({'UP': _mk(_up, share=1e9), 'DOWN': _mk(_down)}, _FORMULA, asof=_asof,
                    thresholds=_cs.ScanThresholds(min_float_mktcap=1e11))
    check("★ 流通市值 = close × outstanding_share：算出来不达标 ⇒ 被剔除；缺列 ⇒ 数据不足",
          _mkt.status['UP'] == _cs.FILTERED and _mkt.status['DOWN'] == _cs.INSUFFICIENT)

    # ---------- 花名册（ST / 退市）----------
    check("★ 启用「剔除 ST」却没给花名册 ⇒ **明确出声**（不静默跳过，§9-V 精神）",
          any('花名册' in _w for _w in _res.warnings))
    check("★ 给了花名册且名称含 ST / 退 ⇒ 被剔除",
          _cs.scan({'UP': _mk(_up)}, _FORMULA, asof=_asof,
                   names={'UP': 'ST某某'}).status['UP'] == _cs.FILTERED
          and _cs.scan({'UP': _mk(_up)}, _FORMULA, asof=_asof,
                       names={'UP': '某某退'}).status['UP'] == _cs.FILTERED)

    # ---------- ④ M3 广度：分母是**有效样本** ----------
    _breadth = _res.breadth_frame()
    _last_day = _breadth.iloc[-1]
    check("④ M3 广度：最后一天命中家数 == M2 命中数（同一个引擎，两种视图）",
          int(_last_day['hits']) == len(_res.hits) == 1)
    # ★ 注意这条语义：M3 的逐日分桶**只覆盖"那天真的有行"的标的** ——
    #   "当日无行"的票在 M2 里记「数据不足」，但在 M3 那天**根本不存在**，不进任何桶
    #   （这正是"新上市 / 停牌不该压低广度占比"的落实；它比"和 == 全市场只数"更难，也更是对的）
    _no_row_on_asof = [sym for sym, st in _res.status.items()
                       if st == _cs.INSUFFICIENT and _res.detail[sym].startswith('当日无数据')]
    check("④ M3 分母 = **有效样本**（当天 2 只），不是全市场只数（6 只）；"
          "且「当日无行」的票那天不进任何桶"
          "（四个桶 = 有效样本 + 被剔除 + 数据不足，`miss` 已含在有效样本里）",
          int(_last_day['valid']) == 2 and len(_no_row_on_asof) == 1
          and int(_last_day['valid'] + _last_day['filtered'] + _last_day['insufficient'])
          == len(_groups) - len(_no_row_on_asof))
    check("④ ratio = hits / valid", abs(float(_last_day['ratio']) - 0.5) < 1e-9)
    check("④ 热身期（前 249 个交易日）全市场一律「数据不足」⇒ 命中家数必为 0",
          bool((_breadth['hits'].iloc[:249] == 0).all())
          and bool((_breadth['insufficient'].iloc[:249] > 0).all()))

    # ---------- ⑤ 缓存矩阵（"改日期秒回"的前提）----------
    _cache = _cs.scan(_groups, _FORMULA, asof=_asof, keep_matrix=True)
    check("⑤ 缓存矩阵是 uint8 四态（内存 = 交易日 × 标的 × 1B ≈ 22 MB/全市场，D3）",
          _cache.status_matrix is not None and _cache.status_matrix.dtype == np.uint8
          and _cache.status_matrix.shape == (len(_cache.symbols), len(_cache.dates)))
    check("⑤ status_on(基准日) 与 scan(asof=基准日) **逐位一致**",
          _cache.status_on(_asof) == _res.status)
    check("⑤ 换一天：缓存切片 == 重新扫（**这就是「改日期秒回」的前提**）",
          _cache.status_on(_days[279]) == _cs.scan(_groups, _FORMULA, asof=_days[279]).status)
    check("⑤ 不在交易日轴上的日期 ⇒ 返回空（不许糊一个「最接近」的结果给用户）",
          _cache.status_on('2001-01-01') == {})

    # ---------- 基准日**就近落位**（v6.42 · 先选后扫：轴外日子不整轮空跑）----------
    _noon = _days[279] + pd.Timedelta(hours=12)          # 午中 ⇒ 永远不在轴上（轴是午夜）
    _snap = _cs.scan(_groups, _FORMULA, asof=_noon)
    check("★ 轴外基准日 ⇒ 就近落到最近交易日（平手取前一日），命中照常判（不空跑）",
          _snap.asof == _days[279] and _snap.status['UP'] == _cs.HIT)
    check("★ 落位必须**出声**（warnings 有 UI 出口：回执会写「已就近落到 …」，不静默换日子）",
          any('就近' in _w for _w in _snap.warnings))
    _future = _cs.scan(_groups, _FORMULA, asof=_days[-1] + pd.Timedelta(days=7))
    check("★ 选到比本地数据还新的日子 ⇒ 落到**轴尾交易日**（数据没有的就是没有，但不空跑）",
          _future.asof == _days[-1] and any('就近' in _w for _w in _future.warnings))

    # ---------- 本地没文件的标的（v6.42："名单 429 → 只扫 27"静默丢标的的根治）----------
    _missk = _cs.scan(_groups, _FORMULA, asof=_asof, keep_matrix=True,
                      missing=['ZZZ1', 'ZZZ2'])
    check("★ 本地无文件的标的 ⇒ 记「数据不足」并**进总数**（总数 = 有文件 + 没文件，不静默丢）",
          _missk.counts['total'] == len(_groups) + 2
          and _missk.status['ZZZ1'] == _cs.INSUFFICIENT
          and '没有日线文件' in _missk.detail['ZZZ1'])
    check("★ 缺文件必须**出声**（warnings → 回执：有效样本只来自有文件的 N 只）",
          any('没有日线文件' in _w for _w in _missk.warnings))
    check("★ 缓存切片与扫描同口径：status_on 也含无文件标的（切日期数字不跳变）",
          _missk.status_on(_asof) == _missk.status
          and _missk.counts_on(_asof)['total'] == len(_groups) + 2)

    # ---------- 整份名单都无文件（v6.42 用户实测：扫描回全空白、无解释）----------
    _miss0 = _cs.scan({}, _FORMULA, missing=['ZZA', 'ZZB'])
    check("★ 读数为空也不回空结果：逐只记「数据不足」+ 进总数 + 出声（界面永远有东西可看）",
          _miss0.counts['total'] == 2 and _miss0.status['ZZA'] == _cs.INSUFFICIENT
          and any('没有日线文件' in _w for _w in _miss0.warnings))
    from data.scan_store import ScanOutcome as _SO4  # noqa: E402
    _out0 = _SO4(result=_miss0, key=None, asof=_miss0.asof)
    check("★ 无矩阵时 ScanOutcome 兜底基准日（None/NaT 都回完整名单，不空表糊弄）",
          _out0.status_on(None) == _miss0.status
          and _out0.status_on(pd.Timestamp('NaT')) == _miss0.status
          and _out0.counts_on(None)['total'] == 2)

    # ---------- ④ 逐位对齐（不只看最后一天）：矩阵 vs 直接跑引擎 ----------
    _direct = (pd.to_numeric(pd.Series(execute_programs(
        [parse_program(_FORMULA)], _cs.prepare_frame(_groups['UP']), {})['COND']),
        errors='coerce').to_numpy() != 0)
    _mismatch = [str(_days[k].date()) for k in range(250, 300)
                 if _cache.status_on(_days[k]).get('UP')
                 != (_cs.HIT if _direct[k] else _cs.MISS)]
    check(f"④ 逐位对齐：热身期后 50 个交易日，矩阵状态 == 直接跑引擎（不符 {_mismatch[:3] or '无'}）",
          not _mismatch)
    check("★ 热身期（第 1/100/249 个交易日）一律「数据不足」—— 即便公式那天已算得出真值",
          all(_cache.status_on(_days[k]).get('UP') == _cs.INSUFFICIENT for k in (0, 100, 248)))

    # ---------- 公式约定与报错 ----------
    check("④ 多语句：**最后一条变量**就是判定变量；`signal_names()` 供界面下拉",
          _cs.scan({'UP': _mk(_up)}, 'A := MA(C, 5); B := C > A;',
                   asof=_asof).signal_name == 'B' and _cs.signal_names(_FORMULA) == ['COND'])

    def _raises(formula, **kwargs):
        try:
            _cs.scan({'UP': _mk(_up)}, formula, asof=_asof, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return type(exc).__name__, str(exc)
        return '', ''

    _name, _ = _raises('C > 1;')
    check("④ 公式没有可判定变量 ⇒ **立刻报错给用户**（不是默默扫出 0 命中）", bool(_name))
    _name2, _msg2 = _raises(_FORMULA, signal_name='NOPE')
    check("④ signal_name 不存在 ⇒ 报错并列出可选项", bool(_name2) and 'COND' in _msg2)

    # ---------- 真实行情（有就验一遍；没有就明说跳过，不假装通过）----------
    _lake = os.path.join(_settings.USER_DATA_DIR, 'data_lake', 'kline', 'daily')
    _has_lake = os.path.isdir(_lake) and any(
        name.endswith('.parquet') for name in os.listdir(_lake))
    if not _has_lake:
        print("  [--] 本地暂无日线分区，跳过「真实行情」部分"
              "（合成数据部分已覆盖全部口径与三态）")
    else:
        _real_formula = 'COND := CROSS(EMA(C,12), EMA(C,26)) AND C > MA(C,20);'
        _t0 = _now()
        _real = _cs.scan_lake(_lake, _real_formula, snapshot_columns=('close', 'amount'))
        _cost = _now() - _t0
        check(f"真实行情：分区 {_real.counts['total']} 只扫得完"
              f"（{_cost:.2f}s · {_cost / max(1, _real.counts['total']) * 1000:.2f} ms/只；"
              f"标杆见 §7-B1/B2 主案 B3）", _real.counts['total'] > 0)
        check("真实行情：四态**分类完备**（和 == 总数）",
              _real.counts['hit'] + _real.counts['miss'] + _real.counts['insufficient']
              + _real.counts['filtered'] == _real.counts['total'])
        check("真实行情：缺列的票（东财兜底透传的中文列 / 期货列）落「数据不足」而不是「不达标」"
              "（§9.1）",
              all(_real.status[s] == _cs.INSUFFICIENT for s, d in _real.detail.items()
                  if d.startswith('缺少所需列')))
        _real_breadth = _real.breadth_frame()
        _ratio = _real_breadth['ratio'].dropna()
        check("真实行情：广度 ratio 全在 [0,1]，且 valid ≤ total（分母口径没串）",
              bool(((_ratio >= 0) & (_ratio <= 1)).all())
              and int(_real_breadth['valid'].max()) <= _real.counts['total'])
        check("★ 真实行情：M2 / M3 **同源自洽** —— 广度表最后一天的 hits / valid 与 M2 逐一相等"
              "（两个视图共用同一份状态码）",
              int(_real_breadth.iloc[-1]['hits']) == _real.counts['hit']
              and int(_real_breadth.iloc[-1]['valid']) == _real.counts['valid'])
        check("★ 「当日无行」的标的**不进广度分母**（M3 那天根本没有它，M2 里记「数据不足」）"
              "—— 这正是「新上市 / 停牌不该压低占比」的落实",
              int(_real_breadth.iloc[-1]['filtered'] + _real_breadth.iloc[-1]['insufficient'])
              <= _real.counts['filtered'] + _real.counts['insufficient'])
        check("★ 真实行情：缓存矩阵切片 == 重扫（**逐位一致**）",
              _cs.scan_lake(_lake, _real_formula, keep_matrix=True).status_on(_real.asof)
              == _real.status)
except Exception as _e:  # noqa: BLE001
    check(f"横截面内核断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# §7-B1/B2 STEP 2 · 会话内存缓存 `data/scan_store.py`（主案 D3 · v6.35）
#   判据：① 同键命中 = **一次求值都不跑**；`asof` 不进键 ⇒ **切日期零成本**
#         ② 键的六样少一样都不行（公式 / 粗筛 / 标的域 / 复权 / **数据版本** / 快照列）
#         ③ **数据一变 ⇒ 键就变 ⇒ 必然不命中**（负向断言：静默陈旧在结构上不可能）
#         ④ 配额双闸（条数 + 字节），占用**看得见、能清**
#         ⑤ **只碰内存**：不写任何文件（源码级断言）
# ==========================================
print("\n== §7-B1/B2 STEP 2 · 会话缓存：键 / 失效 / 切日期 / 配额 ==")
try:
    import shutil as _shutil
    import tempfile as _tempfile

    from data import scan_store as _ss
    from data.market_db import DataLakeManager as _DLM

    # ---- 造一个"假数据湖"（临时目录；**绝不碰用户真实分区**）----
    _zone = _tempfile.mkdtemp(prefix='jian_scan_zone_')
    for _sym, _closes, _opt in (('UP', _up, {}), ('DOWN', _down, {}),
                                ('PENNY', _up, {'scale': 0.05})):
        _mk(_closes, **_opt).to_parquet(os.path.join(_zone, f'{_sym}.parquet'), index=False)
    _fake_symbols = ['UP', 'DOWN', 'PENNY']
    _fake_th = _cs.ScanThresholds()
    _store = _ss.ScanStore()

    _first = _ss.scan_cached(_zone, _FORMULA, symbols=_fake_symbols, thresholds=_fake_th,
                             asof=_asof, store=_store)
    check("STEP 2：首次扫描 = **未命中**（cached=False），且矩阵已落缓存",
          _first.cached is False and _first.result.status_matrix is not None
          and _store.entries() == 1)
    _second = _ss.scan_cached(_zone, _FORMULA, symbols=_fake_symbols, thresholds=_fake_th,
                              asof=_asof, store=_store)
    check("STEP 2：再扫一次 = **命中**，拿到的还是**同一份矩阵**（一次求值都没跑）",
          _second.cached is True and _second.result is _first.result)
    check("★ STEP 2：命中后**切日期零成本**（`asof` 不进键）—— 缓存切片与矩阵逐位一致",
          _second.status_on(_days[279]) == _second.result.status_on(_days[279])
          and _second.status_on(_days[279]) != {})
    check("STEP 2：`counts_on(asof)` 与重扫的 `counts` **同一实现**（不会两处各算一遍）",
          _second.counts_on(_asof) == _first.result.counts)
    check("单例：`get_scan_store()` 两次拿到同一个对象（别自己 new —— 会各存各的）",
          _ss.get_scan_store() is _ss.get_scan_store())

    # ---- 键的六样：少一样都不行 ----
    _key_a = _ss.scan_key(_FORMULA, _fake_th, _fake_symbols, zone_dir=_zone)
    check("★ 键①公式：只改**注释 / 空白 / 大小写** ⇒ 键不变（否则「看着没改却重算几十秒」）",
          _ss.scan_key('cond:=c>ref(c,1); // 只是改了个注释', _fake_th, _fake_symbols,
                       zone_dir=_zone) == _key_a)
    check("★ 键①公式：真改了表达式 ⇒ 键变",
          _ss.scan_key('COND := C > REF(C, 2);', _fake_th, _fake_symbols,
                       zone_dir=_zone) != _key_a)
    check("★ 键②**粗筛阈值进键**（v6.35 修订）：阈值决定「被剔除」桶，不进键 = 静默陈旧",
          _ss.scan_key(_FORMULA, _cs.ScanThresholds(min_price=None), _fake_symbols,
                       zone_dir=_zone) != _key_a)
    check("★ 键③标的域：换域必须失效（否则「自选」的结果会被当成「全市场」）",
          _ss.scan_key(_FORMULA, _fake_th, ['UP', 'DOWN'], zone_dir=_zone) != _key_a)
    check("★ 键④复权口径：前复权 / 不复权是两份数据集，绝不共用缓存",
          _ss.scan_key(_FORMULA, _fake_th, _fake_symbols, adjust='none',
                       zone_dir=_zone) != _key_a)
    check("★ 键⑥快照列：快照是按列取的 ⇒ 列不同即内容不同，不能共用",
          _ss.scan_key(_FORMULA, _fake_th, _fake_symbols, zone_dir=_zone,
                       snapshot_columns=('close',)) != _key_a)

    # ---- 键⑤数据版本：**静默陈旧的唯一堵口** ----
    _v1 = _ss.data_version(_zone)
    check("★ 键⑤数据版本：同目录两次调用**必须相同**（否则永远不命中 = 缓存形同虚设）",
          _ss.data_version(_zone) == _v1 and _v1.startswith('3-'))
    _mk(_up, scale=0.05).to_parquet(os.path.join(_zone, 'EXTRA.parquet'), index=False)
    _v2 = _ss.data_version(_zone)
    check("★ 键⑤数据版本：**新增文件**必须改变版本"
          "（「下了新数据却不重算」= 静默陈旧，§5 / §10 铁律）",
          _v2 != _v1 and _v2.startswith('4-'))
    _after = _ss.scan_cached(_zone, _FORMULA, symbols=_fake_symbols, thresholds=_fake_th,
                             asof=_asof, store=_store)
    check("★★ 数据一变 ⇒ 键就变 ⇒ **必然不命中**（负向断言：静默陈旧在结构上不可能）",
          _after.cached is False and _after.key != _first.key)
    _v3 = _ss.data_version(_zone)
    _mk(_down, amount=2e8).to_parquet(os.path.join(_zone, 'DOWN.parquet'), index=False)
    check("★ 键⑤数据版本：**重写内容**也要察觉（增量补齐 / 重新下载属这一类）",
          _ss.data_version(_zone) != _v3)

    # ---- 配额：会话内存不许无限涨；占用要看得见、能清 ----
    _small = _ss.ScanStore(max_entries=1)
    _small.put(_key_a, _first.result)
    _small.put(_after.key, _first.result)
    check("配额：`max_entries=1` ⇒ 最久未用的被淘汰",
          _small.entries() == 1 and _small.get(_key_a) is None
          and _small.get(_after.key) is not None)
    _stats = _small.stats()
    check("`stats()` 报占用与命中数（§10-10：占用要**看得见、能清**）",
          _stats['entries'] == 1 and _stats['bytes'] > 0 and _stats['hits'] == 1
          and _stats['misses'] == 1)
    check('`clear()` 一键释放（"⟳ 全量重算" / 内存体检按钮的后端）',
          _small.clear() == 1 and _small.bytes_used() == 0)

    # ---- 两条"结构性"护栏 ----
    check("分区目录映射与 `data/market_db.py` **同源**（本模块刻意不实例化它，靠断言钉住一致）",
          _ss.kline_zone_dir('kline_daily') == _DLM().zones['kline_daily']
          and _ss.kline_zone_dir('kline_daily_raw') == _DLM().zones['kline_daily_raw'])
    _ss_src = _pathlib.Path(_ss.__file__).read_text(encoding='utf-8')
    check("★ 本模块**只碰内存**：源码里没有 `open(` / `to_parquet` / `os.replace` / `os.remove`"
          "（缓存不落盘 ⇒ 无需进防污染自检名单）",
          all(token not in _ss_src
              for token in ('open(', 'to_parquet', 'os.replace', 'os.remove')))

    # ---- 真实分区：缓存不许改变结果 ----
    _lake_dir2 = os.path.join(_settings.USER_DATA_DIR, 'data_lake', 'kline', 'daily')
    if not os.path.isdir(_lake_dir2):
        print("  [--] 本地暂无日线分区，跳过「真实分区缓存 == 强制重扫」一条")
    else:
        _live_f = 'COND := CROSS(EMA(C,12), EMA(C,26)) AND C > MA(C,20);'
        _live1 = _ss.scan_cached(_lake_dir2, _live_f, snapshot_columns=('close',))
        _live2 = _ss.scan_cached(_lake_dir2, _live_f, snapshot_columns=('close',))
        check("真实分区：第二次调用**命中**（同键同数据版本）⇒ 切日期 / 换窗口零成本",
              _live2.cached is True and _live2.result is _live1.result)
        _live_day = _live2.result.dates[-1]
        _by_force = _ss.scan_cached(_lake_dir2, _live_f, snapshot_columns=('close',),
                                    asof=_live_day, force=True).result.status
        check("★★ 真实分区：**缓存切片 == 强制重扫**（逐位一致）—— 缓存不许悄悄改变结果",
              _live2.status_on(_live_day) == _by_force)

        # ★回归：显式扫**更早基准日** ⇒ 不吃旧快照缓存（否则 M2 选历史日+开始扫描 数值全 '—'）
        _early = _live2.result.dates[0]
        _live_early = _ss.scan_cached(_lake_dir2, _live_f, snapshot_columns=('close',), asof=_early)
        check("★ 回归：显式扫更早基准日 ⇒ 重扫（cached=False、result.asof=更早日、快照非空），"
              "否则用户选历史日+开始扫描会数值全 '—'（缓存命中短路旧快照的 bug）",
              _live_early.cached is False
              and pd.Timestamp(_live_early.result.asof) == pd.Timestamp(_early)
              and bool(_live_early.result.snapshot))

    _shutil.rmtree(_zone, ignore_errors=True)
    check("假数据湖已删除（临时探针用完即删，§10-13）", not os.path.isdir(_zone))
except Exception as _e:  # noqa: BLE001
    check(f"会话缓存断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# §7-B1/B2 STEP 3 · 后台扫描线程 `CrossSectionWorker` + 竞态守卫（主案 D4 · §9-O5）
#   判据：① `job_id` **原样回包**（页面判"是不是我要的那次"就靠它）
#         ② 进度**两段**（读数 0/0 → 计算 done/total）且单调不减、收尾到底
#         ③ **取消 ⇒ 回包 None + 缓存一条都不落**（半成品矩阵绝不外流）
#         ④ 竞态：发起新任务后，旧任务的回包**必须被丢弃**（真并发验证）
#         ⑤ 缓存命中 ⇒ **一次计算都不跑**（连进度信号都没有）
#         ⑥ 公式错 ⇒ 走 `failed`（异常绝不穿透 QThread，也不会静默无回包）
# ==========================================
print("\n== §7-B1/B2 STEP 3 · CrossSectionWorker：进度 / 取消 / 竞态守卫 ==")
try:
    from ui.workers import CrossSectionWorker, JobGuard

    _zone3 = _tempfile.mkdtemp(prefix='jian_worker_zone_')
    _syms3 = [f'Y{i:02d}' for i in range(6)]        # 6 只 ⇒ chunk=2 正好报 3 次，能看清单调性
    for _sym3 in _syms3:
        _mk(_up).to_parquet(os.path.join(_zone3, f'{_sym3}.parquet'), index=False)

    # ---- ① 竞态守卫（先把判据钉死）----
    _guard = JobGuard()
    _job_a = _guard.next()
    check("竞态守卫：当前任务的回包被接受", _guard.accept(_job_a) is True)
    _job_b = _guard.next()
    check("★ 竞态守卫（§9-O5）：**发起新任务后，旧任务的回包一律丢弃**"
          "（否则「旧结果覆盖新结果」，而且界面看着完全正常）",
          _guard.accept(_job_a) is False and _guard.accept(_job_b) is True)
    check("竞态守卫：类型容错（「1」与 1 同一次），乱值直接拒",
          _guard.accept(str(_job_b)) is True and _guard.accept(None) is False)

    # ---- ② Worker 跑通：job_id 原样回包 + 两段进度 ----
    _seen = {'progress': [], 'finished': []}
    _w1 = CrossSectionWorker(7, _zone3, _FORMULA, symbols=_syms3, chunk=2,
                             store=_ss.ScanStore())
    _w1.progress.connect(lambda d, t, n: _seen['progress'].append((d, t, n)))
    _w1.finished.connect(lambda j, o: _seen['finished'].append((j, o)))
    _w1.start()
    _w1.wait(30000)
    app.processEvents()
    check("STEP 3：回包**原样带回 `job_id`**，且真的带回了结果",
          len(_seen['finished']) == 1 and _seen['finished'][0][0] == 7
          and _seen['finished'][0][1] is not None
          and _seen['finished'][0][1].result.counts['total'] == len(_syms3))
    _calc_steps = [d for d, t, _n in _seen['progress'] if t == len(_syms3)]
    _dump = [(d, t) for d, t, _n in _seen['progress']
             if t == len(_syms3)] + [('read', _seen['progress'][0][1])]
    check(f"STEP 3：进度**两段** —— 先读数（total=0）、再逐块计算；单调不减、收尾到底（实测 {_dump}）",
          _seen['progress'][0][1] == 0 and '读取' in _seen['progress'][0][2]
          and _calc_steps == sorted(_calc_steps) and _calc_steps[-1] == len(_syms3))

    # ---- ③ 取消：绝不落半成品 ----
    _store3 = _ss.ScanStore()
    _w2 = CrossSectionWorker(8, _zone3, _FORMULA, symbols=_syms3, chunk=1, store=_store3)
    _w2.cancel()                                    # 还没起跑就取消 ⇒ 第一个块边界就该停
    _out2 = []
    _w2.finished.connect(lambda j, o: _out2.append((j, o)))
    _w2.start()
    _w2.wait(30000)
    app.processEvents()
    check('★★ 取消：回包是 **None**（明确"没有结果"，而不是半个矩阵）+ `cancelled` 置位',
          _out2 == [(8, None)] and _w2.cancelled is True)
    check("★★ 取消：**会话缓存里一条都没落**"
          "（半个矩阵的命中家数 / 广度占比全是错的，而且界面上看不出来）",
          _store3.entries() == 0)

    # ---- ⑤ 缓存命中：一次计算都不跑 ----
    _store3b = _ss.ScanStore()
    _w3 = CrossSectionWorker(9, _zone3, _FORMULA, symbols=_syms3, chunk=2, store=_store3b)
    _w3.start()
    _w3.wait(30000)
    app.processEvents()
    _seen4, _out4 = [], []
    _w4 = CrossSectionWorker(10, _zone3, _FORMULA, symbols=_syms3, chunk=2, store=_store3b)
    _w4.progress.connect(lambda d, t, n: _seen4.append((d, t, n)))
    _w4.finished.connect(lambda j, o: _out4.append((j, o)))
    _w4.start()
    _w4.wait(30000)
    app.processEvents()
    check("★ 会话缓存命中 ⇒ **一次计算都不跑**（连进度信号都没有），直接回上次的矩阵",
          len(_out4) == 1 and _out4[0][1] is not None and _out4[0][1].cached is True
          and _seen4 == [])

    # ---- ④ 竞态实战：旧任务回包被丢弃 ----
    _guard2 = JobGuard()
    _accepted = []
    _job_old = _guard2.next()
    _w5 = CrossSectionWorker(_job_old, _zone3, _FORMULA, symbols=_syms3, chunk=2,
                             store=_ss.ScanStore())
    _w5.finished.connect(lambda j, o: _accepted.append(j) if _guard2.accept(j) else None)
    _w5.start()
    _job_new = _guard2.next()          # 旧任务还在跑，用户又发起一次 ⇒ 旧回包应作废
    _w5.wait(30000)
    app.processEvents()
    check("★★ 竞态实战：旧任务跑完后回包到来 ⇒ **被守卫丢弃**（不会覆盖新任务的状态）",
          _accepted == [] and _guard2.latest == _job_new)

    # ---- ⑥ 失败路径 ----
    _store3c = _ss.ScanStore()
    _fail = []
    _w6 = CrossSectionWorker(11, _zone3, 'C > 1;', symbols=_syms3, store=_store3c)
    _w6.failed.connect(lambda j, m: _fail.append((j, m)))
    _w6.start()
    _w6.wait(30000)
    app.processEvents()
    check("STEP 3：公式错误 ⇒ 走 `failed`（**异常绝不穿透 QThread**，也不会静默无回包）",
          len(_fail) == 1 and _fail[0][0] == 11 and bool(_fail[0][1]))
    check("STEP 3：失败也不污染会话缓存（**只落成功的结果**）", _store3c.entries() == 0)

    _shutil.rmtree(_zone3, ignore_errors=True)
    check("假数据湖已删除（临时探针用完即删）", not os.path.isdir(_zone3))
except Exception as _e:  # noqa: BLE001
    check(f"后台扫描线程断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# §7-B1/B2 STEP 5 · ⚡ 增量到最新（主案 D7）：尾段续接 / 历史不动 / 诚实退化
#   判据：① 数据追加 ⇒ 数据版本变 ⇒ 键变，但 `find_base` 能找到**同配置旧条目**做基座
#         ② 合并后的矩阵 == 全量重扫（**逐位一致** —— 增量不许悄悄改变结果）
#         ③ **历史一天都不动**：旧日期的状态与广度 = 首轮结果逐位相同（D7 的用户契约）
#         ④ 重写但无新交易日（touch）⇒ 沿用原矩阵 + 明确回执（绝不静默）
#         ⑤ 标的集合变了 ⇒ 诚实退化全量（行序不同的矩阵不许硬接）
#         ⑥ Worker 通道：`incremental=True` 经 CrossSectionWorker 跑通（含诚实回执）
# ==========================================
print("\n== §7-B1/B2 STEP 5 · ⚡ 增量到最新：尾段续接 / 历史不动 / 诚实退化 ==")
try:
    import dataclasses as _dataclasses

    _zone5 = _tempfile.mkdtemp(prefix='jian_incr_zone_')
    _extra5 = pd.bdate_range(_days[-1] + pd.Timedelta(days=1), periods=10)
    _all_days5 = _days.append(_extra5)
    _syms5 = ['UP', 'DOWN']
    _th5 = _cs.ScanThresholds(min_bars=None)      # 关掉 min_bars：信号全程可判，广度非平凡
    _store5 = _ss.ScanStore()

    def _mk5(closes, index):
        """STEP 5 专用帧构造：日期轴可以**长于** `_days`（增量要追加新交易日）。"""
        values = np.asarray(closes, dtype=float)
        return pd.DataFrame({'date': list(index), 'open': values,
                             'high': values * 1.02, 'low': values * 0.98,
                             'close': values, 'volume': 1e6, 'amount': 1e8})

    _mk5(_up, _days).to_parquet(os.path.join(_zone5, 'UP.parquet'), index=False)
    _mk5(_down, _days).to_parquet(os.path.join(_zone5, 'DOWN.parquet'), index=False)
    _first5 = _ss.scan_cached(_zone5, _FORMULA, symbols=_syms5, thresholds=_th5,
                              asof=_days[-1], store=_store5)
    check("STEP 5：首轮扫描落缓存（增量路径的基座）",
          _first5.cached is False and _first5.result.status_matrix is not None
          and len(_first5.result.dates) == 300)

    # ---- ① 追加 10 个新交易日（UP 上行 ⇒ 全真；DOWN 下行 ⇒ 全假）----
    _mk5(np.concatenate([_up, np.linspace(20.0, 25.0, 10)]),
         _all_days5).to_parquet(os.path.join(_zone5, 'UP.parquet'), index=False)
    _mk5(np.concatenate([_down, np.linspace(10.0, 5.0, 10)]),
         _all_days5).to_parquet(os.path.join(_zone5, 'DOWN.parquet'), index=False)
    _incr5 = _ss.scan_cached(_zone5, _FORMULA, symbols=_syms5, thresholds=_th5,
                             asof=None, store=_store5, incremental=True)
    check("★ STEP 5：增量回执说清**续了几天 + 历史沿用原矩阵**（§10-10：绝不静默）",
          _incr5.cached is False and '+10' in _incr5.note and '历史沿用原矩阵' in _incr5.note
          and len(_incr5.result.dates) == 310)
    check("STEP 5：增量回包的 M2 语义正确（新基准日：UP 命中 / DOWN 未命中）",
          _incr5.result.counts['hit'] == 1 and _incr5.result.counts['miss'] == 1
          and _incr5.status_on(_all_days5[-1]) == {'UP': _cs.HIT, 'DOWN': _cs.MISS})

    # ---- ② 逐位一致：增量结果 == 全量重扫 ----
    _full_store5 = _ss.ScanStore()
    _full5 = _ss.scan_cached(_zone5, _FORMULA, symbols=_syms5, thresholds=_th5,
                             asof=None, store=_full_store5)
    check("★★ STEP 5：**增量合并 == 全量重扫**（矩阵/家数/日期轴逐位一致）"
          " —— 增量不许悄悄改变结果",
          np.array_equal(_incr5.result.status_matrix, _full5.result.status_matrix)
          and np.array_equal(_incr5.result.counters, _full5.result.counters)
          and _incr5.result.dates.equals(_full5.result.dates))

    # ---- ③ 历史一天都不动（D7 的用户契约）----
    check("★ STEP 5：**历史一天都没动** —— 旧 300 天的广度与首轮结果逐位相同",
          np.array_equal(_incr5.result.counters[:300], _first5.result.counters)
          and _incr5.status_on(_days[-1]) == _first5.status_on(_days[-1]))

    # ---- ④ touch（重写但无新交易日）⇒ 沿用原矩阵 + 明确回执 ----
    _mk5(np.concatenate([_up, np.linspace(20.0, 25.0, 10)]),
         _all_days5).to_parquet(os.path.join(_zone5, 'UP.parquet'), index=False)
    _touch5 = _ss.scan_cached(_zone5, _FORMULA, symbols=_syms5, thresholds=_th5,
                              asof=None, store=_store5, incremental=True)
    check("★ STEP 5：数据版本变了但**没有新增交易日** ⇒ 沿用原矩阵 + 回执点明"
          "「怀疑历史被修订请用全量重算」（不静默、不假装增量）",
          _touch5.cached is True and '没有新增交易日' in _touch5.note
          and _touch5.result is _incr5.result)

    # ---- ⑤ 标的集合变了 ⇒ 诚实退化全量 ----
    os.remove(os.path.join(_zone5, 'DOWN.parquet'))
    _shift5 = _ss.scan_cached(_zone5, _FORMULA, symbols=_syms5, thresholds=_th5,
                              asof=None, store=_store5, incremental=True)
    check("★ STEP 5：参与计算的**标的集合变了** ⇒ 不许硬接矩阵，诚实退化全量并出声"
          "（v6.42 新契约：文件被删的 DOWN 不再静默消失，记「数据不足」并进总数）",
          _shift5.cached is False and '全量' in _shift5.note
          and _shift5.result.counts['total'] == 2
          and _shift5.result.status['DOWN'] == _cs.INSUFFICIENT)

    # ---- ⑤b find_base 直测：同配置旧版本能找到；同版本不归它管 ----
    _k5 = _ss.scan_key(_FORMULA, _th5, _syms5, zone_dir=_zone5)
    _k5_fake = _dataclasses.replace(_k5, data_version='f4k3-v3rs10n')
    _probe_store5 = _ss.ScanStore()
    _probe_store5.put(_k5, _first5.result)
    check("STEP 5：`find_base` 认「同配置、**不同数据版本**」的条目（增量基座的唯一判据）",
          _probe_store5.find_base(_k5_fake) is _first5.result
          and _probe_store5.find_base(_k5) is None)

    # ---- ⑥ Worker 通道 ----
    _mk5(_up, _days).to_parquet(os.path.join(_zone5, 'DOWN.parquet'), index=False)  # 恢复两只
    _store5w = _ss.ScanStore()
    _wout5 = []
    _w7 = CrossSectionWorker(12, _zone5, _FORMULA, symbols=_syms5, chunk=2,
                             store=_store5w, incremental=True)
    _w7.finished.connect(lambda j, o: _wout5.append((j, o)))
    _w7.start()
    _w7.wait(30000)
    app.processEvents()
    check("STEP 5：Worker 通道（incremental=True）—— 无基座时**诚实退化全量**，job_id 原样回包",
          len(_wout5) == 1 and _wout5[0][0] == 12 and _wout5[0][1] is not None
          and '全量' in _wout5[0][1].note)
    _wout6 = []
    _w8 = CrossSectionWorker(13, _zone5, _FORMULA, symbols=_syms5, chunk=2,
                             store=_store5w, incremental=True)
    _w8.finished.connect(lambda j, o: _wout6.append((j, o)))
    _w8.start()
    _w8.wait(30000)
    app.processEvents()
    check("STEP 5：Worker 通道 —— 数据没变时增量 = **命中 + 明确说「已算到最新」**",
          len(_wout6) == 1 and _wout6[0][1] is not None and _wout6[0][1].cached is True
          and '已算到最新' in _wout6[0][1].note)

    _shutil.rmtree(_zone5, ignore_errors=True)
    check("假数据湖已删除（临时探针用完即删）", not os.path.isdir(_zone5))
except Exception as _e:  # noqa: BLE001
    check(f"增量断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# §7-B1/B2 STEP 6 · 就绪度体检（主案 D6-1 · `data/readiness.py`）
#   判据：① 四分类各就各位（就绪 / 历史不足 / 未下载 / 文件损坏 —— **不许并桶、不许静默跳过**）
#         ② **只读 footer**：行数 + date 统计（实测 0.66 ms/只）；坏文件进问题清单不废整轮
#         ③ min_bars 关掉 ⇒ "历史不足"回到就绪（与粗筛阈值同源）
#         ④ 缺口 / 问题清单 / 一行人话摘要 / 缺口预览各有一份实现
#         ⑤ 取消 = 抛 ReadinessCancelled（绝不回半截报告）；进度每 chunk 一次
#         ⑥ 成分股失败文案 = friendly_constituent_message（分类安抚，§10-10）
# ==========================================
print("\n== §7-B1/B2 STEP 6 · 就绪度体检：只读 footer / 四分类 / 问题清单 ==")
try:
    from data.readiness import (ReadinessCancelled, ReadinessReport,  # noqa: E402
                                probe_readiness)
    from data.sync_service import friendly_constituent_message  # noqa: E402

    _zone6 = _tempfile.mkdtemp(prefix='jian_ready_zone_')
    _mk5(_up, _days).to_parquet(os.path.join(_zone6, 'READY.parquet'), index=False)
    _mk5(_up[:50], _days[:50]).to_parquet(os.path.join(_zone6, 'SHORT.parquet'), index=False)
    with open(os.path.join(_zone6, 'BROKEN.parquet'), 'wb') as _f6:
        _f6.write(b'not a parquet file')

    def _probe6(**kw):
        return probe_readiness(_zone6, ['READY', 'SHORT', 'MISSING', 'BROKEN'], **kw)

    _rep6 = _probe6(min_bars=250)
    check("STEP 6：四分类各就各位 —— 就绪 / 历史不足(50行) / 未下载 / 文件损坏",
          _rep6.ready == ['READY'] and _rep6.partial.get('SHORT') == 50
          and _rep6.missing == ['MISSING'] and list(_rep6.unreadable) == ['BROKEN']
          and _rep6.total == 4)
    check("★ STEP 6：坏文件**进问题清单、不废整轮**（其余 3 只照常出结果，绝不静默跳过）",
          len(_rep6.unreadable) == 1 and len(_rep6.ready) + len(_rep6.partial) == 2)
    check("STEP 6：`latest` 来自 footer 统计（本地日线最新到几号，D6-1）",
          _rep6.latest is not None and pd.Timestamp(_rep6.latest) == _days[-1])
    check("STEP 6：一行摘要说清全局（就绪 N/M · 未下载 · 历史不足 · 文件损坏 · 本地最新）",
          '就绪 1/4' in _rep6.summary_line() and '未下载 1' in _rep6.summary_line()
          and '历史不足 1' in _rep6.summary_line() and '文件损坏 1' in _rep6.summary_line()
          and '本地最新' in _rep6.summary_line())
    check("STEP 6：缺口 = 未下载（partial 补不齐不算缺口）；问题清单 = 损坏文件",
          _rep6.gap_symbols() == ['MISSING'] and _rep6.problem_symbols() == ['BROKEN']
          and _rep6.gap_count == 1)
    check("STEP 6：缺口预览**看得见名字**（不许只给一个数字）",
          'MISSING' in _rep6.gap_preview() and '1 只' in _rep6.gap_preview())
    check("STEP 6：详情文本把「每类问题怎么办」说清（未下载→补齐 / 损坏→重新全量下载）",
          '补齐' in _rep6.detail_text() and '重新全量下载' in _rep6.detail_text()
          and '补不齐' in _rep6.detail_text())

    _rep_off = _probe6(min_bars=None)
    check("STEP 6：min_bars 关掉 ⇒ 「历史不足」回到就绪（阈值与粗筛同源，关掉 = 不设门槛）",
          len(_rep_off.ready) == 2 and not _rep_off.partial)

    _seen6 = []
    probe_readiness(_zone6, ['READY', 'SHORT', 'MISSING', 'BROKEN'],
                    progress=lambda d, t, n: _seen6.append((d, t)))
    check("STEP 6：进度收尾必报（4 只 → 1 次收尾回调，done==total）",
          len(_seen6) == 1 and _seen6[0] == (4, 4))
    try:
        probe_readiness(_zone6, ['READY'], should_stop=lambda: True)
        check("★ STEP 6：取消 ⇒ 抛 ReadinessCancelled（绝不回半截报告）", False)
    except ReadinessCancelled:
        check("★ STEP 6：取消 ⇒ 抛 ReadinessCancelled（绝不回半截报告）", True)

    _rep_empty = probe_readiness(_zone6, [])
    check("STEP 6：空范围 ⇒ 摘要直说「范围是空的」（不假装体检过）",
          _rep_empty.total == 0 and '范围是空的' in _rep_empty.summary_line())
    _rep_none = probe_readiness(os.path.join(_zone6, '__nope__'), ['READY'])
    check("STEP 6：分区目录不存在 ⇒ 全部按「未下载」处理（不崩、不出假就绪）",
          _rep_none.missing == ['READY'] and not _rep_none.ready)

    check("STEP 6：成分股失败文案 = **分类安抚**（no_data 说清「源未收录/代码有误」+ 替代路径，§10-10）",
          '行情源未返回名单' in friendly_constituent_message('000300', {'reason': 'no_data'})
          and '全市场' in friendly_constituent_message('000300', {'reason': 'no_data'})
          and '网络请求失败' in friendly_constituent_message('000300', {'reason': 'network'})
          and '不是用户的错' not in friendly_constituent_message('000300', {'reason': 'no_data'}))

    # ---- 成分股代码规范化（2026-09-20 用户实测：选沪深300 每次都"接口未返回成分股"）----
    #   根因 = 两套指数代码约定并存：日线要带前缀（sh000300，INDEX_PRESETS 键），
    #   成分股三接口只要 6 位裸码 —— 带前缀直接透传 = 三个接口全失败。
    #   修复 = normalize_cons_code 收在行情源边界（§11.5-19 / §11.5-62）。
    import data.akshare_feed as _af  # noqa: E402

    check("★ STEP 6：成分股代码规范化（sh000300/SZ399006 → 6 位裸码；纯数字原样；坏码不脑补）",
          _af.normalize_cons_code('sh000300') == '000300'
          and _af.normalize_cons_code('SZ399006') == '399006'
          and _af.normalize_cons_code(' 000016 ') == '000016'
          and _af.normalize_cons_code('bj899050') == '899050'
          and _af.normalize_cons_code('000300') == '000300'
          and _af.normalize_cons_code('abc') == 'abc')

    class _FakeConsAK:
        """打桩 akshare：记录成分股接口收到的 symbol（验证规范化发生在调用前）。"""

        def __init__(self):
            self.calls = []

        def index_stock_cons(self, symbol):
            self.calls.append(str(symbol))
            return pd.DataFrame({'成分券代码': ['000001', '000002']})

    _fake_ak = _FakeConsAK()
    _real_ak = _af.ak
    _af.ak = _fake_ak
    try:
        _cons_df = _af.AkShareFeed.fetch_index_constituents('sh000300')
        _bad_df = _af.AkShareFeed.fetch_index_constituents('不是代码')
    finally:
        _af.ak = _real_ak
    check("★ STEP 6：带前缀代码**进接口前被规范化**（sh000300 → 以 000300 调 akshare）",
          _fake_ak.calls == ['000300']
          and list(_cons_df['symbol']) == ['000001', '000002'])
    check("STEP 6：乱码**快速失败**（不发任何网络请求、回空 DF 让上层给人话提示）",
          len(_fake_ak.calls) == 1 and _bad_df.empty)

    # ---- v6.42：成分股换权威源 + 快照日期 + 名义只数核对（用户实测 300→288 之谜）----
    class _FakeConsAK2:
        """打桩：官网给全名单（带「日期」+**「指数代码」列**，与线上真实列结构一致 ——
        v6.42 回归教训：旧选列逻辑"第一个含'代码'的列"会命中「指数代码」，
        把沪深300自己当成唯一成分；打桩必须带这列才钉得住）。同花顺只给一部分验官网优先。"""

        def __init__(self):
            self.calls = []

        def index_stock_cons_csindex(self, symbol):
            self.calls.append(('csindex', str(symbol)))
            return pd.DataFrame({'日期': ['2026-09-18'] * 3,
                                 '指数代码': ['000300'] * 3,
                                 '指数名称': ['沪深300'] * 3,
                                 '成分券代码': ['000001', '000002', '600000']})

        def index_stock_cons(self, symbol):
            self.calls.append(('ths', str(symbol)))
            return pd.DataFrame({'品种代码': ['000001'], '纳入日期': ['2026-06-15']})

    _fake_ak2 = _FakeConsAK2()
    _real_ak2 = _af.ak
    _af.ak = _fake_ak2
    try:
        _cons_df2 = _af.AkShareFeed.fetch_index_constituents('sh000300')
        import data.sync_service as _svc  # noqa: E402
        _feed_real2 = _svc.AkShareFeed

        class _WrapFeed2:
            @staticmethod
            def fetch_index_constituents(code):
                return _cons_df2

        _svc.AkShareFeed = _WrapFeed2
        _payload2 = _svc.MarketSyncService.fetch_index_constituents(
            object.__new__(_svc.MarketSyncService), '000300',
            policy=_svc.ThrottlePolicy(interval=0))
        _svc.AkShareFeed = _feed_real2
    finally:
        _af.ak = _real_ak2
    check("★ v6.42：成分股**优先中证指数官网**（权威名单；同花顺快照缺斤短两降为兜底）",
          _fake_ak2.calls[0][0] == 'csindex'
          and list(_cons_df2['symbol']) == ['000001', '000002', '600000'])
    check("★★ v6.42 回归钉：选列绝不许命中「指数代码」（用户实测：沪深300 名单只剩 000300 自己）",
          '000300' not in list(_cons_df2['symbol']))
    check("★ v6.42：名单带**快照日期**（官网「日期」列 → payload.snapshot_date/count）",
          str(_cons_df2['snapshot_date'].iloc[0]) == '2026-09-18'
          and _payload2.get('snapshot_date') == '2026-09-18'
          and _payload2.get('count') == 3 and _payload2.get('ok') is True)
    from ui.widgets.readiness_flow import constituent_snapshot_text as _cst  # noqa: E402
    check("★ v6.42：名义只数核对 —— 来源只回 288/300 时 UI **当场说出**（不静默拿缺名单当全的用）",
          '288/300' in _cst('沪深300', {'count': 288, 'snapshot_date': '2026-09-18'})
          and '288' not in _cst('沪深300', {'count': 300, 'snapshot_date': '2026-09-18'})
          and '名单快照 2026-09-18' in _cst('沪深300', {'count': 300,
                                                        'snapshot_date': '2026-09-18'})
          and '⚠' not in _cst('创业板指', {'count': 100, 'snapshot_date': ''}))

    _shutil.rmtree(_zone6, ignore_errors=True)
    check("假数据湖已删除（临时探针用完即删）", not os.path.isdir(_zone6))
except Exception as _e:  # noqa: BLE001
    check(f"就绪度体检断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
print("\n== §7-B10 · 日线收盘定稿守卫 + 交易日历（纯函数）==")
# ==========================================
try:
    import shutil as _sh2
    import tempfile as _tfd
    import pandas as _pdt
    from datetime import datetime as _dtc, date as _dc
    from data.sync_service import is_daily_bar_settled, _drop_unsettled_tail
    from data.trade_calendar import (latest_settled_trading_day,
                                     previous_trading_day, load_or_fetch,
                                     trading_days_between)
    from data.readiness import format_stale

    # ① is_daily_bar_settled 四态（盘中今天10:30 / 盘后15:30）
    _noon = _dtc(2026, 9, 22, 10, 30)
    _close = _dtc(2026, 9, 22, 15, 30)
    check("定稿：昨天恒已定稿", is_daily_bar_settled(_dc(2026, 9, 21), _noon))
    check("定稿：今天盘中未定稿", not is_daily_bar_settled(_dc(2026, 9, 22), _noon))
    check("定稿：今天盘后已定稿", is_daily_bar_settled(_dc(2026, 9, 22), _close))
    check("定稿：未来日未定稿", not is_daily_bar_settled(_dc(2026, 9, 23), _close))

    # ② _drop_unsettled_tail 只削未定稿当天、不碰历史/盘后
    _dfc = _pdt.DataFrame({'date': _pdt.to_datetime(
        ['2026-09-18', '2026-09-21', '2026-09-22']), 'close': [1, 2, 3]})
    _dropped = _drop_unsettled_tail(_dfc, now=_noon)
    check("裁尾：盘中把今天削掉",
          len(_dropped) == 2
          and _dropped['date'].max() == _pdt.Timestamp('2026-09-21'))
    check("裁尾：盘后保留今天", len(_drop_unsettled_tail(_dfc, now=_close)) == 3)
    _dfc2 = _pdt.DataFrame({'date': _pdt.to_datetime(['2026-09-18']), 'close': [1]})
    check("裁尾：不含今天原样返回（幂等）",
          len(_drop_unsettled_tail(_dfc2, now=_noon)) == 1)

    # ③ latest_settled_trading_day / previous_trading_day
    _cal = [_dc(2026, 9, 17), _dc(2026, 9, 18), _dc(2026, 9, 21), _dc(2026, 9, 22)]
    check("最近定稿交易日：盘中今天→上一交易日",
          latest_settled_trading_day(now=_noon, calendar=_cal) == _dc(2026, 9, 21))
    check("最近定稿交易日：盘后今天→今天",
          latest_settled_trading_day(now=_close, calendar=_cal) == _dc(2026, 9, 22))
    _cal2 = [_dc(2026, 9, 25), _dc(2026, 9, 28)]   # 25 周五 / 28 下周一，今天 26 周六
    check("最近定稿交易日：周末→最近的过去交易日",
          latest_settled_trading_day(now=_dtc(2026, 9, 26, 12, 0), calendar=_cal2)
          == _dc(2026, 9, 25))
    check("最近定稿交易日：日历 None→None（交调用方回退）",
          latest_settled_trading_day(now=_noon, calendar=None) is None)
    check("previous_trading_day 严格早于 ref",
          previous_trading_day(_dc(2026, 9, 22), _cal) == _dc(2026, 9, 21))

    # ④ load_or_fetch 三重兜底（注入假 fetch + 临时缓存，绝不联网）
    _tmpc = _tfd.mkdtemp(prefix='jian_cal_')
    _cp = os.path.join(_tmpc, 'tc.json')
    _calls = []

    def _fake_fetch():
        _calls.append(1)
        return _pdt.DataFrame({'date': _pdt.to_datetime(
            ['2026-09-18', '2026-09-21', '2026-09-22'])})

    _got = load_or_fetch(fetch_fn=_fake_fetch, now=_noon, cache_path=_cp)
    check("load_or_fetch：未命中→抓一次并落盘",
          _calls == [1] and _got and _got[-1] == _dc(2026, 9, 22))
    _got2 = load_or_fetch(fetch_fn=_fake_fetch, now=_noon, cache_path=_cp)
    check("load_or_fetch：缓存命中→不再联网", _calls == [1] and _got2 == _got)

    def _boom():
        raise RuntimeError('net down')

    _got3 = load_or_fetch(fetch_fn=_boom, now=_dtc(2027, 1, 5, 10, 30), cache_path=_cp)
    check("load_or_fetch：抓取失败→回吐旧缓存", _got3 == _got)
    _got4 = load_or_fetch(fetch_fn=_boom, now=_dtc(2030, 1, 1),
                          cache_path=os.path.join(_tmpc, 'none.json'))
    check("load_or_fetch：失败且无缓存→None", _got4 is None)
    _sh2.rmtree(_tmpc, ignore_errors=True)

    # ⑤ trading_days_between 精确数交易日（跨周末不虚报）
    _cal5 = [_dc(2026, 1, 5), _dc(2026, 1, 6), _dc(2026, 1, 7), _dc(2026, 1, 8), _dc(2026, 1, 9)]
    check("trading_days_between：(1/6, 1/9] = 3 个日历日",
          trading_days_between(_dc(2026, 1, 6), _dc(2026, 1, 9), _cal5) == 3)
    check("trading_days_between：a>=b → 0（不早于不算滞后）",
          trading_days_between(_dc(2026, 1, 9), _dc(2026, 1, 6), _cal5) == 0)
    check("trading_days_between：任一 None / 无日历 → 0",
          trading_days_between(None, _dc(2026, 1, 9), _cal5) == 0
          and trading_days_between(_dc(2026, 1, 5), None, _cal5) == 0
          and trading_days_between(_dc(2026, 1, 5), _dc(2026, 1, 9), None) == 0)

    # ⑥ format_stale 滞后文案（零 UI、可单测）
    check("format_stale：滞后>0 出完整提示（含本地/最近交易日/引导）",
          '滞后' in format_stale(_dc(2026, 1, 5), _dc(2026, 1, 9), 3)
          and '2026-01-05' in format_stale(_dc(2026, 1, 5), _dc(2026, 1, 9), 3)
          and '更新到最新' in format_stale(_dc(2026, 1, 5), _dc(2026, 1, 9), 3))
    check("format_stale：无滞后/缺参 → 空串（诚实不打扰）",
          format_stale(_dc(2026, 1, 9), _dc(2026, 1, 9), 0) == ''
          and format_stale(None, _dc(2026, 1, 9), 3) == ''
          and format_stale(_dc(2026, 1, 5), None, 3) == '')

    # ⑦ ReadinessReport.representative_latest / coverage_at（§7-B10 覆盖诚实提示的底层）
    from data.readiness import ReadinessReport as _RRep7
    _r7 = _RRep7(total=3, ready=['a', 'b', 'c'],
                 latest=_pdt.Timestamp('2026-09-22'),
                 lasts=[_pdt.Timestamp('2026-09-20'), _pdt.Timestamp('2026-09-21'),
                        _pdt.Timestamp('2026-09-22')])
    check("representative_latest = 中位日（不被单只最新掩盖）",
          _r7.representative_latest == _pdt.Timestamp('2026-09-21'))
    check("coverage_at：9/22=1 · 9/21=2 · 9/20=3（逐日统计覆盖）",
          _r7.coverage_at(_dc(2026, 9, 22)) == 1 and _r7.coverage_at(_dc(2026, 9, 21)) == 2
          and _r7.coverage_at(_dc(2026, 9, 20)) == 3)
    _r7b = _RRep7(total=1, latest=_pdt.Timestamp('2026-09-22'))
    check("无 lasts → representative_latest 退回 latest、coverage_at=0",
          _r7b.representative_latest == _pdt.Timestamp('2026-09-22')
          and _r7b.coverage_at(_dc(2026, 9, 22)) == 0)
except Exception as _e:  # noqa: BLE001
    check(f"§7-B10 定稿守卫/日历断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
print("\n== §7-A4 · 回测历史存档（存储层：抽稀/往返/淘汰/防注入/只读不写盘）==")
# ==========================================
try:
    import shutil as _sh4
    import tempfile as _tf4
    import json as _json4
    import pandas as _pd4
    import data.backtest_archive as _arc4
    from core.backtest import BacktestResult as _BR4, BacktestTrade as _BT4
    from data.backtest_archive import (BacktestArchive, build_record, record_to_result,
                                       sample_equity, PER_SYMBOL_CAP, TOTAL_CAP,
                                       MAX_FILE_BYTES, EQUITY_MAX_POINTS, KIND_M1,
                                       KIND_M2, KIND_M3, SOURCE_MANUAL)

    def _mk_result(symbol='600000'):
        dates = _pd4.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'])
        eq = _pd4.DataFrame({'date': dates, 'equity': [1.0, 1.1, 1.05, 1.2],
                             'in_market': [0, 1, 1, 1]})
        tr = [_BT4(entry_date=dates[1], exit_date=dates[3], entry_price=10.0,
                   exit_price=12.0, pnl=2.0, return_pct=0.2)]
        return _BR4(symbol, 'B', 'S', '2024-01-02', '2024-01-05', trades=tr, equity=eq)

    _meta4 = {'symbol': '600000', 'name': '长江电力', 'strategy_name': '绿蓝红',
              'start_date': '2024-01-02', 'end_date': '2024-01-05', 'segments': [],
              'params_text': '', 'buy_expr': 'B', 'sell_expr': 'S', 'risk': {},
              'fill': {'fill_mode': 'next_open', 'trigger_tick': 1}, 'index': None}
    _roots = []      # 统一收尾清理

    def _tmp4(prefix='jian_arc_'):
        _p = _tf4.mkdtemp(prefix=prefix)
        _roots.append(_p)
        return _p

    # ⓪ 口径常量（唯一出处 = data/backtest_archive.py）
    check("存档上限常量：每标的20 / 总量500 / 单份2MB / 净值≤250点",
          PER_SYMBOL_CAP == 20 and TOTAL_CAP == 500
          and MAX_FILE_BYTES == 2 * 1024 * 1024 and EQUITY_MAX_POINTS == 250)
    check("★ v1.46：三种 kind 都已启用（M2/M3 不再是『预留』）",
          (KIND_M1, KIND_M2, KIND_M3) == ('M1', 'M2', 'M3'))
    check("上限说明 caps() 与常量同源",
          BacktestArchive.caps()['per_symbol'] == PER_SYMBOL_CAP
          and BacktestArchive.caps()['total'] == TOTAL_CAP)

    # ① save → list → load → pin → delete 往返
    _root4 = _tmp4()
    _ar4 = BacktestArchive(root=_root4)
    _rid = _ar4.save(build_record(_mk_result(), _meta4, config={'symbol': '600000'}))
    check("save 返回 id 且落一个 json + _index.json",
          bool(_rid)
          and os.path.exists(os.path.join(_root4, _rid + '.json'))
          and os.path.exists(os.path.join(_root4, '_index.json')))
    _lst = _ar4.list(kind='M1')
    check("list 命中 1 条、kind=M1、带 KPI",
          len(_lst) == 1 and _lst[0]['kind'] == 'M1'
          and _lst[0]['cumulative_return'] is not None)
    _rec = _ar4.load(_rid)
    check("记录字段齐（meta/config/kpi/trades/equity/source/seq）",
          all(k in _rec for k in ('meta', 'config', 'kpi', 'trades', 'equity', 'source', 'seq')))
    check("记录带 kind=M1（M2/M3 未来复用同一 schema）", _rec['kind'] == 'M1')
    _ar4.set_pinned(_rid, True)
    check("pin 后 list 反映 pinned=True", _ar4.list()[0]['pinned'] is True)
    check("只看重点过滤命中", len(_ar4.list(only_pinned=True)) == 1)
    check("手动来源标记 source=manual",
          _ar4.save(build_record(_mk_result(), _meta4, source=SOURCE_MANUAL)) and
          _ar4.list()[0]['source'] == 'manual')
    check("delete 后该文件移除",
          _ar4.delete(_rid) and not os.path.exists(os.path.join(_root4, _rid + '.json'))
          and all(e['id'] != _rid for e in _ar4.list()))

    # ② 净值抽稀：端点保底（cumulative_return 依赖末点）+ 并入全部成交日 + in_market
    _bd = _pd4.date_range('2020-01-01', periods=1000, freq='D')
    _big = _BR4('600000', 'B', 'S', '2020-01-01', '2022-09-26',
                trades=[_BT4(entry_date=_bd[7], exit_date=_bd[601], entry_price=1.0,
                             exit_price=2.0, pnl=1.0, return_pct=1.0)],
                equity=_pd4.DataFrame({'date': _bd, 'equity': list(range(1000)),
                                       'in_market': [0] * 1000}))
    _samp = sample_equity(_big, max_points=250)
    _samp_dates = [r['date'] for r in _samp]
    _samp_plain = sample_equity(_BR4('600000', 'B', 'S', '2020-01-01', '2022-09-26',
                                     trades=[], equity=_big.equity), max_points=250)
    _grid = {round(i * 999 / 249) for i in range(250)}          # 均匀网格（无用例日）
    check("抽稀上限：没有成交日时不超过 250 点", len(_samp_plain) <= 250)
    check("抽稀点数 = 均匀网格 ∪ 成交日（本例 250 + 2 个网格外成交日）",
          len(_samp) == len(_samp_plain) + 2)
    check("端点保底：首点与**末点**都保留（末点丢=累计收益算错）",
          _samp_dates[0] == _bd[0].strftime('%Y-%m-%d')
          and _samp_dates[-1] == _bd[-1].strftime('%Y-%m-%d'))
    check("成交日并入是「必要」的（7 / 601 都不在均匀网格上）",
          7 not in _grid and 601 not in _grid)
    check("抽稀**强制并入全部成交日**（买卖点不丢）",
          _bd[7].strftime('%Y-%m-%d') in _samp_dates
          and _bd[601].strftime('%Y-%m-%d') in _samp_dates)
    check("抽稀保留 in_market 列",
          all(('in_market' in r) for r in _samp))
    _rec_big = build_record(_big, _meta4)
    check("抽稀后末点净值 == 原始末点（端点保底不引入偏差）",
          abs(_rec_big['equity'][-1]['equity'] - 999.0) < 1e-6)

    # ③ record_to_result 往返：trades / 买卖点列 / 累计
    _rb = record_to_result(_rec_big)
    check("record_to_result 往返：trades 数一致", len(_rb.trades) == 1)
    check("重建 equity 带 buy_at / sell_at（净值曲线靠它画买卖点）",
          'buy_at' in _rb.equity.columns and 'sell_at' in _rb.equity.columns
          and int(_rb.equity['buy_at'].notna().sum()) == 1
          and int(_rb.equity['sell_at'].notna().sum()) == 1)
    check("重建后 cumulative_return 仍等于 (末点净值 − 1)",
          abs(_rb.cumulative_return - 998.0) < 1e-6)
    _rb2 = record_to_result(build_record(_mk_result(), _meta4))
    check("record_to_result 往返：普通序列累计一致",
          len(_rb2.trades) == 1 and abs(_rb2.cumulative_return - 0.2) < 1e-6)

    # ④ 淘汰：分标的 + 全局 + **重点豁免**（用 monkeypatch 常量做小规模，快且不写 500 个文件）
    _cap0, _tot0 = _arc4.PER_SYMBOL_CAP, _arc4.TOTAL_CAP
    try:
        _arc4.PER_SYMBOL_CAP, _arc4.TOTAL_CAP = 3, 100
        _ar4b = BacktestArchive(root=_tmp4('jian_arc_cap_'))
        _pinned_id = _ar4b.save(build_record(_mk_result(), _meta4))
        _ar4b.set_pinned(_pinned_id, True)                 # 最早的这份标为重点
        for _ in range(5):
            _ar4b.save(build_record(_mk_result(), _meta4))
        _rows = _ar4b.list()
        check("每标的：非重点淘汰到 ≤3",
              sum(1 for e in _rows if not e['pinned']) == 3)
        check("★ 重点豁免淘汰（最早那份仍在）",
              any(e['id'] == _pinned_id for e in _rows))

        _arc4.PER_SYMBOL_CAP, _arc4.TOTAL_CAP = 100, 4
        _ar4d = BacktestArchive(root=_tmp4('jian_arc_tot_'))
        _first_id = _ar4d.save(build_record(_mk_result('000001'), _meta4))
        for _i in range(6):
            _ar4d.save(build_record(_mk_result(f'00000{_i + 2}'), _meta4))
        check("全局：总量淘汰到 ≤4（最旧的被淘汰）",
              len(_ar4d.list()) == 4 and all(e['id'] != _first_id for e in _ar4d.list()))
    finally:
        _arc4.PER_SYMBOL_CAP, _arc4.TOTAL_CAP = _cap0, _tot0

    # ⑤ 读路径**绝不写盘**（否则开一次页就把真实目录建出来）
    _ghost = os.path.join(_tmp4('jian_arc_ghost_'), 'never_created')
    _ar5 = BacktestArchive(root=_ghost)
    check("list() 不建目录", _ar5.list() == [] and not os.path.exists(_ghost))
    check("stats() 不建目录",
          _ar5.stats()['count'] == 0 and not os.path.exists(_ghost))
    check("load() 不建目录", _ar5.load('nope') is None and not os.path.exists(_ghost))
    check("delete 一个不存在的 id 也不建目录",
          _ar5.delete('nope') is False and not os.path.exists(_ghost))

    # ⑥ 索引自愈（只读）+ 僵尸项剔除
    _ar6 = BacktestArchive(root=_tmp4('jian_arc_heal_'))
    _rid6 = _ar6.save(build_record(_mk_result(), _meta4))
    os.remove(os.path.join(_ar6.root, '_index.json'))
    check("索引丢失 → list 从各存档文件重建", len(_ar6.list()) == 1)
    check("重建是**只读**的（不顺手把索引写回）",
          not os.path.exists(os.path.join(_ar6.root, '_index.json')))
    _rid6b = _ar6.save(build_record(_mk_result(), _meta4))     # 这次会把索引写回
    os.remove(os.path.join(_ar6.root, _rid6b + '.json'))       # 手删文件、留僵尸索引
    check("僵尸索引项（文件已不在）被剔除",
          len(_ar6.list()) == 1 and all(e['id'] != _rid6b for e in _ar6.list()))

    # ⑦ 防注入：文件名只用 时间戳_uuid；用户文本只进 JSON 字段
    _evil = dict(_meta4)
    _evil['strategy_name'] = '../../etc/passwd, 攻击'
    _evil['symbol'] = '600000'
    _rid3 = _ar6.save(build_record(_mk_result(), _evil))
    check("防注入：文件名无用户文本 / 无路径分隔",
          '/' not in _rid3 and '\\' not in _rid3 and '..' not in _rid3
          and os.path.exists(os.path.join(_ar6.root, _rid3 + '.json')))
    check("用户文本原样落在 JSON 字段里（转义而非执行）",
          _ar6.load(_rid3)['meta']['strategy_name'] == '../../etc/passwd, 攻击')
    check("id 文件名与策略名无关（不含'攻击'）", '攻击' not in _rid3)

    # ⑧ 超体积上限 → 拒存（防体积炸弹）；拒存时不落任何文件
    _mb0 = _arc4.MAX_FILE_BYTES
    try:
        _arc4.MAX_FILE_BYTES = 50
        _ar7 = BacktestArchive(root=_tmp4('jian_arc_big_'))
        check("超上限拒存（返回 None 且不落文件）",
              _ar7.save(build_record(_mk_result(), _meta4)) is None
              and _ar7.list() == []
              and not os.path.exists(os.path.join(_ar7.root, '_index.json')))
    finally:
        _arc4.MAX_FILE_BYTES = _mb0

    for _p in _roots:
        _sh4.rmtree(_p, ignore_errors=True)
    check("存档目录内容可被 JSON 序列化（无 bytes/NaN 残留）",
          bool(_json4.dumps(build_record(_mk_result(), _meta4), ensure_ascii=False)))
except Exception as _e:  # noqa: BLE001
    check(f"§7-A4 存档存储层断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
print("\n== §7-E2 · 代理失败分类 + 三出口文案 + 熔断提前（v1.38）==")
# ==========================================
try:
    import data.sync_service as _ss2
    import ui.workers as _uw2
    from data.sync_service import (ThrottlePolicy as _TP2, _classify_error,
                                   abort_reason_text, friendly_constituent_message,
                                   friendly_fetch_message, looks_like_proxy_error,
                                   short_fetch_reason)

    # ---- ① 分类判据：proxy 必须**先于** network 判定 ----
    #   真实链路：requests.exceptions.ProxyError → ... → IOError(**就是内建 OSError**)。
    #   所以"先 isinstance(error, OSError) 再看文本"会把代理失败归成 network
    #   —— 这正是 §9.3 里"归类没错、但用户看不出该去查代理"的成因。本断言钉住修法。
    class _FakeProxyError(OSError):
        pass

    _pe = _FakeProxyError("HTTPSConnectionPool(host='hq.sinajs.cn', port=443): Max retries exceeded "
                          "with url: / (Caused by ProxyError('Unable to connect to proxy', "
                          "RemoteDisconnected('Remote end closed connection without response')))")
    check("★ 代理失败归 `proxy`（**即使它是 OSError 子类** —— 判定顺序错了就会被吞成 network）",
          _classify_error(_pe) == "proxy" and isinstance(_pe, OSError))
    check("同判据接受纯文本（文案层复用同一入口）",
          looks_like_proxy_error("ProxyError: Unable to connect to proxy")
          and not looks_like_proxy_error("Read timed out"))
    check("普通超时 / 断连仍是 `network`（不误伤原有语义）",
          _classify_error(TimeoutError("timed out")) == "network"
          and _classify_error(ConnectionResetError("connection reset by peer")) == "network")
    check("其它异常仍是 `error`", _classify_error(ValueError("bad value")) == "error")

    # ---- ② 三个文案出口都认 proxy；三档原因文案互不相同；不写死端口、不带 markdown ----
    _rs = {"reason": "proxy", "message": "ProxyError('Unable to connect to proxy', ...)"}
    _short = short_fetch_reason(_rs)
    _single = friendly_fetch_message("600519", _rs)
    _cons = friendly_constituent_message("000300", _rs)
    check("★ 三出口都有 proxy 分支（不再笼统说「稍后重试」）",
          "代理" in _short and "代理" in _single and "代理" in _cons)
    check("★ 文案**不写死本机端口**（127.0.0.1:7897 只属于 §9.3 的诊断记录，不进用户文案）",
          all(("127.0.0.1" not in t and "7897" not in t) for t in (_short, _single, _cons)))
    check("★ 三档原因文案互不相同（分类安抚，§10-10）",
          len({_short, short_fetch_reason({"reason": "network"}),
               short_fetch_reason({"reason": "no_data"})}) == 3
          and friendly_fetch_message("600519", {"reason": "network"}) != _single
          and friendly_fetch_message("600519", {"reason": "no_data"}) != _single)
    check("用户文案里不出现 markdown 星号（Qt 弹窗是纯文本，星号会原样显示出来）",
          all("**" not in t for t in (_short, _single, _cons)))

    # ---- ③ 中断原因文案（公共件：三处消费方共用，别各写一遍）----
    check("★ abort_reason_text：proxy 说「查代理」/ cancel 说「被中断」/ 其余说「被限流」/ 未中断为空",
          "代理" in abort_reason_text({"aborted": True, "aborted_by": "proxy"})
          and "中断" in abort_reason_text({"aborted": True, "aborted_by": "cancel"})
          and "限流" in abort_reason_text({"aborted": True, "aborted_by": "circuit"})
          and abort_reason_text({"aborted": False}) == "")

    # ---- ④ 阈值：代理 3 必须远小于通用 12 ----
    _tp2 = _TP2()
    check("★ 代理熔断阈值 3 < 通用熔断阈值 12（代理全灭时不该白等十几次超时）",
          _tp2.proxy_circuit_breaker == 3 and _tp2.circuit_breaker == 12
          and _tp2.proxy_circuit_breaker < _tp2.circuit_breaker)

    # ---- ⑤ 熔断提前：真跑 SyncWorker（直接调 run()、不起线程 ⇒ 确定性，无等待）----
    class _StubSvc2:
        def __init__(self, reason):
            self.reason = reason
            self.calls = []

        def refresh_one(self, symbol, **kw):
            self.calls.append(symbol)
            return {"ok": False, "symbol": symbol, "reason": self.reason,
                    "message": self.reason, "rows": 0, "skipped": False}

    def _run_sync2(reason, n=15):
        stub = _StubSvc2(reason)
        _orig = _uw2.MarketSyncService
        _orig_cal = _uw2.load_or_fetch
        _uw2.MarketSyncService = lambda *a, **k: stub
        # ⚠ v1.40/§7-E5：`SyncWorker.run()` 现在会取交易日历（冷缓存 ⇒ 联网 + 写真实缓存）。
        #   测试打桩成 None ⇒ `inject_expected_latest` 原样返回策略（零行为变化），
        #   且**不联网、不污染** `~/.jian_data/trade_calendar.json`（收尾自检会查它的 mtime）。
        _uw2.load_or_fetch = lambda *a, **k: None
        try:
            w = _uw2.SyncWorker([f"S{i:03d}" for i in range(n)],
                                policy=_TP2(interval=0, jitter=0))
            out = []
            w.finished.connect(lambda s: out.append(s))
            w.run()
            return (out[0] if out else {}), stub
        finally:
            _uw2.MarketSyncService = _orig
            _uw2.load_or_fetch = _orig_cal

    _pro, _pro_stub = _run_sync2("proxy")
    check("★ 代理连败 **3 次**即熔断（不是默认的 12 次）—— 且原因带回 UI",
          _pro.get("aborted") and _pro.get("aborted_by") == "proxy"
          and _pro.get("fail") == 3 and len(_pro_stub.calls) == 3)
    _net, _net_stub = _run_sync2("network")
    check("非代理失败仍按通用阈值 12 熔断（`aborted_by=circuit`，原语义不被误伤）",
          _net.get("aborted") and _net.get("aborted_by") == "circuit"
          and _net.get("fail") == 12 and len(_net_stub.calls) == 12)
    _few, _ = _run_sync2("network", n=2)
    check("没到阈值 ⇒ 不中断（`aborted=False`、`aborted_by` 为空）",
          not _few.get("aborted") and _few.get("aborted_by") == "" and _few.get("fail") == 2)
    _cancel = _uw2.SyncWorker(["S000", "S001"])
    _cancel.cancel()
    _out_c = []
    _cancel.finished.connect(lambda s: _out_c.append(s))
    _orig_cal3 = _uw2.load_or_fetch
    _uw2.load_or_fetch = lambda *a, **k: None       # 同上：不联网、不写真实日历缓存
    try:
        _cancel.run()
    finally:
        _uw2.load_or_fetch = _orig_cal3
    check("用户主动中断 ⇒ `aborted_by=cancel`（与熔断区分开，回执文案不同）",
          _out_c and _out_c[0].get("aborted_by") == "cancel")
except Exception as _e:  # noqa: BLE001
    check(f"§7-E2 代理分类/熔断断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
print("\n== §7-E3 · 日线落盘列白名单（v1.39）==")
# ==========================================
try:
    import pandas as _pd3
    from core import cross_section as _cs3
    from data.akshare_feed import (DAILY_KEEP_COLUMNS, OHLCV_COLUMNS, AkShareFeed)

    _JUNK3 = {'股票代码', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率', '持仓量', '动态结算价'}

    check("白名单 = OHLCV + symbol/amount/turnover/outstanding_share",
          set(OHLCV_COLUMNS) <= set(DAILY_KEEP_COLUMNS)
          and {'symbol', 'amount', 'turnover', 'outstanding_share'} <= set(DAILY_KEEP_COLUMNS))
    check("白名单不含任何杂列（东财中文透传列 / 期货列）",
          not (_JUNK3 & set(DAILY_KEEP_COLUMNS)))

    # ★★ 本项**最高价值**的一条：白名单必须覆盖下游真正要读的列 ——
    #    否则将来任何一次"裁列"都会让换手率 / 流通市值筛选**静默失效**（§9.1 的核心警告）。
    _req3 = set(_cs3._BASE_COLUMNS) | set(_cs3.columns_for(
        _cs3.ScanThresholds(min_turnover=0.01, min_float_mktcap=1e9)))
    check("★★ 白名单覆盖横截面内核所需的**全部**列（少一个 = 该筛选静默失效）",
          _req3 <= set(DAILY_KEEP_COLUMNS))

    # 照 v1.39 实测的三类杂列构造真实脏数据
    _dirty3 = _pd3.DataFrame({
        '日期': ['2024-01-02', '2024-01-03'], '开盘': [10.0, 10.5], '收盘': [10.5, 10.6],
        '最高': [10.6, 10.7], '最低': [9.9, 10.4], '成交量': [1e6, 1.1e6],
        '成交额': [1e7, 1.1e7], '振幅': [0.07, 0.03], '涨跌幅': [5.0, 0.95],
        '涨跌额': [0.5, 0.1], '换手率': [0.93, 1.02], '股票代码': ['600519'] * 2,
        '持仓量': [1, 2], '动态结算价': [1.0, 2.0],
    })
    _out3 = AkShareFeed._normalize_ohlcv(
        _dirty3, {'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high',
                  '最低': 'low', '成交量': 'volume'}, '600519')
    check("★ 脏数据清洗后**只剩白名单列**（三类杂列全被挡在湖外）",
          set(_out3.columns) <= set(DAILY_KEEP_COLUMNS) and not (_JUNK3 & set(_out3.columns))
          and 'date' in _out3.columns and 'symbol' in _out3.columns)

    # apply-if-present：各分区列集合本来不同（v1.39 实测 index_daily 无 amount、kline_min 无 symbol）
    _only_ohlcv3 = _pd3.DataFrame({'date': ['2024-01-02'], 'open': [1.0], 'high': [1.1],
                                   'low': [0.9], 'close': [1.05], 'volume': [100]})
    _out3b = AkShareFeed._normalize_ohlcv(_only_ohlcv3, {}, 'sh000001')
    check("★ apply-if-present：只有 OHLCV 也不报错、不凭空造列（index_daily / 分钟同款）",
          set(_out3b.columns) <= set(DAILY_KEEP_COLUMNS)
          and 'amount' not in _out3b.columns and 'turnover' not in _out3b.columns)

    # 新浪/东财源透传的"受支持列"必须**留下**（"有就用、没有就数据不足"的前提）
    _rich3 = _pd3.DataFrame({'date': ['2024-01-02'], 'open': [1.0], 'high': [1.1],
                             'low': [0.9], 'close': [1.05], 'volume': [100],
                             'amount': [1e7], 'turnover': [0.0093], 'outstanding_share': [1e9]})
    _out3c = AkShareFeed._normalize_ohlcv(_rich3, {}, '600519')
    check("★ 受支持列 amount / turnover / outstanding_share **不被裁掉**（裁掉=换手率筛选静默失效）",
          {'amount', 'turnover', 'outstanding_share', 'symbol'} <= set(_out3c.columns))

    # 分钟路径行为不变：白名单含 symbol，但分钟随后仍按 OHLCV_COLUMNS 裁回 6 列
    check("★ 分钟路径行为不变（`fetch_a_share_minute` 随后仍裁回 6 列，不含 symbol）",
          set(OHLCV_COLUMNS) <= set(DAILY_KEEP_COLUMNS) and 'symbol' not in OHLCV_COLUMNS)
except Exception as _e:  # noqa: BLE001
    check(f"§7-E3 落盘列白名单断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
print("\n== §7-E5 · 下载层新鲜度对齐真交易日历（v1.40）==")
# ==========================================
try:
    from datetime import date as _dc5

    import ui.workers as _uw5
    from data.sync_service import MarketSyncService as _MSS5
    from data.sync_service import ThrottlePolicy as _TP5
    from data.sync_service import estimate_seconds as _est5, format_duration as _fd5
    from data.trade_calendar import latest_settled_trading_day as _lstd5

    # 固定用"远过去"的日期 ⇒ 断言不受脚本运行当天影响（可重复跑，不会隔天变红）
    _D_A = _dc5(2019, 1, 3)
    _D_B = _dc5(2019, 1, 4)
    _ANCIENT = _dc5(2010, 1, 6)

    # ---- ① 判据：注入 expected_latest ⇒ 以「该到哪天」为尺（本项唯一真源）----
    check("★ `_is_fresh` 注入后：last == expected ⇒ 新鲜（周末 / 盘中不再空跑整个池子）",
          _MSS5._is_fresh(_D_A, 0, _D_A) is True)
    check("★ last < expected ⇒ 不新鲜（盘后该补当天，绝不被新判据误跳过）",
          _MSS5._is_fresh(_D_A, 0, _D_B) is False)
    check("last > expected（本地比日历还新）⇒ 仍算新鲜（不拦用户已拉到的更近数据）",
          _MSS5._is_fresh(_D_B, 0, _D_A) is True)
    check("坏输入一律 False（None / 空串 / expected 不可解析 —— 绝不放行）",
          _MSS5._is_fresh(None, 0, _D_A) is False
          and _MSS5._is_fresh("", 0) is False
          and _MSS5._is_fresh(_D_A, 0, "不是日期") is False)
    check("★ `ThrottlePolicy.expected_latest` 默认 None ⇒ 未注入时零行为变化（可安全回滚）",
          _TP5().expected_latest is None)

    # ---- ② 端到端：周末 / 盘中「零请求」—— 这就是要省的 ≈50 分钟 ----
    def _series5(day_str):
        return pd.DataFrame({"date": [pd.Timestamp(day_str)], "open": 10.0, "high": 11.0,
                             "low": 9.0, "close": 10.5, "volume": 100, "symbol": "600519"})

    class _MemLake5:
        """内存湖：只实现门面用到的四个方法（**绝不碰用户真实数据**）。"""

        def __init__(self, seed=None):
            self.store = dict(seed or {})

        def exists(self, zone, key):
            return key in self.store

        def load_data(self, zone, key):
            return self.store.get(key, pd.DataFrame())

        def save_data(self, zone, key, df):
            self.store[key] = df.copy()
            return True

        def get_latest_date(self, zone, key):
            df = self.store.get(key)
            return "" if df is None or df.empty else str(df["date"].max())

    _calls5 = []
    _orig_fetch5 = _MSS5._fetch

    def _fake_fetch5(symbol, zone, start_date, period=None):
        _calls5.append((symbol, start_date))
        return _series5("2019-01-04")

    _MSS5._fetch = staticmethod(_fake_fetch5)
    _no_sleep5 = (lambda _s: None)
    try:
        _svc5 = _MSS5()
        _svc5.lake = _MemLake5({"600519": _series5("2019-01-03")})

        _skip5 = _svc5.refresh_one(
            "600519", policy=_TP5(interval=0, jitter=0, expected_latest=_D_A),
            sleep_fn=_no_sleep5)
        check("★★ 周末 / 盘中：本地末日 == 最近已定稿交易日 ⇒ **跳过且零请求**"
              "（旧判据这时会给全池各发一次注定返空的请求）",
              _skip5.get("skipped") is True and _skip5.get("reason") == "fresh"
              and len(_calls5) == 0)

        _real5 = _svc5.refresh_one(
            "600519", policy=_TP5(interval=0, jitter=0, expected_latest=_D_B),
            sleep_fn=_no_sleep5)
        check("★ 盘后（expected 前进一天）⇒ 必须真拉：跳过判据不许'跳过该拉的'",
              _real5.get("ok") is True and not _real5.get("skipped")
              and len(_calls5) == 1 and _real5.get("added") == 1)

        _svc_old5 = _MSS5()
        _svc_old5.lake = _MemLake5({"600519": _series5("2010-01-06")})
        _legacy5 = _svc_old5.refresh_one("600519", policy=_TP5(interval=0, jitter=0),
                                         sleep_fn=_no_sleep5)
        check("★ 未注入（None）⇒ 旧判据照旧：古老末日仍会发请求"
              "（'可安全回滚'不是空话）",
              not _legacy5.get("skipped") and len(_calls5) == 2)
    finally:
        _MSS5._fetch = staticmethod(_orig_fetch5)

    # ---- ③ 注入件：每批只取一次日历；拿不到就原样返回（离线可用）----
    _cal5 = [_dc5(2019, 1, 2), _dc5(2019, 1, 3), _dc5(2019, 1, 4)]
    _orig_cal5 = _uw5.load_or_fetch
    _cal_calls5 = []

    def _fake_cal5(*a, **k):
        _cal_calls5.append(1)
        return _cal5

    _uw5.load_or_fetch = _fake_cal5
    try:
        _p5 = _uw5.inject_expected_latest(_TP5())
        check("★ 注入件把「最近已收盘定稿的交易日」写进策略"
              "（与 M1/M2/M3 的滞后提示同一把尺子 = 同一真源）",
              _p5.expected_latest == _dc5(2019, 1, 4)
              and _p5.expected_latest == _lstd5(calendar=_cal5))
        check("调用方已显式注入 ⇒ 尊重它、不再取日历（测试可打桩、也避免重复取）",
              _uw5.inject_expected_latest(
                  _TP5(expected_latest=_D_A)).expected_latest == _D_A
              and len(_cal_calls5) == 1)

        _uw5.load_or_fetch = lambda *a, **k: None
        _p_none5 = _TP5()
        check("★ 拿不到日历 ⇒ **原样返回同一对象**（落在旧判据上，离线也能正常下载）",
              _uw5.inject_expected_latest(_p_none5) is _p_none5
              and _p_none5.expected_latest is None)

        class _StubSvc5:
            def refresh_one(self, symbol, **kw):
                return {"ok": True, "symbol": symbol, "skipped": True,
                        "reason": "fresh", "rows": 0, "added": 0}

        _cal_calls5.clear()
        _uw5.load_or_fetch = _fake_cal5
        _orig_ms5 = _uw5.MarketSyncService
        _uw5.MarketSyncService = lambda *a, **k: _StubSvc5()
        try:
            _w5 = _uw5.SyncWorker(["A", "B", "C"], policy=_TP5(interval=0, jitter=0))
            _w5.run()
        finally:
            _uw5.MarketSyncService = _orig_ms5
        check("★ 日历**每批只取一次**（3 只标的 → 1 次；每只都取才是真慢）",
              len(_cal_calls5) == 1)
    finally:
        _uw5.load_or_fetch = _orig_cal5

    # ---- ④ 预估：按「真正会联网的只数」算 + 说人话出口唯一 ----
    _pol5 = _TP5(interval=0.6, jitter=0.0)
    check("★ 预估吃 `stale_count`：已新鲜的跳过不耗时 ⇒ 不再一律报「50 分钟」把用户劝退",
          _est5(1000, _pol5, stale_count=0) == 0
          and _est5(1000, _pol5, stale_count=100) == 60
          and _est5(1000, _pol5) == 600)
    check("★ `format_duration` 单一出口（两个页面同一说法，不许各写一遍）",
          _fd5(45) == "45 秒" and _fd5(600) == "10 分钟"
          and _fd5(5400) == "1.5 小时" and _fd5(0) == "0 秒")
except Exception as _e5:  # noqa: BLE001
    check(f"§7-E5 下载层新鲜度对齐断言整段抛异常: {type(_e5).__name__}: {_e5}", False)

# ==========================================
print("\n== §7-B11 后续 · 后台下载并发池（v1.44）==")
# ==========================================
try:
    import ui.workers as _uw66
    from data.sync_service import ThrottlePolicy as _TP66, DEFAULT_DOWNLOAD_CONCURRENCY
    from ui.workers import RateGovernor as _RG66
    from ui.download_hub import download_policy_from_prefs as _dpf66
    from ui.download_hub import DownloadHub as _DH66

    _orig_ms66 = _uw66.MarketSyncService
    _orig_cal66 = _uw66.load_or_fetch
    _uw66.load_or_fetch = lambda *a, **k: None   # 不联网、不写真实日历缓存

    class _RecSvc66:
        def __init__(self, reason=""):
            self.reason = reason
            self.calls = []
            self.kws = []

        def refresh_one(self, symbol, **kw):
            self.calls.append(symbol)
            self.kws.append(kw)
            if self.reason:
                return {"ok": False, "symbol": symbol, "reason": self.reason,
                        "message": self.reason, "rows": 0, "skipped": False}
            return {"ok": True, "symbol": symbol, "skipped": False, "added": 1}

    def _run66(symbols, policy, reason=""):
        stub = _RecSvc66(reason)
        _uw66.MarketSyncService = lambda *a, **k: stub
        try:
            w = _uw66.SyncWorker(symbols, policy=policy)
            out = []
            w.finished.connect(lambda s: out.append(s))
            w.run()
            return (out[0] if out else {}), stub
        finally:
            _uw66.MarketSyncService = _orig_ms66

    # ---- ① concurrency=1 ⇒ 逐字节串行（既有确定性断言的根 / 回滚开关）----
    check("★ ThrottlePolicy.concurrency 字段默认 1 ⇒ 裸构造即纯串行",
          _TP66().concurrency == 1)
    _st1, _sv1 = _run66(["S1", "S2", "S3", "S4"], _TP66(interval=0, jitter=0))
    check("★ 串行路径保持发起顺序（不建池、按输入序处理）",
          _sv1.calls == ["S1", "S2", "S3", "S4"] and _st1.get("ok") == 4)
    check("★ 串行路径**不注入** sleep_fn（走 time.sleep 原语义 ⇒ 与 v1.43 逐字节等价）",
          all("sleep_fn" not in kw for kw in _sv1.kws))

    # ---- ② 全局节流阀：共享时间线 ⇒ 聚合发起间隔 == interval（请求率不变）----
    _clk = {"t": 0.0}
    _g66 = _RG66(clock=lambda: _clk["t"], sleeper=lambda s: None)
    _starts = [_g66.reserve(0.6) for _ in range(5)]
    _gaps = [round(_starts[i + 1] - _starts[i], 6) for i in range(4)]
    check("★ RateGovernor：并发下相邻请求发起间隔仍 == interval（提速只靠重叠、不加大请求率）",
          _starts[0] == 0.0 and all(abs(gp - 0.6) < 1e-6 for gp in _gaps))
    check("★ RateGovernor：预约时间线单调不减（多线程共用的前提）",
          all(_starts[i] <= _starts[i + 1] for i in range(4)))

    # ---- ③ 并发池路径：注入共享节流阀、全批处理完 ----
    _st3, _sv3 = _run66(["A", "B", "C", "D", "E"],
                        _TP66(interval=0, jitter=0, concurrency=3))
    check("★ concurrency>1 ⇒ 走并发池（每只 refresh_one 都收到注入的 sleep_fn=全局节流阀）",
          len(_sv3.calls) == 5 and all("sleep_fn" in kw for kw in _sv3.kws)
          and _st3.get("ok") == 5)

    # ---- ④ 并发下代理熔断【跨线程共享计数】⇒ 提前收手，不跑满全批 ----
    _st4, _sv4 = _run66([f"P{i:02d}" for i in range(15)],
                        _TP66(interval=0, jitter=0, concurrency=3, proxy_circuit_breaker=3),
                        reason="proxy")
    check("★ 并发池熔断【共享计数】：代理连败达阈即停手并带回 aborted_by=proxy",
          _st4.get("aborted") and _st4.get("aborted_by") == "proxy")
    check("★ 熔断后不跑满全批（共享 stop 生效：处理数 >= 阈值 3 且远小于 15）",
          3 <= _st4.get("fail", 0) < 15)

    # ---- ⑤ download_policy_from_prefs：全局偏好 → 节流策略（唯一真源）----
    import ui.download_hub as _dh66

    class _P66:
        def __init__(self, d):
            self._d = d

        def get(self, key, default=None):
            return self._d

    _pp66 = _dpf66(_P66({"interval": 1.2, "jitter": False, "concurrency": 9,
                        "circuit_breaker": 5, "skip_fresh": False}))
    check("★ download_policy_from_prefs：逐项读全局（interval/熍断/跳过/jitter bool→float）",
          abs(_pp66.interval - 1.2) < 1e-9 and _pp66.jitter == 0.0
          and _pp66.circuit_breaker == 5 and _pp66.skip_fresh is False)
    check("★ concurrency 越界夹进 [1,4]（K≤4：9→4、0→1）",
          _dpf66(_P66({"concurrency": 9})).concurrency == 4
          and _dpf66(_P66({"concurrency": 0})).concurrency == 1)
    check("★ v6.74（B 档）：空/缺键 ⇒ 回落默认（K=2 / interval 0.5，唯一真源 = preferences.DEFAULTS）",
          _dpf66(_P66({})).concurrency == DEFAULT_DOWNLOAD_CONCURRENCY
          and abs(_dpf66(_P66({})).interval - 0.5) < 1e-9)

    # ---- ⑥ submit(policy=None) 读全局 ⇒ “改一处处处生效”端到端闭环 ----
    _hub66 = _DH66()
    _hub66._pump = lambda: None            # 离屏：绝不起真实下载线程（§11.5-20 铁律）
    _orig_pref66 = _dh66.preferences
    _dh66.preferences = _P66({"interval": 2.5, "concurrency": 4})
    try:
        _ja = _hub66.submit("批A", ["600000", "600001"])
        _jb = _hub66.submit("批A重复", ["600000", "600001"])
        _jc = _hub66.submit("批A显式快档", ["600000", "600001"], policy=_TP66(interval=0.1))
        _jA = _hub66.get(_ja).policy
        _jC = _hub66.get(_jc).policy
    finally:
        _dh66.preferences = _orig_pref66
    check("★ submit 无策略 ⇒ 吃全局偏好（改 download_prefs 即处处生效）",
          abs(_jA.interval - 2.5) < 1e-9 and _jA.concurrency == 4)
    check("★ submit 传了策略 ⇒ 完全尊重（不自动改档）",
          abs(_jC.interval - 0.1) < 1e-9 and _jC.concurrency == 1)
    check("★ 同参去重仍成立（连点两下不重复入队）", _ja == _jb)
    _uw66.load_or_fetch = _orig_cal66        # 最后一块：异常时留桩也无害（其后仅剩汇总）
except Exception as _e66:  # noqa: BLE001
    check(f"§7-B11 后续 并发池断言整段抛异常: {type(_e66).__name__}: {_e66}", False)

# ==========================================
print("\n== §7-B11 后续 · 全市场快照秒补（v1.45）==")
# ==========================================
try:
    import datetime as _dt7
    import pandas as _pd7
    import data.akshare_feed as _af7
    from data.akshare_feed import AkShareFeed as _AF7, SPOT_DAILY_KEEP as _SDK7, EM_VOLUME_UNIT as _EMU7
    from data.sync_service import (MarketSyncService as _MSS7, ThrottlePolicy as _TP7,
                                   ZONE_KLINE as _ZK7, ZONE_KLINE_RAW as _ZKR7)

    _today7 = _dt7.date(2026, 9, 22)          # 已定稿的交易日（当天）
    _prev7 = _dt7.date(2026, 9, 21)           # 上一交易日

    # ---- ① fetch_market_spot_daily 单位归一（命门）—— ★v6.69 改走**按标的批量报价** ----
    # 【打桩点为什么挪】旧实现唯一入口 = `ak.stock_zh_a_spot_em()`（东财**全市场**，内部逐页翻
    #   ~56 页）；现在入口 = `data/em_market.ulist_page`（一次一批最多 100 只）⇒ 桩挪到**新的
    #   HTTP 边界**，但断言的是**同一套单位口径**（成交量 手→股、换手率 %→小数）。
    import data.em_market as _em7
    import data.em_throttle as _et7

    _et7.reset()
    _rows7 = [
        {'f12': '600000', 'f14': '浦发银行', 'f2': 10.2, 'f17': 10.0, 'f15': 10.5, 'f16': 9.8,
         'f18': 10.0, 'f5': 12345.0, 'f6': 1.28e8, 'f8': 0.93, 'f9': 4.8, 'f20': 2.9e11,
         'f21': 1.9e10, 'f23': 0.4},
        {'f12': '000001', 'f14': '平安银行', 'f2': 11.2, 'f17': 11.0, 'f15': 11.5, 'f16': 10.8,
         'f18': 11.0, 'f5': 20000.0, 'f6': 2.3e8, 'f8': 1.55, 'f9': 4.3, 'f20': 2.2e11,
         'f21': 2.1e10, 'f23': 0.5},
        {'f12': '600999', 'f14': '停牌股', 'f2': '-', 'f17': '-', 'f15': '-', 'f16': '-',
         'f18': 8.0, 'f5': 0.0, 'f6': 0.0, 'f8': 0.0, 'f9': '-', 'f20': 1.0e10,
         'f21': 1.0e10, 'f23': '-'},
    ]
    _asked7 = []
    _real_ulist7 = _em7.ulist_page
    _real_clist7 = _em7.clist_page
    _em7.ulist_page = lambda codes: (_asked7.append(list(codes)), list(_rows7))[1]
    try:
        _snap7 = _AF7.fetch_market_spot_daily(['600000', '000001', '600999'])
    finally:
        _em7.ulist_page = _real_ulist7
    _r7 = _snap7.set_index('symbol') if not _snap7.empty else _snap7
    check("★ spot 列集合 ⊆ 白名单且不含 date（‘该算哪天’由上层定）",
          not _snap7.empty and set(_snap7.columns) <= set(_SDK7) and 'date' not in _snap7.columns)
    check("★ 换手率单位归一：东财百分数 0.93 → 小数 0.0093（防 §9-V 的 100× 事故）",
          abs(float(_r7.loc['600000', 'turnover']) - 0.0093) < 1e-9)
    check("★ 成交量单位归一：手 ×EM_VOLUME_UNIT(100) → 股",
          abs(float(_r7.loc['600000', 'volume']) - 12345.0 * _EMU7) < 1e-6)
    check("★ 最新价 → close、成交额 → amount、流通市值 → outstanding_share",
          abs(float(_r7.loc['600000', 'close']) - 10.2) < 1e-9
          and abs(float(_r7.loc['600000', 'amount']) - 1.28e8) < 1e-2
          and abs(float(_r7.loc['600000', 'outstanding_share']) - 1.9e10) < 1e-2)
    check("★ 停牌行（最新价缺）被拦下、不进快照（同一道物理护栏）",
          '600999' not in _r7.index)

    # ---- ★v6.69：**按标的批量**（本轮治"额度被自己打光"的那一刀）----
    check("★ v6.69：只问**清单里的标的**（1 个请求覆盖 3 只；旧版是东财内部翻 ~56 页）",
          _asked7 == [['600000', '000001', '600999']])
    check("★ v6.69：无清单 ⇒ **不联网**回空表（本通道不做「全市场一把抓」，上层诚实回退逐只）",
          _AF7.fetch_market_spot_daily().empty and _AF7.fetch_market_spot_valuation().empty)
    check("★ v6.69：`secid` 寻址（沪 1. / 深 0.）—— 批量报价的代码口径",
          _em7.secid('600000') == '1.600000' and _em7.secid('000001') == '0.000001'
          and _em7.secid('300750') == '0.300750')
    _asked7b = []
    _em7.ulist_page = lambda codes: (_asked7b.append(list(codes)), list(_rows7))[1]
    try:
        _q7 = _em7.fetch_quotes([f'{i:06d}' for i in range(1, 251)], sleep_fn=lambda _s: None)
    finally:
        _em7.ulist_page = _real_ulist7
    check("★ v6.69：250 只 ⇒ 按 `QUOTE_BATCH_SIZE=100` **分 3 包**（不是 250 个请求）",
          [len(c) for c in _asked7b] == [100, 100, 50])
    _q7r = _q7.drop_duplicates(subset='symbol', keep='first').set_index('symbol')
    check("★ v6.69：批量报价同时带出**估值列**（pe/pb/总市值）—— 估值与秒补共用一条通道",
          abs(float(_q7r.loc['600000', 'pe']) - 4.8) < 1e-9
          and abs(float(_q7r.loc['600000', 'pb']) - 0.4) < 1e-9
          and abs(float(_q7r.loc['600000', 'total_mktcap']) - 2.9e11) < 1.0)
    _asked7c = []
    _em7.ulist_page = lambda codes: (_asked7c.append(list(codes)), list(_rows7))[1]
    try:
        _em7.fetch_quotes(['600000'] * 5, sleep_fn=lambda _s: None)
    finally:
        _em7.ulist_page = _real_ulist7
    check("★ v6.69：清单里的重复代码只发 1 次（去重保序）", _asked7c == [['600000']])

    # ---- ★v6.69：失败 ⇒ **退避冷却**（不再"越点越死"）；冷却期内一条请求都不打 ----
    _et7.reset()
    _em7.ulist_page = lambda codes: (_ for _ in ()).throw(RuntimeError('模拟风控'))
    try:
        _q7b = _em7.fetch_quotes(['600000'], sleep_fn=lambda _s: None)
    finally:
        _em7.ulist_page = _real_ulist7
    _left7 = _et7.cooldown_left()
    check("★ v6.69：取数失败 ⇒ 记一笔退避（首败冷却 10 分钟）+ 交回空表（**不上抛**）",
          _q7b.empty and 9 * 60 < _left7 <= 10 * 60 and '冷却' in _et7.describe())
    _asked7d = []
    _em7.clist_page = lambda page, pz=100: (_asked7d.append(page), ([], 0))[1]
    try:
        _r68c = _em7.fetch_industry_page(1, 3, sleep_fn=lambda _s: None)
    finally:
        _em7.clist_page = _real_clist7
    check("★ v6.74：**ulist 冷却不再连坐 clist**（旧版「一份全局冷却」⇒ 行业与估值互相拖死）",
          _asked7d == [1] and '冷却' not in (_r68c.get('error') or ''))
    _et7.note_failure('clist', 'sim')                 # ★v6.74：按通道记，clist 自己进冷却
    _asked7d.clear()
    _em7.clist_page = lambda page, pz=100: (_asked7d.append(page), ([], 0))[1]
    try:
        _r68d = _em7.fetch_industry_page(1, 3, sleep_fn=lambda _s: None)
    finally:
        _em7.clist_page = _real_clist7
    check("★ v6.69：clist 冷却期内**连第 1 页都不打**（旧版每次扫描都重打第一页 ⇒ 越点越死）",
          _asked7d == [] and _r68d['map'] == {} and _r68d['pages_done'] == 0
          and '冷却' in _r68d['error'])
    _et7.note_success()
    _et7.note_success()
    check("★ v6.69+v6.72：恢复后**连续两次**成功才清零（v6.72 起单次成功不再清零 ⇒ 见下节抗抖动）",
          _et7.cooldown_left() == 0 and _et7.is_cooling() is False)
    _et7.reset()          # ⚠ 清掉冷却：下一段（should_stop）要真能发出请求才验得到

    # ---- ★v6.69：`should_stop` ⇒ **页与页之间**收手（关窗取消不必等整批跑完）----
    _stop_pages7 = []
    _em7.clist_page = lambda page, pz=100: (
        _stop_pages7.append(page), ([{'f12': '600000', 'f14': 'x', 'f100': '银行'}], 5000))[1]
    try:
        _r7s = _em7.fetch_industry_page(1, 8, sleep_fn=lambda _s: None,
                                       should_stop=lambda: len(_stop_pages7) >= 2)
    finally:
        _em7.clist_page = _real_clist7
    check("★ v6.69：`should_stop` 在页与页之间生效（取消后最多多等一个页间隔）",
          _stop_pages7 == [1, 2] and _r7s['pages_done'] == 2)
    _et7.reset()          # ⚠ 收尾：绝不给用户的应用留一个"冷却中"（否则下次扫描会拒抓）

    # ---- ② refresh_one 的 spot 快路径（只补当天 / 不造假 / 幂等 / 分区限定）----
    class _MemLake7:
        def __init__(self):
            self.store = {}

        def exists(self, zone, key):
            return key in self.store

        def load_data(self, zone, key):
            return self.store.get(key, _pd7.DataFrame())

        def save_data(self, zone, key, df):
            self.store[key] = df.copy()
            return True

    _fetch_calls7 = []

    def _fake_fetch7(symbol, zone, start_date, period=None):
        _fetch_calls7.append(symbol)
        return _pd7.DataFrame()

    _real_fetch7 = _MSS7._fetch
    _MSS7._fetch = staticmethod(_fake_fetch7)

    def _seed(sym, up_to):
        svc = _MSS7()
        svc.lake = _MemLake7()
        svc.lake.store[sym] = _pd7.DataFrame({
            'date': _pd7.to_datetime([_dt7.date(2026, 9, 18), _dt7.date(2026, 9, 19), up_to]),
            'open': [9.0, 9.5, 10.0], 'high': [9.2, 9.7, 10.5],
            'low': [8.8, 9.3, 9.8], 'close': [9.1, 9.6, 10.2],
            'volume': [1000.0, 1100.0, 1234500.0], 'symbol': sym})
        return svc

    _bar7 = {'open': 10.0, 'high': 10.5, 'low': 9.8, 'close': 10.2,
             'volume': 1234500.0, 'amount': 1.28e8, 'turnover': 0.0093,
             'outstanding_share': 1.9e10,
             # ★v6.67：**昨收** = 除权闸门的判据（与本地最后一根收盘一致 ⇒ 今天没除权）
             'prev_close': 10.2}
    _no_sleep7 = (lambda _s: None)
    try:
        # (a) 本地末日 == 上一交易日 ⇒ 秒补当天，不发网络
        _sv = _seed('600000', _prev7)
        _pol7 = _TP7(interval=0, jitter=0, expected_latest=_today7)
        _res7 = _sv.refresh_one('600000', zone=_ZK7, policy=_pol7,
                                sleep_fn=_no_sleep7, spot_bar=_bar7, spot_prev=_prev7)
        _saved7 = _sv.lake.store['600000']
        check("★ 只缺当天 → reason=spot、不发逐只请求（fetch 未被调用）",
              _res7.get('ok') and _res7.get('reason') == 'spot' and not _fetch_calls7)
        check("★ 秒补后本地末日 == 当天，且历史逐根不动（行数 +1、旧 close 不变）",
              str(_pd7.to_datetime(_saved7['date']).max().date()) == str(_today7)
              and len(_saved7) == 4 and abs(float(_saved7['close'].iloc[0]) - 9.1) < 1e-9)
        check("★ 追加行用 spot 真实价、与 qfq 当天自洽（close==spot close、不重标历史）",
              abs(float(_saved7['close'].iloc[-1]) - 10.2) < 1e-9)
        # (b) 幂等：再跑一次 → 已新鲜（末日>=当天）⇒ 跳过不重复加行
        _res7b = _sv.refresh_one('600000', zone=_ZK7, policy=_TP7(interval=0, jitter=0,
                                                                  expected_latest=_today7),
                                 sleep_fn=_no_sleep7, spot_bar=_bar7, spot_prev=_prev7)
        check("★ 重复跑幂等：第二天已新鲜→skip，行数不变",
              _res7b.get('skipped') and len(_sv.lake.store['600000']) == 4)
        # (c) 多日缺口（末日早于上一交易日）⇒ spot 不造假，退回网络
        _sv2 = _seed('600001', _dt7.date(2026, 9, 18))
        _fetch_calls7.clear()
        _res2 = _sv2.refresh_one('600001', zone=_ZK7, policy=_TP7(interval=0, jitter=0,
                                                                  expected_latest=_today7),
                                 sleep_fn=_no_sleep7, spot_bar=_bar7, spot_prev=_prev7)
        check("★ 缺口 > 1 交易日 → spot 绝不造假（会留洞），退回逐只真拉",
              '600001' in _fetch_calls7 and _res2.get('reason') != 'spot')
        # (d) 非 qfq 日线分区（不复权 raw）⇒ 不走 spot
        _sv3 = _seed('600002', _prev7)
        _fetch_calls7.clear()
        _sv3.refresh_one('600002', zone=_ZKR7, policy=_TP7(interval=0, jitter=0,
                                                           expected_latest=_today7),
                         sleep_fn=_no_sleep7, spot_bar=_bar7, spot_prev=_prev7)
        check("★ 不复权/分钟/指数分区永不走 spot（只有 qfq 日线分区可）",
              '600002' in _fetch_calls7)

        # ---- ★v6.67：**除权/除息闸门**（用户实测："当天转赠/分红的股票，更新到最新后拿到的
        #   都是不复权"）—— spot 是"命中即 return"的旁路 ⇒ 它会**绕过**主路径的复权因子漂移
        #   检测；而除权当天恰好是最容易命中 spot 的形态（本地末日 == 上一交易日）⇒
        #   只追加当天那根、历史仍按旧因子缩放 = 用户看到的现象。判据 = 快照昨收 vs 本地末根收盘。
        _old7 = _sv.lake.store['600000'].iloc[:-1]        # 本地"除权前"的历史（末日=上一交易日）
        check("★ 昨收判据：与本地末根收盘一致 ⇒ 今天没除权（放行秒补）",
              _MSS7._spot_prev_close_ok(_old7, _bar7) is True)
        _drift_bar7 = dict(_bar7, prev_close=7.0)         # 除权参考价 ⇒ 昨收被调整过
        check("★ 昨收判据：差 31%（10.2 → 7.0）⇒ 判定**今天除权/除息**（秒补必须让路）",
              _MSS7._spot_prev_close_ok(_old7, _drift_bar7) is False)
        _noprev_bar7 = {k: v for k, v in _bar7.items() if k != 'prev_close'}
        check("★ 昨收判据缺失（快照没带昨收）⇒ **拒绝秒补**（没有判据就别抄近路）",
              _MSS7._spot_prev_close_ok(_old7, _noprev_bar7) is False
              and _MSS7._spot_prev_close_ok(_old7, {}) is False)
        # 端到端：除权日命中 spot 形态，但必须**退回网络增量**（由漂移判据去整段重算）
        _sv4 = _seed('600003', _prev7)
        _fetch_calls7.clear()
        _res4 = _sv4.refresh_one('600003', zone=_ZK7, policy=_TP7(interval=0, jitter=0,
                                                                  expected_latest=_today7),
                                 sleep_fn=_no_sleep7, spot_bar=_drift_bar7, spot_prev=_prev7)
        check("★★ v6.67：除权日**不走 spot 秒补**（否则历史不重算 = 用户看到的\"不复权\"）",
              '600003' in _fetch_calls7 and _res4.get('reason') != 'spot')
        check("★ v6.67：判据列只当闸门、**永不落盘**（`prev_close` 进 SPOT_DAILY_KEEP，不进湖白名单）",
              'prev_close' in _SDK7 and 'prev_close' not in _af7.DAILY_KEEP_COLUMNS)
    finally:
        _MSS7._fetch = _real_fetch7
except Exception as _e7:  # noqa: BLE001
    check(f"§7-B11 后续 快照秒补断言整段抛异常: {type(_e7).__name__}: {_e7}", False)

# ==========================================
print("\n== ★v6.72 · 网络策略：IPv4 优先 / 代理降级直连 / 失败分类 / 退避抗抖动 ==")
#   用户实测（2026-09-26 22:13）：`ProxyError('Unable to connect to proxy')`。逐层实测是两件事叠加：
#     ① DNS 把 IPv6 排前面而东财 IPv6 端点不通（同刻 `curl -4`=200 / `curl -6`=000）
#        ⇒ `requests` 没有可靠的 Happy-Eyeballs 回退 ⇒ **额度充足也白撞**；
#     ② 系统代理（clash-verge 写 WinINET `ProxyEnable=1 / 127.0.0.1:7897`）在中间，
#        而 `netsh winhttp show proxy` **看不到它**（v6.68 那轮判据选错工具，坑 = §11.5-103）。
# ==========================================
try:
    import socket as _sock72  # noqa: E402
    import urllib3.util.connection as _u3c72  # noqa: E402

    from core.preferences import preferences as _pref72  # noqa: E402
    from data import em_market as _em72  # noqa: E402
    from data import em_throttle as _et72  # noqa: E402
    from data import net_env as _ne72  # noqa: E402
    from data.sync_service import looks_like_proxy_error as _lpe72  # noqa: E402

    _net_back72 = _pref72.get('net')
    _gai_back72 = _u3c72.allowed_gai_family
    try:
        # ---- ① 地址族：默认限定 IPv4，且**可回退**（不是单向焊死）----
        _pref72.set('net', {'force_ipv4': True, 'proxy_mode': 'auto'})
        _ne72.apply()
        check("★ v6.72：默认把地址族限定为 **IPv4**（DNS 优先 IPv6 而东财 IPv6 不通 ⇒ 否则白撞）",
              _u3c72.allowed_gai_family() == _sock72.AF_INET)
        _pref72.set('net', {'force_ipv4': False})
        _ne72.apply()
        check("★ v6.72：关掉开关即**还原系统默认**地址族（可回退）",
              _u3c72.allowed_gai_family() == _gai_back72()          # ⚠ 比**返回值**，别比函数对象
              and _u3c72.allowed_gai_family() != _sock72.AF_INET)
        _pref72.set('net', {'force_ipv4': True, 'proxy_mode': 'direct'})
        check("★ v6.72：`describe()` 说人话且随策略变（页面 tooltip 直接拼它）",
              'IPv4 优先' in _ne72.describe() and '直连' in _ne72.describe())
        check("★ v6.72：代理指纹只有**一份实现**（`net_env` 定义 + `sync_service` 再导出）",
              _lpe72 is _ne72.looks_like_proxy_error
              and _ne72.looks_like_proxy_error("ProxyError: Unable to connect to proxy")
              and not _ne72.looks_like_proxy_error("RemoteDisconnected('Remote end closed')"))

        # ---- ② 代理报错 ⇒ 降级直连重试一次；直连再失败 ⇒ 仍按"代理"报（不是限流）----
        _pref72.set('net', {'force_ipv4': True, 'proxy_mode': 'auto'})
        _et72.reset()
        _em72._STATE.update({'direct_locked': False, 'proxy_err': ''})
        _real_get72 = _em72._do_get
        _calls72 = []

        def _fake_get72(url, params, use_proxy):
            _calls72.append(use_proxy)
            if use_proxy:
                raise RuntimeError("ProxyError: Unable to connect to proxy")
            return {'data': {'diff': [{'f12': '600000', 'f14': 'X', 'f100': '银行'}], 'total': 1}}

        _em72._do_get = _fake_get72
        try:
            _rows72 = _em72.ulist_page(['600000'])
        finally:
            _em72._do_get = _real_get72
        check("★ v6.72：代理报错 ⇒ **降级直连重试一次**并成功 + 记住本轮用直连",
              _calls72 == [True, False] and len(_rows72) == 1 and _em72.direct_locked())

        _calls72b = []
        _em72._STATE['direct_locked'] = False

        def _fake_get72b(url, params, use_proxy):
            _calls72b.append(use_proxy)
            raise RuntimeError("ProxyError: Unable to connect to proxy")

        _em72._do_get = _fake_get72b
        try:
            try:
                _em72.ulist_page(['600000'])
                _err72 = None
            except Exception as e:               # noqa: BLE001
                _err72 = e
        finally:
            _em72._do_get = _real_get72
        check("★ v6.72：直连也失败 ⇒ 抛出的仍是**代理类**错误（上层才按代理安抚，不误导成限流）",
              _err72 is not None and _ne72.looks_like_proxy_error(_err72)
              and _calls72b == [True, False])

        _et72.reset()
        _real_clist72 = _em72.clist_page
        _em72.clist_page = lambda page, pz=100: (_ for _ in ()).throw(
            RuntimeError("ProxyError: Unable to connect to proxy"))
        try:
            _r72 = _em72.fetch_industry_page(1, 1, sleep_fn=lambda _s: None)
        finally:
            _em72.clist_page = _real_clist72
        check("★ v6.72：代理类失败 ⇒ 回执说「查代理（重试无用）」，**不是**「限流冷却」",
              '代理' in _r72['error'] and '限流' not in _r72['error']
              and (_et72.channels().get('clist') or {}).get('fail_class') == 'proxy')
        check("★ v6.72：代理类冷却**固定 5 分钟**（不是限流的 10→20→40 指数退避）",
              abs(_et72.cooldown_left() - 300) < 5)

        # ---- ③ 退避抗抖动：实测 4ms 内「冷却 → 清零 → 再冷却」⇒ 单次成功不许清零 ----
        _et72.reset()
        _et72.note_failure('test', 'boom')
        _et72.note_success()
        check("★ v6.72：失败后**一次**成功不清零（连击 1/2 ⇒ 冷却仍在）",
              _et72.is_cooling() and int((_et72.channels().get('test') or {}).get('streak') or 0) == 1)
        _et72.note_success()
        check("★ v6.72：**连续两次**成功才清零（失败会把连击打回 0）",
              not _et72.is_cooling() and _et72.cooldown_left() == 0)
        _et72.reset()
    finally:
        _u3c72.allowed_gai_family = _gai_back72   # 收场：不给后面的断言留 IPv4-only
        _pref72.set('net', _net_back72 or {'force_ipv4': True, 'proxy_mode': 'auto'})
        _ne72.apply()
        _et72.reset()
except Exception as _e72:  # noqa: BLE001
    check(f"v6.72 网络策略断言整段抛异常: {type(_e72).__name__}: {_e72}", False)

# ==========================================
print("\n== §7-B11 后续 · 统一下载设置入口（v1.45）==")
# ==========================================
try:
    from data.sync_service import DEFAULT_DOWNLOAD_CONCURRENCY as _DDC8

    def _src8(*parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            return f.read()

    from core.preferences import DEFAULTS as _DEF8

    _dp = _DEF8.get("download_prefs")
    check("★ 全局下载偏好 download_prefs 存在且五项齐全（唯一真源的默认）",
          isinstance(_dp, dict) and {"interval", "jitter", "circuit_breaker",
                                     "skip_fresh", "concurrency"} <= set(_dp))
    check("★ v6.74（B 档）：默认并发 2 / interval 0.5（与实际生效一致；用户实测 0.3×K3≈10/秒 才激进）",
          _dp.get("concurrency") == _DDC8 == 2 and abs(float(_dp.get("interval")) - 0.5) < 1e-9)

    _bulk8 = _src8("ui", "dialogs", "bulk_download.py")
    _dm8 = _src8("ui", "views", "data_manager.py")
    _set8 = _src8("ui", "dialogs", "download_settings.py")
    _qp8 = _src8("ui", "widgets", "download_queue_panel.py")
    check("★ 预下载弹窗已去掉私有旋钮：不再构造 ThrottlePolicy / 不再有 spin_interval",
          "ThrottlePolicy(" not in _bulk8 and "spin_interval" not in _bulk8)
    check("★ 数据管理页已去掉独立间隔旋钮（防两套值漂移）",
          "spin_interval" not in _dm8 and "ThrottlePolicy(" not in _dm8)
    check("★ 三处入口打开同一个 DownloadSettingsDialog（不各存一份编辑面）",
          all("DownloadSettingsDialog" in t for t in (_bulk8, _dm8, _qp8)))
    check("★ 设置对话框写盘键形正确（preferences.set('download_prefs', {5 项})）",
          'preferences.set("download_prefs"' in _set8
          and all(f'"{k}"' in _set8 for k in
                  ("interval", "jitter", "circuit_breaker", "skip_fresh", "concurrency")))
except Exception as _e8:  # noqa: BLE001
    check(f"§7-B11 后续 统一下载设置入口断言整段抛异常: {type(_e8).__name__}: {_e8}", False)

# ==========================================
print("\n== 复权自愈（v1.46/§7-B10 后续）：除权后**前复权历史必须整段重算**（不留假跳空）==")
# 【为什么单独立段】用户 2026-09-25 实测：指南针 300803 的「前复权」分区里
#   9/18=82.00（旧口径）× 9/21=56.86（新口径）⇒ 图上出现**假跳空**；而源端 qfq 其实连续
#   （56.55 → 56.86）。根因 = 增量只从「本地末日 + 1」拉 ⇒ 除权后**历史永远不重算**，
#   库里留下"旧行旧口径 / 新行新口径"的混合序列（而且两份口径看起来一模一样）。
#   本段钉住三件事：① 重叠窗口真的存在；② 漂移判据只认"重叠日对不上"；③ 命中即整段重拉。
# ==========================================
try:
    import pandas as _pdR  # noqa: E402
    from data.sync_service import (DEFAULT_MIN_DATE, QFQ_OVERLAP_DAYS,  # noqa: E402
                                   ZONE_KLINE, MarketSyncService, ThrottlePolicy)

    _oldR = _pdR.DataFrame({"date": ["2026-09-17", "2026-09-18"],
                            "close": [79.06, 82.00]})
    _sameR = _pdR.DataFrame({"date": ["2026-09-18", "2026-09-21"],
                             "close": [82.00, 82.45]})
    _driftR = _pdR.DataFrame({"date": ["2026-09-18", "2026-09-21"],
                              "close": [56.55, 56.86]})          # 除权后的新口径

    check("★ 漂移判据：重叠日**价格一致** ⇒ 判「没有漂移」（不误触发整段重拉）",
          MarketSyncService._qfq_factor_drifted(_oldR, _sameR) is False)
    check("★ 漂移判据：重叠日差 31%（82.00 → 56.55）⇒ 判**漂移**（除权/除息）",
          MarketSyncService._qfq_factor_drifted(_oldR, _driftR) is True)
    check("★ 漂移判据：没有重叠日期 ⇒ 无从判断，返回 False（走普通合并，不乱重拉）",
          MarketSyncService._qfq_factor_drifted(
              _oldR, _pdR.DataFrame({"date": ["2026-09-24"], "close": [56.50]})) is False)
    check("★ 重叠窗口是真实常量且足够宽（旧版从「末日 + 1」拉 = 零重叠）",
          isinstance(QFQ_OVERLAP_DAYS, int) and int(QFQ_OVERLAP_DAYS) >= 5)

    class _LakeR:
        """假湖：只回放"本地旧数据"，记录落盘的那一份。"""

        def __init__(self, df):
            self._df = df
            self.saved = None

        def load_data(self, zone, key):
            return self._df.copy()

        def save_data(self, zone, key, df):
            self.saved = df.copy()
            return True

        def exists(self, zone, key):
            return True

    _svcR = MarketSyncService.__new__(MarketSyncService)   # 不连数据库：只跑 refresh_one 的编排
    _svcR.lake = _LakeR(_oldR)
    _callsR = []

    def _fake_fetch(symbol, zone, start_date, period=None):
        _callsR.append(start_date)
        # 第一次＝增量（返回**新口径**的重叠段）；第二次＝整段全量（返回完整历史）
        if len(_callsR) == 1:
            return _driftR.copy()
        return _pdR.DataFrame({"date": ["2010-01-04", "2026-09-18", "2026-09-21"],
                               "close": [12.30, 56.55, 56.86]})

    _svcR._fetch = _fake_fetch
    _resR = _svcR.refresh_one(
        "300803", zone=ZONE_KLINE, sleep_fn=lambda s: None,
        policy=ThrottlePolicy(interval=0.0, jitter=False, skip_fresh=False))
    check("★ 增量起点 = 本地末日 **减去重叠窗口**（本地 9/18 ⇒ 从 9/08 起拉）",
          _callsR and _callsR[0] == "20260908")
    check("★ 检测到除权 ⇒ 第二次取数用**全量起点**（整段重算，只多一次请求）",
          len(_callsR) == 2 and _callsR[1] == DEFAULT_MIN_DATE)
    check("★ 结果标明 rescaled（UI 才能说清「这次不是普通增量」）",
          _resR.get("rescaled") is True and _resR.get("ok") is True)
    check("★ 落盘的是**整段新口径**（旧行 82.00 已被 56.55 覆盖，不再是混合序列）",
          _svcR.lake.saved is not None
          and float(_svcR.lake.saved["close"].iloc[1]) == 56.55
          and len(_svcR.lake.saved) == 3)

    # 反面：**没有漂移**时绝不能整段重拉（否则每次增量都变成全量，白烧流量）
    _svcR2 = MarketSyncService.__new__(MarketSyncService)
    _svcR2.lake = _LakeR(_oldR)
    _callsR2 = []

    def _fake_fetch2(symbol, zone, start_date, period=None):
        _callsR2.append(start_date)
        return _sameR.copy()

    _svcR2._fetch = _fake_fetch2
    _resR2 = _svcR2.refresh_one(
        "300803", zone=ZONE_KLINE, sleep_fn=lambda s: None,
        policy=ThrottlePolicy(interval=0.0, jitter=False, skip_fresh=False))
    check("★ 没有漂移 ⇒ 只拉一次（不把普通增量升级成全量）",
          len(_callsR2) == 1 and _resR2.get("rescaled") is False)
except Exception as _eR:  # noqa: BLE001
    check(f"复权自愈断言整段抛异常: {type(_eR).__name__}: {_eR}", False)

print(f"\n===== 通过 {len(OK)} · 失败 {len(BAD)} =====")
for b in BAD:
    print("  FAIL:", b)

# 【§11.5-20 铁律③】强制退出：残留的非守护 QThread 会让解释器不退出，
# 而管道分页（tail / Select-Object -Last N）会缓冲到进程结束才显示 ⇒ 表现为"卡死无输出"。
sys.stdout.flush()
os._exit(1 if BAD else 0)
