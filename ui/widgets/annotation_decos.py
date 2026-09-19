# ui/widgets/annotation_decos.py
"""画线类型的**附属图元**（v6.25 · §7-B8 R11）—— 档位 / 标签 / 箭头头这类"衍生画法"。

【为什么单独一个文件】
  规格表（`annotation_shapes.py`）= "一种类型一行"的注册处；本文件 = 那些
  `deco(ctx, primary) -> [附属图元]` 的实现。它们有个共同点：**都由主图元派生**
  （主图元被拖动 ⇒ 附属图元按新锚点重建 —— 交互层按"`deco` 存在就重建"推导，
    ★v6.26 H-7 起不再让每种类型自己声明，忘写一个就是一个"文字不跟随"的静默 bug）。
  抽出去之后，规格表只剩"注册与主图元"，两个文件都留在 400 线内（§4 体积铁律）。

【三条纪律】
  · 附属图元**必须**被登记成 extras（由交互层统一做），删主图元时一起删 ——
    否则留下"没人管的线"（§11.5-15 的教训）；
  · 派生画法的**输入永远取存储里的锚点**（`ctx.item["points"]`），交互层在重建前
    会先把拖动后的坐标回写 —— 所以这里不需要、也**不许**自己去摸 ROI 手柄；
  · 标签是**附属图元不是交互件**：不拦鼠标、不参与选中（能选中的只有主图元）。
"""
from __future__ import annotations

import math

import pyqtgraph as pg

from data.annotations import (FIB_ARC_RATIOS, FIB_EXT_RATIOS, FIB_FAN_RATIOS, FIB_RATIOS,
                              FIB_TIME_RATIOS, GANN_FACTORS, PERCENT_RATIOS, REG_SIGMA,
                              fib_levels, gann_label, regression_channel)
from ui.widgets.annotation_items import (FIB_COLORS, _ClickableText, _FillBand, arrow_head,
                                         calendar_days, label, level_line, points_to_xy,
                                         solid_line)

CYCLE_MAX_LINES = 120               # 周期线的**安全阀**（防止间隔过小画出上万条竖线）
ARC_SAMPLES = 48                    # 斐波弧的采样点数（够平滑，又不至于拖慢缩放重算）

_xy = points_to_xy                  # 派生画法的入口坐标换算（与主图元同一份实现）


def _zone_line(x: float, color: str):
    """一档竖向分割线（斐波时间 / 周期线）：不可拖 —— 能拖的只有主图元那条带。"""
    return pg.InfiniteLine(x, angle=90, movable=False,
                           pen=pg.mkPen(color, width=1,
                                        style=pg.QtCore.Qt.PenStyle.DotLine))


def _width_handle(ctx, x: float, price: float):
    """通道 / 回归通道的"宽度手柄" —— 用户拖它改间距（**不需要精确**，不给数字输入框）。

    ⚠ 用文字图元（`⇕`）而不是小方块 ROI：文字是**屏幕尺寸恒定**的，缩放时手柄不会被
    拉成巨块或缩成看不见（ROI 的 size 是数据坐标，会随缩放变形）。
    """
    handle = _ClickableText("⇕", color=ctx.color, anchor=(0.5, 0.5),
                            on_click=ctx.on_select, on_moved=ctx.on_change)
    handle.setPos(float(x), float(price))
    handle._role = "width"          # 回读时靠它在一堆附属图元里认出"哪个是手柄"
    return handle


def deco_hray(ctx, primary) -> list:
    """水平射线：从起点**向右延伸到数据末尾**（与扇形射线同一条道理 —— 它代表"未来"）。

    ⚠ 主图元仍是一条可拖的两点线段（用户拖它以定位/改价），
    第二点只用来表示"从哪开始延伸"，**不是终点**。
    """
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    (x0, y0), (x1, _y1) = pts[0], pts[1]
    end_x = float(max(ctx.size - 1, x1))
    if end_x <= x1:
        return []                      # 已经顶到末尾，不必再接一截
    return [solid_line([(x1, y0), (end_x, y0)], ctx.color, dashed=True)]


def deco_channel(ctx, primary) -> list:
    """平行通道 = **一条严格平行的线 + 填充带 + 宽度手柄**。

    ✅ 用户拍板（§7-B9 C3）：要有填充带（视觉上比普通线粗一档）+ 宽度用手柄。
    ⚠ **平行线 = 基线整体平移同一个 dy**：`[(x0, y0+dy), (x1, y1+dy)]` ——
    v6.26 第一版在这里写成了 `(x0, y1+dy), (x1, y1+dy)` ⇒ 下线变成**水平线**
    （基线越陡越明显，用户截图当场抓包）。教训见 §11.5-43：
    **平移一条线必须平移它的每一个点，绝不能只平移 y 再共用**。
    ⚠ 绘制顺序 = 填充**在最底下**，两条线压在填充上面（否则线被半透明色块罩住发灰）。
    """
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 3:
        return []
    (x0, y0), (x1, y1), (_x2, y2) = pts[0], pts[1], pts[2]
    shift = y2 - y0
    return [
        _FillBand([(x0, y0), (x1, y1), (x1, y1 + shift), (x0, y2)], ctx.color),
        solid_line([(x0, y0), (x1, y1)], ctx.color),          # 基线（= 主图元那两条手柄的连线）
        solid_line([(x0, y0 + shift), (x1, y1 + shift)], ctx.color),   # 平行线：每个点都 +dy
        _width_handle(ctx, x0, y2),
    ]


def deco_reg_channel(ctx, primary) -> list:
    """回归通道：对**收盘价**做最小二乘 ⇒ 中线（主图元）+ **可调的上下轨** + 宽度手柄。

    ★v6.29（用户拍板："正常通道线应该分为三端：起点、终点，还有通道区间"）：
      · p1 / p2 = **拟合区间**（哪一段收盘价参与回归）⇒ 中线由数据算出来、并吸附在回归线上；
      · p3 = **通道区间点**：它到中线的距离就是上下轨的带宽（`±band`，以中线对称）。
        默认 p3 落在自动 `±2σ` 上 ⇒ 观感与旧版一致；拖 ⇕（或 p3）就改宽窄。
      · 换区间后 p3 原地不动 ⇒ 轨道依然经过你给的那个价位（可预期，不会"越调越跑"）。
    """
    fit = regression_channel(getattr(ctx, "closes", None), *_reg_range(ctx))
    if not fit:
        return []
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    x0, x1 = min(pts[0][0], pts[1][0]), max(pts[0][0], pts[1][0])
    start, end, slope = fit["start"], fit["end"], fit["slope"]

    def mid(x):                     # 中线（回归线）在 bar 序号 x 处的拟合价
        return start + slope * (x - x0)

    if len(pts) >= 3:
        x3, y3 = float(pts[2][0]), float(pts[2][1])
        band, anchor = abs(y3 - mid(x3)), (x3, y3)
    else:                           # 兜底（理论上不会走到：回归通道固定 3 个锚点）
        band, anchor = float(fit["band"]), (x1, end + float(fit["band"]))
    sigma = float(fit["band"]) / REG_SIGMA if REG_SIGMA else 0.0
    if abs(band - float(fit["band"])) < 1e-9:
        text = f"±{REG_SIGMA:g}σ"
    elif sigma > 1e-9:
        text = f"±{band:.2f}（{band / sigma:.2f}σ）"
    else:
        text = f"±{band:.2f}"
    # 填充在最底下、两条轨压在上面（同 `deco_channel`，否则线被色块罩住发灰）
    return [
        _FillBand([(x0, start - band), (x1, end - band), (x1, end + band), (x0, start + band)],
                  ctx.color),
        solid_line([(x0, start + band), (x1, end + band)], ctx.color, dashed=True),
        solid_line([(x0, start - band), (x1, end - band)], ctx.color, dashed=True),
        label(text, ctx.color, (x0, start + band)),
        _width_handle(ctx, anchor[0], anchor[1]),
    ]


def _reg_range(ctx):
    """回归区间 = 两个锚点的 bar 序号（前后顺序无所谓）。"""
    pts = _xy(ctx, ctx.item.get("points")) or []
    if len(pts) < 2:
        return (0, 0)
    return (min(pts[0][0], pts[1][0]), max(pts[0][0], pts[1][0]))


def deco_gann_fan(ctx, primary) -> list:
    """甘氏扇形线：**用户画的那条参考线（P1→P2）就是 1×1**，其余射线按经典倍率铺开。

    【为什么是"两点"而不是"一点 + 视图比例"（v6.28 · 用户三轮实测的结论）】
      · 一点版：角度只能由程序猜（屏幕 45° / 可视区间对角线）⇒ **用户无法调整**，
        而且要么全部冲出画面、要么自动长成上下对称的样子 —— 用户原话
        "**会自动生成一个上下对称的样式用户无法调整**"；
      · 两点版（本版，与 TradingView 的甘氏扇形同款）：**第 1 点 = 起点，第 2 点 = 该周期
        期望的涨跌幅度**（这条线就是 1×1）。方向随用户拖（往上 = 未来压力、往下 = 未来支撑，
        **不再自动对称**），陡缓也随用户拖（改比例），落库后仍可随时拖这两个点调整。
    ⚠ 名字里**必须带 gann**：本文件另有一个 `deco_fan`（斐波那契扇形，按竖直比例），
    Python 里"后定义的同名函数会静默覆盖先定义的"，同名会让甘氏线悄悄变成斐波扇形
    （真踩到了，靠"缩放后斜率必须变"的断言才抓出来，§11.5-41）。
    """
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    (x0, y0), (x1, y1) = pts[0], pts[1]       # 起点 + 参考点（参考线 = 1×1）
    if abs(x1 - x0) < 1e-9:
        return []
    unit = (y1 - y0) / (x1 - x0)              # 带符号：负号 ⇒ 整个扇形朝下（未来支撑）
    end_x = float(max(ctx.size - 1, x1))      # 射线延伸到数据末尾（"未来"）
    if end_x <= x0:
        return []
    extras = []
    for index, factor in enumerate(GANN_FACTORS):
        end_price = y0 + unit * factor * (end_x - x0)
        color = FIB_COLORS[index % len(FIB_COLORS)]
        extras.append(solid_line([(x0, y0), (end_x, end_price)], color))
        extras.append(label(gann_label(factor), color, (end_x, end_price)))
    return extras


def deco_fib_arc(ctx, primary) -> list:
    """斐波弧：以两点距离为**屏幕半径**画同心弧（数据坐标里画圆会被拉扁 ⇒ 必须走屏幕）。

    ⚠ 与甘氏扇形同族：**依赖视图**，缩放后要重算。
    """
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    (x0, y0), (x1, _y1) = pts[0], pts[1]
    try:
        center = ctx.view_box.mapViewToScene(pg.QtCore.QPointF(float(x0), float(y0)))
        edge = ctx.view_box.mapViewToScene(pg.QtCore.QPointF(float(x1), float(y0)))
    except Exception:  # noqa: BLE001 —— 尚未布局时画不出来，本次跳过
        return []
    radius = abs(edge.x() - center.x())
    if radius < 1e-6:
        return []
    extras = []
    for index, ratio in enumerate(FIB_ARC_RATIOS):
        color = FIB_COLORS[index % len(FIB_COLORS)]
        points = []
        # 右半圆（-90° → +90°）：弧从"起涨点"向右张开，与扇形/回撤的读法一致
        for step in range(ARC_SAMPLES + 1):
            angle = -0.5 * math.pi + math.pi * step / ARC_SAMPLES
            scene_x = center.x() + radius * ratio * math.cos(angle)
            scene_y = center.y() - radius * ratio * math.sin(angle)   # 屏幕 y 向下
            try:
                view = ctx.view_box.mapSceneToView(pg.QtCore.QPointF(scene_x, scene_y))
            except Exception:  # noqa: BLE001
                break
            points.append((view.x(), view.y()))
        if len(points) > 2:
            extras.append(solid_line(points, color, dashed=True))
            extras.append(label(f"{ratio * 100:.1f}%", color, points[-1]))
    return extras


def deco_wave(ctx, primary) -> list:
    """波浪（**降级版**）：5 个拐点连成的折线 + 浪序标签（1…5）。

    ⚠ 不做自动识别（那是形态识别算法，远期的另一类能力）；用户自己点 5 个拐点。
    """
    pts = _xy(ctx, ctx.item.get("points"))
    if len(pts or []) < 2:
        return []
    return [label(str(index + 1), ctx.color, point, anchor=(0.5, 1.0))
            for index, point in enumerate(pts)]


def deco_head_shoulder(ctx, primary) -> list:
    """头肩形态（**降级版**）：三点折线 = 左肩 / 头 / 右肩，颈线取两肩均价的水平线。

    ⚠ 真颈线要连两个"谷"，但我们只让用户点 3 个**峰** ⇒ 用两肩均价近似，
    并在标签里写"颈线(近似)" —— **不假装精确**（§10-4）。
    """
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 3:
        return []
    (x_left, y_left), (_xh, _yh), (x_right, y_right) = pts[0], pts[1], pts[2]
    neck = (y_left + y_right) / 2.0
    return [
        level_line(x_left, x_right, neck, ctx.color),
        label("颈线(近似)", ctx.color, (x_left, neck)),
        label("左肩", ctx.color, pts[0], anchor=(0.5, 1.0)),
        label("头", ctx.color, pts[1], anchor=(0.5, 1.0)),
        label("右肩", ctx.color, pts[2], anchor=(0.5, 1.0)),
    ]


def deco_ray(ctx, primary) -> list:
    """射线：从第二根手柄沿原始方向**延伸到数据末尾**（不是"无限"，但足够长且不撒谎）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    (x0, y0), (x1, y1) = pts[0], pts[1]
    dx = x1 - x0
    end_x = float(ctx.size - 1) if dx >= 0 else 0.0
    if abs(dx) < 1e-9:
        return []
    if (dx > 0 and x1 >= end_x) or (dx < 0 and x1 <= end_x):
        return []                      # 线段本身已经到头了，不必再接一截
    ratio = (end_x - x0) / dx
    return [solid_line([(x1, y1), (end_x, y0 + (y1 - y0) * ratio)], ctx.color, dashed=True)]


def deco_levels(ctx, primary, ratios) -> list:
    """水平档位（斐波回撤 / 扩展 / 百分比线共用）：一档一条虚线 + 右侧标签。"""
    pts = _xy(ctx, ctx.item.get("points"))
    levels = fib_levels(ctx.item.get("points"), ratios)
    if not pts or len(pts) < 2 or not levels:
        return []
    x0, x1 = pts[0][0], pts[1][0]
    extras = []
    for index, (ratio, price) in enumerate(levels):
        color = FIB_COLORS[index % len(FIB_COLORS)]
        extras.append(level_line(x0, x1, price, color))
        extras.append(label(f"{ratio * 100:.1f}%  {price:.2f}", color, (x1, price)))
    return extras


def deco_fan(ctx, primary) -> list:
    """斐波扇形：从起点发散出三条**射线**（占竖直距离的比例）。

    ✅ 用户拍板（§7-B9 H-7）：扇形的线段常用语义是"**未来可能的支撑位**"⇒
    必须延伸到数据末尾，截止在第二根手柄上等于没画完（与甘氏扇形同一条规矩）。
    """
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    (x0, y0), (x1, y1) = pts[0], pts[1]
    if abs(x1 - x0) < 1e-9:
        return []
    end_x = float(max(ctx.size - 1, x1))      # 射线延伸到数据末尾（"未来"）
    slope_base = (y1 - y0) / (x1 - x0)
    extras = []
    for index, ratio in enumerate(FIB_FAN_RATIOS):
        slope = slope_base * ratio
        end_price = y0 + slope * (end_x - x0)
        color = FIB_COLORS[index % len(FIB_COLORS)]
        extras.append(solid_line([(x0, y0), (end_x, end_price)], color))
        extras.append(label(f"{ratio * 100:.1f}%", color, (end_x, end_price)))
    return extras


def deco_time_zones(ctx, primary) -> list:
    """斐波时间：按时间跨度的比例画竖线（含末端的 100%）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    x0, x1, y0 = pts[0][0], pts[1][0], pts[0][1]
    extras = []
    for index, ratio in enumerate(FIB_TIME_RATIOS):
        xv = x0 + (x1 - x0) * ratio
        color = FIB_COLORS[index % len(FIB_COLORS)]
        extras.append(_zone_line(xv, color))
        extras.append(label(f"{ratio * 100:.1f}%", color, (xv, y0)))
    return extras


def deco_cycle(ctx, primary) -> list:
    """周期线：以区间宽度为间隔，向右等距重复竖线（到数据末尾为止）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    x0, x1, y0 = pts[0][0], pts[1][0], pts[0][1]
    step = max(abs(x1 - x0), 1.0)
    direction = 1.0 if x1 >= x0 else -1.0
    extras = []
    for index in range(1, CYCLE_MAX_LINES + 1):
        xv = x0 + direction * step * index
        if xv > ctx.size - 1 or xv < 0:
            break
        color = FIB_COLORS[index % len(FIB_COLORS)]
        extras.append(_zone_line(xv, color))
        extras.append(label(str(index), color, (xv, y0)))
    return extras


def deco_arrow(ctx, primary) -> list:
    """箭头：主图元是线段，箭头头按**屏幕方向**摆在末端（pxMode ⇒ 缩放不变大）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    (x0, y0), (x1, y1) = pts[0], pts[1]
    head = arrow_head(ctx.view_box, x0, y0, x1, y1, ctx.color)
    return [head] if head is not None else []


def deco_measure(ctx, primary) -> list:
    """测量尺：两端点之间挂一个"涨跌幅 · 根数 · 天数"标签（用户最常问的三个数）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    (x0, y0), (x1, y1) = pts[0], pts[1]
    pct = ((y1 - y0) / y0 * 100.0) if y0 else 0.0
    days = calendar_days(ctx.item.get("points"))
    text = f"{pct:+.2f}% · {abs(x1 - x0):.0f}根 · {days}天"
    return [label(text, ctx.color, ((x0 + x1) / 2.0, (y0 + y1) / 2.0), anchor=(0.5, 1.0))]


def deco_price_measure(ctx, primary) -> list:
    """价格测量：同一天的两个价位，标签给**差价 + 幅度**（不说"点"这种黑话）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    (x0, y0), (_x1, y1) = pts[0], pts[1]
    pct = ((y1 - y0) / y0 * 100.0) if y0 else 0.0
    return [label(f"{y1 - y0:+.2f}（{pct:+.2f}%）", ctx.color, (x0, (y0 + y1) / 2.0),
                  anchor=(0.0, 0.5))]


def deco_time_ruler(ctx, primary) -> list:
    """时间尺：区间中央挂"根数 · 天数"标签（区间本身就是主图元那一条带）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return []
    (x0, y0), (x1, _y1) = pts[0], pts[1]
    days = calendar_days(ctx.item.get("points"))
    return [label(f"{abs(x1 - x0):.0f}根 · {days}天", ctx.color,
                  ((x0 + x1) / 2.0, y0), anchor=(0.5, 1.0))]


def deco_cross(ctx, primary) -> list:
    """交叉线的竖线是**附属图元**，但它同样可拖、同样可选中。

    ⚠ 它自己被拖动时**只落盘、不重建**（挂 `on_persist` 而不是 `on_change`）：
    重建 = 先 `removeItem` 再新建，而"在拖动事件里把自己删掉"是 Qt 的雷区
    （另一个方向的横线被拖时才会重建它 —— 那时被删的是没在被拖的那条，安全）。
    """
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts:
        return []
    vertical = pg.InfiniteLine(pts[0][0], angle=90, movable=True,
                               pen=ctx.pen(ctx.color, False, False))
    vertical.sigClicked.connect(lambda *_a, **_k: ctx.on_select())
    vertical.sigPositionChangeFinished.connect(lambda *_a, **_k: ctx.on_persist())
    return [vertical]


# 各类型实际用的档位（注册处引用这里，**别在规格表里再写一遍数字**）
FIB_DECO = lambda ctx, primary: deco_levels(ctx, primary, FIB_RATIOS)          # noqa: E731
FIB_EXT_DECO = lambda ctx, primary: deco_levels(ctx, primary, FIB_EXT_RATIOS)  # noqa: E731
PERCENT_DECO = lambda ctx, primary: deco_levels(ctx, primary, PERCENT_RATIOS)  # noqa: E731
