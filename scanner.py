import requests
import pandas as pd
import numpy as np

# --- 1. ใส่ข้อมูล Telegram ของคุณตรงนี้ ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- 2. รายชื่อ 10 เหรียญ ---
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "NEARUSDT", "SUIUSDT"
]

def get_4h_data(symbol):
    # ดึงข้อมูลจาก Bybit Futures API (ไม่บล็อก IP บน Cloud / GitHub Actions)
    url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=240&limit=150"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers, timeout=10).json()
    
    if "result" not in res or "list" not in res["result"] or not res["result"]["list"]:
        raise Exception("No data returned")
        
    raw_data = res["result"]["list"]
    # Bybit ส่งข้อมูลแท่งล่าสุดขึ้นก่อน จึงต้องกลับลำดับแถว
    df = pd.DataFrame(raw_data, columns=[
        "startTime", "open", "high", "low", "close", "volume", "turnover"
    ]).iloc[::-1].reset_index(drop=True)
    
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    return df

def check_setup(df):
    df["ema89"] = df["close"].ewm(span=89, adjust=False).mean()

    # Ichimoku Cloud (9, 26, 52)
    tenkan = (df["high"].rolling(9).max() + df["low"].rolling(9).min()) / 2
    kijun = (df["high"].rolling(26).max() + df["low"].rolling(26).min()) / 2
    span_a = (tenkan + kijun) / 2
    span_b = (df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2

    kumo_a = span_a.shift(26)
    kumo_b = span_b.shift(26)

    last_close = df["close"].iloc[-1]
    last_ema89 = df["ema89"].iloc[-1]
    top_kumo = max(kumo_a.iloc[-1], kumo_b.iloc[-1])
    bot_kumo = min(kumo_a.iloc[-1], kumo_b.iloc[-1])

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
    for sym in SYMBOLS:
        try:
            df = get_4h_data(sym)
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
