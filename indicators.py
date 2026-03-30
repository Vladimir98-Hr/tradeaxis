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
    # Точная формула из оригинала: деление через pandas (NaN при Volume=0)
    mfi = (df['High'] - df['Low']) / df['Volume']

    palette = pd.Series(index=df.index, dtype=object)
    bar_range = df['High'] - df['Low']
    # Кастомная формула: объём падает, но диапазон бара растёт
    color_cond3 = (df['Volume'] < df['Volume'].shift(1)) & (bar_range > bar_range.shift(1))
    color_cond1 = (df['Volume'] < df['Volume'].shift(1)) & (mfi < mfi.shift(1)) & ~color_cond3
    color_cond2 = (df['Volume'] < df['Volume'].shift(1)) & (mfi > mfi.shift(1)) & ~color_cond3
    color_cond4 = (df['Volume'] > df['Volume'].shift(1)) & (mfi > mfi.shift(1))

    if color_style:
        palette[color_cond1] = '#9E9E9E'
        palette[color_cond2] = '#E53935'
        palette[color_cond3] = '#00897B'
        palette[color_cond4] = '#00897B'
    else:
        palette[color_cond1] = '#795548'   # Fade
        palette[color_cond2] = '#03A9F4'   # Fake
        palette[color_cond3] = '#E91E63'   # Squat
        palette[color_cond4] = '#8BC34A'   # Green

    palette = palette.fillna('#000000')
    return mfi.fillna(0), palette.tolist()
