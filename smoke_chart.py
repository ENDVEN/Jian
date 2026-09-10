# smoke_chart.py —— 图表架构冒烟断言（P0 / P1 / P2），验证后可直接复跑
#   用法：py smoke_chart.py
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.formula import draw
from core.formula.program import (
    parse_program, execute_programs, execute_programs_with_draws,
    missing_parameter_names, FormulaProgramError,
)

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

print(f"\n===== 通过 {len(OK)} · 失败 {len(BAD)} =====")
for b in BAD:
    print("  FAIL:", b)
sys.exit(1 if BAD else 0)
