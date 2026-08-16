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
    """ดึงข้อมูลแท่งเทียน"""
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

    ku_type = "4hour" if interval == "4h" else "15min"
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type={ku_type}&symbol={coin}-USDT"
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

def check_4h_trend(df_4h):
    """ตรวจทิศทางหลัก 4H"""
    try:
        ema89 = df_4h["close"].ewm(span=89, adjust=False).mean()
        tenkan = (df_4h["high"].rolling(9).max() + df_4h["low"].rolling(9).min()) / 2
        kijun = (df_4h["high"].rolling(26).max() + df_4h["low"].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df_4h["high"].rolling(52).max() + df_4h["low"].rolling(52).min()) / 2).shift(26)

        last_close = df_4h["close"].iloc[-1]
        top_kumo = max(span_a.iloc[-1], span_b.iloc[-1])
        bot_kumo = min(span_a.iloc[-1], span_b.iloc[-1])
        last_ema = ema89.iloc[-1]

        if pd.isna(top_kumo) or pd.isna(bot_kumo):
            top_kumo = last_ema
            bot_kumo = last_ema

        if last_close > top_kumo and last_close > last_ema:
            return "BUY"
        elif last_close < bot_kumo and last_close < last_ema:
            return "SELL"
    except Exception:
        pass

    return "NONE"

def check_15m_trigger(df_15m, trend_4h):
    """ตรวจจังหวะจบย่อ 15M: BUY < 0 / SELL > 0"""
    try:
        fast = df_15m["close"].ewm(span=12, adjust=False).mean()
        slow = df_15m["close"].ewm(span=26, adjust=False).mean()
        macd = fast - slow
        signal = macd.rolling(window=9).mean()

        m_prev, m_now = macd.iloc[-2], macd.iloc[-1]
        s_prev, s_now = signal.iloc[-2], signal.iloc[-1]

        if trend_4h == "BUY":
            if (m_prev <= s_prev) and (m_now > s_now) and (m_now < 0):
                return "TRIGGER_LONG"
        elif trend_4h == "SELL":
            if (m_prev >= s_prev) and (m_now < s_now) and (m_now > 0):
                return "TRIGGER_SHORT"
    except Exception:
        pass

    return "NONE"

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
    triggers = []

    for coin in WATCHLIST:
        df_4h = get_candles(coin, interval="4h", limit=120)
        if df_4h is None:
            continue

        trend_4h = check_4h_trend(df_4h)
        if trend_4h == "NONE":
            continue

        df_15m = get_candles(coin, interval="15m", limit=120)
        if df_15m is None:
            continue

        signal = check_15m_trigger(df_15m, trend_4h)
        if signal == "NONE":
            continue

        sym = f"{coin}USDT"

        if signal == "TRIGGER_LONG":
            card = (
                f"🟢 *LONG ENTRY TRIGGER:* `{sym}`\n"
                f"• *โครงสร้าง:* เหนือเมฆ 4H + 15M Golden Cross\n"
                f"• *MACD Zone:* ตัดขึ้นในโซน *MACD น้อยกว่า 0* (จบการย่อพักตัว ✅)"
            )
            triggers.append(card)

        elif signal == "TRIGGER_SHORT":
            card = (
                f"🔴 *SHORT ENTRY TRIGGER:* `{sym}`\n"
                f"• *โครงสร้าง:* ใต้เมฆ 4H + 15M Death Cross\n"
                f"• *MACD Zone:* ตัดลงในโซน *MACD มากกว่า 0* (จบการเด้งทดสอบ ✅)"
            )
            triggers.append(card)

        time.sleep(0.04)

    if triggers:
        msg = ["⚡️ *[15M A.Aun SETUP TRIGGER]*", "────────────────────────"]
        msg.extend(triggers)
        msg.append("────────────────────────")
        msg.append("🎯 *Checklist เข้าไม้หน้างาน 5M (A.Aun Execution):*")
        msg.append("1. *เปิด 5M เช็กการเรียงเส้น EMA ทันที:*")
        msg.append("   • ฝั่ง BUY: ต้องเรียง *EMA 21 > 35 > 89* (พัดขึ้น)")
        msg.append("   • ฝั่ง SELL: ต้องเรียง *EMA 21 < 35 < 89* (พัดทิ่มลง)")
        msg.append("2. *จังหวะเข้า:* รอแท่ง 5M ย่อทดสอบโซนเส้น EMA 21 หรือ 35 (ห้ามกดไล่ราคา)")
        msg.append("3. *เช็กตาเปล่า:* สังเกต Divergence หน้างานด้วยตัวเอง (หากมี Divergence ให้ลดขนาดออเดอร์ หรือ เลี่ยงการเทรด)")
        msg.append("4. *ตั้งความเสี่ยง:* วาง SL เหนือ/ใต้ Swing 15M ล่าสุด และตั้ง TP ขั้นต่ำ *R:R 1:1.5 – 1:2*")
        send_telegram("\n".join(msg))
    else:
        print("No 15M triggers found at this moment.")

    print("15M Scanner completed.")

if __name__ == "__main__":
    main()
