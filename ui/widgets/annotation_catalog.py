# ui/widgets/annotation_catalog.py
"""画线类型的**目录**（v6.24 · §7-B8 R10/R11）—— **零 Qt、纯数据**。

【为什么要有"目录"而不是直接用能画的那几种】用户原话：
  "正常软件里面画线类型差不多有 **30 多个**，请**避免后续随着类型变多影响观感**。"
⇒ 目录一次列全 32 种（**含尚未实现的**），靠四件事让"多"不显乱：
  ① **按类分组**（6 类）② **每类一个色相**（分类色条 + 该类图标同色，最关键的一条）
  ③ **统一行式**（图标 · 名称 · 编号）④ **固定可视高度 + 内部滚动 + 吸顶分类标题**。
  ⚠ **未实现的项照常出现在目录里**，但**必须明确标注"待实现"** ——
  绝不允许"点了没反应也不说话"（§9-Q 教训：不静默）。
  ⚠ **禁止搜索栏**（用户二轮拍死："用户根本不会去用这个功能"）—— 设计空间只剩"怎么摆得不乱"。

【为什么零 Qt】分类 / 编号 / 快捷键 / 实现状态全是**规则**，抽出来能被纯断言守着；
图标只是按 `icon` 字段画出来的示意（画法在 `ui/widgets/annotation_icons.py`，与数据解耦）。

⚠ **`implemented` 必须与 `annotation_layer.DRAWABLE_KINDS` 严格一致**：目录说能画、实际画不出
（或反过来）都是骗人的。冒烟里有一条**双向**断言钉住这件事。
"""

# 六类（顺序即显示顺序；色相一眼可分，这是"让 32 种不乱"最关键的一条）
CATEGORIES = (
    ("trend", "趋势 / 通道", "#1976D2"),
    ("level", "水平 / 垂直", "#00897B"),
    ("shape", "形态", "#7E57C2"),
    ("fib", "斐波 / 分割", "#E65100"),
    ("time", "时间 / 测量", "#2E7D32"),
    ("mark", "文字 / 标记", "#5B6472"),
)
CATEGORY_COLORS = {key: color for key, _name, color in CATEGORIES}
CATEGORY_NAMES = {key: name for key, name, _color in CATEGORIES}

# 32 种（编号 = 对照编号；**1–9 兼作数字快捷键** —— 见 `is_shortcut`）
# `icon` 是**语义化的线型示意**的键（画法在 annotation_icons），不是装饰：
# 目标是"看一眼就知道画出来长什么样"，把用户的再教育成本降下来（用户原话）。
ENTRIES = (
    # ---- 趋势 / 通道 ----
    dict(num=1, kind="trend", name="趋势线", category="trend", icon="trend", implemented=True),
    dict(num=2, kind="ray", name="射线", category="trend", icon="ray", implemented=True),
    dict(num=3, kind="channel", name="平行通道", category="trend", icon="channel", implemented=True),
    dict(num=4, kind="reg_channel", name="回归通道", category="trend", icon="channel", implemented=True),
    dict(num=5, kind="fan", name="扇形线", category="trend", icon="fan", implemented=True),
    # ---- 水平 / 垂直 ----
    dict(num=6, kind="hline", name="水平线", category="level", icon="hline", implemented=True),
    dict(num=7, kind="vline", name="垂直线", category="level", icon="vline", implemented=True),
    dict(num=8, kind="hray", name="水平射线", category="level", icon="ray_h", implemented=True),
    dict(num=9, kind="cross", name="交叉线", category="level", icon="cross", implemented=True),
    dict(num=10, kind="hband", name="价格带", category="level", icon="band", implemented=True),
    # ---- 形态 ----
    dict(num=11, kind="rect", name="矩形", category="shape", icon="rect", implemented=True),
    dict(num=12, kind="triangle", name="三角形", category="shape", icon="triangle", implemented=True),
    dict(num=13, kind="ellipse", name="椭圆", category="shape", icon="ellipse", implemented=True),
    dict(num=14, kind="arrow", name="箭头", category="shape", icon="arrow", implemented=True),
    dict(num=15, kind="wave", name="波浪", category="shape", icon="wave", implemented=True),
    dict(num=16, kind="head_shoulder", name="头肩形态", category="shape", icon="wave", implemented=True),
    # ---- 斐波 / 分割 ----
    dict(num=17, kind="fib", name="斐波那契回撤", category="fib", icon="fib", implemented=True),
    dict(num=18, kind="fib_ext", name="斐波那契扩展", category="fib", icon="fib_ext", implemented=True),
    dict(num=19, kind="fib_fan", name="斐波那契扇形", category="fib", icon="fan", implemented=True),
    dict(num=20, kind="fib_arc", name="斐波那契弧", category="fib", icon="arc", implemented=True),
    dict(num=21, kind="fib_time", name="斐波那契时间", category="fib", icon="vbands", implemented=True),
    dict(num=22, kind="percent", name="百分比线", category="fib", icon="pct", implemented=True),
    # ---- 时间 / 测量 ----
    dict(num=23, kind="time_ruler", name="时间尺", category="time", icon="ruler", implemented=True),
    dict(num=24, kind="cycle", name="周期线", category="time", icon="vbands", implemented=True),
    dict(num=25, kind="measure", name="测量尺", category="time", icon="measure", implemented=True),
    dict(num=26, kind="price_measure", name="价格测量", category="time", icon="measure_v", implemented=True),
    dict(num=27, kind="time_span", name="时间区间", category="time", icon="band", implemented=True),
    # ---- 文字 / 标记 ----
    dict(num=28, kind="text", name="文字标注", category="mark", icon="text", implemented=True),
    dict(num=29, kind="price_tag", name="价格标签", category="mark", icon="tag", implemented=True),
    dict(num=30, kind="marker", name="箭头标记", category="mark", icon="marker", implemented=True),
    dict(num=31, kind="comment", name="评论气泡", category="mark", icon="comment", implemented=True),
    dict(num=32, kind="dots", name="标记点", category="mark", icon="dots", implemented=True),
)
# ✅ v6.26（§7-B9 STEP 4）：**32 种全部可画**（最后 5 种也落地了）。
#   其中三种按用户拍板**降级**实现（不做自动识别）：波浪 = 5 个拐点的折线、
#   头肩形态 = 三点 + 近似颈线；两种**依赖视图**（甘氏扇形 / 斐波弧）随缩放重算
#   —— 用户原话："甘氏图要做随缩放变化…不能偷工减料缩水糊弄"。
#   目录仍保留"已登记未实现"这套机制（`implemented=False` ⇒ tile 标「待实现」、
#   点了明确告知），将来再加新类型时**先登记、后实现**，绝不静默。

TOTAL = len(ENTRIES)
SHORTCUT_MAX = 9          # 1–9 兼作数字快捷键（32 个工具本来也不可能都挂单键）


def is_shortcut(number) -> bool:
    """这个编号是不是**同时**兼作数字快捷键。"""
    try:
        return 1 <= int(number) <= SHORTCUT_MAX
    except (TypeError, ValueError):
        return False


def entry_of(kind: str) -> dict:
    kind = str(kind or "")
    for entry in ENTRIES:
        if entry["kind"] == kind:
            return dict(entry)
    return {}


def entry(number) -> dict:
    try:
        number = int(number)
    except (TypeError, ValueError):
        return {}
    for item in ENTRIES:
        if item["num"] == number:
            return dict(item)
    return {}


def is_implemented(kind: str) -> bool:
    found = entry_of(kind)
    return bool(found.get("implemented"))


def implemented_entries() -> list:
    return [dict(item) for item in ENTRIES if item["implemented"]]


def grouped() -> list:
    """`[(分类键, 分类名, 色相, [条目, ...]), ...]` —— 按 `CATEGORIES` 顺序，空类不返回。"""
    blocks = []
    for key, name, color in CATEGORIES:
        items = [dict(item) for item in ENTRIES if item["category"] == key]
        if items:
            blocks.append((key, name, color, items))
    return blocks


def placeholder_hint(kind: str) -> str:
    """未实现类型的提示语（**点了必须有话说**，不能静默）。"""
    found = entry_of(kind)
    if not found or found.get("implemented"):
        return ""
    return (f"「{found['name']}」还没实现 —— 已在目录里登记（编号 {found['num']}），\n"
            f"这样你知道它会在哪一类里出现；现在还不能画。")
