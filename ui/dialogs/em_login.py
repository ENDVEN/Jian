# ui/dialogs/em_login.py
"""东财登录（**粘贴凭据**）对话框（★v6.73 / §7-B13 · S2-1）—— **唯一的登录入口**。

【形态为什么是"粘贴"】不存账号密码、不做自动登录（理由见 `data/em_auth.py` 文件头：
  浏览器 cookie 库自 v80 起是 AES-GCM + DPAPI 双层加密，手写解不开；软件内嵌官方登录页要
  PyQt6-WebEngine）。⇒ 用户从浏览器复制 Cookie 整段粘贴，**零新依赖**、零密码留存。
【安全（用户拍板口径）】① 凭据只落本机（优先 DPAPI 加密）；② 界面/日志/回执**永不回显凭据值**
  （只报**条数与名字**）；③ 粘完**立刻清空输入框**（别让凭据长时间摆在屏幕上）；④ 随时可退出登录；
  ⑤ 绝不伪装官方客户端、不做多账号轮换（§10 口径）。
【纪律】本件只做交互：存储 / 判据 / 解析全在 `data/em_auth.py`（§9-H —— ui 不直连存储）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                             QPushButton, QVBoxLayout)

from data import em_auth, em_market
from ui.widgets.custom_widgets import FLAT_QSS, OUTLINE_QSS

_TITLE_QSS = "font-size:14.5px; font-weight:bold; color:#20242C;"
_DESC_QSS = "font-size:12.5px; color:#616B7A;"
_STATUS_QSS = "font-size:12.5px; color:#5B6472; background:#FBFCFE;" \
              " border:1px solid #E6EAF0; border-radius:9px; padding:8px 10px;"
_WARN_QSS = "font-size:12px; color:#8A94A6;"

_HELP = ('为什么要登录：东财对**匿名高频**请求有频次窗（连打几十次会整段拒绝、约 30 分钟自恢复）'
         '—— 登录后取数明显更稳（实测：匿名被拒的同一刻，带 Cookie 的请求仍是 HTTP 200）。\n'
         '怎么拿凭据：浏览器里登录东财 → F12 → Network → 点任一请求 → 复制请求头里的 Cookie 整段；\n'
         '本软件**不要账号密码**，只收这段 Cookie；凭据仅存本机（加密），随时可"退出登录"清除。')


class EmLoginDialog(QDialog):
    """粘贴凭据 ⇒ 解析 ⇒ 保存 ⇒ 立刻告诉用户"现在走哪个档"。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('登录东财（粘贴凭据）')
        self.setMinimumWidth(600)
        self._result_text = ''

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel('🔑 登录东财（提升取数稳定性）')
        title.setStyleSheet(_TITLE_QSS)
        root.addWidget(title)

        desc = QLabel(_HELP)
        desc.setStyleSheet(_DESC_QSS)
        desc.setWordWrap(True)
        root.addWidget(desc)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            '把浏览器里东财的 Cookie 整段粘贴到这里（两种形态都认）：\n'
            '  ① 扩展导出的 JSON 数组：[{"name":"ut","value":"…"}, …]\n'
            '  ② Cookie 头字符串：ut=…; ct=…; pi=…; qgqp_b_id=…')
        self.editor.setFixedHeight(120)
        root.addWidget(self.editor)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_parse = QPushButton('解析并登录')
        self.btn_parse.setStyleSheet(FLAT_QSS)
        self.btn_parse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_parse.clicked.connect(self._on_parse)
        self.btn_logout = QPushButton('退出登录')
        self.btn_logout.setStyleSheet(OUTLINE_QSS)
        self.btn_logout.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_logout.clicked.connect(self._on_logout)
        self.btn_close = QPushButton('关闭')
        self.btn_close.setStyleSheet(OUTLINE_QSS)
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_parse)
        row.addWidget(self.btn_logout)
        row.addStretch()
        row.addWidget(self.btn_close)
        root.addLayout(row)

        self.lbl_status = QLabel('')
        self.lbl_status.setStyleSheet(_STATUS_QSS)
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        warn = QLabel('凭据只存本机（首选用 Windows DPAPI 加密）；界面与日志**只显示条数和名字**，'
                      '永不回显凭据值。')
        warn.setStyleSheet(_WARN_QSS)
        warn.setWordWrap(True)
        root.addWidget(warn)

        self._refresh_status()

    # ==========================================
    # 交互
    # ==========================================
    def _refresh_status(self) -> None:
        st = em_auth.status()
        if st.get('logged_in'):
            head = (f"当前：**已登录** · {st.get('count')} 条 · "
                    f"{'已加密' if st.get('encrypted') else '⚠ 明文（DPAPI 不可用）'}")
        elif st.get('present'):
            head = f"当前：**未登录**（本机有 {st.get('count')} 条但缺登录三元组）"
        else:
            head = '当前：**未登录**（走匿名慢速档）'
        names = '、'.join(st.get('names') or []) or '无'
        self.lbl_status.setText(
            f"{head}\n档位：{em_market.tier_text()} · {em_auth.budget_text(em_market.current_tier())}\n"
            f"本机已有条目（只显示名字）：{names}")

    def _on_parse(self) -> None:
        jar = em_auth.parse_pasted(self.editor.toPlainText())
        if not jar:
            self.lbl_status.setText(
                '⚠ 没解析到有效条目 —— 支持两种形态：① 扩展导出的 JSON 数组；'
                '② `ut=…; ct=…; pi=…` 这样的 Cookie 头整段。')
            return
        if not em_auth.save(jar):
            self.lbl_status.setText('⚠ 保存失败（详情见日志）；本机凭据未被改动。')
            return
        self.editor.clear()                     # ⚠ 粘完立刻清空：别让凭据长时间留在屏幕上
        if em_auth.is_logged_in():
            self._result_text = (f"已登录东财 —— 现在走 {em_market.tier_text()}"
                                 f"（{em_auth.budget_text('auth')}）")
            self.lbl_status.setText(f"✅ {self._result_text} · 本次粘贴 {len(jar)} 条")
        else:
            have = em_auth.load()
            miss = [n for n in em_auth.KEY_COOKIES if not have.get(n)]   # ⚠ 只报**名字**，不报值
            self._result_text = (f"已保存 {len(jar)} 条，但缺登录三元组（{'/'.join(miss)}）"
                                 f"⇒ 仍走匿名慢速档")
            self.lbl_status.setText(f"⚠ {self._result_text}\n"
                                    f"（请确认复制的是**已登录状态**下东财的 Cookie）")

    def _on_logout(self) -> None:
        em_auth.clear()
        self._result_text = f"已退出登录 —— 现在走 {em_market.tier_text()}"
        self._refresh_status()

    @property
    def result_text(self) -> str:
        """给设置页当回执用的一句话（没有动作 ⇒ 空串）。"""
        return self._result_text


def open_login_dialog(parent=None) -> str:
    """打开对话框（模态）⇒ 返回给设置页显示的一句话。"""
    dlg = EmLoginDialog(parent)
    dlg.exec()
    return dlg.result_text
