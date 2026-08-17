import os
import sys
import requests
import pandas as pd
import numpy as np
import time

# --- 1. ดึง Token และ Chat ID จาก GitHub Secrets ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_candles_4h(symbol, is_futures=False, limit=200):
    """ดึงแท่งเทียน 4H จาก API พร้อม Multi-Endpoint สำรอง"""
    if is_futures:
        endpoints = [
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=4h&limit={limit}",
            f"https://fapi.binance.vision/fapi/v1/klines?symbol={symbol}&interval=4h&limit={limit}"
        ]
    else:
        endpoints = [
            f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=4h&limit={limit}",
            f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=4h&limit={limit}"
        ]

    for url in endpoints:
        try:
            res = requests.get(url, headers=HEADERS, timeout=10).json()
            if isinstance(res, list) and len(res) >= 100:
                df = pd.DataFrame(res, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades", "taker_buy_base",
                    "taker_buy_quote", "ignore"
                ])
                for col in ["open", "high", "low", "close", "open_time"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df.sort_values(by="open_time").dropna().reset_index(drop=True)
        except Exception as e:
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
    except Exception as e:
        print(f"Ichimoku calculation error: {e}")
        return "UNKNOWN", 0.0, 0.0

def evaluate_market_regime(btc_status, btcd_status):
    """วิเคราะห์ความสัมพันธ์ Matrix BTC vs BTC.D (9 สภาวะ)"""
    if btc_status == "BULLISH" and btcd_status == "BEARISH":
        title = "🚀 FULL ALTCOIN SEASON"
        desc = "BTC ขาขึ้น แต่ส่วนแบ่งตลาดลดลง เงินไหลเข้าเก็งกำไรใน Altcoins รุนแรง"
        bias = "เน้นเปิด LONG เหรียญ Altcoins (เลือกตัว 15M Over 0 / Golden Cross)"

    elif btc_status == "BULLISH" and btcd_status == "SIDEWAY":
        title = "🔄 SELECTIVE ALTCOIN ROTATION"
        desc = "BTC ขาขึ้น ส่วนแบ่งตลาดทรงตัว เงินหมุนเข้าเก็งกำไรในเหรียญลูกทีละกลุ่ม"
        bias = "เลือก Long เหรียญที่มีสัญญาณ 4H BUY เหนือเมฆ"

    elif btc_status == "BULLISH" and btcd_status == "BULLISH":
        title = "👑 BTC SOLO RUN / SURGE"
        desc = "เงินดูดเข้า BTC ตัวเดียว Altcoins ส่วนใหญ่ถูกดูดสภาพคล่องและขึ้นช้า"
        bias = "โฟกัสเทรด BTC / ชะลอการไล่ราคา Altcoins"

    elif btc_status == "BEARISH" and btcd_status == "BULLISH":
        title = "🩸 ALTCOIN BLEEDING / DANGER ZONE"
        desc = "BTC ย่อตัว และส่วนแบ่งตลาดพุ่ง เหรียญลูกจะร่วงแรงเป็น 2-3 เท่า"
        bias = "หาจังหวะ SHORT Altcoins หรือ ถือ Cash 100% (ห้ามช้อนซื้อ)"

    elif btc_status == "BEARISH" and btcd_status == "BEARISH":
        title = "💸 TOTAL MARKET OUTFLOW / CRASH"
        desc = "เงินไหลออกจากตลาดคริปโตทั้งหมดเข้า Stablecoin หรือ Fiat"
        bias = "เน้นถือเงินสด หรือเล่นฝั่ง Short ภาพรวม"

    elif btc_status == "SIDEWAY" and btcd_status == "BEARISH":
        title = "🪙 ALTCOIN ACCUMULATION"
        desc = "BTC ไซด์เวย์นิ่ง แต่ Dominance ไหลลง มีการสะสมของในเหรียญลูก"
        bias = "ดักเก็บเหรียญต้นรอบที่เพิ่งเกิด Golden Cross บน 15M"

    else:
        title = "⚪️ CHOPPY / NEUTRAL MARKET"
        desc = "ตลาดพักฐาน ไร้ทิศทางชัดเจนทั้ง BTC และ Dominance"
        bias = "ลดขนาดพอร์ต (Position Size) และรอให้เลือกทางชัดเจน"

    return title, desc, bias

def send_telegram(message):
    """ส่งข้อความเข้า Telegram พร้อมระบบ Fallback Plain Text"""
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
    print("Running Market Flow Scanner (BTC + BTC.D Engine)...")

    # ดึงข้อมูล 4H ของ BTCUSDT (Spot) และ BTCDOMUSDT (Dominance Index)
    df_btc = get_candles_4h("BTCUSDT", is_futures=False, limit=200)
    df_btcdom = get_candles_4h("BTCDOMUSDT", is_futures=True, limit=200)

    if df_btc is None:
        print("Error: Failed to fetch BTCUSDT candles")
        return
    if df_btcdom is None:
        print("Error: Failed to fetch BTCDOMUSDT candles")
        return

    btc_status, btc_price, btc_chg = analyze_ichimoku_cloud(df_btc)
    btcd_status, btcd_val, btcd_chg = analyze_ichimoku_cloud(df_btcdom)

    title, desc, bias = evaluate_market_regime(btc_status, btcd_status)

    def icon(s):
        return "🟢" if s == "BULLISH" else ("🔴" if s == "BEARISH" else "⚪️")

    msg = [
        "🌐 *[MARKET REGIME & MONEY FLOW 4H]*",
        "────────────────────────",
        "📊 *4H DATA OVERVIEW:*",
        f"  • BTC Price : `${btc_price:,.1f}` ({btc_chg:+.2f}%) | {icon(btc_status)} *{btc_status}*",
        f"  • BTC.D Dom : `{btcd_val:,.1f}` ({btcd_chg:+.2f}%) | {icon(btcd_status)} *{btcd_status}*",
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
