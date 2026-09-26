# -*- coding: utf-8 -*-
"""「回测页 + 行情工作台」公式叠层 / 标注 / 配方 / 自选 / 周期 / 成交模型（§7-B5）的**页面级**验收（P3–P8）。

用法：py tests/smoke_pages_overlay.py  （在仓库根目录执行）
⚠ 会真实构造主窗口（打开 ~/.jian_data），请勿在 app 运行中同时跑。
⚠ 四条"离屏测试必备"的打桩（**缺一条就会表现为"卡住、无输出"，或写脏用户库**，见 §11.7）：
   ① **模态对话框打桩** —— `QMessageBox/QInputDialog` 在离屏环境没有用户可点，
      一旦弹出就是**永久阻塞**（历史事故：一条"浏览模式下点添加应给提示"的断言
      直接让脚本挂死）。
   ② **更新检查打桩** —— `UpdateCheckerThread` 会请求 GitHub；测试不该依赖网络。
   ③ 结尾用 `os._exit()` —— 只要还有非守护 QThread 存活，解释器就不退出；
      而 `| Select-Object -Last N` 会**缓冲到进程结束**才显示 ⇒ 表现为"长时间无响应"。
   ④ （v1.42 补）**异步回测也不许写真目录** —— 看到"只有几条真实数据类断言红"时，
      先问"有没有东西正在写"：本脚本的 §7-A4 `_on_rerun()` 会真起一次回测，它在
      **后面任意一段**转事件循环时才回包 ⇒ 策略库与自动存档都会写进真实
      `~/.jian_data/`（实测红过两次，红不红取决于时机）。正解 = 路径重定向到临时目录
      + 不把 `backtest_archive.auto` 还原成 True；后台下载同理（打桩 `download_hub.SyncWorker`）。
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

# ★v6.68：**真实库指纹**（跑前抓一次、跑完比一次）—— 见文件末尾自检处的长注释。
#   【为什么要有它】旧判据只看 mtime，会被**用户正在运行的应用**合法改写同一批文件 ⇒ **假红**
#   （本轮实测：应用开着时该断言 3 次里飘 2 次）。内容指纹能分清"被动过"与"被我们写过"。
_REAL_LIB_FILES = ("annotations.json", "formula_library.json", "watchlist.json",
                   "backtest_strategies.json", "preferences.json", "trade_calendar.json",
                   "scan_strategies.json", "industry_map.json")


def _real_lib_fingerprint() -> dict:
    """用户真实库里那批 JSON 的**内容指纹**（读不到/非法 JSON 一律记 None）。"""
    import json as _json

    from config import settings as _s
    out = {}
    for _n in _REAL_LIB_FILES:
        try:
            with open(os.path.join(_s.USER_DATA_DIR, _n), encoding="utf-8") as _f:
                out[_n] = _json.load(_f)
        except Exception:  # noqa: BLE001 —— 不存在 / 解析失败都算"没有内容"
            out[_n] = None
    return out


_REAL_LIB_SNAPSHOT = _real_lib_fingerprint()

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
# 重定向 + stub 保存前，`preferences` 单例已在 import 时从真实文件把 `desk_ui` 载入内存；
# ★v6.43（§7-B8 R7）新键 `sub_order` 会把行情页副图/draft 的**默认渲染顺序**冲掉
#   （早期那些「窗格顺序 = main/vol/macd/sub1/sub2」的老断言假设的就是默认序）。
# 与 §11.6「测试不许依赖用户真实偏好」同族：构造前先把这个用户态抹平，让窗口以默认序起来。
# ⚠ 必须在下面重定向 + stub `save` **之后**再改：否则 `set()` 会真写磁盘、污染用户库。

_pref_module.preferences.path = os.path.join(
    tempfile.mkdtemp(prefix="_tmp_pref_"), "preferences.json")
_pref_module.Preferences.save = lambda self: True

# 现在 set() 只改内存、save 已被 stub（写临时库）⇒ 把**用户态**的行情页视图键抹平，让窗口以默认形态起来。
# ★v6.64：除 `sub_order` 外**还必须抹 `layer_enabled`** —— 真实用过的用户库里会留着
#   **他自己钉的公式图层**（v6.64 实测：`["draft", "formula:0c701b24"]`），只抹 sub_order
#   会让行情页凭空多出窗格/图元 ⇒ 下面那些**假设默认形态**的老断言
#   （「窗格 = main/vol」「统一图元 = 3 内置 + 1 公式」…）**整片假红**，而且多出的公式层
#   会让该段中途卡死（实测跑不完、连汇总行都出不来）。
#   ⇒ 与本节 ③ 的初衷同族：**测试不许依赖用户真实偏好**（§11.6）。
_du = _pref_module.preferences.get("desk_ui")
if isinstance(_du, dict):
    _pref_module.preferences.set("desk_ui", {**_du, "sub_order": [], "layer_enabled": []})

# ★v6.68：`scan_ui` / `breadth_ui` 的 **`col_order`（列拖拽序）也必须抹掉** —— 它会让
#   「表头点击(视觉列) → 逻辑列」的映射**整体错位** ⇒ M2 的排序断言**稳定假红**：本轮实测
#   `on_header_clicked(10)` 之后 `_sort_col` 仍是 `None`（视觉 10 被映射成了**状态列** ⇒ 复位）。
#   与 §11.5-90 同族：**测试不许依赖用户真实偏好**（用户用得越久，冒烟越红）。
for _vk in ("scan_ui", "breadth_ui"):
    _cur_vk = _pref_module.preferences.get(_vk)
    if isinstance(_cur_vk, dict) and "col_order" in _cur_vk:
        _pref_module.preferences.set(
            _vk, {a: b for a, b in _cur_vk.items() if a != "col_order"})

# §7-A4：构造前关掉自动存档，避免任何测试回测写脏真实 ~/.jian_data/backtest_results/。
# （存档接线在下方用临时 root 直接测；真实目录仅可能被读，不会被写。）
_pref_module.preferences.set("backtest_archive", {"auto": False})

from core.formula.program import parse_program, execute_programs_with_draws  # noqa: E402
from ui.main_window import JianMainWindow  # noqa: E402
from ui.views.trading_desk import SUB_PLOT_HEIGHT  # noqa: E402

# §7-B10：M1 视图 __init__ 会自启 CalendarWorker（真实联网 + 写真实缓存）。
# 测试一律打桩为"不发线程、不联网、不改 date_end"，保住既有断言基线；
# 真实逻辑（_on_calendar / 滞后自动补 / 回退回执）在下节直接调 flow 方法测。
import ui.widgets.backtest_flow as _btflow  # noqa: E402  （用唯一别名，避开中部 `_bflow`=breadth_flow 重绑）
import ui.widgets.readiness_flow as _rflow0  # noqa: E402  （§7-B10：M2/M3 两页构页也自启 CalendarWorker）


class _StubSig:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)


class _StubCalendarWorker:
    def __init__(self, parent=None):
        self.finished_signal = _StubSig()

    def start(self):        # 不启真实线程
        pass


_btflow.CalendarWorker = _StubCalendarWorker
_rflow0.CalendarWorker = _StubCalendarWorker   # 两页起日历线程也不联网（trading_target 保持 None → 不提示滞后）

app = QApplication.instance() or QApplication([])
win = JianMainWindow()
view = win.page_backtest.single_view

# ==========================================
# 打桩 ④（v1.42 补）：**策略库与自动存档也不许写真实目录**
#   §7-A4 的 `_on_rerun()` 会真起一次异步回测，而它在**后面任意一段**转事件循环时
#   才回包 ⇒ `StrategyBridge.record()` 写真实 `backtest_strategies.json`；
#   若那时 `backtest_archive.auto` 又被还原成 True，还会往真实 `backtest_results/`
#   落一份快照。实测：收尾自检 2 红，且**红与不红取决于那次异步回测有没有在
#   脚本结束前跑完** —— 竞态型污染（§11.5-79 同族：只有几条“真实数据类”断言红时，
#   先问“有没有东西正在写”）。与 annotations / formula_library / watchlist 同处理：
#   把落盘路径重定向到临时目录，断言口径不变。
# ==========================================
_GUARD_DIR = tempfile.mkdtemp(prefix="jian_guard_")
view.store.path = os.path.join(_GUARD_DIR, "backtest_strategies.json")

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


# ★v6.24（§7-B8 R13）：图层开关的**唯一真源**已从 5 个 QCheckBox 换成 `mkt.layer_model`。
#   ⚠ 旧写法 `_layer("ma", True)` 之所以"顺手重渲染"，是因为 QCheckBox 的
#     `stateChanged` 连着回流；换真源之后**那个信号不存在了** ⇒ 测试也必须显式走同一条
#     回流路径，否则会写出"改了状态但图没动"的**假测试**（最坏的一类：它绿着，功能是坏的）。
def _layer(key, on=True):
    if str(key) == "formula":
        mkt._compile_formula()      # 确保草稿槽已在模型里（测试常直接赋值 _formula_segments）
        key = "draft"
    mkt.layer_model.set_enabled(key, on)
    mkt._on_layer_switch_changed()


mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.current_df = df                      # 复用上面的合成行情
_layer("ma", True)
_layer("boll", False)
_layer("volume", True)
_layer("macd", False)
_layer("formula", True)
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
_layer("formula", False)
check("关掉公式后只剩内置图层（3 条）", len(mkt._layer_items) == 3
      and all(it.__class__.__name__ != '_StickItem' for it in mkt._layer_items))
_layer("formula", True)
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
_layer("macd", True)          # 触发一次重渲染（与用户点开关等价）
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

_layer("formula", False)
check("关掉开关后公式副图全部消失", mkt.formula_plots == {}
      and mkt.host.pane_names == ['main', 'vol', 'macd'])
_layer("formula", True)
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
_layer("ma", True)          # 触发一次完整重渲染（含标注 bind）
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
_layer("boll", True)
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
from data.annotations import (KIND_FIB, KIND_TEXT, AnnotationStore,  # noqa: E402
                              price_text, regression_channel, requires_text)
from data.watchlist_store import WatchlistStore  # noqa: E402
from core.utils import resample_ohlcv  # noqa: E402
from ui.widgets.annotation_layer import DRAWABLE_KINDS  # noqa: E402

# ⚠ 同样用**临时库**：自选股与标注都不碰用户真实文件
tmp_p8 = tempfile.mkdtemp(prefix="jian_p8_")
mkt.watchlist = WatchlistStore(os.path.join(tmp_p8, "watchlist.json"))
# ★ 换库之后必须**同时**归零筛选条件并重刷目标分组下拉 ——
#   否则「目标分组」还是拿**上一个库（= 用户真实库）**的分组名填的，
#   于是断言结果取决于"用户真实库里有没有那个分组"（本套件真红过：
#   用户库里有个「红利组合」，新增就落到它名下 ⇒ 清单被筛成 1 条）。
#   ⚠ 这正是 §11.7 那条纪律的另一面：**测试不只不能写脏用户库，也不能读它当依据**。
mkt.watch_group = None
mkt._refresh_watchlist()
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
check(f"列表条数与库一致（库={mkt.watchlist.symbols()} 组={mkt.watch_group!r} "
      f"列表={mkt.lst_watch.count()}）", mkt.lst_watch.count() == 2)

mkt.lst_watch.setCurrentRow(1)
mkt.move_watchlist(-1)
check(f"上移改变顺序（顺序 = 用户关注顺序；实={mkt.watchlist.symbols()}）",
      mkt.watchlist.symbols()[0] == 'SZ000001')
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
check(f"移除选中项（库与列表同步；实 库={mkt.watchlist.count()} 列表={mkt.lst_watch.count()}）",
      mkt.watchlist.count() == 1 and mkt.lst_watch.count() == 1)

# ==========================================
# ★ §7-B8 R1/R2/R3（v6.24）：自选分组 / 两种添加入口 / 移出本组
# ==========================================
from data.watchlist_store import DEFAULT_GROUP  # noqa: E402
from ui.widgets.custom_widgets import AddChip, GroupChip  # noqa: E402

mkt.show_rail_page("watch")
_watch_body = mkt.desk_panel.body("watch")
check("自选页按 A 方案重排：添加卡 / 分组卡 / 清单卡 / 预留位 / 分组管理都在自选页内",
      all(_watch_body.isAncestorOf(w) for w in (
          mkt.card_watch_add, mkt.card_watch_groups, mkt.card_watch_list,
          mkt.lbl_watch_planned, mkt.card_watch_manage)))
check("分组管理默认**收起**（影响结构的动作不摊在日常动线里），添加卡片默认展开",
      not mkt.card_watch_manage.is_open() and mkt.card_watch_add.is_open())

mkt.card_watch_groups.set_open(False)
check("手风琴收起：内容隐藏但**卡头仍在**（收起后卡头就是唯一可见的状态行）",
      mkt.card_watch_groups.is_open() is False
      and not mkt.watch_chip_host.isVisibleTo(mkt.card_watch_groups)
      and mkt.card_watch_groups.title.isVisibleTo(mkt.card_watch_groups))
mkt.card_watch_groups.set_open(True)
check("再展开 ⇒ 内容回来（折叠可逆）",
      mkt.card_watch_groups.is_open() and mkt.watch_chip_host.isVisibleTo(mkt.card_watch_groups))


def _chip_widgets():
    return [mkt.watch_chip_lay.itemAt(i).widget()
            for i in range(mkt.watch_chip_lay.count())]


def _group_chips():
    return [w for w in _chip_widgets() if isinstance(w, GroupChip)]


mkt.watchlist.add('600519', '贵州茅台')
mkt.watchlist.create_group('核心白马')
mkt._refresh_watchlist()
_chip_keys = [chip.key for chip in _group_chips()]
check("分组胶囊每次从 store **重建**：「全部」在前 + 默认分组 + 新建的空组（空组也要看得见）",
      _chip_keys[0] is None and set(_chip_keys[1:]) == {DEFAULT_GROUP, '核心白马'})
check("「＋ 新建分组」胶囊在同一条动线里（虚线边 = 与真实分组一眼区分）",
      any(isinstance(w, AddChip) for w in _chip_widgets()))
check("目标分组下拉与胶囊**同源**（都来自 store.groups()，不存第二份状态）",
      [mkt.cmb_watch_group.itemData(i) for i in range(mkt.cmb_watch_group.count())]
      == mkt.watchlist.groups())
check("卡头即状态：分组卡写着「N 组 · M 只」，清单卡写着当前组名与只数",
      "组" in mkt.card_watch_groups.state_text()
      and "只" in mkt.card_watch_list.title_text())

mkt.watch_group_selected('核心白马')
check("点分组胶囊 ⇒ 清单只显示该组成员（空组 = 0 条，既不崩也不隐藏）",
      mkt.watch_group == '核心白马' and mkt.lst_watch.count() == 0)
mkt.watch_group_selected(None)
check("切回「全部」⇒ 清单恢复全部成员",
      mkt.watch_group is None and mkt.lst_watch.count() == mkt.watchlist.count())

# 快添加：把"名称 → 代码"的解析换成假函数（测试不碰真花名册、更不联网）
_saved_resolver = mkt._watch._resolve_keyword
mkt._watch._resolve_keyword = lambda keyword: (('600519', '贵州茅台')
                                              if keyword == '茅台' else ('', ''))
mkt.txt_watch_quick.setText('茅台')
mkt.cmb_watch_group.setCurrentIndex(mkt.cmb_watch_group.findData('核心白马'))
mkt.add_to_watchlist()
check("★ 快添加：输入名称 → 解析成代码 → 进**下拉选中的分组**，并自动切到该组",
      mkt.watchlist.group_of('600519') == '核心白马' and mkt.watch_group == '核心白马'
      and mkt.lst_watch.count() == 1 and mkt.txt_watch_quick.text() == '')
check("快添加：查不到的词返回空（由调用方提示，**不静默塞一个错代码**进自选）",
      mkt._watch._resolve_keyword('查无此票') == ('', '') and mkt.watchlist.count() == 2)
mkt._watch._resolve_keyword = _saved_resolver

mkt.lst_watch.setCurrentRow(0)
check("按钮文字随上下文变：正在看某个分组 ⇒ 「移出本组」",
      mkt.btn_watch_remove.text() == '↗ 移出本组')
mkt.remove_from_watchlist()
check("★ 「移出本组」只解绑归类：票**仍留在自选里**，只是回到默认分组",
      mkt.watchlist.count() == 2 and mkt.watchlist.group_of('600519') == DEFAULT_GROUP
      and mkt.lst_watch.count() == 0)
mkt.watch_group_selected(None)
check("切回「全部」⇒ 按钮变成「移除」（同一个按钮、按上下文换含义）",
      mkt.btn_watch_remove.text() == '🗑 移除' and mkt.lst_watch.count() == 2)

mkt.watch_group_selected(DEFAULT_GROUP)
mkt.rename_watch_group()
check("默认分组不可改名（点了只给回执，不弹输入框）",
      mkt.watch_group == DEFAULT_GROUP and mkt.watchlist.count() == 2)
mkt.delete_watch_group()
check("★ 默认分组不可删（它是所有解绑动作的落点；点了也不会弹确认框）",
      mkt.watchlist.has_group(DEFAULT_GROUP) and mkt.watchlist.count() == 2)
mkt.watch_group_selected(None)
mkt.rename_watch_group()
check("「全部」不可改名（它是聚合视图，不是真实分组）", mkt.watch_group is None)

# ---- ★ §7-B8 R3：组合当日涨跌（等权 + 缺数据不算 + ⚠）----
from data.sync_service import ADJUST_NONE, ADJUST_QFQ  # noqa: E402
from data.watchlist_change import ChangeSnapshot  # noqa: E402
from ui.widgets.custom_widgets import CHIP_VALUE_NEUTRAL, CHIP_VALUE_UP  # noqa: E402

_BARS = {
    'SH600000': [('2026-09-16', 10.0), ('2026-09-17', 10.5)],      # +5.00%
    'SZ000001': [('2026-09-16', 20.0), ('2026-09-17', 19.6)],      # −2.00%
    '600519':   [('2026-09-16', 100.0), ('2026-09-17', 100.0)],    # 0.00%（平）
}


def _fake_loader(symbol):
    """假日线：不在表里的票返回空表 ⇒ 走"没有行情数据"那条缺失分支（不碰真库、不联网）。"""
    bars = _BARS.get(symbol) or []
    return pd.DataFrame({'date': [d for d, _c in bars], 'close': [c for _d, c in bars]})


def _chip_by_key(key):
    return next((chip for chip in _group_chips() if chip.key == key), None)


mkt.watchlist.clear()
mkt.watchlist.add('SH600000', '测试股')
mkt.watchlist.add('SZ000001', '平安银行')
mkt.watchlist.add('600519', '贵州茅台')
mkt.watchlist.add('300750', '宁德时代')       # 没有行情数据 ⇒ 该打 ⚠
mkt.watch_group = None
mkt.watch_change = ChangeSnapshot(_fake_loader, ttl_seconds=600)
mkt._refresh_watchlist()

check("「全部」是聚合视图：**显示只数、不显示涨跌**（与样板一致，也免得胶囊虚胖）",
      _chip_by_key(None).count_text() == "4 只" and _chip_by_key(None).value_text() == "")

_all_chip = _chip_by_key(DEFAULT_GROUP)
check("★ 组合当日涨跌（等权）：(−2.00% + 0.00% + 5.00%) / 3 = +1.00%（**缺数据那只不进分母**）",
      _all_chip is not None and _all_chip.value_text() == "+1.00%")
check("★ 明确排除「按 0% 冲淡」那个错值（4 只全算会是 +0.75%）",
      _all_chip.value_text() != "+0.75%")
check("涨用绿（与 K 线涨色同源）", _all_chip.value_color() == CHIP_VALUE_UP)
check("⚠ 打在胶囊上，tooltip 说得出「是哪一只、为什么」",
      _all_chip.warn_text() == "⚠" and "宁德时代" in _all_chip.warn_tooltip()
      and "没算进去" in _all_chip.warn_tooltip())
check("卡头也写组合涨跌（**收起时照样看得见**）",
      mkt.card_watch_list.state_text() == "组合 +1.00%")
check("有票缺数据 ⇒ 卡头转**警示色**（不是假装一切正常）",
      mkt.card_watch_list.state_kind() == "warn")

mkt.watchlist.create_group('上涨组')
mkt.watchlist.create_group('平盘组')
mkt.watchlist.create_group('空组')
mkt.watchlist.set_group('SH600000', '上涨组')
mkt.watchlist.set_group('600519', '平盘组')
mkt._refresh_watchlist()
check("单票组 = 该票自己的涨跌",
      _chip_by_key('上涨组').value_text() == "+5.00%"
      and _chip_by_key('上涨组').value_color() == CHIP_VALUE_UP)
check("★ 平盘（0.00%）用**中性灰** —— 把「平」画成绿会让人以为它在涨",
      _chip_by_key('平盘组').value_text() == "0.00%"
      and _chip_by_key('平盘组').value_color() == CHIP_VALUE_NEUTRAL)
check("空组 ⇒ **不写 0.00%**（一只都没算出来），只显示「0 只」",
      _chip_by_key('空组').value_text() == "" and _chip_by_key('空组').count_text() == "0 只")
check("这一组没有缺数据的票 ⇒ 不打 ⚠", _chip_by_key('上涨组').warn_text() == "")

mkt.current_adjust = ADJUST_NONE          # 顶部切到"不复权"
mkt._refresh_watchlist()
check("★ 组合涨跌固定读**前复权**日线，与顶部「复权」选择无关（那个只管图上给你看哪一份）",
      _chip_by_key('上涨组').value_text() == "+5.00%")
mkt.current_adjust = ADJUST_QFQ

check("快照在两次刷新之间被复用（不是每次刷新都重读 N 份日线）",
      mkt.watch_change.cached_count() == 4)
mkt.invalidate_change_cache()
check("同步完成后快照失效（否则 TTL 内会拿同步前的旧读数当今天）",
      mkt.watch_change.cached_count() == 0)
mkt._refresh_watchlist()
check("失效后刷新会重新算（缓存重新长出条目）", mkt.watch_change.cached_count() == 4)

# ---- ★ §7-B8 R2：第二种添加入口「📋 从自选股里挑选…」----
from ui.dialogs.watchlist_picker import WatchlistPickerDialog  # noqa: E402

check("「从自选股里挑选…」按钮在**添加卡片**里（与快添加同一条动线）",
      mkt.card_watch_add.isAncestorOf(mkt.btn_watch_pick)
      and mkt.btn_watch_pick.isVisibleTo(mkt.card_watch_add))

_picker = WatchlistPickerDialog(entries=mkt.watchlist.entries_all(),
                                groups=mkt.watchlist.groups(),
                                current_group=DEFAULT_GROUP, parent=mkt)
check("弹窗列出**全部自选**（不是只有当前分组）—— 整理分组时必须能跨组挑",
      _picker.list_widget.count() == mkt.watchlist.count() == 4)
check("弹窗的目标下拉与分组胶囊**同源**",
      [_picker.cmb_group.itemData(i) for i in range(_picker.cmb_group.count())]
      == mkt.watchlist.groups())
check("没选任何一只时「移入」是灰的（点了什么都不做的按钮最让人困惑）",
      _picker.selected_symbols() == [] and not _picker.btn_move.isEnabled())

_picker.list_widget.setCurrentRow(0)
_picker.list_widget.item(2).setSelected(True)
check("多选生效，且按钮上写着「选了几只」（用户不必猜）",
      len(_picker.selected_symbols()) == 2 and _picker.btn_move.isEnabled()
      and "2 只" in _picker.btn_move.text())
_picker.cmb_group.setCurrentIndex(_picker.cmb_group.findData('空组'))
check("弹窗只回答「选了哪些 / 移到哪」，**自己不落库**",
      _picker.target_group() == '空组' and mkt.watchlist.group_of('SH600000') == '上涨组')

_moved = mkt.move_selected_to_group(_picker.selected_symbols(), _picker.target_group())
check("★ 批量移入：条数正确，且票**一只都没少**（只改归类，绝不删票）",
      _moved == 2 and mkt.watchlist.count() == 4
      and set(mkt.watchlist.symbols_in('空组')) == set(_picker.selected_symbols()))
check("移完**自动切到目标分组**（否则「移进去了却看不见」）",
      mkt.watch_group == '空组' and mkt.lst_watch.count() == 2)
check("★ 已在目标组里的票不会被重复计数（幂等，不产生假回执）",
      mkt.move_selected_to_group(['SH600000'], '空组') == 0)

mkt.watch_group_selected(None)
check("回到「全部」视图：4 只一只不少", mkt.lst_watch.count() == 4)

# ---- ★ §7-B8 R15 / 2b 余项：自选行的三段式绘制（名称 · 代码右对齐 · 涨跌列）----
import pandas as _pd  # noqa: E402
from PyQt6.QtCore import QRect  # noqa: E402
from PyQt6.QtGui import QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QStyleOptionViewItem  # noqa: E402

from data.watchlist_change import ChangeSnapshot  # noqa: E402
from ui.widgets.watch_row_delegate import (DIR_UNKNOWN, DIR_UP, ROLE_SYMBOL,  # noqa: E402
                                           WatchRowDelegate, change_of)


def _bars(pct):
    return _pd.DataFrame({"date": ["2026-09-16", "2026-09-17"],
                          "close": [100.0, 100.0 * (1 + pct / 100.0)]})


mkt.watch_change = ChangeSnapshot(
    lambda symbol: _bars(2.5) if symbol == "600519" else _pd.DataFrame())
mkt._refresh_watchlist()
_rows = {mkt.lst_watch.item(i).data(ROLE_SYMBOL): change_of(mkt.lst_watch.item(i))
         for i in range(mkt.lst_watch.count())}
check("★ 行右侧带涨跌列：有数据的行 =「+2.50%」（方向=涨）",
      _rows.get("600519") == ("+2.50%", DIR_UP))
check("★ 没数据的行写「—」（**绝不是 0.00%** —— 没数据就说没数据，§10-4）",
      all(value == ("—", DIR_UNKNOWN) for key, value in _rows.items() if key != "600519"))

check("用 delegate 而非 setItemWidget（后者会把**选中高亮**盖掉）",
      isinstance(mkt.lst_watch.itemDelegate(), WatchRowDelegate)
      and mkt.watch_row_delegate.sizeHint(
          QStyleOptionViewItem(), mkt.lst_watch.model().index(0, 0)).height() == 27)

# 真画一行进 pixmap：绘制路径的冒烟 + 量"三段各自落了墨"
_pix = QPixmap(300, 27)
_pix.fill(Qt.GlobalColor.transparent)
_painter = QPainter(_pix)
_option = QStyleOptionViewItem()
_option.rect = QRect(0, 0, 300, 27)
_option.font = mkt.font()
mkt.watch_row_delegate.paint(_painter, _option, mkt.lst_watch.model().index(0, 0))
_painter.end()
_image = _pix.toImage()


def _inked(x0, x1):
    return any(_image.pixelColor(x, 13).alpha() > 0 for x in range(x0, x1))


check("★ 一行真的画出来了：左侧名称段有墨 + 最右涨跌列有墨（右对齐列真的存在）",
      _inked(0, 120) and _inked(300 - 56 - 10, 300))


def _watch_order():
    return [mkt.lst_watch.item(i).data(ROLE_SYMBOL) for i in range(mkt.lst_watch.count())]


# ---- ★ §7-B8 R15：拖拽排序（三道闸防误触）----
from PyQt6.QtCore import QModelIndex, QPoint  # noqa: E402
from PyQt6.QtWidgets import QAbstractItemView  # noqa: E402

from ui.widgets.watch_sort_list import HANDLE_WIDTH  # noqa: E402

mkt.watch_group_selected("空组")
mkt._refresh_watchlist()
check("★ 闸 1：平时列表**根本不响应拖动**（`NoDragDrop` ⇒ 浏览时手滑不会改任何顺序）",
      mkt.lst_watch.is_sort_mode() is False
      and mkt.lst_watch.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
      and mkt.lst_watch.acceptDrops() is False)

mkt.set_watch_sort_mode(True)
check("★ 进排序模式：切成 InternalMove + 出现提示条与「撤销 / 完成」",
      mkt.lst_watch.is_sort_mode() and mkt.watch_sort_mode
      and mkt.lst_watch.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove
      and mkt.watch_sort_bar.isVisibleTo(mkt.card_watch_list)
      and mkt.watch_row_delegate.is_sort_mode())
check("★ 边缘自动滚动 + 落位提示线都开着（大列表这两条缺一不可）",
      mkt.lst_watch.hasAutoScroll() and mkt.lst_watch.autoScrollMargin() == 24
      and mkt.lst_watch.showDropIndicator())

# 闸 2 的命中判定：直接量"按下点算不算落在手柄带里"（不依赖窗口是否真的显示出来）
_item_at, _item_rect = mkt.lst_watch.itemAt, mkt.lst_watch.visualItemRect
mkt.lst_watch.itemAt = lambda point: mkt.lst_watch.item(0)
mkt.lst_watch.visualItemRect = lambda item: QRect(0, 0, 250, 27)
check("★ 闸 2 的命中判定：落行首手柄带 ⇒ 能拖；落行本体 ⇒ 不拖（两个热区物理分开）",
      mkt.lst_watch._hit_handle(QPoint(HANDLE_WIDTH - 2, 13)) is True
      and mkt.lst_watch._hit_handle(QPoint(HANDLE_WIDTH + 40, 13)) is False)
mkt.lst_watch.itemAt, mkt.lst_watch.visualItemRect = _item_at, _item_rect

mkt.lst_watch._drag_armed = False
mkt.lst_watch.startDrag(Qt.DropAction.MoveAction)
check("★ 闸 2：不是从 ⣿ 起的拖 ⇒ `startDrag` **直接吞掉**（什么都不发生，也不报错）",
      mkt.lst_watch.is_drag_armed() is False)

# 用 `moveRow` 真模拟一次"拖拽结束后的行移动"，再走落盘入口
_sort_group = mkt.watch_group
_order_before = mkt.watchlist.symbols_in(_sort_group)
mkt.lst_watch.model().moveRow(QModelIndex(), 0, QModelIndex(), 2)
_after_drag = [mkt.lst_watch.item(i).data(ROLE_SYMBOL)
               for i in range(mkt.lst_watch.count())]
check("模拟一次行移动：列表顺序确实变了（与底片不同）", _after_drag != _order_before)

mkt.apply_watch_sort()
check("★ 拖拽结束才落盘：把**当前列表顺序**写回 store（只在本组内重排）",
      mkt.watchlist.symbols_in(_sort_group) == _after_drag)
check("★ 其它分组一格不动（拖拽不会顺手改分组）",
      mkt.watchlist.symbols_in(DEFAULT_GROUP)
      == [entry["symbol"] for entry in mkt.watchlist.entries_in(DEFAULT_GROUP)])

mkt.undo_watch_sort()
check("★ 闸 3：撤销 ⇒ 回到**进排序模式之前**的顺序，并退出排序模式",
      mkt.watchlist.symbols_in(_sort_group) == _order_before
      and mkt.watch_sort_mode is False and not mkt.lst_watch.is_sort_mode()
      and not mkt.watch_sort_bar.isVisibleTo(mkt.card_watch_list)
      and not mkt.watch_row_delegate.is_sort_mode())

mkt.watch_group_selected(None)
mkt.set_watch_sort_mode(True)
check("★ 「全部」视图**拒绝**进排序模式（跨组拖动等于顺手改分组）：按钮回弹 + 说明原因",
      mkt.watch_sort_mode is False and not mkt.btn_watch_sort.isChecked()
      and "先选一个分组" in mkt.card_watch_list.state_text())
mkt.watch_group_selected(None)

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
from ui.widgets import annotation_catalog  # noqa: E402

check("★ 画线类型目录：32 种 / 6 类全部直出（**无搜索栏、不折叠**）",
      len(mkt.anno_tiles) == annotation_catalog.TOTAL == 32
      and len(mkt.anno_headers) == len(annotation_catalog.CATEGORIES) == 6)
check("★ 目录里标「已实现」的，必须**真的能画**（双向一致 —— 说能画却画不出就是骗人）",
      {key for key, entry in mkt.anno_tiles.items() if entry.implemented}
      == set(DRAWABLE_KINDS)
      and {e["kind"] for e in annotation_catalog.implemented_entries()} == set(DRAWABLE_KINDS))
check("★ 未实现的照常出现并**标注「待实现」**（不静默、也不假装能用）",
      all(tile.todo_text() == "" for tile in mkt.anno_tiles.values() if tile.implemented)
      and sum(1 for tile in mkt.anno_tiles.values() if tile.todo_text() == "待实现")
      == annotation_catalog.TOTAL - len(DRAWABLE_KINDS))
check("★ 面板高度**不随类型数增长**（目录最小高 + 放不下就内部滚动，外层内容区兜底）",
      mkt.anno_scroll.minimumHeight() == 320
      and mkt.anno_scroll.verticalScrollBar().maximum() > 0)
check("★ 每类一个色相（色相是「让 32 种不乱」最关键的一条）",
      len({header.color for header in mkt.anno_headers.values()})
      == len(mkt.anno_headers) == 6)

# 选中态是**投影**：真源是 `current_tool`，tile 跟着它走
mkt.select_tool(KIND_FIB)
check("★ 选中态只是投影：真源 `current_tool` + tile 高亮同源",
      mkt.current_tool == KIND_FIB and mkt.anno_tiles[KIND_FIB].is_selected()
      and not mkt.anno_tiles[KIND_TREND].is_selected())
mkt.select_tool_number(1)
check("★ 数字快捷键 1 ⇒ 目录里编号 1 的类型（趋势线）",
      mkt.current_tool == KIND_TREND and mkt.anno_tiles[KIND_TREND].is_selected())
mkt.select_tool_number("不是数字")
check("非法快捷键输入不炸也不改状态", mkt.current_tool == KIND_TREND)

# ★ 点不动的类型：**必须有话说**（§9-Q：不静默）
#   ⚠ 两条纪律都得守：① **不许写死"哪个类型没实现"**（写死的下场 = 扩容那天变假失败，
#   同 §11.5-34）；② **也不能假设"一定有未实现的"**（v6.26 32 种全部做完后就真没有了）。
_todo = [e["kind"] for e in annotation_catalog.ENTRIES if not e["implemented"]]
if _todo:
    mkt.select_tool(_todo[0])
    check("★ 点到未实现的类型 ⇒ 明确告知「还没实现」（连同它归在哪一类 / 编号几）",
          "还没实现" in mkt.lbl_annotation_status.text()
          and mkt.current_tool == KIND_TREND          # 工具没被切走
          and not mkt.anno_tiles[_todo[0]].is_selected())
else:
    mkt.select_tool("__no_such_kind__")               # 目录外的假类型：同样不许静默
    check("★ 目录里没有待实现项时（32 种全通），点目录外的类型也要有话说",
          "不能用" in mkt.lbl_annotation_status.text()
          and mkt.current_tool == KIND_TREND)
mkt.select_tool(KIND_TREND)

# ---- v6.26：32 种**逐个**走一遍"选类型 → 在图上点出来 → 删掉"（目录不许骗人）----
from ui.widgets.annotation_shapes import DRAWABLE_KINDS, spec_of  # noqa: E402


def draw_by_clicks(kind, prices=None):
    """等价用户"选类型 → 在图上依次点锚点"（§7-B9 STEP 1 的主路径）。

    :return: `(落库的标注, 首个锚点的期望值)`；`prices` 缺省按**当前可视区间**取几个位置。
    ⚠ 锚点必须落在**可视区**内（页面上的真实用户只会点看得见的地方），且彼此**拉开距离**
    （回归通道这种"框选区间"的类型，点挤在同一根 bar 上是退化情形 ⇒ 画不出来）。
    """
    spec = spec_of(kind)
    size = max(mkt._annotations._axis.size, 1)
    (vx0, vx1), (vy0, vy1) = mkt.host.main_pane.view_box.viewRange()
    span_x = max(float(vx1) - float(vx0), 1e-9)
    span_y = max(float(vy1) - float(vy0), 1e-9)
    prices = list(prices or []) or [float(vy0) + span_y * fraction
                                    for fraction in (0.45, 0.62, 0.30, 0.75, 0.20)]
    mkt.select_tool(kind)
    item, first = None, None
    for index in range(spec.points):
        position = float(vx0) + span_x * (0.05 + 0.13 * index)
        date_label = mkt._annotations._axis.index_to_date(round(position))
        if first is None:
            first = (date_label, prices[index])
        item = mkt._annotations._session.on_click(date_label, prices[index])
    return item, first


# 主图元**价格由算出来**的类型：回归通道的中线 = 对收盘价回归的结果（不是点击时的价）
_DERIVED_Y = {"reg_channel"}

_drawn_ok, _composite_ok, _failed = True, True, []
for _kind in DRAWABLE_KINDS:
    mkt._annotations.clear_all()
    # 需要用户填文字的类型（文字 / 评论气泡）走打桩的输入框，**别让断言真去弹窗**
    if requires_text(_kind):
        ANSWERS.append("测试输入")
    _item, _first = draw_by_clicks(_kind)
    _graphic = mkt._annotations._items.get(_item["id"]) if _item else None
    if _item is None or _graphic is None:
        _drawn_ok, _failed = False, _failed + [_kind]
        continue
    # 落库坐标必须就是**点击处**的日期 + 价（不是什么"默认落点"）
    _date_ok = _item["points"][0][0] == _first[0]
    if _kind in _DERIVED_Y:
        _xs = sorted([mkt._annotations._axis.date_to_index(p[0])
                      for p in _item["points"][:2]])
        _fit = regression_channel(mkt._annotations._closes, _xs[0], _xs[1])
        _price_ok = _fit is not None and abs(_item["points"][0][1] - _fit["start"]) < 1e-6
    else:
        _price_ok = abs(_item["points"][0][1] - _first[1]) < 1e-6
    if not (_date_ok and _price_ok):
        _drawn_ok = False
        _failed = _failed + [f"{_kind}(落点={_item['points'][0]} 期望={_first})"]
    _extras = mkt._annotations._extras.get(_item["id"]) or []
    # 复合类型（档位/标签/箭头）必须真的有附属图元，且**都在窗格容器里**（§11.5-15）
    if _extras and len(mkt.host.main_pane.annotation_items) != 1 + len(_extras):
        _composite_ok = False
    mkt.delete_selected_annotation()
    if mkt._annotations.count() != 0 or mkt.host.main_pane.annotation_items:
        _drawn_ok, _failed = False, _failed + [_kind + "(删不掉)"]
check(f"★ 目录里 {len(DRAWABLE_KINDS)} 种**每一种**都能点出来并落库"
      f"（说能画就必须画得出）{_failed}",
      _drawn_ok and len(DRAWABLE_KINDS) == 32)

# ★ STEP 1 拍板语义：① 点一半不落库 ② Esc 取消不留东西 ③ 画完回浏览模式 ④ 允许重合
mkt._annotations.clear_all()
mkt.select_tool(KIND_TREND)
mkt._annotations._session.on_click(mkt._annotations._axis.index_to_date(3.0), 101.0)
check("★ 只点了 1 个锚点 ⇒ **不落库**（没点够就不该出现半截线；图上只有预览）",
      mkt._annotations.count() == 0 and not mkt._annotations._items
      and mkt._annotations.drawing)
mkt.select_tool("")                      # 浏览模式 == 取消绘制
check("★ 切回浏览模式 ⇒ 半截绘制被丢掉，图上不留预览",
      mkt._annotations.count() == 0 and not mkt.host.main_pane.annotation_items
      and not mkt._annotations.drawing)
mkt.select_tool(KIND_HLINE)
mkt._annotations._session.on_click(mkt._annotations._axis.index_to_date(4.0), 102.0)
check("★ 画完一条 ⇒ **自动回到浏览模式**（用户拍板：必须防手残）",
      mkt._annotations.count() == 1 and mkt.current_tool == ""
      and not mkt._annotations.drawing)
mkt.select_tool(KIND_TREND)
mkt._annotations._session.on_click(mkt._annotations._axis.index_to_date(5.0), 103.0)
mkt._annotations._session.on_click(mkt._annotations._axis.index_to_date(5.0), 103.0)
check("★ 允许点位重合（两次点同一个地方也照落，**不做**自以为是的去重）",
      mkt._annotations.count() == 2)
mkt._annotations.clear_all()
check("★ 复合类型（档位/标签）的附属图元全部挂进窗格容器（不会留下没人管的线）",
      _composite_ok)
mkt._annotations.clear_all()
mkt.select_tool(KIND_TREND)

# 价格标签：**文字就是价位**，拖到新价位后标签跟着变（不是写死的一串字）
mkt.select_tool("price_tag")
_tag = mkt._annotations.create_default()
check("价格标签新建时文字 = 当时的价位",
      _tag is not None and _tag["text"] == price_text(_tag["points"][0][1]))
mkt._annotations._items[_tag["id"]].setPos(20.0, 88.8)      # 模拟用户拖到这里
mkt._annotations._persist_from_view(_tag["id"])
check("★ 拖到新价位后标签文字跟着变（价位标签不是说一次就死的字）",
      p8_store.get("sh600000", "monthly", _tag["id"])["text"] == price_text(88.8))
mkt._annotations.clear_all()

# 区间类（价格带 / 时间区间）：读回来的是"两条价位 / 两个日期"，不是序号
mkt.select_tool("hband")
_band = mkt._annotations.create_default()
_band_y = [p[1] for p in _band["points"]]
check("价格带 = 两条价位（横向贯穿，日期只是锚点）",
      len(_band_y) == 2 and abs(_band_y[0] - _band_y[1]) > 0)
mkt._annotations.clear_all()

# 吸顶分类标题（R11 第 4 条）：滚下去之后顶部一直显示"当前是类"
mkt.anno_scroll.set_sections([
    (0, "趋势 / 通道　5 种", "#1976D2"),
    (200, "水平 / 垂直　5 种", "#00897B"),
    (400, "形态　6 种", "#7E57C2")])
mkt.anno_scroll.verticalScrollBar().setValue(0)
check("滚到最上面时**不显示**吸顶条（真实标题就在眼前，显示两个会打架）",
      mkt.anno_scroll.sticky_text() == "")
mkt.anno_scroll.verticalScrollBar().setValue(250)
check("★ 滚过第一类之后 ⇒ 顶部吸住「水平 / 垂直」（分类参照不会滚丢）",
      "水平 / 垂直" in mkt.anno_scroll.sticky_text())
mkt.anno_scroll.verticalScrollBar().setValue(420)
check("再滚 ⇒ 吸顶条换成「形态」", "形态" in mkt.anno_scroll.sticky_text())
mkt.anno_scroll.verticalScrollBar().setValue(0)

mkt.select_tool(KIND_FIB)
fib_item = mkt._annotations.create_default()
check("斐波那契：主图元 + 7 档水平位 + 7 标签",
      fib_item is not None and len(mkt._annotations._extras[fib_item['id']]) == 14
      and len(mkt.host.main_pane.annotation_items) == 15)
# ★v6.26：绘制中的回执是**分步提示**（"第 1/2 步 —— 点起点"），比"已存几条"重要
check("★ 绘制中回执给分步提示（用户此刻唯一要知道的是「下一步点哪」）",
      "第 1/2 步" in mkt.lbl_annotation_status.text()
      and "起点" in mkt.lbl_annotation_status.text())
mkt.select_tool("")
check("面板回执说明了周期与条数", '月线' in mkt.lbl_annotation_status.text())
mkt.delete_selected_annotation()
check("删除斐波那契：附属水平位一并消失（不留无主图元）",
      len(mkt.host.main_pane.annotation_items) == 0 and p8_store.count('sh600000', 'monthly') == 0)

ANSWERS.append("这里是压力位")              # 文字标注要填内容 → 交给打桩的输入框
mkt.select_tool(KIND_TEXT)
mkt._annotations._session.on_click(mkt._annotations._axis.index_to_date(6.0), 104.0)
check("★ 文字标注：点一下 ⇒ 弹输入框要内容 ⇒ 落库（新流程，按钮已删）",
      mkt._annotations.count() == 1 and len(mkt.host.main_pane.annotation_items) == 1
      and mkt._annotations.selected_id)
ANSWERS.append("")                          # 空内容 ⇒ 应当被拒（不落库）
mkt._annotations.clear_all()
mkt.select_tool(KIND_TEXT)
mkt._annotations._session.on_click(mkt._annotations._axis.index_to_date(7.0), 105.0)
check("★ 内容为空 ⇒ 不落库（绝不存一条画不出东西的记录）",
      mkt._annotations.count() == 0)
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

# ★v6.68（用户 2026-09-25 实测："无论怎么切，图始终是前复权"）：**必须验"真人手点"这条路**。
#   真事故 = `SegmentedControl._on_clicked` 用 `not key` 判"无效段"，而「不复权」的业务值
#   `ADJUST_NONE` **就是空字符串** ⇒ 手点被整段吞掉；而程序入口 `select_adjust()` 走的是
#   `set_current()`（**没有**那个真值判断）⇒ 一切正常。于是**所有走程序入口的断言全绿，
#   只有真人点不动** —— 这是本轮最贵的一课（§11.5-96）。
_btns68 = mkt.seg_adjust.buttons()
_keys68 = [mkt.seg_adjust.key_at(i) for i in range(mkt.seg_adjust.count())]
check("★ v6.68：复权分段的 key 里**确实有一个空字符串**（= `ADJUST_NONE`）—— 事故的地基",
      _keys68 == [ADJUST_QFQ, ADJUST_NONE] and ADJUST_NONE == "")
mkt.select_adjust(ADJUST_QFQ)
_btns68[1].click()                           # ← **真实点击**（用户手点走的就是这条）
check("★ v6.68：【真实点击】「不复权」必须切过去（空 key 也点得动；旧版 `not key` 把它吞了）",
      mkt.current_adjust == ADJUST_NONE and mkt.seg_adjust.current_key() == ADJUST_NONE
      and mkt._data_zone_and_key()[0] == 'kline_daily_raw')
_btns68[0].click()                           # ← 点回前复权
check("★ v6.68：【真实点击】点回「前复权」同样生效（不是单向可用）",
      mkt.current_adjust == ADJUST_QFQ and mkt._data_zone_and_key()[0] == 'kline_daily')

print("== v6.15 · 坐标轴自适应（§7-B4）：页面级 ==")
from ui.widgets.adaptive_axis import handle_for  # noqa: E402

# ---- 行情工作台：主图 + 量/MACD 副图逐格自适应 ----
mkt.select_period_group("D")               # 回到日线（前面测过周/月）
_layer("volume", True)
_layer("macd", True)
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
# 逐笔明细区 = 表头之后、遇到分隔空行或“# 以下逐日净值…”注释行为止（§7-A2 新增了尾部净值段）
_data = []
for _r in _rows[_hdr + 1:]:
    if not _r or _r[0].startswith("#") or _r[0] == "日期":
        break
    _data.append(_r)
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
_layer("ma", True)
_layer("boll", False)
_layer("volume", True)
_layer("macd", True)
_layer("formula", True)
mkt.render_charts()

check("工具行 chips 每组 ≤ 3 个（溢出交给「＋ 更多」，配置不会完全不可见）",
      len(mkt.chips_for("main")) <= CHIP_LIMIT and len(mkt.chips_for("sub")) <= CHIP_LIMIT
      and bool(mkt.chips_for("main")))

_saved_chips = {}
mkt._save_desk_ui = lambda **kw: (mkt._desk_ui.update(kw), _saved_chips.update(kw))
mkt.toggle_chip("boll")
check("点 chip = 改**真源**（`layer_model`；chip 只是投影，不是第二套状态）",
      mkt.layer_model.enabled("boll") and "boll" in mkt.chips_for("main"))
check("刚用过的项排到最前（最近使用优先）", mkt.chips_for("main")[0] == "boll")
check("最近使用历史落偏好（下次打开还记得）",
      _saved_chips.get("main_chips", [])[:1] == ["boll"])

mkt.toggle_chip("boll")
check("取消勾选：真源关掉，但 chips 里**留位变灰**（否则关掉就再也点不回来）",
      not mkt.layer_model.enabled("boll") and "boll" in mkt.chips_for("main"))

# ⚠ 这条不变量在**子图池**上已经测不动了：那一刻子图已有 3 项在开（占满工具行的 3 个位置），
#   灰位**没有空位可放**（这是规则本身的正确行为，不是 bug）。所以换到主图池上验同一条：
#   "从真源关闭（非 chip 路径）⇒ chips 里仍留灰位"。
_layer("ma", False)
check(f"反向投影：从真源（非 chip 路径）关闭 → chips 里留灰位（两个方向同一份状态；"
      f"实 chips={mkt.chips_for('main')}）",
      "ma" in mkt.chips_for("main"))
_layer("ma", True)
_layer("macd", True)

_layer("boll", True)
check("已启用项一定出现在 chips 里（不会『开了却看不到』）",
      "boll" in mkt.chips_for("main") and len(mkt.chips_for("main")) <= CHIP_LIMIT)

# ---- ★ §7-B8 R13/R14：配方库 = 图层真源；**多配方可同时开** + 顶栏镜像是投影 ----
from data.formula_store import FormulaStore, make_formula  # noqa: E402
from ui.widgets.chip_mru import chip_label  # noqa: E402
from ui.widgets.layer_model import LayerModel  # noqa: E402

# ⚠ 换**临时**配方库，并且把由它派生的一切一起重建
#   （§11.5-32：测试不只不能写脏用户库，也不能**读**它当依据）
_tmp_formula = FormulaStore(os.path.join(tmp_p8, "formulas.json"))
_main_recipe = _tmp_formula.upsert(make_formula(
    "我的均线", [("主图线: MA(C,10), COLORWHITE;", "main")]))
_sub_recipe = _tmp_formula.upsert(make_formula(
    "离差指标", [("离差值: C - MA(C,5), COLORWHITE;", "sub1")]))
_main_key = f"formula:{_main_recipe['id']}"
_sub_key = f"formula:{_sub_recipe['id']}"

mkt._formula_store = _tmp_formula
mkt._recipe_programs = {}
mkt.layer_model = LayerModel(formulas=_tmp_formula.all(), enabled=["volume"], params={})
mkt.current_df = df.copy()
mkt.render_charts()
check("模型里出现两条配方，且**内置在前、你的在后**",
      mkt.layer_model.keys()[4:] == [_main_key, _sub_key])
check("未启用的配方**不渲染**（开关真的在起作用，不是摆设）",
      not mkt._layer_formula and mkt.formula_plots == {})

mkt.layer_model.set_enabled(_main_key, True)
mkt.layer_model.set_enabled(_sub_key, True)
mkt.render_charts()
check("★ 多配方同时开：主图配方并进主图、副图配方**自己占一格**",
      len(mkt._layer_formula.get('main', [])) == 1
      and len(mkt._layer_formula.get(_sub_key, [])) == 1)
check("★ 副图窗格键 = **配方 key**（不绑「第几格」⇒ 以后调顺序不会让语义漂移）",
      set(mkt.formula_plots) == {_sub_key}
      and mkt.host.pane_names == ['main', 'vol', _sub_key])
check("★ chip 上写的是**配方名**（不是「公式副图 1」）—— 用户一眼知道那一格是什么",
      chip_label(_sub_key) != mkt._chips._label(_sub_key) == "离差指标")
check("两个池都**从模型动态取**（配方出现在候选里）",
      _main_key in mkt._chips._chip_candidates("main")
      and _sub_key in mkt._chips._chip_candidates("sub"))

# 「＋ 更多」的镜像：需要**池比工具行容量大**才看得出"被收进来的那些"
_sub_recipe2 = _tmp_formula.upsert(make_formula(
    "动量指标", [("动量: C - MA(C,5), COLORWHITE;", "sub1")]))
_sub_key2 = f"formula:{_sub_recipe2['id']}"
mkt.layer_model = LayerModel(formulas=_tmp_formula.all(),
                             enabled=["volume", "macd", _main_key, _sub_key], params={})
mkt._recipe_programs = {}
mkt.render_charts()
mkt._refresh_chips()
_texts = [a.text() for a in mkt._sub_more_menu.actions()]
check(f"★ 顶栏「＋ 更多」= 配方库**镜像**（分段 + 标出已开/已关；实={_texts}）",
      "你的配方" in _texts
      and any("动量指标" in text and "已关" in text for text in _texts)
      and all(("已开" in text or "已关" in text or text in ("内置", "你的配方"))
              for text in _texts))
check("★ 镜像里那条点一下就能开（不是只读展示）",
      any(a.isCheckable() and "动量指标" in a.text()
          for a in mkt._sub_more_menu.actions()))

mkt.toggle_chip(_sub_key)
check(f"★ 点 chip 关掉一条配方：只掉它自己那一格，**主图配方不受影响**"
      f"（enabled={mkt.layer_model.enabled(_sub_key)} plots={list(mkt.formula_plots)} "
      f"main={len(mkt._layer_formula.get('main', []))}）",
      mkt.layer_model.enabled(_sub_key) is False and _sub_key not in mkt.formula_plots
      and len(mkt._layer_formula.get('main', [])) == 1)
check("★ 关掉后它仍留在工具行上变灰（§7-B6-D 规则 3：关掉也要能点回来）",
      _sub_key in mkt.chips_for("sub")
      and _sub_key not in mkt._chips._chip_enabled_keys("sub"))
mkt.layer_model.set_enabled(_main_key, False)
mkt.render_charts()

# ---- ★ §7-B8 R7：副图换序端到端（⬆⬇ + 拖拽 → 即时重渲染 → 持久化 → 撤销；只改格位不改 target）----
from PyQt6.QtWidgets import QAbstractItemView  # noqa: E402
from ui.widgets.watch_sort_list import DragHandleListWidget  # noqa: E402
_R7_keep = (mkt.layer_model, mkt._recipe_programs, mkt._formula_segments,
            dict(mkt._sub_visible), mkt._desk_ui.get("sub_order"))   # 借状态，收尾原样还回去
mkt.layer_model = LayerModel(formulas=_tmp_formula.all(),
                             enabled=["volume", "macd", _sub_key], params={})
mkt._recipe_programs = {}
mkt.render_charts()
# ★体验修复回归：开关图层（同一份数据重渲染）不得把用户 x 缩放拉回全历史/默认
_vb = mkt.main_plot.getViewBox()
_n = len(mkt._rendered_df)
_vb.setXRange(_n * 0.4, _n * 0.6, padding=0)      # 模拟用户缩放到中段
_zoom_before = _vb.viewRange()[0]
mkt.render_charts()                                # 同一份数据、仅重渲染（等价于开关图层）
app.processEvents()                                # 过一轮事件循环（真实栅格重排/布局在此发生）
app.processEvents()
_zoom_after = _vb.viewRange()[0]
check("★ 切图层重渲染保住用户 x 缩放（不再被拉回全历史/默认）",
      abs(_zoom_after[0] - _zoom_before[0]) < 1 and abs(_zoom_after[1] - _zoom_before[1]) < 1)
check("主图 x 轴 autoRange 已关（栅格重排不会再 auto-fit 回全部历史）",
      _vb.state['autoRange'][0] is False)
check("★ 每张联动副图 x 轴 autoRange 已关（联动图不得自我 auto-fit，否则重排会把共享 x 拉回全历史）",
      all(mkt.host.pane(nm).plot_item.getViewBox().state['autoRange'][0] is False
          for nm in ('vol', 'macd', _sub_key)))
check("起点：副图格位 = 内置量 → MACD → 离差指标（渲染吃模型顺序）",
      mkt.layer_model.sub_order_keys() == ["volume", "macd", _sub_key, _sub_key2]
      and mkt.host.pane_names == ['main', 'vol', 'macd', _sub_key])
mkt.set_formula_sort_mode(True)
check("进换序模式：按副图先后铺开行（含未启用仍占格），工具条/列表都显出来",
      mkt._formula_sort_mode is True
      and mkt.formula_sort_list.count() == 4
      and not mkt.formula_sort_bar.isHidden() and not mkt.formula_sort_list.isHidden())
check("★ 换序列表复用 DragHandleListWidget（三道闸+边缘自滚），进模式后开启内部拖拽",
      isinstance(mkt.formula_sort_list, DragHandleListWidget)
      and mkt.formula_sort_list.dragDropMode()
      == QAbstractItemView.DragDropMode.InternalMove)
mkt.formula_sort_list.setCurrentRow(0)          # 选中 volume
mkt.move_formula_sort(1)                         # volume 下移一格 ⇒ macd 冒到最前
check("★ ⬆⬇ 换序落模型：sub_order 首位变 macd",
      mkt.layer_model.sub_order_keys()[0] == "macd")
mkt.render_charts()
check("★ 换序即时反映到窗格顺序（渲染吃模型顺序）",
      mkt.host.pane_names == ['main', 'macd', 'vol', _sub_key])
check("★ 换序**绝不改 target**：副图成员仍全是副图（R7 一致性口径）",
      all(mkt.layer_model.target_of(k) == 'sub' for k in mkt.layer_model.sub_order_keys()))
mkt._persist_layer_state()
check("★ 换序结果被记住（写进 desk_ui.sub_order）",
      (mkt._desk_ui.get('sub_order') or [''])[0] == "macd")
# 拖拽提交：模拟"把 离差指标 拖到最顶"（InternalMove 后复现列表序 → rowsMoved 延迟回写）
_drag_it = mkt.formula_sort_list.takeItem(2)      # 当前第 3 行 = 离差指标
mkt.formula_sort_list.insertItem(0, _drag_it)
mkt._formula.apply_formula_sort()                 # 等价于 rowsMoved → 延迟提交
check("★ 拖拽提交回写模型：离差指标顶到最前",
      mkt.layer_model.sub_order_keys()[0] == _sub_key)
mkt.render_charts()
check("★ 拖拽后窗格顺序 = ['main', 离差, macd, vol]",
      mkt.host.pane_names == ['main', _sub_key, 'macd', 'vol'])
mkt.undo_formula_sort()
check("↺ 撤销回到进入前顺序（volume 又回到最前）",
      mkt.layer_model.sub_order_keys()[0] == "volume")
mkt.finish_formula_sort()
check("✓ 完成退出换序模式（模式关、列表隐藏）",
      mkt._formula_sort_mode is False and mkt.formula_sort_list.isHidden())
# 还原借用的全局状态（§11.5-32：绝不把本段污染给后面的 draft/chip 断言）
(mkt.layer_model, mkt._recipe_programs, mkt._formula_segments, mkt._sub_visible) = _R7_keep[:4]
if _R7_keep[4] is None:
    mkt._desk_ui.pop("sub_order", None)
else:
    mkt._desk_ui["sub_order"] = _R7_keep[4]
mkt.render_charts()

# ---- ★ §7-B8 R6：配方库**页版式**（分区 + 徽标 + 图例 + 管理模式）----
def _recipe_chips(target):
    lay = mkt.formula_chip_lays[target]
    return [lay.itemAt(i).widget() for i in range(lay.count())]


mkt.show_rail_page("formula")
mkt.refresh_recipe_page()
check("配方库页：两个分区（主图/副图）+ 图例 + 管理模式 + 主操作都在本页",
      mkt.card_formula_lib.isAncestorOf(mkt.lbl_formula_legend)
      and set(mkt.formula_section_labels) == {"main", "sub"}
      and "主图配方" in mkt.formula_section_labels["main"].text()
      and "条" in mkt.formula_section_labels["sub"].text())
check("★ 徽标一眼分辨去处：内置 / 主图 / 副图 三种（治「载入时看不出是主图还是副图」）",
      [chip.badge.text() for chip in _recipe_chips("main")][:2] == ["内置", "内置"]
      and any(chip.badge.text() == "主图" for chip in _recipe_chips("main"))
      and any(chip.badge.text() == "副图" for chip in _recipe_chips("sub")))

mkt.set_formula_manage(True)
check("★ 管理模式：用户配方出现 ✏/🗑，但**内置项一个都不出现**（改了怕你改不回来）",
      all(not chip.ops_visible() for chip in _recipe_chips("main") if chip.builtin)
      and all(chip.ops_visible() for chip in _recipe_chips("main") if not chip.builtin)
      and all(not chip.ops_visible() for chip in _recipe_chips("sub") if chip.builtin))
mkt.set_formula_manage(False)
check("退出管理模式 ⇒ 操作全部收起（危险动作不与高频操作同排）",
      all(not chip.ops_visible() for chip in _recipe_chips("main")))

_toggle_key = next(chip.key for chip in _recipe_chips("sub")
                   if chip.key.startswith("formula:"))
_before = mkt.layer_model.enabled(_toggle_key)
mkt.toggle_recipe(_toggle_key)
check(f"★ 点配方 chip = **直接开关**，且页面与真源同时变（不是各存一份；"
      f"key={_toggle_key} 前={_before} 后={mkt.layer_model.enabled(_toggle_key)} "
      f"chip_on={[c.is_on() for c in _recipe_chips('sub') if c.key == _toggle_key]}）",
      mkt.layer_model.enabled(_toggle_key) != _before
      and all(chip.is_on() == mkt.layer_model.enabled(_toggle_key)
              for chip in _recipe_chips("sub") if chip.key == _toggle_key))
mkt.toggle_recipe(_toggle_key)
check("再点一次 ⇒ 回到原状态（可逆）",
      mkt.layer_model.enabled(_toggle_key) == _before)

# ---- ★ §7-B8 R16：⚙ 参数窗口（三道闸）----
from ui.dialogs.indicator_params import IndicatorParamsDialog, trial_run  # noqa: E402

check("★ 有参数才有 ⚙：MA / BOLL 有，**成交量没有**（绝不放点了没反应的假入口）",
      all(chip.has_param_button() for chip in _recipe_chips("main")
          if chip.key in ("ma", "boll"))
      and all(not chip.has_param_button() for chip in _recipe_chips("sub")
              if chip.key == "volume"))

mkt.layer_model.set_enabled("ma", True)
_dlg = IndicatorParamsDialog(mkt.layer_model, "ma", parent=mkt, sample_df=df.copy())
check("窗口按参数规格生成输入框，且**范围口径进了 tooltip**（不是冷冰冰一句「不合法」）",
      list(_dlg.editors) == ["周期1", "周期2", "周期3"]
      and "1 ~ 250" in _dlg.editors["周期1"].toolTip())

_dlg.editors["周期1"].setText("8")
_dlg.reject()
check("★ 闸①：改过参数就想关窗 ⇒ **拦下来**（绝不静默丢改动）",
      _dlg.discard_bar_visible() is True)
_dlg._on_keep_editing()
check("「继续编辑」⇒ 确认条收起（窗口还在）", _dlg.discard_bar_visible() is False)

_dlg.editors["周期1"].setText("abc")
_dlg._on_apply()
check("★ 闸②：格式不对点「应用」⇒ **自动回默认值并告知**（不放行、也不静默改）",
      _dlg.was_applied() is False
      and mkt.layer_model.params_of("ma")["周期1"] == 5
      and _dlg.editors["周期1"].text() == "5"
      and "已恢复为默认值" in _dlg.message_text())
_dlg.editors["周期2"].setText("300")
_dlg._on_apply()
check("★ 越界（>250）同样回默认并告知",
      mkt.layer_model.params_of("ma")["周期2"] == 20
      and "已恢复为默认值" in _dlg.message_text())

_dlg.editors["周期1"].setText("8")
_dlg._on_validate()
check(f"★ 「校验」拿**真实行情**试算一遍（实={_dlg.message_text()!r}）",
      _dlg.was_validated() is True and "校验通过" in _dlg.message_text())
_dlg.reject()
check("★ 校验通过后关窗**不再追问**（否则改了合法参数还老拦人）",
      _dlg.discard_bar_visible() is False)

_dlg.editors["周期1"].setText("9")
_dlg._on_reset()
check("★ 闸③：一键恢复默认（并提示「点应用才生效」）",
      mkt.layer_model.params_of("ma") == {"周期1": 5, "周期2": 20, "周期3": 60}
      and "点「应用」才生效" in _dlg.message_text())

_dlg.editors["周期1"].setText("8")
_dlg.editors["周期2"].setText("13")
_dlg._on_apply()
check("★ 合法参数点「应用」⇒ 真的生效（模型 → 引擎形参都跟着变）",
      _dlg.was_applied() is True
      and mkt.layer_model.engine_options()["ma"] == {"windows": (8, 13, 60)})
check("★ 试算判据是「**真的算出了值**」而不是「没报错」：窗口过大 ⇒ 不通过",
      trial_run("ma", {"windows": (250, 260, 280)}, df.copy())[0] is False
      and trial_run("ma", {"windows": (5, 20, 60)}, df.copy())[0] is True)
mkt.layer_model.reset_params("ma")
mkt.show_rail_page("watch")

# ⚠ 收尾：本段用 `toggle_chip` 走过"回流"，那会把 `layer_enabled` 写进偏好 ⇒
#   后面那些"草稿默认可见"的老断言依赖的是**没有记忆**这条路径（升级/首次运行）。
#   所以必须把这份"记忆"撤掉，否则本段就变成了对后面测试的隐式污染（§11.5-32 同族）。
mkt._desk_ui.pop("layer_enabled", None)
mkt._desk_ui.pop("layer_params", None)

# ⚠ 收尾：本段用 `toggle_chip` 走过"回流"，那会把 `layer_enabled` 写进偏好 ⇒
#   后面那些"草稿默认可见"的老断言依赖的是**没有记忆**这条路径（升级/首次运行）。
#   所以必须把这份"记忆"撤掉，否则本段就变成了对后面测试的隐式污染（§11.5-32 同族）。
mkt._desk_ui.pop("layer_enabled", None)
mkt._desk_ui.pop("layer_params", None)

check("「＋ 更多」菜单列出**完整候选池**（去掉已显示的；池是**动态的**、标签用配方名）",
      {a.text().split("　")[0] for a in mkt._main_more_menu.actions() if a.isCheckable()}
      == {mkt._chips._label(key)
          for key in set(mkt._chips._chip_candidates("main")) - set(mkt.chips_for("main"))})

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
_layer("ma", True)
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
# ★v1.46（用户 2026-09-25 实测）：③ **价格接缝** —— 单日 ≥25% 交易上不可能（创业板上限 20%），
#   它正是"除权后前复权历史没重算"的指纹（实证：指南针 300803 的 9/18=82.00 → 9/21=56.86）。
#   旧版只查量能接缝 ⇒ 这种**假跳空**永远不进回执，用户只能靠肉眼怀疑"复权是不是坏了"。
_price_df = _seam_df.copy()
_price_df['close'] = np.concatenate([np.full(40, 11.6), np.full(40, 8.0)])   # → -31% 假跳空
mkt.current_df = _price_df
mkt._data._health_cache.clear()
mkt._refresh_adjust_hint()
_price_text = mkt.lbl_adjust_hint.text()
check(f"★ v1.46：体检抓到「价格接缝」并点名疑似除权未重算 + 给出修复入口（{_price_text[:60]}…）",
      '价格接缝' in _price_text and '疑似除权后历史未重算' in _price_text
      and '重新全量下载' in _price_text)

# ★v1.46（用户实测）：取数失败必须**退出"正在取数"态**，否则回执永远挂着"正在从云端取这一份…"，
#   用户看到的就是"切了口径没反应"（而不是"取数失败了"）。
mkt.current_df = pd.DataFrame()
mkt._data._health_cache.clear()
mkt._refresh_adjust_hint(failed=True)
check("★ v1.46：取数失败时口径回执**不再停在「正在取数」**（旧版会永久挂着 = 看起来没反应）",
      '取数失败' in mkt.lbl_adjust_hint.text()
      and '正在从云端取' not in mkt.lbl_adjust_hint.text())
mkt.current_df = df.copy()
mkt._data._health_cache.clear()
mkt._refresh_adjust_hint()
check("干净数据不给假警报", '疑似数据异常' not in mkt.lbl_adjust_hint.text())
mkt.render_charts()

print("\n== §7-B6 STEP 4 · 左栏：图标轨 + 分页面板 + 折起（控件搬家不重建）==")
from ui.views.trading_desk import RAIL_ITEMS  # noqa: E402

check("图标轨 4 项、面板 4 页，键一一对应（v6.24 删掉「◫ 主图叠加/附图」页）",
      mkt.rail.keys() == [key for key, _icon, _title in RAIL_ITEMS] == mkt.desk_panel.keys()
      and len(RAIL_ITEMS) == 4)
# ★ 反向断言：删掉的东西**不许再存在**（否则"删了页但控件还在"会静默骗过所有人）
_revived = [name for name in ("cb_ma", "cb_boll", "cb_formula", "cb_vol", "cb_macd")
            if hasattr(mkt, name)]
check(f"★ 左栏那 5 个 QCheckBox 已退休、不许复活（还在的：{_revived or '无'}）",
      not _revived and "layer" not in mkt.desk_panel.keys() and "layer" not in mkt.rail.keys())

# ---- 搬家不重建：控件仍挂在**正确的页**上（父级链能追到该页容器）----
_MOVED = [("lst_watch", "watch"), ("btn_watch_add", "watch"), ("btn_watch_up", "watch"),
          # ★v6.24 §7-B8 R1/R2：自选页重排后新增的控件，同样"换容器可以，换页/换名字不行"
          ("card_watch_add", "watch"), ("card_watch_groups", "watch"),
          ("card_watch_list", "watch"), ("card_watch_manage", "watch"),
          ("txt_watch_quick", "watch"), ("cmb_watch_group", "watch"),
          ("watch_chip_host", "watch"), ("lbl_watch_planned", "watch"),
          ("btn_watch_pick", "watch"),
          ("btn_watch_down", "watch"), ("btn_watch_remove", "watch"),
          ("btn_watch_rename", "watch"), ("btn_watch_delete_group", "watch"),
          ("btn_edit_formula", "formula"), ("lbl_formula_status", "formula"),
          ("anno_scroll", "anno"), ("btn_anno_browse", "anno"),
          # ⚠ v6.26（§7-B9 拍板①）：`btn_add_annotation` 已随"添加标注"按钮删除 ⇒ 从护栏里摘掉
          ("btn_delete_annotation", "anno"), ("btn_clear_lines", "anno"),
          ("lbl_annotation_status", "anno"), ("lbl_adjust_hint", "data"),
          # ★v6.24 §7-B8 第 4/5 批：拖拽排序 + 内容区可滚（新增控件同样不许换页/换名）
          ("btn_watch_sort", "watch"), ("watch_sort_bar", "watch"),
          ("card_formula_lib", "formula"), ("card_anno_tools", "anno"),
          ("scroll_watch", "watch"), ("scroll_formula", "formula"), ("scroll_anno", "anno")]


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

# ---- ★ §7-B8 第 5 批：内容区可滚 + 卡头不被拉伸（修"卡片撑成巨大空框"）----
from PyQt6.QtWidgets import QSizePolicy  # noqa: E402
from ui.widgets.custom_widgets import ScrollRegion  # noqa: E402

check("三个页面都有各自的内容区（ScrollRegion，放不下就滚而不是顶掉底部按钮）",
      isinstance(mkt.scroll_watch, ScrollRegion)
      and isinstance(mkt.scroll_formula, ScrollRegion)
      and isinstance(mkt.scroll_anno, ScrollRegion))
check("★ 配方页：卡片在**内容区里**（贴顶堆叠、不贪心拉伸），主操作在外层**钉底**",
      mkt.scroll_formula.widget().isAncestorOf(mkt.card_formula_lib)
      and not mkt.scroll_formula.widget().isAncestorOf(mkt.btn_edit_formula))
check("★ 画线页：目录卡在内容区里、操作键在外层钉底（不跟着内容一起滚）",
      mkt.scroll_anno.widget().isAncestorOf(mkt.card_anno_tools)
      and not mkt.scroll_anno.widget().isAncestorOf(mkt.btn_delete_annotation))
check("★ 卡头**钉成固定高**（父布局把卡片拉高时，多出来的高度全给内容区、不给卡头）",
      mkt.card_formula_lib._head.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
      and mkt.card_anno_tools._head.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed)

mkt.card_formula_lib.set_open(False)
_collapsed_hint = mkt.card_formula_lib.sizeHint().height()
mkt.card_formula_lib.set_open(True)
_expanded_hint = mkt.card_formula_lib.sizeHint().height()
check("★ 收起卡片 → 高度需求**收缩到只剩卡头**，展开 → 恢复（不再「收起也占满整页」）",
      _collapsed_hint < 60 and _expanded_hint > _collapsed_hint)

# ---- 信号没断（搬家最容易的翻车点：连了但对象换了/丢了）----
mkt.current_symbol, mkt.current_name = 'sh600000', '测试股'
mkt.current_df = df.copy()
_layer("ma", True)
_layer("boll", True)
check(f"搬家后信号仍活着：均线 3 + 布林 2（上/下轨，中轨由 MA20 承担）⇒ 图层 5 条"
      f"（MA={mkt.layer_model.enabled('ma')} BOLL={mkt.layer_model.enabled('boll')}"
      f" 实际={len(mkt._layer_builtin)} 周期={mkt.current_period}）",
      len(mkt._layer_builtin) == 5)
_layer("boll", False)

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
        # ⚠ v6.26：`add_annotation` 薄壳已删（按钮也没了）⇒ 换成新流程的 `ask_annotation_text`
        ("_annos", "ask_annotation_text", "ask_annotation_text", "desk_annotations.py"),
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
    # ★v6.24（§7-B8 R13）：5 个 QCheckBox 已退休 ⇒ 公共面换成**图层真源**（模型 + 唯一落点）
    "layer_model", "_persist_layer_state",
    "btn_edit_formula", "lbl_formula_status", "lbl_annotation_status", "lbl_adjust_hint",
    # ⚠ v6.26：`btn_add_annotation` 已删除（§7-B9 拍板①），公共面同步摘掉
    "btn_delete_annotation", "btn_clear_lines",
    # ★STEP 3b/3c/4：顶栏第 2 行 + 左栏（迁移期新增的公共面，同样不许改名）
    "seg_period", "seg_minute", "seg_adjust",
    # ★v6.24（§7-B8 R10/R11）：`seg_tool` 已退休（换成 32 种类型目录）⇒ 公共面换成这一组
    "anno_scroll", "anno_tiles", "anno_headers", "btn_anno_browse",
    "current_tool", "select_tool_number",
    "lbl_minute_depth", "lbl_caliber_note", "lbl_anno_pill", "btn_anno_tool",
    "rail", "desk_panel",
    # ★v6.24 §7-B8 R1/R2：自选分组 + 快添加（迁移期新增的公共面，同样不许改名）
    "card_watch_add", "card_watch_groups", "card_watch_list", "card_watch_manage",
    "txt_watch_quick", "cmb_watch_group", "watch_chip_host", "watch_chip_lay",
    "lbl_watch_planned", "btn_watch_rename", "btn_watch_delete_group", "watch_group",
    "watch_change", "invalidate_change_cache", "watch_quick_add", "watch_list_menu",
    "btn_watch_pick", "pick_watch_into_group", "move_selected_to_group",
    "watch_sort_mode", "btn_watch_sort", "btn_watch_sort_undo", "btn_watch_sort_done",
    "watch_sort_bar", "watch_row_delegate", "set_watch_sort_mode", "undo_watch_sort",
    "finish_watch_sort", "on_watch_rows_moved", "apply_watch_sort",
    "scroll_watch", "scroll_formula", "scroll_anno",
    "card_formula_lib", "card_anno_tools",
    # ★STEP 6：行为模块句柄（页面只转发；测试按模块核对实现位置）
    "_layout", "_panel", "_data", "_layers", "_formula", "_annos", "_chips",
    "_watch", "_readout",
    # 行为入口（页面级断言与 main_window 互送都调它们）
    "load_symbol", "sync_cloud", "render_charts", "prepared_df",
    "edit_formula", "save_formula_as", "open_formula_library",
    "send_formula_to_backtest", "receive_formula",
    "delete_selected_annotation", "clear_annotations",
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
check("取而代之：周期 / 复权仍是分段控件（**画线类型已不是** —— v6.24 换成 32 种目录）",
      all(hasattr(mkt, name) for name in ("seg_period", "seg_adjust"))
      and not hasattr(mkt, "seg_tool"))

# ==========================================
# 复盘页迁移护栏（1.25 · §9-U 收口 + §9-L 拆分）
#   与行情工作台同一套判据：**只许换容器与排布，不许换控件名 / 方法名 / 私有状态名**
#   （别处断言与 `main_window` 都按这些名字读），并把"实现确实搬走了 + 分栏不变量"
#   写成可执行断言 ⇒ 谁改名 / 把薄壳写成空函数 / 分栏退化都会立刻红。
# ==========================================
print("\n== 复盘页迁移护栏（1.25 · §9-U + §9-L）：公共面不许改名 + 分栏不变量 ==")
import ui.widgets.review_charts  # noqa: E402,F401
import ui.widgets.review_editor  # noqa: E402,F401
import ui.widgets.review_flow  # noqa: E402,F401
import ui.widgets.review_layout  # noqa: E402,F401
import ui.widgets.review_playback  # noqa: E402,F401
from ui.views import review as _review_module  # noqa: E402

_rev = win.page_review
_review_lines = [line for line in Path(_review_module.__file__).read_text(
    encoding="utf-8").splitlines() if line.strip()]
check(f"review.py 已降到 ≤500 行（实测 {len(_review_lines)}）", len(_review_lines) <= 500)
check("5 个 review_* 模块都能独立导入（新能力落 ui/widgets/*，§10-12）", True)

# 判据 = 拆分前后同一套断言零改动 ⇒ 只额外钉"实现确实搬走了"（不是把壳写成空函数）
for _handle, _impl_name, _page_name, _module in (
        ("_layout", "build", "_setup_ui", "review_layout.py"),
        ("_layout", "_build_monthly_mode", "_build_monthly_mode", "review_layout.py"),
        ("_playback", "_render_trade_playback", "_render_trade_playback", "review_playback.py"),
        ("_playback", "_nearest_bar_index", "_nearest_bar_index", "review_playback.py"),
        ("_charts", "_render_monthly_charts", "_render_monthly_charts", "review_charts.py"),
        ("_charts", "_render_duration_analysis", "_render_duration_analysis", "review_charts.py"),
        ("_editor", "on_review_trade_selected", "on_review_trade_selected", "review_editor.py"),
        ("_editor", "save_review_text", "save_review_text", "review_editor.py"),
        ("_editor", "stitch_current_orphan", "stitch_current_orphan", "review_editor.py"),
        ("_flow", "update_review_view", "update_review_view", "review_flow.py"),
        ("_flow", "refresh_review_filters", "refresh_review_filters", "review_flow.py"),
        ("_flow", "refresh_time_picker", "refresh_time_picker", "review_flow.py")):
    _impl = getattr(getattr(_rev, _handle), _impl_name)     # 实现（模块里）
    _src = Path(inspect.getsourcefile(_impl)).name
    check(f"{_impl_name} 的实现已搬进 {_module}，页面保留同名薄壳 {_page_name}",
          _src == _module and hasattr(_rev, _page_name))

# 公共面白名单：控件名 / 状态名 / 行为入口一个都不许动（§11.7 迁移红线）
REVIEW_PUBLIC_ATTRS = (
    # 状态
    "current_review_date", "is_yearly_view", "current_view_df", "current_editing_idx",
    "data_lake", "_trading_cal", "_review_ui",
    # 版式骨架 / 操作轴
    "review_stack", "review_monthly_widget", "yearly_panel", "macro_micro_splitter",
    "btn_mode_toggle", "btn_prev_time", "btn_next_time", "cb_time_picker", "btn_latest_time",
    "cb_rev_account", "cb_rev_strategy", "cb_rev_symbol", "cb_rev_direction", "cb_rev_result",
    "btn_manage_str",
    # 日历 / 图表
    "review_calendar", "lbl_cal_month_title", "review_chart_tabs", "review_pnl_chart",
    "review_kline_chart", "playback_chart", "review_duration_chart",
    # 清单 / 编辑卡
    "day_trades_list", "lbl_selected_date", "editor_header_card", "lbl_trade_detail",
    "cb_edit_strategy", "txt_reason", "txt_reflection", "orphan_bar", "gallery",
    "btn_del_trade", "btn_save_review",
    # 行为模块句柄 + 页面级入口
    "_layout", "_charts", "_playback", "_editor", "_flow",
    "update_review_view", "refresh_review_filters", "toggle_review_mode", "change_review_time",
    "jump_to_latest", "quick_jump_time", "on_calendar_day_clicked", "on_review_trade_selected",
    "save_review_text", "delete_current_trade", "silent_update_strategy",
    "guess_orphan_entry_price", "stitch_current_orphan",
)
_review_missing = [name for name in REVIEW_PUBLIC_ATTRS if not hasattr(_rev, name)]
check(f"复盘页公共面完整（{len(REVIEW_PUBLIC_ATTRS)} 项 · 缺：{_review_missing or '无'}）",
      not _review_missing)
check("导航第 3 页仍指向复盘工作台（main_window.page_review）", win.page_review is _rev)

# ★§9-U 收口不变量 --------------------------------------------------------
_split = _rev.macro_micro_splitter
check("★§9-U：宏观/微观之间是**竖向可拖分栏**（不是写死的 5:4 比例平铺）",
      _split.orientation() == Qt.Orientation.Vertical and _split.count() == 2)
check("★§9-U：分栏两块都不许拖到 0（整块塌掉会像控件丢了）",
      _split.childrenCollapsible() is False)

# 默认回落：没有偏好时用 560/340（短屏不再被写死比例挤死）
_saved_rui = dict(_rev._review_ui)
_rev._review_ui = {}
check("★§9-U：无偏好时回落默认分栏 560/340",
      _rev._layout._restored_v_sizes() == [560, 340])
_rev._review_ui = _saved_rui

# 记住上次：拖动 → 防抖落偏好（直接调落盘点，避开 300ms 等待）
from core.preferences import preferences as _prefs  # noqa: E402
_split.setSizes([620, 280])
app.processEvents()
_current_sizes = list(_split.sizes())
_rev._on_review_splitter_moved()          # 拖动信号 → 启动防抖计时器
check("★§9-U：拖动分栏会启动落盘（防抖计时器在跑）", _rev._review_save_timer.isActive())
_rev._persist_review_ui()                 # 直接落盘（等价计时器到点）
check("★§9-U：分栏高度**记住上次**（写入 review_ui.v_sizes，与 backtest_ui/desk_ui 同源）",
      len(_current_sizes) == 2
      and _prefs.get("review_ui", {}).get("v_sizes") == _current_sizes)
check("★§9-U：偏好可被重新读出（下次打开还原分栏高度）",
      _rev._load_review_ui().get("v_sizes") == _current_sizes)

# 坏偏好一律回落默认（0 / 负数 / 长度不对都不落）
_prefs.set("review_ui", {"v_sizes": [0, -5]})
check("★§9-U：坏偏好一律回落默认（0/负数不落）", _rev._load_review_ui() == {})
_prefs.set("review_ui", {"v_sizes": _current_sizes})

check("复盘页仍在导航挂载（content_area 里能找到它）",
      any(_rev is win.content_area.widget(i) for i in range(win.content_area.count())))

# ==========================================
# §7-B1/B2 STEP 4 · M2「全市场筛选」页（v6.37 · ScanView）
#   与行情工作台 / 复盘页同一套判据：**公共面不许改名 + 版式与口径不变量写成可执行断言**。
# ==========================================
print("\n== §7-B1/B2 STEP 4 · M2 全市场筛选页：公共面 / 版式不变量 / 端到端 ==")
try:
    from time import perf_counter as _now4
    from time import sleep as _sleep4

    from core.cross_section import ScanThresholds  # noqa: E402
    from core.preferences import preferences  # noqa: E402
    from data.scan_store import get_scan_store, kline_zone_dir  # noqa: E402
    from ui.views.scan_view import ScanView  # noqa: E402
    from ui.workers import JobGuard  # noqa: E402

    _scan = win.page_backtest.page_scan

    # ★P5：M2 扫描完成会后台拉估值快照（联网）⇒ 测试必须打桩为不 start，守 §11.5-20 离线。
    from ui.widgets import scan_flow as _sflow4
    from PyQt6.QtCore import QObject as _QObjectV, pyqtSignal as _pyqtSignalV

    class _StubValWorker(_QObjectV):
        finished = _pyqtSignalV(object)

        def __init__(self, *args, **kwargs):
            super().__init__()                # ★v6.68：容纳 IndustryMapWorker(page_start, pages, parent=…)

        def start(self):
            pass                              # 不联网、不回包 ⇒ 估值列保持 '—'

        def isRunning(self):
            return False                      # 非真线程：永远不在跑（不阻后续发车判定）

    _orig_val_worker = _sflow4.SpotValuationWorker
    _sflow4.SpotValuationWorker = _StubValWorker
    _sflow4.IndustryMapWorker = _StubValWorker          # ★P6：行业映射 worker 同样打桩不联网

    # ---- ① 挂载与公共面（迁移护栏：改名 / 删除 / 把薄壳写成空函数 ⇒ 立刻红）----
    check("M2 已换掉 `_ComingSoonPage` 占位（`page_scan` = ScanView）", isinstance(_scan, ScanView))
    check("M2 仍挂在回测模块的页签上（`backtest_module` 的壳一字未动，F-2）",
          win.page_backtest.tabs.widget(1) is _scan
          and win.page_backtest.tabs.tabText(1) == '🌐 全市场筛选')
    SCAN_PUBLIC = (
        # 状态（全部留在页面）
        'main_win', '_thresholds', '_symbols', '_names', '_asof', '_outcome', '_guard',
        '_worker', '_store', '_open_key', '_last_pane', '_layout',
        # 行为模块句柄
        '_flow', '_result', '_formula_pane', '_filter_pane', '_panes', '_drawer', '_scrim',
        # L1 操作轴
        'cb_scope', 'cb_index', 'lbl_scope', 'lbl_adjust', 'btn_config',
        'btn_prev_day', 'lbl_day', 'btn_next_day', 'btn_latest_day', 'date_asof',
        # L2 摘要条
        'chip_formula', 'chip_filter', 'chip_scope', 'lbl_receipt', 'bar_progress', 'btn_run',
        # L0 结果区
        'lbl_title', 'lbl_cached', 'kpi', 'table', 'lbl_empty', 'btn_empty_action', 'lbl_foot',
        # 行为入口（同名薄壳）
        'build_top_bar', 'build_summary_bar', 'build_result_area', 'build_overlays',
        'open_pane', 'close_pane', 'start_scan', 'cancel_scan', 'resolve_scope', 'refresh',
        'shift_date', 'jump_latest', 'reset_thresholds', 'current_counts',
        '_load_scan_ui', 'save_scan_ui',
    )
    _scan_missing = [name for name in SCAN_PUBLIC if not hasattr(_scan, name)]
    check(f"M2 公共面完整（{len(SCAN_PUBLIC)} 项 · 缺：{_scan_missing or '无'}）", not _scan_missing)
    check("竞态守卫就位（§9-O5：页面用的是公共件 `JobGuard`，不是各写一个 `_token`）",
          isinstance(_scan._guard, JobGuard))

    # ---- ② 版式与口径不变量 ----
    check("★ 常驻行 ≤3（§10-14：L1 操作轴 + L2 摘要条 + L0 结果区；抽屉是**覆盖层**不占布局）",
          _scan.layout().count() == 3)
    check("结果表 17 列 = #/代码/名称/行业/收盘/当日%/当月%/当年%/成交额(万)/成交量(万手)/换手率%/市盈率/市净率/总市值(亿)/流通市值(亿)/状态/说明（★P2 富字段 + ★P5 估值 + ★P6 行业；**用户量纲**，§10-10）",
          _scan.table.columnCount() == 17
          and _scan.table.horizontalHeaderItem(0).text() == '#'
          and _scan.table.horizontalHeaderItem(3).text() == '行业'
          and _scan.table.horizontalHeaderItem(5).text() == '当日%'
          and _scan.table.horizontalHeaderItem(8).text() == '成交额(万)'
          and _scan.table.horizontalHeaderItem(11).text() == '市盈率'
          and _scan.table.horizontalHeaderItem(14).text() == '流通市值(亿)')
    check("抽屉两张卡：ƒ 筛选条件 + 🎚 粗筛（含「↺ 恢复默认」）；出厂示例已填好（不是空框）",
          [pane.key for pane in _scan._panes] == ['fn', 'filter']
          and hasattr(_scan._filter_pane, 'btn_reset')
          and bool(_scan._formula_pane.txt_formula.toPlainText().strip()))
    check("复权口径**印在界面上**且只有这一种（D8：raw 未备齐前不假装支持）",
          _scan.lbl_adjust.text() == '前复权')

    # ---- ②b 基准日「先选后扫」+ 表格性能护栏（v6.42 用户实测三项）----
    from PyQt6.QtCore import QDate as _QDate4  # noqa: E402
    from PyQt6.QtWidgets import QHeaderView as _QHeader4  # noqa: E402
    check("★ 基准日控件**扫描前就可用**（日历弹窗自由选，不再只能先扫后看 / ◀▶ 挪）",
          _scan.date_asof.isEnabled() and _scan.date_asof.calendarPopup())
    _scan.date_asof.setDate(_QDate4(2024, 5, 10))
    check("选日期即刻有回执（告诉你将按这一天扫，而不是没反应）",
          '2024-05-10' in _scan.lbl_receipt.text() and '开始扫描' in _scan.lbl_receipt.text())
    check("★ 结果表列宽**不是** ResizeToContents（v6.42 卡死根因：动态测宽 × 全 A 行数 = 平方级冻死 UI）",
          all(_scan.table.horizontalHeader().sectionResizeMode(i)
              != _QHeader4.ResizeMode.ResizeToContents for i in range(17)))

    # ---- ③ 粗筛阈值「内核 → 界面 → 内核」往返零漂移（唯一换算处：亿元 / %）----
    _defaults = ScanThresholds()
    _scan._filter_pane.from_thresholds(_defaults)
    _roundtrip = _scan._filter_pane.to_thresholds()
    check("★ 阈值往返**零漂移**（换手率/市值默认关闭时必须仍是 None，不许变成 0 误杀一片）",
          abs(_roundtrip.min_amount - _defaults.min_amount) < 1.0
          and abs(_roundtrip.min_price - _defaults.min_price) < 1e-9
          and _roundtrip.min_bars == _defaults.min_bars
          and _roundtrip.min_turnover is None and _roundtrip.min_float_mktcap is None
          and _roundtrip.exclude_st == _defaults.exclude_st
          and _roundtrip.exclude_suspended == _defaults.exclude_suspended
          and _roundtrip.exclude_limit == _defaults.exclude_limit)
    _scan.reset_thresholds()
    check("「↺ 恢复默认」= 出厂值（D5）",
          _scan._filter_pane.to_thresholds().to_dict() == _defaults.to_dict())

    # ---- ④ 门面：代码 → 名称（§9-H：UI 不许直接碰 DatabaseManager）----
    _roster_names = win.engine.roster_names()
    _roster_syms = win.engine.list_stock_symbols()
    check("engine.roster_names() 门面可用（dict；且覆盖全部全 A 代码）",
          isinstance(_roster_names, dict)
          and (not _roster_syms or set(_roster_syms) <= set(_roster_names)))

    # ---- ④b 扫描前闸门（v6.42）：体检发现缺数据 ⇒ 必须二次确认，选「否」不启动 ----
    from data.readiness import ReadinessReport as _RRep4  # noqa: E402
    _scan._symbols = ['GATE01', 'GATE02']                # 非空即可（闸门在真扫之前拦）
    _scan._readiness.report = _RRep4(
        total=429, ready=['GATE01'], missing=[f'G{nn:04d}' for nn in range(428)])
    _asked4 = []
    _orig_q4 = QMessageBox.question

    def _answer_no4(*args, **_k):
        _asked4.append(str(args[2] if len(args) > 2 else ''))
        return QMessageBox.StandardButton.No

    QMessageBox.question = staticmethod(_answer_no4)
    _worker_before4 = _scan._worker
    _scan.start_scan()
    QMessageBox.question = _orig_q4
    check("★ 闸门：体检发现缺 428 只 ⇒ 弹二次确认把缺口说清；选「否」⇒ 根本不启动扫描",
          bool(_asked4) and '缺 428 只' in _asked4[0] and '429' in _asked4[0]
          and _scan._worker is _worker_before4 and '已取消' in _scan.lbl_receipt.text())
    _scan._readiness.report = None
    _scan._symbols = []

    # ---- ⑤ 端到端（真数据 · 小范围）：点「▶ 开始扫描」→ 线程 → 回包 → 渲染 ----
    _scan_zone = kline_zone_dir('kline_daily')
    _lake_syms = sorted(name[:-8] for name in os.listdir(_scan_zone)
                        if name.endswith('.parquet'))
    check("本地日线分区有数据可扫（否则本段只验版式）", len(_lake_syms) > 0)
    if _lake_syms:
        _probe = _lake_syms[:5]                       # 小范围：端到端要的是"管线通"，不是规模
        _scan.cb_scope.setCurrentIndex(2)             # 先切范围（会触发一次 resolve_scope）
        _scan._symbols = list(_probe)                 # 再收小范围（不受花名册规模影响）
        _scan._names = {sym: _roster_names.get(sym, '') for sym in _probe}
        get_scan_store().clear()                      # 从零开始（不受其它断言影响）
        _scan.date_asof.setDate(_QDate4.currentDate())   # ②b 把日期拨到过去只为验控件；端到端回到"默认=最新"语义
        _t04 = _now4()
        _scan.start_scan()

        def _wait_scan(page, timeout_s=120.0):
            """等后台线程跑完并把队列里的回包派发给页面（离屏环境没有事件循环在转）。"""
            deadline = _now4() + timeout_s
            while _now4() < deadline:
                app.processEvents()
                if page._worker is not None and page._worker.isFinished():
                    app.processEvents()
                    app.processEvents()
                    return page._outcome
                _sleep4(0.05)
            return page._outcome

        _outcome4 = _wait_scan(_scan)
        check(f"端到端：{len(_probe)} 只扫完并回包（{_now4() - _t04:.2f}s，含线程来回；非缓存命中）",
              _outcome4 is not None and _outcome4.result.counts['total'] == len(_probe)
              and _outcome4.cached is False)
        check("表格真的渲染出来了（行数 = 四态总数；不是只有 KPI 变了）",
              _scan.table.rowCount() == len(_probe) and not _scan.table.isHidden()
              and _scan.empty_box.isHidden())
        _counts4 = _scan.current_counts()
        check("★ KPI 三态齐全，**数据不足单独成桶**，分母 = 有效样本（口径铁律，E 节）",
              all(key in _counts4 for key in ('hit', 'miss', 'insufficient', 'filtered', 'valid'))
              and _counts4['valid'] == _counts4['hit'] + _counts4['miss']
              and _counts4['total'] == len(_probe))
        check("扫描基准日有**数值快照**（收盘列不是全 '—'）",
              any(_scan.table.item(r, 4) is not None and _scan.table.item(r, 4).text() not in ('', '—')
                  for r in range(_scan.table.rowCount())))

        # ---- ★P1 行号 + 全局排序（命中置顶默认 / 点列全局排 / 点状态列复位）----
        _nrow = min(3, _scan.table.rowCount())
        check("★ P1 首列行号随显示顺序连续（1,2,3…）",
              [_scan.table.item(r, 0).text() for r in range(_nrow)] == [str(i) for i in range(1, _nrow + 1)])
        _scan._flow.on_header_clicked(10)               # 点「换手率%」列 → 命中置顶 + 组内降序
        _st = [_scan.table.item(r, 15).text() for r in range(_scan.table.rowCount())]
        _tv = [_scan.table.item(r, 10).text() for r in range(_scan.table.rowCount())]
        _first_nonhit = next((i for i, s in enumerate(_st) if s != '命中'), len(_st))
        _hit_turn = [float(x.replace(',', '')) for x, s in zip(_tv, _st)
                     if s == '命中' and x not in ('', '—')]
        check("★ P1 点数值列 → 命中永远置顶（分组不被打散）+ 命中组内按该列降序",
              _scan._sort_col == 10 and _scan._sort_desc is True
              and not any(s == '命中' for s in _st[_first_nonhit:])
              and _hit_turn == sorted(_hit_turn, reverse=True))
        _scan._flow.on_header_clicked(10)               # 再点同列 → 组内升序
        _st2 = [_scan.table.item(r, 15).text() for r in range(_scan.table.rowCount())]
        _tv2 = [_scan.table.item(r, 10).text() for r in range(_scan.table.rowCount())]
        _hit_turn2 = [float(x.replace(',', '')) for x, s in zip(_tv2, _st2)
                      if s == '命中' and x not in ('', '—')]
        check("★ P1 再点同列 → 命中组内切升序（仍命中置顶）",
              _scan._sort_desc is False and _hit_turn2 == sorted(_hit_turn2))
        _scan._flow.on_header_clicked(15)               # 点「状态」列 → 复位（组内回到按代码）
        check("★ P1 点状态列 → 复位 _sort_col=None（命中置顶·组内按代码）",
              _scan._sort_col is None and _scan._sort_desc is False)

        # ---- ★P5：B 层估值列（当前值，仅基准日==最新定稿日填；喂假快照验渲染+诚实空值）----
        _scan._valuation = {s: {'pe': 30.0, 'pb': 2.0, 'total_mktcap': 1e10} for s in _probe}
        _scan._valuation_date = pd.Timestamp(_outcome4.result.asof).normalize()
        _scan.refresh()
        check("★ P5：喂入估值快照后 市盈率/市净率/总市值 列出数（表头在 11/12/13 列）",
              _scan.table.horizontalHeaderItem(11).text() == '市盈率'
              and _scan.table.horizontalHeaderItem(13).text() == '总市值(亿)'
              and _scan.table.item(0, 11).text() not in ('', '—')
              and _scan.table.item(0, 13).text() == '100')
        _scan._valuation, _scan._valuation_date = None, None   # 清场（模拟历史基准日/未取）
        _scan.refresh()
        check("★ P5：无估值（历史基准日/未取）⇒ 估值列诚实留 '—'（不拿 0 冒充）",
              all(_scan.table.item(r, 11).text() == '—' for r in range(_scan.table.rowCount())))

        # ---- ★P6：细分行业列（本地缓存；喂映射→出数，清空→'—'不瞎猜）----
        from data.industry_store import get_industry_store as _gis6
        _istore6 = _gis6()
        _saved6 = dict(_istore6._map)
        _istore6._map = {s: '半导体' for s in _probe}
        _scan.refresh()
        check("★ P6：喂入行业映射后 行业列(第3列)出数",
              _scan.table.horizontalHeaderItem(3).text() == '行业'
              and _scan.table.item(0, 3).text() == '半导体')
        _istore6._map = {}
        _scan.refresh()
        check("★ P6：无行业映射 ⇒ 行业列诚实留 '—'（不瞎猜板块）",
              all(_scan.table.item(r, 3).text() == '—' for r in range(_scan.table.rowCount())))
        _istore6._map = _saved6                          # 还原单例，不污染真实缓存

        # ★v6.68（用户实测"行业一直是空的，是不是我下载没弄好"）：**失败必须说出来**。
        #   旧版拿不到映射时那个分支什么都不做 ⇒ 界面只剩一列 '—'，用户只会怀疑自己。
        _scan.lbl_receipt.setText('基线回执')
        _scan._flow._on_industry_ready(None, _scan._industry_guard.next())
        check("★ v6.68：行业映射取不到 ⇒ 回执**说出来**（不静默）+ 给出路（再扫一次会重试）",
              '行业映射未取到' in _scan.lbl_receipt.text()
              and '重试' in _scan.lbl_receipt.text()
              and '基线回执' in _scan.lbl_receipt.text()          # 追加，不覆盖原回执
              and '东财' in _scan.lbl_receipt.toolTip())

        # ★v6.68：行业映射改**分批 + 断点续抓**（旧写法 80+ 连击正踩东财匿名高频风控，§11.5-99）
        _prog_back68 = preferences.get('industry_fetch')
        _started_ind68 = []

        class _StubIndWorker(_QObjectV):
            finished = _pyqtSignalV(object)

            def __init__(self, page_start=1, pages=1, parent=None):
                super().__init__()
                _started_ind68.append((int(page_start), int(pages)))

            def start(self):
                pass

            def isRunning(self):
                return False

        _sflow4.IndustryMapWorker = _StubIndWorker
        preferences.set('industry_fetch', {'next_page': 1, 'pages_total': 0})
        # ⚠ 单例 `path` 默认指向**用户真实库** ⇒ 必须换到临时文件，否则下面的断言会把
        #   假行业写进用户的 industry_map.json（本轮就被"防污染自检"当场抓到 ✓ 这是它该干的活）。
        import tempfile as _tmp68                          # noqa: E402
        _ind_path_back68 = _istore6.path
        _istore6.path = os.path.join(_tmp68.mkdtemp(prefix='jian_ind_flow68_'),
                                     'industry_map.json')
        _istore6._map = {}
        _started_ind68.clear()
        _scan._flow._maybe_fetch_industry()
        check("★ v6.68：行业走**分批**抓取（每批几页，不再是一次性几十次连击）",
              _started_ind68 == [(1, _sflow4.INDUSTRY_PAGES_PER_SCAN)])
        # ★v6.69（用户 2026-09-26 实测：一次扫描完成会**同时**打"行业 + 估值"两串全市场请求
        #   ⇒ 4 秒内两条一起 `RemoteDisconnected`）—— 三处收紧：
        #   ① 每批 8 → 3 页；② 估值改**按标的池批量**（不再全市场 56 页）；③ 失败退避冷却。
        check("★ v6.69：行业每批**降到 3 页**（单次扫描的突发从 8 个请求降到 3 个）",
              _sflow4.INDUSTRY_PAGES_PER_SCAN == 3)
        _cool_back68 = _sflow4.em_throttle.describe
        _sflow4.em_throttle.describe = lambda *a, **k: '东财限流冷却中（约 9 分钟后再试）'
        _started_ind68.clear()
        _scan.lbl_receipt.setText('基线')
        _scan._flow._maybe_fetch_industry()
        check("★ v6.69：冷却中 ⇒ **一个请求都不打**，且回执明说'还要等多久'（不再越点越死）",
              _started_ind68 == [] and '冷却' in _scan.lbl_receipt.text()
              and '行业映射未取到' in _scan.lbl_receipt.text())
        _sflow4.em_throttle.describe = _cool_back68
        # 估值也必须**按标的池**取（源码级护栏：这条一旦被改回"无参全市场"，额度立刻又会被打光）
        import pathlib as _pl68  # noqa: E402

        _src68 = _pl68.Path("ui/widgets/scan_flow.py").read_text(encoding="utf-8")
        check("★ v6.69：估值走**按标的池**（`SpotValuationWorker(list(p._symbols…))`，源码级护栏）",
              'SpotValuationWorker(list(p._symbols or [])' in _src68)
        import ui.main_window as _mw68  # noqa: E402

        check("★ v6.69：关窗统一 `cancel + wait` 后台线程（消掉 `QThread: Destroyed while …`）",
              hasattr(_mw68.JianMainWindow, '_shutdown_background_threads'))
        _scan.lbl_receipt.setText('基线')
        _scan._flow._on_industry_ready(
            {'map': {'600000': '银行'}, 'page_start': 1, 'pages_done': 2,
             'total_pages': 3, 'done': False}, _scan._industry_guard.next())
        _prog68 = preferences.get('industry_fetch') or {}
        check("★ v6.68：一批回包 ⇒ **并入**缓存（不是整体替换）+ 断点推进",
              _istore6.get('600000') == '银行' and _prog68.get('next_page') == 3
              and _prog68.get('pages_total') == 3)
        _scan._flow._on_industry_ready(
            {'map': {'600519': '白酒'}, 'page_start': 3, 'pages_done': 1,
             'total_pages': 3, 'done': True}, _scan._industry_guard.next())
        _started_ind68.clear()
        _scan._flow._maybe_fetch_industry()
        check("★ v6.68：补齐后**不再联网**（长期缓存）+ 回执说一声",
              _started_ind68 == [] and '行业映射已补齐' in _scan.lbl_receipt.text())
        _istore6._map = {}                                  # 清场
        _istore6.path = _ind_path_back68                    # 还回真实路径 + 重读真实库
        _istore6.load()
        preferences.set('industry_fetch', _prog_back68 or {})

        # ---- ★P7：列拖拽换序（只改视觉序，逻辑 item(r,c) 不变）+ 持久化 + 非法拒绝 ----
        _n7 = _scan.table.columnCount()
        _scan._flow.apply_column_order(list(reversed(range(_n7))))     # 完全倒序
        check("★ P7：换序后视觉位 0 的逻辑列=末列，而 item(r,逻辑列) 数据定位不变",
              _scan.table.horizontalHeader().logicalIndex(0) == _n7 - 1
              and _scan._flow.current_column_order() == list(reversed(range(_n7))))
        _scan._flow.apply_column_order(list(range(_n7)))               # 复位默认
        check("★ P7：复位后 current_column_order 回到自然序",
              _scan._flow.current_column_order() == list(range(_n7)))
        _scan._flow.apply_column_order([1, 2])                         # 非法/旧长度
        check("★ P7：非法列序被拒（保持当前序、不崩）",
              _scan._flow.current_column_order() == list(range(_n7)))
        _scan.save_scan_ui()
        check("★ P7：col_order 进 scan_ui（拖拽顺序持久化）",
              'col_order' in (preferences.get('scan_ui') or {}))

        # ---- ⑥ 切日期**零成本** + 不冒充 ----
        _dates4 = _outcome4.result.dates
        check("交易日轴来自缓存矩阵（≥1 天）", _dates4 is not None and len(_dates4) >= 1)
        if len(_dates4) >= 1:
            _other_day = str(pd.Timestamp(_dates4[0]).date())
            _scan._asof = pd.Timestamp(_dates4[0])
            _scan.refresh()
            check("★ 切到另一天：日期变了、表格重渲染了 —— **没进线程、没读盘**（纯切片，D3）",
                  _scan.lbl_day.text() == _other_day and _scan._worker.isFinished()
                  and get_scan_store().entries() == 1)
            check("★★ 非**扫描基准日** ⇒ 数值列是 '—'（**绝不拿旧日期的快照冒充当日**，D3 纪律）",
                  all(_scan.table.item(r, 4) is not None and _scan.table.item(r, 4).text() == '—'
                      for r in range(_scan.table.rowCount()))
                  and '只显示状态' in _scan.lbl_foot.text())
            _scan.jump_latest()
            check("「最新」回跳 = 扫描基准日（数值快照随之回来）",
                  _scan.lbl_day.text() == str(pd.Timestamp(_outcome4.result.asof).date())
                  and any(_scan.table.item(r, 4) is not None
                          and _scan.table.item(r, 4).text() != '—'
                          for r in range(_scan.table.rowCount())))
            # —— v6.42：日期控件 = 切日期的正路（选轴外日子 ⇒ 就近、零成本、出声）
            _axis_set = set(_dates4)
            _gap_day = next((_d + pd.Timedelta(days=1) for _d in _dates4[:-1]
                             if (_d + pd.Timedelta(days=1)) not in _axis_set), None)
            if _gap_day is not None and _gap_day <= pd.Timestamp.now():
                _scan.date_asof.setDate(_QDate4.fromString(str(_gap_day.date()), 'yyyy-MM-dd'))
                check("★ 点日历选**非交易日** ⇒ 就近落到最近交易日（回执出声，绝不空表糊弄）",
                      _scan._asof in _axis_set and str(_scan._asof.date()) == _scan.lbl_day.text()
                      and '就近' in _scan.lbl_receipt.text())
            _pick_day = pd.Timestamp(_dates4[3])
            _scan.date_asof.setDate(_QDate4.fromString(str(_pick_day.date()), 'yyyy-MM-dd'))
            check("★ 选轴上的交易日 ⇒ 精确落在它；切日期零成本（不进线程、缓存条数不变）",
                  _scan._asof == _pick_day and _scan.lbl_day.text() == str(_pick_day.date())
                  and _scan._worker.isFinished() and get_scan_store().entries() == 1)

    # ---- ⑦ 抽屉开合（覆盖层：不动主区高度）----
    win.switch_to('backtest')                     # 真实用户动作：切到回测模块
    win.page_backtest.tabs.setCurrentIndex(1)     # 再切到 M2 页签（否则页面不在前台，isVisible 恒 False）
    app.processEvents()
    _scan.open_pane('filter')
    check("抽屉可开：抽屉 + 遮罩可见，几何在页面矩形内（§11.5-26）",
          _scan._drawer.isVisible() and _scan._scrim.isVisible()
          and 0 < _scan._drawer.geometry().width() <= _scan.width())
    _scan.open_pane('filter')
    check("再点同一个胶囊 = 关闭（backtest 页同款交互）",
          not _scan._drawer.isVisible() and _scan._open_key is None)

    # ---- ⑧ 偏好「记住上次」：只存轻量配置，**绝不存扫描结果** ----
    _scan.save_scan_ui()
    _scan_ui = preferences.get('scan_ui')
    check("scan_ui 偏好只含 scope / 指数 / 条件 / 参数 / 阈值 / 列序（结果只进会话缓存，D3）",
          isinstance(_scan_ui, dict)
          and set(_scan_ui) <= {'scope', 'index_code', 'formula', 'params', 'thresholds', 'col_order'}
          and str(_scan_ui.get('formula') or '').strip() != ''
          and isinstance(_scan_ui.get('thresholds'), dict))
    # ★P5：故意**不还原** SpotValuationWorker 打桩 —— 后续 readiness 等段还会扫 M2，
    #   若用真 worker 会联网（违反 §11.5-20）；没有测试需要真估值线程，全程留桩最稳。
except Exception as _e:  # noqa: BLE001
    check(f"M2 全市场筛选页断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# §7-B1/B2 STEP 5 · M3「广度统计」页（1.29 · BreadthView）
#   与 M2 同一套判据：**公共面不许改名 + 版式与口径不变量写成可执行断言** + 端到端真数据。
#   M3 特有：双窗格 x 联动（B2）/ 区间切片零成本（D3）/ ⚡增量（D7）/ ⟳全量重算闸门（§10-10）。
# ==========================================
print("\n== §7-B1/B2 STEP 5 · M3 广度统计页：公共面 / 版式不变量 / 端到端 ==")
try:
    from PyQt6.QtCore import QObject as _QObject, pyqtSignal as _pyqtSignal  # noqa: E402

    from ui.views.breadth_view import BreadthView  # noqa: E402
    from ui.widgets import breadth_flow as _bflow  # noqa: E402

    _brd = win.page_backtest.page_breadth

    # ---- ① 挂载与公共面（迁移护栏：改名 / 删除 / 把薄壳写成空函数 ⇒ 立刻红）----
    check("M3 已换掉 `_ComingSoonPage` 占位（`page_breadth` = BreadthView，占位类退役）",
          isinstance(_brd, BreadthView))
    check("M3 仍挂在回测模块的第 3 页签上（`backtest_module` 的壳一字未动，F-2）",
          win.page_backtest.tabs.widget(2) is _brd
          and win.page_backtest.tabs.tabText(2) == '📊 广度统计')
    BRD_PUBLIC = (
        # 状态（全部留在页面）
        'main_win', '_thresholds', '_symbols', '_names', '_outcome', '_guard', '_index_guard',
        '_worker', '_cons_worker', '_index_worker', '_index_fetching', '_store', '_lake',
        '_range_key', '_index_df', '_index_code', '_open_key', '_last_pane', '_layout',
        # 行为模块句柄
        '_flow', '_result', '_formula_pane', '_filter_pane', '_display_pane',
        '_panes', '_drawer', '_scrim',
        # L1 操作轴
        'cb_scope', 'cb_index', 'lbl_scope', 'cb_range', 'lbl_adjust', 'btn_config',
        # L2 摘要条
        'chip_formula', 'chip_filter', 'chip_scope', 'chip_display', 'lbl_receipt',
        'bar_progress', 'btn_incr', 'btn_full', 'btn_run',
        # L0 结果区
        'chart', 'lbl_title', 'lbl_cal', 'lbl_cached', 'lbl_mini', 'lbl_empty',
        'btn_empty_action', 'lbl_foot',
        # 行为入口（同名薄壳）
        'build_top_bar', 'build_summary_bar', 'build_result_area', 'build_overlays',
        'open_pane', 'close_pane', 'start_scan', 'incremental_scan', 'full_recompute',
        'cancel_scan', 'resolve_scope', 'refresh', 'set_range', 'reset_thresholds',
        'current_breadth', '_load_breadth_ui', 'save_breadth_ui',
    )
    _brd_missing = [name for name in BRD_PUBLIC if not hasattr(_brd, name)]
    check(f"M3 公共面完整（{len(BRD_PUBLIC)} 项 · 缺：{_brd_missing or '无'}）", not _brd_missing)
    check("竞态守卫就位（§9-O5：扫描与指数补拉各一把公共件 JobGuard，不是手写 token）",
          isinstance(_brd._guard, JobGuard) and isinstance(_brd._index_guard, JobGuard))

    # ---- ② 版式与口径不变量 ----
    check("★ 常驻行 ≤3（§10-14：L1 操作轴 + L2 摘要条 + L0 结果区；抽屉是**覆盖层**不占布局）",
          _brd.layout().count() == 3)
    check("抽屉三张卡：ƒ 筛选条件 + 🎚 粗筛 + 📈 展示（ƒ/🎚 **直接复用 M2 的同款 EditPane**）",
          [pane.key for pane in _brd._panes] == ['fn', 'filter', 'display']
          and hasattr(_brd._filter_pane, 'btn_reset')
          and bool(_brd._formula_pane.txt_formula.toPlainText().strip()))
    check("复权口径**印在界面上**且只有这一种（D8：raw 未备齐前不假装支持）",
          _brd.lbl_adjust.text() == '前复权')
    check("区间快捷档 6 档（近3月/近6月/近1年/近3年/近5年/全部历史，顺序即下拉顺序）",
          _brd.cb_range.count() == 6
          and [_brd.cb_range.itemText(i) for i in range(6)]
          == ['近3个月', '近6个月', '近1年', '近3年', '近5年', '全部历史'])
    _defaults3 = ScanThresholds()
    _brd._filter_pane.from_thresholds(_defaults3)
    _roundtrip3 = _brd._filter_pane.to_thresholds()
    check("★ 阈值往返**零漂移**（M3 复用 M2 的唯一换算处：关掉项必须还是 None）",
          abs(_roundtrip3.min_amount - _defaults3.min_amount) < 1.0
          and _roundtrip3.min_turnover is None and _roundtrip3.min_float_mktcap is None)

    # ---- ③ 端到端（真数据 · 小范围）：扫描 → 回包 → 双窗格渲染 ----
    _brd_zone = kline_zone_dir('kline_daily')
    _brd_syms = sorted(name[:-8] for name in os.listdir(_brd_zone)
                       if name.endswith('.parquet'))
    check("本地日线分区有数据可扫（否则本段只验版式）", len(_brd_syms) > 0)
    if _brd_syms:
        _probe3 = _brd_syms[:5]
        _brd.cb_scope.setCurrentIndex(2)
        _brd._symbols = list(_probe3)
        _brd._names = {sym: _roster_names.get(sym, '') for sym in _probe3}
        # 指数副图先喂**合成数据**：端到端必须离线确定，不许在测试里联网补拉（§11.5-20）
        # ⚠ 显式打开「叠加指数」并把指数图形拨回折线：测试自己控制前置，不依赖用户真实偏好
        #   （v6.42 实测：用户手动测试把 overlay 关掉 / index_style 选成 K线 存进了 breadth_ui，
        #   副图断言会隔日误报 —— 测试对环境敏感就是测试的 bug）
        _brd._display_pane.chk_overlay.setChecked(True)
        _brd._display_pane.cb_index_style.setCurrentIndex(0)   # 折线
        #   v6.43 同族补正：下面两条断言（读数条「命中 N 只」/ 家数纵轴取整）同样依赖
        #   **口径=家数、视觉=柱状** —— 用户手测时勾上「占比%」/ 切到折线都会存进 breadth_ui，
        #   不显式钉死就会隔日误报（占比模式读数天生是「%」、纵轴该留小数）。
        _brd._display_pane.cb_chart.setCurrentIndex(0)          # 柱状（默认）
        _brd._display_pane.chk_ratio.setChecked(False)         # 家数口径（非占比）
        _overlay_code = str(_brd._display_pane.cb_overlay_code.currentData() or 'sh000001')
        _brd._index_code = _overlay_code
        # ★v1.46/方案A：合成指数拉到远未来（periods=1200 ⇒ 末日≈ 2030）——
        #   保证它**不落后于**真实广度轴 ⇒ ③ 段不会触发自动补拉（端到端必须离线，§11.5-20）。
        _brd._index_df = pd.DataFrame({
            'date': pd.bdate_range('2025-09-01', periods=1200),
            'close': np.linspace(3000.0, 3300.0, 1200),
            'open': np.linspace(2995.0, 3295.0, 1200),
            'high': np.linspace(3010.0, 3310.0, 1200),
            'low': np.linspace(2985.0, 3285.0, 1200)})
        get_scan_store().clear()
        _brd._formula_pane.txt_formula.setPlainText('COND := C > MA(C, 20);')  # 与 M2 的键错开
        _t05 = _now4()
        _brd.start_scan()
        _outcome5 = _wait_scan(_brd)
        check(f"端到端：{len(_probe3)} 只广度扫完并回包（{_now4() - _t05:.2f}s，含线程来回）",
              _outcome5 is not None and _outcome5.cached is False
              and _outcome5.result.counts['total'] == len(_probe3))
        check("★ 双窗格结构 = 广度（主）+ 指数（副），**x 轴联动**（B2：不做真·双 y 轴）",
              _brd.chart._host.pane_names == ['breadth', 'index']
              and _brd.chart._host.x_linked('index'))
        check("广度线真的画出来了（主窗格有曲线图元）",
              _brd.chart._host.pane('breadth').plot_item.items and not _brd.chart.isHidden()
              and _brd.empty_box.isHidden())
        check("指数副图也画出来了（喂了合成指数 ⇒ 副窗格有曲线）",
              any(getattr(item, 'curve', None) is not None
                  for item in _brd.chart._host.pane('index').plot_item.items))
        check("读数条常显且是**业务文案**（日期 + 命中家数，不是内置的 X/Y）",
              '命中' in _brd.chart._host.readout_text and '只' in _brd.chart._host.readout_text)

        # ---- ③b v6.42 图表可读性护栏：bar 序号轴 + y 真跟随 + 刻度可见 + 双视觉 ----
        from ui.widgets.adaptive_axis import handle_for as _handle_for  # noqa: E402
        from ui.widgets.breadth_chart import _BreadthTickAxis  # noqa: E402
        _pane_b = _brd.chart._host.pane('breadth').plot_item
        _pane_i = _brd.chart._host.pane('index').plot_item
        check("★ 默认视觉 = 柱状 + MA5 趋势线（整数家数用柱子读；下拉可切折线）",
              _brd._display_pane.cb_chart.currentData() == 'bars'
              and any(isinstance(it, pg.BarGraphItem) for it in _pane_b.items))
        check("家数纵轴刻度取整（「3.5 只」是谎话；占比模式才留小数）",
              isinstance(_pane_b.getAxis('left'), _BreadthTickAxis)
              and _pane_b.getAxis('left').integer)
        _h_b = _handle_for(_pane_b)
        _h_i = _handle_for(_pane_i)
        check("★ 两窗格都挂上 y 跟随器（adaptive_axis 的 **bar 序号**口径 —— 旧版喂 epoch 秒，跟随器 100% 失效）",
              _h_b is not None and _h_b.y_enabled and _h_i is not None and _h_i.y_enabled)
        _n_bars = _brd.chart._n
        _pane_b.vb.setXRange(_n_bars - 40, _n_bars - 20, padding=0)
        app.processEvents()
        _h_b.refresh()
        _h_i.refresh()
        _seg = _brd.chart._ys[-40:-19]
        _exp_top = float(np.nanmax(_seg)) * 1.08 + 1.0
        _y_lo, _y_hi = _h_b.y_range
        check("★ 缩放后家数纵轴**真的跟随可视区**（旧 bug：provider 收到 1.7e9 当序号，切片恒空 ⇒ 永不更新）",
              np.isfinite(_seg).any()
              and abs(_y_hi - _exp_top * 1.06) < max(1e-6, abs(_exp_top) * 0.02))
        _ilo4 = _brd.chart._idx_lo[-40:-19]
        _ihi4 = _brd.chart._idx_hi[-40:-19]
        _m4 = np.isfinite(_ilo4) & np.isfinite(_ihi4)
        _i_lo, _i_hi = _h_i.y_range
        _ispan = float(_ihi4[_m4].max() - _ilo4[_m4].min()) if _m4.any() else 0.0
        _itol = max(1.0, _ispan * 0.1)                       # 跟随器自带 6% padding，容差给到 10%
        check("★ 指数副图纵轴只框住**可视那 20 根**（旧 bug：全历史自动量程 2000~6000，4000 点跨度没人看得懂）",
              _m4.sum() > 1 and (_i_hi - _i_lo) < float(np.nanmax(_brd.chart._idx_hi)
                                                        - np.nanmin(_brd.chart._idx_lo))
              and _i_lo >= float(_ilo4[_m4].min()) - _itol and _i_hi <= float(_ihi4[_m4].max()) + _itol)
        _ticks = _h_i.ticks
        check("★ 底部日期刻度落在**视野内**（旧 bug：刻度钉在序号位置而轴是 epoch ⇒ 整根轴没字）",
              bool(_ticks) and all(0 <= t[0] <= _n_bars - 1 for t in _ticks)
              and any('-' in t[1] for t in _ticks))
        _pane_b.vb.setXRange(0, _n_bars - 1, padding=0)      # 恢复全视野，不影响后续断言
        app.processEvents()
        _brd._display_pane.cb_chart.setCurrentIndex(1)      # 切「折线 + 面积」
        app.processEvents()
        check("视觉可切换：折线态 = 有曲线图元、无柱（只换画法，数据一个字节不动）",
              not any(isinstance(it, pg.BarGraphItem) for it in _pane_b.items)
              and any(getattr(it, 'curve', None) is not None for it in _pane_b.items))
        _brd._display_pane.cb_chart.setCurrentIndex(0)      # 切回默认，不影响后续断言
        app.processEvents()

        # ---- ③c v6.42：指数副图四种图形 + 两窗格轴对齐 + 分界线调高 ----
        from ui.widgets.custom_widgets import CandlestickItem as _K4, OhlcBarItem as _O4  # noqa: E402
        _brd._display_pane.cb_index_style.setCurrentIndex(2)     # K 线
        app.processEvents()
        check("★ 指数副图可切 K 线（有开高低列的日子画四价）",
              any(isinstance(it, _K4) for it in _pane_i.items))
        _brd._display_pane.cb_index_style.setCurrentIndex(3)     # 美国线
        app.processEvents()
        check("指数副图可切美国线（OHLC bar，与 K 线同数据格式同色板）",
              any(isinstance(it, _O4) for it in _pane_i.items)
              and not any(isinstance(it, _K4) for it in _pane_i.items))
        _brd._display_pane.cb_index_style.setCurrentIndex(1)     # 面积
        app.processEvents()
        check("指数副图可切面积（回到曲线图元，无 K/OHLC 件）",
              not any(isinstance(it, (_K4, _O4)) for it in _pane_i.items)
              and any(getattr(it, 'curve', None) is not None for it in _pane_i.items))
        _brd._display_pane.cb_index_style.setCurrentIndex(0)     # 回默认折线
        app.processEvents()
        _w_b = _pane_b.getAxis('left').style.get('tickTextWidth')
        _w_i = _pane_i.getAxis('left').style.get('tickTextWidth')
        check("★ 两窗格纵轴共用同一个固定左槽（R8 第二版口径：对齐且**不留大片空白**）",
              bool(_w_b) and _w_b == _w_i and _w_b <= 60)
        check("★ 两图分界把手已启用且**看得见**（浅灰胶囊浮在交界上；没把手的功能等于没有）",
              _brd.chart._host._drag_pairs == ('breadth', 'index')
              and _brd.chart._host._divider is not None
              and not _brd.chart._host._divider.isHidden())   # 离屏非当前页：isVisible 恒假，用自身 show 态
        # 真实鼠标事件模拟：按下交界 → 往上拖 → 松手；再往下拖；再双击复位。
        # ⚠ 拖动模型 = 按下瞬间锁定参考系 —— 上下双向都必须跟手（v6.42 用户实测：
        #   旧版拿实时几何反推 ⇒ 布局回流振荡，"拖一点就失控/往上拖没反应"）。
        from PyQt6.QtCore import QPointF as _QP4, QEvent as _QE4  # noqa: E402
        from PyQt6.QtGui import QMouseEvent as _QME4  # noqa: E402
        _vp4 = _brd.chart._host._glw.viewport()
        _geo4 = _brd.chart._host._divider_geometry()

        def _me4(kind, y, down=True):
            btn = Qt.MouseButton.LeftButton
            return _QME4(kind, _QP4(80.0, y), btn,
                         btn if down else Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier)

        if _geo4 is not None:
            _ly4, _tp4, _bt4 = _geo4
            _span4 = _bt4 - _tp4
            app.sendEvent(_vp4, _me4(_QE4.Type.MouseButtonPress, _ly4))
            app.sendEvent(_vp4, _me4(_QE4.Type.MouseMove, _tp4 + _span4 * 0.30))
            app.sendEvent(_vp4, _me4(_QE4.Type.MouseButtonRelease,
                                     _tp4 + _span4 * 0.30, down=False))
            check("★ 分界把手**往上拖也响应**（双向跟手；主图权重真变小）",
                  _brd.chart._host.pane_stretch('breadth') <= 40)
            app.processEvents()                     # 让布局回流落地，再按**新交界**抓把手
            _geo4b = _brd.chart._host._divider_geometry()
            _ly4b = _geo4b[0] if _geo4b is not None else _tp4 + _span4 * 0.30
            app.sendEvent(_vp4, _me4(_QE4.Type.MouseButtonPress, _ly4b))
            app.sendEvent(_vp4, _me4(_QE4.Type.MouseMove, _tp4 + _span4 * 0.85))
            app.sendEvent(_vp4, _me4(_QE4.Type.MouseButtonRelease,
                                     _tp4 + _span4 * 0.85, down=False))
            check("★ 往下拖把主图调大（指数图空间收小）—— 两个方向都是直线映射，无振荡死区",
                  _brd.chart._host.pane_stretch('breadth') >= 80)
            _brd.chart._host.reset_divider_stretch()
            check("双击/重置分界线恢复默认 3:1",
                  _brd.chart._host.pane_stretch('breadth') == 3
                  and _brd.chart._host.pane_stretch('index') == 1)
        else:   # 离屏几何拿不到 ⇒ 直接判红（拖动功能依赖它，不许静默跳过）
            check("分界几何可算（拖动功能的前置）", False)
        check("★ 口径印在标题行上（E 节）：范围 · 前复权 · 有效 N/M · 区间",
              '前复权' in _brd.lbl_cal.text() and '有效' in _brd.lbl_cal.text()
              and str(_brd.cb_scope.currentText()).replace('…', '') in _brd.lbl_cal.text())
        check("近5日迷你读数就位（`MM-DD · N 只 / x%`）",
              _brd.lbl_mini.text().startswith('近5日') and '只' in _brd.lbl_mini.text())
        check("「⚡ 增量到最新」在结果就绪后可用（此前禁用，防空按）",
              _brd.btn_incr.isEnabled())
        _entries_after_scan = get_scan_store().entries()

        # ---- ④ 区间切换 = 纯切片，零成本（不进线程、不读盘）----
        _brd.set_range('3m')
        app.processEvents()
        check("★ 切区间：`_range_key` 生效、重画完成 —— **没进线程、缓存条数不变**（D3）",
              _brd._range_key == '3m' and _brd._worker.isFinished()
              and get_scan_store().entries() == _entries_after_scan
              and not _brd.chart.isHidden())
        _brd._display_pane.chk_ratio.setChecked(True)
        app.processEvents()
        check("切换「占比 %」口径：纵轴单位跟着换（家数（只）→ 占比（%））",
              '占比' in _brd.chart._host.pane('breadth').plot_item.getAxis('left').labelText)
        _brd._display_pane.chk_ratio.setChecked(False)
        app.processEvents()

        # ---- ⑤ ⚡ 增量到最新：数据没变 ⇒ 命中 + 明确说"已算到最新"（D7 / Worker 通道）----
        _brd.incremental_scan()
        _wait_scan(_brd)
        check("★ 增量到最新（数据没变）：**缓存命中**且回执明说「已算到最新」（不静默）",
              _brd._outcome.cached is True and '已算到最新' in _brd.lbl_receipt.text())

        # ---- ⑥ ⟳ 全量重算：危险动作 = 隔离呈现 + **二次确认**（§10-10）----
        _orig_question = _bflow.QMessageBox.question
        _bflow.QMessageBox.question = staticmethod(
            lambda *a, **k: _bflow.QMessageBox.StandardButton.No)
        _brd.full_recompute()
        check("全量重算：确认框选「否」⇒ **什么都不动**（原结果保留，回执说明）",
              '已取消全量重算' in _brd.lbl_receipt.text() and _brd._outcome is not None)
        _bflow.QMessageBox.question = staticmethod(
            lambda *a, **k: _bflow.QMessageBox.StandardButton.Yes)
        _brd.full_recompute()
        _wait_scan(_brd)
        _bflow.QMessageBox.question = _orig_question
        check("全量重算：确认框选「是」⇒ 走 `force=True` **真重扫**并重新渲染",
              _brd._outcome is not None and _brd._outcome.cached is False
              and not _brd.chart.isHidden())

        # ---- ⑦ 指数副图数据链：缺数据 ⇒ 后台补拉一次（走 MarketSyncService，§9-H）----
        _started_idx = []

        class _StubIndexWorker(_QObject):
            finished = _pyqtSignal(dict)

            def __init__(self, code, zone=None, parent=None):
                super().__init__(parent)
                self._code = str(code)

            def start(self):
                _started_idx.append(self._code)

        class _EmptyLake:
            """只模拟"湖里没有这只指数"（load_data 恒 None；绝不碰用户真实分区）。"""

            @staticmethod
            def load_data(zone, key):
                return None

            @staticmethod
            def exists(zone, key):
                return False

        _orig_idx_worker = _bflow.SingleSyncWorker
        _bflow.SingleSyncWorker = _StubIndexWorker
        _real_lake3 = _brd._lake
        _brd._lake = _EmptyLake()
        _brd._index_df = None
        _brd._index_code = ''
        _brd._flow._ensure_index()
        check("★ 指数副图缺数据：**后台补拉一次**且回执说明「失败不影响主图」（不静默、不卡 UI）",
              _started_idx == [_overlay_code]
              and '后台拉取' in _brd.lbl_receipt.text()
              and '不影响主图' in _brd.lbl_receipt.text())
        _brd._flow._ensure_index()
        check("指数补拉**不重复发车**（同一只还在拉 ⇒ 再调也不发第二枪）",
              _started_idx == [_overlay_code])

        # ---- ⑦b ★v1.46/方案A：有数据但**落后于主图** ⇒ 也自动补拉（副图不再停旧日子）----
        _brd._index_code = _overlay_code
        _brd._index_df = pd.DataFrame(
            {'date': pd.bdate_range('2019-01-01', periods=50),
             'close': np.linspace(3000.0, 3100.0, 50)})   # 末日远早于广度轴 ⇒ 落后
        _brd._index_fetching = ''
        _brd._flow._index_synced_to = None
        _brd._flow._index_gate.release()
        _started_idx.clear()
        _brd._flow._ensure_index()
        check("★ 指数副图落后于主图：**也自动补拉**（旧版只在完全没数据时补 ⇒ 副图永远停旧日子）",
              _started_idx == [_overlay_code]
              and '落后于主图' in _brd.lbl_receipt.text()
              and '不影响主图' in _brd.lbl_receipt.text())
        _brd._index_df = None
        _brd._index_code = ''
        _brd._index_fetching = ''
        _brd._flow._index_synced_to = None
        _brd._flow._index_gate.release()
        _bflow.SingleSyncWorker = _orig_idx_worker
        _brd._lake = _real_lake3

    # ---- ⑧ 抽屉开合（覆盖层：不动主区高度）----
    win.switch_to('backtest')
    win.page_backtest.tabs.setCurrentIndex(2)         # 切到 M3 页签（离屏下 isVisible 需要）
    app.processEvents()
    _brd.open_pane('display')
    check("抽屉可开（📈 展示卡）：抽屉 + 遮罩可见，几何在页面矩形内（§11.5-26）",
          _brd._drawer.isVisible() and _brd._scrim.isVisible()
          and 0 < _brd._drawer.geometry().width() <= _brd.width())
    _brd.open_pane('display')
    check("再点同一个胶囊 = 关闭（backtest 页同款交互）",
          not _brd._drawer.isVisible() and _brd._open_key is None)

    # ---- ⑨ 偏好「记住上次」：只存轻量配置，**绝不存扫描结果** ----
    _brd.save_breadth_ui()
    _brd_ui = preferences.get('breadth_ui')
    check("breadth_ui 偏好只含配置十一项（结果只进会话缓存，D3）",
          isinstance(_brd_ui, dict)
          and set(_brd_ui) <= {'scope', 'index_code', 'formula', 'params', 'thresholds',
                               'range', 'chart', 'index_style', 'smooth', 'ratio',
                               'overlay', 'overlay_code'}
          and str(_brd_ui.get('formula') or '').strip() != ''
          and isinstance(_brd_ui.get('thresholds'), dict)
          and _brd_ui.get('range') in ('3m', '6m', '1y', '3y', '5y', 'all')
          and _brd_ui.get('chart') in ('bars', 'line')
          and _brd_ui.get('index_style') in ('line', 'area', 'kline', 'ohlc'))
except Exception as _e:  # noqa: BLE001
    check(f"M3 广度统计页断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# §7-B1/B2 STEP 6 · 就绪度体检 + ⬇补齐缺失 + 成分股人话诊断（M2/M3 共用 `ReadinessFlow`）
#   用户拍板（2026-09-19）：必须保证用户能**真正获取**所选范围的股票；
#   出问题必须说清是哪一环 —— 名单（成分股）/ 本地数据（体检）/ 缺口（补齐）三段各有诊断。
# ==========================================
print("\n== §7-B1/B2 STEP 6 · 就绪度体检 / 补齐缺失 / 成分股诊断 ==")
try:
    from PyQt6.QtCore import QDate as _QDate6  # noqa: E402

    from data.readiness import ReadinessReport as _RReport6  # noqa: E402
    from data.scan_store import kline_zone_dir as _kzd6  # noqa: E402
    from ui.dialogs.bulk_download import BulkDownloadDialog as _BDD6  # noqa: E402
    from ui.widgets import readiness_flow as _rf6  # noqa: E402

    _brd6 = win.page_backtest.page_breadth      # 用 M3 页验证接线（M2 共用同一控制器类）

    def _wait_probe6(flow, timeout_s=60.0):
        # 以「报告入库」为准（线程 isFinished 先于跨线程信号派发，光等线程会偶发漏接）
        deadline = _now4() + timeout_s
        while _now4() < deadline:
            app.processEvents()
            if flow.report is not None:
                return flow.report
            _sleep4(0.02)
        return flow.report

    # ---- ① 范围就绪 ⇒ 自动体检（真湖 5 只 + 2 只不存在的 ⇒ 缺口可见可动作）----
    _zone9 = _kzd6('kline_daily')
    _real9 = sorted(name[:-8] for name in os.listdir(_zone9)
                    if name.endswith('.parquet'))[:5]
    check("本地日线分区有数据（体检接线段的前置）", len(_real9) == 5)
    _syms9 = _real9 + ['ZZZ001', 'ZZZ002']
    _brd6._outcome = None
    _brd6._symbols = list(_syms9)
    _brd6._readiness.start(_syms9, min_bars=250)
    _rep9 = _wait_probe6(_brd6._readiness)
    check(f"★ 体检接线（后台 footer 探测）：回执一行说清「就绪 5/7 · 未下载 2 · 本地最新…」"
          f"（实测 report={_rep9!r} · 回执={_brd6.lbl_receipt.text()!r}）",
          _rep9 is not None and len(_rep9.ready) == 5 and _rep9.gap_count == 2
          and '就绪 5/7' in _brd6.lbl_receipt.text()
          and '未下载 2' in _brd6.lbl_receipt.text())
    check("★ 缺口**看得见名字** + 空态给「⬆ 更新到最新交易日」动作（§7-B10 合并一键，禁止静默，D6-1/E 节）",
          'ZZZ001' in _brd6.lbl_empty.text()
          and '更新到最新交易日' in _brd6.btn_empty_action.text())

    # ---- ② 补齐缺失：★v1.43 任务**交给主窗口的后台队列**（§7-B11），
    #      打桩队列里的 SyncWorker —— 绝不联网（§11.5-20 离屏打桩铁律）----
    from ui import download_hub as _dhub6  # noqa: E402

    _fill_started = []

    class _StubSyncWorker6(_QObject):
        progress = _pyqtSignal(int, int, str)
        failed = _pyqtSignal(str, str)
        finished = _pyqtSignal(dict)

        def __init__(self, symbols, zone=None, force_full=False, min_date=None,
                     policy=None, parent=None):
            super().__init__(parent)
            self._symbols = [str(s) for s in (symbols or [])]
            self.cancelled = False
            _fill_started.append(self)

        def start(self):
            pass                              # 打桩：不起线程

        def cancel(self):
            self.cancelled = True

    _orig_sync9 = _dhub6.SyncWorker
    _dhub6.SyncWorker = _StubSyncWorker6
    _brd6._readiness.fill_missing()
    _job6 = _brd6._readiness._sync_job
    check("★ 补齐缺失：只把**未下载的 2 只**交给后台队列（已就绪/历史不足的不折腾）",
          [w._symbols for w in _fill_started] == [['ZZZ001', 'ZZZ002']]
          and _brd6._readiness._syncing and '补齐中' in _brd6.lbl_empty.text())
    check("★ 任务归属在主窗口的队列里，不在页面里（切页/关窗都不影响它跑）",
          win.downloads.get(_job6) is not None
          and win.downloads.get(_job6).origin == 'breadth')
    check("补齐进行中按钮 = 「⏹ 停止补齐」（温柔抓取可中断）",
          _brd6.btn_empty_action.text() == '⏹ 停止补齐')
    _brd6._readiness.stop_fill()
    check("停止补齐：worker.cancel 置位 + 回执说明「已下载的保留」（断点续传）",
          _fill_started[-1].cancelled and '保留' in _brd6.lbl_receipt.text())
    _fill_started[-1].finished.emit({'ok': 0, 'fail': 0, 'skipped': 0, 'added': 0,
                                     'aborted': True, 'aborted_by': 'cancel',
                                     'symbols_failed': []})          # 收尾：让队列回到空坑位
    check("★ 中断回包后队列不卡死（页面回执说清原因，任务号不再挂在页面上）",
          _brd6._readiness._sync_job is None
          and win.downloads.current is None
          and '已中断' in _brd6.lbl_receipt.text())

    # ---- ②b 更新到最新（§7-B10 STEP 2 合并一键）：把**整批当前范围**交给队列 ----
    _fill_started.clear()
    _brd6._readiness._syncing = False          # 恢复现场
    _brd6._readiness.update_latest()
    check("★ 更新到最新：把整批当前范围（含已就绪的 7 只）都交给后台队列 —— 缺的补、旧的拉到最新",
          [w._symbols for w in _fill_started] == [[str(s) for s in _syms9]]
          and _brd6._readiness._syncing and '更新中' in _brd6.lbl_empty.text())
    check("更新进行中按钮 = 「⏹ 停止更新」（可中断）",
          _brd6.btn_empty_action.text() == '⏹ 停止更新')
    _fill_started[-1].progress.emit(3, 7, 'ZZZ001')
    check("★ 页面进度条是队列的**投影**（只认自己那个任务号，进度真的落到页面上）",
          _brd6.bar_progress.value() == 3 and '更新 3/7' in _brd6.lbl_receipt.text())
    _fill_started[-1].finished.emit({'ok': 5, 'fail': 2, 'skipped': 0, 'added': 10,
                                     'aborted': False, 'aborted_by': '',
                                     'symbols_failed': ['ZZZ001', 'ZZZ002']})
    check("★ 完成后回执说清成败（不弹窗打断 —— 用户可能正在别的页面做事）",
          '成功 5' in _brd6.lbl_receipt.text() and '失败 2' in _brd6.lbl_receipt.text()
          and _brd6._readiness._syncing is False)
    _rep6b = _wait_probe6(_brd6._readiness)      # 完成会自动复检（两页口径仍只有一份）
    check("★ 同步结束后自动复检就绪度（不拿旧报告骗用户）", _rep6b is not None)

    # ---- ②c ★v1.46 修复（用户 2026-09-25 实测）：**已有扫描结果时**更新不得把结果区
    #      换成"更新中…"占位 —— 那会 `empty_box.show() + table.hide()` 把刚扫出来的表藏起来，
    #      而下载结束后的体检分支只换「正在体检」占位、**不会恢复它** ⇒ 永久卡在"更新中…" ----
    _keep_empty6 = _brd6.lbl_empty.text()
    _keep_outcome6 = _brd6._outcome
    _brd6._outcome = object()                 # 模拟"已经扫过一次、结果区正在展示结果"
    _fill_started.clear()
    _brd6._readiness._syncing = False         # 恢复现场
    _brd6._readiness.update_latest()
    check("★ 已有结果时更新：结果区**不被换成「更新中」占位**（否则下载结束后无处恢复 ⇒ 永久卡住）",
          '更新中' not in _brd6.lbl_empty.text()
          and _brd6.lbl_empty.text() == _keep_empty6
          and _brd6._readiness._syncing)
    check("★ 已有结果时更新：进度仍在回执行可见（结果区归结果、进度归回执/下载条）",
          '已提交后台' in _brd6.lbl_receipt.text())
    _fill_started[-1].finished.emit({'ok': 7, 'fail': 0, 'skipped': 0, 'added': 20,
                                     'aborted': False, 'aborted_by': '',
                                     'symbols_failed': []})
    check("★ 已有结果时更新完成：明说结果表仍是旧数据、给出刷新动作（不静默假装已刷新）",
          '成功 7' in _brd6.lbl_receipt.text()
          and '旧数据' in _brd6.lbl_receipt.text()
          and '开始扫描' in _brd6.lbl_receipt.text())
    _wait_probe6(_brd6._readiness)             # 收尾：等自动复检线程结束，别留半个线程给后段
    _brd6._readiness._syncing = False
    _brd6._outcome = _keep_outcome6            # 恢复现场

    # ---- ②d ★历史不足（partial）必须"看得见地"解释（用户 2026-09-25 实测：沪深300 每次
    #      都有 1 只"历史不足"、更新后依旧 —— 那是次新股，数据源没有更早行情，补不齐不是缺陷）----
    _keep_report6 = _brd6._readiness.report
    _keep_names6 = _brd6._names
    _brd6._outcome = None
    _brd6._readiness.report = _RReport6(total=3, ready=['AAA', 'BBB'],
                                        partial={'001280': 199}, missing=[],
                                        latest=pd.Timestamp('2026-09-24'))
    _brd6._names = {'001280': '示例新材'}
    _brd6._readiness._render_readiness()
    _txt6 = _brd6.lbl_empty.text()
    check("★ 历史不足：空态**看得见地**说清（点名标的 + 行数 + 补不齐 + 不是缺陷），不只藏在 tooltip（§10-10）",
          '001280' in _txt6 and '199' in _txt6 and '补不齐' in _txt6 and '不是缺陷' in _txt6)
    _brd6._readiness.report = _keep_report6    # 恢复现场（后段 ③ 还要用它的 gap_count）
    _brd6._names = _keep_names6
    _brd6._outcome = None

    _dhub6.SyncWorker = _orig_sync9
    _brd6._readiness._syncing = False          # 恢复现场

    # ---- ③ 范围切换后，旧体检回包**不得覆盖**新范围的提示（防串台）----
    _stale_job = _brd6._readiness._guard.next()
    _brd6._readiness._last_symbols = ['OLD999']
    _brd6._symbols = ['ONLY999']               # 用户已切走
    _keep_receipt6 = _brd6.lbl_receipt.text()   # 上一段②b 的完成回执（属于扫描/同步，体检不许抢）
    _brd6._readiness._on_probed(_stale_job, _RReport6(total=1, ready=['OLD999']),
                                ['OLD999'])    # 回调绑定"体检时自己的范围"（防穿透，v6.39）
    check("★ 迟到的旧范围体检被丢弃（回执不被覆盖，且不污染已有报告 —— §9-O5 精神同样成立）",
          _brd6.lbl_receipt.text() == _keep_receipt6
          and _brd6._readiness.report is not None
          and _brd6._readiness.report.gap_count == 2)

    # ---- ④ 成分股解析失败 = **人话诊断**（用户点名的痛点：不许裸甩"接口未返回成分股"）----
    _scan6 = win.page_backtest.page_scan
    _scan6._flow._on_constituents(
        {'ok': False, 'symbols': [], 'index_code': '000300',
         'reason': 'no_data', 'message': '接口未返回成分股'}, _scan6._guard.next())
    check("★ M2 成分股失败：分类说清「行情源未返回名单」+ 可能原因 + 替代路径 + 重试动作",
          '行情源未返回名单' in _scan6.lbl_empty.text()
          and '建议' in _scan6.lbl_empty.text()
          and _scan6.btn_empty_action.text() == '重试'
          and '接口未返回成分股' in _scan6.lbl_receipt.text())
    _brd6._flow._on_constituents(
        {'ok': False, 'symbols': [], 'index_code': '000905',
         'reason': 'network', 'message': 'timeout'}, _brd6._guard.next())
    check("★ M3 同款诊断（两页共用同一份实现，§11.5-11）：网络类失败安抚 + 建议重试",
          '网络请求失败' in _brd6.lbl_empty.text() and '稍后重试' in _brd6.lbl_empty.text())

    # ---- ④b 成分股**成功**回包 ⇒ 名称映射补齐 + 内核警告出口（用户 2026-09-20 实测两连）----
    from data.scan_store import scan_cached as _sc10  # noqa: E402

    _syms10 = list(_real9[:3])
    _scan6._flow._on_constituents(
        {'ok': True, 'symbols': _syms10, 'index_code': '000300',
         'reason': 'ok', 'message': 'OK'}, _scan6._guard.next())
    _roster10 = win.engine.roster_names()
    check("★ 成分股解析成功 ⇒ **名称映射从花名册补齐**（名称列不再全空、剔ST 生效；此前漏装配）",
          set(_scan6._names) == set(_syms10)
          and all(bool(_scan6._names.get(s)) for s in _syms10 if _roster10.get(s))
          and _scan6.lbl_scope.text() == '3 只')
    _out10 = _sc10(kline_zone_dir('kline_daily'), 'COND := C > MA(C,20);', symbols=_syms10,
                   names={}, thresholds=ScanThresholds())
    check("前置：空花名册 ⇒ 内核确实对「剔ST 未生效」出过警告（这条此前被 UI 整个吞掉）",
          any('ST' in w for w in (_out10.result.warnings or [])))
    _scan6._flow._on_finished(_scan6._guard.next(), _out10)
    check("★ 内核警告有出口：回执 ⚠ 摘要 + tooltip 全文（禁止静默，§10-10）",
          '⚠' in _scan6.lbl_receipt.text() and '剔除' in _scan6.lbl_receipt.toolTip())
    _brd6._flow._on_constituents(
        {'ok': True, 'symbols': _syms10, 'index_code': '000300',
         'reason': 'ok', 'message': 'OK'}, _brd6._guard.next())
    check("M3 同款名称映射（两页共用同一份实现口径，§11.5-11）",
          set(_brd6._names) == set(_syms10))

    # ---- ④c §7-B10 STEP 3/4：滞后提示（真日历）+ M2 基准日诚实化 ----
    import datetime as _dtm6
    import pandas as _pdc

    _cal9 = [_dtm6.date(2026, 1, d) for d in range(1, 31)]
    _brd6._outcome = None
    _brd6._symbols = list(_syms9)
    _brd6._readiness._calendar = _cal9
    _brd6._readiness.trading_target = _dtm6.date(2026, 1, 30)
    _brd6._readiness.report = _RReport6(total=7, ready=list(_real9),
                                        missing=['ZZZ001', 'ZZZ002'],
                                        latest=_pdc.Timestamp('2026-01-05'))
    _brd6._readiness._render_readiness()
    check("★ §7-B10 滞后提示：本地到 2026-01-05、最近交易日 2026-01-30 ⇒ 结果区现「滞后…交易日」+引导",
          '滞后' in _brd6.lbl_empty.text()
          and '更新到最新' in _brd6.btn_empty_action.text()
          and '待更新' in _brd6.lbl_receipt.text())
    # 无滞后（本地已到最近交易日）⇒ 不提示滞后
    _brd6._readiness.report = _RReport6(total=7, ready=list(_real9),
                                        latest=_pdc.Timestamp('2026-01-30'))
    _brd6._readiness._render_readiness()
    check("§7-B10 不滞后（本地=最近交易日）⇒ 结果区不出现「滞后」",
          '滞后' not in _brd6.lbl_empty.text())
    # M2 基准日说明（STEP 4）：上限=本地最新 + hint 回显
    _scan6._date_touched = False
    _scan6._readiness._calibrate_asof_date(
        _RReport6(total=1, ready=['x'], latest=_pdc.Timestamp('2026-01-20')))
    check("★ §7-B10 M2 基准日诚实化：hint 说明「上限=本地最新」且 date_asof 上限抬到本地最新",
          '上限=本地最新' in _scan6.lbl_asof_hint.text()
          and _scan6.date_asof.maximumDate() == _QDate6(2026, 1, 20))

    # §7-B10 修正：基准日覆盖诚实提示（M2）—— 多数文件滞后、仅少数覆盖基准日 ⇒ 明说覆盖 N/total
    _scan6._outcome = None
    _scan6._symbols = list(_syms9)
    _scan6._readiness._calendar = _cal9
    _scan6._readiness.trading_target = _dtm6.date(2026, 1, 30)
    _scan6._readiness.report = _RReport6(
        total=7, ready=list(_real9), latest=_pdc.Timestamp('2026-01-30'),
        lasts=[_pdc.Timestamp('2026-01-05')] * 6 + [_pdc.Timestamp('2026-01-30')])
    _scan6._readiness._render_readiness()
    check("★ §7-B10 基准日覆盖诚实提示：基准日当天仅 1/7 有数据 ⇒ 结果区明说「仅 1/7 只有数据」（不撑顶栏）",
          '仅 1/7 只有数据' in _scan6.lbl_empty.text()
          and '只有数据' not in _scan6.lbl_receipt.text())

    # ---- ⑤ bulk_download「全市场扫描就绪」预设（D6-2）----
    _dlg9 = _BDD6(win)
    _dlg9._apply_scan_ready_preset()
    check("★「全市场扫描就绪」一键预设：来源=全A · 起点 2016-01-01 · 不全量重下",
          _dlg9._radios['all'].isChecked()
          and _dlg9.date_start.date() == _QDate6(2016, 1, 1)
          and not _dlg9.chk_force.isChecked())
    _dlg9.deleteLater()
except Exception as _e:  # noqa: BLE001
    check(f"就绪度体检/补齐断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# ★ §7-B10 · M1 回测区间默认终点 / 滞后自动补 / 回退回执
# ==========================================
try:
    import pandas as _pd10
    from datetime import datetime as _dtm10, timedelta as _td10
    from PyQt6.QtCore import QDate as _QD10
    from data.trade_calendar import latest_settled_trading_day as _lstd10

    _btv = view                     # SingleStockBacktestView
    _f10 = _btv.flow

    # ① 迁移护栏：控件/方法名不变（薄壳护栏）
    check("M1 迁移护栏：date_end/date_start/cmb_range_preset/lbl_range_note 齐",
          all(hasattr(_btv, a) for a in
              ('date_end', 'date_start', 'cmb_range_preset', 'lbl_range_note')))

    # ② _on_calendar：默认终点精修到"最近已定稿交易日"（与实现同一判据，免时间竞态）
    _tday = _dtm10.now().date()
    _cal = [(_tday - _td10(days=i)) for i in range(5, -1, -1)]
    _f10._on_calendar(_cal)
    _exp = _lstd10(calendar=_cal)
    check("§7-B10 默认终点 = 最近已定稿交易日（date_end 被拨到该日）",
          _exp is not None
          and _btv.date_end.date() == _QD10(_exp.year, _exp.month, _exp.day))
    check("§7-B10 日历就绪回执非空（不静默）",
          '最近交易日' in _btv.lbl_range_note.text())

    # ③ 离线回退：拿不到日历 → 保持系统日 + 明确回执
    _before = _btv.date_end.date()
    _f10._on_calendar(None)
    check("§7-B10 离线：date_end 不被乱改", _btv.date_end.date() == _before)
    check("§7-B10 离线：回执提示未取到日历/离线",
          ('离线' in _btv.lbl_range_note.text()
           or '未取到交易日历' in _btv.lbl_range_note.text()))

    # ④ 滞后回退 + 回执 + 定格快照同步（绝不静默截断）
    _btv.date_end.setDate(_QD10(2026, 1, 1))
    _btv._last_meta = {"end_date": "2026-01-01"}
    _stale_df = _pd10.DataFrame({'date': _pd10.to_datetime(
        ['2025-06-01', '2025-06-02', '2025-06-03'])})
    _f10._apply_end_date_receipt(_stale_df)
    check("§7-B10 回退：date_end 拨到有数据那天",
          _btv.date_end.date() == _QD10(2025, 6, 3))
    check("§7-B10 回退：短回执不撑窗（单行只留短文本），完整说明入 tooltip",
          '未达目标终点' in _btv.lbl_range_note.toolTip()
          and len(_btv.lbl_range_note.text()) < 40)
    check("§7-B10 回退：_last_meta.end_date 同步（导出口径诚实）",
          _btv._last_meta['end_date'] == '2025-06-03')

    # ⑤ 只回退不前移：数据比目标终点更新时不动 date_end
    _btv.date_end.setDate(_QD10(2025, 1, 1))
    _f10._apply_end_date_receipt(_stale_df)
    check("§7-B10 只回退不前移（用户手动更早终点被保留）",
          _btv.date_end.date() == _QD10(2025, 1, 1))

    # ⑥⑦ 滞后自动补 / 已齐 —— 用全新 BacktestFlow + 假 page（与真实方法同构、无实例态污染）
    _today_qd = _QD10.currentDate()
    _stale_last_qd = _today_qd.addMonths(-3)
    _stale_df2 = _pd10.DataFrame({'date': _pd10.to_datetime([
        _stale_last_qd.addDays(-2).toString('yyyy-MM-dd'),
        _stale_last_qd.addDays(-1).toString('yyyy-MM-dd'),
        _stale_last_qd.toString('yyyy-MM-dd')])})

    _sync_start = []

    class _StubSyncOnce:
        def __init__(self, *a, **k):
            self.finished = _StubSig()

        def start(self):
            _sync_start.append(1)

    class _NeedD:
        def __init__(self, d):
            self._d = d

        def date(self):
            return self._d

    class _LakeD:
        def __init__(self, df):
            self._df = df

        def load_data(self, zone, key, **r):
            return self._df

    _orig_sync = _btflow.SingleSyncWorker
    _btflow.SingleSyncWorker = _StubSyncOnce
    try:
        class _FakePage:
            pass

        # ⑥ 本地末日 < 目标终点（今天）→ 应起 SingleSyncWorker
        _pg = _FakePage()
        _pg.date_end = _NeedD(_today_qd)
        _pg.data_lake = _LakeD(_stale_df2)
        _pg.current_symbol = '600000'
        _fn = _btflow.BacktestFlow(_pg)
        _fn._set_busy = lambda *a, **k: None
        _fn._on_data_ready = lambda df: None
        _fn._prepare_stock_then_run()
        check("§7-B10 滞后自动补：本地末日<终点 → 起 SingleSyncWorker",
              len(_sync_start) == 1)

        # ⑦ 本地末日 >= 目标终点 → 不联网、直接进就绪链
        _sync_start.clear()
        _ready_calls = []
        _pg2 = _FakePage()
        _pg2.date_end = _NeedD(_stale_last_qd)
        _pg2.data_lake = _LakeD(_stale_df2)
        _pg2.current_symbol = '600000'
        _fn2 = _btflow.BacktestFlow(_pg2)
        _fn2._set_busy = lambda *a, **k: None
        _fn2._on_data_ready = lambda df: _ready_calls.append(df)
        _fn2._prepare_stock_then_run()
        check("§7-B10 已齐：不触发同步、直接进就绪链",
              len(_sync_start) == 0 and len(_ready_calls) == 1)
    finally:
        _btflow.SingleSyncWorker = _orig_sync
except Exception as _e:  # noqa: BLE001
    check(f"§7-B10 M1 区间断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# ★ §7-A2 · 回测结果图表导出（CSV 逐日净值列 + .xlsx 内嵌图）
# ==========================================
print("\n== §7-A2 · 回测结果图表导出（CSV 数据列 + xlsx 内嵌图）==")
try:
    import io as _ioA
    import pandas as _pdA
    from core.backtest import BacktestResult as _BRA, BacktestTrade as _TRA
    from ui.widgets.backtest_export import build_daily_series, compose_result_csv
    from ui.widgets.backtest_xlsx import _build_workbook, write_result_xlsx

    _dates = _pdA.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'])
    _eq = _pdA.DataFrame({'date': _dates, 'equity': [1.0, 1.1, 1.05, 1.2],
                          'in_market': [0, 1, 1, 1]})
    _tr = [_TRA(entry_date=_dates[1], exit_date=_dates[3], entry_price=10.0,
                exit_price=12.0, pnl=2.0, return_pct=0.2)]
    _resA = _BRA(symbol='600000', buy_expression='B', sell_expression='S',
                 start_date='2024-01-02', end_date='2024-01-05', trades=_tr, equity=_eq)
    _metaA = {'symbol': '600000', 'name': '测试', 'start_date': '2024-01-02',
              'end_date': '2024-01-05', 'segments': [], 'params_text': '',
              'buy_expr': 'B', 'sell_expr': 'S', 'risk': {},
              'fill': {'fill_mode': 'next_open', 'trigger_tick': 1}, 'index': None}

    # ① build_daily_series
    _dA = build_daily_series(_resA)
    check("build_daily_series 列齐且日期升序",
          list(_dA.columns) == ['date', 'equity', 'in_market', 'buy_price', 'sell_price']
          and _dA['date'].tolist() == sorted(_dA['date'].tolist()))
    check("买卖点落在成交日（1/3 买 10、1/5 卖 12），非交易日留空",
          float(_dA.loc[_dA.date == '2024-01-03', 'buy_price'].iloc[0]) == 10.0
          and float(_dA.loc[_dA.date == '2024-01-05', 'sell_price'].iloc[0]) == 12.0
          and _pdA.isna(_dA.loc[_dA.date == '2024-01-02', 'buy_price'].iloc[0]))

    # ② CSV 不再输出逐日净值段（按用户反馈去掉；看图靠 xlsx）
    _csvA = compose_result_csv(_resA, _metaA)
    check("CSV 只保留逐笔表头、不再含逐日净值段",
          '买入日期,买入价' in _csvA and '日期,净值,持仓,买入价,卖出价' not in _csvA)

    # ③ xlsx 内嵌图（对构建时的 Workbook 断言，openpyxl 读回会丢图）
    _wbA = _build_workbook(_resA, _metaA)
    check("xlsx 三个 sheet（回测明细 + 可见净值曲线 + 隐藏净值数据）",
          '回测明细' in _wbA.sheetnames and '净值曲线' in _wbA.sheetnames
          and '净值数据' in _wbA.sheetnames)
    check("逐日数据放隐藏 sheet（主表不刷屏）",
          _wbA['净值数据'].sheet_state == 'hidden'
          and _wbA['净值曲线'].sheet_state == 'visible')
    _wsA = _wbA['净值曲线']
    check("净值曲线 sheet 内嵌 ≥1 图且系列数 ≥3（净值+买+卖）",
          len(_wsA._charts) >= 1 and len(_wsA._charts[0].series) >= 3)
    # 真能存盘（BytesIO，不落真实目录）
    _bufA = _ioA.BytesIO()
    write_result_xlsx(_resA, _metaA, _bufA)
    check("write_result_xlsx 能写入字节流（非空）", _bufA.tell() > 0)
except Exception as _e:  # noqa: BLE001
    check(f"§7-A2 图表导出断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# ★ §7-A4 · 运行历史子页（列表/预览/选中/pin/载入回放/复用/重跑/送行情/删除 + 存档接线）
# ==========================================
print("\n== §7-A4 · 运行历史子页接线 ==")
try:
    import tempfile as _tf5
    import shutil as _sh5
    import pandas as _pd5
    from core.backtest import BacktestResult as _BR5, BacktestTrade as _BT5
    from data.backtest_archive import (SOURCE_MANUAL, BacktestArchive, build_record)
    from ui.widgets import backtest_flow as _bflow5
    from ui.widgets.backtest_history_ui import COL_PIN, _SignedValueDelegate

    _hv = win.page_backtest.page_history
    _sv5 = win.page_backtest.single_view
    check("市场回测页第4子页 = 运行历史（index 3）",
          _hv is not None and win.page_backtest.tabs.indexOf(_hv) == 3)

    def _settle5(seconds=0.4):
        """等防抖 / 事件循环跑完（★v1.46：搜索框起 220ms 防抖，不再每敲一字重读索引）。"""
        import time as _t5
        deadline = _t5.time() + seconds
        while _t5.time() < deadline:
            app.processEvents()
            _t5.sleep(0.02)

    # —— 版式护栏：kind 过滤 M1/M2/M3 都可选（★P4 已解禁）；数字着色走 delegate（选中行不叠色）——
    _kmodel = _hv.cmb_kind.model()
    check("kind 过滤：M1/M2/M3 都可选（★P4 已解禁，不再置灰“预留”）",
          _hv.cmb_kind.count() == 3 and all(_kmodel.item(i).isEnabled() for i in range(3))
          and '（预留）' not in _hv.cmb_kind.itemText(1))
    check("列表数字着色走 delegate（修『点一下就变色』）",
          isinstance(_hv.table.itemDelegate(), _SignedValueDelegate))
    check("版式分层：过滤条 + 列表/预览分栏 + 页脚设置",
          hasattr(_hv, 'filter_bar') and hasattr(_hv, 'splitter')
          and hasattr(_hv, 'settings') and _hv.splitter.count() == 2)

    # —— 用临时 root 喂存档，绝不碰真实目录 ——
    _root5 = _tf5.mkdtemp(prefix='jian_hist_')
    _hv.archive = BacktestArchive(root=_root5)
    _d5 = _pd5.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'])
    _eq5 = _pd5.DataFrame({'date': _d5, 'equity': [1.0, 1.1, 1.05, 1.2],
                           'in_market': [0, 1, 1, 1]})
    _res5 = _BR5('600000', 'B', 'S', '2024-01-02', '2024-01-05',
                 trades=[_BT5(entry_date=_d5[1], exit_date=_d5[3], entry_price=10.0,
                              exit_price=12.0, pnl=2.0, return_pct=0.2)], equity=_eq5)
    _meta5 = {'symbol': '600000', 'name': '长江电力', 'strategy_name': '绿蓝红',
              'start_date': '2024-01-02', 'end_date': '2024-01-05', 'segments': ['A:MA(C,5);'],
              'params_text': 'N=5', 'buy_expr': 'B', 'sell_expr': 'S', 'risk': {},
              'fill': {'fill_mode': 'next_open', 'trigger_tick': 1}, 'index': None}
    _meta5b = dict(_meta5, symbol='000001', name='平安银行', strategy_name='另一套')
    _rid5 = _hv.archive.save(build_record(_res5, _meta5, config=dict(_meta5)))
    _hv.archive.save(build_record(_res5, _meta5b, config=dict(_meta5b)))
    _hv.refresh()
    check("列表渲染出 2 行", _hv.table.rowCount() == 2)

    # —— 选中即预览（按下标点还行不行：改按 id 选中，杜绝行序漂移）——
    check("按 id 选中命中", _hv.table.select_by_id(_rid5) and _hv.table.current_id() == _rid5)
    check("选中后 _current 有值 + 预览头含标的/策略",
          _hv._current is not None and '600000' in _hv.lbl_head.text()
          and '绿蓝红' in _hv.lbl_head.text())
    check("预览 KPI 胶囊已填（累计/胜率/笔数）",
          '累计' in _hv.preview.pill_cum.text() and '胜率' in _hv.preview.pill_win.text()
          and _hv.preview.pill_trades.text() == '成交 1 笔')
    check("迷你净值曲线已画（含买卖点散点）",
          len([it for it in _hv.preview.chart.getPlotItem().items
               if isinstance(it, pg.ScatterPlotItem)]) >= 2)
    check("参数详情默认只给摘要，点开后补全（可折叠）",
          '区间' in _hv.preview.lbl_params.text()
          and '风控' not in _hv.preview.lbl_params.text())
    _hv.preview.btn_params.setChecked(True)
    check("展开参数详情 → 出现风控/成交/条件组",
          all(k in _hv.preview.lbl_params.text() for k in ('风控', '成交', '条件组')))
    _hv.preview.btn_params.setChecked(False)

    # —— pin：**必须保持选中**（用户实测"重点选不上"的根因）——
    _hv._on_pin()
    check("pin 后仍保持选中（不再整表重建清空选择）",
          _hv.table.current_id() == _rid5)
    check("pin 后该行 ★ 列已就地更新",
          _hv.table.item(0, COL_PIN).text() == '★'
          or _hv.table.item(1, COL_PIN).text() == '★')
    check("pin 后记录 pinned=True + 按钮变『取消重点』",
          _hv.archive.load(_rid5)['pinned'] is True
          and '取消' in _hv.preview.action_button('pin').text())
    _hv.chk_pinned.setChecked(True)
    check("『只看重点』过滤生效（2 行 → 1 行）", _hv.table.rowCount() == 1)
    _hv.chk_pinned.setChecked(False)
    _hv.ed_search.setText('平安')
    _settle5(0.5)                             # ★v1.46：搜索防抖 220ms ⇒ 等它落地
    check("搜索过滤生效（按策略/标的）", _hv.table.rowCount() == 1)
    _hv.ed_search.setText('')
    _settle5(0.5)

    # —— 载入查看 = 只读回放：不改写现场 / 禁导出 / 有横幅 / 净值曲线带买卖点 ——
    _prior = _BR5('000002', 'B', 'S', '2023-01-01', '2023-01-31', trades=[], equity=_eq5)
    _sv5._last_result = _prior
    _sv5._last_meta = {'symbol': '000002', 'name': '万科A'}
    _sv5._last_df = _pd5.DataFrame()
    _sv5._last_draws = []
    _hv.table.select_by_id(_rid5)
    _hv._on_view()
    check("载入查看：M1 进只读回放态 + 横幅出现（不是靠 tooltip 告诉用户）",
          _sv5._preview_mode is True and not _sv5._preview_bar.isHidden()
          and '只读回放' in _sv5.lbl_preview.text())
    check("只读回放**不改写现场**（_last_result/_last_meta 原样）",
          _sv5._last_result is _prior and _sv5._last_meta['symbol'] == '000002')
    check("只读回放期间**导出被禁用**（防导出『存档结果 + 旧参数』）",
          not _sv5.btn_export_result.isEnabled())
    check("回放的净值曲线画出买卖点（buy_at/sell_at → 散点）",
          len([it for it in _sv5.result.equity_chart.getPlotItem().items
               if isinstance(it, pg.ScatterPlotItem)]) >= 2)
    check("回放的 K 线页给出诚实提示（存档不含逐日 OHLC）",
          '历史存档' in getattr(_sv5.result, '_kline_hint_text', '')
          and _sv5.result._kline_state is None)
    _sv5.exit_preview()
    check("退出预览：现场恢复 + 导出恢复 + 横幅收起",
          _sv5._preview_mode is False and _sv5._last_result is _prior
          and _sv5.btn_export_result.isEnabled() and _sv5._preview_bar.isHidden())

    # —— 手动『存为历史』入口（自动存档关掉时的兜底）——
    _orig_arc_cls = _bflow5.BacktestArchive
    _bflow5.BacktestArchive = lambda *a, **k: _orig_arc_cls(root=_root5)
    _sv5._last_result = _res5
    _sv5._last_meta = _meta5
    _sv5._last_config = dict(_meta5)
    _manual_id = _sv5.save_to_history()
    check("💾 存为历史：手动入口落一份 source=manual",
          bool(_manual_id)
          and _hv.archive.load(_manual_id)['source'] == SOURCE_MANUAL)

    # —— 自动存档接线：开关开 + 定格 config ⇒ flow 落一份 ——
    _pref_module.preferences.set("backtest_archive", {"auto": True})
    _n_before = len(_hv.archive.list())
    _sv5.flow._auto_archive(_res5)
    _auto_id = _sv5._last_archive_id
    check("自动存档接线：开关开时 flow 落一份快照（+1）",
          len(_hv.archive.list()) == _n_before + 1 and bool(_auto_id))
    check("自动存档**用发起瞬间定格的 config**（不是调用时的编辑器状态）",
          _hv.archive.load(_auto_id)['config']['symbol'] == '600000')
    _pref_module.preferences.set("backtest_archive", {"auto": False})
    _sv5.flow._auto_archive(_res5)
    check("自动存档开关关掉时不再落盘", len(_hv.archive.list()) == _n_before + 1)
    # ★v1.42：上面那行 `auto=False` **故意不还原成 True** —— §7-A4 之后还有
    #   `_on_rerun()` 真起异步回测，它在后面任意一段转事件循环时才回包
    #   ⇒ 若此时开关是 True，就会把快照写进**真实** `~/.jian_data/backtest_results/`
    #   （收尾自检会红，且红得飘忽：取决于那次异步回测跑不跑得完）。
    _bflow5.BacktestArchive = _orig_arc_cls     # 存档类已用完，尽早还原（后续段落不再打桩）

    # —— 复用参数 / 重跑 / 送行情页 ——
    _hv.table.select_by_id(_rid5)
    _hv._on_reuse()
    check("复用参数：M1 切到该标的 + 退出预览态 + 函数段已还原",
          _sv5.current_symbol == '600000' and _sv5._preview_mode is False
          and _sv5.current_formula_segments() == ['A:MA(C,5);'])
    _hv._on_rerun()
    check("重跑：复用参数后确实触发了 M1 运行流程（条件缺失时安全退出，不联网）",
          _sv5.current_symbol == '600000')

    _sent = {}
    _orig_send = win.send_formula_to_market
    win.send_formula_to_market = (lambda segs, params='':
                                  _sent.update(n=len(segs), params=params) or len(segs))
    try:
        _hv._on_send_to_market()
    finally:
        win.send_formula_to_market = _orig_send
    check("送行情页：经主窗口转交存档函数段（两页互不 import）",
          _sent.get('n') == 1 and _sent.get('params') == 'N=5')

    # —— 删除（二次确认已打桩为 Yes）——
    _n_before_del = len(_hv.archive.list())
    _hv.table.select_by_id(_rid5)
    _hv._on_delete()
    check("删除后列表少一行（删的是存档文件本身）",
          len(_hv.archive.list()) == _n_before_del - 1 and _hv.table.rowCount() >= 0)
    check("删除后列表选中态已清空（不给幽灵选中）", _hv.table.current_id() is None)
    _hv.refresh()
    check("刷新后行数与存档数一致",
          _hv.table.rowCount() == len(_hv.archive.list()))

    # ★P4 / v1.46：M2 扫描快照落档 → kind 声明表驱动列表 → 四态占比条预览 → 复用路由
    from data.backtest_archive import (KIND_M1 as _K1, KIND_M2 as _K2, KIND_M3 as _K3,
                                       build_scan_record as _bsr4)
    from ui.widgets.history_kinds import KIND_SPECS as _KS4, spec_of as _spec4
    _cfg4 = {'scope': 0, 'index_code': '', 'formula': 'COND := C > MA(C,20);',
             'params': 'N=20', 'thresholds': {'min_amount': 5e7, 'min_bars': 250,
                                              'exclude_st': True}, 'adjust': 'qfq'}
    _counts4 = {'total': 300, 'hit': 64, 'miss': 232, 'insufficient': 3, 'filtered': 1, 'valid': 296}
    _rid4 = _hv.archive.save(_bsr4(
        _cfg4, kind=_K2, scope_label='沪深300 · 300只', scope_code='sh000300',
        counts=_counts4, asof=_d5[1]))
    _e4 = next((e for e in _hv.archive.list(kind=_K2) if e['id'] == _rid4), None)
    check("★ P4：M2 扫描快照落档、list(kind=M2) 可查、hit/valid 进索引",
          bool(_rid4) and _e4 is not None and _e4.get('hit') == 64 and _e4.get('valid') == 296)
    check("★★ v1.46：范围名**带指数名 + 指数代码**（旧版只存「指数成分 300只」⇒ 认不出是哪个指数）",
          _e4.get('scope_label') == '沪深300 · 300只' and _e4.get('scope_code') == 'sh000300'
          and _e4.get('condition_label', '').endswith('1段'))
    check("★ v1.46：M2/M3 不再借 M1 的键（total_trades / win_rate / cumulative_return 一律 None）",
          _e4.get('total_trades') is None and _e4.get('win_rate') is None
          and _e4.get('cumulative_return') is None)
    check("★ v1.46：kind 声明表三种齐全、列数一致、未知 kind 安全回落 M1",
          set(_KS4) == {_K1, _K2, _K3} and len(_KS4[_K2].columns) == 9
          and _spec4('M9').kind == _K1)
    _hv.cmb_kind.setCurrentIndex(
        [_hv.cmb_kind.itemData(i) for i in range(_hv.cmb_kind.count())].index(_K2))
    check("★ P4：切到 M2 后表头变（范围/命中率/命中/数据不足）且只剩 M2 行",
          _hv.table.horizontalHeaderItem(2).text() == '范围'
          and _hv.table.horizontalHeaderItem(5).text() == '命中率'
          and _hv.table.horizontalHeaderItem(7).text() == '数据不足'
          and _hv.table.rowCount() == 1)
    check("★ v1.46：过滤轴对 M2/M3 换成「范围」并列出出现过的范围（旧版写死'标的'、且永远只有'全部'）",
          _hv.filter_bar.lbl_facet.text() == '范围'
          and _hv.cmb_facet.findData('sh000300') >= 0)
    _hv.table.select_by_id(_rid4)
    _sel4 = _hv.preview
    check("★ v1.46：M2 预览走**四态占比条**（不再照抄 M1 的累计/胜率/成交/平均单笔胶囊）",
          _sel4.statbar.isVisibleTo(_sel4) and not _sel4.chart.isVisibleTo(_sel4)
          and not _sel4.pills_row.isVisibleTo(_sel4)
          and '有效样本 296 / 300' in _sel4.statbar.lbl_head.text()
          and '命中 64' in _sel4.statbar.lbl_legend.text())
    check("★ v1.46（用户拍板）：M2/M3 动作集 = 复用/重跑/重点/删除 —— **无「载入查看」**"
          "（横截面无净值可回放）且**无「送行情页」**（统计口径不针对个股）",
          not _sel4.action_button('view').isEnabled()
          and _sel4.action_button('reuse').isEnabled()
          and _sel4.action_button('rerun').isEnabled()
          and _sel4.action_button('pin').isEnabled()
          and not _sel4.action_button('send').isEnabled()
          and not _sel4.action_button('send').isVisibleTo(_sel4))
    check("★ v1.46：运行历史页钉**开源字体栈** + 代码块走**开源等宽栈**"
          "（§10-15 字体版权纪律；**禁止点名专有字体**）",
          any('Source Han Sans' in f for f in _hv.font().families())
          and any('Noto Sans' in f for f in _hv.font().families())
          and 'JetBrains Mono' in _sel4.txt_formula.styleSheet()
          and 'Consolas' not in _sel4.txt_formula.styleSheet())
    check("★ v1.46：M2 条件**全文**在预览里（可直接复制）+ 粗筛摘要 —— 回答『到底有没有存函数』",
          'MA(C,20)' in _sel4.txt_formula.toPlainText()
          and '1 段' in _sel4.sect_condition.lbl_meta.text()
          and '成交额 ≥ 5000 万元' in _sel4.lbl_filter.text())
    _hv._on_view()
    check("★ v1.46：动作层自己校验 kind —— 拿 M2 存档点「载入查看」不进 M1 只读回放（不靠按钮灰）",
          _sv5._preview_mode is False and '横截面' in _hv.settings.lbl_receipt.text())
    _sent4b = {}
    _orig_send4b = win.send_formula_to_market
    win.send_formula_to_market = (lambda segs, params='':
                                  _sent4b.update(n=len(segs)) or len(segs))
    try:
        _hv._on_send_to_market()
    finally:
        win.send_formula_to_market = _orig_send4b
    check("★ v1.46（用户拍板）：拿 M2 存档点「送行情页」**被动作层拒掉**（不靠按钮隐藏）"
          "+ 诚实回执『不针对个股』",
          'n' not in _sent4b and '不针对个股' in _hv.settings.lbl_receipt.text())
    _rerun4 = {}
    _orig_req4 = _scan.request_run
    _scan.request_run = lambda: _rerun4.update(called=True)
    try:
        _hv.table.select_by_id(_rid4)
        _hv._on_rerun()
    finally:
        _scan.request_run = _orig_req4
    check("★★ v1.46：M2「重跑」走 `request_run`（等名单+体检就绪再扫 —— 旧版直接 start_scan "
          "对指数成分必空跑、对同步范围必弹'体检未完成'闸门框）",
          _rerun4.get('called') is True
          and 'MA(C,20)' in _scan._formula_pane.txt_formula.toPlainText())
    check("★ v1.46：M2 页真的有 `request_run` 薄壳（不靠测试打桩才发现没实现）",
          callable(getattr(win.page_backtest.page_breadth, 'request_run', None)))
    _scan._formula_pane.txt_formula.setPlainText('清空占位')
    _hv._on_reuse()
    check("★ P4：M2 存档「复用参数」路由到 M2 页并 apply_config（formula 落地）",
          'MA(C,20)' in _scan._formula_pane.txt_formula.toPlainText())
    _hv.cmb_kind.setCurrentIndex(0)          # 还原 M1，不影响后续

    _bflow5.BacktestArchive = _orig_arc_cls
    _sh5.rmtree(_root5, ignore_errors=True)
except Exception as _e:  # noqa: BLE001
    check(f"§7-A4 运行历史接线断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# ★ §7-E2 · 批量预下载的竞态判据改用公共件 JobGuard（P4 顺手项 · v1.38）
# ==========================================
print("\n== §7-E2 · 批量预下载 JobGuard 收编（P4）==")
try:
    from ui.dialogs.bulk_download import BulkDownloadDialog
    from ui.workers import JobGuard as _JG2

    _dlg2 = BulkDownloadDialog(win, parent=win)
    check("★ P4：批量预下载的竞态判据已改用公共件 JobGuard（手写 `_cons_token` 退役）",
          isinstance(_dlg2._cons_guard, _JG2) and not hasattr(_dlg2, "_cons_token"))
    _stale = _dlg2._cons_guard.next()
    _fresh = _dlg2._cons_guard.next()
    _dlg2._symbols = ["SENTINEL"]
    _dlg2._on_constituents({"ok": True, "symbols": ["600519"]}, _stale)   # 迟到 ⇒ 必须丢弃
    check("迟到回包被丢弃（不覆盖新结果）", _dlg2._symbols == ["SENTINEL"])
    _dlg2._on_constituents({"ok": True, "symbols": ["600519", "000001"]}, _fresh)
    check("最新回包正常生效（2 只）", _dlg2._symbols == ["600519", "000001"])
    _dlg2.close()
except Exception as _e:  # noqa: BLE001
    check(f"§7-E2 批量预下载 JobGuard 断言整段抛异常: {type(_e).__name__}: {_e}", False)

# ==========================================
# ★v6.66 · 「不复权」分区的**下载入口**（用户 2026-09-25 实测："预下载从来没补过这里"）
#   两条死路（本次一并修）：
#     ① 批量预下载**没有口径选择** ⇒ 永远只写 `kline_daily`（前复权）；
#     ② 数据管理页对一个**空分区**没入口（表里没有任何行可勾 ⇒ 更新/全量按钮恒灰）
#        —— 截图实证：`kline_daily_raw` 只有 1 项，搜索 300803 得到空表，想补也无从下手。
# ==========================================
print("\n== v6.66 · 不复权分区下载入口（批量口径选择 + 空分区回落）==")
try:
    from data.sync_service import (ZONE_INDEX as _ZI16, ZONE_KLINE as _ZK16,
                                   ZONE_KLINE_RAW as _ZKR16)  # noqa: E402
    from ui.dialogs.bulk_download import BulkDownloadDialog as _BD16  # noqa: E402

    _dlg16 = _BD16(win, win)
    _dlg16._radios["paste"].setChecked(True)
    _dlg16.txt_paste.setPlainText("300803")
    check("★ v6.66：批量预下载有「口径」选择，默认前复权（旧版没有这一项）",
          _dlg16.cmb_adjust.count() == 3 and _dlg16.cmb_adjust.currentData() == "qfq")
    check("★ v6.66：口径=前复权 ⇒ 只写 kline_daily", _dlg16._zones_to_download() == [_ZK16])
    _dlg16.cmb_adjust.setCurrentIndex(_dlg16.cmb_adjust.findData("raw"))
    check("★ v6.66：口径=不复权 ⇒ 写 kline_daily_raw（**旧版根本没有这条路** ⇒ 该分区永远是空的）",
          _dlg16._zones_to_download() == [_ZKR16])
    _dlg16.cmb_adjust.setCurrentIndex(_dlg16.cmb_adjust.findData("both"))
    check("★ v6.66：口径=两个都下 ⇒ 两个分区各一份（两份数据互推不出来，只能各存各下）",
          _dlg16._zones_to_download() == [_ZK16, _ZKR16])
    check("★ v6.66：预估按「只数 × 口径数」算并把口径写出来（别少报一半耗时）",
          "前复权 + 不复权" in _dlg16.lbl_estimate.text())

    _sent16 = []
    _orig_submit16 = win.downloads.submit
    win.downloads.submit = (lambda label, syms, **kw:
                            (_sent16.append((label, list(syms), kw.get("zone")))
                             or len(_sent16)))
    try:
        _dlg16._start()
    finally:
        win.downloads.submit = _orig_submit16
    check("★ v6.66：点「开始下载」真提交**两个任务**，任务名带口径（在下载条/队列里认得出是哪个）",
          [z for _, _, z in _sent16] == [_ZK16, _ZKR16]
          and all(("前复权" in lab or "不复权" in lab) for lab, _, _ in _sent16))
    check("★ v6.66：两个任务 id 都记下了（回包过滤与「停止本任务」要认一组）",
          len(_dlg16._job_ids) == 2)

    _dlg16._radios["index_preset"].setChecked(True)
    check("★ v6.66：指数预设来源 ⇒ 口径选择**禁用并说明**（指数没有复权概念，不是藏起来）",
          _dlg16._zones_to_download() == [_ZI16] and not _dlg16.cmb_adjust.isEnabled())
    _dlg16.close()

    # ---- 数据管理页：空分区也能把新标的下进来 ----
    _dm16 = win.page_data
    _dm16._current_zone = _ZKR16        # 直接切到"不复权"（空的那一个）
    _dm16._items = []
    _dm16._checked.clear()
    _dm16.txt_filter.setText("300803")
    _dm16._render_items()
    _dm16._sync_ops_enabled()
    check("★★ v6.66：空分区 + 过滤框有代码 ⇒ **下载入口可用**"
          "（旧版表里没行可勾 ⇒ 更新/全量按钮恒灰 = 用户无路可走）",
          _dm16._sync_targets() == ["300803"]
          and _dm16.btn_force.isEnabled() and _dm16.btn_sync.isEnabled())
    check("★ v6.66：但「删除」仍**只认勾选**（不许按过滤框删一个并不在本地的名字）",
          not _dm16.btn_delete.isEnabled())
    check("★ v6.66：界面说清「现在按谁下载」（按钮突然可点不能显得莫名其妙）",
          "300803" in _dm16.lbl_selected.text() and "过滤框" in _dm16.lbl_selected.text())
    check("★ v6.66：空分区把出路写在状态行（旧版这里一声不吭）",
          "本分区当前为空" in _dm16.lbl_status.text())
    _dm16.txt_filter.setText("平安")      # 中文名/非代码 ⇒ 不猜
    _dm16._render_items()
    check("★ v6.66：过滤框不是代码形态（中文名）⇒ **不给**下载入口，不乱猜",
          _dm16._sync_targets() == [])
    _dm16.txt_filter.setText("")
    _dm16._render_items()

    # ---- 「抓的是哪一份」必须**看得见**（用户实测反馈："点了云端同步，抓的不是我要的那份"）----
    import pathlib as _pl16b  # noqa: E402

    from data.sync_service import ADJUST_NONE as _AN16, ADJUST_QFQ as _AQ16  # noqa: E402
    from ui.widgets import readiness_flow as _rf16  # noqa: E402

    _adj_back16 = mkt.current_adjust
    _per_back16 = mkt.current_period
    mkt.current_period = "D"
    mkt.current_adjust = _AN16
    mkt._sync_period_widgets()
    _tt_raw16 = mkt.btn_sync.toolTip()
    check("★ v6.66：切到不复权 ⇒「云端同步」tooltip 明说目标含 **不复权 · kline_daily_raw**",
          "不复权" in _tt_raw16 and "kline_daily_raw" in _tt_raw16)
    mkt.current_adjust = _AQ16
    mkt._sync_period_widgets()
    # ★v6.67（用户拍板）**取代** v6.66 的"tooltip 随口径变"：这条按钮现在**恒**同步两份，
    #   所以两个口径下的说明必须**一致**（口径不再是它的差异点）—— 断言跟着改口径，不是放宽。
    check("★ v6.67：两个口径下 tooltip **都写\"同时同步两份\"**（取代 v6.66 的\"随口径变\"）",
          "同时同步两份" in _tt_raw16 and "同时同步两份" in mkt.btn_sync.toolTip())
    mkt.current_adjust = _adj_back16
    mkt.current_period = _per_back16
    mkt._sync_period_widgets()

    check("★★ v6.66：M2/M3 的「更新到最新」写明**口径固定 = 前复权日线**"
          "（回测/扫描口径与行情页图表口径是两件事，用户问过）",
          "前复权" in win.page_backtest.page_scan.btn_sync.toolTip()
          and "前复权" in win.page_backtest.page_breadth.btn_sync.toolTip())
    check("★ v6.66：回测页补数据的回执也点名口径（不是只写在 tooltip 里）",
          "本地前复权日线未到" in _pl16b.Path("ui/widgets/backtest_flow.py").read_text(
              encoding="utf-8"))
    check("★ v6.66：M1/M2/M3 的同步口径只有一个出口（`SYNC_CALIBER_LABEL`），回执直接引用它",
          _rf16.SYNC_CALIBER_LABEL == '前复权日线'
          and '口径 {SYNC_CALIBER_LABEL}' in _pl16b.Path(
              "ui/widgets/readiness_flow.py").read_text(encoding="utf-8"))

    # ---- ★v6.67（用户拍板）：一次点「云端同步」必须**同时下载前复权与不复权** ----
    from PyQt6.QtCore import QObject as _QO67, pyqtSignal as _PS67  # noqa: E402

    import ui.widgets.desk_data as _dd67  # noqa: E402

    _started67: list = []

    class _FakeWorker67(_QO67):
        finished = _PS67(dict)

        def __init__(self, symbol, zone=None, force_full=False, parent=None, period=None):
            super().__init__(parent)
            _started67.append(zone)

        def start(self):
            pass

    _orig_w67 = _dd67.SingleSyncWorker
    _dd67.SingleSyncWorker = _FakeWorker67
    try:
        mkt.current_symbol = 'sh600000'
        mkt.current_adjust = _AQ16
        mkt.current_period = "D"
        _started67.clear()
        # ⚠ 前面的分节把 `mkt.sync_cloud` 换成了 lambda（实例属性会遮蔽类方法）⇒ 直接调行为模块
        mkt._data.sync_cloud()
        check("★★ v6.67：一次点「云端同步」⇒ **两个口径各起一次取数**（前复权 + 不复权）",
              _started67 == [_ZK16, _ZKR16])
        check("★ v6.67：进度回执点名两份（旧版只写\"正在同步…\"）",
              '前复权' in mkt.lbl_sync_status.text()
              and '不复权' in mkt.lbl_sync_status.text())
        check("★ v6.67：按分区**各一个**互斥件（`SingleSyncGate` 单占位 ⇒ 两个口径必须两个实例）",
              len(mkt._data._gates) >= 2
              and mkt._data._gates[_ZK16] is not mkt._data._gates[_ZKR16])
        # 只回来一份 ⇒ 不收尾（否则汇总回执会缺一份、按钮提前恢复）
        mkt._on_sync_finished({'ok': True, 'symbol': 'sh600000', 'zone': _ZKR16,
                               'period': '', 'skipped': True, 'added': 0}, _ZKR16)
        check("★ v6.67：一份回来**不收尾**（按钮仍禁用、回执不写\"同步完成\"）",
              not mkt.btn_sync.isEnabled()
              and '同步完成' not in mkt.lbl_sync_status.text())
        mkt._on_sync_finished({'ok': True, 'symbol': 'sh600000', 'zone': _ZK16,
                               'period': '', 'added': 12, 'rescaled': True}, _ZK16)
        _sum67 = mkt.lbl_sync_status.text()
        check("★ v6.67：两份收齐才收尾，汇总回执分别点名两份（含\"已重算整段\"）",
              mkt.btn_sync.isEnabled() and '同步完成' in _sum67
              and '前复权' in _sum67 and '不复权' in _sum67 and '已重算整段' in _sum67)
        check("★ v6.67：tooltip 改成\"同时同步两份\"（旧文案写的是\"当前口径那一份\"）",
              '同时同步两份' in mkt.btn_sync.toolTip())
    finally:
        _dd67.SingleSyncWorker = _orig_w67
        mkt._data._gate_for(_ZK16).release()
        mkt._data._gate_for(_ZKR16).release()
        mkt.current_adjust = _adj_back16
        mkt.current_period = _per_back16
        mkt._sync_period_widgets()
except Exception as _e16:  # noqa: BLE001
    check(f"v6.66 不复权下载入口断言整段抛异常: {type(_e16).__name__}: {_e16}", False)

# ==========================================
# §7-B1/B2 补漏 · 「需要动作」必须有**入口**（v1.41 · 用户实测反馈驱动 · §11.5-80）
#   现场（用户截图）：M2 范围切到「指数成分 · 中证500」，体检说"未下载 456"，
#   结果区却**没有任何更新入口**；上方还挂着旧范围(300)的统计，与 500 的就绪度同屏打架。
#   根因**三处**（本次一并治，不是只补那一处）：
#     ① 唯一入口是结果区**空态**按钮，而它只在"还没有扫描结果"时出现
#        ⇒ 一旦扫过一次，整页再也找不到"更新/补齐数据"的地方；
#     ② `resolve_scope` 从不清旧 `_outcome` ⇒ 旧统计与新就绪度混串，
#        且 `_render_readiness` 误以为"已有当前范围的结果"而不再给入口；
#     ③ 各处文案指称的按钮名（旧「⬇ 补齐缺失」）在 v6.47 改名后**已不存在** ⇒ 指路指到空处。
# ==========================================
print("\n== §7-B1/B2 补漏 · 需要动作必有入口 / 按钮名单一出口 / 范围切换清旧结果（v1.41）==")
try:
    import pathlib as _pl11  # noqa: E402

    from data.readiness import ReadinessReport as _RRep11  # noqa: E402
    from ui.widgets.custom_widgets import SYNC_ACTION_LABEL as _SAL11  # noqa: E402

    _m2_11 = win.page_backtest.page_scan
    _m3_11 = win.page_backtest.page_breadth

    # ---- ① 常驻入口：两页都有，且文字来自**唯一常量出口** ----
    check("★★ 两页都有**常驻**「更新到最新」按钮（旧版唯一入口藏在空态里 ⇒ 扫过一次就再也点不到）",
          hasattr(_m2_11, 'btn_sync') and hasattr(_m3_11, 'btn_sync')
          and _m2_11.btn_sync.text() == _SAL11 and _m3_11.btn_sync.text() == _SAL11)
    check("★ 空态按钮与常驻按钮**同文字**（同一个动作在页面上只有一种叫法）",
          _SAL11 == '⬆ 更新到最新交易日')

    # ---- ② 接线：点常驻按钮 ⇒ 走就绪度控制器的 update_latest（打桩，绝不联网）----
    _hit11 = []
    _orig_upd11_m3 = _m3_11._readiness.update_latest
    _orig_upd11_m2 = _m2_11._readiness.update_latest
    _m3_11._readiness.update_latest = lambda: _hit11.append(1)
    try:
        _m2_11._readiness.update_latest = lambda: _hit11.append(2)
        _m3_11.btn_sync.click()
        _m2_11.btn_sync.click()
    finally:
        # ⚠ 两页都要还原：只还原一半 = M2 永久留着桩函数，
        #   后面所有针对 M2 `update_latest` 的断言都在测桩（本批真实踩到）
        _m3_11._readiness.update_latest = _orig_upd11_m3
        _m2_11._readiness.update_latest = _orig_upd11_m2
    check("★ 两页的常驻按钮都真的接到 `update_latest`（按钮存在但没接线 = 假入口）",
          _hit11 == [1, 2])

    # ---- ③ 范围切换 ⇒ 旧结果必须作废（消除"旧统计 + 新就绪度"混串）----
    _m3_11._outcome = object()                       # 哨兵：假装上一范围有结果
    _m3_11.lbl_cal.setText('口径：沪深300 · 有效 295/300')
    _orig_start11 = _m3_11._readiness.start
    _m3_11._readiness.start = lambda *a, **k: None    # 不真跑体检（省时间、零副作用）
    try:
        # ⚠ 只切到**本地范围**（自选 / 全A）：索引 1 = 指数成分会真起 ConstituentsWorker 联网
        _m3_11.cb_scope.setCurrentIndex(2 if _m3_11.cb_scope.currentIndex() != 2 else 0)
    finally:
        _m3_11._readiness.start = _orig_start11
    _expect_key11 = (_m3_11.cb_scope.currentIndex(), '')
    check("★★ 换范围 ⇒ 旧 `_outcome` 作废 + 口径摘要清空（不许两套数字同屏打架）",
          _m3_11._outcome is None and _m3_11.lbl_cal.text() == ''
          and _m3_11._scope_key == _expect_key11)
    check("★ 范围没变时**不白丢结果**（同一范围重复解析 ⇒ `_scope_key` 不变、结果保留）",
          (_m3_11._flow._drop_stale_result(_expect_key11) is None
           and _m3_11._scope_key == _expect_key11))

    # ---- ④ 「已有结果」分支**不许抢结果区**（抢了会把刚扫出的结果藏起来）----
    _gap11 = _RRep11(total=5, missing=['A', 'B'], lasts=[])
    _m3_11._readiness.report = _gap11
    _m3_11.lbl_empty.setText('这是扫描结果的空态文字（不许被抢）')
    _m3_11._outcome = object()                       # 非 None ⇒ 走"已有结果"分支
    _m3_11._readiness._render_readiness()
    check("★ 已有结果时 `_render_readiness` **不调 set_empty**（否则 `empty_box.show()+chart.hide()`"
          " 会把用户刚扫出来的图/表藏掉 —— 比「没按钮」严重得多）",
          _m3_11.lbl_empty.text() == '这是扫描结果的空态文字（不许被抢）')

    # ---- ⑤ 坏文件也是"需要动作" ⇒ 必须给入口（旧版只给一句话）----
    _bad11 = _RRep11(total=5, unreadable={'X': '打不开'}, lasts=[])
    _m3_11._readiness.report = _bad11
    _m3_11._outcome = None
    _m3_11._readiness._render_readiness()
    check("★ 只有坏文件（无缺口）也**给「去数据管理」入口**（判据是「要不要用户动手」，"
          "不是「有没有缺口」）",
          _m3_11.btn_empty_action.text() == '去数据管理')

    # ---- ⑥ 源码级防漂移：旧按钮名彻底退役；core/data 不许指名 UI 按钮 ----
    _ui_src11 = ''.join(
        _pl11.Path(f).read_text(encoding='utf-8') for f in (
            'ui/widgets/scan_flow.py', 'ui/widgets/breadth_flow.py',
            'ui/widgets/readiness_flow.py', 'ui/widgets/scan_layout.py',
            'ui/widgets/breadth_layout.py'))
    check("★ 旧按钮名「补齐缺失」在 UI 层**彻底退役**（它已不是任何控件 —— 留着就会出现"
          "「文案指路到不存在的按钮」，本次缺陷的直接成因）",
          '补齐缺失' not in _ui_src11)
    _layer_src11 = (_pl11.Path('core/cross_section.py').read_text(encoding='utf-8')
                    + _pl11.Path('data/readiness.py').read_text(encoding='utf-8'))
    check("★ core/ 与 data/ **不许指名 UI 按钮**（分层纪律：它们曾写死「用结果区的…」，"
          "按钮一改名就全失联 ⇒ 只说「页面的下载入口」）",
          '补齐缺失' not in _layer_src11 and '更新到最新交易日' not in _layer_src11)
except Exception as _e11:  # noqa: BLE001
    check(f"§7-B1/B2 补漏 入口完整性断言整段抛异常: {type(_e11).__name__}: {_e11}", False)

# ==========================================
# §10-9 还清 · 数值控件宽度：「间隔(秒)」不再被截成 "0"（v1.42 · 用户实测反馈驱动）
#   现场：批量预下载弹窗预设 0.6，但控件被钉死在 64px ⇒ 原生上下箭头占掉 18~22px 后
#   文本区只剩约 30px，用户只看得见 "0"；而数据管理页同一个控件是 82px
#   ⇒ 同一件事两个尺寸，正是 §10-9「同类控件同一张脸 + 数值控件最小宽度 ≥ 72px」被破。
#   修法：宽度收成 `custom_widgets.double_spin / int_spin` 唯一工厂（**只给下限、不钉死宽度**）。
# ==========================================
print("\n== §10-9 · 数值控件宽度工厂（v1.42 · v1.45 已迁到下载设置对话框）==")
try:
    import pathlib as _pl12

    from core.preferences import DEFAULTS as _PDEF12  # noqa: E402
    from core.preferences import preferences as _prefs12  # noqa: E402
    from ui.dialogs.download_settings import DownloadSettingsDialog as _DSD12  # noqa: E402
    from ui.widgets.custom_widgets import SPIN_MIN_WIDTH as _SMW12  # noqa: E402
    from ui.widgets.custom_widgets import double_spin as _dsp12, int_spin as _isp12

    # v1.45：间隔/熍断旋钮已从两页搬进全局下载设置对话框 —— 宽度断言改验它的控件。
    _set12 = _DSD12()

    # ---- ① 真判据：文本区**放得下当前值**（不是"宽度看着顺眼"）----
    for _tag12, _spin12 in (("下载设置 间隔(秒)", _set12.spin_interval),
                            ("下载设置 连续失败熍断", _set12.spin_breaker)):
        _spin12.resize(_spin12.sizeHint())
        app.processEvents()
        _need12 = _spin12.fontMetrics().horizontalAdvance(_spin12.text())
        _line12 = _spin12.lineEdit().geometry().width()
        check(f"★ {_tag12}：文本区 {_line12}px 放得下 \"{_spin12.text()}\"（需 {_need12}px）",
              _line12 >= _need12)
        check(f"★ {_tag12}：minimumWidth={_spin12.minimumWidth()} ≥ {_SMW12}"
              f" 且宽度未被钉死（maximumWidth={_spin12.maximumWidth()}）",
              _spin12.minimumWidth() >= _SMW12 and _spin12.maximumWidth() > 16_000_000)

    # ---- ② 只修宽度，**不许顺手改数值口径**（从全局偏好预填）----
    #   ⚠ 隔离（v1.45 隐患修正）：默认值锁在**规格常量** `DEFAULTS`，实框只验
    #     「预填 == 当前已存偏好」。旧写法直接钉 `value()==0.6` ⇒ 用户一旦在下载设置里
    #     改过间隔就**假红**（非产品 bug：规格与用户数据混在了同一条断言里）。
    _cur_int12 = float((_prefs12.get("download_prefs") or {}).get("interval", 0.6))
    check("★ 间隔默认 0.6（规格常量）、范围 0~10、步长 0.1、预填==已存偏好（口径原样+隔离）",
          abs(float(_PDEF12["download_prefs"]["interval"]) - 0.6) < 1e-9
          and (_set12.spin_interval.minimum(), _set12.spin_interval.maximum()) == (0.0, 10.0)
          and abs(_set12.spin_interval.singleStep() - 0.1) < 1e-9
          and abs(_set12.spin_interval.value() - _cur_int12) < 1e-9)
    check("★ 并发框范围 1~4（K≤4，与不封 IP 取向一致）",
          (_set12.spin_concurrency.minimum(), _set12.spin_concurrency.maximum()) == (1, 4))

    # ---- ③ 工厂自身的契约（新页面误用也能被发现）----
    _probe12 = _dsp12(value=1.0, lo=0.0, hi=9.9, decimals=1)
    check("★ double_spin 步长跟着小数位（1 位→0.5 / 2 位→0.01 / 0 位→1），不写死",
          abs(_probe12.singleStep() - 0.5) < 1e-9
          and abs(_dsp12(decimals=2).singleStep() - 0.01) < 1e-9
          and abs(_dsp12(decimals=0).singleStep() - 1.0) < 1e-9)
    check("★ int_spin 与 double_spin 同一张脸（同 minimumWidth / 同高度）",
          _isp12().minimumWidth() == _probe12.minimumWidth()
          and _isp12().height() == _probe12.height())

    # ---- ④ 源码级防漂移 ----
    _ui_py12 = [p for p in _pl12.Path('ui').rglob('*.py')]
    _bad12 = [str(p) for p in _ui_py12
              if 'setFixedWidth(64)' in p.read_text(encoding='utf-8')]
    check("★ 全 ui/ 不再出现 `setFixedWidth(64)`（这类钉死宽度就是本次截字的成因）",
          not _bad12)
    _bulk12 = _pl12.Path('ui/dialogs/bulk_download.py').read_text(encoding='utf-8')
    _dm12b = _pl12.Path('ui/views/data_manager.py').read_text(encoding='utf-8')
    _set12src = _pl12.Path('ui/dialogs/download_settings.py').read_text(encoding='utf-8')
    check("★ 下载参数已收进设置对话框：bulk/data_manager 不再各自放间隔旋钮，"
          "download_settings 走工厂、不钉死宽度（否则又会出现“这页 64、那页 82”）",
          'spin_interval' not in _bulk12 and 'spin_interval' not in _dm12b
          and 'double_spin(' in _set12src
          and 'spin_interval.setFixedWidth' not in _set12src
          and 'NoWheelDoubleSpinBox()' not in _set12src)
    _set12.deleteLater()
except Exception as _e12:  # noqa: BLE001
    check(f"§10-9 数值控件宽度断言整段抛异常: {type(_e12).__name__}: {_e12}", False)

# ==========================================
# ★ §7-B11 · 后台下载队列 + 底部下载条 + 导航角标 + 非模态队列面板（v1.43）
#   现场（用户实测）：批量预下载是**模态弹窗**，而且 `SyncWorker(parent=弹窗)` ⇒
#   下载期间整个界面被冻住、窗口不能关，用户只能守着看进度。
#   修法：任务归属搬到主窗口的 `DownloadHub`（串行 K=1），进度改成三个**投影**：
#   底部下载条 / 导航角标 / 非模态队列面板。
#   ⚠ 全程把 `download_hub.SyncWorker` 打桩为不 `start()` 的假线程（§11.5-71②）。
# ==========================================
print("\n== §7-B11 · 后台下载队列 / 下载条 / 角标 / 队列面板（v1.43）==")
try:
    import pathlib as _pl13
    import re as _re13

    from ui import download_hub as _dhub13  # noqa: E402
    from ui.download_hub import (STATUS_DONE, STATUS_QUEUED, STATUS_RUNNING,  # noqa: E402
                                DownloadHub)
    from PyQt6.QtWidgets import (QDialog as _QDialog13,  # noqa: E402
                                 QLabel as _QLabel13,
                                 QProgressBar as _QProgressBar13,
                                 QPushButton as _QPushButton13)
    from ui.widgets.download_bar import DownloadBar  # noqa: E402
    from ui.widgets.download_queue_panel import DownloadQueuePanel  # noqa: E402

    _made13 = []

    class _StubWorker13(_QObject):
        progress = _pyqtSignal(int, int, str)
        failed = _pyqtSignal(str, str)
        finished = _pyqtSignal(dict)

        def __init__(self, symbols, zone=None, force_full=False, min_date=None,
                     policy=None, parent=None):
            super().__init__(parent)
            self._symbols = [str(s) for s in (symbols or [])]
            self.cancelled = False
            _made13.append(self)

        def start(self):
            pass                              # 打桩：绝不真起线程（否则跑测试=真下载）

        def cancel(self):
            self.cancelled = True

    _DONE = dict(ok=0, fail=0, skipped=0, added=0, aborted=False, aborted_by='',
                 symbols_failed=[])
    _orig13 = _dhub13.SyncWorker
    _dhub13.SyncWorker = _StubWorker13
    try:
        hub = DownloadHub()
        bar = DownloadBar(hub)
        panel = DownloadQueuePanel(hub)

        # ---- ① 空闲 ⇒ 不占界面 ----
        check("★ 空闲时下载条隐藏（不新增一块常驻“皮”）", bar.isHidden())
        check("★ 空面板不存任务数据（每次从队列现取）", panel.table.rowCount() == 0)

        # ---- ② 串行 K=1 ----
        j1 = hub.submit("全市场 A 股 日线", ["A", "B", "C"], origin="bulk")
        j2 = hub.submit("中证500 成分股", ["X", "Y"], origin="scan")
        check("★ 串行：只跑第一个，第二个停在排队中（与“宁可慢也不封 IP”一致）",
              hub.current.id == j1 and hub.get(j2).status == STATUS_QUEUED
              and len(_made13) == 1)
        check("★ 下载条随提交自动出现，并说出当前任务名",
              not bar.isHidden() and bar.lbl_name.text() == "全市场 A 股 日线")
        _made13[0].progress.emit(1, 3, "A")
        check("★ 进度广播到下载条（任务名/百分比/当前标的）",
              bar.lbl_txt.text().startswith("1/3") and "A" in bar.lbl_txt.text()
              and bar.bar.value() == 33)
        check("★ 排队数也说出来（用户要知道后面还有多少）", bar.lbl_queue.text() == "· 排队 1")

        # ---- ③ 完成 ⇒ 自动接跑下一个；回执说清成败 ----
        _made13[0].failed.emit("B", "无行情数据（代码有误？或已退市/长期停牌）")
        _made13[0].finished.emit(dict(_DONE, ok=2, fail=1, added=5,
                                      symbols_failed=["B"]))
        app.processEvents()
        check("★ 任务 1 完成 ⇒ 队列自动接跑任务 2（串行不断链）",
              hub.current is not None and hub.current.id == j2 and len(_made13) == 2)
        check("★ 完成回执含“失败 1”，且原因走 `failure_hint` 单出口",
              "失败 1" in hub.get(j1).receipt_text()
              and "退市" in hub.get(j1).hint_text)
        check("★ 任务状态标记正确（done / running）",
              hub.get(j1).status == STATUS_DONE and hub.get(j2).status == STATUS_RUNNING)

        # ---- ④ 防手残：同样的清单不重复入队 ----
        j3 = hub.submit("重复提交", ["X", "Y"], origin="scan")
        check("★ 同样的标的清单不重复入队（连点两下不会把 500 只抓两遍）",
              j3 == j2 and len(_made13) == 2)

        # ---- ⑤ 中断单个 / 重试失败 ----
        hub.cancel(j2)
        check("★ 中断只停当前任务（cancel 真的传到 worker）", _made13[1].cancelled)
        _made13[1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()
        check("★ 中断后状态=已中断，队列回到空坑位（不卡死）",
              hub.get(j2).status == "cancelled" and hub.current is None)
        j4 = hub.retry_failures(j1)
        check("★ 只重试失败清单（旧版只能“复制清单”再来一遍）",
              bool(j4) and hub.get(j4).symbols == ["B"])
        _made13[-1].finished.emit(dict(_DONE, ok=1, added=3))
        app.processEvents()
        check("★ 全部跑完 ⇒ activity 归零（角标会随之收起）",
              hub.is_busy() is False and hub.pending_count() == 0)

        # ---- ⑥ 队列面板：浮层形态 + 按样板呈现 + 列出全部（含已完成回看）----
        panel.refresh()
        check("★ 面板是**主窗口内的浮层**（不是 `_QDialog13` 独立窗口 ⇒ 不抢焦点/不进任务栏/拖不走）",
              not isinstance(panel, _QDialog13))
        check("★ 面板列出全部任务（运行过的都能回看，不只当前那一个）",
              panel.table.rowCount() == len(hub.jobs()))
        check("★ 面板底部有「只重试失败 / 复制失败清单 / 全部中断」三件（旧能力搬出弹窗）",
              all(hasattr(panel, n) for n in ('btn_retry', 'btn_copy', 'btn_stop')))
        # 按样板验收：头部统计胶囊 / 表内迷你进度条 + 状态胶囊 + 每行操作
        check("★ 头部有「运行中 N / 排队 N」统计胶囊（样板同款）",
              panel.lbl_run.text().startswith("运行中")
              and panel.lbl_queued.text().startswith("排队"))
        check("★ 表内进度是**迷你进度条**、状态是**彩色胶囊**（样板同款，不是纯文本）",
              panel.table.cellWidget(0, 1) is not None
              and panel.table.cellWidget(0, 1).findChild(_QProgressBar13) is not None
              and panel.table.cellWidget(0, 2) is not None
              and panel.table.cellWidget(0, 2).findChild(_QLabel13) is not None
              and 'background:' in panel.table.cellWidget(0, 2).findChild(_QLabel13).styleSheet())
        check("★ 每行都有操作按钮（运行中=中断 / 有失败=只重试失败）",
              panel.table.cellWidget(0, 3) is not None
              and panel.table.cellWidget(0, 3).findChild(_QPushButton13) is not None)
        # ★v1.43 收口二次（用户实测：贴顶直条 / 整格色块）——单元格内容必须**居中且不撑满**
        _ph83 = panel.table.cellWidget(0, 1).findChild(_QProgressBar13)
        _pill83 = panel.table.cellWidget(0, 2).findChild(_QLabel13)
        check("★ 进度条：高 6、宽 100（< 列宽 120）⇒ 两端圆弧 + 不铺满整格",
              _ph83.minimumHeight() == 6 and _ph83.maximumHeight() == 6
              and _ph83.minimumWidth() == 100)
        check("★ 状态是**圆角气泡**（radius 10 + 只有内容那么大，不是整格色块填充）",
              'border-radius:10px' in _pill83.styleSheet()
              and _pill83.sizeHint().width() < 104)
        bar.dismiss()
        check("★ 用户可以✕掉回执条（不是永久占位）", bar.isHidden())
        # ✕ 只在回执态出现：任务在跑时它按不动（投影会立刻弹回来）⇒ 不该给假按钮
        _q13 = hub.submit("进行中", ["Z9"], origin="bulk")
        check("★ 任务在跑时「✕」不出现（免得按了收不起来 = 假按钮）",
              not bar.btn_close.isVisible() and bar.btn_stop.isVisible())
        hub.cancel(_q13)
        _made13[-1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()
        check("★ 跑完后「✕」回来（回执可收起）", bar.btn_close.isVisible())

        # ---- ⑦ 不撑窗（§11.5-73：单行标签只放短状态）----
        check("★ 下载条的长文本标签水平策略 Ignored ⇒ 可缩不可撑大窗口",
              bar.lbl_txt.sizePolicy().horizontalPolicy()
              == bar.lbl_txt.sizePolicy().Policy.Ignored)

        # ---- ★回归：closeEvent 守卫 has_unfinished 必须是普通方法（曾误设 @property）----
        from ui.download_hub import DownloadHub as _DH13g  # noqa: E402
        check("★ has_unfinished 可当方法调用（主窗口 closeEvent 写的是 has_unfinished()；"
              "若退回 @property 会 'bool' object is not callable 且跳过 shutdown）",
              callable(_DH13g.has_unfinished))

        # ---- ⑧ 主窗口接线：三处视图同一个真源 ----
        check("★ 主窗口持有队列 + 底部条 + 角标（hub 与 engine 同级）",
              isinstance(win.downloads, DownloadHub)
              and win.download_bar._hub is win.downloads
              and win.nav_badge.isHidden())
        _rid13 = win.downloads.submit("角标测试", ["Q1", "Q2"], origin="bulk")
        app.processEvents()
        check("★ 真下载 ⇒ 导航角标亮起（任何页面瞥一眼就知道有活在跑）",
              win.downloads.is_busy() and not win.nav_badge.isHidden())
        win.show_download_queue()
        check("★ 点角标/详情 ⇒ 打开队列面板（懒建，不开下载不多一块界面）",
              win._download_panel is not None and not win._download_panel.isHidden())
        check("★ 浮层挂在**主窗口内容区**上、且钉在右下角（落在浮动下载条上方）",
              win._download_panel.parent() is win._right_panel
              and win._download_panel.x() >= 0 and win._download_panel.y() >= 0)
        win.downloads.cancel(_rid13)
        _made13[-1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()
        check("★ 全部结束后角标不再显示（不会亮着骗人）",
              win.downloads.current is None and win.nav_badge.isHidden())

        # ---- ⑨ 数据管理页：提交即返回，不再锁整页 ----
        _dm13 = win.page_data
        _dm13._items = [{"name": "600519", "bytes": 1, "rows": 10, "first": "2024-01-02",
                         "last": "2024-01-03"}]
        _dm13._checked = {"600519"}
        _dm13._current_zone = "kline_daily"
        _before13 = (_dm13.btn_sync.isEnabled(), _dm13.btn_bulk.isEnabled(),
                     _dm13.btn_rescan.isEnabled(), _dm13.btn_delete.isEnabled())
        _dm13._sync_selected(False)
        check("★ 提交后本页按钮状态**一个都没变**（旧版提交即把 8 个按钮锁到任务结束）",
              (_dm13.btn_sync.isEnabled(), _dm13.btn_bulk.isEnabled(),
               _dm13.btn_rescan.isEnabled(), _dm13.btn_delete.isEnabled()) == _before13)
        check("★ 任务进了主窗口队列，回执说清“已提交后台”",
              any(j.origin == "data_manager" for j in win.downloads.jobs())
              and "已提交到后台" in _dm13.lbl_status.text())
        win.downloads.cancel(None)
        _made13[-1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()

        # ---- ⑩ 源码级防漂移 ----
        _bd13 = _pl13.Path('ui/dialogs/bulk_download.py').read_text(encoding='utf-8')
        check("★ 旧版“关窗前硬等 15 秒”整套退役（线程不再属于弹窗 ⇒ 窗口随时可关）",
              '_try_stop_worker' not in _bd13 and '_worker = SyncWorker(' not in _bd13)
        _dm13s = _pl13.Path('ui/views/data_manager.py').read_text(encoding='utf-8')
        check("★ 预下载弹窗不再用模态 `exec()` 打开（“强制置顶无法操作其它界面”的直接根因；"
              "v1.45 设置对话框仍可模态，故只钉住预下载弹窗 `_bulk_dialog`）",
              '_bulk_dialog.exec' not in _dm13s and '.show()' in _dm13s
              and '_set_busy' not in _dm13s)
        _hub13s = _pl13.Path('ui/download_hub.py').read_text(encoding='utf-8')
        check("★ 队列不自造 QThread（§2：`ui/workers.py` 仍是全 app 唯一 QThread 定义处）",
              _re13.search(r'class\s+\w+\(QThread\)', _hub13s) is None)
        check("★ 新鲜度注入仍只有一处（队列不重复实现§7-E5 的日历注入）",
              'inject_expected_latest(' not in _hub13s)

        # ---- ⑪ v1.43 收口：cancel(全部) 必须给**排队中**的任务也发 finished ----
        #      漏发 ⇒ 消费方（M2/M3 的 _syncing、批量弹窗）永远收不到回包，页面卡在“进行中”。
        hub2 = DownloadHub()
        hub2.submit("跑着", ["1", "2"], origin="t")
        _b2 = hub2.submit("排着", ["3"], origin="t")
        _got2 = []
        hub2.job_finished.connect(lambda jid, st: _got2.append(jid))
        hub2.cancel(None)
        check("★ 「全部中断」给排队中的任务也发完成回包（否则页面永久卡在“进行中”）",
              _b2 in _got2 and hub2.get(_b2).status == "cancelled")
        _made13[-1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()
        check("★ 中断收尾后活动标记归零（角标不会一直亮着骗人）",
              hub2.is_busy() is False and hub2.pending_count() == 0)

        # ---- ⑫ 去重键必须认「起点 / 档力度」（否则第二个发起方的范围被静默忽略）----
        from data.sync_service import ThrottlePolicy as _TP13  # noqa: E402

        hub3 = DownloadHub()
        _k1 = hub3.submit("更新到最新", ["600000"], origin="t", min_date=None)
        _k2 = hub3.submit("从2016起", ["600000"], origin="t", min_date="20160101")
        _k3 = hub3.submit("同参重复", ["600000"], origin="t", min_date=None)
        _k4 = hub3.submit("同参但间隔不同", ["600000"], origin="t", min_date=None,
                          policy=_TP13(interval=5.0))
        check("★ 同样清单但**起点不同**不合并（否则第二方范围被静默忽略）", _k2 != _k1)
        check("★ 档力度不同也不合并（特意调慢的那轮不该被并进快的那轮）", _k4 != _k1)
        check("★ 完全同参的提交仍然合并（防手残不变）", _k3 == _k1)
        hub3.cancel(None)
        _made13[-1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()

        # ---- ⑬ 下载条「中断」= 只停当前，排队的不动 ----
        hub5 = DownloadHub()
        bar5 = DownloadBar(hub5)
        hub5.submit("跑", ["1"], origin="t")
        _r2 = hub5.submit("排", ["2"], origin="t")
        bar5._stop()
        check("★ 下载条「中断」只停当前任务，排队的不动（全停留给面板「全部中断」）",
              _made13[-1].cancelled and hub5.get(_r2).status == STATUS_QUEUED)
        _made13[-1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()
        hub5.cancel(None)
        _made13[-1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()

        # ---- ⑭ 单只互斥收敛成唯一公共件 SingleSyncGate ----
        from ui.download_hub import SingleSyncGate  # noqa: E402

        hub6 = DownloadHub()
        hub6.submit("批量占住 600519", ["600519"], origin="t")

        class _Owner13:
            pass

        _own = _Owner13()
        _own.downloads = hub6
        _g13 = SingleSyncGate(_own)
        check("★ 单只互斥：批量任务里的标的被认出来（不再各页手写 token）",
              _g13.blocked_by("600519", "kline_daily")
              and not _g13.blocked_by("000001", "kline_daily"))
        _g13.hold("000001", "kline_daily")
        check("★ 占位生效（反向也成立：批量此时也认得出 000001 有人在抓）",
              hub6.is_busy_for("000001", "kline_daily"))
        _g13.release()
        _g13.release()                     # 幂等：重复释放不报错
        check("★ 释放幂等、占位清零（漏调/重复调都不会永久占住这只标的）",
              not hub6.is_busy_for("000001", "kline_daily"))
        check("★ 拿不到队列时是**空操作**（假页面 / 单测不会炸）",
              not SingleSyncGate(None).blocked_by("600519"))
        hub6.cancel(None)
        _made13[-1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()

        # ---- ⑮ 源码级防漂移：token 只剩一处实现；下载条不再拿 cancel(None) 当「中断」----
        for _f13 in ('ui/widgets/desk_data.py', 'ui/widgets/backtest_flow.py',
                     'ui/widgets/breadth_flow.py'):
            _src13 = _pl13.Path(_f13).read_text(encoding='utf-8')
            check(f"★ {_f13} 不再手写 note_single/release_single（收敛进 SingleSyncGate）",
                  'note_single(' not in _src13 and 'release_single(' not in _src13)
        _bar13src = _pl13.Path('ui/widgets/download_bar.py').read_text(encoding='utf-8')
        check("★ 下载条不再用 cancel(None) 当「中断」（否则静默取消排队任务）",
              'self._hub.cancel(None)' not in _bar13src)

        # ---- ⑯ 后台下载在跑时**换统计范围**：新范围就绪度必须照样渲染（§11.5-83）----
        #   用户实测复现：点「更新到最新」挂后台 → 换到另一个范围 → 整页一直停在
        #   「正在体检本地数据就绪度…」，那个"更新到最新"的空态入口永远不出现，
        #   必须等下载跑完/中断才恢复（旧 `_busy_elsewhere()` 把 `_syncing` 也算进守卫）。
        from data.readiness import ReadinessReport as _RRep83  # noqa: E402
        from ui.widgets.custom_widgets import SYNC_ACTION_LABEL as _SAL83  # noqa: E402

        _m2_83 = win.page_backtest.page_scan
        _rd83 = _m2_83._readiness
        _m2_83._outcome = None
        _m2_83._symbols = ['NEW1', 'NEW2']
        _rd83._last_symbols = ['NEW1', 'NEW2']
        _rd83._syncing = True                      # 模拟"旧那一批正在后台跑"
        _rd83._sync_scope = ('OLD1',)
        _rd83._sync_label = '更新'
        _m2_83._result.set_empty('范围就绪（2 只）—— 正在体检本地数据就绪度…')
        _rep83 = _RRep83(total=2, ready=['NEW1'], missing=['NEW2'])
        _rd83._on_probed(_rd83._guard.next(), _rep83, ['NEW1', 'NEW2'])
        _txt83 = _m2_83.lbl_empty.text()
        check("★ 后台下载在跑时换范围 ⇒ 新范围就绪度**照样渲染**（不再卡在“正在体检…”）",
              '正在体检' not in _txt83 and '未下载 1' in _txt83)
        check("★ 入口同时给出：范围已换 ⇒ 空态按钮是「⬆ 更新到最新交易日」而不是“停止”",
              _m2_83.btn_empty_action.text() == _SAL83)
        _before83 = len(win.downloads.jobs())
        _rd83.update_latest()
        check("★ 范围已换 ⇒ 再点它是**把新范围交队列**（不误停旧那一批）",
              len(win.downloads.jobs()) == _before83 + 1
              and win.downloads.get(_rd83._sync_job) is not None
              and _rd83._same_batch(_m2_83._symbols))
        _rd83.stop_fill()                          # 同一批再点 = 中断（原语义保留）
        _made13[-1].finished.emit(dict(_DONE, aborted=True, aborted_by="cancel"))
        app.processEvents()
        check("★ 同一批再点仍是“中断”语义（原行为不被破坏）",
              _rd83._syncing is False and _rd83._sync_job is None)
        _rd83._syncing = False                     # 恢复现场
    finally:
        _dhub13.SyncWorker = _orig13
except Exception as _e13:  # noqa: BLE001
    check(f"§7-B11 后台下载断言整段抛异常: {type(_e13).__name__}: {_e13}", False)

# ==========================================
# §9-F① · 退出守卫（v6.70）：**分片等待 + “正在停止…”可见 + 超时不销毁在跑的线程**
#   旧形态 = `cancel(None)` + 一次 `worker.wait(15000)` ⇒ 两个问题：
#   ① 主线程整段阻塞 ⇒ 界面完全不动，用户无法区分“正在收尾”与“程序死了”；
#   ② 真超时时 `wait()` 返回后主窗口照常析构 ⇒ **带着在跑的 QThread 被 delete**（必崩）。
#   本段用**假 worker**（不 start、不联网）把三个分支逐个验到；
#   ⚠ 全程不碰真 `SyncWorker`（§11.5-71②：否则“跑测试 = 真下载”）。
# ==========================================
print("\n== §9-F① · 退出守卫：分片等待 / 正在停止回执 / 超时摘 parent ==")
try:
    import pathlib as _pl18  # noqa: E402
    from PyQt6.QtCore import QObject as _QO18, pyqtSignal as _PS18  # noqa: E402

    from ui import download_hub as _dh18  # noqa: E402

    class _StuckWorker18(_QO18):
        """假 worker：`wait()` 醒够 `n` 次才算结束 ⇒ 能验“到底等了几片”。"""

        finished = _PS18(object)              # ★加固断言的靶子：孤儿线程跑完要自清

        def __init__(self, n: int, parent=None):
            super().__init__(parent)          # ★给超时分支挂上 parent ⇒ 能验“真被摘了”
            self.running = True
            self.n = n
            self.wait_calls = 0
            self.cancelled = False

        def isRunning(self):        # noqa: N802
            return self.running

        def cancel(self):
            self.cancelled = True

        def wait(self, ms):         # noqa: N802
            self.wait_calls += 1
            if self.wait_calls >= self.n:
                self.running = False
            return not self.running

    # ---- ① 分片：醒 3 片才结束 ⇒ on_tick 必须被叫到 3 次（旧实现只会 wait 一次）----
    _hub18 = _dh18.DownloadHub()
    _w18 = _StuckWorker18(3)
    _hub18._worker = _w18
    _seen18 = []
    _ok18 = _hub18.shutdown(wait_ms=10000, tick_ms=5, on_tick=_seen18.append)
    check("★ shutdown 分片等待：每片回调一次（实测 tick %d 次、worker.wait %d 次）"
          % (len(_seen18), _w18.wait_calls),
          _ok18 is True and len(_seen18) == 3 and _w18.wait_calls == 3)
    check("★ 分片之间会刷新回执（而不是一个阻塞 wait 把界面闷死 15 秒）",
          _seen18 == [5, 10, 15])
    check("★ 退出中绝不再吃新任务（分片等待会转事件循环 ⇒ 一手误点就能重新填队）",
          _hub18.submit("退出后再投", ["000001"]) == 0 and not _hub18.jobs())

    # ---- ② 超时分支：卡住不醒 ⇒ 不能假装“已停干净”，也不能裸销毁 ----
    _hub18b = _dh18.DownloadHub()
    _stuck18 = _StuckWorker18(10 ** 9, _hub18b)      # parent = hub（与真 SyncWorker 同形）
    assert _stuck18.parent() is _hub18b              # 前置事实：没超时时它确实会被窗口带走
    _hub18b._worker = _stuck18
    _seenb18 = []
    _ret18 = _hub18b.shutdown(wait_ms=60, tick_ms=5, on_tick=_seenb18.append)
    check("★ 预算内停不下 ⇒ 返回 False（不谎报“已经停干净”）",
          _ret18 is False and len(_seenb18) >= 10)
    check("★ 超时不销毁在跑的线程：parent 已摘掉 + hub 松手 + 模块级列表握住引用",
          _stuck18.parent() is None and _hub18b._worker is None
          and _stuck18 in _dh18._ORPHAN_WORKERS)
    # ★v6.70 加固（二次修改）：孤儿线程跑完必须**自清** —— 旧版列表只增不减：
    #   每次"退出超时"都留一个跑完的线程对象（Python 引用常驻 + C++ 侧永不回收）。
    _stuck18.running = False
    _stuck18.finished.emit({})                 # 线程已结束 ⇒ 摘引用 + deleteLater
    check("★ 孤儿线程**跑完自清**（`_ORPHAN_WORKERS` 回到空 ⇒ 退出路径不留慢性泄漏）",
          _stuck18 not in _dh18._ORPHAN_WORKERS)

    # ---- ③ 回执真的落在下载条上（投影件不存任务数据）----
    _bar18 = win.download_bar
    _bar18.show_stopping(1500)
    check("★ 「正在停止…」写进下载条（名字 + 已等多久，不是静默阻塞）",
          _bar18.lbl_name.text().startswith("正在停止")
          and "1.5" in _bar18.lbl_txt.text() and not _bar18.isHidden())
    check("★ 不知道还要多久就走 busy 条纹（不画假百分比）+ 收起「中断 / ✕」",
          _bar18.bar.maximum() == 0 and _bar18.btn_stop.isHidden()
          and _bar18.btn_close.isHidden())
    _bar18.refresh()                            # 归还：下一拍仍是 hub 的投影

    # ---- ④ 源码级防漂移 ----
    _mws18 = _pl18.Path('ui/main_window.py').read_text(encoding='utf-8')
    check("★ 主窗口 closeEvent 带 `_exiting` 重入闸门（转事件循环后“再点 X”会重入）",
          'if self._exiting:' in _mws18 and 'self._exiting = True' in _mws18)
    _dhs18 = _pl18.Path('ui/download_hub.py').read_text(encoding='utf-8')
    check("★ hub 不再“一次 wait(全预算)”（那等于把界面闷死 15 秒）",
          'worker.wait(wait_ms)' not in _dhs18 and 'on_tick' in _dhs18)
    check("★ 退出等待里的 `processEvents` **挡掉用户输入**（只许看、不许动）",
          'ExcludeUserInputEvents' in _mws18)
except Exception as _e18:  # noqa: BLE001
    check(f"§9-F① 退出守卫断言整段抛异常: {type(_e18).__name__}: {_e18}", False)

# ==========================================
# §9-F② · 「继续未完成」（v6.70）：**中断后那些一次都没轮到的标的，得有个入口**
#   旧面板只有「只重试失败」，而“没轮到的那批”压根不在失败清单里（没发过请求）
#   ⇒ 用户只能自己重新提交同范围（属可发现性问题，不是数据问题）。
#   【本批真正要钉住的口径】续传的根据 = `SyncWorker` 记下的 `symbols_attempted`；
#   ⚠ 绝不允许改用 `symbols[done:]`——并发 K>1 下完成顺序与提交顺序无关，
#   而“已最新跳过”也计入 done ⇒ 按位置切会**同时**漏抓与重抓（下面用乱序样本验）。
#   ⚠ 全程打桩：不 start 真线程、不联网（§11.5-71②）；桩**成对还原**（§11.5-84）。
# ==========================================
print("\n== §9-F② · 续传清单：只认 symbols_attempted（不拿位置当依据）==")
try:
    import pathlib as _pl19  # noqa: E402
    from PyQt6.QtCore import QObject as _QO19, pyqtSignal as _PS19  # noqa: E402

    from data.sync_service import ThrottlePolicy as _TP19  # noqa: E402
    from ui import download_hub as _dh19  # noqa: E402
    from ui import workers as _wk19  # noqa: E402
    from ui.widgets.download_queue_panel import DownloadQueuePanel as _QP19  # noqa: E402

    class _Svc19:
        """假同步门面：每只都"成功"，可在第 N 只后把 worker 标成"请收手"。"""

        def __init__(self, interrupt_after: int = 0):
            self.calls = []
            self.interrupt_after = interrupt_after
            self.owner = None

        def refresh_one(self, symbol, **_kw):
            self.calls.append(symbol)
            if self.interrupt_after and len(self.calls) >= self.interrupt_after:
                self.owner._cancel = True      # 与真实 `cancel()` 同路径：只与只之间生效
            return {"ok": True, "added": 1, "reason": "net"}

    _orig19 = (_wk19.MarketSyncService, _wk19._load_calendar_safely, _dh19.SyncWorker)

    class _NoStartWorker19(_QO19):     # 队列的假 worker（绝不可真起线程）
        progress = _PS19(int, int, int)
        failed = _PS19(str, str)
        finished = _PS19(object)

        def __init__(self, *a, **k):
            super().__init__(k.get("parent"))

        def start(self):               # noqa: D401
            pass

        def isRunning(self):           # noqa: N802
            return False

        def cancel(self):
            pass

    try:
        _wk19._load_calendar_safely = lambda *a, **k: None     # 不联网拿日历
        _dh19.SyncWorker = _NoStartWorker19

        # ---- ① 串行路径：第 3 只没轮到 ⇒ 不记成"碰过" ----
        _svc19 = _Svc19(interrupt_after=2)
        _w19 = _wk19.SyncWorker(["A1", "A2", "A3", "A4"],
                                policy=_TP19(concurrency=1))
        _svc19.owner = _w19
        _wk19.MarketSyncService = lambda *a, **k: _svc19
        _cap19 = []
        _w19.finished.connect(lambda s: _cap19.append(s))
        _w19.run()
        check("★ 串行逐只记 `symbols_attempted`（只发了请求才算；实测 %s / 只跑了 %s）"
              % (_cap19[0].get("symbols_attempted"), _svc19.calls),
              _cap19[0]["symbols_attempted"] == ["A1", "A2"] == _svc19.calls)
        check("★ 被中断的两只仍记作 aborted（续传与熍断不互相遮盖）",
              bool(_cap19[0].get("aborted")) and _cap19[0].get("aborted_by") == "cancel")

        # ---- ② 并发路径：同样逐只记，且不重不漏 ----
        _svc19b = _Svc19()
        _w19b = _wk19.SyncWorker(["P%d" % i for i in range(6)],
                                 policy=_TP19(concurrency=3))
        _wk19.MarketSyncService = lambda *a, **k: _svc19b
        _cap19b = []
        _w19b.finished.connect(lambda s: _cap19b.append(s))
        _w19b.run()
        _att19b = _cap19b[0]["symbols_attempted"]
        check("★ 并发 K=3 下仍逐只记（6 只不多不少、无重复：实测 %d 条）"
              % len(_att19b),
              sorted(_att19b) == ["P%d" % i for i in range(6)] and len(set(_att19b)) == 6)
    finally:
        # ⚠ 只还原 `_wk19` 那两个；`_dh19.SyncWorker` 必须**整段持桩**到本块结束 ——
        #   因为下面的 `submit()` / `continue_unfinished()` 会走 `_pump()` 真建 worker，
        #   提前还原 = “跑测试 = 真下载”（§11.5-71② / §11.5-81⑤）。
        _wk19.MarketSyncService, _wk19._load_calendar_safely = _orig19[0], _orig19[1]

    # ---- ③ 续传口径：乱序 + 跳过也算"碰过"，按位置切定当错 ----
    _hub19 = _dh19.DownloadHub()
    _hub19.submit("全市场 A 股 日线", ["B1", "B2", "B3", "B4", "B5"],
                  min_date="2020-01-01")
    _j19 = _hub19.jobs()[0]
    _j19.stats = {"symbols_attempted": ["B3", "B1", "B5"], "symbols_failed": ["B5"],
                  "ok": 2, "fail": 1, "skipped": 0}
    _j19.status = _dh19.STATUS_CANCELLED
    check("★ 续传按**真没碰过**算（乱序样本）：期望 [B2, B4]、实测 %s（旧的 symbols[done:] 会错切成 [B4, B5]）"
          % _j19.unprocessed(), _j19.unprocessed() == ["B2", "B4"])
    check("★ `rest_count()` 不构集合也能对上（面板每拍都算，不能埋 O(n)）",
          _j19.rest_count() == 2 and _j19.to_dict()["rest"] == 2)
    _nid19 = _hub19.continue_unfinished(_j19.id)
    _n19 = _hub19.get(_nid19)
    check("★ 「继续未完成」投的正是那两只，且 zone / min_date / force_full 完全沿用",
          _n19 is not None and _n19.symbols == ["B2", "B4"]
          and _n19.zone == _j19.zone and _n19.min_date == "2020-01-01"
          and _n19.force_full is _j19.force_full and _n19.policy is _j19.policy)
    check("★ 任务名用人话（动作 + 对象，不甩“断点续传”这类术语，§10-10）",
          _n19 is not None and _n19.label.startswith("继续未完成 ·"))
    _j19b = _dh19.DownloadJob(id=9001, label="已全部跑完", symbols=["Z1", "Z2"],
                              status=_dh19.STATUS_CANCELLED,
                              stats={"symbols_attempted": ["Z2", "Z1"]})
    _hub19._jobs.append(_j19b)
    check("★ 已全部碰过 ⇒ 不投空任务（返回 0）", _hub19.continue_unfinished(_j19b.id) == 0)
    check("★ 拿不到的 job id ⇒ 返回 0（不报错、不投东西）", _hub19.continue_unfinished(4242) == 0)

    # ---- ④ 面板判据：被中断才给「继续」，“完成但有失败”不得误判 ----
    _panel19 = _QP19(_hub19)
    _btn19 = _panel19._row_action({"id": 1, "status": _dh19.STATUS_CANCELLED,
                                   "failed": 1, "rest": 2}, _dh19.STATUS_CANCELLED)
    check("★ 被中断且还有没轮到的 ⇒ 行内按钮是「继续 2 只」（失败那批仍由底部「只重试失败」兼顾）",
          _btn19.text() == "继续 2 只" and "同一份参数" in _btn19.toolTip())
    _btn2 = _panel19._row_action({"id": 2, "status": _dh19.STATUS_DONE,
                                  "failed": 3, "rest": 0}, _dh19.STATUS_CANCELLED)
    check("★ “完成但有失败”被 `_state_of` 映射成同一个橙色档 ⇒ 绝不可当成可续传（只能重试失败）",
          _btn2.text() == "只重试失败")
    _btn3 = _panel19._row_action({"id": 3, "status": _dh19.STATUS_DONE,
                                  "failed": 0, "rest": 5}, _dh19.STATUS_DONE)
    check("★ 正常完成（即使数字上有差）不给续传入口，不给“看得到却没用”的按钮",
          _btn3.text() == "" or not hasattr(_btn3, "text"))

    # ---- ⑥ ★v6.70 加固（二次修改）：续传**幂等** + 旧行收成「已续传」（不可点）----
    check("★ 续传过的那条带 `continued` 标记（面板据此收口，别让旧行一直可点）",
          _j19.to_dict().get("continued") is True)
    _nid19b = _hub19.continue_unfinished(_j19.id)
    check("★ 上一次续传**还在途** ⇒ 再点只把它还回来（不重投同一批：白抓 / `force_full` 时整段重下）",
          _nid19b == _nid19 and len(_hub19.jobs()) == 3)
    _btn4 = _panel19._row_action({"id": 4, "status": _dh19.STATUS_CANCELLED, "failed": 0,
                                  "rest": 2, "continued": True}, _dh19.STATUS_CANCELLED)
    check("★ 已续传的旧行 ⇒ 按钮变**不可点**的「已续传」（旧版会一直挂着可点的「继续 N 只」）",
          _btn4.text() == "已续传" and not _btn4.isEnabled())

    # ---- ⑤ 源码级防漂移 ----
    _ws19 = _pl19.Path('ui/workers.py').read_text(encoding='utf-8')
    check("★ 两条取数路径（串行 + 并发池）**都**记 attempted（只加一处 = 另一档位静默错值）",
          _ws19.count('stats["symbols_attempted"].append(symbol)') == 2)
    _hs19 = _pl19.Path('ui/download_hub.py').read_text(encoding='utf-8')
    # ⚠ 判据只盯“真代码形状”（`self.symbols[self.done`）——早先写的是短字面量，
    #   结果被自己 docstring 里那句“绝不能用 …”触红（§11.5-101：负向断言的样本
    #   必须收到“写错时长什么样”，否则注释也会把它引爆）。
    check("★ 续传不拿位置当依据（出现真代码形状 `self.symbols[self.done` 即口径错）",
          'self.symbols[self.done' not in _hs19 and 'symbols_attempted' in _hs19)
    _hub19.cancel(None)
except Exception as _e19:  # noqa: BLE001
    check(f"§9-F② 续传断言整段抛异常: {type(_e19).__name__}: {_e19}", False)
finally:
    # 桩成对还原（§11.5-84）；用 globals().get 防御“整段在赋值前就抱异常”的情况
    _o19 = globals().get("_orig19")
    _d19 = globals().get("_dh19")
    if _o19 is not None and _d19 is not None:
        _d19.SyncWorker = _o19[2]

# ==========================================
# §7-B12 P3 · 筛选方案库（ScanStrategyStore CRUD + M2 配置打包/还原往返）
# ==========================================
print("\n== §7-B12 P3 · 筛选方案库 ==")
try:
    import tempfile as _tmp_p3
    from data.scan_strategy_store import ScanStrategyStore as _SSSp3
    from data.scan_strategy_store import get_scan_strategy_store as _gsp3

    _store_p3 = _SSSp3()
    _store_p3.path = os.path.join(_tmp_p3.mkdtemp(prefix="jian_scanstrat_"),
                                  "scan_strategies.json")   # 临时库，绝不写真实目录
    _store_p3.data = {"strategies": []}
    _id1 = _store_p3.upsert({"name": "方案甲", "scope": 1, "index_code": "sh000300",
                             "formula": "COND := C > MA(C,20);", "params": "N=20",
                             "thresholds": {"min_amount": 50000000.0}, "adjust": "qfq"})
    _store_p3.upsert({"name": "方案甲", "scope": 2, "index_code": "",
                      "formula": "COND := C > MA(C,60);", "params": "",
                      "thresholds": {}, "adjust": "qfq"})   # 同名覆盖
    check("★ 同名 upsert 只留一条、内容被覆盖（不重复堆积）",
          len(_store_p3.list_strategies()) == 1
          and _store_p3.get(_id1)["config"]["formula"].endswith("MA(C,60);")
          and _store_p3.get(_id1)["config"]["scope"] == 2)
    _store_p3.upsert({"name": "方案乙", "formula": "X:=1;", "scope": 0})
    check("★ 不同名各存一条、列表按名字排序",
          [s["name"] for s in _store_p3.list_strategies()] == ["方案乙", "方案甲"])
    _reloaded = _SSSp3()
    _reloaded.path = _store_p3.path
    _reloaded.load()
    check("★ 落盘可重载（原子写 tmp+replace 后 JSON 完整）",
          len(_reloaded.list_strategies()) == 2)
    check("★ delete 按 id 生效",
          _store_p3.delete(_id1) is True and len(_store_p3.list_strategies()) == 1)

    # M2 配置打包/还原往返（scope 先置 0=自选 ⇒ resolve_scope 走本地不联网）
    _scan.cb_scope.setCurrentIndex(0)
    _scan._formula_pane.txt_formula.setPlainText("COND := C > MA(C, 99);")
    _scan._formula_pane.txt_params.setText("P=9")
    _cfg_p3 = _scan.current_config()
    check("★ current_config 打包出六件套（scope/index/formula/params/thresholds/adjust）",
          set(_cfg_p3) >= {"scope", "index_code", "formula", "params", "thresholds", "adjust"}
          and "MA(C, 99)" in _cfg_p3["formula"] and _cfg_p3["params"] == "P=9")
    _scan._formula_pane.txt_formula.setPlainText("")          # 打乱
    _scan._formula_pane.txt_params.setText("")
    _scan.apply_config(_cfg_p3)                                # 还原
    check("★ apply_config 往返无损（formula/params 复原）",
          "MA(C, 99)" in _scan._formula_pane.txt_formula.toPlainText()
          and _scan._formula_pane.txt_params.text() == "P=9")
    check("★ M2/M3 桥接共用 get_scan_strategy_store 单例（一份池跨页可见）",
          _scan._strategy.store is _gsp3() and _brd._strategy.store is _gsp3())

    # ★P6：行业映射缓存 store CRUD（临时路径，不碰真实 industry_map.json）
    from data.industry_store import IndustryStore as _IS6
    _ist6 = _IS6(path=os.path.join(_tmp_p3.mkdtemp(prefix="jian_ind_"), "industry_map.json"))
    check("★ P6：空表 is_loaded=False、get 返回 ''", _ist6.is_loaded() is False and _ist6.get('600000') == '')
    # ★v6.68：行业映射**分页直取**（东财列表 `f100`）+ 分批合并 —— 替掉"逐板块 80+ 连击"（§11.5-99）
    import tempfile as _tf68  # noqa: E402

    import data.akshare_feed as _af68  # noqa: E402
    # ★v6.69：分页取数实现搬到 `data/em_market.py` ⇒ 打桩点跟着挪到**新的 HTTP 边界**
    #   （`clist_page`），断言口径不变；退避闸门在 `data/em_throttle.py`（失败即冷却）。
    import data.em_market as _em68  # noqa: E402
    import data.em_throttle as _et68  # noqa: E402

    from data.sync_service import fetch_industry_page as _fip68  # noqa: E402

    _pages68 = {
        1: ([{'f12': '600000', 'f14': '浦发银行', 'f100': '银行'},
             {'f12': '600519', 'f14': '贵州茅台', 'f100': '白酒'}], 150),
        2: ([{'f12': '000001', 'f14': '平安银行', 'f100': '银行'},
             {'f12': 'BAD', 'f14': '怪码', 'f100': '银行'},
             {'f12': '600001', 'f14': '无行业', 'f100': '-'}], 150),
    }
    _real_page68 = _em68.clist_page
    _em68.clist_page = lambda page, pz=100: _pages68.get(page, ([], 150))
    try:
        _r68 = _fip68(1, 2, sleep_fn=lambda _s: None, interval=0)
    finally:
        _em68.clist_page = _real_page68
    check("★ v6.68：分页直取只收「6 位数字码 + 有行业名」的行（怪码 / '-' 被过滤）",
          _r68['map'] == {'600000': '银行', '600519': '白酒', '000001': '银行'})
    check("★ v6.68：分页边界（total=150、单页 100 ⇒ 抓满 2 页即 done、不多打）",
          _r68['pages_done'] == 2 and _r68['total_pages'] == 2 and _r68['done'] is True)
    _thr_back68 = preferences.get('em_throttle')
    _em68.clist_page = lambda page, pz=100: (_ for _ in ()).throw(RuntimeError('模拟风控'))
    try:
        _r68b = _fip68(1, 2, sleep_fn=lambda _s: None, interval=0)
    finally:
        _em68.clist_page = _real_page68
    check("★ v6.68：单页失败 ⇒ 空 map + done=False（**绝不上抛**；页面保留旧缓存并出声）",
          _r68b['map'] == {} and _r68b['pages_done'] == 0 and _r68b['done'] is False)
    check("★ v6.69：失败同时记一笔**退避冷却**，并把'还要等多久'交回上层（回执据此说话）",
          _et68.is_cooling() and '冷却' in (_r68b.get('error') or ''))
    _et68.reset()                                    # ⚠ 收尾：绝不把"冷却中"留给用户的应用
    preferences.set('em_throttle', _thr_back68 or {'fails': 0, 'cooldown_until': 0})

    from data.industry_store import IndustryStore as _IS68  # noqa: E402
    _st68 = _IS68(path=os.path.join(_tf68.mkdtemp(prefix='jian_ind68_'), 'industry_map.json'))
    _st68.merge({'600000': '银行', '600519': '白酒'})
    _st68.merge({'000001': '银行', '600000': '', '600002': ' '})    # 空值不得覆盖 / 入库
    check("★ v6.68：`merge` 分批并入（**空值不覆盖已有**、空名不入库）",
          _st68.coverage() == 3 and _st68.get('600000') == '银行' and _st68.get('000001') == '银行')
    check("★ v6.68：`merge` 落盘可回读（断点续抓靠它长期缓存）",
          _IS68(path=_st68.path).coverage() == 3)

    _ist6.replace({'600000': '银行', '600519': '白酒', 'BAD': ''})
    check("★ P6：replace 落盘并过滤空值；get/as_map/coverage 一致",
          _ist6.get('600000') == '银行' and _ist6.coverage() == 2
          and _ist6.as_map() == {'600000': '银行', '600519': '白酒'} and _ist6.is_loaded())
    _ist6b = _IS6(path=_ist6.path)
    check("★ P6：从磁盘重载得到同样映射（原子写 JSON 完整）", _ist6b.get('600519') == '白酒')
    _ist6b.replace({})                                     # 抓空不动旧表
    check("★ P6：replace 传空不清好数据（抓失败保留旧映射）", _ist6b.get('600000') == '银行')
except Exception as _e_p3:  # noqa: BLE001
    check(f"§7-B12 P3 筛选方案库断言整段抛异常: {type(_e_p3).__name__}: {_e_p3}", False)

# ==========================================
# 收尾自检：绝不能污染用户真实数据（测试一律用临时库）
# ==========================================
from config import settings  # noqa: E402

# ★v6.68：判据**不再是 mtime** —— 旧版 `mtime < RUN_STARTED_AT` 会被**用户正在运行的应用**合法改写
#   （它自己也会写 `preferences.json` / `trade_calendar.json`：用户一点界面就可能落盘）⇒ **假红**
#   （本轮实测：应用开着时这条 3 次里飘 2 次）。新判据两级：
#     ①**内容指纹**与跑前完全一致 ⇒ 真没被动过；②指纹变了 ⇒ 再看**我们可能写的那几个键**
#       （desk_ui / scan_ui / …）是否**逐值一致** —— 一致 ⇒ 被动的是别人的键，不是我们写的 ⇒ 通过。
#   两级都不满足才 FAIL（真污染仍然抓得住）。
_AFTER_LIB = _real_lib_fingerprint()
_OUR_KEYS = ("desk_ui", "scan_ui", "breadth_ui", "review_ui", "download_prefs")
for _name in ("annotations.json", "formula_library.json", "watchlist.json",
              "backtest_strategies.json", "preferences.json", "trade_calendar.json",
              "scan_strategies.json", "industry_map.json", "backtest_results"):
    _path = os.path.join(settings.USER_DATA_DIR, _name)
    _untouched = (not os.path.exists(_path)) or os.path.getmtime(_path) < RUN_STARTED_AT
    if not _untouched and _name in _AFTER_LIB:
        _before, _after = _REAL_LIB_SNAPSHOT.get(_name), _AFTER_LIB[_name]
        if _before == _after:
            _untouched = True                    # 内容一模一样（可能只是被别的进程重写了一遍）
        elif isinstance(_before, dict) and isinstance(_after, dict):
            _untouched = all(_before.get(_k) == _after.get(_k) for _k in _OUR_KEYS)
            if _untouched:
                print(f"  [说明] {_name} 被外部改动过，但我们关心的键逐值一致 ⇒ 判定未污染")
    check(f"未污染用户真实库 {_name}（本脚本只用临时库）", _untouched)

# ==========================================
# §9-A 末条 · 提交备注规范（v6.68 · 用户 2026-09-26 拍板：**照 1.12–1.33 的短写法**）
#   【为什么要机器钉】备注长度靠"自觉"必然反弹 —— 我上一轮就写成 200–900 字，用户在 GitHub 里看着头晕。
#   判据（只查 **HEAD**，也就是"即将被 push 的那一条"）：
#     ① 首词 == `APP_VERSION`（三处同步的**第四处**核对）；② 长度 ≤ 60 字符；
#     ③ 不含「§11.5-」「文档回写」「版本号三处同步」这类套话（细节本就属于文档）。
#   ⚠ 非 git 环境（导出 zip 跑冒烟）⇒ 打印说明并跳过，**不假红**。
# ==========================================
print("\n== §9-A 末条 · 提交备注规范（短 · 无套话 · 首词=版本号）==")
try:
    import subprocess as _sp68  # noqa: E402

    _git68 = _sp68.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),   # 仓库根（同文件开头口径）
        capture_output=True, text=True, encoding="utf-8")
    if _git68.returncode != 0:
        print("  [说明] 非 git 环境 ⇒ 跳过备注规范检查（不假红）")
    else:
        _subj68 = _git68.stdout.strip()
        _banned68 = [t for t in ("§11.5-", "文档回写", "版本号三处同步") if t in _subj68]
        check(f"★ 备注够短 · 首词=版本号 · 无套话（实测 {len(_subj68)} 字符 / 上限 60）",
              _subj68.split(" ")[0] == settings.APP_VERSION
              and len(_subj68) <= 60 and not _banned68)
except Exception as _e68:  # noqa: BLE001
    check(f"§9-A 备注规范断言抛异常: {type(_e68).__name__}: {_e68}", False)

# ==========================================
# §10-15 · 字体版权纪律（v1.46）：**不许把专有字体名写进 QSS / QFont**
#   用户 2026-09-25 拍板：界面字体只许点名开源 / 免费商用字体（思源黑体 / Noto / JetBrains Mono…）。
#   判据 = **源码形态**（不是"提没提到"）：`font-family:` 里出现专有名、或 `QFont(` 里点名专有族。
#   ⚠ 注释 / docstring 里**讲这条禁令**不算违规（本断言只看代码部分）。
# ==========================================
print("\n== §10-15 · 字体版权纪律：专有字体名不许进 QSS / QFont ==")
try:
    import pathlib as _pl15  # noqa: E402
    import re as _re15  # noqa: E402

    _PROP15 = "Consolas|Courier New|Microsoft YaHei|SimSun|Microsoft JhengHei|Arial|宋体|微软雅黑"
    _bad_qss15 = _re15.compile(r"font-family\s*:[^;\"']*(?:" + _PROP15 + ")", _re15.I)
    _bad_font15 = _re15.compile(r"QFont\(\s*[\"'](?:" + _PROP15 + ")", _re15.I)
    _hits15 = []
    _scan15 = [("ui", "*.py"), ("design", "*.html"), ("design", "*.css")]
    for _dir15, _glob15 in _scan15:
        for _p15 in sorted(_pl15.Path(_dir15).rglob(_glob15)):
            for _ln15 in _p15.read_text(encoding="utf-8", errors="ignore").splitlines():
                # 只对 .py 去注释（`#` 在 CSS/HTML 里是**颜色值**，按注释切会把后面整段切掉 ⇒ 漏检）
                _code15 = _ln15.split("#", 1)[0] if _p15.suffix == ".py" else _ln15
                if _bad_qss15.search(_code15) or _bad_font15.search(_code15):
                    _hits15.append(f"{_p15.name}: {_ln15.strip()[:50]}")
                    break
    check(f"★ §10-15：ui/ 与 design/ 样板都无「专有字体名写进 QSS/QFont」"
          f"（越界 {len(_hits15)} 处：{_hits15[:3]}）", not _hits15)
    _cw15 = _pl15.Path("ui/widgets/custom_widgets.py").read_text(encoding="utf-8")
    check("★ §10-15：字体仍只有**一个出口**（界面栈 / 等宽栈 / 磅值版 / 页面根钉一次 / 状态自检）",
          all(_n in _cw15 for _n in ("UI_FONT_STACK", "UI_MONO_STACK", "apply_ui_font",
                                     "ui_painter_font", "mono_font_css", "ui_font_status")))
except Exception as _e15:  # noqa: BLE001
    check(f"§10-15 字体断言整段抛异常: {type(_e15).__name__}: {_e15}", False)

# ==========================================
# §9-F③ · 按钮样式唯一出口（v6.70）：**同一类按钮只允许有一份定义**
#   背景：`FLAT_QSS` 的定义曾住在 `backtest_panes.py`（名字带“回测”却被全站 6 处引用），
#   另有 4 处**私有 `_FLAT_QSS` 副本**——其中 3 处是 flat 家族的尺寸/字号变体，
#   1 处（运行历史页）**有底有框**、根本是另一种控件（⇒ 正名 `OUTLINE_QSS`）。
#   【为什么只钉结构不钉“一张脸”】把不同形状硬统一 = 视觉变更，不属本项。
#   【本护栏守的是】今后谁再开一份私有副本、或把定义搬回带业务名的模块 → 当场红。
# ==========================================
print("\n== §9-F③ · 按钮样式唯一出口（flat / outline 家族）==")
try:
    import pathlib as _plq  # noqa: E402
    import re as _req  # noqa: E402

    _uiq = sorted(_plq.Path("ui").rglob("*.py"))
    _priv = [p.name for p in _uiq
             if _req.search(r"(?m)^_FLAT_QSS\s*=", p.read_text(encoding="utf-8", errors="ignore"))]
    check(f"★ §9-F③：`ui/` 内不再有任何私有 `_FLAT_QSS =` 定义（越界 {_priv}）", not _priv)

    _cwq = _plq.Path("ui/widgets/custom_widgets.py").read_text(encoding="utf-8")
    check("★ §9-F③：样式只有一个出口 = `flat_qss()` 生成器 + 五个命名变体",
          all(_n in _cwq for _n in ("def flat_qss(", "FLAT_QSS = flat_qss()",
                                    "FLAT_QSS_WIDE", "FLAT_QSS_SMALL", "FLAT_QSS_DANGER",
                                    "OUTLINE_QSS =")))
    _bpq = _plq.Path("ui/widgets/backtest_panes.py").read_text(encoding="utf-8")
    check("★ §9-F③：`backtest_panes` 只 import、不再**定义** `FLAT_QSS`（归属漂移已退役）",
          not _req.search(r"(?m)^FLAT_QSS\s*=", _bpq))
    _badimport = [p.name for p in _uiq
                  if _req.search(r"from ui\.widgets\.backtest_panes import[^\n]*FLAT_QSS",
                                 p.read_text(encoding="utf-8", errors="ignore"))]
    check(f"★ §9-F③：全站不再从 `backtest_panes` 借 `FLAT_QSS`（越界 {_badimport}）",
          not _badimport)
    # **观感零变化**的机器版证据：五个常量逐项钉住当年那五处的值
    from ui.widgets import custom_widgets as _cwmq  # noqa: E402
    check("★ §9-F③：五项样式逐项照旧（颜色 / 内边距 / 圆角 / 字号 / 悬停态）——本轮只改结构",
          ("color: #1976D2" in _cwmq.FLAT_QSS and "padding: 0 8px" in _cwmq.FLAT_QSS
           and "border-radius: 8px" in _cwmq.FLAT_QSS
           and "disabled" in _cwmq.FLAT_QSS
           and "padding: 0 10px" in _cwmq.FLAT_QSS_WIDE
           and "border-radius: 6px" in _cwmq.FLAT_QSS_WIDE
           and "font-size: 12px" in _cwmq.FLAT_QSS_SMALL
           and "disabled" not in _cwmq.FLAT_QSS_SMALL
           and "#8A94A6" in _cwmq.FLAT_QSS_DANGER
           and "#F44336" in _cwmq.FLAT_QSS_DANGER and "#FDECEA" in _cwmq.FLAT_QSS_DANGER
           and "border: 1px solid #E4E9F0" in _cwmq.OUTLINE_QSS
           and "background: #fff" in _cwmq.OUTLINE_QSS))
    check("★ §9-F③：flat 家族都是“无底无框”、描边家族保留底与框（两种形状没被强成一张脸）",
          "border: none" in _cwmq.FLAT_QSS and "border: none" not in _cwmq.OUTLINE_QSS)
except Exception as _eq:  # noqa: BLE001
    check(f"§9-F③ 样式断言整段抛异常: {type(_eq).__name__}: {_eq}", False)

# ==========================================
# 发布物一致性（v6.66）：`version.json` 是**老用户的更新清单**（`core/updater.py` 每次启动比对）
#   ⇒ 它必须是**合法 JSON**，且版本号与 `settings.APP_VERSION` 同步（§9-A 三处同步的机器版）。
#   【为什么加机器护栏】v6.66 手工回写时 notes 里写了**裸双引号** ⇒ 整个文件成了非法 JSON
#   （人眼完全看不出来，只有 `json.load` 会炸）—— 而那等于**所有老用户的更新检查崩**。
#   这条纪律以前只有 §11.7 一句"三处同步"（靠人记）⇒ 现在改成可执行断言。
# ==========================================
print("\n== 发布物一致性：version.json 可解析 + 版本号三处同步 ==")
try:
    import json as _json17  # noqa: E402
    import pathlib as _pl17  # noqa: E402

    from config import settings as _st17  # noqa: E402

    _vj17 = _json17.loads(_pl17.Path("version.json").read_text(encoding="utf-8"))
    check("★ version.json 是**合法 JSON**（解析失败 = 所有老用户的更新检查直接崩）",
          isinstance(_vj17, dict) and bool(str(_vj17.get("version") or "")))
    check("★ 版本号三处同步：version.json 的 version == settings.APP_VERSION",
          str(_vj17.get("version")) == str(_st17.APP_VERSION))
    check("★ version.json 的 url 仍指向项目 Releases 页（正式发版才换直链）",
          "github.com/ENDVEN/Jian/releases" in str(_vj17.get("url") or ""))
    check("★ 更新说明非空且是给人看的（用户点更新时看到的就是它）",
          len(str(_vj17.get("notes") or "").strip()) > 20)
except Exception as _e17:  # noqa: BLE001
    check(f"发布物一致性断言整段抛异常: {type(_e17).__name__}: {_e17}", False)

print(f"\n===== 通过 {len(OK)} · 失败 {len(BAD)} =====")
for b in BAD:
    print("  FAIL:", b)

# 【打桩 ③】必须强制退出：只要还有非守护 QThread 存活（哪怕只是后台收尾），
# 解释器就不退出 ⇒ 管道 | Select-Object -Last N 会一直缓冲、表现为"无响应"。
sys.stdout.flush()
os._exit(1 if BAD else 0)
sys.exit(1 if BAD else 0)
