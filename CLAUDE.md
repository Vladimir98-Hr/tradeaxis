# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TradingView-like web application for cryptocurrency charting with technical indicators. Python/FastAPI backend serving REST API and WebSocket endpoints, with a vanilla JS frontend using Lightweight Charts.

## Commands

### Run the application
```bash
pip install -r requirements.txt
python main.py
# or: uvicorn main:app --reload
```

### Prerequisites
- Python 3.10+
- Redis running on localhost:6379

There are no tests, linter, or formatter configured in this project.

## Architecture

The backend is a FastAPI async application with modular separation:

- **main.py** — App entry point. Mounts routers, CORS middleware, serves static files.
- **config.py** — All configuration constants (Redis URL, exchange name, timeframes, CORS origins, cache TTL, rate limits, server host/port).
- **exchange.py** — CCXT wrapper. Instantiates the exchange client (OKX by default), normalizes symbols (`BTCUSDT` → `BTC/USDT`) and timeframes, fetches OHLCV data as pandas DataFrames.
- **indicators.py** — Bill Williams technical indicators: Alligator (SMMA-based), Awesome Oscillator, BW MFI. All operate on pandas DataFrames.
- **cache.py** — Async Redis caching layer with MD5-based keys and configurable TTL.
- **routes.py** — REST endpoints (`/health`, `/ohlcv`, `/alligator`, `/ao`, `/bwmfi`). Each endpoint checks cache first, then fetches and computes. Rate-limited.
- **websocket.py** — `WS /ws/{symbol}` streams live ticker data (price, 24h stats) every 1 second.
- **static/index.html** — Single-page frontend with dark TradingView-like UI, three synchronized charts (candlestick+Alligator, AO histogram, BW MFI histogram), symbol/timeframe selectors, and WebSocket price ticker. UI is in Russian.

### Data flow
Request → routes.py (check Redis cache) → exchange.py (fetch OHLCV from OKX via CCXT) → indicators.py (compute indicators on DataFrame) → JSON response (last 100 records) → cache result in Redis.

### Key conventions
- Async/await throughout (FastAPI, Redis, WebSocket)
- Snake_case functions/variables, UPPER_CASE module constants
- Comments are in Russian
- `main_backup.py` is the legacy monolithic version (not used)
