import requests
import pandas as pd
import numpy as np

# --- 1. ตั้งค่า Telegram (ใส่ Token และ Chat ID เรียบร้อยแล้ว) ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- 2. รายชื่อ 10 เหรียญหลัก ---
COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "NEAR", "SUI"]

def get_4h_data(coin):
    # ดึงข้อมูลผ่าน Public API ที่ไม่ติดบล็อก IP บน GitHub Actions / Cloud
    try:
        # ช่องทางที่ 1: KuCoin API
        url = f"https://api.kucoin.com/api/v1/market/candles?type=4hour&symbol={coin}-USDT"
        res = requests.get(url, timeout=10).json()
        if res.get("code") == "200000" and res.get("data"):
            raw = res["data"]
            # KuCoin: [time, open, close, high, low, volume, turnover]
            df = pd.DataFrame(raw, columns=["time", "open", "close", "high", "low", "volume", "turnover"])
            df["time"] = df["time"].astype(int)
            df = df.sort_values(by="time").reset_index(drop=True)
            df["close"] = df["close"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            return df
    except Exception:
        pass

    # ช่องทางที่ 2 (สำรอง): Gate.io API
    url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval=4h&limit=150"
    res = requests.get(url, timeout=10).json()
    # Gate.io: [timestamp, volume, close, high, low, open]
    df = pd.DataFrame(res, columns=["time", "volume", "close", "high", "low", "open"])
    df["time"] = df["time"].astype(int)
    df = df.sort_values(by="time").reset_index(drop=True)
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    return df

def check_setup(df):
    # คำนวณ EMA 89
    df["ema89"] = df["close"].ewm(span=89, adjust=False).mean()

    # คำนวณ Ichimoku Cloud (9, 26, 52)
    tenkan = (df["high"].rolling(9).max() + df["low"].rolling(9).min()) / 2
    kijun = (df["high"].rolling(26).max() + df["low"].rolling(26).min()) / 2
    span_a = (tenkan + kijun) / 2
    span_b = (df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2

    # ดึงขอบเมฆปัจจุบัน (ย้อนหลัง 26 แท่ง)
    kumo_a = span_a.shift(26)
    kumo_b = span_b.shift(26)

    last_close = df["close"].iloc[-1]
    last_ema89 = df["ema89"].iloc[-1]
    top_kumo = max(kumo_a.iloc[-1], kumo_b.iloc[-1])
    bot_kumo = min(kumo_a.iloc[-1], kumo_b.iloc[-1])

    # เงื่อนไขการตัดสินใจตามระบบ A.Aun
    if last_close > top_kumo and last_close > last_ema89:
        return "🟢 LONG (เหนือเมฆ + เหนือ EMA89)"
    elif last_close < bot_kumo and last_close < last_ema89:
        return "🔴 SHORT (ใต้เมฆ + ใต้ EMA89)"
    elif bot_kumo <= last_close <= top_kumo:
        return "⚪ NO TRADE (อยู่ในเนื้อเมฆ)"
    else:
        return "⚪ NO TRADE (ขัดแย้งกับ EMA89)"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=10)

def main():
    report = ["📊 *สรุปผลสแกน 4H ประจำวัน (A.Aun Setup)*", "────────────────────────"]
    for coin in COINS:
        sym = f"{coin}USDT"
        try:
            df = get_4h_data(coin)
            status = check_setup(df)
            report.append(f"*{sym}* : {status}")
        except Exception:
            report.append(f"*{sym}* : ⚠️ ดึงข้อมูลล้มเหลว")

    report.append("────────────────────────")
    report.append("💡 *Action:* เหรียญที่ผ่านเกณฑ์ ให้เปิด 15M/5M รอย่อ Retest เข้าเทรด")
    
    final_message = "\n".join(report)
    send_telegram(final_message)

if __name__ == "__main__":
    main()
