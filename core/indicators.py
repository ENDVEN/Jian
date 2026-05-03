# core/indicators.py
import pandas as pd

class TAEngine:
    """
    纯原生原生技术分析引擎 (Native Technical Analysis Engine)
    零外部依赖，利用 Pandas 向量化极速计算，永久兼容所有 Python 版本。
    """
    
    @staticmethod
    def add_ma(df: pd.DataFrame, windows=(5, 20, 60)) -> pd.DataFrame:
        """计算简单移动平均线 (SMA)"""
        for w in windows:
            df[f'MA_{w}'] = df['close'].rolling(window=w).mean()
        return df

    @staticmethod
    def add_boll(df: pd.DataFrame, window=20, num_std=2) -> pd.DataFrame:
        """计算布林带 (Bollinger Bands)"""
        ma = df['close'].rolling(window=window).mean()
        std = df['close'].rolling(window=window).std()
        df['BOLL_UP'] = ma + (std * num_std)
        df['BOLL_MID'] = ma
        df['BOLL_DOWN'] = ma - (std * num_std)
        return df

    @staticmethod
    def add_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
        """计算平滑异同移动平均线 (MACD)"""
        # 使用 ewm (Exponential Weighted Math) 计算指数移动平均
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
        
        df['MACD_line'] = ema_fast - ema_slow
        df['MACD_signal'] = df['MACD_line'].ewm(span=signal, adjust=False).mean()
        df['MACD_hist'] = (df['MACD_line'] - df['MACD_signal']) * 2 # 国内习惯将柱子放大2倍
        return df