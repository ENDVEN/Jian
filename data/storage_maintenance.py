# data/storage_maintenance.py
"""存储与维护（★v6.75 · §7-B13 · **S2-5**）—— 数据目录 / 缓存清理 / 配置导出导入的**唯一实现处**。

【清理范围（**只清可再生成的**）】
  ① **轮转日志**：`logs/app.log.1`、`app.log.2`…（当前正在写的 `app.log` **不动**）；
  ② **残留临时文件**：`USER_DATA_DIR` 下的 `*.tmp`（原子写中断留下的碎片）。
  ⚠ **绝不碰**：数据湖 `data_lake/`、回测存档 `backtest_results/`、截图、交易库 `jian_trades.db`、
    **登录凭据 `em_cookie.json`** —— 那是"数据主权"红线：清理只能清**可再生成**的东西。
【口径】`cache_items()` 先**列出清单与体积**，用户看见了再删（§10-10：别偷偷删东西）。
【配置导出/导入】只动 `preferences`（一份 JSON）；**不含凭据**——凭据在 `em_cookie.json`，
  本模块**不读、不写、不导出**（导出前还会再过滤一遍敏感键）。
"""
from __future__ import annotations

import glob
import json
import logging
import os
import time

from config import settings

logger = logging.getLogger(__name__)

# 导出/导入**必须排除**的偏好键（敏感或只与"今天我发了多少请求"有关，换机没有意义）
EXPORT_DENY = ('em_auth', 'em_request_budget', 'em_throttle')
EXPORT_FILE_NAME = 'jian_config.json'

# 数据目录下的"绝不清"清单（写出来是为了让审查者一眼看到边界）
NEVER_TOUCH = ('data_lake', 'backtest_results', 'screenshots', 'jian_trades.db',
               'em_cookie.json', 'watchlist.json', 'annotations.json')


def _root(root: str = None) -> str:
    return str(root or settings.USER_DATA_DIR)


def cache_items(root: str = None) -> list:
    """可清理项清单 ⇒ `[{'path', 'name', 'bytes', 'kind'}]`（**只读，不删任何东西**）。"""
    base = _root(root)
    out = []
    # ① 轮转日志（当前 app.log 不在其中）
    for p in sorted(glob.glob(os.path.join(base, 'logs', 'app.log.*'))):
        if os.path.isfile(p):
            out.append({'path': p, 'name': os.path.basename(p),
                        'bytes': _size(p), 'kind': '轮转日志'})
    # ② 残留临时文件（原子写碎片；只在数据目录顶层找，不做深递归以免误删）
    for p in sorted(glob.glob(os.path.join(base, '*.tmp'))):
        if os.path.isfile(p):
            out.append({'path': p, 'name': os.path.basename(p),
                        'bytes': _size(p), 'kind': '残留临时文件'})
    return out


def _size(path: str) -> int:
    try:
        return int(os.path.getsize(path))
    except OSError:
        return 0


def human_size(num: float) -> str:
    """字节 ⇒ 人话（B / KB / MB）。"""
    try:
        n = float(num)
    except (TypeError, ValueError):
        return '—'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f"{n:.0f} {unit}" if unit == 'B' else f"{n:.1f} {unit}"
        n /= 1024.0
    return '—'


def cache_text(root: str = None) -> str:
    """给设置页的一行状态：`可清理 3 项 · 1.2 MB（轮转日志 + 残留临时文件）`。"""
    items = cache_items(root)
    if not items:
        return '暂无需要清理的内容'
    kinds = sorted({i['kind'] for i in items})
    return f"可清理 {len(items)} 项 · {human_size(sum(i['bytes'] for i in items))}（{'/'.join(kinds)}）"


def clear_cache(root: str = None) -> dict:
    """清理可再生成的内容 ⇒ `{'removed', 'bytes', 'failed', 'text'}`（**绝不碰用户数据**）。"""
    items = cache_items(root)
    removed, freed, failed = 0, 0, 0
    for it in items:
        try:
            os.remove(it['path'])
            removed += 1
            freed += int(it['bytes'])
        except OSError as e:
            failed += 1
            logger.warning(f"清理失败（跳过）: {it['path']}: {e}")
    text = (f"已清理 {removed} 项 · 释放 {human_size(freed)}"
            + (f"（{failed} 项失败，见日志）" if failed else '')
            + ("；数据湖 / 回测存档 / 登录凭据一律未动" if removed else ''))
    logger.info(text)
    return {'removed': removed, 'bytes': freed, 'failed': failed, 'text': text}


# ==========================================
# 配置导出 / 导入（**不含凭据**）
# ==========================================
def export_config(path: str, prefs=None) -> dict:
    """把偏好导出一份 JSON（过滤敏感键）⇒ `{'ok', 'count', 'path', 'text'}`。"""
    store = _prefs(prefs)
    data = {}
    try:
        raw = store.get_all() if hasattr(store, 'get_all') else None
        if raw is None:                      # 兼容：用默认表里的键逐个取
            from core.preferences import DEFAULTS
            raw = {k: store.get(k) for k in DEFAULTS}
        data = {k: v for k, v in (raw or {}).items() if k not in EXPORT_DENY}
    except Exception as e:                                    # noqa: BLE001
        logger.warning(f"导出配置：读偏好失败: {type(e).__name__}: {e}")
        return {'ok': False, 'count': 0, 'path': '', 'text': f'读取设置失败：{e}'}
    doc = {'app': settings.APP_NAME, 'version': settings.APP_VERSION,
           'exported_at': time.strftime('%Y-%m-%d %H:%M:%S'),
           'note': '不含登录凭据（凭据只存在本机 em_cookie.json，从不导出）',
           'preferences': data}
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning(f"导出配置：写文件失败: {e}")
        return {'ok': False, 'count': 0, 'path': path, 'text': f'写文件失败：{e}'}
    text = f"已导出 {len(data)} 项设置到 {os.path.basename(path)}（不含凭据）"
    logger.info(text)
    return {'ok': True, 'count': len(data), 'path': path, 'text': text}


def import_config(path: str, prefs=None) -> dict:
    """从导出的 JSON 合并回偏好 ⇒ `{'ok', 'count', 'text'}`（**跳过敏感键**；不删已有的键）。"""
    store = _prefs(prefs)
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except Exception as e:                                    # noqa: BLE001
        return {'ok': False, 'count': 0, 'text': f'读不了这个文件（不是本软件的配置？）：{e}'}
    data = doc.get('preferences') if isinstance(doc, dict) else None
    if not isinstance(data, dict) or not data:
        return {'ok': False, 'count': 0, 'text': '文件里没有设置内容（缺 preferences 段）'}
    applied, skipped = 0, 0
    for key, value in data.items():
        if key in EXPORT_DENY:
            skipped += 1
            continue
        try:
            store.set(key, value)
            applied += 1
        except Exception as e:                                # noqa: BLE001
            skipped += 1
            logger.warning(f"导入设置：{key} 写入失败: {type(e).__name__}: {e}")
    text = (f"已导入 {applied} 项设置"
            + (f"（跳过 {skipped} 项：凭据/额度类不导入）" if skipped else '')
            + "；重启应用后全部生效")
    logger.info(text)
    return {'ok': applied > 0, 'count': applied, 'text': text}


def _prefs(prefs=None):
    if prefs is not None:
        return prefs
    from core.preferences import preferences
    return preferences
