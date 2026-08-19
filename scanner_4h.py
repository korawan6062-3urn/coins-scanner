import os
import sys
import requests
import pandas as pd
import numpy as np
import time

# --- 1. ดึงข้อมูล Telegram จาก GitHub Secrets ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

WATCHLIST = [
  "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "PAXGUSDT", "XRPUSDT",
  "ONDOUSDT", "PENDLEUSDT", "AAVEUSDT", "LINKUSDT", "ENAUSDT", "UNIUSDT", "JUPUSDT",
  "TAOUSDT", "NEARUSDT", "FETUSDT", "RENDERUSDT", "WLDUSDT",
  "SUIUSDT", "SEIUSDT", "INJUSDT", "TIAUSDT"
]

def get_binance_candles_4h(symbol):
    """ดึงข้อมูลแท่งเทียน 4H ตรงจาก Binance Public API"""
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=4h&limit=500",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=4h&limit=500"
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
                for col in ["open", "high", "low", "close", "volume", "open_time"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.sort_values(by="open_time").dropna().reset_index(drop=True)
                return df
        except Exception:
            continue
    return None

def analyze_4h_cloud(df):
    """คำนวณเมฆ Ichimoku (9, 26, 52, 26) บนแท่ง 4H ที่ปิดสมบูรณ์แล้ว"""
    try:
        tenkan = (df["high"].rolling(9).max() + df["low"].rolling(9).min()) / 2
        kijun = (df["high"].rolling(26).max() + df["low"].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2).shift(26)

        # แท่งปิดสมบูรณ์ล่าสุดคือ iloc[-2]
        close_val = df["close"].iloc[-2]
        span_a_val = span_a.iloc[-2]
        span_b_val = span_b.iloc[-2]

        if pd.isna(span_a_val) or pd.isna(span_b_val):
            return "UNKNOWN"

        top_kumo = max(span_a_val, span_b_val)
        bot_kumo = min(span_a_val, span_b_val)

        if close_val > top_kumo:
            return "BUY"
        elif close_val < bot_kumo:
            return "SELL"
        else:
            return "UNKNOWN"
    except Exception:
        return "UNKNOWN"

def format_grid(coins, cols=3):
    """จัดเรียงรายชื่อเหรียญแถวละ 3 ตัว ล็อกความกว้างช่องละ 11 ตัวอักษร"""
    if not coins:
        return "  • ไม่มี"
    rows = []
    for i in range(0, len(coins), cols):
        chunk = coins[i:i + cols]
        row_str = "  " + " ".join([f"`{c:<11}`" for c in chunk])
        rows.append(row_str)
    return "\n".join(rows)

def send_telegram(message):
    """ส่งข้อความสรุปเข้า Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing Telegram Token/Chat ID in Secrets")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            payload_plain = {"chat_id": TELEGRAM_CHAT_ID, "text": message.replace("*", "").replace("`", "")}
            requests.post(url, json=payload_plain, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    buy_list = []
    sell_list = []
    unknown_list = []

    for sym in WATCHLIST:
        df = get_binance_candles_4h(sym)

        if df is None:
            unknown_list.append(sym)
            continue

        status = analyze_4h_cloud(df)

        if status == "BUY":
            buy_list.append(sym)
        elif status == "SELL":
            sell_list.append(sym)
        else:
            unknown_list.append(sym)

        time.sleep(0.04)

    msg = [
        "📊 *สรุปภาพรวมเหรียญ TF 4H (Pure Cloud)*",
        "────────────────────────",
        f"🟢 *BUY (เหนือเมฆ) [{len(buy_list)}]*",
        format_grid(buy_list, cols=3),
        "",
        f"🔴 *SELL (ใต้เมฆ) [{len(sell_list)}]*",
        format_grid(sell_list, cols=3),
        "",
        f"⚪️ *UNKNOWN (ในเมฆ) [{len(unknown_list)}]*",
        format_grid(unknown_list, cols=3),
        "────────────────────────",
        "📌 *แนวทาง:* รอแจ้งเตือนรอบคลื่นจากบอท 15M แล้วสังเกตระยะห่าง EMA 89 หน้างาน"
    ]

    send_telegram("\n".join(msg))
    print("4H Scanner executed successfully.")

if __name__ == "__main__":
    main()
