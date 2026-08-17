import os
import sys
import requests
import pandas as pd
import numpy as np
import time

# --- 1. ดึง Token และ Chat ID จาก GitHub Secrets ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TV_SCANNER_URL = "https://scanner.tradingview.com/crypto/scan"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

def get_tradingview_4h_data():
    """ดึงข้อมูล BTC.D และ BTCUSDT 4H จาก TradingView Technical Scanner โดยตรง"""
    payload = {
        "symbols": {
            "tickers": ["CRYPTOCAP:BTC.D", "BINANCE:BTCUSDT"]
        },
        "columns": [
            "close",
            "change",
            "close|240",
            "change|240",
            "Ichimoku.Lead1|240",
            "Ichimoku.Lead2|240",
            "EMA50|240",
            "Recommend.All|240"
        ]
    }
    try:
        res = requests.post(TV_SCANNER_URL, json=payload, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            data = res.json().get("data", [])
            results = {}
            for item in data:
                symbol = item["s"]
                d = item["d"]
                # ดึงค่า: close 4h, change 4h, span a, span b, ema50, recommend
                close_4h = d[2] if d[2] is not None else d[0]
                chg_4h   = d[3] if d[3] is not None else d[1]
                span_a   = d[4]
                span_b   = d[5]
                ema_50   = d[6]
                rec_all  = d[7]

                # วิเคราะห์เมฆ Ichimoku 4H
                if span_a is not None and span_b is not None:
                    top_cloud = max(span_a, span_b)
                    bot_cloud = min(span_a, span_b)
                    if close_4h > top_cloud:
                        status = "BULLISH"
                    elif close_4h < bot_cloud:
                        status = "BEARISH"
                    else:
                        status = "SIDEWAY"
                elif ema_50 is not None:
                    status = "BULLISH" if close_4h > ema_50 else "BEARISH"
                elif rec_all is not None:
                    status = "BULLISH" if rec_all > 0.1 else ("BEARISH" if rec_all < -0.1 else "SIDEWAY")
                else:
                    status = "UNKNOWN"

                results[symbol] = {
                    "close": float(close_4h),
                    "change": float(chg_4h if chg_4h is not None else 0.0),
                    "status": status
                }
            return results
    except Exception as e:
        print(f"TradingView Scanner Error: {e}")
    return None

def evaluate_market_regime(btc_status, btcd_status):
    """วิเคราะห์ Matrix กระแสเงินทุน BTC vs BTC.D (9 สภาวะ)"""
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
    """ส่งข้อความเข้า Telegram พร้อม Fallback"""
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
    print("Fetching BTC & BTC.D 4H Data from TradingView...")
    tv_data = get_tradingview_4h_data()

    if not tv_data or "CRYPTOCAP:BTC.D" not in tv_data or "BINANCE:BTCUSDT" not in tv_data:
        print("Error: Could not fetch data from TradingView Scanner API.")
        return

    btcd_info = tv_data["CRYPTOCAP:BTC.D"]
    btc_info  = tv_data["BINANCE:BTCUSDT"]

    btc_status, btc_price, btc_chg = btc_info["status"], btc_info["close"], btc_info["change"]
    btcd_status, btcd_val, btcd_chg = btcd_info["status"], btcd_info["close"], btcd_info["change"]

    print(f"TradingView Data -> BTC: {btc_status} (${btc_price:.1f}), BTC.D: {btcd_status} ({btcd_val:.2f}%)")

    title, desc, bias = evaluate_market_regime(btc_status, btcd_status)

    def icon(s):
        return "🟢" if s == "BULLISH" else ("🔴" if s == "BEARISH" else "⚪️")

    msg = [
        "🌐 *[MARKET REGIME & MONEY FLOW 4H]*",
        "────────────────────────",
        "📊 *4H DATA OVERVIEW (TradingView)*",
        f"  • BTC Price : `${btc_price:,.1f}` ({btc_chg:+.2f}%) | {icon(btc_status)} *{btc_status}*",
        f"  • BTC.D Dom : `{btcd_val:.2f}%` ({btcd_chg:+.2f}%) | {icon(btcd_status)} *{btcd_status}*",
        "────────────────────────",
        f"🎯 *MARKET STATE:*\n  *{title}*",
        f"  {desc}",
        "",
        f"💡 *TRADING PLAYBOOK:*\n  • {bias}",
        "────────────────────────",
        "📌 *เกณฑ์การคำนวณ:* TradingView Technical 4H (Ichimoku Cloud)"
    ]

    send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
