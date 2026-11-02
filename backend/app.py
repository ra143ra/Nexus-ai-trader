from datetime import datetime, timezone
from typing import Literal
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from hybrid_engine import analyze as hybrid_analyze
import paper_engine
import paper_scheduler

app = FastAPI(title="NEXUS AI TRADER API", version="0.3.0")

@app.on_event("startup")
async def start_paper_scheduler():
    paper_engine.init_db()
    paper_scheduler.start_scheduler()

@app.on_event("shutdown")
async def stop_paper_scheduler():
    await paper_scheduler.stop_scheduler()

MODE = "PAPER"
STARTING_BALANCE_USDT = 100.0
paper_balance = STARTING_BALANCE_USDT
paper_trades = []
BINANCE_PUBLIC = "https://api.binance.com"

class PaperOrder(BaseModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,15}USDT$")
    side: Literal["BUY", "SELL"]
    quote_amount: float = Field(gt=0, le=25)
    reference_price: float = Field(gt=0)

def valid_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if not symbol.endswith("USDT") or len(symbol) > 20:
        raise HTTPException(400, "Use a USDT-quoted symbol, e.g. BTCUSDT")
    return symbol

async def get_klines(symbol: str, interval: str = "1h", limit: int = 150):
    symbol = valid_symbol(symbol)
    if interval not in {"5m", "15m", "1h", "4h", "1d"}:
        raise HTTPException(400, "Supported intervals: 5m, 15m, 1h, 4h, 1d")
    limit = max(30, min(limit, 500))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{BINANCE_PUBLIC}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit}
            )
            response.raise_for_status()
            raw = response.json()
        return [
            {"time": int(row[0]), "open": float(row[1]), "high": float(row[2]),
             "low": float(row[3]), "close": float(row[4]), "volume": float(row[5])}
            for row in raw
        ]
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "Could not retrieve public market data from the exchange.")

def ema(values, period):
    alpha = 2 / (period + 1)
    out = []
    current = values[0]
    for value in values:
        current = alpha * value + (1 - alpha) * current
        out.append(current)
    return out

def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def make_signal(candles):
    closes = [c["close"] for c in candles]
    if len(closes) < 30:
        return {"signal": "HOLD", "reason": "Not enough candle history.", "rsi": None}
    fast = ema(closes, 9)
    slow = ema(closes, 21)
    current_rsi = rsi(closes)
    # Conservative long-only spot signal. Require trend alignment and avoid chasing extremes.
    if fast[-1] > slow[-1] and 50 <= current_rsi <= 68:
        signal, reason = "BUY", "EMA 9 is above EMA 21 and RSI confirms positive momentum."
    elif fast[-1] < slow[-1] or (current_rsi is not None and current_rsi > 75):
        signal, reason = "SELL", "Trend/momentum filter is negative; review any open paper position."
    else:
        signal, reason = "HOLD", "Trend and momentum conditions are not aligned."
    return {
        "signal": signal,
        "reason": reason,
        "indicators": {
            "ema_9": round(fast[-1], 6),
            "ema_21": round(slow[-1], 6),
            "rsi_14": round(current_rsi, 2) if current_rsi is not None else None
        }
    }

@app.get("/health")
def health():
    paper_engine.init_db()
    return {"status": "ok", "mode": MODE, "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/dashboard")
def dashboard():
    state = paper_engine.status()
    return {
        "bot_name": "NEXUS AI TRADER", "mode": MODE,
        "paper_balance_usdt": state["cash_usdt"],
        "equity_usdt": state["equity_usdt"],
        "open_positions": len(state["positions"]),
        "closed_paper_trades": len(paper_engine.trade_history()),
        "bot_enabled": state["enabled"], "live_trading_enabled": False
    }

@app.get("/market/price/{symbol}")
async def market_price(symbol: str):
    symbol = valid_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{BINANCE_PUBLIC}/api/v3/ticker/price", params={"symbol": symbol}
            )
            response.raise_for_status()
            data = response.json()
        return {"symbol": symbol, "price": float(data["price"]), "source": "Binance public market data"}
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "Could not retrieve public market price.")

@app.get("/market/klines/{symbol}")
async def market_klines(symbol: str, interval: str = "1h", limit: int = 150):
    return {"symbol": symbol.upper(), "interval": interval, "candles": await get_klines(symbol, interval, limit)}

@app.get("/signal/{symbol}")
async def signal(symbol: str, interval: str = "1h"):
    candles = await get_klines(symbol, interval, 150)
    return {"symbol": symbol.upper(), "interval": interval, **make_signal(candles)}

@app.get("/hybrid-analysis/{symbol}")
async def hybrid_analysis(symbol: str, interval: str = "1h"):
    """Select a transparent rule set based on a simple market-regime classification."""
    candles = await get_klines(symbol, interval, 180)
    return {"symbol": symbol.upper(), "interval": interval, **hybrid_analyze(candles)}

@app.get("/backtest/{symbol}")
async def backtest(symbol: str, interval: str = "1h", fee_bps: float = 10, slippage_bps: float = 5):
    """Illustrative long-only EMA/RSI backtest; assumes next-candle execution."""
    candles = await get_klines(symbol, interval, 500)
    closes = [c["close"] for c in candles]
    fast, slow = ema(closes, 9), ema(closes, 21)
    fee = max(0, min(fee_bps, 100)) / 10000
    slip = max(0, min(slippage_bps, 100)) / 10000
    cash, units, entry_value = 1000.0, 0.0, 0.0
    trades = 0
    equity_curve = []
    for i in range(30, len(closes) - 1):
        r = rsi(closes[:i+1])
        buy = fast[i] > slow[i] and r is not None and 50 <= r <= 68
        sell = fast[i] < slow[i] or (r is not None and r > 75)
        execution_price = closes[i+1]
        if units == 0 and buy:
            spend = cash
            units = (spend * (1 - fee)) / (execution_price * (1 + slip))
            entry_value = spend
            cash = 0.0
        elif units > 0 and sell:
            proceeds = units * execution_price * (1 - slip) * (1 - fee)
            cash = proceeds
            units = 0.0
            trades += 1
        equity_curve.append(cash + units * closes[i+1])
    final_equity = cash + units * closes[-1]
    initial = 1000.0
    peak, max_dd = initial, 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak:
            max_dd = max(max_dd, (peak - equity) / peak)
    return {
        "symbol": symbol.upper(), "interval": interval,
        "starting_balance_usdt": initial,
        "ending_equity_usdt": round(final_equity, 2),
        "return_percent": round((final_equity / initial - 1) * 100, 2),
        "closed_trades": trades,
        "max_drawdown_percent": round(max_dd * 100, 2),
        "assumptions": {
            "fee_bps_each_side": fee_bps, "slippage_bps_each_side": slippage_bps,
            "execution": "next candle close", "position": "long-only, fully invested",
            "warning": "Historical simulation only; limited sample, no guarantee of future results."
        }
    }


@app.get("/paper-bot/status")
def paper_bot_status():
    return paper_engine.status()

@app.post("/paper-bot/start")
def paper_bot_start():
    # Enables paper simulation only; no exchange credentials or live orders exist.
    return paper_engine.set_enabled(True)

@app.post("/paper-bot/stop")
def paper_bot_stop():
    return paper_engine.set_enabled(False)

@app.post("/paper-bot/tick/{symbol}")
async def paper_bot_tick(symbol: str, interval: str = "1h"):
    # One evaluation using current public price and latest hybrid signal.
    symbol = valid_symbol(symbol)
    price_data = await market_price(symbol)
    analysis = await hybrid_analysis(symbol, interval)
    result = paper_engine.tick(symbol, price_data["price"], analysis["signal"])
    return {"market": price_data, "analysis": analysis, "execution": result}

@app.get("/paper-bot/trades")
def paper_bot_trades(limit: int = 50):
    return paper_engine.trade_history(limit)

@app.post("/paper-order")
def paper_order(order: PaperOrder):
    raise HTTPException(410, "Manual legacy paper orders are disabled. Use the risk-controlled paper bot endpoints.")

@app.get("/paper-trades")
def get_paper_trades():
    return paper_engine.trade_history()


@app.get("/paper-bot/scheduler")
def paper_bot_scheduler_status():
    return paper_scheduler.scheduler_status()
