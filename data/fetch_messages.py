# data/fetch_messages.py
"""取数失败的**人话文案唯一出口**（★2.04 / P2 拆件）。

从 `data/sync_service.py` 抽出：单个标的失败 / 成分股失败 / 批量中断原因 / 批量失败提示。
纯字符串函数，零 Qt、零网络、零 IO —— 三处弹窗共用同一套措辞（§11.5-11）。
"""
from __future__ import annotations

__all__ = ["friendly_fetch_message", "friendly_constituent_message",
           "abort_reason_text", "failure_hint"]

# 【代理文案的唯一出处】三处（单个标的弹窗 / 成分股弹窗 / 批量回执）共用同一套措辞。
# ⚠ **绝不写死 `127.0.0.1:7897`**：那是诊断记录（§9.3）里**某一台机器**的端口，
#   写进用户文案就是对新用户撒谎；端口只留在 §9.3 的历史记录里。
_PROXY_WHAT = ("本机系统代理（Clash / V2Ray 等）在同步过程中断连，或中途切换了节点。"
               "这类失败的特征是：短时间内每一只都报同一句「无法连接代理」的错误。"
               "（这不是行情源挂了、也不是被限流，所以「稍后重试」通常没用，先查代理。）")


def friendly_fetch_message(symbol: str, result: dict) -> str:
    """给单个标的后台同步失败时的弹窗用：说明"最可能是什么 + 该怎么办"。

    【背景】退市股（如 600277，2024-06 退市）会因行情源不再提供而取不到数据。
    旧文案一律说"代码不存在 / 网络抖动"，极具误导性 ——
    用户明明没输错，只是该股已经退市了。
    """
    symbol = str(symbol or "")
    reason = (result or {}).get("reason")
    if reason == "proxy":
        return (f"{symbol} 未能同步：疑似本机代理问题。\n\n"
                f"最可能是什么：{_PROXY_WHAT}\n\n"
                f"怎么办：① 检查代理软件是否在运行、规则是否覆盖了行情域名；\n"
                f"② 切换节点后重试；③ 若不需要代理，可临时关闭系统代理再同步。")
    if reason == "network":
        return (f"{symbol} 未能同步：网络请求失败。\n\n"
                f"可能原因：① 当前断网；② 请求超时；③ 请求过于频繁被行情源临时限流。\n"
                f"建议稍后重试；批量任务请调大「同步间隔」。")
    if reason == "no_data":
        return (f"{symbol} 未返回任何行情数据。\n\n"
                f"可能原因：① 代码/名称输入有误；\n"
                f"② 该股已退市或长期停牌，行情源不再提供（属正常现象，本地已缓存的历史仍可用）；\n"
                f"③ 次新/特殊标的，两个行情源暂未收录。")
    return (f"{symbol} 未能同步：{result.get('message', '未知原因')}\n\n"
            f"建议稍后重试；若反复失败请到「🗄 数据管理」查看是否已停止更新。")


def friendly_constituent_message(index_code: str, result: dict) -> str:
    """指数成分股解析失败时的人话提示（§10-10：分类安抚，而非统一吓唬）。

    同样区分"网络类失败"与"行情源本来就没收录这个指数" —— 后者不是用户的错，
    且明确告诉他可行的替代来源。
    """
    index_code = str(index_code or "")
    reason = (result or {}).get("reason")
    if reason == "proxy":
        return (f"未能获取 {index_code} 的成分股：疑似本机代理问题。\n\n"
                f"最可能是什么：{_PROXY_WHAT}\n\n"
                f"怎么办：① 检查代理软件是否在运行；② 切换节点后重试；\n"
                f"③ 若不需要代理，可临时关闭系统代理再解析。")
    if reason == "network":
        return (f"未能获取 {index_code} 的成分股：网络请求失败。\n\n"
                f"可能原因：① 当前断网；② 请求超时；③ 请求过于频繁被临时限流。\n"
                f"建议稍后重试。")
    if reason == "no_data":
        return (f"未能获取 {index_code} 的成分股：行情源未返回名单。\n\n"
                f"可能原因：① 代码有误；② 该指数不在行情源收录范围内"
                f"（部分行业/主题指数常缺）；③ 接口临时变更。\n"
                f"建议：改用「粘贴代码列表」或「全市场 A 股」。")
    return (f"未能获取 {index_code} 的成分股：{result.get('message', '未知原因')}\n\n"
            f"建议：① 稍后重试；② 改用「粘贴代码列表」或「全市场 A 股」。")


def abort_reason_text(stats: dict) -> str:
    """批量任务**被中断的原因**（一句话，不带括号；没被中断返回空串）。

    【为什么做成公共件】`SyncWorker` 的 `finished` 回包有三个消费方
    （批量预下载弹窗 / 数据管理页 / M2-M3 的更新与补齐），
    三处各写一遍"（已中断）"就会漏 —— 代理中断必须**说清为什么提前停**，
    否则用户只看到一个"已中断"，还是不知道该去查代理（§11.5-11 同类防护做全套）。
    """
    stats = stats or {}
    if not stats.get("aborted"):
        return ""
    if stats.get("aborted_by") == "proxy":
        return "疑似本机代理问题，已提前停手以免白等（请检查代理软件）"
    if stats.get("aborted_by") == "cancel":
        return "已被你中断"
    return "连续失败过多，已停手保护（疑似被限流）"


def failure_hint(stats: dict) -> str:
    """“为什么会有标的没下到”的**教学文案 = 唯一出口**。

    【为什么收成公共件】旧版这段在批量预下载弹窗与数据管理页**各写一份**，
    而且两份已经不一致（一份列了“④ 代理”，另一份没列）—— 同一类防护只改一处
    必然漏另一处（§11.5-11）。代理类失败要**前置**说出来：它是唯一
    “重试无用、必须先去查代理”的原因（§7-E2）。
    ⚠ 依旧不许写死本机端口（§9.3 / §11.5-76③）。
    """
    stats = stats or {}
    base = ("常见原因：① 代码输入有误；② 该股已退市 / 长期停牌，"
            "行情源不再提供（属正常现象）；③ 网络抖动或被限流。")
    if stats.get("aborted_by") == "proxy":
        return ("④ 本机代理软件断连 —— 表现为短时间每一只都失败，"
                "请先检查代理软件（重试无用）。\n" + base)
    return base
