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
  "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "PAXGUSDT", "XRPUSDT",
  "ONDOUSDT", "PENDLEUSDT", "AAVEUSDT", "LINKUSDT", "ENAUSDT", "UNIUSDT", "JUPUSDT",
  "TAOUSDT", "NEARUSDT", "FETUSDT", "RENDERUSDT", "WLDUSDT",
  "SUIUSDT", "SEIUSDT", "INJUSDT", "TIAUSDT"
]

def get_binance_candles_15m(symbol, limit=200):
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

def analyze_macd_and_ema(df):
    """คำนวณ MACD (12, 26, 9) และ EMA 89 ตรวจจับ Event"""
    try:
        exp1 = df["close"].ewm(span=12, adjust=False).mean()
        exp2 = df["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()

        ema89 = df["close"].ewm(span=89, adjust=False).mean()

        m_curr, s_curr = macd.iloc[-2], signal.iloc[-2]
        m_prev, s_prev = macd.iloc[-3], signal.iloc[-3]

        low_curr, high_curr = df["low"].iloc[-2], df["high"].iloc[-2]
        low_prev, high_prev = df["low"].iloc[-3], df["high"].iloc[-3]
        ema_curr = ema89.iloc[-2]
        ema_prev = ema89.iloc[-3]

        events = []

        if m_prev <= s_prev and m_curr > s_curr:
            events.append("GOLDEN_CROSS")
        elif m_prev >= s_prev and m_curr < s_curr:
            events.append("DEATH_CROSS")

        if m_prev <= 0 and m_curr > 0:
            events.append("OVER_0")
        elif m_prev >= 0 and m_curr < 0:
            events.append("UNDER_0")

        # แตะรับ: แท่งก่อนหน้าลอยเหนือเส้น -> แท่งนี้ย่อลงมาแตะเส้น
        if low_prev > ema_prev and low_curr <= ema_curr:
            events.append("TOUCH_SUPPORT")
        # แตะต้าน: แท่งก่อนหน้าจมใต้เส้น -> แท่งนี้เด้งขึ้นไปแตะเส้น
        elif high_prev < ema_prev and high_curr >= ema_curr:
            events.append("TOUCH_RESIST")

        return events
    except Exception:
        return []

def analyze_pivots(df, left=10, right=10):
    """ตรวจจับ Pivot Structure Period 10 (HH, HL, LH, LL)"""
    try:
        highs = df["high"].values
        lows = df["low"].values
        n = len(df)
        
        pivot_highs = []
        pivot_lows = []

        for i in range(left, n - right):
            if all(highs[i] >= highs[i - k] for k in range(1, left + 1)) and \
               all(highs[i] > highs[i + k] for k in range(1, right + 1)):
                pivot_highs.append((i, highs[i]))

            if all(lows[i] <= lows[i - k] for k in range(1, left + 1)) and \
               all(lows[i] < lows[i + k] for k in range(1, right + 1)):
                pivot_lows.append((i, lows[i]))

        events = []

        if len(pivot_highs) >= 2:
            curr_ph = pivot_highs[-1][1]
            prev_ph = pivot_highs[-2][1]
            ph_idx = pivot_highs[-1][0]
            if ph_idx == (n - right - 1):
                events.append("HH" if curr_ph > prev_ph else "LH")

        if len(pivot_lows) >= 2:
            curr_pl = pivot_lows[-1][1]
            prev_pl = pivot_lows[-2][1]
            pl_idx = pivot_lows[-1][0]
            if pl_idx == (n - right - 1):
                events.append("HL" if curr_pl > prev_pl else "LL")

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
    print("Scanning 15M MACD, EMA 89 & Pivots...")

    results = {
        "GOLDEN_CROSS": [],
        "DEATH_CROSS": [],
        "OVER_0": [],
        "UNDER_0": [],
        "TOUCH_SUPPORT": [],
        "TOUCH_RESIST": [],
        "HH": [],
        "HL": [],
        "LH": [],
        "LL": []
    }

    for symbol in WATCHLIST:
        df = get_binance_candles_15m(symbol, limit=200)
        if df is not None:
            for ev in analyze_macd_and_ema(df):
                if ev in results:
                    results[ev].append(symbol)
            for pv in analyze_pivots(df, left=10, right=10):
                if pv in results:
                    results[pv].append(symbol)
        time.sleep(0.03)

    def fmt(lst):
        return "  • " + ", ".join(lst) if lst else "  • ไม่มี"

    msg = [
        "⚡️ *[15M SCANNER & STRUCTURE]*",
        "────────────────────────────",
        "🟢 *GOLDEN CROSS :* ➔ ซูม 5M หาจังหวะ BUY",
        fmt(results["GOLDEN_CROSS"]),
        "",
        "🔴 *DEATH CROSS  :* ➔ ซูม 5M หาจังหวะ SELL",
        fmt(results["DEATH_CROSS"]),
        "",
        "🚀 *OVER 0       :* ➔ โมเมนตัมขึ้นแข็งแกร่ง",
        fmt(results["OVER_0"]),
        "",
        "🔻 *UNDER 0      :* ➔ โมเมนตัมลงแข็งแกร่ง",
        fmt(results["UNDER_0"]),
        "────────────────────────────",
        "🎯 *EMA 89 TOUCH :*",
        "📥 *แตะรับ       :* ➔ ซูม 5M ดูแท่งกลับตัวโซนรับ",
        fmt(results["TOUCH_SUPPORT"]),
        "",
        "📤 *แตะต้าน      :* ➔ ซูม 5M ดูแท่งกลับตัวโซนต้าน",
        fmt(results["TOUCH_RESIST"]),
        "────────────────────────────",
        "📐 *PIVOT (P10)  :*",
        "📈 *HH           :* ➔ ห้ามไล่ รอ 15M ทำ HL",
        fmt(results["HH"]),
        "",
        "🔼 *HL           :* ➔ ย่อจบ ซูม 5M เคาะ BUY",
        fmt(results["HL"]),
        "",
        "📉 *LH           :* ➔ เด้งจบ ซูม 5M เคาะ SELL",
        fmt(results["LH"]),
        "",
        "🔽 *LL           :* ➔ ห้ามตาม รอ 15M เด้งทำ LH",
        fmt(results["LL"]),
        "────────────────────────────",
        "📌 *Check:* 4H เมฆ ➔ 15M Signal ➔ 5M Entry"
    ]

    send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
