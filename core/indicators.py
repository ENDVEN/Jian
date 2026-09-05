# core/indicators.py
import pandas as pd


class TAEngine:
    """
    纯原生技术分析引擎 (Native Technical Analysis Engine)
    零外部依赖，利用 Pandas 向量化极速计算，永久兼容所有 Python 版本。

    【扩展点】新增指标的步骤：
      1. 在本类中新增一个 add_xxx(df, ...) 静态方法
      2. 在 REGISTRY 中登记 'xxx' -> 'add_xxx'
      3. (可选) 在 OUTPUTS 中声明它产出的列名
    调用方只需通过 TAEngine.apply(df, ['xxx']) 声明式使用，无需改动。
    """

    # 指标注册表：对外名称 -> 计算方法名 (延迟解析，避免静态方法绑定问题)
    REGISTRY = {
        'ma': 'add_ma',
        'boll': 'add_boll',
        'macd': 'add_macd',
    }

    # 各指标产出的列名，供调用方做存在性校验与自动图例
    OUTPUTS = {
        'ma': ('MA_5', 'MA_20', 'MA_60'),
        'boll': ('BOLL_UP', 'BOLL_MID', 'BOLL_DOWN'),
        'macd': ('MACD_line', 'MACD_signal', 'MACD_hist'),
    }

    @classmethod
    def available_indicators(cls) -> list[str]:
        """返回全部已注册指标名称"""
        return list(cls.REGISTRY)

    @classmethod
    def apply(cls, df: pd.DataFrame, indicators, **options) -> pd.DataFrame:
        """
        声明式批量计算指标。
        :param indicators: 指标名称列表，如 ['ma', 'macd']
        :param options: 按指标名传入的覆盖参数，如 ma={'windows': (5, 10)}
        """
        if df.empty or not indicators:
            return df

        unknown = [key for key in indicators if key not in cls.REGISTRY]
        if unknown:
            raise ValueError(
                f"未注册的指标: {unknown}。当前可用: {cls.available_indicators()}"
            )

        for key in indicators:
            method = getattr(cls, cls.REGISTRY[key])
            df = method(df, **options.get(key, {}))
        return df

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
