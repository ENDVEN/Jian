# ui/dialogs/indicator_params.py
"""`⚙` 指标参数窗口（v6.24 · §7-B8 R16）—— **内置项与用户配方共用同一个组件**。

【为什么必须有这个窗口】用户原话："内置**不要改名**（怕不懂的用户改不回来），
但是比如 **MACD 这类的会有个参数设置的环节**，要保留一个给用户改参数的窗口。"
⇒ 于是内置项**只读名称、但参数可调**；`成交量` 这类没有参数的**不给 ⚙**（不做假入口）。

【三道闸（用户四轮拍板 · 缺一不可）】
  ① 改动过、**又没应用也没校验**就想关 ⇒ 底部换成确认条：
     「参数已改动，但既没应用也没校验。直接关掉就等于丢掉这次修改」+ [继续编辑][放弃改动]
     ⇒ **绝不静默丢改动**（这是最容易被写漏的一条：默认行为就是静默丢弃）。
  ② 点「应用」时参数**格式/范围不对** ⇒ **自动恢复默认值并明确告知**，
     **不放行、也不静默改**（"已恢复为 5 / 20 / 60，确认无误再点一次应用"）。
  ③ 随时可「↺ 恢复默认」⇒ 回出厂值，并提示"**点应用才生效**"。

【「校验」的口径】`▶ 校验参数` 拿**页面上正在看的那份真实行情**把指标试算一遍
  —— 直接调 `TAEngine.apply`（**与图上渲染同源的引擎**），不另起一套试算逻辑。
  ⚠ 判据不能是"没抛异常"：`TAEngine` 对数据太短/缺列是**静默返回原表**的，
  那样"校验通过"就是假的 ⇒ 判据 = **产出的列真的算出了值**（至少一个非 NaN）。
  校验通过 = 视为已验证 ⇒ 关闭窗口时不再追问（否则用户会觉得"改了合法参数还老拦我"）。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QVBoxLayout)

from core.indicators import TAEngine

_DIALOG_QSS = ("QDialog { background:#F7F9FC; }"
               "QLabel#ParamName { font-size:12px; color:#3A4250; font-weight:700; }"
               "QLabel#ParamRange { font-size:10.6px; color:#8A94A6; }"
               "QLabel#ParamTitle { font-size:13px; font-weight:800; color:#212121; }"
               "QLabel#ParamMsg { font-size:11.4px; color:#5B6472; }")
_INPUT_QSS = ("QLineEdit { border:1px solid #E4E9F0; border-radius:7px; padding:6px 9px;"
              " font-size:12.4px; background:#FFFFFF; }"
              "QLineEdit:focus { border-color:#A9C7EA; }")
_BTN_QSS = ("QPushButton { background:#F5F5F5; border:1px solid #E0E0E0; border-radius:6px;"
            " padding:7px 14px; font-weight:bold; color:#424242; }"
            "QPushButton:hover { background:#EDEDED; }")
_BTN_PRIMARY_QSS = ("QPushButton { background:#1976D2; color:white; border:none; border-radius:6px;"
                    " padding:7px 16px; font-weight:bold; }"
                    "QPushButton:hover { background:#1565C0; }")
_BAR_QSS = ("QFrame#DiscardBar { background:#FFF8E1; border:1px solid #FFE082;"
            " border-radius:6px; }")


def trial_run(key: str, options: dict, df) -> tuple:
    """拿给定行情把指标**试算一遍**。返回 `(ok, 人话说明)`。

    【判据必须跟参数无关】`TAEngine.OUTPUTS` 里是**默认形状的列名**（MA 默认 `MA_5/20/60`），
    而 MA 的列名**随参数变**（把周期1 改成 8，产出就是 `MA_8`）⇒ 拿它当判据会把
    **合法参数误判成失败**（本步实测踩到：校验报"没有算出 MA_5"）。
    所以判据改成两条**参数无关**的事实：
      ① 引擎**真的新增了列**（不是原表返回）；
      ② 新增的列里**至少有一个算出了值**（不是全 NaN）。
    后者才是"数据太短 / 参数过大"的真信号 —— `TAEngine` 对短数据是**静默返回原表**的，
    只看"没抛异常"会把失败当通过。
    """
    key = str(key or "")
    if not TAEngine.OUTPUTS.get(key):
        return True, "该指标没有独立产出列（无需试算）"
    if df is None or len(df) == 0:
        return False, "本地没有可用的最近行情 —— 先同步一段数据再校验"
    before = set(getattr(df, "columns", ()))
    try:
        out = TAEngine.apply(df.copy(), [key], **{key: dict(options or {})})
    except Exception as e:                      # noqa: BLE001 —— 试算任何异常都算"没通过"
        return False, f"试算出错：{e}"
    added = [column for column in out.columns if column not in before]
    if not added:
        return False, "没有算出任何新的指标列"
    if not any(out[column].notna().any() for column in added):
        return False, f"{len(df)} 根数据太短或参数过大，算出来全是空值"
    return True, f"{len(df)} 根数据试算通过（新增 {len(added)} 列）"


class IndicatorParamsDialog(QDialog):
    """参数窗口：顶部标题 + 每个参数一行（名称 / 输入框 / 范围）+ 三道闸的按钮区。"""

    def __init__(self, model, key: str, parent=None, sample_df=None, sample_label: str = ""):
        super().__init__(parent)
        self.model = model
        self.key = str(key)
        self._specs = list(model.param_specs(self.key))
        self._sample_df = sample_df
        self._sample_label = str(sample_label or "")
        self._applied = False
        self._validated = False
        self._force_close = False

        self.setWindowTitle(f"参数 · {model.label(self.key)}")
        self.setStyleSheet(_DIALOG_QSS)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(9)

        title = QLabel(f"{model.label(self.key)}　参数")
        title.setObjectName("ParamTitle")
        box.addWidget(title)

        self.editors: dict = {}
        for name, default, lo, hi, hint in self._specs:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(name)
            label.setObjectName("ParamName")
            label.setFixedWidth(56)
            row.addWidget(label)

            editor = QLineEdit(str(default))
            editor.setStyleSheet(_INPUT_QSS)
            editor.setToolTip(f"{name}：{hint}\n合法范围 {lo} ~ {hi}")     # ★范围口径进 tooltip（P8）
            editor.textChanged.connect(self._on_edited)
            self.editors[name] = editor
            row.addWidget(editor, 1)

            range_label = QLabel(f"{lo} ~ {hi}")
            range_label.setObjectName("ParamRange")
            row.addWidget(range_label)
            box.addLayout(row)

        self.lbl_message = QLabel("改完点「应用」生效；点「校验参数」可以拿最近的行情试算一遍。")
        self.lbl_message.setObjectName("ParamMsg")
        self.lbl_message.setWordWrap(True)
        box.addWidget(self.lbl_message)

        # ---- 闸①：放弃改动的确认条（默认隐藏）----
        self.bar = QFrame()
        self.bar.setObjectName("DiscardBar")
        self.bar.setStyleSheet(_BAR_QSS)
        bar = QHBoxLayout(self.bar)
        bar.setContentsMargins(10, 8, 10, 8)
        bar.setSpacing(8)
        warn = QLabel("参数已改动，但既没应用也没校验。直接关掉就等于丢掉这次修改 —— 确定放弃？")
        warn.setWordWrap(True)
        warn.setStyleSheet("font-size:11.2px; color:#E65100; border:none; background:transparent;")
        bar.addWidget(warn, 1)
        btn_keep = QPushButton("继续编辑")
        btn_keep.setStyleSheet(_BTN_QSS)
        btn_keep.clicked.connect(self._on_keep_editing)
        bar.addWidget(btn_keep)
        btn_drop = QPushButton("放弃改动")
        btn_drop.setStyleSheet(_BTN_QSS)
        btn_drop.clicked.connect(self._on_discard)
        bar.addWidget(btn_drop)
        self.bar.setVisible(False)
        box.addWidget(self.bar)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_reset = QPushButton("↺ 恢复默认")            # 闸③
        self.btn_reset.setStyleSheet(_BTN_QSS)
        self.btn_reset.setToolTip("回到出厂默认值；**点「应用」才生效**")
        self.btn_reset.clicked.connect(self._on_reset)
        row.addWidget(self.btn_reset)

        self.btn_validate = QPushButton("▶ 校验参数")
        self.btn_validate.setStyleSheet(_BTN_QSS)
        self.btn_validate.setToolTip("拿页面上正在看的那份行情试算一遍；\n"
                                     "校验通过之后关窗口就不再追问")
        self.btn_validate.clicked.connect(self._on_validate)
        row.addWidget(self.btn_validate)
        row.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet(_BTN_QSS)
        self.btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_cancel)

        self.btn_apply = QPushButton("应用")                   # 闸②
        self.btn_apply.setStyleSheet(_BTN_PRIMARY_QSS)
        self.btn_apply.clicked.connect(self._on_apply)
        row.addWidget(self.btn_apply)
        box.addLayout(row)
        self.resize(360, 200)

    # ==========================================
    # 对外
    # ==========================================
    def was_applied(self) -> bool:
        return self._applied

    def was_validated(self) -> bool:
        return self._validated

    def message_text(self) -> str:
        return self.lbl_message.text()

    def discard_bar_visible(self) -> bool:
        return self.bar.isVisibleTo(self)

    def values(self) -> dict:
        return {name: self.editors[name].text() for name in self.editors}

    # ==========================================
    # 内部
    # ==========================================
    def _on_edited(self, *_):
        """编辑过就把"已校验/已应用"清掉 —— 否则改完不点应用也能"假装验证过"蒙混过关。"""
        self._validated = False
        self._applied = False

    def _dirty(self) -> bool:
        """编辑器里的值是否与模型里的不同（**按模型当前值判断**，不记"我改过没"）。"""
        current = self.model.params_of(self.key)
        for name, editor in self.editors.items():
            try:
                if float(editor.text()) != float(current.get(name)):
                    return True
            except (TypeError, ValueError):
                return True         # 输入根本不是数字 ⇒ 也算改动过（不能让它静默溜走）
        return False

    def _reload(self) -> None:
        values = self.model.params_of(self.key)
        for name, editor in self.editors.items():
            editor.blockSignals(True)
            editor.setText(str(values.get(name)))
            editor.blockSignals(False)

    def _say(self, text: str, *, warn: bool) -> None:
        self.lbl_message.setText(text)
        self.lbl_message.setStyleSheet(
            f"font-size:11.4px; color:{'#E65100' if warn else '#2E7D32'};")

    # ---- 闸①：关窗 ----
    def reject(self):
        if self._force_close or not self._dirty() or self._applied or self._validated:
            super().reject()
            return
        self.bar.setVisible(True)       # 绝不静默丢改动

    def _on_keep_editing(self):
        self.bar.setVisible(False)

    def _on_discard(self):
        self._force_close = True
        self.bar.setVisible(False)
        super().reject()

    # ---- 闸③：恢复默认 ----
    def _on_reset(self):
        self.model.reset_params(self.key)
        self._reload()
        self.bar.setVisible(False)
        self._say("已恢复出厂默认值 —— **点「应用」才生效**。", warn=True)

    # ---- 校验 ----
    def _on_validate(self):
        for name, editor in self.editors.items():
            self.model.set_param(self.key, name, editor.text())
        ok, note = self.model.validate_params(self.key)
        if not ok:
            self._say(f"参数不合法：{note}", warn=True)
            return
        options = self.model.engine_options().get(self.key, {})
        ok, note = trial_run(self.key, options, self._sample_df)
        data = f"（{self._sample_label}）" if self._sample_label else ""
        self._say(("✓ 校验通过：" + note + data) if ok else ("✗ 校验未通过：" + note + data),
                  warn=not ok)
        self._validated = ok

    # ---- 闸②：应用 ----
    def _on_apply(self):
        bad = [name for name in self.editors
               if not self.model.set_param(self.key, name, self.editors[name].text())]
        if bad:
            # **自动恢复默认值并告知**：不放行、也不静默改
            self.model.reset_params(self.key)
            self._reload()
            defaults = "、".join(f"{name}={value}"
                               for name, value in self.model.params_of(self.key).items())
            self._say(f"参数格式或范围不对（{'、'.join(bad)}），已恢复为默认值："
                      f"{defaults}。确认无误后再点一次「应用」。", warn=True)
            return
        self._applied = True
        self.bar.setVisible(False)
        self.accept()
