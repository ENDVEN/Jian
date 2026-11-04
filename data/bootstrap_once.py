# data/bootstrap_once.py
"""一次性全历史 bootstrap 授权（★2.06 / DATA-PLATFORM P2）。

为什么不是直接放开预算：日常 300 次/日是产品风控线；一次性 bootstrap 必须：
  1. 显式 arm（写标记文件）；
  2. 跑一次即 consume（防止明天/下次启动又被当成“还授权”）；
  3. 只对 bootstrap 脚本生效，不改普通下载的预算判据。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time

from config import settings

logger = logging.getLogger(__name__)

__all__ = ["flag_path", "arm", "status", "consume", "allowed", "text"]


def flag_path() -> str:
    return os.path.join(settings.USER_DATA_DIR, "em_bootstrap_once.json")


def _read() -> dict:
    path = flag_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write(data: dict) -> None:
    path = flag_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".boot_", suffix=".json",
                               dir=os.path.dirname(path))
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def arm(note: str = "") -> str:
    _write({"armed": True, "consumed": False,
            "armed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note})
    return flag_path()


def status() -> dict:
    return _read()


def allowed() -> bool:
    st = _read()
    return bool(st.get("armed")) and not bool(st.get("consumed"))


def consume() -> None:
    st = _read()
    if not st:
        return
    st.update(armed=False, consumed=True,
              consumed_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    _write(st)


def text() -> str:
    st = _read()
    if not st:
        return "未授权一次性 bootstrap"
    if allowed():
        return "已授权一次性 bootstrap（尚未消费）"
    return "一次性 bootstrap 已消费" if st.get("consumed") else "未授权"
