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
    """ดึงข้อมูลแท่งเทียน 15M 300 แท่งตรงจาก Binance API"""
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
    """ตรวจจับ 4 สถานะ MACD บนแท่งปิดสมบูรณ์ล่าสุด (iloc[-2])"""
    try:
        fast = df_15m["close"].ewm(span=12, adjust=False).mean()
        slow = df_15m["close"].ewm(span=26, adjust=False).mean()
        macd = fast - slow
        signal = macd.ewm(span=9, adjust=False).mean()

        m_prev, m_curr = macd.iloc[-3], macd.iloc[-2]
        s_prev, s_curr = signal.iloc[-3], signal.iloc[-2]

        is_golden = (m_prev <= s_prev) and (m_curr > s_curr)
        is_death  = (m_prev >= s_prev) and (m_curr < s_curr)
        is_over0  = (m_prev <= 0) and (m_curr > 0)
        is_under0 = (m_prev >= 0) and (m_curr < 0)

        return is_golden, is_death, is_over0, is_under0
    except Exception:
        return False, False, False, False

def format_grid(coins, cols=3):
    """จัดเรียงรายชื่อเหรียญเป็นแถวละ 3 ตัว ล็อกความกว้างช่องละ 11 ตัวอักษร"""
    if not coins:
        return "  • ไม่มี"
    rows = []
    for i in range(0, len(coins), cols):
        chunk = coins[i:i + cols]
        row_str = "  " + " ".join([f"`{c:<11}`" for c in chunk])
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
        print(f"Telegram error: {e}")

def main():
    golden_list = []
    death_list  = []
    over0_list  = []
    under0_list = []

    for coin in WATCHLIST:
        df = get_binance_candles_15m(coin, limit=300)
        if df is None:
            continue

        is_golden, is_death, is_over0, is_under0 = check_macd_events(df)
        sym = f"{coin}USDT"

        if is_golden:
            golden_list.append(sym)
        if is_death:
            death_list.append(sym)
        if is_over0:
            over0_list.append(sym)
        if is_under0:
            under0_list.append(sym)

        time.sleep(0.03)

    # ส่งเฉพาะเมื่อมีเหรียญเกิดการเปลี่ยนแปลงอย่างน้อย 1 กลุ่ม
    total_events = len(golden_list) + len(death_list) + len(over0_list) + len(under0_list)

    if total_events > 0:
        msg = [
            "⚡️ *[15M MACD EVENT TRIGGER]*",
            "────────────────────────",
            f"🟢 *GOLDEN CROSS [{len(golden_list)}]*",
            format_grid(golden_list, cols=3),
            "",
            f"🔴 *DEATH CROSS [{len(death_list)}]*",
            format_grid(death_list, cols=3),
            "",
            f"🚀 *OVER 0 [{len(over0_list)}]*",
            format_grid(over0_list, cols=3),
            "",
            f"🔻 *UNDER 0 [{len(under0_list)}]*",
            format_grid(under0_list, cols=3),
            "────────────────────────",
            "📌 *Next Step:* เปิด 5M ดู Dashboard พัด EMA + รอย่อแตะ EMA 21/35"
        ]
        send_telegram("\n".join(msg))
        print(f"Reported {total_events} events successfully.")
    else:
        print("No new 15M MACD events at this bar.")

if __name__ == "__main__":
    main()
