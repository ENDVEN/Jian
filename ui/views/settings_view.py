# ui/views/settings_view.py
"""⚙ 设置页（★v6.73 / §7-B13 · 主案 **S2「系统设置双栏」** · 本文件 = 路径表 **S2-0** 的壳）。

【S2 的形】左侧 = **条目列表**（一张大圆角卡片，一屏只看一组）；右侧 = **详情滚动区**（一组一张卡）。
【唯一纪律】**本页只渲染 `ui/settings_registry.py`** ——
  · 不手写任何设置项（加设置 = 注册表加一行，护栏见 `smoke_pages_overlay`）；
  · 不自己读写偏好（一律经 `settings_registry.get_value/set_value`）⇒ 落点唯一（§9-D）。
【空分组不放假控件】还没接进来的分组只显示 `todo`（"哪一步接进来"），避免"看得到却没用"。
【后续步骤的落点】S2-1 账号与数据源（登录/额度/自检）· S2-2 下载与取数（收编旧对话框）
  · S2-3 外观（需先令牌化颜色）· S2-4 默认值 · S2-5 存储维护 · S2-6 交互只读 · S2-7 关于。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from ui import settings_registry as reg
from ui.widgets.settings_render import build_control

# S2 观感（★S2-3 会把颜色收进令牌；v1 先就地声明，别处不许抄）
_LIST_QSS = (
    "QFrame#SettingsList { background:#FFFFFF; border:1px solid #E6EAF0;"
    " border-radius:14px; }"
    "QPushButton[class='SettingsItem'] { text-align:left; padding:9px 11px; border:0;"
    " background:transparent; border-radius:10px; color:#616B7A; }"
    "QPushButton[class='SettingsItem']:hover { background:#F7F9FC; color:#20242C; }"
    "QPushButton[class='SettingsItem']:checked { background:#1976D2; color:#FFFFFF;"
    " font-weight:600; }")
_CARD_QSS = ("QFrame#SettingsCard { background:#FFFFFF; border:1px solid #E6EAF0;"
             " border-radius:14px; }")
_TITLE_QSS = "font-size:14.5px; font-weight:bold; color:#20242C;"
_LEAD_QSS = "font-size:12.5px; color:#616B7A;"
_TODO_QSS = ("font-size:12.5px; color:#8A94A6; background:#FBFCFE;"
             " border:1px dashed #E6EAF0; border-radius:10px; padding:10px 12px;")
_NAME_QSS = "font-weight:600; color:#20242C;"
_DESC_QSS = "font-size:12.5px; color:#616B7A;"
_SEP_QSS = "background:#F2F5F9;"
_STATUS_QSS = "font-size:12px; color:#5B6472; padding:2px 2px 0 2px;"

logger = logging.getLogger(__name__)


def open_group(parent, gid: str = 'download') -> bool:
    """★v6.74 / **S2-2**：**跳到设置页的某个分组** —— 旧「⚙ 下载设置」等入口的**唯一去向**。

    【为什么要这个函数】S2 定案要求"**不新开第二套编辑面**"（§9-D 防两套值漂移）：旧入口都保留，
      但一律**跳到设置页**（同一个编辑面）。找不到主窗口时**明确告诉用户去哪**（不静默）。
    返回是否真的跳成功（False 时已弹提示）。
    """
    win = parent.window() if parent is not None else None
    page = getattr(win, 'page_settings', None)
    switch = getattr(win, 'switch_to', None)
    if page is None or not callable(switch):
        if isinstance(parent, QWidget):       # 有父件 ⇒ 明确告诉用户去哪（不静默）
            QMessageBox.information(parent, '设置在哪',
                                    '请在主界面**左栏最下方**打开「⚙ 设置」，'
                                    '参数在「下载与取数」一组里（一处调、处处生效）。')
        else:                                 # 无父件（测试 / 异常路径）⇒ 只记日志，绝不弹窗
            logger.info('未找到设置页（无主窗口）—— 请在左栏「⚙ 设置 → 下载与取数」里调整')
        return False
    switch('settings')                      # 切到设置页
    page.show_group(gid)                    # 并定位到目标分组
    return True


class SettingsView(QWidget):
    """S2 双栏设置页（**只渲染注册表**）。"""

    LIST_WIDTH = 214

    def __init__(self, parent=None):
        super().__init__(parent)
        self._btns: dict = {}
        self._pages: dict = {}
        self._rows: dict = {}          # gid -> [row, ...]（断言 / reload 用）
        self._status: QLabel = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # ---- 左：条目列表（S2 的"一屏只看一组"）----
        left = QFrame()
        left.setObjectName('SettingsList')
        left.setFixedWidth(self.LIST_WIDTH)
        left.setStyleSheet(_LIST_QSS)
        lay_left = QVBoxLayout(left)
        lay_left.setContentsMargins(10, 10, 10, 10)
        lay_left.setSpacing(2)
        for g in reg.groups():
            btn = QPushButton(f"{g.icon} {g.title}".strip())
            btn.setProperty('class', 'SettingsItem')
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(g.lead or g.title)
            btn.clicked.connect(lambda _=False, gid=g.gid: self.show_group(gid))
            lay_left.addWidget(btn)
            self._btns[g.gid] = btn
        lay_left.addStretch()
        root.addWidget(left)

        # ---- 右：详情（一组一页）----
        right = QWidget()
        lay_right = QVBoxLayout(right)
        lay_right.setContentsMargins(0, 0, 0, 0)
        lay_right.setSpacing(8)
        self._stack = QStackedWidget()
        for g in reg.groups():
            page = self._build_group_page(g)
            self._pages[g.gid] = page
            self._stack.addWidget(page)
        lay_right.addWidget(self._stack, 1)
        self._status = QLabel('')
        self._status.setStyleSheet(_STATUS_QSS)
        self._status.setWordWrap(True)
        lay_right.addWidget(self._status)
        root.addWidget(right, 1)

        self.show_group(reg.groups()[0].gid)

    # ==========================================
    # 渲染（**唯一入口**：分组页 → 行 → 控件）
    # ==========================================
    def _build_group_page(self, g: reg.Group) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        card = QFrame()
        card.setObjectName('SettingsCard')
        card.setStyleSheet(_CARD_QSS)
        body = QVBoxLayout(card)
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(10)

        title = QLabel(f"{g.icon} {g.title}".strip())
        title.setStyleSheet(_TITLE_QSS)
        body.addWidget(title)
        if g.lead:
            lead = QLabel(g.lead)
            lead.setStyleSheet(_LEAD_QSS)
            lead.setWordWrap(True)
            body.addWidget(lead)

        rows = []
        for item in reg.items(g.gid):
            if rows:                                    # 行间细分隔线（S2 的"卡片内列表"）
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(_SEP_QSS)
                body.addWidget(sep)
            row = self._build_row(item)
            body.addWidget(row)
            rows.append(row)
        self._rows[g.gid] = rows

        if not rows and g.todo:                          # 空分组：**说明哪一步接进来**，不放假控件
            note = QLabel(f"⏳ {g.todo}")
            note.setStyleSheet(_TODO_QSS)
            note.setWordWrap(True)
            body.addWidget(note)

        outer.addWidget(card)
        outer.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _build_row(self, item: reg.Item) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        name = QLabel(item.label)
        name.setStyleSheet(_NAME_QSS)
        name.setFixedWidth(150)
        lay.addWidget(name)

        desc = QLabel(item.tip or '')
        desc.setStyleSheet(_DESC_QSS)
        desc.setWordWrap(True)
        if item.help or item.where:
            desc.setToolTip((item.help or item.tip or '')
                            + f"\n落点：{reg.describe_where(item)}")
        lay.addWidget(desc, 1)

        control = build_control(item, self._on_change)
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignRight)
        return row

    # ==========================================
    # 交互
    # ==========================================
    def _on_change(self, item: reg.Item, value) -> None:
        """控件变了 ⇒ 只做一件事：交给注册表写（生效钩子也在注册表里）。

        ★v6.73 S2-1：`value is None` = **动作项被点**（登录… / 退出登录 / 网络自检）——
          去执行它，然后整页刷新（状态项本就是现算的，刷新即最新），并把动作返回的人话当回执。
        """
        if value is None and item.kind == reg.KIND_ACTION:
            self._run_action(item)
            return
        ok = reg.set_value(item, value)
        if not ok:
            self._say(f"⚠ {item.label} 保存失败（见日志）")
            return
        extra = '（重启后生效）' if item.restart else '（立即生效）'
        self._say(f"已保存：{item.label} = {reg.value_text(item)} {extra}"
                  f" · 落点 {reg.describe_where(item)}")

    _worker_action = None

    def _run_action(self, item: reg.Item) -> None:
        """执行动作项：**动作自己做、自己返回一句人话**；页面只管刷新与显示。

        ★v6.74 S2-1b：声明了 `worker`（异步动作）⇒ 交后台线程跑（自检这类要几秒的活，
        **绝不阻塞界面**），回来再刷新与回执。
        """
        if callable(getattr(item, 'worker', None)):
            self._run_worker_action(item)
            return
        try:
            result = item.action() if callable(item.action) else None
        except Exception as e:                                # noqa: BLE001 —— 动作炸了不该带走页面
            logger.warning(f"设置动作失败({item.key}): {type(e).__name__}: {e}")
            self._say(f"⚠ {item.label} 执行失败：{type(e).__name__}: {e}")
            return
        self.reload()                                          # 档位/登录/额度等状态项随之刷新
        self._say(str(result) if result else f"已执行：{item.label}")

    def _run_worker_action(self, item: reg.Item) -> None:
        """★v6.74 S2-1b：**异步动作**（自检 / 清理）—— 起线程，回来再刷新 + 回执。"""
        self._say(f"{item.label}：后台执行中…（界面可继续操作）")
        try:
            thread = item.worker(self)
        except Exception as e:                                # noqa: BLE001 —— 起不来要说清楚
            logger.warning(f"设置异步动作创建失败({item.key}): {type(e).__name__}: {e}")
            self._say(f"⚠ {item.label} 启动失败：{type(e).__name__}: {e}")
            return
        self._worker_action = thread          # ⚠ 握引用：否则运行中的 QThread 被 GC = 崩
        thread.finished.connect(lambda text, i=item: self._on_worker_action_done(i, text))
        thread.start()

    def _on_worker_action_done(self, item: reg.Item, text) -> None:
        self.reload()                                          # 状态项（档位/额度/退避）随之刷新
        self._say(str(text) if text else f"已执行：{item.label}")

    def _say(self, text: str) -> None:
        self._status.setText(text or '')
        if text and '\n' in text:                 # ★v6.74：多行报告（自检）⇒ tooltip 看/复制全文
            self._status.setToolTip(text)

    def show_group(self, gid: str) -> None:
        """切到某分组（左侧按钮状态同步 —— 程序化调用时也要高亮正确）。"""
        page = self._pages.get(gid)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        btn = self._btns.get(gid)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        g = reg.group_of(gid)
        if g is not None:
            self._say(g.lead or g.title)

    def reload(self) -> None:
        """按**当前**注册表重建全部页面（S2-0 的护栏："加一行注册项 ⇒ 页面自动出现"）。

        ⚠ 只重建右侧（左侧分组是骨架，不该随手加）；重建后回到当前分组。
        """
        cur = self.current_group()
        while self._stack.count():
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._rows.clear()
        self._pages.clear()
        for g in reg.groups():
            page = self._build_group_page(g)
            self._pages[g.gid] = page
            self._stack.addWidget(page)
        self.show_group(cur or reg.groups()[0].gid)

    # ==========================================
    # 只读查询（断言 / 后续步骤用）
    # ==========================================
    def current_group(self) -> str:
        for gid, page in self._pages.items():
            if page is self._stack.currentWidget():
                return gid
        return ''

    def count_rows(self, gid: str) -> int:
        """该分组渲染出的**设置行数**（= 注册表项数；断言"加一行即多一行"就用它）。"""
        return len(self._rows.get(gid) or [])
