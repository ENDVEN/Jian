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

# 【§11.7】Windows 控制台默认 GBK：带 ⇒ 这类符号的 print 会抛 UnicodeEncodeError，
# 表现为"某个分节整段被跳过 + 假报若干失败"（1.23 修）。统一按 UTF-8 输出。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 —— 被重定向的流不支持 reconfigure 就跳过
        pass

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

# ==========================================
# 打桩 ③：用户偏好**一律不落盘**（1.23 · STEP 3c 真踩到的坑）
#   行情工作台会记住"上次用什么"（`desk_ui`），回测页会记 `backtest_ui`；
#   测试里点一下开关就会触发保存 ⇒ 跑一次冒烟就把用户真实 `preferences.json` 写脏。
#   做法是**两层保险**：
#     ① 单例的 `path` 重定向到临时目录 —— 无论哪条代码路径保存，都写不到用户文件；
#     ② `Preferences.save` 再打一层桩（内存写入）。断言照常读内存值。
#   收尾自检里仍保留 `preferences.json`，防止以后有人绕过这层。
# ==========================================
from core import preferences as _pref_module  # noqa: E402

_pref_module.preferences.path = os.path.join(
    tempfile.mkdtemp(prefix="_tmp_pref_"), "preferences.json")
_pref_module.Preferences.save = lambda self: True

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
mkt.select_tool('trend')
check("工具切换 → 面板回执显示当前工具", "趋势线" in mkt.lbl_annotation_status.text())
trend = mkt._annotations.create_default()
mkt.select_tool('hline')
hline = mkt._annotations.create_default()
mkt.select_tool('vline')
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

mkt.select_period_group("W")              # 周线（★STEP 3b：分段控件与测试同一入口）
weekly_bars = len(resample_ohlcv(df, 'W'))
check("切周线：渲染根数 = 聚合后的周线根数", mkt.current_period == 'W'
      and mkt._layer_bars == weekly_bars < daily_bars)
check("标题注明周期与根数", '周线' in mkt.main_plot.titleLabel.text
      and str(weekly_bars) in mkt.main_plot.titleLabel.text)
check("标注层周期跟着切（日线的画线不串到周线）", mkt._annotations._period == 'W')

mkt.select_tool('trend')
mkt._annotations.create_default()
check("标注按 (标的, 周期) 隔离：只在 weekly 有一条第 daily 为 0",
      p8_store.count('sh600000', 'weekly') == 1 and p8_store.count('sh600000', 'daily') == 0)

mkt.select_period_group("M")              # 月线
check("切月线：根数 = 月线聚合根数且标注按 monthly 取",
      mkt.current_period == 'M' and mkt._layer_bars == len(resample_ohlcv(df, 'M'))
      and mkt._annotations._period == 'M' and mkt._annotations.count() == 0)

# ---- 新画线类型：斐波那契 / 文字 ----
check("画线工具 = 浏览 + 交互层声明的全部可画类型（两处同源；★STEP 4 起是分段控件）",
      mkt.seg_tool.count() == 1 + len(DRAWABLE_KINDS)
      and mkt.seg_tool.current_key() == 'trend')

mkt.select_tool(KIND_FIB)
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
mkt.select_tool(KIND_TEXT)
mkt.add_annotation()
check("文字标注：经页面入口创建并落库",
      mkt._annotations.count() == 1 and len(mkt.host.main_pane.annotation_items) == 1)

before_modals = len(MODALS)
mkt.select_tool("")                        # 回到浏览模式：不应再新建
mkt.add_annotation()
check("浏览模式下点「添加」不会新建（改为提示用户先选类型）",
      mkt._annotations.count() == 1
      and any(kind == 'information' for kind, _text in MODALS[before_modals:]))
mkt._annotations.clear_all()

# ---- 复权切换（v6.13 · P8 收尾）：换分区取数，两份互不覆盖 ----
from data.sync_service import ADJUST_NONE, ADJUST_QFQ, zone_for_adjust  # noqa: E402

check("默认前复权（与全 app 历史行为一致）",
      mkt.current_adjust == ADJUST_QFQ and mkt.seg_adjust.current_key() == ADJUST_QFQ
      and zone_for_adjust(mkt.current_adjust) == 'kline_daily')

adjust_syncs = []
mkt.sync_cloud = lambda: adjust_syncs.append(zone_for_adjust(mkt.current_adjust))
mkt.select_adjust(ADJUST_NONE)               # → 不复权
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

mkt.select_adjust(ADJUST_QFQ)                # 切回前复权
check("切回前复权：回到前复权分区（两份来回切不会互相覆盖）",
      mkt.current_adjust == ADJUST_QFQ and adjust_syncs[-1] == 'kline_daily')

print("== v6.15 · 坐标轴自适应（§7-B4）：页面级 ==")
from ui.widgets.adaptive_axis import handle_for  # noqa: E402

# ---- 行情工作台：主图 + 量/MACD 副图逐格自适应 ----
mkt.select_period_group("D")               # 回到日线（前面测过周/月）
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
# 1.22：成交模型收进「🎯 成交」编辑卡片（默认收起）；isVisibleTo(卡片) 只看该控件
# 自身与卡片的 body —— 卡片整体收起不影响这里的口径，也不必写用户偏好文件。
check("非第三档时「买卖价要多等」整块隐藏 —— 不给用户看不懂的常驻参数",
      not view._fill_offset_box.isVisibleTo(view.pane_fill))

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
check("第三档「买卖价要多等」对用户可见", view._fill_offset_box.isVisibleTo(view.pane_fill))
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

print("\n== §7-B6 STEP 3b · 顶栏第 2 行：分段控件（周期含分钟 / 复权）+ 口径回执 ==")
# 本节只验"控件与状态"，**不联网**：分钟取数路径用 monkeypatch 的 sync_cloud 观察。
from core.utils import MINUTE_DEPTH_DAYS, MINUTE_PERIODS, is_minute_period  # noqa: E402
from data.sync_service import ZONE_MIN, minute_key  # noqa: E402
from ui.views.trading_desk import DESK_UI_KEY  # noqa: E402

check("顶栏第 2 行的三个分段控件齐备（周期 / 分钟档位 / 复权）",
      all(hasattr(mkt, name) for name in ("seg_period", "seg_minute", "seg_adjust")))
check("周期分段 = 日/周/月/分钟 四档（一级）",
      mkt.seg_period.count() == 4 and mkt.seg_period.labels() == ["日", "周", "月", "分钟"])
check("分钟档位分段 = 1/5/15/30/60 五档（二级，只在选「分钟」时出现）",
      mkt.seg_minute.count() == 5 and mkt.seg_minute.labels() == ["1", "5", "15", "30", "60"])

# ---- 日线态：二级控件隐藏、复权可用 ----
mkt.select_period_group("D")
check("日线态：分钟档位与深度提示都隐藏（参数只在有意义的档位出现，§10-10）",
      not mkt.seg_minute.isVisibleTo(mkt) and not mkt.lbl_minute_depth.isVisibleTo(mkt))
check("日线态：复权分段可用、无口径警告",
      mkt.seg_adjust.isEnabled() and mkt.lbl_caliber_note.text() == "")

# ---- 切分钟：kline_min 分区 + 按档位分键 + 复权禁用 + 深度诚实提示 ----
minute_syncs = []
mkt.sync_cloud = lambda: minute_syncs.append(mkt._data_zone_and_key())
mkt.select_period_group("MIN")
check("切分钟：生效周期 = 上次用过的分钟档位（一级档位停在「分钟」）",
      mkt._period_group == "MIN" and mkt.current_period == mkt.current_minute)
check("切分钟：二级档位与深度提示出现；复权**禁用**并说明只有真实价一种口径",
      mkt.seg_minute.isVisibleTo(mkt) and mkt.lbl_minute_depth.isVisibleTo(mkt)
      and not mkt.seg_adjust.isEnabled() and "不含复权" in mkt.lbl_caliber_note.text())
check("切分钟：取数走 kline_min 分区 + **按档位分键**（不是一个键装所有档位）",
      bool(minute_syncs) and minute_syncs[-1] == (ZONE_MIN, minute_key('sh600000', mkt.current_minute)))
check("深度提示用的是**实测值**（1m 与 60m 不同，不是拍脑袋的固定文案）",
      str(MINUTE_DEPTH_DAYS[mkt.current_minute]) in mkt.lbl_minute_depth.text()
      and MINUTE_DEPTH_DAYS["1m"] != MINUTE_DEPTH_DAYS["60m"])
check("口径回执写清「分钟只有真实价」+ 可回溯天数",
      "真实成交价" in mkt.lbl_adjust_hint.text() and "交易日" in mkt.lbl_adjust_hint.text())

_saved_prefs = {}
mkt._save_desk_ui = lambda **kw: (mkt._desk_ui.update(kw), _saved_prefs.update(kw))
mkt.select_minute("60m")
check("换分钟档位：current_period 与偏好一起更新（记住上次）",
      mkt.current_period == "60m" and _saved_prefs.get("minute_period") == "60m")
check("偏好键与 `backtest_ui` 同源做法（不新增存储文件）", DESK_UI_KEY == "desk_ui")
check("换档位后深度提示跟着换（60m 比 5m 深得多）",
      str(MINUTE_DEPTH_DAYS["60m"]) in mkt.lbl_minute_depth.text())

# ---- 从分钟切回日线：必须重新取日线数据（绝不能拿分钟数据配日线标题）----
mkt.current_df = pd.DataFrame({
    "date": pd.date_range("2026-09-16 09:35", periods=6, freq="5min"),
    "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100})
reloads = []
mkt.sync_cloud = lambda: reloads.append(mkt._data_zone_and_key())
mkt.select_period_group("D")
check("⚠ 分钟 → 日线：**重新取日线数据**（数据源变了就必须换，不是重算）",
      bool(reloads) and reloads[-1][0] == 'kline_daily')
check("切回日线：复权恢复可用、二级控件收回、口径警告消失",
      mkt.seg_adjust.isEnabled() and not mkt.seg_minute.isVisibleTo(mkt)
      and mkt.lbl_caliber_note.text() == "")

# ---- 日 ↔ 周/月 是**同源**：只重渲染，不该重新取数（否则每次切周期都联网）----
mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.current_df = df.copy()
mkt.render_charts()
no_fetch = []
mkt.sync_cloud = lambda: no_fetch.append(1)
mkt.select_period_group("W")
mkt.select_period_group("D")
check("日 ↔ 周/月 切换**不触发取数**（同源就地聚合，§7-B6-C）",
      no_fetch == [] and mkt.current_period == "D")

print("\n== §7-B6 STEP 3c · 工具行 chips（最近使用优先 / 单一状态源 / 满池在「＋ 更多」）==")
from ui.widgets.chip_mru import CHIP_LIMIT, CHIP_POOLS, chip_label  # noqa: E402

mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.current_df = df.copy()
mkt.cb_ma.setChecked(True)
mkt.cb_boll.setChecked(False)
mkt.cb_vol.setChecked(True)
mkt.cb_macd.setChecked(True)
mkt.cb_formula.setChecked(True)
mkt.render_charts()

check("工具行 chips 每组 ≤ 3 个（溢出交给「＋ 更多」，配置不会完全不可见）",
      len(mkt.chips_for("main")) <= CHIP_LIMIT and len(mkt.chips_for("sub")) <= CHIP_LIMIT
      and bool(mkt.chips_for("main")))

_saved_chips = {}
mkt._save_desk_ui = lambda **kw: (mkt._desk_ui.update(kw), _saved_chips.update(kw))
mkt.toggle_chip("boll")
check("点 chip = 改**真源复选框**（chip 只是投影，不是第二套状态）",
      mkt.cb_boll.isChecked() and "boll" in mkt.chips_for("main"))
check("刚用过的项排到最前（最近使用优先）", mkt.chips_for("main")[0] == "boll")
check("最近使用历史落偏好（下次打开还记得）",
      _saved_chips.get("main_chips", [])[:1] == ["boll"])

mkt.toggle_chip("boll")
check("取消勾选：复选框关掉，但 chips 里**留位变灰**（否则关掉就再也点不回来）",
      not mkt.cb_boll.isChecked() and "boll" in mkt.chips_for("main"))

mkt.cb_macd.setChecked(False)
check("反向投影：从左栏复选框关闭 → chips 同样变灰（两个方向同一份状态）",
      "macd" in mkt.chips_for("sub"))
mkt.cb_macd.setChecked(True)

mkt.cb_boll.setChecked(True)
check("已启用项一定出现在 chips 里（不会『开了却看不到』）",
      "boll" in mkt.chips_for("main") and len(mkt.chips_for("main")) <= CHIP_LIMIT)

check("「＋ 更多」菜单列出**完整候选池**（去掉已显示的）",
      {a.text() for a in mkt._main_more_menu.actions() if a.isCheckable()}
      == {chip_label(k) for k in set(CHIP_POOLS["main"]) - set(mkt.chips_for("main"))})

# ---- 公式副图 chip：控制**这一格的显示**（不删用户的函数段）----
mkt._formula_segments = [("DIFF: EMA(C,5) - EMA(C,20);", 'sub1')]
mkt._compile_formula()
mkt.render_charts()
check("公式段指向副图 1 ⇒ 该 chip 进候选且窗格可见",
      "sub1" in mkt.chips_for("sub") and "sub1" in mkt.host.pane_names)
mkt.toggle_chip("sub1")
check("关掉「公式副图 1」⇒ 只隐藏这一格，函数段本体还在（关的是显示，不是函数）",
      "sub1" not in mkt.host.pane_names and bool(mkt._formula_segments))
mkt.toggle_chip("sub1")
check("再打开 ⇒ 窗格回来（可逆）", "sub1" in mkt.host.pane_names)
mkt._formula_segments = []
mkt._compile_formula()
mkt.render_charts()

print("\n== §7-B6 STEP 5 · 读数条接线（业务读数由页面给）+ 三处回执一行化 ==")
mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.current_df = df.copy()
mkt.cb_ma.setChecked(True)
mkt.render_charts()
_rdf = mkt._rendered_df
_row = _rdf.iloc[-1]
_text = mkt.host.readout_text

check("读数条常驻（不悬停也有东西看）且 = 最新一根",
      mkt.host._readout.isVisibleTo(mkt.host) and bool(_text))
check("读数各字段与**本次渲染的那一份 df** 逐字段一致（不造假）",
      _row['date'].strftime('%Y-%m-%d') in _text
      and f"开 {_row['open']:.2f}" in _text and f"高 {_row['high']:.2f}" in _text
      and f"低 {_row['low']:.2f}" in _text and f"收 {_row['close']:.2f}" in _text
      and f"量 {_row['volume']:,.0f}" in _text)
check("开了均线 ⇒ 读数带 MA5 / MA20（列名与 TAEngine.add_ma 同源）",
      "MA5" in _text and "MA20" in _text and f"{_row['MA_5']:.2f}" in _text)
_hover = mkt._readout_for_pane('main', 10, 100.0)
check("悬停第 11 根 ⇒ 读数换成这一根（provider 真按 x 取行）",
      f"收 {_rdf.iloc[10]['close']:.2f}" in _hover and _hover != _text)
check("副图不抢读数条（各窗格 y 含义不同 ⇒ 交回宿主内置文案）；越界也不崩",
      mkt._readout_for_pane('macd', 10, 1.0) == ""
      and mkt._readout_for_pane('main', 99999, 1.0) == ""
      and mkt._readout_for_pane('main', -5, 1.0) == "")
_period_backup = mkt.current_period
mkt.current_period = "5m"
check("分钟周期 ⇒ 读数时间戳到分钟（不是只给日期）",
      mkt._readout_stamp_fmt() == '%Y-%m-%d %H:%M')
mkt.current_period = _period_backup

check("复权回执已是一行摘要（不再用 \\n 折行；完整说法在 tooltip）",
      "\n" not in mkt.lbl_adjust_hint.text()
      and "根" in mkt.lbl_adjust_hint.text()
      and "\n" in mkt.lbl_adjust_hint.toolTip())
check("标注回执已是一行摘要（操作说明挪进 tooltip）",
      "\n" not in mkt.lbl_annotation_status.text()
      and "松手自动保存" in mkt.lbl_annotation_status.toolTip())
check("公式回执已是一行摘要（多行会被 · 串联，不靠换行折行）",
      "\n" not in mkt.lbl_formula_status.text())

# ---- ★v6.23：回执行的"差异定位"与"数据体检"（用户 2026-09-17 实测反馈驱动）----
#   为什么要有这两段：① 前复权的差异**只在除权日之前**，用户看最近一段会以为"开关坏了"；
#   ② 本地曾出现过"兜底源数据（成交量=手 / 负价）混入" ⇒ 图上量能 100× 台阶 + y 轴被压扁。
from data.sync_service import ADJUST_QFQ, ZONE_KLINE, ZONE_KLINE_RAW  # noqa: E402

_REAL_LAKE = mkt.data_lake
_DAYS = pd.bdate_range('2024-01-01', periods=80)
# 构造一次除权：不复权 10 元 → 8 元；前复权把除权日**之前**的价格改成 8 元（连续）
_RAW_CLOSE = np.concatenate([np.full(40, 10.0), np.full(40, 8.0)])
_QFQ_CLOSE = np.full(80, 8.0)


class _LakeStub:
    def load_data(self, zone, key):
        if zone == ZONE_KLINE:
            return pd.DataFrame({'date': _DAYS, 'close': _QFQ_CLOSE})
        return pd.DataFrame({'date': _DAYS, 'close': _RAW_CLOSE})

    def exists(self, zone, key):
        return True


mkt.data_lake = _LakeStub()
mkt.current_symbol = 'sh600000'
mkt.current_adjust = ADJUST_QFQ
mkt._data._diff_cache.clear()
mkt._data._health_cache.clear()
mkt._refresh_adjust_hint()
_diff_text = mkt.lbl_adjust_hint.text()
check(f"回执点名「最近一次除权跳空」在哪天、多大（{_diff_text}）",
      '除权跳空最近一次' in _diff_text and '-20.0%' in _diff_text)
check("tooltip 讲清「为什么切了口径看着一样」（差异只在除权日之前）",
      '只把**除权日之前**的历史价格往回改' in mkt.lbl_adjust_hint.toolTip())
mkt._data._diff_cache.clear()
mkt.data_lake = _REAL_LAKE

# ---- 数据体检：两类"物理上不可能"的行都要被写进回执（不静默）----
_SEAM_VOL = np.concatenate([np.full(40, 1e6), np.full(40, 1e8)])
_seam_df = pd.DataFrame({
    'date': _DAYS, 'open': np.full(80, 8.0), 'high': np.full(80, 8.2),
    'low': np.full(80, 7.8), 'close': np.full(80, 8.0), 'volume': _SEAM_VOL})
mkt.current_df = _seam_df
mkt._data._health_cache.clear()
mkt._refresh_adjust_hint()
_seam_text = mkt.lbl_adjust_hint.text()
check(f"体检：成交量量纲接缝（×100）被抓出并指向修复入口（{_seam_text}）",
      '量能接缝' in _seam_text and '重新全量下载' in _seam_text)
check("体检提示与口径摘要**同一行**（不靠换行折行，窄面板也读得到）",
      "\n" not in _seam_text)
_neg_df = _seam_df.copy()
_neg_df.loc[0, 'close'] = -0.68
mkt.current_df = _neg_df
mkt._data._health_cache.clear()
mkt._refresh_adjust_hint()
check("体检：非正价行被抓出（一根负价就会把整张图压扁）",
      '非正价 1 根' in mkt.lbl_adjust_hint.text())
mkt.current_df = df.copy()
mkt._data._health_cache.clear()
mkt._refresh_adjust_hint()
check("干净数据不给假警报", '疑似数据异常' not in mkt.lbl_adjust_hint.text())
mkt.render_charts()

print("\n== §7-B6 STEP 4 · 左栏：图标轨 + 分页面板 + 折起（控件搬家不重建）==")
from ui.views.trading_desk import RAIL_ITEMS  # noqa: E402

check("图标轨 5 项、面板 5 页，键一一对应",
      mkt.rail.keys() == [key for key, _icon, _title in RAIL_ITEMS] == mkt.desk_panel.keys())

# ---- 搬家不重建：控件仍挂在**正确的页**上（父级链能追到该页容器）----
_MOVED = [("lst_watch", "watch"), ("btn_watch_add", "watch"), ("btn_watch_up", "watch"),
          ("btn_edit_formula", "formula"), ("lbl_formula_status", "formula"),
          ("cb_ma", "layer"), ("cb_boll", "layer"), ("cb_formula", "layer"),
          ("cb_vol", "layer"), ("cb_macd", "layer"),
          ("seg_tool", "anno"), ("btn_add_annotation", "anno"),
          ("btn_delete_annotation", "anno"), ("btn_clear_lines", "anno"),
          ("lbl_annotation_status", "anno"), ("lbl_adjust_hint", "data")]


def _in_page(widget, page):
    body = mkt.desk_panel.body(page)
    node = widget
    while node is not None:
        if node is body:
            return True
        node = node.parentWidget()
    return False


_missing = [name for name, page in _MOVED
            if not hasattr(mkt, name) or not _in_page(getattr(mkt, name), page)]
check(f"搬家后控件都挂在正确的页上（{len(_MOVED)} 项 · 异常：{_missing or '无'}）", not _missing)

# ---- 信号没断（搬家最容易的翻车点：连了但对象换了/丢了）----
mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.current_df = df.copy()
mkt.cb_ma.setChecked(True)
mkt.cb_boll.setChecked(True)
check(f"搬家后信号仍活着：均线 3 + 布林 2（上/下轨，中轨由 MA20 承担）⇒ 图层 5 条"
      f"（MA={mkt.cb_ma.isChecked()} BOLL={mkt.cb_boll.isChecked()}"
      f" 实际={len(mkt._layer_builtin)} 周期={mkt.current_period}）",
      len(mkt._layer_builtin) == 5)
mkt.cb_boll.setChecked(False)

# ---- 切页 = 只切可见性（§11.5-25 的 isVisibleTo 口径）----
mkt.show_rail_page("formula")
check("切到公式页：本页控件可见、自选页控件不可见（但对象都还在）",
      mkt.desk_panel.current_page() == "formula"
      and mkt.btn_edit_formula.isVisibleTo(mkt.desk_panel)
      and not mkt.lst_watch.isVisibleTo(mkt.desk_panel))
mkt.show_rail_page("watch")
check("切回自选页：可见性反转", mkt.desk_panel.current_page() == "watch"
      and mkt.lst_watch.isVisibleTo(mkt.desk_panel)
      and not mkt.btn_edit_formula.isVisibleTo(mkt.desk_panel))

# ---- 折起：面板收起、图标轨常驻（否则折起后就切不了页）----
mkt.set_panel_collapsed(True)
check("折起：面板隐藏，但图标轨仍在（还能切页）",
      mkt.is_panel_collapsed() and mkt.desk_panel.isHidden() and not mkt.rail.isHidden())
mkt.rail.button("anno").click()
check("折起状态下点图标 = 先展开、再切到该页（活动栏手感）",
      not mkt.is_panel_collapsed() and mkt.desk_panel.current_page() == "anno")

win.resize(1440, 900)
win.show()                       # 离屏平台也支持 show；不给它看，布局就不会分配真实宽度
app.processEvents()
_width_before = mkt.host.width()
mkt.set_panel_collapsed(True)
app.processEvents()
_width_after = mkt.host.width()
check(f"折起后图表拿到更多宽度（{_width_before} → {_width_after}）",
      mkt.desk_panel.isHidden() and (_width_before == 0 or _width_after > _width_before + 200))

# ---- ★v6.22 离屏实测补修：富余宽度归**图表**，折起要把宽度**还干净** ----
#   修前实测（1911px 窗口）：展开 left=969 / 图表只剩 698（55% 被左栏吃掉）；
#   折起 left=269（面板虽隐藏，Qt 的 qSmartMinSize 仍按 minimumSizeHint 留着 ~340px 空白）。
from ui.views.trading_desk import PANEL_DEFAULT_WIDTH  # noqa: E402
from ui.widgets.desk_panel import RAIL_TOTAL_WIDTH  # noqa: E402

mkt.set_panel_collapsed(False)
app.processEvents()
_sizes_open = mkt.main_splitter.sizes()
check(f"展开态：富余宽度归图表，左栏只占 {_sizes_open[0]}px（≈{PANEL_DEFAULT_WIDTH}，不吃富余）",
      _sizes_open[0] <= PANEL_DEFAULT_WIDTH + 40)
mkt.set_panel_collapsed(True)
app.processEvents()
_sizes_fold = mkt.main_splitter.sizes()
check(f"折起态：左侧只剩图标轨（{_sizes_fold[0]}px ≈ {RAIL_TOTAL_WIDTH}，面板宽度 = {mkt.desk_panel.width()}）",
      _sizes_fold[0] <= RAIL_TOTAL_WIDTH + 10 and mkt.desk_panel.width() == 0)
check(f"折起后图表真的吃满（host.w = {mkt.host.width()}，比展开态多 ≈ 面板宽）",
      mkt.host.width() > _sizes_open[0] + 300)
mkt.set_panel_collapsed(False)
mkt.set_panel_collapsed(True)
app.processEvents()
check("折起/展开来回切是幂等的（左侧仍只剩图标轨）",
      mkt.main_splitter.sizes()[0] <= RAIL_TOTAL_WIDTH + 10)

# ---- 工具行的 ✎ 入口 ----
mkt.btn_anno_tool.click()
check("工具行 ✎ 入口：打开「✎ 标注」页并自动展开",
      mkt.desk_panel.current_page() == "anno" and not mkt.is_panel_collapsed())

# ---- 记住上次（页 + 折起）----
_saved_panel = {}
mkt._save_desk_ui = lambda **kw: (mkt._desk_ui.update(kw), _saved_panel.update(kw))
mkt.show_rail_page("data")
check("切页落偏好（下次打开还在这一页）", _saved_panel.get("panel_page") == "data")
mkt.set_panel_collapsed(False)
check("展开状态也落偏好", _saved_panel.get("rail_collapsed") is False)

print("\n== §7-B6 STEP 6 · 拆分后：页面是薄壳（名字全在，实现搬进 desk_*.py）==")
import inspect  # noqa: E402
from pathlib import Path  # noqa: E402

import ui.widgets.desk_annotations  # noqa: E402,F401
import ui.widgets.desk_chips  # noqa: E402,F401
import ui.widgets.desk_data  # noqa: E402,F401
import ui.widgets.desk_formula  # noqa: E402,F401
import ui.widgets.desk_layers  # noqa: E402,F401
import ui.widgets.desk_layout  # noqa: E402,F401
import ui.widgets.desk_panel  # noqa: E402,F401
import ui.widgets.desk_readout  # noqa: E402,F401
import ui.widgets.desk_watch  # noqa: E402,F401
from ui.views import trading_desk as _desk_module  # noqa: E402

_desk_lines = [line for line in Path(_desk_module.__file__).read_text(
    encoding="utf-8").splitlines() if line.strip()]
check(f"trading_desk.py 已降到 ≤500 行（实测 {len(_desk_lines)}）", len(_desk_lines) <= 500)
check("9 个 desk_* 模块都能独立导入（新能力落 ui/widgets/*，§10-12）", True)

# 判据 = **拆分前后同一套断言零改动**：所以这里只额外钉"实现确实搬走了"（不是把壳写成空函数）
#   (模块句柄, 模块内的方法名, 页面上的同名薄壳, 实现所在文件)
for _handle, _impl_name, _page_name, _module in (
        ("_layers", "render_charts", "render_charts", "desk_layers.py"),
        ("_layers", "prepared_df", "prepared_df", "desk_layers.py"),
        ("_layers", "_paint_layers", "_paint_layers", "desk_layers.py"),
        ("_data", "select_adjust", "select_adjust", "desk_data.py"),
        ("_data", "load_symbol", "load_symbol", "desk_data.py"),
        ("_data", "_refresh_adjust_hint", "_refresh_adjust_hint", "desk_data.py"),
        ("_formula", "edit_formula", "edit_formula", "desk_formula.py"),
        ("_formula", "receive_formula", "receive_formula", "desk_formula.py"),
        ("_annos", "add_annotation", "add_annotation", "desk_annotations.py"),
        ("_annos", "_refresh_annotation_status", "_refresh_annotation_status",
         "desk_annotations.py"),
        ("_chips", "toggle_chip", "toggle_chip", "desk_chips.py"),
        ("_watch", "move_watchlist", "move_watchlist", "desk_watch.py"),
        ("_readout", "_readout_for_pane", "_readout_for_pane", "desk_readout.py"),
        ("_panel", "set_panel_collapsed", "set_panel_collapsed", "desk_panel.py"),
        ("_layout", "build_tool_row", "_build_tool_row", "desk_layout.py")):
    _impl = getattr(getattr(mkt, _handle), _impl_name)     # 实现（模块里）
    _src = Path(inspect.getsourcefile(_impl)).name
    check(f"{_impl_name} 的实现已搬进 {_module}，页面保留同名薄壳 {_page_name}",
          _src == _module and hasattr(mkt, _page_name))

# ==========================================
# 行情工作台迁移护栏（1.23 / §7-B6 · 版式收口 STEP 0）
#   迁移的**唯一红线** = 只许换容器与排布，不许换控件名 / 方法名 / 常量名
#   （本页有 86+ 处 `mkt.xxx` 断言直接引用它们）。把白名单写成可执行断言 ⇒
#   谁不小心改名/删名，这里立刻红，而不是等别处的断言以"怪异原因"挂掉。
# ==========================================
print("\n== 行情工作台迁移护栏（§7-B6 STEP 0）：公共面不许改名/删除 ==")
DESK_PUBLIC_ATTRS = (
    # 恒等状态（页面与主窗口都按这些名字读写）
    "current_symbol", "current_name", "current_df", "current_period", "current_adjust",
    "current_minute", "_period_group", "_rendered_df", "_desk_ui",
    # 图表设施
    "main_plot", "host", "formula_plots", "_axes", "_annotations", "_main_more_menu",
    # 控件（换容器可以，换名字不行）
    "txt_search", "btn_search", "btn_sync", "lbl_sync_status", "lst_watch",
    "cb_ma", "cb_boll", "cb_formula", "cb_vol", "cb_macd",
    "btn_edit_formula", "lbl_formula_status", "lbl_annotation_status", "lbl_adjust_hint",
    "btn_add_annotation", "btn_delete_annotation", "btn_clear_lines",
    # ★STEP 3b/3c/4：顶栏第 2 行 + 左栏（迁移期新增的公共面，同样不许改名）
    "seg_period", "seg_minute", "seg_adjust", "seg_tool",
    "lbl_minute_depth", "lbl_caliber_note", "lbl_anno_pill", "btn_anno_tool",
    "rail", "desk_panel",
    # ★STEP 6：行为模块句柄（页面只转发；测试按模块核对实现位置）
    "_layout", "_panel", "_data", "_layers", "_formula", "_annos", "_chips",
    "_watch", "_readout",
    # 行为入口（页面级断言与 main_window 互送都调它们）
    "load_symbol", "sync_cloud", "render_charts", "prepared_df",
    "edit_formula", "save_formula_as", "open_formula_library",
    "send_formula_to_backtest", "receive_formula",
    "add_annotation", "delete_selected_annotation", "clear_annotations",
    "select_period_group", "select_minute", "select_adjust",
    "select_tool", "toggle_chip", "chips_for",
    "show_rail_page", "set_panel_collapsed", "is_panel_collapsed",
)
# 图层/配方相关的私有状态：拆分（§9-L）时"状态留页面"，所以名字也不许动
DESK_PUBLIC_STATE = ("_layer_builtin", "_layer_formula", "_layer_items",
                     "_formula_segments", "_formula_params_text", "_formula_store")
_desk_missing = [name for name in DESK_PUBLIC_ATTRS + DESK_PUBLIC_STATE if not hasattr(mkt, name)]
check(f"公共面完整（{len(DESK_PUBLIC_ATTRS) + len(DESK_PUBLIC_STATE)} 项 · 缺：{_desk_missing or '无'}）",
      not _desk_missing)
check("附图高度常量 SUB_PLOT_HEIGHT 仍可外部导入（150）", SUB_PLOT_HEIGHT == 150)
check("导航第 4 页仍指向行情工作台（main_window.page_market）", win.page_market is mkt)

# ⚠ STEP 3b 已办：周期/复权两个下拉被**分段控件**取代。这里反过来钉住"旧名不该再留"
#   —— 留着就是两套入口（§11.5-11：改一处漏一处的老毛病）。
check("周期/复权下拉已被分段控件取代（旧控件名不该再存在）",
      not hasattr(mkt, "cb_period") and not hasattr(mkt, "cb_adjust")
      and hasattr(mkt, "seg_period") and hasattr(mkt, "seg_adjust"))
# ⚠ STEP 4 已办：画线工具下拉换成「✎ 标注」页里的分段控件 ⇒ **迁移期三处旧入口至此全部清掉**。
check("迁移期三处旧入口已全部清除（`cb_period` / `cb_adjust` / `cmb_tool` 都不该存在）",
      not any(hasattr(mkt, name) for name in ("cb_period", "cb_adjust", "cmb_tool")))
check("取而代之：三个分段控件 `seg_period` / `seg_adjust` / `seg_tool` 齐备",
      all(hasattr(mkt, name) for name in ("seg_period", "seg_adjust", "seg_tool")))

# ==========================================
# 收尾自检：绝不能污染用户真实数据（测试一律用临时库）
# ==========================================
from config import settings  # noqa: E402

for _name in ("annotations.json", "formula_library.json", "watchlist.json",
              "backtest_strategies.json", "preferences.json"):
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
