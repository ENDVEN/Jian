# -*- coding: utf-8 -*-
"""「回测页 + 行情工作台」公式叠层 / 标注 / 配方 / 自选 / 周期 / 成交模型（§7-B5）的**页面级**验收（P3–P8）。

用法：py tests/smoke_pages_overlay.py  （在仓库根目录执行）
⚠ 会真实构造主窗口（打开 ~/.jian_data），请勿在 app 运行中同时跑。
⚠ 三条"离屏测试必备"的打桩（**缺一条就会表现为"卡住、无输出"**，见 §11.7）：
   ① **模态对话框打桩** —— `QMessageBox/QInputDialog` 在离屏环境没有用户可点，
      一旦弹出就是**永久阻塞**（历史事故：一条"浏览模式下点添加应给提示"的断言
      直接让脚本挂死）。
   ② **更新检查打桩** —— `UpdateCheckerThread` 会请求 GitHub；测试不该依赖网络。
   ③ 结尾用 `os._exit()` —— 只要还有非守护 QThread 存活，解释器就不退出；
      而 `| Select-Object -Last N` 会**缓冲到进程结束**才显示 ⇒ 表现为"长时间无响应"。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
# 本文件在 tests/ 子目录里，**仓库根 = 本文件的父目录**（由 `__file__` 反推，§10-13）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 【防污染基准】本脚本会写入"用户标注 / 配方库 / 自选股"三类库，**一律用临时库**；
# 跑完会自检"用户真实库没被创建/修改"（见文件末尾），这条时间戳就是判据。
RUN_STARTED_AT = time.time()

import numpy as np
import pandas as pd

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

OK, BAD = [], []


def check(desc, cond):
    (OK if cond else BAD).append(desc)
    print(("  [OK] " if cond else "  [!!] ") + desc)


# ==========================================
# 打桩 ①：模态对话框（不点就会永久卡住）
# ==========================================
MODALS = []      # [(kind, text)] —— 记录"本该弹出来的对话框"，供断言
ANSWERS = []     # 预置的文本输入回答（按顺序消费；用尽回落默认值）


def _record(kind, args):
    MODALS.append((kind, " / ".join(str(a) for a in args if isinstance(a, str))[:200]))


def _install_modal_stubs():
    QMessageBox.information = staticmethod(lambda *a, **k: _record('information', a))
    QMessageBox.warning = staticmethod(lambda *a, **k: _record('warning', a))
    QMessageBox.critical = staticmethod(lambda *a, **k: _record('critical', a))

    def _question(*args, **_kwargs):
        _record('question', args)
        return QMessageBox.StandardButton.Yes      # 危险动作在测试里直接"确认"

    def _get_text(*args, **_kwargs):
        _record('input', args)
        return (ANSWERS.pop(0) if ANSWERS else "测试输入"), True

    QMessageBox.question = staticmethod(_question)
    QInputDialog.getText = staticmethod(_get_text)


_install_modal_stubs()

# ==========================================
# 打桩 ②：版本更新检查（测试不碰网络）
# ==========================================
import ui.main_window as _mw_module  # noqa: E402


class _SignalStub:
    def connect(self, *_args, **_kwargs):
        pass


class _NoopUpdateChecker:
    def __init__(self, *_args, **_kwargs):
        self.update_available = _SignalStub()

    def start(self):
        pass


_mw_module.UpdateCheckerThread = _NoopUpdateChecker

from core.formula.program import parse_program, execute_programs_with_draws  # noqa: E402
from ui.main_window import JianMainWindow  # noqa: E402
from ui.views.trading_desk import SUB_PLOT_HEIGHT  # noqa: E402

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

print("== 行情页：用户标注持久化 + 逐个独立删除（v6.9 · P6 · 管线 B）==")
import os
import tempfile

from data.annotations import KIND_HLINE, KIND_TREND, KIND_VLINE, AnnotationStore

# ⚠ 用**临时库**替换真实库，绝不污染 ~/.jian_data/annotations.json（用户数据主权）
tmp_annot = tempfile.mkdtemp(prefix="jian_annot_page_")
store = AnnotationStore(os.path.join(tmp_annot, "annotations.json"))
mkt._annotations._store = store

mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.current_df = df
mkt.cb_ma.setChecked(True)          # 触发一次完整重渲染（含标注 bind）
check("标注层已绑定当前标的", mkt._annotations._symbol == 'sh600000')
check("初始无标注、删除按钮禁用",
      mkt._annotations.count() == 0 and not mkt.btn_delete_annotation.isEnabled())

# —— 三类标注逐个新建（等价用户：选类型 → 点「➕ 添加标注」）——
mkt.cmb_tool.setCurrentIndex(1)
check("工具切换 → 面板回执显示当前工具", "趋势线" in mkt.lbl_annotation_status.text())
trend = mkt._annotations.create_default()
mkt.cmb_tool.setCurrentIndex(2)
hline = mkt._annotations.create_default()
mkt.cmb_tool.setCurrentIndex(3)
vline = mkt._annotations.create_default()
check("三类标注全部落库", store.count('sh600000') == 3
      and all(x is not None for x in (trend, hline, vline)))
check("三类标注全部画到主图（ChartPane 标注容器）",
      len(mkt._annotations._items) == 3 and len(mkt.host.main_pane.annotation_items) == 3)
check("趋势线 = LineSegmentROI（可拖两端）",
      mkt._annotations._items[trend["id"]].__class__.__name__ == 'LineSegmentROI')
check("水平/垂直线 = InfiniteLine",
      all(mkt._annotations._items[x["id"]].__class__.__name__ == 'InfiniteLine'
          for x in (hline, vline)))
check("落库坐标是日期（不是 bar 序号）", trend["points"][0][0] ==
      df['date'].iloc[0].strftime('%Y-%m-%d') or "-" in trend["points"][0][0])
check("新建后删除按钮可用（已自动选中新对象）", mkt.btn_delete_annotation.isEnabled())

# —— 重渲染（改指标开关）后标注仍在：证明"读盘恢复"而非"内存残留" ——
mkt.cb_boll.setChecked(True)
check("重渲染后 3 条标注仍在图上", len(mkt._annotations._items) == 3)
check("重渲染不产生重复条目", store.count('sh600000') == 3)

# —— 模拟重启：新建一个 store 从同一文件读回 ——
reopened = AnnotationStore(store.path)
check("重启后能从磁盘读回全部标注", len(reopened.list('sh600000')) == 3)
check("按 (标的, 周期) 隔离：另一个标的读不到",
      reopened.count('sz000001') == 0 and reopened.symbols() == ['sh600000'])

# —— 逐个独立删除（管线 B 的硬要求）——
mkt._annotations.select(hline["id"])
check("选中态可被页面读到（删除按钮据此启用）", mkt._annotations.selected_id == hline["id"])
mkt.delete_selected_annotation()
check("删除只影响被选中的那一条",
      store.count('sh600000') == 2 and hline["id"] not in mkt._annotations._items
      and len(mkt.host.main_pane.annotation_items) == 2)
check("被删的那条不会从磁盘复活",
      hline["id"] not in [i["id"] for i in AnnotationStore(store.path).list('sh600000')])
check("删除后取消选中、按钮回到禁用", mkt._annotations.selected_id == ""
      and not mkt.btn_delete_annotation.isEnabled())

# —— 关键防漂移断言：数据窗口变化后，标注锚定的**仍是同一天** ——
# 【为什么要在**前面**插数据】bar 序号会整体后移，只有当数据窗口的"起点提前"时才会发生
# （典型场景：重新全量下载补到更早历史 / 首次只加载了一段）。这正是"存日期而不是存序号"的理由。
anchor_date = trend["points"][0][0]
x_before = mkt._annotations._x(anchor_date)
first_date = df['date'].iloc[0]
earlier = pd.DataFrame({
    'date': [first_date - pd.Timedelta(days=offset) for offset in range(5, 0, -1)],
    'open': 1.0, 'high': 1.0, 'low': 1.0, 'close': 1.0, 'volume': 0.0,
})
mkt.current_df = pd.concat([earlier, df], ignore_index=True)
mkt.render_charts()
x_after = mkt._annotations._x(anchor_date)
check("数据窗口前提 5 根后，标注仍锚在同一天（序号 +5，而不是漂移错位）",
      x_after == x_before + 5 and mkt._annotations._axis.size == len(df) + 5)
check("数据窗口变化后标注仍在图上", len(mkt._annotations._items) == 2)
check("存储里的日期没被改写（漂移的是序号不是数据）",
      AnnotationStore(store.path).list('sh600000')[0]["points"][0][0] == anchor_date)

# —— 清空：只清本标的（页面侧有二次确认；此处直接调底层）——
removed = mkt._annotations.clear_all()
check("清空本标的：删掉 2 条且图上清空",
      removed == 2 and store.count('sh600000') == 0
      and len(mkt.host.main_pane.annotation_items) == 0)

print("== 行情页 ⇄ 回测页：公式资产化 + 互送（v6.11 · P7）==")
from PyQt6.QtWidgets import QInputDialog

from data.formula_store import FormulaStore
from ui.widgets.formula_library import FormulaLibraryDialog

# ⚠ 用**临时库**替换真实库，绝不污染 ~/.jian_data/formula_library.json（用户数据主权）
tmp_formula = tempfile.mkdtemp(prefix="jian_formula_page_")
fstore = FormulaStore(os.path.join(tmp_formula, "formula_library.json"))
mkt._formula_store = fstore
bt = win.page_backtest.backtest_single
bt.formula_store = fstore
check("两个页面共用同一个配方库实例（否则后保存的会覆盖先保存的）",
      mkt._formula_store is bt.formula_store)

MACD_SEG = "DIF := EMA(C,12) - EMA(C,26);\nMACD线: DIF, COLORWHITE;"
MA_SEG = "MA线: MA(C,5), COLORRED;"
mkt.receive_formula([(MACD_SEG, 'sub1'), (MA_SEG, 'main')], "L1=5", source_label="测试")
check("行情页接收外来公式：段 / 参数 / 目标窗格全部落位",
      [t for t, _ in mkt._formula_segments] == [MACD_SEG, MA_SEG]
      and [g for _, g in mkt._formula_segments] == ['sub1', 'main']
      and mkt._formula_params_text == "L1=5")
check("接收后回执说明了来源", "测试" in mkt.lbl_formula_status.text())

# —— 存为配方（输入框已在上方统一打桩；这里只排队"该输入什么名字"）——
ANSWERS.extend(["行情页配方", "回测页配方", "行情页配方"])
mkt.save_formula_as()
saved_market = fstore.get_by_name("行情页配方")
check("行情页把公式存进了配方库", saved_market is not None and fstore.count() == 1)
check("配方**保留了每段的目标窗格**（回测侧做不到这点）",
      [seg["target"] for seg in saved_market["segments"]] == ['sub1', 'main'])
check("配方记录了来源与参数",
      saved_market["source"] == 'market' and saved_market["params_text"] == "L1=5")

# —— 行情页 → 回测页 ——
sent = mkt.send_formula_to_backtest()
check("互送：段数一致", sent == 2)
check("回测页①函数区已收到函数文本（目标不随行）",
      bt.segments.texts() == [MACD_SEG, MA_SEG])
check("回测页参数框已同步", bt.txt_params.text() == "L1=5")
check("互送后自动切到回测页", win.content_area.currentIndex() == 4)
check("送来的函数被自动检测（不是静默塞进去）",
      bt.lbl_detect.text() and "未检测" not in bt.lbl_detect.text())

# —— 回测页 → 行情页 ——
bt.segments.set_texts(["RSV := (C - LLV(C,9)) / (HHV(C,9) - LLV(C,9)) * 100;\nK值: RSV, COLORWHITE;"])
bt.txt_params.setText("N1=9")
bt.save_formula_as()
check("回测页也能存配方（同名覆盖、来源标记正确）",
      fstore.count() == 2 and fstore.get_by_name("回测页配方")["source"] == 'backtest')

back = bt.send_formula_to_market()
check("互送：回测页 → 行情页 段数一致", back == 1)
check("行情页已切换并按「主图」接收（回测侧没有窗格信息）",
      len(mkt._formula_segments) == 1 and mkt._formula_segments[0][1] == 'main'
      and mkt._formula_params_text == "N1=9")
check("互送后自动切到行情页", win.content_area.currentIndex() == 3)
check("回执说明了来源", "回测页" in mkt.lbl_formula_status.text())

# —— 配方库对话框 ——
dlg = FormulaLibraryDialog(fstore)
check("配方库列出了全部配方", dlg.lst_formulas.count() == fstore.count() == 2)
check("未点载入时没有选中结果", dlg.selected_formula() is None)
check("选中项可被读出", dlg.current_formula() is not None)
check("预览区展示了选中配方的正文",
      dlg.current_formula()["name"] in dlg.txt_preview.toPlainText())
dlg.load_selected()
check("载入后回传该配方", dlg.selected_formula()["name"] == dlg.current_formula()["name"]
      or dlg.selected_formula() is not None)
check("载入会记录“最近使用”", bool(fstore.get(dlg.selected_formula()["id"])["used_at"]))
dlg.close()

# —— 开机自动恢复（"公式重启就丢"的治本办法）——
last = fstore.last_used()
mkt._formula_segments, mkt._formula_params_text = [], ""
mkt._restore_last_formula()
check("自动恢复上次用过的配方（含参数）",
      len(mkt._formula_segments) == len(last["segments"])
      and mkt._formula_params_text == last["params_text"])
check("恢复回执点名了配方名", last["name"] in mkt.lbl_formula_status.text())

# —— 同名覆盖（不产生重复条目）——
before = fstore.count()
mkt.save_formula_as()
check("同名再保存 = 覆盖，不新增条目", fstore.count() == before)

print("== 行情工作台（v6.12 · P8）：自选股 / 周期 / 新画线类型 ==")
from data.annotations import KIND_FIB, KIND_TEXT, AnnotationStore  # noqa: E402
from data.watchlist_store import WatchlistStore  # noqa: E402
from core.utils import resample_ohlcv  # noqa: E402
from ui.widgets.annotation_layer import DRAWABLE_KINDS  # noqa: E402

# ⚠ 同样用**临时库**：自选股与标注都不碰用户真实文件
tmp_p8 = tempfile.mkdtemp(prefix="jian_p8_")
mkt.watchlist = WatchlistStore(os.path.join(tmp_p8, "watchlist.json"))
p8_store = AnnotationStore(os.path.join(tmp_p8, "annotations.json"))
mkt._annotations._store = p8_store

# ---- 自选股 ----
mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.add_to_watchlist()
check("加入自选：库里有 1 条、列表也刷新了",
      mkt.watchlist.count() == 1 and mkt.lst_watch.count() == 1)
mkt.add_to_watchlist()
check("重复加入不产生重复项", mkt.watchlist.count() == 1)
mkt.watchlist.add('sz000001', '平安银行')
mkt._refresh_watchlist()
check("列表条数与库一致", mkt.lst_watch.count() == 2)

mkt.lst_watch.setCurrentRow(1)
mkt.move_watchlist(-1)
check("上移改变顺序（顺序 = 用户关注顺序）", mkt.watchlist.symbols()[0] == 'SZ000001')
mkt.move_watchlist(1)
check("下移恢复原顺序", mkt.watchlist.symbols()[1] == 'SZ000001')

# 双击切换标的：把联网入口换掉，避免测试触发真实网络与后台线程
sync_calls = []
mkt.sync_cloud = lambda: sync_calls.append(mkt.current_symbol)
target_symbol = str(mkt.lst_watch.item(0).data(Qt.ItemDataRole.UserRole))
mkt.current_symbol = None
mkt._on_watch_activated(mkt.lst_watch.item(0))
check("双击自选即切换标的（本地无数据时自动转同步）",
      mkt.current_symbol == target_symbol and sync_calls == [target_symbol])

mkt.lst_watch.setCurrentRow(1)
mkt.remove_from_watchlist()
check("移除选中项（库与列表同步）",
      mkt.watchlist.count() == 1 and mkt.lst_watch.count() == 1)

# ---- 周期：周/月由日线就地聚合 ----
mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.current_df = df
mkt.render_charts()                      # 先以日线建立一次基线
daily_bars = mkt._layer_bars
check("日线基线：渲染根数 = 原始日线根数", daily_bars == len(df))
check("标注层周期键 = D", mkt._annotations._period == 'D')

mkt.cb_period.setCurrentIndex(1)          # 周线
weekly_bars = len(resample_ohlcv(df, 'W'))
check("切周线：渲染根数 = 聚合后的周线根数", mkt.current_period == 'W'
      and mkt._layer_bars == weekly_bars < daily_bars)
check("标题注明周期与根数", '周线' in mkt.main_plot.titleLabel.text
      and str(weekly_bars) in mkt.main_plot.titleLabel.text)
check("标注层周期跟着切（日线的画线不串到周线）", mkt._annotations._period == 'W')

mkt.cmb_tool.setCurrentIndex(1 + DRAWABLE_KINDS.index('trend'))
mkt._annotations.create_default()
check("标注按 (标的, 周期) 隔离：只在 weekly 有一条第 daily 为 0",
      p8_store.count('sh600000', 'weekly') == 1 and p8_store.count('sh600000', 'daily') == 0)

mkt.cb_period.setCurrentIndex(2)          # 月线
check("切月线：根数 = 月线聚合根数且标注按 monthly 取",
      mkt.current_period == 'M' and mkt._layer_bars == len(resample_ohlcv(df, 'M'))
      and mkt._annotations._period == 'M' and mkt._annotations.count() == 0)

# ---- 新画线类型：斐波那契 / 文字 ----
check("工具下拉 = 浏览 + 交互层声明的全部可画类型（两处同源）",
      mkt.cmb_tool.count() == 1 + len(DRAWABLE_KINDS))

mkt.cmb_tool.setCurrentIndex(1 + DRAWABLE_KINDS.index(KIND_FIB))
fib_item = mkt._annotations.create_default()
check("斐波那契：主图元 + 7 档水平位 + 7 标签",
      fib_item is not None and len(mkt._annotations._extras[fib_item['id']]) == 14
      and len(mkt.host.main_pane.annotation_items) == 15)
check("面板回执说明了当前工具与周期", '斐波那契' in mkt.lbl_annotation_status.text()
      and '月线' in mkt.lbl_annotation_status.text())
mkt.delete_selected_annotation()
check("删除斐波那契：附属水平位一并消失（不留无主图元）",
      len(mkt.host.main_pane.annotation_items) == 0 and p8_store.count('sh600000', 'monthly') == 0)

ANSWERS.append("这里是压力位")              # 文字标注要填内容 → 交给打桩的输入框
mkt.cmb_tool.setCurrentIndex(1 + DRAWABLE_KINDS.index(KIND_TEXT))
mkt.add_annotation()
check("文字标注：经页面入口创建并落库",
      mkt._annotations.count() == 1 and len(mkt.host.main_pane.annotation_items) == 1)

before_modals = len(MODALS)
mkt.cmb_tool.setCurrentIndex(0)            # 回到浏览模式：不应再新建
mkt.add_annotation()
check("浏览模式下点「添加」不会新建（改为提示用户先选类型）",
      mkt._annotations.count() == 1
      and any(kind == 'information' for kind, _text in MODALS[before_modals:]))
mkt._annotations.clear_all()

# ---- 复权切换（v6.13 · P8 收尾）：换分区取数，两份互不覆盖 ----
from data.sync_service import ADJUST_NONE, ADJUST_QFQ, zone_for_adjust  # noqa: E402

check("默认前复权（与全 app 历史行为一致）",
      mkt.current_adjust == ADJUST_QFQ and mkt.cb_adjust.currentData() == ADJUST_QFQ
      and zone_for_adjust(mkt.current_adjust) == 'kline_daily')

adjust_syncs = []
mkt.sync_cloud = lambda: adjust_syncs.append(zone_for_adjust(mkt.current_adjust))
mkt.cb_adjust.setCurrentIndex(1)             # → 不复权
check("切到不复权：口径与目标分区都换了",
      mkt.current_adjust == ADJUST_NONE
      and zone_for_adjust(mkt.current_adjust) == 'kline_daily_raw')
check("本地没有这一份 → 转云端取数，且取的是**不复权分区**（不复用前复权那份）",
      adjust_syncs == ['kline_daily_raw'])
check("面板立刻交代清楚：口径 + 取数中（且不谎报根数）",
      '不复权' in mkt.lbl_adjust_hint.text()
      and '正在从云端取' in mkt.lbl_adjust_hint.text()
      and '根' not in mkt.lbl_adjust_hint.text())
check("不复权明确提示两个已知差异（除权跳空 / 画线不共用）",
      '除权' in mkt.lbl_adjust_hint.text() and '画线' in mkt.lbl_adjust_hint.text())
check("tooltip 点名了对应分区（便于用户去数据管理页核对）",
      'kline_daily_raw' in mkt.lbl_adjust_hint.toolTip())

mkt.cb_adjust.setCurrentIndex(0)             # 切回前复权
check("切回前复权：回到前复权分区（两份来回切不会互相覆盖）",
      mkt.current_adjust == ADJUST_QFQ and adjust_syncs[-1] == 'kline_daily')

print("== v6.15 · 坐标轴自适应（§7-B4）：页面级 ==")
from ui.widgets.adaptive_axis import handle_for  # noqa: E402

# ---- 行情工作台：主图 + 量/MACD 副图逐格自适应 ----
mkt.cb_period.setCurrentIndex(0)           # 回到日线（前面测过周/月）
mkt.cb_vol.setChecked(True)
mkt.cb_macd.setChecked(True)
mkt.current_df = df                        # 200 根合成日线（前面被前置过 5 根，这里复位）
mkt.render_charts()
app.processEvents()

check("行情页每个窗格都挂了自适应跟随器（不是只挂最下那张）",
      set(mkt._axes.pane_names) == set(mkt.host.pane_names)
      and {'main', 'vol', 'macd'} <= set(mkt._axes.pane_names))
check("跟随器可反查（弱引用登记表读口）", handle_for(mkt.main_plot) is not None)

mkt.main_plot.getViewBox().setXRange(40, 49, padding=0)     # 缩到 10 根（旧实现只剩 1 个刻度）
app.processEvents()
bottom_ticks = mkt._axes.ticks_of(mkt.host.bottom_axis_pane)
check(f"缩到 10 根后底部轴仍有 {len(bottom_ticks)} 个刻度且全落在窗口内",
      len(bottom_ticks) >= 2 and all(40 <= index <= 49 for index, _ in bottom_ticks))
check("刻度文本是日期（不再出现 pyqtgraph 自动生成的 'A' 之类字符）",
      all('-' in text for _, text in bottom_ticks))

prepared = mkt.prepared_df()
visible_peak = float(prepared['volume'].to_numpy(dtype=float)[40:50].max())
vol_lo, vol_hi = mkt._axes.handle('vol').y_range
full_peak = float(prepared['volume'].to_numpy(dtype=float).max())
check(f"量副图 y 跟随可视区间（可视峰 {visible_peak:,.0f} ⇒ 上限 {vol_hi:,.0f}）",
      abs(vol_hi - visible_peak * 1.06) < visible_peak * 0.01 and vol_lo < 0.0)
check(f"且不再被全量峰值钉死（{vol_hi:,.0f} < 全量版 {full_peak * 1.06:,.0f}）",
      vol_hi < full_peak * 1.06 * 0.95)

macd_lo, macd_hi = mkt._axes.handle('macd').y_range
check("MACD 副图量程含 0（零轴必须留在可视区，否则看不出柱子正负）",
      macd_lo <= 0.0 <= macd_hi)

mkt.main_plot.getViewBox().setXRange(0, len(df) - 1, padding=0)
app.processEvents()
wide_ticks = mkt._axes.ticks_of(mkt.host.bottom_axis_pane)
check("缩回全量后刻度重新变密（自适应是双向的）",
      len(wide_ticks) > len(bottom_ticks) and wide_ticks[-1][0] == len(df) - 1)

# ---- 复盘页：资金 K 线（横轴=当月第几日，序数轴）也接了自适应 ----
rev = win.page_review
rev_days = 12
rev.current_view_df = pd.DataFrame({
    'trade_time': pd.to_datetime([f'2025-06-{day:02d} 09:30' for day in range(1, rev_days + 1)]),
    'net_profit': [120.0 if day % 2 else -80.0 for day in range(rev_days)],
    'commission': [2.0] * rev_days,
})
rev._render_monthly_charts()
app.processEvents()
rev_handle = handle_for(rev.review_kline_chart)
check("复盘页资金 K 线接了自适应坐标轴", rev_handle is not None)
check("横轴是序数文本（「N日」）且密度收敛，不是 12 个标签全堆上",
      rev_handle is not None and 0 < len(rev_handle.ticks) <= rev_days
      and all(text.endswith('日') for _, text in rev_handle.ticks))
check("资金 K 线纵轴也跟随可视区间", rev_handle is not None and rev_handle.y_enabled)

# ==========================================
# §7-B5 成交真实性：页面级接线（v6.18）
#   引擎侧断言在 tests/smoke_chart.py；这里只管"页面上能不能用、导出能不能溯源"。
# ==========================================
print("\n[§7-B5] 成交模型行：UI 往返 / 存档兼容 / 参数按需出现")
from core.backtest import (FILL_CLOSE, FILL_NEXT_OPEN, FILL_TRIGGER, BacktestEngine,
                           BacktestTrade, fill_mode_oneliner, normalize_fill,
                           tick_to_yuan, yuan_to_tick)  # noqa: E402
from core.backtest import fill_summary as _fill_summary  # noqa: E402

check("新建页面默认口径 = 次日开盘 + 0.01 元（与改动前行为一致）",
      view._fill_config() == {"fill_mode": FILL_NEXT_OPEN, "trigger_tick": 1})
check("下拉三项文案与 core.backtest 同源（页面没另写一份）",
      [view.cmb_fill_mode.itemData(i) for i in range(view.cmb_fill_mode.count())]
      == [FILL_NEXT_OPEN, FILL_CLOSE, FILL_TRIGGER])
check("行内说明默认已显示（不必悬停就能看到）",
      view.lbl_fill_desc.text() == fill_mode_oneliner(FILL_NEXT_OPEN, 1))
check("非第三档时「买卖价要多等」整块隐藏 —— 不给用户看不懂的常驻参数",
      not view._fill_offset_box.isVisibleTo(view))

check("跳数控件步长 == 0.01 元（有过渡价格，不是一按顶到上限）",
      abs(view.spin_fill_offset.singleStep() - 0.01) < 1e-12)
view.spin_fill_offset.setValue(0.01)
view.spin_fill_offset.stepUp()
check("0.01 按一次上箭头 → 0.02（逐级过渡）",
      abs(view.spin_fill_offset.value() - 0.02) < 1e-9)
check("风控行的 1 位小数控件步长仍为 0.5（没被顺手改坏）",
      abs(view.spin_risk_stop.singleStep() - 0.5) < 1e-12)

view._apply_fill_config({"fill_mode": FILL_TRIGGER, "trigger_tick": 3})
check("载入触发式口径可完整还原（3 跳 ↔ 0.03 元）",
      view._fill_config() == {"fill_mode": FILL_TRIGGER, "trigger_tick": 3}
      and abs(view.spin_fill_offset.value() - 0.03) < 1e-9)
check("第三档「买卖价要多等」对用户可见", view._fill_offset_box.isVisibleTo(view))
check("行内说明里的金额跟着参数实时变（0.03 元）", "0.03 元" in view.lbl_fill_desc.text())
check("元→跳 换算走公共件（界面用元、落库存整数跳）",
      tick_to_yuan(3) == 0.03 and yuan_to_tick(0.35) == 35)

view._apply_fill_config({})                      # 模拟"旧存档：完全没有 fill 字段"
check("载入旧存档（无 fill 字段）→ 回落默认口径，老策略跑的还是同一套口径",
      view._fill_config() == {"fill_mode": FILL_NEXT_OPEN, "trigger_tick": 1})
view._apply_fill_config({"fill_mode": "瞎写", "trigger_tick": -9})
check("载入非法口径 → 回落默认（不炸、也不静默乱用）",
      view._fill_config() == {"fill_mode": FILL_NEXT_OPEN, "trigger_tick": 1})

check("策略快照 payload 携带 fill（保存后可完整复原）",
      view._strategy_payload().get("fill")
      == {"fill_mode": FILL_NEXT_OPEN, "trigger_tick": 1})
from data.strategy_store import _signature as _sig  # noqa: E402
_payload = view._strategy_payload()
check("真实 payload 去掉 fill 字段后签名不变 —— 默认口径不改变策略身份",
      _sig({k: v for k, v in _payload.items() if k != "fill"}) == _sig(_payload))

print("[§7-B5] 用户教学入口：📖 三档怎么选？")
check("行上有「📖 三档怎么选？」按钮（教学入口是看得见的，不只藏在 tooltip 里）",
      hasattr(view, "btn_fill_help") and "怎么选" in view.btn_fill_help.text())
from ui.dialogs.fill_model_help import FillModelHelpDialog  # noqa: E402
_help = FillModelHelpDialog(None, trigger_tick=2)
from PyQt6.QtWidgets import QLabel, QPushButton  # noqa: E402
_help_text = " ".join(lab.text() for lab in _help.findChildren(QLabel))
check("教学弹窗标题是问句式人话", _help.windowTitle() == "成交模型怎么选？")
check("弹窗用一套固定价格数字讲三档差别（有例子才教得会）",
      all(x in _help_text for x in ("10.00", "10.60", "9.50", "9.30")))
check("弹窗里的金额与实际参数一致（用户看到的例子 = 他将要用的口径）",
      "0.02 元" in _help_text)
check("T+1 用大白话解释，不出现「当根/K线」",
      "今天买的" in _help_text and "今天不能卖" in _help_text
      and "当根" not in _help_text and "K 线" not in _help_text)
check("弹窗有明确关闭按钮",
      any(isinstance(b, QPushButton) and "知道了" in b.text()
          for b in _help.findChildren(QPushButton)))
_help.deleteLater()

print("[§7-B5] 导出：口径可溯源 + T+1 标记 + 结构不变")
_probe_df = pd.DataFrame({
    "date": pd.date_range("2024-01-02", periods=4, freq="D"),
    "open": [10.0] * 4, "high": [10.0] * 4, "low": [10.0] * 4,
    "close": [10.0] * 4, "volume": [1] * 4})
_bt_res = BacktestEngine()._run_on_signals(
    data=_probe_df, buy_signal=np.array([False] * 4), sell_signal=np.array([False] * 4),
    symbol="sh600000", buy_expression="B", sell_expression="S",
    start_date="2024-01-02", end_date="2024-01-05", params={}, commission_rate=0.0003,
    risk={"max_bars": 0, "stop_loss_pct": 0.0, "take_profit_pct": 0.0, "trailing_pct": 0.0})
_bt_res.trades = [
    BacktestTrade(entry_date=pd.Timestamp("2024-01-03"), exit_date=pd.Timestamp("2024-01-04"),
                  entry_price=10.0, exit_price=9.0, commission=0.0057, pnl=-1.0057,
                  return_pct=-0.10057, exit_reason="stop_loss", deferred_t1=True),
    BacktestTrade(entry_date=pd.Timestamp("2024-02-01"), exit_date=pd.Timestamp("2024-02-20"),
                  entry_price=10.0, exit_price=11.0, commission=0.0063, pnl=0.9937,
                  return_pct=0.09937, exit_reason="signal", deferred_t1=False),
]
_meta = {"symbol": "sh600000", "name": "测试股", "strategy_name": "单元测试",
         "start_date": "2024-01-01", "end_date": "2024-12-31",
         "segments": ["A:MA(C,5);"], "params_text": "N=5", "buy_expr": "B",
         "sell_expr": "S", "risk": {}, "index": None,
         "fill": {"fill_mode": FILL_TRIGGER, "trigger_tick": 2}}
_csv_text = view._compose_result_csv(_bt_res, _meta)
check("CSV 表头写入成交模型（与 fill_summary 同源）",
      f"# 成交模型: {_fill_summary(FILL_TRIGGER, 2)}" in _csv_text)
check("CSV 表头写明 T+1 已启用（导出可复现）", "# T+1 约束：已启用" in _csv_text)
check("被 T+1 顺延的那一笔在明细里带标记", _csv_text.count("（T+1 顺延）") == 1)

import csv as _csv  # noqa: E402
import io as _io  # noqa: E402
_rows = list(_csv.reader(_io.StringIO(_csv_text)))
_hdr = next(i for i, r in enumerate(_rows) if r and r[0] == "买入日期")
_data = [r for r in _rows[_hdr + 1:] if r]
check("逐笔区仍是 8 列（新增标记没破坏列结构）", all(len(r) == 8 for r in _data))
check("逐笔行数 == 成交笔数", len(_data) == 2)
check("表头区每行仍是单格（含逗号的函数行不会被拆列）",
      all(len(r) == 1 for r in _rows[:_hdr] if r))

from ui.widgets.backtest_report import render_result_png  # noqa: E402
_png_dir = tempfile.mkdtemp(prefix="_tmp_png_")
_png = os.path.join(_png_dir, "r.png")
_ok_png = render_result_png(_meta, _bt_res, _png)
check("PNG 报告图带成交模型渲染并落盘成功", bool(_ok_png) and os.path.getsize(_png) > 0)
from PyQt6.QtGui import QImage  # noqa: E402
check("报告图尺寸仍是 1120×660",
      QImage(_png).width() == 1120 and QImage(_png).height() == 660)

# ==========================================
# 收尾自检：绝不能污染用户真实数据（测试一律用临时库）
# ==========================================
from config import settings  # noqa: E402

for _name in ("annotations.json", "formula_library.json", "watchlist.json",
              "backtest_strategies.json"):
    _path = os.path.join(settings.USER_DATA_DIR, _name)
    _untouched = (not os.path.exists(_path)) or os.path.getmtime(_path) < RUN_STARTED_AT
    check(f"未污染用户真实库 {_name}（本脚本只用临时库）", _untouched)

print(f"\n===== 通过 {len(OK)} · 失败 {len(BAD)} =====")
for b in BAD:
    print("  FAIL:", b)

# 【打桩 ③】必须强制退出：只要还有非守护 QThread 存活（哪怕只是后台收尾），
# 解释器就不退出 ⇒ 管道 | Select-Object -Last N 会一直缓冲、表现为"无响应"。
sys.stdout.flush()
os._exit(1 if BAD else 0)
sys.exit(1 if BAD else 0)
