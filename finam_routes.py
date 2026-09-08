"""
Роутер для Finam Trade API — доступен только администратору (is_admin),
т.к. токен привязан к личному брокерскому счёту.
"""

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from database import get_db, User
from cache import get_cache_key, get_cached_data, set_cached_data
from indicators import calculate_alligator, calculate_ao, calculate_bw_mfi, find_fractals, find_divergences, calculate_bollinger_bands
from finam import fetch_ohlcv_finam, fetch_finam_assets

router = APIRouter(prefix="/finam", tags=["finam"])


def _require_admin(current_user: User):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа")


@router.get("/symbols")
async def get_finam_symbols(current_user: User = Depends(get_current_user)):
    """
    Список доступных инструментов Finam Trade API.
    /v1/assets у Finam иногда отдаёт 500 (слишком большой ответ на их стороне) —
    в этом случае отдаём пустой список, фронт переключается на ручной ввод тикера.
    """
    _require_admin(current_user)
    try:
        assets = await fetch_finam_assets()
    except HTTPException:
        assets = []
    return {"assets": assets}


@router.get("/chart-data")
async def get_finam_chart_data(
    symbol: str = "SBER@MISX",
    timeframe: str = "1d",
    limit: int = 200,
    current_user: User = Depends(get_current_user),
):
    """Комбинированный Finam endpoint: OHLCV + все индикаторы."""
    _require_admin(current_user)

    key = get_cache_key(symbol, timeframe, limit, "finam_chart")
    cached = await get_cached_data(key)
    if cached:
        return cached

    try:
        df = await fetch_ohlcv_finam(symbol, timeframe, limit)

        ohlcv = df.to_dict("records")
        df_alligator = calculate_alligator(df)
        alligator = df_alligator.to_dict("records")
        ao = calculate_ao(df)
        ao_data = [{"timestamp": t, "AO": v} for t, v in zip(df["timestamp"], ao.values)]
        mfi, palette = calculate_bw_mfi(df)
        bwmfi = [{"timestamp": t, "MFI": float(m), "color": c}
                 for t, m, c in zip(df["timestamp"], mfi.values, palette)]
        df_fractals = find_fractals(df)
        fractal_highs = (df_fractals.dropna(subset=["Fractal_High"])
                         [["timestamp", "Fractal_High"]]
                         .rename(columns={"Fractal_High": "value"})
                         .to_dict("records"))
        fractal_lows = (df_fractals.dropna(subset=["Fractal_Low"])
                        [["timestamp", "Fractal_Low"]]
                        .rename(columns={"Fractal_Low": "value"})
                        .to_dict("records"))
        bearish, bullish = find_divergences(df, ao)
        df_bb = calculate_bollinger_bands(df)
        bollinger = df_bb.to_dict("records")

        response = {
            "symbol": symbol, "timeframe": timeframe,
            "data": ohlcv, "alligator": alligator, "ao": ao_data,
            "bwmfi": bwmfi, "fractal_highs": fractal_highs, "fractal_lows": fractal_lows,
            "bearish": bearish, "bullish": bullish, "bollinger": bollinger,
        }
        await set_cached_data(key, response, ttl=300)
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Finam chart: {str(e)}")
