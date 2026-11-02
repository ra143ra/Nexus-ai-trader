"""Transparent rule-based market-regime selector for NEXUS.

This is not a trained AI model. It selects among simple rule sets using
observable trend strength, EMA separation, RSI and normalized ATR.
"""
from typing import Any

def ema(values: list[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    current = values[0]
    result = []
    for value in values:
        current = alpha * value + (1 - alpha) * current
        result.append(current)
    return result

def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i-1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)

def atr_percent(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        c, prev = candles[i], candles[i-1]["close"]
        trs.append(max(c["high"] - c["low"], abs(c["high"] - prev), abs(c["low"] - prev)))
    atr = sum(trs[-period:]) / period
    last = candles[-1]["close"]
    return (atr / last * 100) if last else None

def analyze(candles: list[dict[str, Any]]) -> dict[str, Any]:
    if len(candles) < 40:
        return {
            "regime": "UNKNOWN", "selected_strategy": "NONE",
            "signal": "HOLD", "confidence": "LOW",
            "reason": "At least 40 candles are required for this analysis.",
            "risk_note": "No trade should be opened from incomplete data."
        }

    closes = [float(c["close"]) for c in candles]
    fast, slow = ema(closes, 9), ema(closes, 21)
    current_rsi = rsi(closes)
    atr_pct = atr_percent(candles)
    spread_pct = abs(fast[-1] - slow[-1]) / closes[-1] * 100
    slope_pct = (slow[-1] - slow[-6]) / closes[-1] * 100

    # Volatility gate has priority: avoid initiating positions in unusually
    # volatile conditions rather than trying to predict the next move.
    if atr_pct is not None and atr_pct >= 2.5:
        regime, strategy, signal = "HIGH_VOLATILITY", "CAPITAL_PRESERVATION", "HOLD"
        reason = "Normalized ATR is elevated; the engine stands aside."
    elif spread_pct >= 0.18 and abs(slope_pct) >= 0.08:
        regime, strategy = "TRENDING", "EMA_TREND_FOLLOWING"
        if fast[-1] > slow[-1] and current_rsi is not None and 50 <= current_rsi <= 68:
            signal = "BUY"
            reason = "Trend filter is positive and RSI is inside the configured momentum band."
        elif fast[-1] < slow[-1] or (current_rsi is not None and current_rsi > 75):
            signal = "SELL"
            reason = "Trend/momentum filter is negative; review existing exposure."
        else:
            signal = "HOLD"
            reason = "Trend exists, but momentum confirmation is incomplete."
    else:
        regime, strategy = "RANGE_OR_WEAK_TREND", "MEAN_REVERSION_WATCH"
        if current_rsi is not None and current_rsi <= 30:
            signal, reason = "WATCH_BUY", "RSI is oversold; wait for a confirmed reversal before entry."
        elif current_rsi is not None and current_rsi >= 70:
            signal, reason = "WATCH_SELL", "RSI is overbought; wait for confirmation and manage exposure."
        else:
            signal, reason = "HOLD", "No clear edge detected in the current range/weak trend."

    return {
        "regime": regime,
        "selected_strategy": strategy,
        "signal": signal,
        "indicators": {
            "ema_9": round(fast[-1], 8),
            "ema_21": round(slow[-1], 8),
            "rsi_14": round(current_rsi, 2) if current_rsi is not None else None,
            "atr_percent": round(atr_pct, 3) if atr_pct is not None else None,
            "ema_spread_percent": round(spread_pct, 4),
            "slow_ema_slope_percent_5_bars": round(slope_pct, 4)
        },
        "reason": reason,
        "confidence": "RULE_BASED",
        "risk_note": "Signal is informational. No order is placed; confirm with backtesting and paper trading."
    }
