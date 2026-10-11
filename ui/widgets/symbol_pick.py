# ui/widgets/symbol_pick.py
"""
选标的的**共用件**（★用户 2026-10-01 追加需求：*"标的要像 M1 一样 —— 手输 + 额外一个「选择」按钮，
选好后有 M1 同款的文字提示"*）。

M1（`ui/widgets/backtest_flow.select_symbol`）与 🧪 参数研究页（§7-B15）要的是同一件事：
**搜索 → 校验 A 股 → 回一句人话提示**。各写一份 ⇒ 提示文案与校验口径必然漂
（§11.5-112 同族：同一个零件两处两张脸）。所以口径收在这里，各页都调它。

【边界】本件只做"查 + 判 + 组文案"，**不碰任何控件**：调用方拿到 `(symbol, name, hint)` 自己回填
（M1 回填 `txt_symbol / lbl_symbol`；参数研究页回填 `in_symbol / lbl_symbol + 数据回执`）。

【为什么走 `main_win.engine.search_symbol`】那是 DataEngine 门面 —— UI 层不碰 DAO（§10 分层）。

★1.70 / §11.5-125：**"花名册为空"曾经是一堵没有门的墙** —— 新机器上花名册天然为空，
  用户输 600519 得到"未找到"、输"茅台"还是"未找到"，**没有任何提示告诉他该怎么办**。
  现在三件事一起给：① **代码直通**（花名册只该用于"按名字找代码"，不该当门票）；
  ② 花名册为空时给**明确两条路 + 一键同步**；③ 决策收成**纯函数** `decide_keyword`（可断言）。
"""
from __future__ import annotations

import re

from PyQt6.QtWidgets import QMessageBox

from data.akshare_feed import is_stock_code

__all__ = ["CACHED_SUFFIX", "ROSTER_EMPTY_GUIDE", "decide_keyword",
           "normalize_stock_code", "offer_roster_sync", "pick_symbol",
           "roster_empty", "symbol_hint"]

CACHED_SUFFIX = " · 已缓存"

# 花名册为空时给**新用户**的指引（唯一文案出口；各页共用，别再各写一句）
ROSTER_EMPTY_GUIDE = (
    "本机【花名册】还是空的 —— 它是「按名称搜标的」的前提（全市场 A 股 + 期货对照表），\n"
    "新装的机器第一次都要同步一次（它不在 git 里，属于你的本机数据）。\n\n"
    "两条路，任选：\n"
    "  ① **直接输 6 位代码**（如 600519）—— 花名册为空也能查，这条现在就能用；\n"
    "  ② 想**按名称搜**（如“茅台”）⇒ 点下面的「立即同步花名册」按钮，"
    "约 17 秒（走交易所官方名单）。"
)

# 6 位纯数字，允许带 sh / sz / bj 前缀（本仓并存两套写法）
_CODE_RE = re.compile(r"^(?:(sh|sz|bj))?(\d{6})$", re.I)


def normalize_stock_code(keyword: str) -> str | None:
    """把用户输入认成**合法 6 位 A 股代码** ⇒ 返回纯 6 位数字；认不出返回 None。

    接受：`600519` / `sh600519` / `SZ000001` / `bj920000`。
    ⚠ **不认**中文名、也不认期货品种码（RB/IF…）—— 期货走花名册"按字母命中"那条通道。
    """
    m = _CODE_RE.match(str(keyword or "").strip())
    return m.group(2) if m else None


def decide_keyword(keyword: str, hits, *, roster_empty: bool) -> tuple[str, str, str]:
    """关键词 → 决策（**纯函数**，UI 只把状态翻成文案）。返回 `(状态, symbol, name)`。

    状态四态，**顺序即优先级**：
      · `hit`         —— 花名册命中（自带名称）；
      · `direct`      —— 没命中，但输入本身就是**合法 6 位代码** ⇒ **直通**
                         （花名册的职责是"按名字找代码"，**不该当门票**）；
      · `need_roster` —— 没命中又不是代码，且**花名册是空的** ⇒ 必须给新用户明确出口；
      · `not_found`   —— 花名册非空、但确实没有这一只。
    """
    kw = str(keyword or "").strip()
    if hits is not None and len(hits) > 0:
        row = hits.iloc[0]
        return "hit", str(row["symbol"]), str(row.get("name", "") or "")
    code = normalize_stock_code(kw)
    if code is not None:
        return "direct", code, ""
    if roster_empty:
        return "need_roster", "", ""
    return "not_found", "", ""


def roster_empty(page) -> bool:
    """花名册（A 股那半边）是否为空 —— 走门面；**异常一律当"空"**（宁可多给引导，也别给死路）。"""
    try:
        return not page.main_win.engine.list_stock_symbols()
    except Exception:  # noqa: BLE001 —— 门面抽风不该把"给用户的出口"也一起弄没
        return True


def offer_roster_sync(page) -> bool:
    """★1.70：**一键同步花名册**（新用户第一次的出口）。成功返回 True。

    ⚠ 线程一律用 `ui/workers` 的（全 app QThread 只此一处，§10-12）；同步约十几秒，
      必须有进度反馈 —— 没有进度条的十几秒，用户会以为它卡死了（刚修过这类问题）。
    """
    from PyQt6.QtWidgets import QProgressDialog

    from ui.workers import RosterSyncWorker

    dlg = QProgressDialog("正在同步花名册（交易所官方名单，约 17 秒）…", "取消", 0, 0, page)
    dlg.setWindowTitle("同步花名册")
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)

    state = {"ok": False, "msg": ""}
    worker = RosterSyncWorker(page)

    def _on_ok(rep: dict) -> None:
        state["ok"] = True
        state["msg"] = (f"已同步 {rep.get('a_share', 0)} 只 A 股 + "
                        f"{rep.get('futures', 0)} 只期货（{rep.get('elapsed', 0):.1f} 秒）。")
        dlg.close()

    def _on_bad(reason: str) -> None:
        state["msg"] = str(reason)
        dlg.close()

    worker.finished_ok.connect(_on_ok)
    worker.failed.connect(_on_bad)
    worker.start()
    dlg.exec()
    if not state["ok"] and not state["msg"]:
        state["msg"] = "同步已取消（在途请求会自己结束，最长 20 秒）。"
    worker.wait(30000)
    if state["ok"]:
        QMessageBox.information(page, "同步完成",
                                state["msg"] + "\n现在可以按名称搜索了。")
    else:
        QMessageBox.warning(page, "同步未完成",
                            state["msg"] + "\n\n也可以先用 6 位代码直接查；"
                                           "稍后重试即可（额度被拒约 30 分钟自恢复）。")
    return state["ok"]


def symbol_hint(name: str, symbol: str, cached: bool = False) -> str:
    """M1 同款提示文本：`贵州茅台 (600519) · 已缓存`。

    ⚠ 没缓存时**不带后缀**（别谎报"已缓存"—— 用户会以为可以直接跑）。
    """
    return f"{name} ({symbol})" + (CACHED_SUFFIX if cached else "")


def pick_symbol(page, keyword: str, *, lake=None):
    """关键词 → `(symbol, name, hint)`；**代码直通**（花名册为空也放行）。

    :param page: 宿主页面（只用作消息框父窗口，以及取 `main_win.engine`）
    :param lake: 数据湖（判"已缓存"）；None = 不判缓存（提示不带后缀）
    """
    keyword = str(keyword or "").strip()
    if not keyword:
        QMessageBox.information(page, "提示", "请输入股票代码或名称。")
        return None
    try:
        hits = page.main_win.engine.search_symbol(keyword)
    except Exception as e:                       # noqa: BLE001 —— 查询失败也要给出路
        QMessageBox.warning(page, "查询失败",
                            f"查花名册时出错：{e}\n\n可以直接输 6 位代码（如 600519）试试。")
        return None

    state, symbol, name = decide_keyword(keyword, hits, roster_empty=roster_empty(page))

    if state == "need_roster":
        QMessageBox.information(page, "花名册是空的（要先同步一次）", ROSTER_EMPTY_GUIDE)
        offer_roster_sync(page)
        return None
    if state == "not_found":
        QMessageBox.warning(page, "未找到",
                            f"花名册里没有 '{keyword}'。\n\n"
                            "试试 6 位代码（如 600519），或核对名称是否写全。")
        return None
    if not is_stock_code(symbol):
        QMessageBox.warning(page, "仅支持A股", f"'{name or symbol}' 不是A股标的。")
        return None

    cached = bool(lake.exists("kline_daily", symbol)) if lake is not None else False
    if state == "direct":
        # 名称待补：**绝不编造**（§10-4）——直通给的是代码，名字等花名册同步后自然补齐
        return symbol, name or symbol, (f"{symbol}（花名册未命中 ⇒ 按代码直通；"
                                        f"同步花名册后名称会自动补齐）"
                                        + (CACHED_SUFFIX if cached else ""))
    return symbol, name, symbol_hint(name, symbol, cached)
