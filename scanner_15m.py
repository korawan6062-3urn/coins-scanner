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
    """ดึงข้อมูลแท่งเทียนจาก Gate.io หรือ KuCoin"""
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
    """ตรวจทิศทาง 4H กรองเฉพาะเมฆ Ichimoku เท่านั้น (ไม่บล็อก EMA89)"""
    try:
        tenkan = (df_4h["high"].rolling(9).max() + df_4h["low"].rolling(9).min()) / 2
        kijun = (df_4h["high"].rolling(26).max() + df_4h["low"].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df_4h["high"].rolling(52).max() + df_4h["low"].rolling(52).min()) / 2).shift(26)

        last_close = df_4h["close"].iloc[-1]
        top_kumo = max(span_a.iloc[-1], span_b.iloc[-1])
        bot_kumo = min(span_a.iloc[-1], span_b.iloc[-1])

        if pd.isna(top_kumo) or pd.isna(bot_kumo):
            return "NONE"

        # 4H เหนือเมฆ = อนุญาต BUY / 4H ใต้เมฆ = อนุญาต SELL
        if last_close > top_kumo:
            return "BUY"
        elif last_close < bot_kumo:
            return "SELL"
    except Exception:
        pass

    return "NONE"

def check_15m_trigger(df_15m, trend_4h):
    """ตรวจจุดตัด MACD 15M (Signal Line EMA 9 ตรง TradingView)"""
    try:
        fast = df_15m["close"].ewm(span=12, adjust=False).mean()
        slow = df_15m["close"].ewm(span=26, adjust=False).mean()
        macd = fast - slow
        signal = macd.ewm(span=9, adjust=False).mean()

        crossover_now  = (macd.iloc[-2] <= signal.iloc[-2]) and (macd.iloc[-1] > signal.iloc[-1])
        crossover_prev = (macd.iloc[-3] <= signal.iloc[-3]) and (macd.iloc[-2] > signal.iloc[-2])

        crossunder_now  = (macd.iloc[-2] >= signal.iloc[-2]) and (macd.iloc[-1] < signal.iloc[-1])
        crossunder_prev = (macd.iloc[-3] >= signal.iloc[-3]) and (macd.iloc[-2] < signal.iloc[-2])

        # BUY: 4H เหนือเมฆ + 15M ตัดขึ้นใต้เส้น 0
        if trend_4h == "BUY":
            if (crossover_now and macd.iloc[-1] < 0) or (crossover_prev and macd.iloc[-2] < 0):
                return "TRIGGER_LONG"

        # SELL: 4H ใต้เมฆ + 15M ตัดลงเหนือเส้น 0
        elif trend_4h == "SELL":
            if (crossunder_now and macd.iloc[-1] > 0) or (crossunder_prev and macd.iloc[-2] > 0):
                return "TRIGGER_SHORT"

    except Exception as e:
        print(f"15M Trigger error: {e}")

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
        print(f"Telegram send error: {e}")

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
                f"• *MACD Zone:* ตัดขึ้นในโซน *MACD < 0* (จบการย่อพักตัว ✅)"
            )
            triggers.append(card)

        elif signal == "TRIGGER_SHORT":
            card = (
                f"🔴 *SHORT ENTRY TRIGGER:* `{sym}`\n"
                f"• *โครงสร้าง:* ใต้เมฆ 4H + 15M Death Cross\n"
                f"• *MACD Zone:* ตัดลงในโซน *MACD > 0* (จบการเด้งทดสอบ ✅)"
            )
            triggers.append(card)

        time.sleep(0.04)

    if triggers:
        msg = ["⚡️ *[15M A.Aun SETUP TRIGGER]*", "────────────────────────"]
        msg.extend(triggers)
        msg.append("────────────────────────")
        msg.append("🎯 *Checklist เข้าไม้หน้างาน 5M:*")
        msg.append("1. *เปิด 5M ดู Dashboard:* ต้องขึ้นสถานะ UP TREND หรือ DOWN TREND")
        msg.append("2. *จังหวะเข้า:* รอแท่ง 5M สัมผัสแนวรับ/ต้าน EMA 21 หรือ 35 (ห้ามกดไล่ราคา)")
        msg.append("3. *เช็กตาเปล่า:* สังเกตระยะห่าง EMA 89 และ Regular Divergence")
        msg.append("4. *ตั้งความเสี่ยง:* วาง SL เหนือ/ใต้ Swing 15M ล่าสุด และตั้ง TP ขั้นต่ำ *R:R 1:1.5 – 1:2*")
        send_telegram("\n".join(msg))
    else:
        print("No 15M triggers found at this moment.")

    print("15M Scanner executed successfully.")

if __name__ == "__main__":
    main()
