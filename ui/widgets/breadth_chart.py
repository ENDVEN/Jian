# ui/widgets/breadth_chart.py
"""📊 M3 图表的**显示选项目录**（★1.73 起：图本体已搬到 `ui/widgets/breadth_rows.py`）。

【这个文件现在只干什么】放**"能选什么"**的目录常量（每行怎么画 / 指数副图怎么画），
  由抽屉的展示卡、流程与偏好恢复三处共用。放一处的理由 = §11.5-112：同一份目录不许两处
  各写一份，否则"下拉里有、渲染不认"（或反之）这类漂移必然发生。

【历史与清理】v6.38 起这里是 `BreadthChart`（单序列 + 指数副图的双窗格图）的所在地；
  ★1.73 / §7-B16 期 1 升级为**多统计项多行小图**后，实现整块搬进
  `breadth_rows.BreadthRowsChart`，旧的 `BreadthChart` / `_BreadthTickAxis` / `RATIO_MAX_PAD` /
  私有配色与 `_INDEX_*` 重复常量**已删除**（★1.74 复核发现的死代码）。
  ⚠ 冒烟有一条护栏：**本模块不许再定义任何 `QWidget` 子类**（防止死代码复活 —— 谁要新图表，
  请进 `breadth_rows.py`）。
"""
from __future__ import annotations

__all__ = ['CHART_TYPES', 'DEFAULT_CHART_TYPE', 'INDEX_STYLES', 'DEFAULT_INDEX_STYLE',
           'INDEX_COLOR', 'INDEX_OHLC_NEED']

# 统计项**每行**的画法（唯一事实来源：抽屉下拉与 `breadth_rows.render(chart_type=…)` 共用）
CHART_TYPES = (('bars', '柱状 + 趋势线（推荐）'), ('line', '折线 + 面积'))
DEFAULT_CHART_TYPE = 'bars'

# 指数副图可选图形（★v6.43 用户拍板：不止折线 —— K线/美国线都要有）。
# K线/美国线需要本地指数有开高低列；缺列诚实退回折线（不画假四价）。
INDEX_STYLES = (('line', '折线'), ('area', '面积'),
                ('kline', 'K 线'), ('ohlc', '美国线 (OHLC)'))
DEFAULT_INDEX_STYLE = 'line'
INDEX_COLOR = '#5B6472'                       # 副图主色（折线 / 面积填充）
INDEX_OHLC_NEED = ('open', 'high', 'low')     # kline/ohlc 的最低列要求（close 恒需）
