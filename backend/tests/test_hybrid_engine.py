from hybrid_engine import analyze

def candles_from_closes(closes):
    return [
        {"open": p, "high": p * 1.002, "low": p * 0.998, "close": p, "volume": 1}
        for p in closes
    ]

def test_insufficient_history_holds():
    result = analyze(candles_from_closes([100 + i for i in range(20)]))
    assert result["signal"] == "HOLD"
    assert result["regime"] == "UNKNOWN"

def test_output_has_disclaimer_and_strategy():
    result = analyze(candles_from_closes([100 + i * 0.3 for i in range(80)]))
    assert result["selected_strategy"] in {
        "CAPITAL_PRESERVATION", "EMA_TREND_FOLLOWING", "MEAN_REVERSION_WATCH"
    }
    assert "No order is placed" in result["risk_note"]
