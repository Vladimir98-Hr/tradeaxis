# TradingView Clone — Финальный план разработки

## Контекст
Проект — клон TradingView для криптовалют и российских акций.
**Текущее состояние:** Бэкенд на FastAPI с модульной структурой готов (main.py, config.py, exchange.py, indicators.py, cache.py, routes.py, websocket.py, static/index.html). Биржа — OKX через ccxt. Фронтенд — vanilla JS (Lightweight Charts). Мобильного приложения нет. MOEX нет. CI/CD нет.
**Цель:** Пройти от текущего состояния до полноценного приложения с веб-фронтом на React, мобильным приложением на React Native, российскими данными (Tinkoff Invest API) и автодеплоем.

---

## Итоговая структура проекта

```
Project/
├── backend/                    # FastAPI (текущий код, доработанный)
│   ├── main.py
│   ├── config.py
│   ├── cache.py
│   ├── exchange.py
│   ├── indicators.py
│   ├── routes.py
│   ├── websocket.py
│   ├── tinkoff.py              # Новый: MOEX через Tinkoff Invest API
│   └── requirements.txt
├── frontend-web/               # React + Vite + Lightweight Charts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Chart.tsx       # Основной график (свечи + Alligator)
│   │   │   ├── AOChart.tsx     # Awesome Oscillator
│   │   │   ├── MFIChart.tsx    # BW MFI
│   │   │   ├── Ticker.tsx      # Live цена WebSocket
│   │   │   └── Toolbar.tsx     # Выбор символа/таймфрейма
│   │   ├── hooks/
│   │   │   ├── useOHLCV.ts
│   │   │   ├── useIndicators.ts
│   │   │   └── useWebSocket.ts
│   │   └── api.ts              # Все запросы к бэкенду
│   ├── package.json
│   └── vite.config.ts
├── frontend-mobile/            # React Native + Expo
│   ├── app/
│   │   ├── index.tsx           # Главный экран
│   │   ├── chart.tsx           # График
│   │   └── _layout.tsx
│   ├── components/
│   │   ├── CandleChart.tsx
│   │   └── IndicatorPanel.tsx
│   └── package.json
├── deploy/
│   ├── Dockerfile              # Бэкенд
│   ├── docker-compose.yml      # Бэкенд + Redis
│   └── .github/workflows/
│       └── ci.yml              # GitHub Actions
└── CLAUDE.md
```

---

## Фаза 1: Починка и доработка бэкенда
**Файлы:** `backend/routes.py`, `backend/exchange.py`, `backend/indicators.py`, `backend/config.py`, `backend/requirements.txt`

### Шаг 1.1 — Исправить текущие баги
- `routes.py:47` — сообщение об ошибке говорит "Bybit", а биржа OKX. Исправить на `f"{EXCHANGE_ID}: {str(e)}"`
- `requirements.txt` — добавить `pyrate-limiter>=3.9.0` (сейчас импортируется но не указан)
- `exchange.py` — упростить `normalize_symbol()`: сейчас логика с `.replace('/')` может сломаться на нестандартных символах

### Шаг 1.2 — Добавить поддержку .env файла
- Добавить `python-dotenv` в requirements.txt
- `config.py` — читать `REDIS_URL`, `EXCHANGE_ID`, `HOST`, `PORT` из `.env` с fallback на дефолты
- Создать `.env.example` для документации переменных

### Шаг 1.3 — Добавить индикаторы из new.py
- `indicators.py` — добавить:
  - `find_fractals(df, order=5)` — определение локальных максимумов/минимумов через `scipy.signal.argrelextrema`
  - `find_divergences(df, ao)` — поиск бычьих/медвежьих дивергенций по AO
- `routes.py` — добавить эндпоинты:
  - `GET /fractals?symbol=&timeframe=&limit=` → `{fractal_highs: [...], fractal_lows: [...]}`
  - `GET /divergences?symbol=&timeframe=&limit=` → `{bullish: [...], bearish: [...]}`

### Шаг 1.4 — Добавить Tinkoff Invest API (MOEX)
- Создать `backend/tinkoff.py`:
  - Подключение к Tinkoff Invest API (gRPC через `tinkoff-investments`)
  - `fetch_ohlcv_tinkoff(figi, interval, limit)` — данные по FIGI (SBER, GAZP, LKOH)
  - Конвертация в тот же формат DataFrame что и `fetch_ohlcv_df`
- `config.py` — добавить `TINKOFF_TOKEN`, `MOEX_SYMBOLS = {"SBER": "BBG004730N88", ...}`
- `routes.py` — эндпоинт `GET /moex/ohlcv?symbol=SBER&interval=day&limit=100`
- `requirements.txt` — добавить `tinkoff-investments`

### Шаг 1.5 — Добавить /symbols эндпоинт
- `routes.py` — `GET /symbols` возвращает список доступных символов:
  ```json
  {
    "crypto": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
    "moex": ["SBER", "GAZP", "LKOH", "YNDX"]
  }
  ```

---

## Фаза 2: Веб-фронтенд (React + Vite)
**Новая папка:** `frontend-web/`

### Шаг 2.1 — Инициализация проекта
- `npm create vite@latest frontend-web -- --template react-ts`
- Установить: `lightweight-charts`, `react-query` (или `SWR`), `axios`
- Настроить proxy в `vite.config.ts` → `localhost:8000` (чтобы не нужен CORS в dev)

### Шаг 2.2 — API слой
- `src/api.ts` — все fetch-функции к бэкенду:
  - `fetchOHLCV(symbol, timeframe, limit)`
  - `fetchAlligator(symbol, timeframe)`
  - `fetchAO(symbol, timeframe)`
  - `fetchBWMFI(symbol, timeframe)`
  - `fetchFractals(symbol, timeframe)`

### Шаг 2.3 — Хуки данных
- `hooks/useOHLCV.ts` — react-query хук с кешем и refetch интервалом
- `hooks/useIndicators.ts` — параллельная загрузка всех индикаторов
- `hooks/useWebSocket.ts` — подключение к `ws://localhost:8000/ws/{symbol}` с авто-реконнектом и экспоненциальным backoff

### Шаг 2.4 — Компоненты графиков
- `Chart.tsx` — основной LightweightCharts: свечи + Alligator (3 линии) + фракталы (маркеры)
- `AOChart.tsx` — гистограмма AO с зелёным/красным по направлению
- `MFIChart.tsx` — гистограмма BW MFI с цветами из API
- Синхронизация timeScale между всеми тремя графиками (`.subscribeVisibleLogicalRangeChange`)

### Шаг 2.5 — UI компоненты
- `Ticker.tsx` — шапка: символ, live цена, 24h%, хай/лоу, объём (из WebSocket)
- `Toolbar.tsx` — выбор символа (crypto + MOEX) и таймфрейма
- Тёмная тема (CSS переменные), responsive layout

### Шаг 2.6 — Сборка и раздача через бэкенд
- `npm run build` → `frontend-web/dist/`
- `main.py` — `StaticFiles(directory="../frontend-web/dist")` вместо `static/`
- В dev режиме: Vite dev server на :3001, FastAPI на :8000

---

## Фаза 3: Мобильное приложение (React Native + Expo)
**Новая папка:** `frontend-mobile/`

### Шаг 3.1 — Инициализация Expo
- `npx create-expo-app frontend-mobile --template blank-typescript`
- Установить: `expo-router`, `react-native-gifted-charts` (или `victory-native`)
- Настроить `app.json` с именем, иконкой

### Шаг 3.2 — Переиспользовать API слой
- Скопировать `api.ts` и `hooks/` из `frontend-web` с минимальными изменениями
- Заменить WebSocket URL на IP машины (не localhost — эмулятор Android видит хост иначе)

### Шаг 3.3 — Экраны
- `app/index.tsx` — список пар (crypto + MOEX) с живыми ценами
- `app/chart.tsx` — страница графика с тремя панелями (candlestick, AO, MFI)
- `app/_layout.tsx` — Expo Router навигация

### Шаг 3.4 — Компоненты графиков
- `CandleChart.tsx` — candlestick + Alligator линии
- `IndicatorPanel.tsx` — AO + BW MFI гистограммы
- Жесты: pinch-to-zoom через `react-native-gesture-handler`

### Шаг 3.5 — Сборка
- `eas build --platform android` → APK
- Протестировать на реальном устройстве

---

## Фаза 4: CI/CD и деплой
**Новая папка:** `deploy/`

### Шаг 4.1 — Docker
- `deploy/Dockerfile` — образ для бэкенда (Python 3.12, копирует backend/, устанавливает requirements.txt)
- `deploy/docker-compose.yml` — два сервиса: `api` (FastAPI) + `redis` (Redis 7)

### Шаг 4.2 — GitHub Actions
- `deploy/.github/workflows/ci.yml`:
  - Trigger: push в main
  - Jobs:
    1. `lint` — ruff/flake8 бэкенд
    2. `build-frontend` — `npm run build`
    3. `docker-build` — сборка и пуш образа в Docker Hub

### Шаг 4.3 — Деплой на сервер (опционально)
- Render.com / Railway.app — бэкенд из Docker образа
- Vercel — фронтенд из `frontend-web/dist`

---

## Порядок выполнения (приоритеты)

| # | Задача | Файлы | Статус |
|---|--------|-------|--------|
| 1 | Починить баги бэкенда (1.1) | routes.py, requirements.txt | ⬜ |
| 2 | .env поддержка (1.2) | config.py, .env.example | ⬜ |
| 3 | Добавить fractals + divergences (1.3) | indicators.py, routes.py | ⬜ |
| 4 | Tinkoff Invest API (1.4) | tinkoff.py, routes.py, config.py | ⬜ |
| 5 | Эндпоинт /symbols (1.5) | routes.py | ⬜ |
| 6 | React frontend инициализация (2.1-2.2) | frontend-web/ | ⬜ |
| 7 | Компоненты графиков React (2.3-2.5) | frontend-web/src/ | ⬜ |
| 8 | Сборка React → раздача из FastAPI (2.6) | main.py | ⬜ |
| 9 | Expo mobile инициализация (3.1-3.2) | frontend-mobile/ | ⬜ |
| 10 | Экраны и графики мобильного (3.3-3.4) | frontend-mobile/ | ⬜ |
| 11 | Сборка APK (3.5) | — | ⬜ |
| 12 | Docker + CI/CD (4.1-4.2) | deploy/ | ⬜ |

---

## Верификация на каждом этапе

**После Фазы 1:**
- `python main.py` → сервер запустился
- `GET /health` → `{"status": "ok"}`
- `GET /fractals?symbol=BTCUSDT&timeframe=1h` → массив с фракталами
- `GET /moex/ohlcv?symbol=SBER` → OHLCV данные MOEX
- `GET /symbols` → списки crypto и moex

**После Фазы 2:**
- `npm run dev` в frontend-web → открывается браузер
- Графики отображают свечи, Alligator, AO, MFI
- Переключение символов и таймфреймов работает
- Live тикер обновляется из WebSocket

**После Фазы 3:**
- `npx expo start` → приложение запускается в эмуляторе
- Список пар с ценами виден
- График с индикаторами открывается по клику
- Live обновления работают на реальном устройстве

**После Фазы 4:**
- `docker compose up` → бэкенд + Redis запустились
- Push в GitHub → Actions проходят (lint + build + docker)
