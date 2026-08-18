import os
import sys
import requests
import pandas as pd
import numpy as np
import time

# --- 1. ดึง Token และ Chat ID จาก GitHub Secrets ---
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

def get_binance_candles_15m(symbol, limit=120):
    """ดึงแท่งเทียน 15M จาก Binance Vision Spot API"""
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=15m&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=15m&limit={limit}"
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

def analyze_events(df):
    """คำนวณ MACD (12, 26, 9) และ EMA 89 ตรวจจับเฉพาะ Event จุดสัมผัส"""
    try:
        # 1. MACD Calculation
        exp1 = df["close"].ewm(span=12, adjust=False).mean()
        exp2 = df["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()

        # 2. EMA 89 Calculation
        ema89 = df["close"].ewm(span=89, adjust=False).mean()

        # แท่งที่ปิดสมบูรณ์ล่าสุด (iloc[-2]) และแท่งก่อนหน้า (iloc[-3])
        m_curr, s_curr = macd.iloc[-2], signal.iloc[-2]
        m_prev, s_prev = macd.iloc[-3], signal.iloc[-3]

        low_curr, high_curr = df["low"].iloc[-2], df["high"].iloc[-2]
        low_prev, high_prev = df["low"].iloc[-3], df["high"].iloc[-3]
        ema_curr = ema89.iloc[-2]
        ema_prev = ema89.iloc[-3]

        events = []

        # --- ตรวจจับ MACD Events ---
        if m_prev <= s_prev and m_curr > s_curr:
            events.append("GOLDEN_CROSS")
        elif m_prev >= s_prev and m_curr < s_curr:
            events.append("DEATH_CROSS")

        if m_prev <= 0 and m_curr > 0:
            events.append("OVER_0")
        elif m_prev >= 0 and m_curr < 0:
            events.append("UNDER_0")

        # --- ตรวจจับ EMA 89 Touch Events (เพิ่งแตะแท่งนี้เป็นแท่งแรก) ---
        # 1. แตะแนวรับ: แท่งก่อนหน้าลอยอยู่เหนือเส้น -> แท่งนี้ย่อลงมาแตะ/แทงทะลุเส้น
        if low_prev > ema_prev and low_curr <= ema_curr:
            events.append("TOUCH_SUPPORT")

        # 2. แตะแนวต้าน: แท่งก่อนหน้าจมอยู่ใต้เส้น -> แท่งนี้เด้งขึ้นไปแตะ/แทงทะลุเส้น
        elif high_prev < ema_prev and high_curr >= ema_curr:
            events.append("TOUCH_RESIST")

        return events
    except Exception:
        return []

def send_telegram(message):
    """ส่งแจ้งเตือนเข้า Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing Telegram Secrets")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            plain = message.replace("*", "").replace("`", "").replace("_", "")
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=10)
        print("Telegram sent successfully.")
    except Exception as e:
        print(f"Telegram Exception: {e}")

def main():
    print("Scanning 15M MACD & EMA 89 Events...")

    results = {
        "GOLDEN_CROSS": [],
        "DEATH_CROSS": [],
        "OVER_0": [],
        "UNDER_0": [],
        "TOUCH_SUPPORT": [],
        "TOUCH_RESIST": []
    }

    for symbol in WATCHLIST:
        df = get_binance_candles_15m(symbol, limit=120)
        if df is not None:
            evs = analyze_events(df)
            for ev in evs:
                if ev in results:
                    results[ev].append(symbol)
        time.sleep(0.03)

    def fmt(lst):
        return "  " + ", ".join(lst) if lst else "  • ไม่มี"

    msg = [
        "⚡️ *[15M MACD & EMA 89 TRIGGER]*",
        "────────────────────────",
        f"🟢 *GOLDEN CROSS [{len(results['GOLDEN_CROSS'])}]*",
        fmt(results["GOLDEN_CROSS"]),
        "",
        f"🔴 *DEATH CROSS [{len(results['DEATH_CROSS'])}]*",
        fmt(results["DEATH_CROSS"]),
        "",
        f"🚀 *OVER 0 [{len(results['OVER_0'])}]*",
        fmt(results["OVER_0"]),
        "",
        f"🔻 *UNDER 0 [{len(results['UNDER_0'])}]*",
        fmt(results["UNDER_0"]),
        "────────────────────────",
        "🎯 *EMA 89 TOUCH (เพิ่งแตะเส้นแท่งแรก):*",
        f"📥 *ย่อแตะรับ (Touch Support) [{len(results['TOUCH_SUPPORT'])}]:*",
        fmt(results["TOUCH_SUPPORT"]),
        "",
        f"📤 *เด้งแตะต้าน (Touch Resist) [{len(results['TOUCH_RESIST'])}]:*",
        fmt(results["TOUCH_RESIST"]),
        "────────────────────────",
        "📌 *Action:* เปิด 5M ดูโครงสร้างแท่งเทียนกลับตัวบริเวณ EMA 89"
    ]

    send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
