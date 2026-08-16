import requests
import pandas as pd
import numpy as np
import time

# --- 1. ข้อมูลการแจ้งเตือน Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- 2. Top 31 Curated Watchlist (รวม PAXG ทองคำ) เรียง A -> Z ---
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

def detect_macd_divergence(df, lookback=100):
    """ตรวจจับ Macro Divergence ทั้งใน 4H และ 15M"""
    try:
        fast_ema = df["close"].ewm(span=12, adjust=False).mean()
        slow_ema = df["close"].ewm(span=26, adjust=False).mean()
        macd = fast_ema - slow_ema

        sub_df = df.tail(lookback).copy().reset_index(drop=True)
        sub_macd = macd.tail(lookback).values
        highs = sub_df["high"].values
        lows = sub_df["low"].values
        n = len(sub_df)

        if n < 40:
            return "NONE"

        # Bullish Divergence
        curr_price = lows[-1]
        curr_macd = sub_macd[-1]

        past_window_macd = sub_macd[max(0, n - 80): n - 10]
        past_window_lows = lows[max(0, n - 80): n - 10]

        if len(past_window_macd) > 0:
            min_past_macd = np.min(past_window_macd)
            idx_min_macd = np.argmin(past_window_macd)
            price_at_min_macd = past_window_lows[idx_min_macd]

            if curr_price <= price_at_min_macd and curr_macd > (min_past_macd * 0.75) and min_past_macd < 0:
                return "BULL_DIV"

        # Bearish Divergence
        past_window_highs = highs[max(0, n - 80): n - 10]

        if len(past_window_macd) > 0:
            max_past_macd = np.max(past_window_macd)
            idx_max_macd = np.argmax(past_window_macd)
            price_at_max_macd = past_window_highs[idx_max_macd]

            if curr_price >= price_at_max_macd and curr_macd < (max_past_macd * 0.75) and max_past_macd > 0:
                return "BEAR_DIV"

    except Exception:
        pass

    return "NONE"

def check_4h_trend(df_4h):
    """ตรวจทิศทางหลัก 4H (ต้องพ้นเมฆ และยืนเหนือ/ใต้ EMA89)"""
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
    """ตรวจจังหวะจบย่อ 15M (เพิ่งตัด Golden/Death Cross สดๆ)"""
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
        # 1. เช็ก 4H ด่านแรก
        df_4h = get_candles(coin, interval="4h", limit=120)
        if df_4h is None:
            continue

        trend_4h = check_4h_trend(df_4h)
        if trend_4h == "NONE":
            continue

        # 2. เช็ก 15M ด่านสอง
        df_15m = get_candles(coin, interval="15m", limit=120)
        if df_15m is None:
            continue

        signal = check_15m_trigger(df_15m, trend_4h)
        if signal == "NONE":
            continue

        # 3. ตรวจสอบ Divergence ทั้ง 4H และ 15M
        div_4h = detect_macd_divergence(df_4h)
        div_15m = detect_macd_divergence(df_15m)
        sym = f"{coin}USDT"

        if signal == "TRIGGER_LONG":
            warnings = []
            if div_4h == "BEAR_DIV":
                warnings.append("4H มี Bear Div")
            if div_15m == "BEAR_DIV":
                warnings.append("15M มี Bear Div")

            if warnings:
                risk_status = f"⚠️ *เตือนเสี่ยง:* {', '.join(warnings)}"
                plan = "⚡️ *คำแนะนำ:* ลดขนาดไม้เหลือ 50% / ปิด TP1 ทันที"
            else:
                risk_status = "✅ *ความเสี่ยง:* ปลอดภัย (ไม่มี Divergence ขวาง)"
                plan = "🚀 *คำแนะนำ:* ไม้ขนาดเต็ม 100% / รันเทรนด์ได้"

            card = (
                f"🟢 *LONG ENTRY TRIGGER:* `{sym}`\n"
                f"• โครงสร้าง: เหนือเมฆ 4H + 15M Golden Cross\n"
                f"• {risk_status}\n"
                f"• {plan}"
            )
            triggers.append(card)

        elif signal == "TRIGGER_SHORT":
            warnings = []
            if div_4h == "BULL_DIV":
                warnings.append("4H มี Bull Div")
            if div_15m == "BULL_DIV":
                warnings.append("15M มี Bull Div")

            if warnings:
                risk_status = f"🔥 *เตือนเสี่ยง:* {', '.join(warnings)} (ระวังเด้ง)"
                plan = "⚡️ *คำแนะนำ:* ลดขนาดไม้เหลือ 50% / บังคับเก็บกำไร TP1"
            else:
                risk_status = "✅ *ความเสี่ยง:* ปลอดภัย (ไม่มี Divergence ขวาง)"
                plan = "🚀 *คำแนะนำ:* ไม้ขนาดเต็ม 100% / รันเทรนด์ได้"

            card = (
                f"🔴 *SHORT ENTRY TRIGGER:* `{sym}`\n"
                f"• โครงสร้าง: ใต้เมฆ 4H + 15M Death Cross\n"
                f"• {risk_status}\n"
                f"• {plan}"
            )
            triggers.append(card)

        time.sleep(0.04)

    if triggers:
        msg = ["⚡️ *[15M A.Aun SETUP TRIGGER]*", "────────────────────────"]
        msg.extend(triggers)
        msg.append("────────────────────────")
        msg.append("👉 *Next Step:* เปิดกราฟ 5M ดูจังหวะ Retest เส้น EMA 21/35 แล้วเข้าตามแผน")
        send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
