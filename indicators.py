"""
Модуль технических индикаторов Билла Вильямса.
Реализации: SMMA, Alligator, Awesome Oscillator (AO),
Market Facilitation Index (BW MFI).
"""

import numpy as np
import pandas as pd


def smma(data: np.ndarray, period: int) -> np.ndarray:
    """
    Сглаженная скользящая средняя (Smoothed Moving Average).
    Используется в индикаторе Alligator.
    Формула: SMMA(i) = (SMMA(i-1) * (period-1) + data(i)) / period
    """
    if len(data) < period:
        return np.full(len(data), 0.0)

    smma_vals = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        smma_vals.append((smma_vals[-1] * (period - 1) + data[i]) / period)

    result = np.full(len(data), 0.0)
    result[period - 1:period - 1 + len(smma_vals)] = smma_vals
    return result


def calculate_alligator(df: pd.DataFrame) -> pd.DataFrame:
    """
    Индикатор Alligator (Аллигатор Билла Вильямса).
    Jaw (Челюсть) - SMMA(13), Teeth (Зубы) - SMMA(8), Lips (Губы) - SMMA(5).
    Все линии строятся по медианной цене (High + Low) / 2.
    """
    hl2 = (df['High'] + df['Low']) / 2
    jaw = smma(hl2.values, 13)
    teeth = smma(hl2.values, 8)
    lips = smma(hl2.values, 5)

    df_alligator = df[['timestamp', 'Close']].copy()
    df_alligator['Jaw'] = jaw
    df_alligator['Teeth'] = teeth
    df_alligator['Lips'] = lips
    return df_alligator.fillna(0)


def calculate_ao(df: pd.DataFrame) -> pd.Series:
    """
    Awesome Oscillator (AO) - осциллятор Билла Вильямса.
    Рассчитывается как разница SMA(5) и SMA(34) от медианной цены (HL/2).
    """
    hl2 = (df['High'] + df['Low']) / 2
    ao = hl2.rolling(window=5).mean() - hl2.rolling(window=34).mean()
    return ao.fillna(0)


def calculate_bw_mfi(df: pd.DataFrame, color_style: bool = False):
    """
    Bill Williams Market Facilitation Index (BW MFI).
    Возвращает кортеж: (Series значений MFI, список цветов баров).
    Цвета определяют соотношение объема и MFI относительно предыдущего бара:
    - Green: объем растет, MFI растет
    - Fade: объем падает, MFI падает
    - Fake: объем падает, MFI растет
    - Squat: объем растет, MFI падает
    """
    mfi = np.zeros(len(df))
    for i in range(1, len(df)):
        if df['Volume'].iloc[i] > 0:
            mfi[i] = (df['High'].iloc[i] - df['Low'].iloc[i]) / df['Volume'].iloc[i]

    palette = ['#000000'] * len(df)
    for i in range(1, len(df)):
        vol_curr, vol_prev = df['Volume'].iloc[i], df['Volume'].iloc[i - 1]
        mfi_curr, mfi_prev = mfi[i], mfi[i - 1]

        if vol_curr < vol_prev and mfi_curr < mfi_prev:
            palette[i] = '#795548' if not color_style else '#9E9E9E'     # Fade
        elif vol_curr < vol_prev and mfi_curr >= mfi_prev:
            palette[i] = '#03A9F4' if not color_style else '#E53935'     # Fake
        elif vol_curr >= vol_prev and mfi_curr < mfi_prev:
            palette[i] = '#E91E63' if not color_style else '#00897B'     # Squat
        elif vol_curr >= vol_prev and mfi_curr >= mfi_prev:
            palette[i] = '#8BC34A' if not color_style else '#00897B'     # Green

    return pd.Series(mfi), palette
