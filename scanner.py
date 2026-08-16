import sys
import requests
import pandas as pd
import numpy as np
import time

# --- 1. ข้อมูล Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- 2. Top 30 High-Volume Binance (รวม PAXG) เรียง A -> Z ---
WATCHLIST = sorted([
    "AAVE", "ADA", "APT", "ARB", "AVAX",
    "BCH", "BNB", "BTC", "DOGE", "DOT",
    "ENA", "ETH", "FET", "INJ", "LINK",
    "LTC", "NEAR", "ONDO", "OP", "PAXG",
    "PENDLE", "RENDER", "SEI", "SOL", "SUI",
    "TAO", "TIA", "UNI", "XLM", "XRP"
])

def get_candles(coin, interval="4h", limit=120):
    """ดึงข้อมูลแท่งเทียน 4H จาก Gate.io หรือ KuCoin"""
    try:
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval={interval}&limit={limit}"
        res = requests.get(url, timeout=7).json()
        if isinstance(res, list) and len(res) >= 50:
            df = pd.DataFrame(res, columns=["time", "volume", "close", "high", "low", "open"])
            df["time"] = pd.to_numeric(df["time"], errors="coerce")
            df = df.sort_values(by="time").reset_index(drop=True)
            for col in ["close", "high", "low", "open"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna().reset_index(drop=True)
            if len(df) >= 50:
                return df
    except Exception:
        pass

    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type=4hour&symbol={coin}-USDT"
        res = requests.get(url, timeout=7).json()
        if isinstance(res, dict) and res.get("code") == "200000" and res.get("data"):
            raw = res["data"]
            if len(raw) >= 50:
                df = pd.DataFrame(raw, columns=["time", "open", "close", "high", "low", "volume", "turnover"])
                df["time"] = pd.to_numeric(df["time"], errors="coerce")
                df = df.sort_values(by="time").reset_index(drop=True)
                for col in ["close", "high", "low", "open"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().reset_index(drop=True)
                if len(df) >= 50:
                    return df
    except Exception:
        pass

    return None

def analyze_4h(df):
    """วิเคราะห์สถานะ 4H ด้วยเมฆ Ichimoku ล้วน"""
    try:
        tenkan = (df["high"].rolling(9).max() + df["low"].rolling(9).min()) / 2
        kijun = (df["high"].rolling(26).max() + df["low"].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2).shift(26)

        last_close = df["close"].iloc[-1]
        top_kumo = max(span_a.iloc[-1], span_b.iloc[-1])
        bot_kumo = min(span_a.iloc[-1], span_b.iloc[-1])

        if pd.isna(top_kumo) or pd.isna(bot_kumo):
            return "UNKNOWN"

        if last_close > top_kumo:
            return "BUY"
        elif last_close < bot_kumo:
            return "SELL"
        else:
            return "UNKNOWN"
    except Exception:
        return "UNKNOWN"

def format_grid(coins, cols=3):
    """จัดเรียงรายชื่อเหรียญเป็นแถวละ 3 ตัว เพื่อความสมมาตรและประหยัดพื้นที่"""
    if not coins:
        return "  • ไม่มี"
    rows = []
    for i in range(0, len(coins), cols):
        chunk = coins[i:i + cols]
        row_str = "  " + "   ".join([f"`{c}`" for c in chunk])
        rows.append(row_str)
    return "\n".join(rows)

def send_telegram(message):
    """ส่งข้อความเข้า Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            payload_plain = {"chat_id": TELEGRAM_CHAT_ID, "text": message.replace("*", "").replace("`", "")}
            requests.post(url, json=payload_plain, timeout=10)
    except Exception as e:
        print(f"Telegram send error: {e}")

def main():
    buy_list = []
    sell_list = []
    unknown_list = []

    for coin in WATCHLIST:
        df = get_candles(coin, interval="4h", limit=120)
        sym = f"{coin}USDT"
        
        if df is None:
            unknown_list.append(sym)
            continue

        status = analyze_4h(df)

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
    print("4H Compact Summary Scanner executed successfully.")

if __name__ == "__main__":
    main()
