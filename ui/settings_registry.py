# ui/settings_registry.py
"""设置项的**唯一真源**（★v6.73 / §7-B13 · S2 路径表 **S2-0**）。

【为什么要有它】设置页的使命是"后续把**系统项 / 登录 / 个性化**全塞进来"。若每项都在页面里
  手写控件、各自读写偏好 ⇒ 两个必然恶果：① **加一项就要改页面**；② 极易出现"两处可改同一个值"
  （§9-D 漂移，本项目已经踩过：下载间隔曾散在三个入口各自一套）。
  ⇒ 本模块只做一件事：**用声明描述每一项**，页面**只渲染它**。**加设置 = 加一行**。
  护栏：`smoke_pages_overlay` 有"注册表加一行 ⇒ 页面自动多一行"的断言。

【落点口径（§9-D）】每项必须声明 `where`（`偏好键.子键` / `readonly:<原因>`）——
  读、写、恢复默认**一律经本模块**的 `get_value / set_value / reset_value`
  ⇒ **同一项只可能有一处写入点**。

【v1（S2-0）先接"真项"】下载节流 5 项（`download_prefs`）+ 网络 2 项（`net`）—— 都是**已在用**的
  偏好 ⇒ "改完即时生效"这句话现在就成立（网络两项写完会真的重新 `net_env.apply()`）。
  其余分组先只出标题 + `todo`（**不放假控件**，页面显示"后续步骤"）。
【扩展接口（给后续 S2-x 用）】加一个新类型 = 在 `settings_render` 加一个工厂；
  加一个新设置 = 往 `ITEMS` 加一条 `Item(...)`；需要"改完顺手做点什么" ⇒ 在 `_AFTER_SET` 里登记。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.preferences import preferences

logger = logging.getLogger(__name__)

# 控件类型（渲染层一一对应一个工厂，见 `ui/widgets/settings_render.py`）
KIND_TOGGLE = 'toggle'        # 开关
KIND_NUMBER = 'number'        # 数值（int/float 由 decimals 决定）
KIND_ENUM = 'enum'            # 枚举（下拉）
KIND_READONLY = 'readonly'    # 只读展示（状态 / 版本 / 交互一览）
# ↓ 预留（S2-1/S2-5 用；渲染层已留工厂位）
KIND_TEXT = 'text'
KIND_PATH = 'path'
KIND_ACTION = 'action'

# 作用域（S4"表格视图"与 tooltip 都用它）
SCOPE_GLOBAL = 'global'       # 一处调、处处生效
SCOPE_PAGE = 'page'           # 只影响某一页
SCOPE_TASK = 'task'           # 每次任务自己选（不进设置页，除只读展示）


@dataclass(frozen=True)
class Group:
    """一个分组 = S2 左侧列表的一行 = 右侧详情的一页。"""
    gid: str
    title: str
    lead: str = ''
    icon: str = ''
    todo: str = ''            # 还没接的分组：写清"哪一步接进来"（不放假控件）


@dataclass
class Item:
    """一个设置项 = 详情页里的一行。**除了这里，别处不许描述设置项。**"""
    key: str                                  # 唯一键（也用于断言定位）
    group: str                                # 所属分组 gid
    label: str                                # 界面标题
    kind: str = KIND_READONLY
    default: object = None                    # 默认值（"恢复默认"的判据）
    where: str = ''                           # 落点：`偏好键.子键` 或 `readonly:<原因>`
    tip: str = ''                             # 一行说明（详情行右侧）
    help: str = ''                            # 长帮助（tooltip，可多行）
    choices: tuple = ()                       # enum：((值, 显示名), ...)
    lo: float = 0.0
    hi: float = 1e9
    step: float = 1.0
    decimals: int = 0                         # 0 ⇒ 整数
    restart: bool = False                     # 改完需重启？（界面要说清）
    unit: str = ''                            # 数值单位（"秒" / "次" / "路" / "页"）
    readonly: bool = False                    # 只读（状态展示用）
    # ★v6.73 S2-1：**动态只读**（状态类：当前档位 / 登录状态 / 今日额度）—— 每次渲染**现算**
    value_fn: object = None                   # 可调用 ⇒ 当前值（`None` 则用 default）
    # ★v6.73 S2-1：**动作项**（登录… / 退出登录 / 网络自检）—— 按钮点它，**返回值当回执**
    action: object = None                     # 可调用 ⇒ 执行后返回一句人话（可为 None）
    # ★v6.74 S2-1b：**异步动作**（自检 / 清理这类要几百毫秒~几秒的活）——
    #   可调用(`parent`) ⇒ 返回带 `finished(str)` 信号的 QThread；页面自己去起/收（绝不阻塞界面）
    worker: object = None


# ==========================================
# 分组（S2 左侧列表 · 顺序即显示顺序）
# ==========================================
GROUPS = (
    Group('account', '账号与数据源', '登录档位 · 每日额度 · 地址族 · 代理策略', '🔑',
          todo='S2-1 接入：东财登录/退出（`data/em_auth` 已就绪）· 今日额度 · 地址族 · 代理策略 · 网络自检'),
    Group('download', '下载与取数', '全局节流参数 —— 一处调、处处生效', '⬇'),
    Group('appearance', '外观与个性化', '主题 · 强调色 · 涨跌配色 · 字体 · 密度', '🎨',
          todo='S2-3 接入：需先把全站硬编码颜色**令牌化**（`ui/theme.py`），分壳/卡片/表格 → 图表两批'),
    Group('defaults', '回测与扫描默认', '新任务的默认值（可被页面临时覆盖）', '📐',
          todo='S2-4 接入：默认区间 · 自动存档 · 首次扫描提示'),
    Group('storage', '存储与维护', '数据目录 · 缓存 · 日志 · 配置备份', '🗄',
          todo='S2-5 接入：数据目录（打开/迁移）· 缓存清理 · 日志级别 · 配置导出导入（不含凭据）'),
    Group('keys', '快捷键与交互', '现有交互一览（v1 只读，不做假开关）', '⌨',
          todo='S2-6 接入：先只读列出现有键位（双击跳转 / 滚轮缩放 / 拖拽换序…），预留 `keybinding` 类型'),
    Group('about', '关于与更新', '版本 · 检查更新 · 反馈', 'ℹ',
          todo='S2-7 接入：版本号 · 检查更新（复用 `core/updater`）· 反馈入口'),
)

# ==========================================
# 动态状态 / 动作的**取数函数**（★v6.73 S2-1）
#   ⚠ 一律**惰性 import**（函数体内）：注册表是"声明层"，不该在导入期就把 data 层全拉起来
#     （否则任何 import 注册表的地方都连带拉起 pandas / requests）。
# ==========================================
def _tier_text() -> str:
    from data import em_market
    return em_market.tier_text()


def _login_text() -> str:
    from data import em_auth
    st = em_auth.status()
    if not st.get('logged_in'):
        return (f"未登录（本机有 {st.get('count')} 条但不齐，缺登录三元组）"
                if st.get('present') else '未登录')
    return (f"已登录 · {st.get('count')} 条凭据 · "
            f"{'已加密' if st.get('encrypted') else '⚠ 明文（DPAPI 不可用）'}"
            + (f" · 存于 {st.get('saved_at')}" if st.get('saved_at') else ''))


def _budget_text() -> str:
    from data import em_auth, em_market
    return em_auth.budget_text(em_market.current_tier())


def _open_login_dialog():
    """打开"粘贴凭据"对话框（唯一登录入口；**不做账号密码登录**）。"""
    from ui.dialogs.em_login import open_login_dialog
    return open_login_dialog()


def _do_logout():
    from data import em_auth, em_market
    em_auth.clear()
    return f"已退出登录 —— 现在走 {em_market.tier_text()}"


def _self_check_worker(parent=None):
    """★v6.74 S2-1b：异步动作的**线程工厂**（页面只负责"起 + 收结果"，见 `settings_view`）。"""
    from ui.workers import NetSelfCheckWorker
    return NetSelfCheckWorker(parent=parent)


# ==========================================
# 设置项（v1：先接已在用的真项 ⇒ 改了立刻生效）
# ==========================================
_ITEMS_V1 = (
    Item('download.interval', 'download', '请求间隔', KIND_NUMBER, default=0.5,
         where='download_prefs.interval', lo=0.0, hi=10.0, step=0.1, decimals=1, unit='秒',
         tip='每次请求前的等待时间（并发时是全局发起节奏）。越慢越安全，建议不低于 0.4 秒。',
         help='对所有批量下载生效（数据管理 / 预下载 / M2 / M3）—— 唯一真源，改完立即对下一个任务生效。'),
    Item('download.jitter', 'download', '随机抖动', KIND_TOGGLE, default=True,
         where='download_prefs.jitter',
         tip='让间隔随机浮动 ±30%，打散"机器人固定频率"特征。',
         help='这是**好人设计**的一部分：固定频率是最容易被反爬系统识别的特征之一。'),
    Item('download.circuit_breaker', 'download', '连续失败熔断', KIND_NUMBER, default=12,
         where='download_prefs.circuit_breaker', lo=1, hi=999, step=1, unit='次',
         tip='连续失败达到该数即停手，避免把额度/账号往死里打。'),
    Item('download.concurrency', 'download', '并发', KIND_NUMBER, default=2,
         where='download_prefs.concurrency', lo=1, hi=4, step=1, unit='路',
         tip='K≤4：只靠网络往返重叠提速，**聚合请求率不变**。',
         help='上限 4 是刻意留的（"宁可慢也不封 IP"）；调大不会让你更快被限流放过。'),
    Item('download.skip_fresh', 'download', '跳过已最新', KIND_TOGGLE, default=True,
         where='download_prefs.skip_fresh',
         tip='本地已是最新的标的直接跳过（断点续传的基础）。'),
    # ---- ★v6.74：扫描后**补全调度器**（行业/估值：扫描先出结果，这两列后台慢慢补）----
    Item('enrich.enabled', 'download', '扫描后补全行业/估值', KIND_TOGGLE, default=True,
         where='enrich.enabled',
         tip='扫描**先出命中结果**，行业与估值在后台按轮补齐并刷新到表里（不拖慢扫描）。',
         help='为什么要后台补：这两列要向东财发请求，且**一次请求覆盖 100 只** ⇒\n'
              '沪深300 只需 3 个请求、全 A 约 56 个（不是"每只 1 个"）。\n'
              '关掉它 = 只剩扫描本身，两列会一直显示 \'—\'。'),
    Item('enrich.requests', 'download', '补全：每轮请求数', KIND_NUMBER, default=3,
         where='enrich.requests', lo=1, hi=10, step=1, unit='个',
         tip='每轮最多发几个请求（1 个 = 100 只）。越小越温柔，但补齐越慢。',
         help='轮内还受"全局最小间隔 ≥0.8 秒"约束 ⇒ 3 个请求 ≈ 2.4 秒发完。'),
    Item('enrich.gap', 'download', '补全：轮间间隔', KIND_NUMBER, default=30,
         where='enrich.gap', lo=5, hi=600, step=5, unit='秒',
         tip='两轮之间等多久（长休是"别把额度打进风控"的关键）。'),
    Item('em.legacy_paging', 'account', '全市场分页预热（旧通道）', KIND_TOGGLE, default=False,
         where='em.legacy_paging',
         tip='默认关闭：行业已改由「扫描后按池补全」（更快更准）。补全不可用时才会自动兜底走它。',
         help='旧通道 = 东财全市场列表 `clist` 分页（单页 100 行、全市场约 56 页），按**代码升序**补齐\n'
              '⇒ 沪深300/中证500 这类池子里的沪市票"永远轮不到"（用户实测命中 <30/300）。\n'
              '新通道 = `ulist` 按标的取（与估值同一次请求）⇒ 沪深300 = 3 个请求。'),
    Item('net.force_ipv4', 'account', '地址族限定 IPv4', KIND_TOGGLE, default=True,
         where='net.force_ipv4', restart=False,
         tip='国内行情源实测 IPv4 更稳（IPv6 端点不通）；关掉即回落系统默认。',
         help='实测（2026-09-26）：同一刻 IPv4 直连 200 · 0.18 秒，而 IPv6 连接即被断。\n'
              '关掉本项 = 恢复让系统自己选地址族（一般不推荐）。'),
    Item('net.proxy_mode', 'account', '代理策略', KIND_ENUM, default='auto',
         where='net.proxy_mode',
         choices=(('auto', '自动（代理报错时降级直连）'), ('direct', '直连（不用代理）'),
                  ('proxy', '只用系统代理（不降级）')),
         tip='必须走代理的网络选"只用系统代理"；默认"自动"只在代理报错时才降级一次。'),
    # ---- ★v6.73 S2-1：东财登录（凭据只落本机、加密保存；**日志/界面永不回显值**）----
    Item('em.tier', 'account', '当前档位', KIND_READONLY, default='—',
         where='readonly:data/em_market.current_tier（登录档 = 常速 / 匿名档 = 慢速分批）',
         readonly=True, value_fn=_tier_text,
         tip='登录后页间隔更短、每批补更多页；不登录也照常能用，只是更慢。',
         help='判据（2026-09-26 同一刻对照实测）：带 Cookie 200 + 真实数据，匿名同刻被 RST\n'
              '⇒ 门槛是「登录态」，不是无差别封 IP。登录档也**绝不做全市场高频轮询**。'),
    Item('em.login_state', 'account', '登录状态', KIND_READONLY, default='—',
         where='readonly:data/em_auth.status（只报条数与名字，**绝不回显凭据值**）',
         readonly=True, value_fn=_login_text,
         tip='凭据只存本机（首选用 Windows DPAPI 加密）；随时可"退出登录"清除。'),
    Item('em.budget', 'account', '今日取数额度', KIND_READONLY, default='—',
         where='readonly:data/em_auth.budget_text（防「狂点把账号打进风控」）',
         readonly=True, value_fn=_budget_text,
         tip='额度用完会「停在缓存档」（已抓到的数据照常读），第二天自动恢复。'),
    Item('em.login', 'account', '登录东财', KIND_ACTION, default='登录 / 粘贴凭据…',
         where='action:data/em_auth.parse_pasted + save（原子写 ~/.jian_data/em_cookie.json）',
         action=_open_login_dialog,
         tip='粘贴浏览器里的东财 Cookie（**不用账号密码**，软件不存密码）。',
         help='为什么要登录：东财对**匿名高频**请求有频次窗（会整段拒绝）——\n'
              '登录后取数明显更稳（实测匿名被拒时登录仍 200）。\n'
              '怎么拿：浏览器登录东财 → F12 → Network → 任一请求的 Cookie，整段复制粘贴即可。'),
    Item('em.logout', 'account', '退出登录', KIND_ACTION, default='退出登录',
         where='action:data/em_auth.clear（删本机凭据 + 回到匿名慢速档）',
         action=_do_logout,
         tip='清除本机保存的凭据（不影响你浏览器里的登录状态）。'),
    Item('em.selfcheck', 'account', '网络自检', KIND_ACTION, default='开始自检',
         where='action:data/em_market.self_check（策略 / 代理 / DNS / 登录 / 额度 / 退避 + 1 个探测）',
         worker=_self_check_worker,
         tip='一次看清「现在为什么取不到数」：网络策略 · 代理 · DNS · 登录 · 档位额度 · 退避 + 连通性。',
         help='**只发 1 个请求**（问 1 只票）—— 自检不刷量（避免被反爬盯上），其余全是读本机状态。\n'
              '报告同时写进日志（~/.jian_data/logs/app.log），便于事后复盘。\n'
              '多行报告看状态行；鼠标悬停在状态行上可看全文并复制。'),
)

ITEMS = list(_ITEMS_V1)

# 【改完顺手要做的事】登记在这里 ⇒ 页面只管写值，"生效"由真源负责（页面不写业务）
_AFTER_SET = {
    'net.force_ipv4': lambda _v: _apply_net(),
    'net.proxy_mode': lambda _v: _apply_net(),
}


def _apply_net() -> None:
    """网络类设置改完立即生效（唯一出口在 `data/net_env.py`）。"""
    try:
        from data import net_env
        net_env.apply()
    except Exception as e:                                    # noqa: BLE001 —— 生效失败不该阻断保存
        logger.warning(f"网络策略应用失败（已保存，重启后生效）: {type(e).__name__}: {e}")


# ==========================================
# 查询
# ==========================================
def groups() -> tuple:
    return GROUPS


def items(group: str = None) -> list:
    """按分组取项（`None` ⇒ 全部）。**保持声明顺序**。"""
    if group is None:
        return list(ITEMS)
    return [i for i in ITEMS if i.group == group]


def find(key: str):
    for i in ITEMS:
        if i.key == key:
            return i
    return None


def group_of(gid: str):
    for g in GROUPS:
        if g.gid == gid:
            return g
    return None


def _split_where(where: str) -> tuple:
    if '.' in where:
        k, sub = where.split('.', 1)
        return k, sub
    return where, None


def is_passive(item: Item) -> bool:
    """**不可写**的项：只读展示 / 动作按钮（它们没有"偏好落点"，别当设置去写）。"""
    return (bool(item.readonly) or item.kind == KIND_ACTION
            or str(item.where).startswith(('readonly', 'action')))


def describe_where(item: Item) -> str:
    """落点的人话（S4 表格视图的"来源"列 / tooltip 用）—— 便于排障时知道它落在哪。"""
    where = str(item.where)
    if item.kind == KIND_ACTION or where.startswith(('action', 'readonly')):
        return where.split(':', 1)[-1] or '只读'
    return f"preferences[{where}]"


# ==========================================
# 读写（唯一写入点：别处在页面上直接改偏好）
# ==========================================
def get_value(item: Item):
    """当前值（类型与声明一致；坏值回落默认）。

    ★v6.73 S2-1：动态状态项（`value_fn`）⇒ **现算**（当前档位 / 登录状态 / 今日额度）；
      算不动就回落 `default` —— 界面宁可显示占位，也不许因一个探针坏掉而崩页。
    """
    if is_passive(item):
        if callable(item.value_fn):
            try:
                return item.value_fn()
            except Exception as e:                        # noqa: BLE001
                logger.warning(f"动态设置值计算失败({item.key}): {type(e).__name__}: {e}")
                return item.default
        return item.default
    key, sub = _split_where(item.where)
    try:
        raw = preferences.get(key)
    except Exception:                                        # noqa: BLE001
        return item.default
    if sub is None:
        val = raw if raw is not None else item.default
    else:
        val = (raw or {}).get(sub, item.default) if isinstance(raw, dict) else item.default
    return _coerce(item, val)


def _coerce(item: Item, value):
    try:
        if item.kind == KIND_TOGGLE:
            return bool(value)
        if item.kind == KIND_NUMBER:
            return float(value) if item.decimals else int(value)
    except (TypeError, ValueError):
        return item.default
    return value


def set_value(item: Item, value) -> bool:
    """写一项（**唯一写入点**）⇒ 落偏好并触发登记过的"即时生效"钩子。"""
    if is_passive(item):
        logger.warning(f"设置项 {item.key} 是只读的，忽略写入")
        return False
    key, sub = _split_where(item.where)
    new = _coerce(item, value)
    try:
        if sub is None:
            preferences.set(key, new)
        else:
            cur = preferences.get(key)
            data = dict(cur) if isinstance(cur, dict) else {}
            data[sub] = new
            preferences.set(key, data)
    except Exception as e:                                    # noqa: BLE001
        logger.warning(f"设置写入失败({item.key}): {type(e).__name__}: {e}")
        return False
    hook = _AFTER_SET.get(item.key)
    if hook is not None:
        hook(new)
    return True


def reset_value(item: Item) -> bool:
    """恢复默认（= 把该项写回声明里的 `default`）。"""
    return set_value(item, item.default)


def value_text(item: Item) -> str:
    """当前值的**人话**（只读项/状态行用）。"""
    val = get_value(item)
    if item.kind == KIND_TOGGLE:
        return '开' if val else '关'
    if item.kind == KIND_ENUM:
        for v, label in item.choices:
            if v == val:
                return str(label)
        return str(val)
    if item.kind == KIND_NUMBER:
        num = f"{float(val):.{item.decimals}f}" if item.decimals else f"{int(val)}"
        return f"{num} {item.unit}".strip()
    return str(val)
