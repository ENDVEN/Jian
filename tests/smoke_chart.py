# tests/smoke_chart.py —— 图表架构冒烟断言（P0 / P1 / P2），验证后可直接复跑
#   用法：py tests/smoke_chart.py  （在仓库根目录执行）
import os
import sys

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

    expect_error("未知标注类型报错", lambda: make_annotation("s", "arrow", [[1, 2]]), "不支持")
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
    check("周期中文标签与顺序", period_label("W") == "周线" and PERIOD_ORDER == ("D", "W", "M"))

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

    # ---- 斐波那契 / 文字：绘制 + **附属图元随主图元一起删**（§11.5-15 同类风险）----
    from data.annotations import KIND_FIB, KIND_TEXT, KIND_TREND
    from ui.widgets.annotation_layer import AnnotationLayer
    from ui.widgets.chart_host import ChartHost

    host = ChartHost(bottom_axis_mode='no_values', crosshair=True)
    host.resize(640, 420)
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

    layer.set_tool(KIND_TREND)
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
        def button(self):
            return pg.QtCore.Qt.MouseButton.LeftButton

        def accept(self):
            pass

    class _DragEvent:
        def __init__(self, scene_pos, down_pos, finish=False):
            self._scene, self._down, self._finish = scene_pos, down_pos, finish
            self.accepted = False

        def button(self):
            return pg.QtCore.Qt.MouseButton.LeftButton

        def scenePos(self):
            return self._scene

        def buttonDownScenePos(self):
            return self._down

        def isFinish(self):
            return self._finish

        def accept(self):
            self.accepted = True

    moved = []
    text_graphic = _ClickableText("压力位", on_moved=lambda: moved.append(1))
    text_graphic.setPos(10.0, 100.0)
    text_graphic.mousePressEvent(_PressEvent())
    text_graphic.mouseDragEvent(_DragEvent(QPointF(13.0, 105.0), QPointF(10.0, 100.0)))
    check("拖动中：文字跟随鼠标位移（不是只记录不移动）",
          text_graphic.pos().x() == 13.0 and text_graphic.pos().y() == 105.0)
    check("拖动过程中不回调（避免拖动途中疯狂写盘）", moved == [])
    text_graphic.mouseDragEvent(_DragEvent(QPointF(13.0, 105.0), QPointF(10.0, 100.0),
                                           finish=True))
    check("松手才回调一次（触发落盘）", moved == [1])

    # ---- 4) 拖完存到哪：x 映射回日期、y 存真实价（回读一致）----
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
    drag_layer._items[drag_item["id"]].setPos(25.5, 88.8)     # 模拟用户拖到这里
    drag_layer._persist_from_view(drag_item["id"])
    stored = drag_store.get('sh600000', 'daily', drag_item["id"])
    check("文字拖到哪就存哪（x 按日期存、y 按真实价存）",
          stored["points"][0][1] == 88.8
          and stored["points"][0][0] == drag_layer._axis.index_to_date(25.5))
    reopened = AnnotationStore(str(tmp_drag / "annotations.json"))
    reloaded = reopened.get('sh600000', 'daily', drag_item["id"])
    check("重启后文字与位置都在（文字内容丢失会被模型层直接拒收，能读回=没丢）",
          reloaded is not None and reloaded["text"] == "箱体上沿"
          and reloaded["points"][0][1] == 88.8)
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

print(f"\n===== 通过 {len(OK)} · 失败 {len(BAD)} =====")
for b in BAD:
    print("  FAIL:", b)

# 【§11.5-20 铁律③】强制退出：残留的非守护 QThread 会让解释器不退出，
# 而管道分页（tail / Select-Object -Last N）会缓冲到进程结束才显示 ⇒ 表现为"卡死无输出"。
sys.stdout.flush()
os._exit(1 if BAD else 0)
