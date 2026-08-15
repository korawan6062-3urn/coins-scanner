import requests
import pandas as pd
import numpy as np
import time

# --- ข้อมูลการแจ้งเตือน Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- Watchlist 31 ตัว (A -> Z) ---
WATCHLIST = sorted([
    "AAVE", "ADA", "APT", "AVAX", "BCH",
    "BNB", "BTC", "DOT", "ENA", "ETH",
    "FET", "INJ", "JTO", "KAS", "LDO",
    "LINK", "LTC", "NEAR", "ONDO", "PAXG",
    "PENDLE", "RENDER", "SEI", "SOL", "SUI",
    "TAO", "TIA", "TRX", "UNI", "XLM", "XRP"
])

def get_candles(coin, interval="4h", limit=120):
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

def detect_macd_divergence(df, lookback=35, pivot_period=3):
    """ตรวจจับ Regular Divergence (Custom MACD 12, 26, SMA 9)"""
    try:
        fast_ema = df["close"].ewm(span=12, adjust=False).mean()
        slow_ema = df["close"].ewm(span=26, adjust=False).mean()
        macd = fast_ema - slow_ema

        sub_df = df.tail(lookback).copy().reset_index(drop=True)
        sub_macd = macd.tail(lookback).values
        highs = sub_df["high"].values
        lows = sub_df["low"].values
        n = len(sub_df)

        ph_idx = [i for i in range(pivot_period, n - pivot_period) if highs[i] == max(highs[i - pivot_period:i + pivot_period + 1])]
        pl_idx = [i for i in range(pivot_period, n - pivot_period) if lows[i] == min(lows[i - pivot_period:i + pivot_period + 1])]

        if len(ph_idx) >= 2:
            p1, p2 = ph_idx[-2], ph_idx[-1]
            if (n - 1 - p2) <= 5 and highs[p2] > highs[p1] and sub_macd[p2] < sub_macd[p1]:
                return "BEAR_DIV"

        if len(pl_idx) >= 2:
            p1, p2 = pl_idx[-2], pl_idx[-1]
            if (n - 1 - p2) <= 5 and lows[p2] < lows[p1] and sub_macd[p2] > sub_macd[p1]:
                return "BULL_DIV"
    except Exception:
        pass

    return "NONE"

def check_4h_trend(df_4h):
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
    df_15m["ema89"] = df_15m["close"].ewm(span=89, adjust=False).mean()
    tenkan = (df_15m["high"].rolling(9).max() + df_15m["low"].rolling(9).min()) / 2
    kijun = (df_15m["high"].rolling(26).max() + df_15m["low"].rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((df_15m["high"].rolling(52).max() + df_15m["low"].rolling(52).min()) / 2).shift(26)

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

    if trend_4h == "BUY":
        if c_now > top_kumo_now and c_now > ema_now and (m_prev <= s_prev) and (m_now > s_now):
            return "TRIGGER_LONG"
    elif trend_4h == "SELL":
        if c_now < bot_kumo_now and c_now < ema_now and (m_prev >= s_prev) and (m_now < s_now):
            return "TRIGGER_SHORT"

    return "NONE"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=10)

def main():
    triggers = []

    for coin in WATCHLIST:
        df_4h = get_candles(coin, interval="4h", limit=90)
        if df_4h is None:
            continue

        trend_4h = check_4h_trend(df_4h)
        if trend_4h == "NONE":
            continue

        df_15m = get_candles(coin, interval="15m", limit=90)
        if df_15m is None:
            continue

        signal = check_15m_trigger(df_15m, trend_4h)
        if signal == "NONE":
            continue

        # ตรวจสอบ Divergence ประกอบการตัดสินใจ
        div_4h = detect_macd_divergence(df_4h)
        div_15m = detect_macd_divergence(df_15m)

        sym = f"{coin}USDT"
        warnings = []

        if signal == "TRIGGER_LONG":
            if div_4h == "BEAR_DIV":
                warnings.append("⚠️ 4H มี Bear Div (ระวังจบรอบ)")
            if div_15m == "BEAR_DIV":
                warnings.append("⚠️ 15M มี Bear Div (ระวังพักลึก)")
            
            warn_text = f"\n• *คำเตือน:* {', '.join(warnings)}" if warnings else "\n• *Divergence:* ปลอดภัย (ไม่มีสัญญาณขัดแย้ง)"
            triggers.append(
                f"🟢 *LONG ENTRY TRIGGER:* `{sym}`\n"
                f"• *4H Trend:* เหนือเมฆ + เหนือ EMA89\n"
                f"• *15M Setup:* พ้นเมฆ + MACD เพิ่ง Golden Cross 🔥"
                f"{warn_text}"
            )

        elif signal == "TRIGGER_SHORT":
            if div_4h == "BULL_DIV":
                warnings.append("🔥 4H มี Bull Div (ระวังเด้งสวน)")
            if div_15m == "BULL_DIV":
                warnings.append("🔥 15M มี Bull Div (ระวังดีดแรง)")

            warn_text = f"\n• *คำเตือน:* {', '.join(warnings)}" if warnings else "\n• *Divergence:* ปลอดภัย (ไม่มีสัญญาณขัดแย้ง)"
            triggers.append(
                f"🔴 *SHORT ENTRY TRIGGER:* `{sym}`\n"
                f"• *4H Trend:* ใต้เมฆ + ใต้ EMA89\n"
                f"• *15M Setup:* หลุดเมฆ + MACD เพิ่ง Death Cross ⚠️"
                f"{warn_text}"
            )

        time.sleep(0.04)

    if triggers:
        msg = ["⚡️ *[15M A.Aun SETUP TRIGGER]*", "────────────────────────"]
        msg.extend(triggers)
        msg.append("────────────────────────")
        msg.append("👉 *Action:* เปิด 5M รอย่อ Retest EMA 21/35 (หากติดคำเตือน ให้ลดขนาดไม้ลงครึ่งหนึ่ง)")
        send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
