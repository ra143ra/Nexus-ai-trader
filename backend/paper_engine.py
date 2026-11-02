"""Persistent, long-only PAPER trading engine. No exchange orders are ever sent."""
import sqlite3
import threading
from datetime import datetime, timezone, date

DB_PATH = "nexus_paper.db"
_LOCK = threading.Lock()

def _connect():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with _LOCK, _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS account (
          id INTEGER PRIMARY KEY CHECK(id=1), balance REAL NOT NULL,
          starting_balance REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
          daily_start_equity REAL NOT NULL, daily_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS positions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL UNIQUE,
          quantity REAL NOT NULL, entry_price REAL NOT NULL,
          quote_cost REAL NOT NULL, stop_price REAL NOT NULL,
          target_price REAL NOT NULL, opened_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trades (
          id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
          side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL,
          quote_value REAL NOT NULL, fee REAL NOT NULL, pnl REAL,
          reason TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        db.execute("""INSERT OR IGNORE INTO account
          (id,balance,starting_balance,enabled,daily_start_equity,daily_date)
          VALUES (1,100,100,0,100,?)""", (date.today().isoformat(),))

def _account(db):
    return db.execute("SELECT * FROM account WHERE id=1").fetchone()

def _equity(db, prices=None):
    acc = _account(db)
    total = acc["balance"]
    for p in db.execute("SELECT * FROM positions"):
        price = (prices or {}).get(p["symbol"], p["entry_price"])
        total += p["quantity"] * price
    return total

def status(prices=None):
    init_db()
    with _LOCK, _connect() as db:
        acc = _account(db)
        positions = [dict(x) for x in db.execute("SELECT * FROM positions")]
        return {
          "mode":"PAPER_ONLY", "enabled":bool(acc["enabled"]),
          "cash_usdt":round(acc["balance"],4),
          "equity_usdt":round(_equity(db, prices),4),
          "starting_balance_usdt":acc["starting_balance"],
          "daily_loss_limit_percent":2.0,
          "max_position_percent":10.0,
          "positions":positions,
          "live_trading_enabled":False
        }

def set_enabled(enabled: bool):
    init_db()
    with _LOCK, _connect() as db:
        db.execute("UPDATE account SET enabled=? WHERE id=1", (1 if enabled else 0,))
    return status()

def _close_position(db, pos, price, reason, fee_rate):
    qty = pos["quantity"]
    gross = qty * price
    fee = gross * fee_rate
    proceeds = gross - fee
    cost = pos["quote_cost"]
    pnl = proceeds - cost
    db.execute("UPDATE account SET balance=balance+? WHERE id=1", (proceeds,))
    db.execute("DELETE FROM positions WHERE id=?", (pos["id"],))
    db.execute("""INSERT INTO trades(symbol,side,quantity,price,quote_value,fee,pnl,reason,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?)""",
               (pos["symbol"],"SELL",qty,price,gross,fee,pnl,reason,datetime.now(timezone.utc).isoformat()))
    return {"side":"SELL","symbol":pos["symbol"],"pnl_usdt":round(pnl,4),"reason":reason}

def tick(symbol: str, price: float, signal: str, fee_bps: float = 10):
    """One explicit market-data tick. Scheduler/automatic live execution is not included."""
    init_db()
    symbol = symbol.upper()
    if price <= 0: raise ValueError("price must be positive")
    fee_rate = min(max(fee_bps, 0), 100) / 10000
    actions = []
    with _LOCK, _connect() as db:
        acc = _account(db)
        today = date.today().isoformat()
        if acc["daily_date"] != today:
            db.execute("UPDATE account SET daily_date=?, daily_start_equity=? WHERE id=1",
                       (today, _equity(db, {symbol:price})))
            acc = _account(db)
        pos = db.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
        if pos:
            if price <= pos["stop_price"]:
                actions.append(_close_position(db,pos,price,"STOP_LOSS",fee_rate))
            elif price >= pos["target_price"]:
                actions.append(_close_position(db,pos,price,"TAKE_PROFIT",fee_rate))
            elif signal == "SELL":
                actions.append(_close_position(db,pos,price,"STRATEGY_EXIT",fee_rate))
        acc = _account(db)
        equity = _equity(db, {symbol:price})
        daily_loss = max(0.0, (acc["daily_start_equity"] - equity) / max(acc["daily_start_equity"], 1e-9))
        if daily_loss >= 0.02:
            db.execute("UPDATE account SET enabled=0 WHERE id=1")
        elif acc["enabled"] and signal == "BUY" and not pos:
            open_count = db.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"]
            if open_count == 0:
                cash = _account(db)["balance"]
                spend = min(cash * 0.10, cash / (1 + fee_rate))
                if spend >= 5:
                    fee = spend * fee_rate
                    qty = (spend - fee) / price
                    stop = price * 0.98
                    target = price * 1.04
                    db.execute("UPDATE account SET balance=balance-? WHERE id=1", (spend,))
                    db.execute("""INSERT INTO positions(symbol,quantity,entry_price,quote_cost,stop_price,target_price,opened_at)
                                  VALUES(?,?,?,?,?,?,?)""",
                               (symbol,qty,price,spend,stop,target,datetime.now(timezone.utc).isoformat()))
                    db.execute("""INSERT INTO trades(symbol,side,quantity,price,quote_value,fee,pnl,reason,created_at)
                                  VALUES(?,?,?,?,?,?,?,?,?)""",
                               (symbol,"BUY",qty,price,spend,fee,None,"HYBRID_BUY_SIGNAL",datetime.now(timezone.utc).isoformat()))
                    actions.append({"side":"BUY","symbol":symbol,"quantity":round(qty,8),
                                    "entry_price":price,"stop_price":round(stop,8),"target_price":round(target,8)})
    return {"actions":actions,"status":status({symbol:price})}

def trade_history(limit=50):
    init_db()
    with _LOCK, _connect() as db:
        return [dict(x) for x in db.execute(
          "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (max(1,min(limit,200)),))]
