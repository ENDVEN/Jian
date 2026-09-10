# -*- coding: utf-8 -*-
"""「回测页 + 行情页」公式叠层的**页面级**验收（P3 / P4），可重复运行。

用法：py smoke_pages_overlay.py
⚠ 会真实构造主窗口（打开 ~/.jian_data），请勿在 app 运行中同时跑。
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication

from core.formula.program import parse_program, execute_programs_with_draws
from ui.main_window import JianMainWindow
from ui.views.market import SUB_PLOT_HEIGHT

OK, BAD = [], []


def check(desc, cond):
    (OK if cond else BAD).append(desc)
    print(("  [OK] " if cond else "  [!!] ") + desc)


app = QApplication.instance() or QApplication([])
win = JianMainWindow()
view = win.page_backtest.single_view

# ---- 合成一段行情 ----
n = 200
dates = pd.bdate_range('2024-01-01', periods=n)
close = 100 + 8 * np.sin(np.arange(n) * 0.2) + np.arange(n) * 0.05
df = pd.DataFrame({
    'date': dates, 'open': close - 0.2, 'high': close + 1.0,
    'low': close - 1.0, 'close': close, 'volume': 10000 + np.arange(n) * 10,
})

SRC = """
DIFF := EMA(C,5) - EMA(C,20);
MOM: DIFF, COLORWHITE, LINETHICK2;
HIDDEN: DIFF, NODRAW;
STICKLINE(DIFF > 0, 0, DIFF, 3, 0);
DRAWICON(DIFF > 0, H, 1);
"""
prog = parse_program(SRC)
variables, draws = execute_programs_with_draws([prog], df, {})

view.current_name = '测试股'
view.current_symbol = 'sh600000'
view._programs = [prog]
view._last_df = df
view._last_draws = draws
view.chk_overlay.setChecked(True)


class _Trade:
    def __init__(self, e, x):
        self.entry_date, self.exit_date = e, x


class _Result:
    def __init__(self, trades):
        self.trades = trades


result = _Result([_Trade(dates[50], dates[150])])
view._render_kline(result)

# ---- 断言 ----
print("== 叠层已渲染 ==")
check("叠层图元非空（公式线+状态柱+图标）", len(view._overlay_items) == 3)
check("叠层类型顺序 = PlotDataItem/_StickItem/ScatterPlotItem",
      (isinstance(view._overlay_items[0], pg.PlotDataItem)
       and view._overlay_items[1].__class__.__name__ == '_StickItem'
       and isinstance(view._overlay_items[2], pg.ScatterPlotItem)))
check("K线页签图元总数 = K线 + 3 叠层 + 买卖点",
      len(view.kline_chart.getPlotItem().items) >= 5)

print("== 对齐（核心：不得漂移）==")
win_len = len(view._kline_state['dates'])
check("窗口切片长度一致",
      all(len(d.y) == win_len if d.kind == 'line' else len(d.cond) == win_len
          for d in view._kline_win_draws))
check("窗口长度 < 全量长度（确实切过窗）", 0 < win_len < n)

x_data = view._overlay_items[0].getData()[0]
check("叠层 x = 0..n-1（与 K 线同一坐标系）", np.allclose(x_data, np.arange(win_len)))

win_dates = pd.to_datetime(view._kline_state['dates'])
expected_y = df.loc[df['date'].isin(win_dates), 'close'].to_numpy()
# MOM = DIFF（EMA5-EMA20），用它自己的公式重算一遍对账，避免"看起来对"
close_s = pd.Series(close.tolist())
diff_full = (close_s.ewm(span=5, adjust=False).mean()
             - close_s.ewm(span=20, adjust=False).mean()).to_numpy()
expect_mom = diff_full[np.isin(df['date'].to_numpy(), win_dates.to_numpy())]
check("公式线数值与逐 bar 重算完全一致（无一格错位）",
      np.allclose(view._kline_win_draws[0].y, expect_mom, equal_nan=True))
check("状态柱 cond 与窗内 DIFF>0 一致",
      np.array_equal(view._kline_win_draws[1].cond, expect_mom > 0))
check("HIDDEN(NODRAW) 只在变量池、不进图元",
      all(d.name != 'HIDDEN' for d in view._kline_win_draws))

print("== y 自适应 ==")
ov_lo = view._kline_state['overlay_lo']
ov_hi = view._kline_state['overlay_hi']
check("叠层范围已并入 _kline_state", ov_lo is not None and len(ov_lo) == win_len)
y0, y1 = view.kline_chart.getViewBox().viewRange()[1]
check("视口 y 覆盖叠层最低值", y0 <= float(np.nanmin(ov_lo)) + 1e-9)
check("视口 y 覆盖叠层最高值", y1 >= float(np.nanmax(ov_hi)) - 1e-9)

print("== 开关 ==")
view.chk_overlay.setChecked(False)
check("关掉后图元全部隐藏", all(not it.isVisible() for it in view._overlay_items))
check("关掉后 y 范围不再含叠层", view._kline_state['overlay_lo'] is None)
view.chk_overlay.setChecked(True)
check("再打开后恢复可见", all(it.isVisible() for it in view._overlay_items))
check("再打开后 y 范围重新含叠层", view._kline_state['overlay_lo'] is not None)

print("== 无绘图语句的旧函数不受影响 ==")
plain = parse_program("MA5: MA(C,5), COLORRED;")
_, plain_draws = execute_programs_with_draws([plain], df, {})
view._last_draws = plain_draws
view._render_kline(result)
check("只有一条公式线", len(view._overlay_items) == 1)
check("线色 = 红（未被对比度守卫改动）",
      view._overlay_items[0].opts['pen'].color().name().upper() == '#FF0000')

print("== 离屏截图验收（§7-B3 5) 要求）==")
from PyQt6.QtCore import QBuffer, QIODevice


def png_bytes(widget):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    widget.grab().save(buf, 'PNG')
    return bytes(buf.data())


view.kline_chart.resize(900, 480)
view._last_draws = draws
view.chk_overlay.setChecked(True)
view._render_kline(result)
img_with = png_bytes(view.kline_chart)
view.chk_overlay.setChecked(False)
view._render_kline(result)
img_without = png_bytes(view.kline_chart)
check("grab PNG 非空", len(img_with) > 3000 and len(img_without) > 3000)
check("开关叠层确实改变了像素（证明真画上去了）", img_with != img_without)

print("== 检测期：绘图语句尾部颜色 + 未渲染语句的非阻断提示（§9-Q 回归防护）==")
# 这一条是真实回归的固化：`STICKLINE(...), COLORFF0000;` 曾让存量函数直接跑不起来
view.segments.set_texts([
    "QSD: MA(C,5), COLORWHITE, LINETHICK2;\n"
    "STICKLINE(C > MA(C,5), 0, 0, 3, 0), COLORFF0000;\n"
    "DRAWTEXT(C > 0, H, 1), COLORRED;"
])
view.detect_function(quiet=True)
detect_text = view.lbl_detect.text()
check("带尾部颜色的绘图语句不再导致检测失败", "无法识别" not in detect_text)
check("含未渲染语句仍判定为可运行", bool(view._programs))
check("提示点名了本期不渲染的函数", "DRAWTEXT" in detect_text and "不渲染" in detect_text)
check("检测文案完整进 tooltip（单行标签会截断）", view.lbl_detect.toolTip() == detect_text)
check("已支持的 STICKLINE 不进未渲染名单",
      all("STICKLINE" not in p.unsupported for p in view._programs))

print("== 行情页：内置指标与用户公式统一图层（§7-B3 P4，窗格已迁 ChartHost）==")
mkt = win.page_market
mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.current_df = df                      # 复用上面的合成行情
mkt.cb_ma.setChecked(True)
mkt.cb_boll.setChecked(False)
mkt.cb_vol.setChecked(True)
mkt.cb_macd.setChecked(False)
mkt.cb_formula.setChecked(True)
mkt._formula_segments = [("STICKLINE(C > MA(C,5), 0, 0, 3, 0), COLORFF0000;", 'main')]
mkt._formula_params_text = ""
mkt._compile_formula()
mkt.render_charts()

check("主图已建立（ChartHost 常驻主图窗格）", mkt.main_plot is not None)
check("窗格 = main/vol（副图按开关重建）", mkt.host.pane_names == ['main', 'vol'])
check("内置图层 = 3 条均线", len(mkt._layer_builtin) == 3)
check("公式图层落在主图 = 1 根状态柱", len(mkt._layer_formula.get('main', [])) == 1)
check("统一图元 = 3 内置 + 1 公式", len(mkt._layer_items) == 4)
check("内置线 = 3 个 PlotDataItem",
      sum(1 for it in mkt._layer_items if isinstance(it, pg.PlotDataItem)) == 3)
check("用户状态柱 → _StickItem（与内置走同一渲染器）",
      sum(1 for it in mkt._layer_items if it.__class__.__name__ == '_StickItem') == 1)

# 开关行为与 MA/BOLL **完全一致**（重渲染）：关掉公式只影响公式图层，内置指标保留
mkt.cb_formula.setChecked(False)
check("关掉公式后只剩内置图层（3 条）", len(mkt._layer_items) == 3
      and all(it.__class__.__name__ != '_StickItem' for it in mkt._layer_items))
mkt.cb_formula.setChecked(True)
check("再打开恢复公式图层（4 个）", len(mkt._layer_items) == 4)

# 公式在某标的上算不出来时：不打断整页渲染，只把原因写在面板上
mkt._formula_segments = [("X: 不存在的列 + 1;", 'main')]
mkt._compile_formula()
mkt.render_charts()
check("公式执行失败仍照常渲染内置图层", len(mkt._layer_items) == 3)
check("面板给出失败提示", "❌" in mkt.lbl_formula_status.text())
check("失败提示完整进 tooltip", mkt.lbl_formula_status.toolTip() == mkt.lbl_formula_status.text())

print("== 行情页：量级引导（副图量级误放主图）==")
MACD_LIKE = ("DIF := EMA(C,12) - EMA(C,26);\n"
             "MACD: (DIF - EMA(DIF,9)) * 2, COLORWHITE;")
mkt._formula_segments = [(MACD_LIKE, 'main')]
mkt._compile_formula()
mkt.render_charts()
check("副图量级误放主图 → 面板给出'改用副图'的建议",
      "⚠" in mkt.lbl_formula_status.text() and "副图" in mkt.lbl_formula_status.text())
check("完整引导进 tooltip", "相差很大" in mkt.lbl_formula_status.toolTip())

print("== 行情页：多副图 + 跨段共享变量池（v6.8 · P5）==")
mkt.cb_macd.setChecked(True)          # 触发一次重渲染（与用户点开关等价）
mkt._formula_segments = [
    ("基线 := MA(C,5);\n主图线: 基线, COLORWHITE;", 'main'),
    ("离差: C - 基线, COLORYELLOW;", 'sub1'),          # 引用段1变量 → 跨目标共享池
    ("RSV := (C - LLV(C,9)) / (HHV(C,9) - LLV(C,9)) * 100;\n"
     "K值: SMA(RSV,3,1), COLORMAGENTA;", 'sub2'),
]
mkt._compile_formula()
mkt.render_charts()

check("窗格顺序 = main/vol/macd/sub1/sub2",
      mkt.host.pane_names == ['main', 'vol', 'macd', 'sub1', 'sub2'])
check("按需创建两张公式副图", set(mkt.formula_plots) == {'sub1', 'sub2'})
check("主图图层来自段1", len(mkt._layer_formula.get('main', [])) == 1)
check("跨段共享变量池（段2 引用段1 的「基线」仍可求值）",
      len(mkt._layer_formula.get('sub1', [])) == 1
      and mkt._layer_formula['sub1'][0].name == '离差')
check("副图2 图层来自段3", mkt._layer_formula['sub2'][0].name == 'K值')
check("每张公式副图都联动主图 x 轴",
      all(p.vb.linkedView(pg.ViewBox.XAxis) is mkt.main_plot.vb
          for p in mkt.formula_plots.values()))
check("每张公式副图 y 轴独立（互不压扁）",
      all(p.vb.linkedView(pg.ViewBox.YAxis) is None for p in mkt.formula_plots.values()))
check("附图高度被钉死为 150", mkt.formula_plots['sub1'].maximumHeight() == SUB_PLOT_HEIGHT)
check("刻度值只在最下窗格显示（bottom_axis_mode=no_values）",
      mkt.main_plot.getAxis('bottom').style['showValues'] is False
      and mkt.formula_plots['sub2'].getAxis('bottom').style['showValues'] is True)
check("非最下窗格保留轴线（旧观感）", mkt.main_plot.getAxis('bottom').isVisible())
check("状态汇总落点分布", "主图 1" in mkt.lbl_formula_status.text()
      and "副图 2 格" in mkt.lbl_formula_status.text())

mkt.cb_formula.setChecked(False)
check("关掉开关后公式副图全部消失", mkt.formula_plots == {}
      and mkt.host.pane_names == ['main', 'vol', 'macd'])
mkt.cb_formula.setChecked(True)
check("重新打开后按需恢复", set(mkt.formula_plots) == {'sub1', 'sub2'})

print("== 公式对话框：每段目标窗格 + 示例模板 ==")
from ui.dialogs.formula_overlay import (TARGET_MAIN, TARGET_SUB1, TARGET_SUB2,
                                        FormulaOverlayDialog)

dlg = FormulaOverlayDialog(None, segments=[("M: MA(C,5), COLORWHITE;", TARGET_SUB1)],
                           params_text="L1=5")
check("回读段目标 = 副图 1", dlg.result_segments() == [("M: MA(C,5), COLORWHITE;", 'sub1')])
check("确定按钮文案 = 应用到行情图", dlg.btn_ok.text() == "应用到行情图")
check("回读参数文本", dlg.params_text() == "L1=5" and dlg.result_params() == {'L1': 5.0})
check("每段都挂上了目标窗格下拉", all(c is not None for c in dlg.segments.accessories()))

dlg._insert_example('sub')
check("插入副图模板后该段目标自动切到副图 1", dlg.result_segments()[0][1] == TARGET_SUB1)
check("模板内容含 MACD 示例", "EMA" in dlg.result_segments()[0][0])
check("示例模板能通过自检", dlg.check_function())
check("对话框只有一段（无僵尸段）",
      len(list(dlg.segments._iter_wraps())) == len(dlg.segments.texts()) == 1)

# 多段多目标：每段各选各的
dlg.segments.set_texts(["A: MA(C,5), COLORWHITE;", "B: (C - MA(C,5)), COLORRED;"])
combos = dlg.segments.accessories()
combos[0].setCurrentIndex(combos[0].findData(TARGET_MAIN))
combos[1].setCurrentIndex(combos[1].findData(TARGET_SUB2))
check("每段可各选不同目标窗格", dlg.result_segments() == [
    ("A: MA(C,5), COLORWHITE;", TARGET_MAIN),
    ("B: (C - MA(C,5)), COLORRED;", TARGET_SUB2)])

# v6.7 Bug② 的可观测量：段标题与编辑框之间**没有大空档**，多余高度进了编辑框
dlg.show()
app.processEvents()
wrap0 = list(dlg.segments._iter_wraps())[0]
check("编辑框紧贴段标题（不再被推到几百像素之外）", wrap0.editor.geometry().top() < 60)
check("多余高度被编辑框吸收（≥ 最小高度 110）", wrap0.editor.height() >= 110)
dlg.close()

print(f"\n===== 通过 {len(OK)} · 失败 {len(BAD)} =====")
for b in BAD:
    print("  FAIL:", b)
sys.exit(1 if BAD else 0)
