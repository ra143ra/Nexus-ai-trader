"""Background PAPER-only polling loop. Optional Telegram alerts use env vars."""
import asyncio
import os
import httpx
import paper_engine

SYMBOLS = [x.strip().upper() for x in os.getenv("NEXUS_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if x.strip()]
POLL_SECONDS = max(60, int(os.getenv("NEXUS_POLL_SECONDS", "300")))
_task = None
_stop = asyncio.Event()

async def _telegram(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message}
            )
    except httpx.HTTPError:
        # Notification failure must never stop the paper engine.
        pass

async def _run_cycle():
    from app import market_price, hybrid_analysis
    if not paper_engine.status()["enabled"]:
        return
    for symbol in SYMBOLS:
        try:
            price = await market_price(symbol)
            analysis = await hybrid_analysis(symbol, "1h")
            result = paper_engine.tick(symbol, price["price"], analysis["signal"])
            for action in result["actions"]:
                await _telegram(
                    f"NEXUS PAPER {action['side']} {symbol}\n"
                    f"Price: {price['price']}\n"
                    f"Reason: {action.get('reason','HYBRID_SIGNAL')}\n"
                    f"PnL: {action.get('pnl_usdt','n/a')} USDT"
                )
        except Exception as exc:
            await _telegram(f"NEXUS PAPER cycle error for {symbol}: {type(exc).__name__}")

async def _loop():
    while not _stop.is_set():
        await _run_cycle()
        try:
            await asyncio.wait_for(_stop.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass

def start_scheduler():
    global _task
    if _task is None or _task.done():
        _stop.clear()
        _task = asyncio.create_task(_loop())

async def stop_scheduler():
    global _task
    _stop.set()
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None

def scheduler_status():
    return {
        "running": bool(_task and not _task.done()),
        "poll_seconds": POLL_SECONDS,
        "symbols": SYMBOLS,
        "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "execution_mode": "PAPER_ONLY"
    }
