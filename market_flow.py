import os
import sys
import requests
import pandas as pd
import numpy as np
import time

# --- 1. ดึง Token และ Chat ID จาก GitHub Secrets ผ่าน Environment Variables ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def get_binance_spot_candles(symbol, interval="4h", limit=200):
    """ดึงข้อมูล Spot ตรงจาก Binance Vision (แกนเดียวกับ 15M)"""
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
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

def analyze_ichimoku_cloud(df):
    """คำนวณเมฆ Ichimoku บนแท่ง 4H ปิดสมบูรณ์ล่าสุด (iloc[-2])"""
    try:
        tenkan = (df["high"].rolling(9).max() + df["low"].rolling(9).min()) / 2
        kijun = (df["high"].rolling(26).max() + df["low"].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2).shift(26)

        close_val = df["close"].iloc[-2]
        span_a_val = span_a.iloc[-2]
        span_b_val = span_b.iloc[-2]

        top_kumo = max(span_a_val, span_b_val)
        bot_kumo = min(span_a_val, span_b_val)

        if close_val > top_kumo:
            status = "BULLISH"
        elif close_val < bot_kumo:
            status = "BEARISH"
        else:
            status = "SIDEWAY"

        prev_close = df["close"].iloc[-3]
        change_pct = ((close_val - prev_close) / prev_close) * 100

        return status, close_val, change_pct
    except Exception:
        return "UNKNOWN", 0.0, 0.0

def evaluate_regime(btc_status, ethbtc_status):
    """วิเคราะห์สภาวะตลาดตามกระแสเงินทุน BTC vs Altcoins (ETH/BTC)"""
    if btc_status == "BULLISH" and ethbtc_status == "BULLISH":
        title = "🚀 FULL ALTCOIN SEASON"
        desc = "BTC ขาขึ้น และเหรียญลูก (ETH/BTC) แข็งแกร่งกว่า เงินล้นเข้า Altcoins"
        bias = "เน้นเปิด LONG เหรียญ Altcoins ตามสัญญาณ 15M"

    elif btc_status == "BULLISH" and ethbtc_status == "BEARISH":
        title = "👑 BTC SOLO RUN"
        desc = "BTC ขึ้นตัวเดียว แต่เหรียญลูกอ่อนแอ เงินถูกดูดกลับเข้าเหรียญแม่"
        bias = "โฟกัสเทรด BTC / ชะลอการเปิด Long Altcoins"

    elif btc_status == "BEARISH" and ethbtc_status == "BEARISH":
        title = "🩸 ALTCOIN BLEEDING / DANGER"
        desc = "BTC ย่อตัว และเหรียญลูกโดนเทหนักกว่าปกติ (ความเสี่ยงสูงมาก)"
        bias = "หาจังหวะ SHORT Altcoins หรือ ถือ Cash 100%"

    elif btc_status == "BEARISH" and ethbtc_status == "BULLISH":
        title = "🛡 ALTCOIN RESISTANCE"
        desc = "BTC อ่อนแรง แต่เหรียญลูกบางกลุ่มยังฝืนตลาดและมีแรงพยุง"
        bias = "เล่นสั้นเฉพาะเหรียญ Top ที่ยืนเหนือเมฆ 4H"

    elif btc_status == "SIDEWAY" and ethbtc_status == "BULLISH":
        title = "🔄 ALTCOIN ROTATION"
        desc = "BTC พักตัวนิ่ง เงินหมุนเวียนเก็งกำไรในเหรียญ Altcoins ต้นรอบ"
        bias = "ดักเข้าเหรียญ 15M Golden Cross / Over 0"

    else:
        title = "⚪️ CHOPPY / NEUTRAL MARKET"
        desc = "ตลาดพักฐาน ไร้ทิศทางชัดเจนทั้ง BTC และเหรียญลูก"
        bias = "ลด Position Size และรอสัญญาณเลือกทาง"

    return title, desc, bias

def send_telegram(message):
    """ส่งข้อความเข้า Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in Environment Secrets.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            plain_text = message.replace("*", "").replace("`", "").replace("_", "")
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain_text}, timeout=10)
        print("Telegram message sent successfully.")
    except Exception as e:
        print(f"Telegram Exception: {e}")

def main():
    print("Running Market Flow Scanner (Spot Vision Engine)...")

    # ดึงข้อมูล Spot (BTCUSDT และ ETHBTC)
    df_btc = get_binance_spot_candles("BTCUSDT", interval="4h", limit=200)
    df_ethbtc = get_binance_spot_candles("ETHBTC", interval="4h", limit=200)

    if df_btc is None or df_ethbtc is None:
        print("Error: Could not retrieve Binance Spot candles")
        return

    btc_status, btc_price, btc_chg = analyze_ichimoku_cloud(df_btc)
    ethbtc_status, ethbtc_price, ethbtc_chg = analyze_ichimoku_cloud(df_ethbtc)

    title, desc, bias = evaluate_regime(btc_status, ethbtc_status)

    def icon(s):
        return "🟢" if s == "BULLISH" else ("🔴" if s == "BEARISH" else "⚪️")

    msg = [
        "🌐 *[MARKET REGIME & MONEY FLOW 4H]*",
        "────────────────────────",
        "📊 *4H DATA OVERVIEW (Spot)*",
        f"  • BTC Price   : `${btc_price:,.1f}` ({btc_chg:+.2f}%) | {icon(btc_status)} *{btc_status}*",
        f"  • ETH/BTC Ratio: `{ethbtc_price:.5f}` ({ethbtc_chg:+.2f}%) | {icon(ethbtc_status)} *{ethbtc_status}*",
        "────────────────────────",
        f"🎯 *MARKET STATE:*\n  *{title}*",
        f"  {desc}",
        "",
        f"💡 *TRADING PLAYBOOK:*\n  • {bias}",
        "────────────────────────",
        "📌 *เกณฑ์การคำนวณ:* Ichimoku Cloud (9, 26, 52, 26) บนแท่ง 4H ปิดสมบูรณ์"
    ]

    send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
