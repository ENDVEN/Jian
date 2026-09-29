# ui/widgets/hub_latest.py
"""「总库有更新版」的**提示 + 显式更新**（★1.61 / §7-B16 H4 · 两处桥接共用一份口径）。

【为什么必须做成公共件】
M1（`ui/widgets/backtest_strategy.py`）与 M2·M3（`ui/widgets/scan_strategy_bridge.py`）
的这段逻辑**逐行相同**：读内联快照判时效 → 显隐一个默认隐藏的「⤒ 用最新版」→ 点了才替换
内容并出回执。各抄一份 = 迟早一处改了另一处没改（§11.5-11「同类防护要做就做全套」），
而且"默认保留旧版"这条**红线②**若在某一份里被写歪，界面上根本看不出来。

【红线②（本模块的存在意义）】
  ① **绝不静默改变已存方案的函数**：载入路径只读**内联快照**；本模块的 `tip()` / `prompt()`
     只做"提示与显隐"，**不碰任何内容**；
  ② 只有用户点了按钮（`apply()`）才替换 —— 替换范围也**只有函数本身**（函数段+参数），
     条件 / 风控 / 门控 / 成交 / 区间 / 阈值 / 范围一律不动。
  ⇒ 源码级护栏（冒烟）：**读资产的调用只许出现在本文件的 `apply()` 里**（判据是带括号的
     调用形态，因为模块顶部的 import 不算调用），两个桥接文件里一个都不许有
     （载入路径绝不读资产内容）。
"""
from __future__ import annotations

from data.hub_assets import asset_texts


class LatestFunctionPrompt:
    """一条"待更新"的资产 + 摘要条上的显式动作（M1 与 M2·M3 各持一个实例）。

    :param page:      所在页面（只用来取回执控件与按钮，不存状态）
    :param subject:   「本策略」/「本方案」——回执里的主语
    :param noun:      被替换的东西的说法（「函数段与参数」/「筛选条件」）
    :param kept:      明说"没动"的那些配置（用户最担心的就是"顺手改了我的条件"）
    :param fill:      `(texts, params_text) -> int`：把内容回填到页面并复检；返回段数
    :param receipt:   回执控件名（M1 = `lbl_run_status` / M2·M3 = `lbl_receipt`）
    :param button:    动作按钮名（两页都叫 `btn_apply_latest`）
    """

    def __init__(self, page, *, subject: str, noun: str, kept: str, fill,
                 receipt: str = 'lbl_receipt', button: str = 'btn_apply_latest',
                 receipt_tail: str = ''):
        self.p = page
        self._subject = subject
        self._noun = noun
        self._kept = kept
        self._fill = fill
        self._receipt = receipt
        self._button = button
        self._tail = receipt_tail      # 回执尾巴（M2/M3 补一句"点开始扫描按它取截面"）
        self._stale = None

    # ---------------- 文案 ----------------
    def tip(self, stale) -> str:
        """回执里追加的那一句（**不点按钮 = 保持原样**是默认动作，必须在文案里说出来）。"""
        if stale is None:
            return ''
        return (f" ⚠ 总库里的「{stale.get('name')}」已有更新版 ——"
                f"点「⤒ 用最新版」可换成新版；不点则保持{self._subject}保存时的函数原样。")

    # ---------------- 提示面（只显隐按钮，绝不改内容） ----------------
    def prompt(self, stale) -> bool:
        """记下待更新的资产并显隐「⤒ 用最新版」（None = 收起）。"""
        self._stale = stale
        btn = getattr(self.p, self._button, None)
        if btn is not None:
            if stale is not None:
                btn.setToolTip(
                    f"总库里的「{stale.get('name')}」已有更新版 —— 点它把**{self._noun}**"
                    f"换成最新版；{self._kept}等配置一字不动。\n"
                    f"不点它就保持{self._subject}保存时的原样（默认）。")
            btn.setVisible(stale is not None)
        return stale is not None

    # ---------------- 显式动作（唯一允许读资产内容的地方） ----------------
    def apply(self) -> int:
        """把总库最新版回填进页面。**只**换 `noun`，其余配置一字不动。

        :return: 实际替换的段数（0 = 没有待更新的资产 / 资产内容为空）
        """
        asset = self._stale
        if asset is None:
            return 0
        texts = [t for t in asset_texts(asset) if str(t).strip()]
        if not texts:
            self.prompt(None)
            return 0
        n = self._fill(texts, str(asset.get('params_text') or ''))
        self.prompt(None)
        getattr(self.p, self._receipt).setText(
            f"⤒ 已按总库最新版「{asset.get('name')}」替换{self._noun}"
            f"（{self._kept}未改动）。{self._tail}")
        return n

    def pending(self):
        """当前待更新的资产（没有 = None）—— 供测试与页面查询。"""
        return self._stale
