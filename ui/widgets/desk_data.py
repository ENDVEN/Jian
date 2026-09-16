# ui/widgets/desk_data.py
"""行情取数与口径（周期 / 复权 / 分钟档位）（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【职责】回答两个问题并落到数据上：
  ① **该读哪一份**（分区 + 键）—— `_data_zone_and_key` 是**全页唯一入口**，别处禁止自己拼字符串
     （防串档 · §11.5-19）；
  ② **取不到怎么办** —— 湖命中即渲染；没有就转后台 `SingleSyncWorker`（UI 不发网络，§10-3）。

【三种"换视图"的代价不同】
  · 日 ↔ 周/月：**同源**（都是日线就地聚合）⇒ 只重渲染，不重新取数；
  · 进出分钟 / 换分钟档位：数据源与键都不同 ⇒ 必须重新取数（`kline_min` 分区）；
  · 日线 ↔ 不复权：**两份独立数据** ⇒ 重新取数（所以画线不会跟着走，回执要讲清楚）。

【竞态防护（§9-O5）】拉取期间用户可能切了标的/周期/复权 —— 过期结果一律丢弃
（判据 = 标的 + 分区 + 档位**三者同时吻合**）。

【约定】状态留页面：`current_symbol/current_name/current_df/current_period/current_minute/
current_adjust/_period_group/data_lake` 与控件回执，本模块只承载行为。
"""
import pandas as pd
from PyQt6.QtWidgets import QMessageBox

from core.utils import (MINUTE_DEPTH_DAYS, MINUTE_PERIODS, is_minute_period,
                        normalize_period, period_label)
from data.sync_service import (ADJUST_QFQ, ZONE_KLINE, ZONE_KLINE_RAW, ZONE_MIN,
                               adjust_label, friendly_fetch_message, minute_key,
                               zone_for_adjust)
from ui.workers import SingleSyncWorker

# 一级周期档位：日/周/月/**分钟**（选"分钟"才出现二级档位 —— 参数只在有意义的档位出现，§10-10）
PERIOD_GROUP_MIN = "MIN"
PERIOD_GROUPS = (("D", "日"), ("W", "周"), ("M", "月"), (PERIOD_GROUP_MIN, "分钟"))
# 二级：分钟档位（各自独立取数；深度见 core.utils.MINUTE_DEPTH_DAYS 的实测值）
MINUTE_SEGMENTS = tuple((key, key[:-1]) for key in MINUTE_PERIODS)   # ("5m","5")…
# 老的 `PERIOD_CHOICES` 保留为"由日线聚合的三档"（`_build_control_panel` 已不再用它）
PERIOD_CHOICES = ("D", "W", "M")


class DeskData:
    """取数/同步/周期/复权（页面持状态，本类持行为）。"""

    # 数据体检判据（★v6.23）
    HEALTH_SEAM_RATIO = 50.0     # 接缝后 20 根中位量 / 前 20 根 ≥ 50 倍（或 ≤1/50）视为量纲接缝
    HEALTH_SEAM_WINDOW = 20
    HEALTH_MIN_BARS = 60         # 太短的数据不做体检（免得噪声当结论）

    def __init__(self, page):
        self.page = page
        # 派生缓存（**可随时丢弃**，不是业务状态）：回执里的两段"体检结论"按标的算一次就够
        self._diff_cache: dict = {}
        self._health_cache: dict = {}

    # ==========================================
    # 查询（UI 不发网络：统一走 SingleSyncWorker → MarketSyncService）
    # ==========================================
    def search_and_load(self):
        p = self.page
        keyword = p.txt_search.text().strip()
        if not keyword:
            return
        result = p.main_win.engine.search_symbol(keyword)   # 经门面取数，UI 不碰 DAO
        if result.empty:
            QMessageBox.warning(p, "未找到", "未找到该标的，请确认花名册已更新。")
            return
        p.load_symbol(str(result.iloc[0]['symbol']), str(result.iloc[0]['name']))

    # ==========================================
    # 取数：分区/键的**唯一入口**（防串档 · §11.5-19）
    # ==========================================
    def _data_zone_and_key(self):
        """当前视图该读**哪个分区、哪个键** —— 全页唯一入口，别处禁止自己拼字符串。

        · 日/周/月 → 分区由**复权口径**决定（`zone_for_adjust`），键 = 标的代码；
        · 分钟 → 分区固定 `kline_min`，键 = `minute_key(标的, 档位)`；分钟与复权无关
          （它只有一种口径 = 真实成交价）。
        """
        p = self.page
        if is_minute_period(p.current_period):
            return ZONE_MIN, minute_key(p.current_symbol or "", p.current_period)
        return zone_for_adjust(p.current_adjust), str(p.current_symbol or "")

    def _loaded_is_minute(self) -> bool:
        """`current_df` 里装的是不是分钟数据 —— **按数据自身判断，不靠记状态**。

        页面可能被外部直接赋值 `current_df`（换壳 / 测试），"我记得我加载过什么"这种状态
        在这种路径上会失真；看数据的实际形状永远是真的。
        """
        p = self.page
        df = p.current_df
        if df is None or len(df) == 0 or "date" not in df.columns:
            return False
        try:
            stamps = pd.to_datetime(df["date"], errors="coerce").dropna()
        except Exception:  # noqa: BLE001
            return False
        if stamps.empty:
            return False
        return bool((stamps.dt.hour != 0).any() or (stamps.dt.minute != 0).any())

    def _reload_for_current_view(self) -> bool:
        """按**当前 (周期, 复权)** 重新取数：湖命中即渲染；没有就联网（后台）。

        :return: True = 本地命中并已渲染；False = 已转后台同步（见 `_on_sync_finished`）
        """
        p = self.page
        if not p.current_symbol:
            p.current_df = pd.DataFrame()
            p.render_charts()
            p._refresh_adjust_hint()
            return False
        zone, key = self._data_zone_and_key()
        if p.data_lake.exists(zone, key):
            df = p.data_lake.load_data(zone, key)
            if not df.empty:
                p.current_df = df
                p.render_charts()
                p._refresh_adjust_hint(loaded_from_lake=True)
                return True
        # 换数据源时**先把旧数据丢掉**：宁可先显示空图，也绝不出现"分钟的数据配日线的标题"
        p.current_df = pd.DataFrame()
        p.render_charts()
        p.sync_cloud()      # 本地没这一份 → 转后台取数
        p._refresh_adjust_hint(pending=True)
        return False

    def load_symbol(self, symbol: str, name: str = "") -> bool:
        """载入某标的：**数据湖优先**，没有才联网。

        :return: True = 本地命中并已渲染；False = 转后台联网同步（见 `_on_sync_finished`）。
        """
        p = self.page
        p.current_symbol = str(symbol)
        p.current_name = str(name or p.watchlist.display_name(symbol))
        # 顺手把自选里的名称刷新为花名册里的最新名称（旧名不当真相）
        if p.watchlist.update_name(p.current_symbol, p.current_name):
            p._refresh_watchlist()
        return self._reload_for_current_view()

    def sync_cloud(self):
        """把当前标的同步到最新（日线：本地有=增量 / 没有=全量；**分钟：整段快照**）。

        【为什么名字不叫 force_sync】它**不是**强制全量（§9-O4 的历史教训）：
        全量重下统一放在「🗄 数据管理」页，避免误触把 2010 起的整段重下一遍。
        """
        p = self.page
        if not p.current_symbol:
            QMessageBox.information(p, "提示", "请先搜索并选中一个标的，再进行云端同步。")
            return
        p.btn_sync.setEnabled(False)
        p.lbl_sync_status.setText("正在同步…")
        zone, _key = self._data_zone_and_key()
        period = p.current_period if is_minute_period(p.current_period) else None
        p.fetch_thread = SingleSyncWorker(
            p.current_symbol, zone=zone, force_full=False, parent=p, period=period)
        p.fetch_thread.finished.connect(p._on_sync_finished)
        p.fetch_thread.start()

    def _on_sync_finished(self, result: dict):
        p = self.page
        p.btn_sync.setEnabled(True)
        symbol = str(result.get("symbol", p.current_symbol) or p.current_symbol)

        # 【竞态防护】拉取期间用户可能切了标的 / 周期 / 复权 —— 过期结果必须丢弃（§9-O5）。
        # 判据 = 标的 + 分区 + 档位**三者同时吻合**（只看标的会漏掉"切了周期"这种过期）。
        zone, key = self._data_zone_and_key()
        expected_period = p.current_period if is_minute_period(p.current_period) else ""
        if (symbol != p.current_symbol
                or str(result.get("zone") or "") != zone
                or str(result.get("period") or "") != expected_period):
            p.lbl_sync_status.setText("")
            return

        if not result.get("ok"):
            p.lbl_sync_status.setText("同步失败")
            QMessageBox.warning(p, "行情同步失败", friendly_fetch_message(symbol, result))
            return

        if result.get("skipped"):
            p.lbl_sync_status.setText("已是最新，无需更新")
        else:
            added = int(result.get("added", 0) or 0)
            unit = "根" if expected_period else "行"
            p.lbl_sync_status.setText(f"已更新，新增 {added} {unit}" if added > 0 else "已更新")

        df = p.data_lake.load_data(zone, key)
        if df.empty:
            QMessageBox.critical(p, "错误", f"{symbol} 行情拉取失败（未取得数据）。")
            return
        p.current_df = df
        p.render_charts()
        p._refresh_adjust_hint(loaded_from_lake=True)

    # ==========================================
    # 周期（★STEP 3b：一级档位 + 分钟二级档位；UI 与测试走**同一个入口**）
    # ==========================================
    def select_period_group(self, group: str) -> None:
        """切一级周期档位（`D/W/M/MIN`）—— 分段控件与测试**同一入口**，避免测试绕过信号。"""
        p = self.page
        group = str(group or "D")
        if group not in dict(PERIOD_GROUPS):
            return
        if group == p._period_group:
            p.seg_period.set_current(group)     # 幂等：只把控件对齐，不重复干活
            return
        if not p.seg_period.set_current(group):
            return
        self._apply_period_group(group)

    def _on_period_group_clicked(self, group: str) -> None:
        self._apply_period_group(str(group))

    def _apply_period_group(self, group: str) -> None:
        """把一级档位落到实处：改状态 → 同步控件 → **按需**重新取数。

        【为什么不是每次都重取】日 ↔ 周/月 是**同源**（都是日线数据就地聚合）⇒ 只重渲染；
        只有"进出分钟"（数据源不同）或"换分钟档位"（键不同）才需要重新取数。
        """
        p = self.page
        p._period_group = group
        p.current_period = p.current_minute if group == PERIOD_GROUP_MIN else group
        self._sync_period_widgets()
        if group == PERIOD_GROUP_MIN or self._loaded_is_minute():
            self._reload_for_current_view()
        else:
            p.render_charts()

    def select_minute(self, period: str) -> None:
        """切分钟档位（各档位独立取数，见 `MINUTE_DEPTH_DAYS` 的实测深度）。"""
        p = self.page
        period = normalize_period(period)
        if period not in MINUTE_PERIODS or period == p.current_minute:
            p.seg_minute.set_current(p.current_minute)
            return
        if not p.seg_minute.set_current(period):
            return
        self._apply_minute(period)

    def _on_minute_clicked(self, period: str) -> None:
        self._apply_minute(str(period))

    def _apply_minute(self, period: str) -> None:
        p = self.page
        p.current_minute = normalize_period(period)
        p.current_period = p.current_minute
        p._save_desk_ui(minute_period=p.current_minute)
        self._sync_period_widgets()
        self._reload_for_current_view()

    def _sync_period_widgets(self) -> None:
        """把周期/复权控件的可见性与可用性对齐状态（**控件外观只是状态的投影**，§7-B6-D-6）。"""
        p = self.page
        minute_mode = (p._period_group == PERIOD_GROUP_MIN)
        for widget in (p.lbl_minute_unit, p.seg_minute, p.lbl_minute_depth):
            widget.setVisible(minute_mode)
        if minute_mode:
            p.lbl_minute_depth.setText(
                f"约可回溯 {MINUTE_DEPTH_DAYS.get(p.current_minute, 0)} 个交易日"
                f"（新浪源上限 1970 根）")
        # 分钟只有一种口径 ⇒ 复权**禁用 + 说明**（不是隐藏：藏起来用户会以为前复权也在生效）
        p.seg_adjust.setEnabled(not minute_mode)
        p.seg_adjust.setToolTip(
            "分钟数据只有一种口径（真实成交价，不含复权），所以切到分钟时本控件不可用。"
            if minute_mode else
            "**前复权**（默认）：看长期趋势 / 算指标用它；**不复权**：看当年的真实价位。\n"
            "两份数据**各存一个分区**，来回切换不覆盖、也不会重复下载。")
        p.lbl_caliber_note.setText("分钟：真实成交价口径（不含复权）" if minute_mode else "")

    # ==========================================
    # 复权（v6.13 · P8 收尾）
    # ==========================================
    def select_adjust(self, adjust: str) -> None:
        """切复权口径（分段控件与测试**同一入口**）。"""
        p = self.page
        adjust = ADJUST_QFQ if adjust is None else str(adjust)
        if adjust == p.current_adjust:
            p.seg_adjust.set_current(adjust)
            return
        if not p.seg_adjust.set_current(adjust):
            return
        self._apply_adjust(adjust)

    def _on_adjust_clicked(self, adjust: str) -> None:
        self._apply_adjust(str(adjust))

    def _apply_adjust(self, adjust: str) -> None:
        """切换复权口径：换分区重新载入（本地没有就自动联网同步）。

        ⚠ 不复权与前复权是**两份独立数据**，所以这里不是"重算"，而是**重新取数**；
        也因此**画线不会跟着走**（不复权的价格坐标跟前复权完全不同，
        硬搬过去会画在莫名其妙的位置）—— 面板会明确提示这一点。
        """
        p = self.page
        p.current_adjust = adjust
        if p._annotations is not None:       # 构造期可能还没挂好（本函数先于 _build_chart_area）
            p._annotations.clear_view()       # 先清掉旧口径的线，避免"挂在错误价位"上闪一下
        self._sync_period_widgets()
        if not p.current_symbol:
            self._refresh_adjust_hint()
            return
        self._reload_for_current_view()

    def _adjust_warning(self) -> str:
        """不复权的两个已知差异（前复权时为空串）。文案只在这里写一份，两处回执共用。"""
        if self.page.current_adjust == ADJUST_QFQ:
            return ""
        return "⚠ 不复权按真实价显示：指标/收益会含除权跳空；画线也不与前复权共用"

    def _adjust_warning_short(self) -> str:
        """回执行的**一行版**警示（完整说法在 tooltip 里，见 `_adjust_warning`）。"""
        return ("" if self.page.current_adjust == ADJUST_QFQ
                else "⚠ 含除权跳空，画线不共用")

    def _refresh_adjust_hint(self, loaded_from_lake: bool = False, pending: bool = False):
        """数据口径回执：现在看的是哪一份、有哪些已知差异、在不在取数。

        :param pending: True = 刚切过去、正在联网取这一份（不显示根数，避免报旧口径的行数）
        """
        p = self.page
        rows = len(p.current_df) if p.current_df is not None else 0

        # ---- 分钟：口径不是"复权"，而是**真实成交价**（实测 adjust 不生效）----
        if is_minute_period(p.current_period):
            zone, key = self._data_zone_and_key()
            depth = MINUTE_DEPTH_DAYS.get(normalize_period(p.current_period), 0)
            label = period_label(p.current_period)
            # 深度是**档位的已知事实**（实测表），不是"数据加载出来后才知道的东西"
            # ⇒ 无论有没有数据、在不在取数都写明，用户一眼知道这个档位能看多远。
            # ★STEP 5：**一行摘要**（窄面板不再折行），完整说明进 tooltip。
            if pending:
                text = f"{label} · 正在从云端取这一档…（约 {depth} 个交易日 · 真实成交价）"
            elif rows:
                text = f"{label} · {rows} 根（约 {depth} 个交易日）· 真实成交价"
            else:
                text = f"{label}（约 {depth} 个交易日）· 真实成交价"
            health = self._data_health_note()          # ★v6.23 数据体检（不静默）
            if health:
                text += f" · {health}"
            p.lbl_adjust_hint.setText(text)
            p.lbl_adjust_hint.setToolTip(
                f"数据湖分区：{zone}（键 {key}，按档位各存一份）\n"
                f"该档位可回溯约 {depth} 个交易日（数据源上限 1970 根）。\n"
                "**分钟数据只有一种口径：真实成交价（不含复权）** —— "
                "实测新浪分钟源的 adjust 参数不生效，所以不假装有'前复权分钟'。\n"
                + (f"（本次本地命中：{zone}/{key}）\n" if loaded_from_lake else "")
                + "「🗄 数据管理」页可单独查看/删除这一份；分钟不接批量预下载（避免高频轰炸）。")
            return

        zone = zone_for_adjust(p.current_adjust)
        label = adjust_label(p.current_adjust)
        # ★STEP 5：一行摘要 = 口径 + 根数（+ 已知差异的短版）；完整说法在 tooltip
        if pending:
            text = f"{label} · 正在从云端取这一份…"
        elif rows:
            text = f"{label} · {rows} 根"
        else:
            text = f"{label}"
        short = self._adjust_warning_short()
        if short:
            text += f" · {short}"
        # ★v6.23（用户 2026-09-17 反馈）：把"差异在哪一天"和"数据有没有毛病"都写进行内摘要
        for note in (self._adjust_diff_note(), self._data_health_note()):
            if note:
                text += f" · {note}"
        p.lbl_adjust_hint.setText(text)
        p.lbl_adjust_hint.setToolTip(
            f"数据湖分区：{zone}\n"
            + (f"本次本地命中：{zone}\n" if loaded_from_lake else "")
            + (f"{self._adjust_warning()}\n" if self._adjust_warning() else "")
            + "【为什么切了口径看着一样】前复权以**最新价**为锚，只把**除权日之前**的历史价格"
              "往回改 —— 除权日之后两份**逐根完全相同**。所以只看最近一段会觉得'两个口径没差别'，"
              "往回拖到除权日之前就能看到差异（行内摘要会给出最近一次跳空的日期）。\n"
            + "「🗄 数据管理」页可单独查看/删除这一份（另一份不受影响）。")

    # ==========================================
    # 数据体检（★v6.23）：**不静默** —— 把"这份数据有毛病"直接写进回执
    # ==========================================
    def _adjust_diff_note(self) -> str:
        """两份数据（前复权 / 不复权）的**差异定位**：最近一次跳空在哪天、多大。

        【要解决的困惑】前复权的差异**只在除权日之前**（除权日之后两份逐根相同），
        用户看最近一段会以为"复权开关没用"（2026-09-17 实测反馈）。
        【诚实】只做两份数据的**事实比对**（不猜除权原因、不说"分红/送股"）；另一份本地
        还没有时返回空串（这时回执行本来就会写"正在从云端取"）。
        【成本】按 symbol 缓存，只算一次（比 ~4000 行，毫秒级）。
        """
        p = self.page
        symbol = str(p.current_symbol or "")
        if not symbol:
            return ""
        if symbol in self._diff_cache:
            return self._diff_cache[symbol]
        note = ""
        try:
            qfq = p.data_lake.load_data(ZONE_KLINE, symbol)
            raw = p.data_lake.load_data(ZONE_KLINE_RAW, symbol)
            if not qfq.empty and not raw.empty:
                left = qfq[["date", "close"]].rename(columns={"close": "qfq"})
                right = raw[["date", "close"]].rename(columns={"close": "raw"})
                both = pd.merge(left, right, on="date", how="inner").dropna()
                both = both[both["raw"] > 0].reset_index(drop=True)
                if len(both) >= 2:
                    ratio = both["qfq"] / both["raw"]
                    # 两份的**比例**发生变化的那一天 = 除权日（比例在事件前后各自恒定）
                    changed = ratio.pct_change().abs() > 0.001
                    hits = both.index[changed]
                    if len(hits):
                        i = int(hits[-1])                       # 最近一次
                        jump = float(both.loc[i, "raw"] / both.loc[i - 1, "raw"] - 1)
                        note = (f"⚠ 除权跳空最近一次 {str(both.loc[i, 'date'])[:10]}"
                                f"（{jump:+.1%}）")
        except Exception:  # noqa: BLE001 —— 回执绝不能因为比对失败而崩
            note = ""
        self._diff_cache[symbol] = note
        return note

    def _data_health_note(self) -> str:
        """数据体检：这份数据里有没有**物理上不可能**的东西。

        两条判据都**精确**（不靠猜）：
          ① **非正价行**（价格 ≤ 0）—— 任何口径下都无意义，一根就能把主图 y 轴拽到负数区、
             整张图被压扁（实据：300750 的 2018-06 段 `open=-4.03 / close=-0.68`）；
          ② **成交量量纲接缝** —— 以某天为界，后 20 根**中位量** ≥ 前 20 根的 50 倍
             （实据：300750 的「手 / 股」接缝 ×159）。用中位数比对而不是单根，
             是为了把"复牌 / 涨停放量"这类**单日**跳变排除掉（它们会回落到同一基线）。
        命中就点名"走「🗄 数据管理 → 重新全量下载」"——那是唯一能修回历史的手段
        （增量永远只补最新几天，§9-M3 的数据窗纪律）。
        """
        p = self.page
        df = p.current_df
        if df is None or len(df) < self.HEALTH_MIN_BARS or "close" not in df.columns:
            return ""
        key = (str(p.current_symbol or ""), str(p.current_adjust), len(df))
        if key in self._health_cache:
            return self._health_cache[key]

        issues: list = []
        price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
        if price_cols:
            bad = int((pd.to_numeric(df[price_cols].stack(), errors="coerce")
                       .unstack() <= 0).any(axis=1).sum())
            if bad:
                issues.append(f"非正价 {bad} 根")
        if "volume" in df.columns:
            volume = pd.to_numeric(df["volume"], errors="coerce").astype(float)
            seam = self._volume_seam(volume)
            if seam is not None:
                index, ratio = seam
                stamp = ""
                try:
                    stamp = str(pd.to_datetime(df["date"].iloc[index]))[:10]
                except Exception:  # noqa: BLE001
                    stamp = f"第 {index} 根"
                issues.append(f"量能接缝 {stamp}（×{ratio:.0f}）")
        note = ("⚠ 疑似数据异常：" + "、".join(issues)
                + " · 建议「🗄 数据管理 → 重新全量下载」修回历史") if issues else ""
        self._health_cache[key] = note
        return note

    def _volume_seam(self, volume):
        """找"成交量量纲接缝"。

        以 i 为界：`median(volume[i:i+w]) / median(volume[i-w:i])` ≥ 50（或 ≤ 1/50）。
        返回 `(接缝处的行号, 倍数)`，找不到返回 None。
        """
        w = self.HEALTH_SEAM_WINDOW
        n = len(volume)
        if n < w * 2:
            return None
        rolling = volume.rolling(w).median()
        for i in range(w, n - w + 1):
            before = rolling.iloc[i - 1]
            after = rolling.iloc[i + w - 1]
            if pd.isna(before) or pd.isna(after) or before <= 0 or after <= 0:
                continue
            ratio = float(after / before)
            if ratio >= self.HEALTH_SEAM_RATIO or ratio <= 1.0 / self.HEALTH_SEAM_RATIO:
                return i, ratio
        return None
