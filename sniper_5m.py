import os
import requests
import pandas as pd
import numpy as np
import time

# --- 1. ดึง Token และ Chat ID จาก GitHub Secrets / Environment ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LTCUSDT", "BCHUSDT",
    "PAXGUSDT", "ONDOUSDT", "LINKUSDT", "PENDLEUSDT", "AAVEUSDT",
    "TAOUSDT", "NEARUSDT", "FETUSDT", "RENDERUSDT", "WLDUSDT", "ARKMUSDT",
    "SUIUSDT", "APTUSDT", "SEIUSDT", "INJUSDT", "TIAUSDT", "PYTHUSDT",
    "JUPUSDT", "ENAUSDT", "UNIUSDT", "STXUSDT",
    "XRPUSDT", "DOGEUSDT", "PEPEUSDT"
]

MIN_SPREAD_PCT = 0.12  # ตัวกรองพัดบีบแคบ / Sideway (0.12%)

def get_binance_candles_5m(symbol, limit=200):
    """ดึงแท่งเทียน 5M จาก Binance Vision / Binance Spot API"""
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=5m&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = requests.get(url, timeout=8).json()
            if isinstance(res, list) and len(res) >= 100:
                df = pd.DataFrame(res, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades", "taker_buy_base",
                    "taker_buy_quote", "ignore"
                ])
                for col in ["open", "high", "low", "close", "open_time"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df.sort_values(by="open_time").dropna().reset_index(drop=True)
        except Exception:
            continue
    return None

def analyze_5m_sniper(df):
    """ตรวจจับจุดยิงสไนเปอร์ พร้อมแยก Plan A (Retest 21/35) และ Plan B (Re-break 89)"""
    try:
        df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
        df["ema35"] = df["close"].ewm(span=35, adjust=False).mean()
        df["ema89"] = df["close"].ewm(span=89, adjust=False).mean()
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

        # MACD (12, 26, 9)
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = ema12 - ema26

        curr = df.iloc[-2]  # แท่งปิดสมบูรณ์ล่าสุด

        ema21_v = curr["ema21"]
        ema35_v = curr["ema35"]
        ema89_v = curr["ema89"]
        ema200_v = curr["ema200"]
        macd_v = curr["macd"]

        open_p = curr["open"]
        close_p = curr["close"]
        high_p = curr["high"]
        low_p = curr["low"]

        # ตัวกรองพัดกาง
        spread_pct = (abs(ema21_v - ema89_v) / ema89_v) * 100
        is_expanded = spread_pct >= MIN_SPREAD_PCT

        is_bull_fan = (ema21_v > ema35_v > ema89_v > ema200_v) and is_expanded
        is_bear_fan = (ema21_v < ema35_v < ema89_v < ema200_v) and is_expanded

        # ----------------------------------------------------
        # 🟢 ฝั่ง BUY (LONG)
        # ----------------------------------------------------
        if is_bull_fan and (macd_v > 0):
            # Plan A: ย่อแตะแถบ 21/35 แล้วปิดเขียวเหนือ 21
            touch_a = (low_p <= max(ema21_v, ema35_v)) and (high_p >= min(ema21_v, ema35_v))
            if touch_a and (close_p > open_p) and (close_p > ema21_v):
                return "BUY", "Plan A"

            # Plan B: ย่อลึกเทส 89 แล้วปิดแท่งตลบกลับขึ้นมายืนเหนือ 21/35
            touch_b = (low_p <= ema89_v) and (close_p > ema89_v)
            if touch_b and (close_p > max(ema21_v, ema35_v)):
                return "BUY", "Plan B"

        # ----------------------------------------------------
        # 🔴 ฝั่ง SELL (SHORT)
        # ----------------------------------------------------
        if is_bear_fan and (macd_v < 0):
            # Plan A: เด้งแตะแถบ 21/35 แล้วปิดแดงใต้ 21
            touch_a = (high_p >= min(ema21_v, ema35_v)) and (low_p <= max(ema21_v, ema35_v))
            if touch_a and (close_p < open_p) and (close_p < ema21_v):
                return "SELL", "Plan A"

            # Plan B: เด้งลึกเทส 89 แล้วปิดแท่งมุดกลับลงมาใต้ 21/35
            touch_b = (high_p >= ema89_v) and (close_p < ema89_v)
            if touch_b and (close_p < min(ema21_v, ema35_v)):
                return "SELL", "Plan B"

        return None, None
    except Exception:
        return None, None

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing Telegram Credentials")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            plain = message.replace("*", "").replace("`", "").replace("_", "")
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=10)
        print("Telegram alert sent.")
    except Exception as e:
        print(f"Telegram Exception: {e}")

def main():
    print("Scanning 5M Entry Triggers (Plan A / B)...")

    buy_signals = []
    sell_signals = []

    for symbol in WATCHLIST:
        df = get_binance_candles_5m(symbol, limit=200)
        if df is not None:
            side, plan = analyze_5m_sniper(df)
            if side == "BUY":
                buy_signals.append(f"{symbol} [{plan}]")
            elif side == "SELL":
                sell_signals.append(f"{symbol} [{plan}]")
        time.sleep(0.03)

    # ไม่ส่งข้อความหากไม่มีสัญญาณเข้าเงื่อนไข
    if not buy_signals and not sell_signals:
        print("No sniper setups found. Telegram skipped.")
        return

    def fmt(lst):
        return "\n".join([f"  • {item}" for item in lst]) if lst else "  • ไม่มี"

    msg = [
        "🎯 *[5M SNIPER ENTRY TRIGGER]*",
        "────────────────────────────",
        "🟢 *BUY SNIPER (เคาะ Market BUY) :*",
        fmt(buy_signals),
        "",
        "🔴 *SELL SNIPER (เคาะ Market SELL) :*",
        fmt(sell_signals),
        "────────────────────────────",
        "📌 *Check:* 4H ยืน 89 ➔ 15M MACD ใกล้ 0 ➔ SL ใต้ Low/EMA89"
    ]

    send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
