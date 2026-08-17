import sys
import requests
import pandas as pd
import numpy as np
import time

# --- 1. ข้อมูล Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- 2. Top 30 High-Volume Binance ---
WATCHLIST = sorted([
    "AAVE", "ADA", "APT", "ARB", "AVAX",
    "BCH", "BNB", "BTC", "DOGE", "DOT",
    "ENA", "ETH", "FET", "INJ", "LINK",
    "LTC", "NEAR", "ONDO", "OP", "PAXG",
    "PENDLE", "RENDER", "SEI", "SOL", "SUI",
    "TAO", "TIA", "UNI", "XLM", "XRP"
])

def get_binance_candles_15m(coin, limit=300):
    """ดึงข้อมูล 15M 300 แท่งตรงจาก Binance API"""
    symbol = f"{coin}USDT"
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=15m&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=15m&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = requests.get(url, timeout=10).json()
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

def check_macd_events(df_15m):
    """ตรวจจับ Event การตัด และการข้ามแดน 0 บนแท่งปิดสมบูรณ์ล่าสุด (iloc[-2])"""
    try:
        fast = df_15m["close"].ewm(span=12, adjust=False).mean()
        slow = df_15m["close"].ewm(span=26, adjust=False).mean()
        macd = fast - slow
        signal = macd.ewm(span=9, adjust=False).mean()

        m_prev, m_curr = macd.iloc[-3], macd.iloc[-2]
        s_prev, s_curr = signal.iloc[-3], signal.iloc[-2]

        events = []

        # 1. ตรวจจับการตัดกัน (Crossover / Crossunder)
        if (m_prev <= s_prev) and (m_curr > s_curr):
            zone = "เหนือเส้น 0" if m_curr > 0 else "ใต้เส้น 0"
            events.append(f"🟢 *Golden Cross (ตัดขึ้น):* โซน {zone} (MACD: `{m_curr:.5f}`)")

        elif (m_prev >= s_prev) and (m_curr < s_curr):
            zone = "เหนือเส้น 0" if m_curr > 0 else "ใต้เส้น 0"
            events.append(f"🔴 *Death Cross (ตัดลง):* โซน {zone} (MACD: `{m_curr:.5f}`)")

        # 2. ตรวจจับการข้ามแดน 0 (Zero-Line Break)
        if (m_prev <= 0) and (m_curr > 0):
            events.append(f"🚀 *ข้ามแดน 0 ขึ้น (Bullish Zero-Cross):* พลิกเข้าแดนบวก (`{m_curr:.5f}`)")

        elif (m_prev >= 0) and (m_curr < 0):
            events.append(f"🔻 *ข้ามแดน 0 ลง (Bearish Zero-Cross):* พลิกเข้าแดนลบ (`{m_curr:.5f}`)")

        return events
    except Exception:
        return []

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            payload_plain = {"chat_id": TELEGRAM_CHAT_ID, "text": message.replace("*", "").replace("`", "")}
            requests.post(url, json=payload_plain, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    alerts = []

    for coin in WATCHLIST:
        df = get_binance_candles_15m(coin, limit=300)
        if df is None:
            continue

        events = check_macd_events(df)
        sym = f"{coin}USDT"

        for event in events:
            alerts.append(f"• `{sym:<10}` : {event}")

        time.sleep(0.03)

    if alerts:
        msg = [
            "⚡️ *[15M MACD EVENT TRIGGER]*",
            "────────────────────────"
        ]
        msg.extend(alerts)
        msg.append("────────────────────────")
        msg.append("📌 *Next Step:* เปิดชาร์ต 5M เช็ก Dashboard พัด EMA + รอแตะแนวรับ/ต้าน 21/35")
        send_telegram("\n".join(msg))
        print(f"Sent {len(alerts)} events to Telegram.")
    else:
        print("No new 15M MACD events at this bar.")

if __name__ == "__main__":
    main()
