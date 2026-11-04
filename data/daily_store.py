# data/daily_store.py
"""日快照中转（★2.05 / DATA-PLATFORM P1）。

全市场日更不再逐只发请求：先落一个 `snapshots/bar_daily/YYYY-MM-DD.parquet`，
再把每只的一行安全合并进原有 symbol.parquet。快照是**可恢复的中转/审计层**，
历史仍是唯一读路径，避免一次性改动所有消费者。

安全口径：
- 快照只保留正价行；每只一行；
- 合并前由调用方判断“昨日收盘是否一致”（除权日不直接抄快照）；
- 写入用临时文件 + `os.replace`，不产生半截 parquet。
"""
from __future__ import annotations

import logging
import os
import tempfile

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

__all__ = ["snapshot_dir", "write_snapshot", "read_snapshot", "latest_snapshot",
           "merge_row", "normalize_snapshot"]


def snapshot_dir() -> str:
    return os.path.join(settings.USER_DATA_DIR, "data_lake", "snapshots", "bar_daily")


def _path_for(asof) -> str:
    day = pd.Timestamp(asof).strftime("%Y-%m-%d")
    return os.path.join(snapshot_dir(), f"{day}.parquet")


def normalize_snapshot(df: pd.DataFrame, asof) -> pd.DataFrame:
    """统一列/日期/代码，去重并剔除无正价行。"""
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy()
    if "symbol" not in out.columns or "close" not in out.columns:
        return pd.DataFrame()
    out["symbol"] = out["symbol"].astype(str).str.strip()
    out = out[out["symbol"].str.len() > 0]
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out[out["close"] > 0]
    out["date"] = pd.Timestamp(asof).normalize()
    out = out.drop_duplicates(subset=["symbol"], keep="last")
    return out.reset_index(drop=True)


def write_snapshot(df: pd.DataFrame, asof) -> str:
    """原子写日快照；返回路径。空表不写。"""
    data = normalize_snapshot(df, asof)
    if data.empty:
        return ""
    path = _path_for(asof)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".snap_", suffix=".parquet",
                               dir=os.path.dirname(path))
    os.close(fd)
    try:
        data.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


def read_snapshot(asof) -> pd.DataFrame:
    path = _path_for(asof)
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_parquet(path, engine="pyarrow")
    except Exception as e:  # noqa: BLE001
        logger.warning("日快照读取失败 [%s]: %s", path, e)
        return pd.DataFrame()


def latest_snapshot() -> tuple[str, pd.DataFrame]:
    """返回 `(asof_text, df)`；没有快照 ⇒ `("", empty)`。"""
    folder = snapshot_dir()
    if not os.path.isdir(folder):
        return "", pd.DataFrame()
    names = sorted(n for n in os.listdir(folder) if n.endswith(".parquet"))
    if not names:
        return "", pd.DataFrame()
    asof = names[-1][:-8]          # YYYY-MM-DD.parquet
    return asof, read_snapshot(asof)


def merge_row(history: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    """把快照的一行并入 symbol 历史；同日以快照为准。"""
    if row is None:
        return history
    one = pd.DataFrame([row])
    for col in ("prev_close", "name", "pe", "pb", "total_mktcap", "industry"):
        if col in one.columns:
            one = one.drop(columns=[col])
    if history is not None and len(history) and "symbol" not in history.columns:
        one = one.drop(columns=["symbol"], errors="ignore")
    one["date"] = pd.to_datetime(one["date"], errors="coerce").dt.normalize()
    one = one.dropna(subset=["date"])
    if one.empty:
        return history
    if history is None or len(history) == 0:
        return one.reset_index(drop=True)
    old = history.copy()
    old["date"] = pd.to_datetime(old["date"], errors="coerce").dt.normalize()
    both = pd.concat([old, one], ignore_index=True)
    both = both.drop_duplicates(subset=["date"], keep="last")
    return both.sort_values("date").reset_index(drop=True)
