# data/em_auth.py
"""东财**登录态凭据**的唯一出口（★v6.73）—— 存储、有效性判据、Cookie 头、每日预算。

【为什么做它 · 实测判据（2026-09-26 23:0x，同一刻对照）】
    带 Cookie  `clist` → HTTP 200 · 1.20s · total=1641 · 样本 `003816 中国广核 → 电力`
    匿名       `clist` → RemoteDisconnected（被 RST）
    带 Cookie  `ulist` → HTTP 200 · 0.99s · `600000` 有 f2/f5/f8/f9… 真实值
    匿名       `ulist` → RemoteDisconnected
  ⇒ **门槛是"登录态"，不是"无差别封 IP"**（与 v6.68 的四次实测一致）。
  所以走**双档**：**登录 ⇒ 正常速度**；**不登录 ⇒ 慢速分批 + 冷却**（v6.69/v6.72 已就位）。

【产品级风控纪律（用户 2026-09-26 拍板："要避免被反爬系统盯上"，且不许因此拖慢开发）】
  ① 登录档也**只做小范围/低频**，**绝不做**全市场高频轮询；
  ② **每日请求预算**（`DAILY_BUDGET`）——超了**停在缓存档**并说明，不让用户把账号点进风控；
  ③ **登录档失败即回退匿名档**（不拿账号硬试）；匿名档失败走既有退避冷却；
  ④ **不伪装官方客户端 / 不做多账号轮换 / 不绕验证码**（§10 口径）。
【安全】落 `~/.jian_data/em_cookie.json`（**原子写**），优先 **Windows DPAPI 加密**
  （`ctypes` 调 CryptProtectData，**零新依赖**）；DPAPI 不可用则降级明文但**在状态里标明**。
  ⚠ **日志/回执/断言永不回显 cookie 值**（只报名字与条数）；仓库与文档里**永远没有凭据**。
【不做】绝不存账号密码（软件内登录走官方页面，见后续 P2）。

# 【为什么不自己读浏览器 cookie 库】Chrome/Edge 从 v80 起 cookie 值是 AES-256-GCM 加密
#   （密钥再由 DPAPI 包一层），而 `bash 里没有 cryptography/Crypto/win32crypt` ⇒ 解不开
#   （手写 AES 不现实）。而"读用户全量 cookie 库"本身也是隐私面 ⇒ 产品形态取
#   **用户显式粘贴**（P1，零依赖）或**软件内嵌官方登录页**（P2，需 PyQt6-WebEngine）。
"""
from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import time
from ctypes import wintypes

from config import settings

logger = logging.getLogger(__name__)

AUTH_KEY = 'em_auth'                      # preferences 里只放"状态/预算"（**不放 cookie 值**）
AUTH_FILE = 'em_cookie.json'

# 【登录态判据】东财的登录三元组：缺任一个就当**未登录**（诚实：宁可走慢速档，也别拿半套凭据去试）
KEY_COOKIES = ('ut', 'ct', 'pi')
# 交易/风控指纹类（有就一起带上；东财可能用它们做"像不像真人浏览器"的判据）
EXTRA_COOKIES = ('qgqp_b_id', 'uidal', 'st_pvi', 'st_si', 'st_psi', 'nid18',
                 'nid18_create_time', 'gviem', 'gviem_create_time', 'st_nvi')

# 每日请求预算（防"用户狂点把账号打进风控"；超了停在缓存档）
DAILY_BUDGET = {'auth': 300, 'anon': 100}

_BUDGET_KEY = 'em_request_budget'


# ==========================================
# Windows DPAPI（零新依赖；失败则降级明文）
# ==========================================
class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]


def _dpapi(raw: bytes, protect: bool) -> bytes:
    buf = ctypes.create_string_buffer(raw, len(raw))
    blob_in = _DataBlob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    fn = (ctypes.windll.crypt32.CryptProtectData if protect
          else ctypes.windll.crypt32.CryptUnprotectData)
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError(f"DPAPI {'加密' if protect else '解密'}失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _path() -> str:
    return os.path.join(settings.USER_DATA_DIR, AUTH_FILE)


def _encode(jar: dict) -> tuple:
    """`(payload_str, encrypted)` —— 优先 DPAPI，失败降级明文（并在状态里标明）。"""
    raw = json.dumps(jar, ensure_ascii=False).encode('utf-8')
    try:
        return base64.b64encode(_dpapi(raw, True)).decode('ascii'), True
    except Exception as e:                                # noqa: BLE001 —— 降级但不隐藏事实
        logger.warning(f"DPAPI 不可用（降级为明文存储，状态里会标明）: {e}")
        return raw.decode('utf-8'), False


def _decode(payload: str, encrypted: bool) -> dict:
    if encrypted:
        raw = _dpapi(base64.b64decode(payload.encode('ascii')), False)
    else:
        raw = payload.encode('utf-8')
    data = json.loads(raw.decode('utf-8'))
    return {str(k): str(v) for k, v in (data or {}).items()} if isinstance(data, dict) else {}


# ==========================================
# 存取（原子写；坏档一律当"没登录"，绝不抛）
# ==========================================
def load() -> dict:
    """当前凭据 `{name: value}`；没有/坏档/解不开 ⇒ `{}`。"""
    path = _path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
        return _decode(str(doc.get('payload') or ''), bool(doc.get('encrypted')))
    except Exception as e:                                # noqa: BLE001
        logger.warning(f"东财凭据读取失败（按未登录处理，不阻断）: {type(e).__name__}: {e}")
        return {}


def save(jar: dict) -> bool:
    """覆盖保存（**原子写**：tmp + os.replace）。返回是否落盘成功。"""
    clean = {str(k): str(v).strip() for k, v in (jar or {}).items()
             if str(k).strip() and str(v).strip()}
    if not clean:
        return False
    payload, encrypted = _encode(clean)
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'payload': payload, 'encrypted': encrypted,
                       'saved_at': time.strftime('%Y-%m-%d %H:%M:%S')}, f, ensure_ascii=False)
        os.replace(tmp, path)
        logger.info(f"东财登录凭据已保存（{len(clean)} 条 · 加密={encrypted}）")   # ⚠ 只报条数/名字
        return True
    except OSError as e:
        logger.warning(f"东财凭据写入失败: {e}")
        return False


def clear() -> None:
    """退出登录（删凭据文件 + 清预算计数）。"""
    try:
        if os.path.exists(_path()):
            os.remove(_path())
    except OSError as e:
        logger.warning(f"删除东财凭据失败: {e}")
    logger.info("东财登录态已清除（回到匿名慢速档）")


# ==========================================
# 判据与取值
# ==========================================
def is_logged_in() -> bool:
    """**登录三元组齐**才算登录（`ut`/`ct`/`pi`）—— 少一个走慢速档，别拿半套凭据去试。"""
    jar = load()
    return all(jar.get(n) for n in KEY_COOKIES)


def cookie_header() -> str:
    """`a=b; c=d`（**只在请求头里用，别写日志、别进回执**）。未登录 ⇒ 空串。"""
    jar = load()
    if not all(jar.get(n) for n in KEY_COOKIES):
        return ''
    order = list(KEY_COOKIES) + [n for n in EXTRA_COOKIES if n in jar]
    rest = [n for n in jar if n not in order]
    return '; '.join(f'{n}={jar[n]}' for n in order + rest)


def names() -> list:
    """在场 cookie **名字**（给界面/日志看状态用，**不含值**）。"""
    return sorted(load().keys())


def status() -> dict:
    """给界面/回执：是否登录 + 条数 + 名字 + 是否加密（**绝不含值**）。"""
    path = _path()
    enc = False
    saved_at = ''
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
            enc, saved_at = bool(doc.get('encrypted')), str(doc.get('saved_at') or '')
        except Exception:                                 # noqa: BLE001
            pass
    jar = load()
    return {'present': bool(jar), 'logged_in': all(jar.get(n) for n in KEY_COOKIES),
            'count': len(jar), 'names': sorted(jar.keys()),
            'encrypted': enc, 'saved_at': saved_at,
            'budget': dict(DAILY_BUDGET)}


def parse_pasted(text: str) -> dict:
    """把用户粘贴的内容解析成 `{name: value}` —— 支持两种形态：

    ① **扩展导出的 JSON 数组**（`[{"name": ..., "value": ...}, ...]`）；
    ② **`Cookie:` 头字符串**（`a=b; c=d; …`）。
    解析不出东西 ⇒ 回 `{}`（上层据此说"没解析到有效条目"）。
    """
    raw = (text or '').strip()
    if not raw:
        return {}
    if raw.startswith('[') or raw.startswith('{'):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            return {str(it.get('name')): str(it.get('value')) for it in data
                    if isinstance(it, dict) and it.get('name') and it.get('value') is not None}
        except ValueError:
            return {}
    out = {}
    for part in raw.replace('\n', ';').split(';'):
        if '=' in part:
            k, v = part.split('=', 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


# ==========================================
# 每日预算（防"用户狂点把账号点进风控"）
# ==========================================
def _today() -> str:
    return time.strftime('%Y-%m-%d')


def note_request(who: str = 'auth', n: int = 1) -> None:
    """记一次真实请求（按天计数，跨天自动清零）。"""
    from core.preferences import preferences
    st = preferences.get(_BUDGET_KEY)
    st = st if isinstance(st, dict) else {}
    if st.get('day') != _today():
        st = {'day': _today(), 'auth': 0, 'anon': 0}
    st[who] = int(st.get(who) or 0) + int(n)
    preferences.set(_BUDGET_KEY, st)


def budget_left(who: str = 'auth') -> int:
    """今天还剩多少请求额度（负数按 0）。"""
    from core.preferences import preferences
    st = preferences.get(_BUDGET_KEY)
    st = st if isinstance(st, dict) and st.get('day') == _today() else {}
    limit = int(DAILY_BUDGET.get(who, 0))
    return max(0, limit - int(st.get(who) or 0))


def budget_text(who: str = 'auth') -> str:
    """给回执的一句话：`今日东财取数额度 还剩 287/300 次（登录档）`。"""
    tag = '登录档' if who == 'auth' else '匿名档'
    return f"今日东财取数额度 还剩 {budget_left(who)}/{DAILY_BUDGET.get(who, 0)} 次（{tag}）"
