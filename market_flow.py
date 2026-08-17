import os
import sys
import requests
import pandas as pd
import numpy as np
import time

# --- 1. ดึง Token จาก Secrets ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

def get_binance_candles_4h(symbol, is_futures=False, limit=200):
    """ดึงข้อมูลแท่งเทียน 4H พร้อมใส่ User-Agent ป้องกันการโดนบล็อก"""
    if is_futures:
        endpoints = [
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=4h&limit={limit}"
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
            print(f"Error fetching {symbol} from {url}: {e}")
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
        print(f"Error in analyze_ichimoku_cloud: {e}")
        return "UNKNOWN", 0.0, 0.0

def evaluate_market_regime(btc_status, btc_dom_status):
    """วิเคราะห์ Matrix กระแสเงินทุน"""
    if btc_status == "BULLISH" and btc_dom_status == "BEARISH":
        title = "🚀 FULL ALTCOIN SEASON"
        desc = "เงินไหลออกจาก BTC เข้าเก็งกำไรในเหรียญ Altcoins อย่างรุนแรง"
        bias = "เน้นเปิด LONG เหรียญ Altcoins (เลือกตัว 15M Over 0 / Golden Cross)"
    
    elif btc_status == "BULLISH" and btc_dom_status == "SIDEWAY":
        title = "🔄 SELECTIVE ALTCOIN PUMP"
        desc = "BTC ทรงตัวขาขึ้น เงินหมุนเวียนเก็งกำไรใน Altcoins รายกลุ่ม"
        bias = "เลือก Long เหรียญที่มีสัญญาณ 4H BUY เหนือเมฆ"

    elif btc_status == "BULLISH" and btc_dom_status == "BULLISH":
        title = "👑 BTC SOLO RUN / SURGE"
        desc = "เงินดูดเข้า BTC ตัวเดียว Altcoins ส่วนใหญ่ถูกดูดสภาพคล่อง"
        bias = "เทรดเฉพาะ BTC / ชะลอการไล่ราคา Altcoins"

    elif btc_status == "BEARISH" and btc_dom_status == "BULLISH":
        title = "🩸 ALTCOIN BLEEDING / DANGER ZONE"
        desc = "BTC ย่อตัวและส่วนแบ่งตลาดพุ่ง เหรียญเล็กจะร่วงแรงเป็น 2-3 เท่า"
        bias = "หาจังหวะ SHORT Altcoins หรือ ถือ Cash 100% (ห้ามช้อนซื้อ)"

    elif btc_status == "BEARISH" and btc_dom_status == "BEARISH":
        title = "💸 TOTAL MARKET OUTFLOW / CRASH"
        desc = "เงินไหลออกจากตลาดคริปโตทั้งหมดเข้า Stablecoin หรือ Fiat"
        bias = "เน้นถือเงินสด หรือเล่นฝั่ง Short ภาพรวม"

    elif btc_status == "SIDEWAY" and btc_dom_status == "BEARISH":
        title = "🪙 ALTCOIN ACCUMULATION"
        desc = "BTC ไซด์เวย์นิ่ง แต่ Dominance ไหลลง มีการสะสมของในเหรียญลูก"
        bias = "ดักเก็บเหรียญต้นรอบที่เพิ่งเกิด Golden Cross บน 15M"

    else:
        title = "⚪️ CHOPPY / NEUTRAL MARKET"
        desc = "ตลาดพักฐาน ไร้ทิศทางชัดเจนทั้งราคาและส่วนแบ่งตลาด"
        bias = "ลดขนาดพอร์ต (Position Size) และรอให้เลือกทางชัดเจน"

    return title, desc, bias

def send_telegram(message):
    """ส่งข้อความเข้า Telegram พร้อมระบบ Fallback Plain Text"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in Secrets")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=10)
        
        # หาก Markdown ติด Error ให้ส่งเป็นข้อความธรรมดาทันที
        if res.status_code != 200:
            print(f"Telegram Markdown Failed ({res.text}), sending fallback plain text...")
            plain_text = message.replace("*", "").replace("`", "").replace("_", "")
            fallback_payload = {"chat_id": TELEGRAM_CHAT_ID, "text": plain_text}
            res_fb = requests.post(url, json=fallback_payload, timeout=10)
            print(f"Fallback response: {res_fb.status_code}")
        else:
            print("Telegram message sent successfully.")
    except Exception as e:
        print(f"Telegram Exception: {e}")

def main():
    print("Starting Market Flow Scanner...")
    
    df_btc = get_binance_candles_4h("BTCUSDT", is_futures=False)
    df_btcdom = get_binance_candles_4h("BTCDOMUSDT", is_futures=True)

    if df_btc is None:
        print("Error: Could not fetch BTCUSDT candles")
        return
    if df_btcdom is None:
        print("Error: Could not fetch BTCDOMUSDT candles")
        return

    btc_status, btc_price, btc_chg = analyze_ichimoku_cloud(df_btc)
    btcd_status, btcd_val, btcd_chg = analyze_ichimoku_cloud(df_btcdom)

    print(f"BTC: {btc_status} (${btc_price}), BTCDOM: {btcd_status} ({btcd_val})")

    title, desc, bias = evaluate_market_regime(btc_status, btcd_status)

    def icon(s):
        return "🟢" if s == "BULLISH" else ("🔴" if s == "BEARISH" else "⚪️")

    msg = [
        "🌐 *[MARKET REGIME & MONEY FLOW 4H]*",
        "────────────────────────",
        "📊 *4H DATA OVERVIEW:*",
        f"  • BTC Price : `${btc_price:,.1f}` ({btc_chg:+.2f}%) | {icon(btc_status)} *{btc_status}*",
        f"  • BTC.D Index: `{btcd_val:,.2f}` ({btcd_chg:+.2f}%) | {icon(btcd_status)} *{btcd_status}*",
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
    main()import os
import sys
import requests
import pandas as pd
import numpy as np
import time

# --- ดึง Token จาก Secrets ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def get_binance_candles_4h(symbol, is_futures=False, limit=200):
    """ดึงข้อมูลแท่งเทียน 4H จาก Binance Spot หรือ Futures API"""
    if is_futures:
        endpoints = [
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=4h&limit={limit}"
        ]
    else:
        endpoints = [
            f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=4h&limit={limit}",
            f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=4h&limit={limit}"
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
    """คำนวณเมฆ Ichimoku บนแท่ง 4H ที่ปิดสมบูรณ์ล่าสุด (iloc[-2])"""
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

        # คำนวณ % การเปลี่ยนแปลงของแท่งล่าสุดเทียบกับแท่งก่อนหน้า
        prev_close = df["close"].iloc[-3]
        change_pct = ((close_val - prev_close) / prev_close) * 100

        return status, close_val, change_pct
    except Exception:
        return "UNKNOWN", 0.0, 0.0

def evaluate_market_regime(btc_status, btc_dom_status):
    """วิเคราะห์ความสัมพันธ์ BTC vs BTC.D (Matrix 9 สภาวะ)"""
    if btc_status == "BULLISH" and btc_dom_status == "BEARISH":
        title = "🚀 [FULL ALTCOIN SEASON]"
        desc = "เงินไหลออกจาก BTC เข้าเก็งกำไรในเหรียญ Altcoins อย่างรุนแรง"
        bias = "เน้นเปิด LONG เหรียญ Altcoins (เลือกตัว 15M Over 0 / Golden Cross)"
    
    elif btc_status == "BULLISH" and btc_dom_status == "SIDEWAY":
        title = "🔄 [SELECTIVE ALTCOIN PUMP]"
        desc = "BTC ทรงตัวขาขึ้น เงินหมุนเวียนเก็งกำไรใน Altcoins รายกลุ่ม"
        bias = "เลือก Long เหรียญที่มีสัญญาณ 4H BUY เหนือเมฆ"

    elif btc_status == "BULLISH" and btc_dom_status == "BULLISH":
        title = "👑 [BTC SOLO RUN / SURGE]"
        desc = "เงินดูดเข้า BTC ตัวเดียว Altcoins ส่วนใหญ่ถูกดูดสภาพคล่อง"
        bias = "เทรดเฉพาะ BTC / ชะลอการไล่ราคา Altcoins"

    elif btc_status == "BEARISH" and btc_dom_status == "BULLISH":
        title = "🩸 [ALTCOIN BLEEDING / DANGER ZONE]"
        desc = "BTC ย่อตัวและส่วนแบ่งตลาดพุ่ง เหรียญเล็กจะร่วงแรงเป็น 2-3 เท่า"
        bias = "หาจังหวะ SHORT Altcoins หรือ ถือ Cash 100% (ห้ามช้อนซื้อ)"

    elif btc_status == "BEARISH" and btc_dom_status == "BEARISH":
        title = "💸 [TOTAL MARKET OUTFLOW / CRASH]"
        desc = "เงินไหลออกจากตลาดคริปโตทั้งหมดเข้า Stablecoin หรือ Fiat"
        bias = "เน้นถือเงินสด หรือเล่นฝั่ง Short ภาพรวม"

    elif btc_status == "SIDEWAY" and btc_dom_status == "BEARISH":
        title = "🪙 [ALTCOIN ACCUMULATION]"
        desc = "BTC ไซด์เวย์นิ่ง แต่ Dominance ไหลลง มีการสะสมของในเหรียญลูก"
        bias = "ดักเก็บเหรียญต้นรอบที่เพิ่งเกิด Golden Cross บน 15M"

    else:
        title = "⚪️ [CHOPPY / NEUTRAL MARKET]"
        desc = "ตลาดพักฐาน ไร้ทิศทางชัดเจนทั้งราคาและส่วนแบ่งตลาด"
        bias = "ลดขนาดพอร์ต (Position Size) และรอให้เลือกทางชัดเจน"

    return title, desc, bias

def send_telegram(message):
    """ส่งข้อความเข้า Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram Secrets")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    # 1. ดึง BTCUSDT (Spot) และ BTCDOMUSDT (Futures)
    df_btc = get_binance_candles_4h("BTCUSDT", is_futures=False)
    df_btcdom = get_binance_candles_4h("BTCDOMUSDT", is_futures=True)

    if df_btc is None or df_btcdom is None:
        print("Failed to fetch BTC or BTC.D data")
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
        f"  • BTC.D Index: `{btcd_val:,.1f}` ({btcd_chg:+.2f}%) | {icon(btcd_status)} *{btcd_status}*",
        "────────────────────────",
        f"🎯 *MARKET STATE:*\n  *{title}*",
        f"  _{desc}_",
        "",
        f"💡 *TRADING PLAYBOOK:*\n  • {bias}",
        "────────────────────────",
        "📌 *เกณฑ์การคำนวณ:* Ichimoku Cloud (9, 26, 52, 26) บนแท่ง 4H ปิดสมบูรณ์"
    ]

    send_telegram("\n".join(msg))
    print("Market flow evaluated and sent.")

if __name__ == "__main__":
    main()
