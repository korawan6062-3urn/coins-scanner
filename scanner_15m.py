import requests
import pandas as pd
import numpy as np
import time

# --- ข้อมูลการแจ้งเตือน Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- Watchlist คุณภาพสูง 31 ตัว (รวมทองคำ PAXG) เรียง A -> Z ---
WATCHLIST = sorted([
    "AAVE", "ADA", "APT", "AVAX", "BCH",
    "BNB", "BTC", "DOT", "ENA", "ETH",
    "FET", "INJ", "JTO", "KAS", "LDO",
    "LINK", "LTC", "NEAR", "ONDO", "PAXG",
    "PENDLE", "RENDER", "SEI", "SOL", "SUI",
    "TAO", "TIA", "TRX", "UNI", "XLM", "XRP"
])

def get_candles(coin, interval="4h", limit=120):
    """ดึงข้อมูลกราฟจาก Gate.io (หลัก) หรือ KuCoin (สำรอง)"""
    try:
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval={interval}&limit={limit}"
        res = requests.get(url, timeout=5).json()
        if isinstance(res, list) and len(res) >= 60:
            df = pd.DataFrame(res, columns=["time", "volume", "close", "high", "low", "open"])
            df["time"] = df["time"].astype(int)
            df = df.sort_values(by="time").reset_index(drop=True)
            df["close"] = df["close"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            return df
    except Exception:
        pass

    ku_type = "4hour" if interval == "4h" else "15min"
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type={ku_type}&symbol={coin}-USDT"
        res = requests.get(url, timeout=5).json()
        if res.get("code") == "200000" and res.get("data") and len(res["data"]) >= 60:
            raw = res["data"]
            df = pd.DataFrame(raw, columns=["time", "open", "close", "high", "low", "volume", "turnover"])
            df["time"] = df["time"].astype(int)
            df = df.sort_values(by="time").reset_index(drop=True)
            df["close"] = df["close"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            return df
    except Exception:
        pass

    return None

def check_4h_trend(df_4h):
    """เช็กภาพใหญ่ 4H: ต้องชัดเจน (BUY หรือ SELL เท่านั้น)"""
    ema89 = df_4h["close"].ewm(span=89, adjust=False).mean()
    tenkan = (df_4h["high"].rolling(9).max() + df_4h["low"].rolling(9).min()) / 2
    kijun = (df_4h["high"].rolling(26).max() + df_4h["low"].rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((df_4h["high"].rolling(52).max() + df_4h["low"].rolling(52).min()) / 2).shift(26)

    last_close = df_4h["close"].iloc[-1]
    top_kumo = max(span_a.iloc[-1], span_b.iloc[-1])
    bot_kumo = min(span_a.iloc[-1], span_b.iloc[-1])
    last_ema = ema89.iloc[-1]

    if last_close > top_kumo and last_close > last_ema:
        return "BUY"
    elif last_close < bot_kumo and last_close < last_ema:
        return "SELL"
    return "NONE"

def check_15m_trigger(df_15m, trend_4h):
    """
    เช็กจังหวะจบชุดย่อ 15M (เพิ่งเปลี่ยนสถานะเป็น Golden/Death Cross ภายในแท่งล่าสุด)
    """
    df_15m["ema89"] = df_15m["close"].ewm(span=89, adjust=False).mean()

    tenkan = (df_15m["high"].rolling(9).max() + df_15m["low"].rolling(9).min()) / 2
    kijun = (df_15m["high"].rolling(26).max() + df_15m["low"].rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((df_15m["high"].rolling(52).max() + df_15m["low"].rolling(52).min()) / 2).shift(26)

    # Custom MACD (12, 26, SMA 9)
    fast = df_15m["close"].ewm(span=12, adjust=False).mean()
    slow = df_15m["close"].ewm(span=26, adjust=False).mean()
    macd = fast - slow
    signal = macd.rolling(window=9).mean()

    c_prev, c_now = df_15m["close"].iloc[-2], df_15m["close"].iloc[-1]
    ema_now = df_15m["ema89"].iloc[-1]
    top_kumo_now = max(span_a.iloc[-1], span_b.iloc[-1])
    bot_kumo_now = min(span_a.iloc[-1], span_b.iloc[-1])

    m_prev, m_now = macd.iloc[-2], macd.iloc[-1]
    s_prev, s_now = signal.iloc[-2], signal.iloc[-1]

    # เงื่อนไข LONG
    if trend_4h == "BUY":
        is_above_kumo = c_now > top_kumo_now
        is_above_ema = c_now > ema_now
        just_cross_up = (m_prev <= s_prev) and (m_now > s_now)
        if is_above_kumo and is_above_ema and just_cross_up:
            return "TRIGGER_LONG"

    # เงื่อนไข SHORT
    elif trend_4h == "SELL":
        is_below_kumo = c_now < bot_kumo_now
        is_below_ema = c_now < ema_now
        just_cross_down = (m_prev >= s_prev) and (m_now < s_now)
        if is_below_kumo and is_below_ema and just_cross_down:
            return "TRIGGER_SHORT"

    return "NONE"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=10)

def main():
    triggers = []

    for coin in WATCHLIST:
        # 1. เช็ก 4H ด่านแรก
        df_4h = get_candles(coin, interval="4h", limit=90)
        if df_4h is None:
            continue

        trend_4h = check_4h_trend(df_4h)
        if trend_4h == "NONE":
            continue

        # 2. ถ้า 4H ผ่าน เช็ก 15M ด่านสอง
        df_15m = get_candles(coin, interval="15m", limit=90)
        if df_15m is None:
            continue

        signal = check_15m_trigger(df_15m, trend_4h)
        sym = f"{coin}USDT"

        if signal == "TRIGGER_LONG":
            triggers.append(f"🟢 *LONG ENTRY TRIGGER:* `{sym}`\n• *4H Trend:* เหนือเมฆ + เหนือ EMA89\n• *15M Setup:* พ้นเมฆ + MACD เพิ่ง Golden Cross 🔥")
        elif signal == "TRIGGER_SHORT":
            triggers.append(f"🔴 *SHORT ENTRY TRIGGER:* `{sym}`\n• *4H Trend:* ใต้เมฆ + ใต้ EMA89\n• *15M Setup:* หลุดเมฆ + MACD เพิ่ง Death Cross ⚠️")

        time.sleep(0.04)

    # ส่งแจ้งเตือนเฉพาะเมื่อมีจังหวะเข้าทำใหม่จริงๆ เท่านั้น
    if triggers:
        msg = ["⚡️ *[15M A.Aun SETUP TRIGGER]*", "────────────────────────"]
        msg.extend(triggers)
        msg.append("────────────────────────")
        msg.append("👉 *Action:* เปิดกราฟ 5M ดูจังหวะย่อแตะ EMA 21/35 เพื่อกด Order ทันที!")
        send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
