# ui/dialogs/fill_model_help.py
"""「成交模型怎么选？」用户教学弹窗 (v6.17 · §7-B5)。

【为什么单独做一个弹窗，而不是塞进 tooltip】
  用户实测反馈原话：「触发式条件单 / 触发跳数 —— 用户完完全全都不知道」。
  我们的原则是「面向用户说人话」（§10-10），但**术语本身可以保留在系统里**，
  只是不能让它成为界面上唯一的解释。tooltip 的问题是**用户不会主动去悬停**，
  所以关键概念必须有"看得见的入口 + 用例子讲"（§6.6-R3 已验证：用例子教，比堆说明有效）。

【这份文案的分工】
  · 一句话说明 → `core.backtest.fill_mode_oneliner`（与页面行内说明**同源**，禁止另写一份）；
  · **具体数字举例** → 本文件（教学专用，只在这里出现）；
  · 留档/可复现文案 → `core.backtest.fill_summary`（写进 CSV / PNG 报告）。

【纪律】本弹窗**只读不写**：不改任何配置，纯解释。参数由调用方传入现状值，
让用户看到的例子就是他此刻将要使用的口径（而不是一个泛泛的说明）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from core.backtest import (FILL_CLOSE, FILL_NEXT_OPEN, FILL_TRIGGER,
                           fill_mode_oneliner, normalize_fill)

_TITLE_QSS = "font-size: 16px; font-weight: bold; color: #1F2430;"
_SUBTITLE_QSS = "font-size: 12px; color: #5B6472;"
_NAME_QSS = "font-size: 14px; font-weight: bold; color: #1565C0;"
_BODY_QSS = "font-size: 12px; color: #3C4552;"
_EG_QSS = "font-size: 12px; color: #8A94A6;"
_CARD_QSS = "QFrame { background: #F8FAFD; border: 1px solid #E7EAF0; border-radius: 10px; }"
_T1_QSS = "QFrame { background: #FBF6FF; border: 1px solid #E6D6F5; border-radius: 10px; }"
_T1_HEAD_QSS = "font-size: 13px; font-weight: bold; color: #6A1B9A;"

# 教学例子：一套固定的"信号日 / 次日"数字，三档都拿同一套数字对照，差别才看得清。
_EG_SIGNAL = "假设某股：信号日最高 10.00 元、最低 9.50 元；次日开盘 10.20 元，最高 10.60 元，最低 9.30 元。"


class FillModelHelpDialog(QDialog):
    """「三档成交时点 + T+1」说明书。只解释，不改配置。"""

    def __init__(self, parent=None, trigger_tick: int = 1):
        super().__init__(parent)
        self.setWindowTitle("成交模型怎么选？")
        self.setMinimumWidth(620)
        conf = normalize_fill(FILL_TRIGGER, trigger_tick)
        offset = conf["trigger_tick"]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        title = QLabel("成交模型：信号出现之后，到底「什么时候、按什么价」成交")
        title.setStyleSheet(_TITLE_QSS)
        title.setWordWrap(True)
        outer.addWidget(title)

        sub = QLabel("指标天然滞后一步，所以「按什么价成交」会明显改变回测结果。"
                     "下面三档，选最接近你**真实下单习惯**的那一个。")
        sub.setStyleSheet(_SUBTITLE_QSS)
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # 内容放进滚动区：小屏幕上也不会把按钮挤掉（§11.5-15②）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                             "QScrollArea > QWidget > QWidget { background: transparent; }")
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 6, 0)
        body_lay.setSpacing(10)

        body_lay.addWidget(self._card(
            "① 次日开盘价成交（默认）",
            fill_mode_oneliner(FILL_NEXT_OPEN),
            _EG_SIGNAL + "  这一档会在**次日 10.20 元**买入 —— 最稳、最不占便宜，"
                         "但当天最低跌到 9.30 元时，你一开盘就浮亏。"))

        body_lay.addWidget(self._card(
            "② 当日收盘价成交",
            fill_mode_oneliner(FILL_CLOSE),
            _EG_SIGNAL + "  这一档在**信号当天收盘**（约 10.05 元）就买入 —— "
                         "不用白等一整天，代价是要接受「收盘价」这个偏乐观的假设。"))

        body_lay.addWidget(self._card(
            "③ 价格冲破 / 跌破才成交",
            fill_mode_oneliner(FILL_TRIGGER, offset),
            _EG_SIGNAL + f"  这一档会先挂单：买入触发价 = 10.00 + {offset * 0.01:.2f} 元；"
                         f"卖出触发价 = 9.50 − {offset * 0.01:.2f} 元。\n"
                         "· 次日最高 10.60 元 → **碰到了，按触发价买入**（不会追到 10.60）；\n"
                         "· 若次日最高只到 9.98 元 → **一整天没碰到，这次就不买**"
                         "（信号作废，等下一次信号）—— 所以成交笔数通常比前两档少。"))

        body_lay.addWidget(self._t1_card())
        body_lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        foot = QHBoxLayout()
        tip = QLabel("不确定就先用默认（次日开盘价）：它最保守，不会让你高估收益。")
        tip.setStyleSheet(_EG_QSS)
        tip.setWordWrap(True)
        foot.addWidget(tip, 1)
        btn = QPushButton("知道了")
        btn.setStyleSheet("QPushButton { background:#1976D2; color:white; font-weight:bold;"
                          " padding:7px 20px; border:none; border-radius:8px; font-size:13px; }"
                          "QPushButton:hover { background:#1565C0; }")
        btn.clicked.connect(self.accept)
        foot.addWidget(btn)
        outer.addLayout(foot)

    # ---------- 内部构件 ----------
    @staticmethod
    def _card(name: str, oneliner: str, example: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(_CARD_QSS)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(6)
        head = QLabel(name)
        head.setStyleSheet(_NAME_QSS)
        lay.addWidget(head)
        words = QLabel(oneliner)
        words.setStyleSheet(_BODY_QSS)
        words.setWordWrap(True)
        lay.addWidget(words)
        eg = QLabel(example)
        eg.setStyleSheet(_EG_QSS)
        eg.setWordWrap(True)
        eg.setTextFormat(Qt.TextFormat.MarkdownText)   # **加粗** 是给"眼睛扫关键数字"用的
        lay.addWidget(eg)
        return card

    @staticmethod
    def _t1_card() -> QFrame:
        card = QFrame()
        card.setStyleSheet(_T1_QSS)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(6)
        head = QLabel("🔒 无论选哪一档都遵守的 T+1 规则（不能关）")
        head.setStyleSheet(_T1_HEAD_QSS)
        lay.addWidget(head)
        lines = [
            "A股规定：**今天买的股票，今天不能卖**。回测同样照此执行，否则结果会显得比现实好。",
            "· 买入当天如果就跌穿了止损线（或涨到了止盈线）→ 当天卖不掉，"
            "只能**第二天一开盘就卖**，第二天的跳空低开你得自己承担；",
            "· 「最长持仓 1 天」实际会变成**第二天收盘才卖**；",
            "· 同一天里**卖出之后不会立刻又买回来**（那是白交两次手续费、持仓却毫无变化）。",
        ]
        for line in lines:
            lab = QLabel(line)
            lab.setStyleSheet(_BODY_QSS)
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.TextFormat.MarkdownText)
            lay.addWidget(lab)
        return card
