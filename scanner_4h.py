import os
import sys
import requests
import pandas as pd
import numpy as np
import time

# ======================== 1. CONFIGURATION & SECRETS ========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

WATCHLIST = [
    # --- Tier A (Core Blue Chips & Macro | เรียง A-Z) ---
    "BNBUSDT",
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XAUUSDT",
    "XRPUSDT",

    # --- DeFi & Real World Assets (เรียง A-Z) ---
    "AAVEUSDT",
    "ENAUSDT",
    "JUPUSDT",
    "LINKUSDT",
    "ONDOUSDT",
    "PENDLEUSDT",
    "UNIUSDT",

    # --- AI & Decentralized Compute (เรียง A-Z) ---
    "FETUSDT",
    "NEARUSDT",
    "RENDERUSDT",
    "TAOUSDT",
    "WLDUSDT",

    # --- Layer 1 & Modular (เรียง A-Z) ---
    "INJUSDT",
    "SEIUSDT",
    "SUIUSDT",
    "TIAUSDT",

    # --- Legacy & เพิ่มเติม (เรียง A-Z) ---
    "LTCUSDT",
    "ZECUSDT",
]

# ======================== 2. DATA FETCHERS (BINANCE / GATE.IO / KUCOIN) ========================
def get_binance_candles_4h(symbol):
    """ดึงแท่งเทียน 4H จาก Binance (Futures -> Spot Vision -> Spot Public)"""
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=4h&limit=200",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=4h&limit=200",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=4h&limit=200"
    ]
    for url in endpoints:
        try:
            res = requests.get(url, timeout=10).json()
            if isinstance(res, list) and len(res) >= 60:
                df = pd.DataFrame(res, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades", "taker_buy_base",
                    "taker_buy_quote", "ignore"
                ])
                for col in ["open", "high", "low", "close", "volume", "open_time"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df.sort_values(by="open_time").dropna().reset_index(drop=True)
        except Exception:
            continue
    return None

def get_gateio_candles_4h(symbol):
    """ดึงแท่งเทียน 4H จาก Gate.io API (รองรับทั้ง Spot และ Futures)"""
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    
    endpoints = [
        f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval=4h&limit=200",
        f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval=4h&limit=200"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for url in endpoints:
        try:
            res = requests.get(url, headers=headers, timeout=10).json()
            if isinstance(res, list) and len(res) >= 60:
                records = []
                for item in res:
                    # Futures format: dict / Spot format: list [t, v, c, h, l, o, ...]
                    if isinstance(item, dict):
                        records.append({
                            "open_time": float(item.get("t", 0)) * 1000,
                            "open": float(item.get("o", 0)),
                            "high": float(item.get("h", 0)),
                            "low": float(item.get("l", 0)),
                            "close": float(item.get("c", 0)),
                            "volume": float(item.get("v", 0))
                        })
                    elif isinstance(item, list) and len(item) >= 6:
                        records.append({
                            "open_time": float(item[0]) * 1000,
                            "open": float(item[5]),
                            "high": float(item[3]),
                            "low": float(item[4]),
                            "close": float(item[2]),
                            "volume": float(item[6]) if len(item) > 6 else float(item[1])
                        })
                if records:
                    df = pd.DataFrame(records)
                    return df.sort_values(by="open_time").dropna().reset_index(drop=True)
        except Exception:
            continue
    return None

def get_kucoin_candles_4h(symbol):
    """ดึงแท่งเทียน 4H จาก KuCoin Public API"""
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    kucoin_sym = f"{base_sym}-USDT"
    url = f"https://api.kucoin.com/api/v1/market/candles?type=4hour&symbol={kucoin_sym}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= 60:
            records = []
            for item in res["data"]:
                records.append({
                    "open_time": float(item[0]) * 1000,
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5])
                })
            df = pd.DataFrame(records)
            return df.sort_values(by="open_time").dropna().reset_index(drop=True)
    except Exception as e:
        print(f"[!] KuCoin API Error ({symbol}): {e}")
    return None

def get_market_candles_4h(symbol):
    """Router ดึงแท่งเทียนอัตโนมัติ: Binance -> Gate.io -> KuCoin"""
    df = get_binance_candles_4h(symbol)
    if df is not None:
        return df

    df = get_gateio_candles_4h(symbol)
    if df is not None:
        return df

    df = get_kucoin_candles_4h(symbol)
    return df

# ======================== 3. PURE KUMO CALCULATION ========================
def analyze_4h_cloud(df):
    """คำนวณเมฆ Ichimoku (9, 26, 52, 26) บนแท่ง 4H ที่ปิดสมบูรณ์แล้ว"""
    try:
        tenkan = (df["high"].rolling(9).max() + df["low"].rolling(9).min()) / 2
        kijun = (df["high"].rolling(26).max() + df["low"].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2).shift(26)

        close_val = df["close"].iloc[-2]
        span_a_val = span_a.iloc[-2]
        span_b_val = span_b.iloc[-2]

        if pd.isna(span_a_val) or pd.isna(span_b_val):
            return "UNKNOWN"

        top_kumo = max(span_a_val, span_b_val)
        bot_kumo = min(span_a_val, span_b_val)

        if close_val > top_kumo:
            return "BUY"
        elif close_val < bot_kumo:
            return "SELL"
        else:
            return "UNKNOWN"
    except Exception:
        return "UNKNOWN"

# ======================== 4. FORMATTING & NOTIFICATION ========================
def format_grid(coins, cols=3):
    """จัดเรียงรายชื่อเหรียญแถวละ 3 ตัว ล็อกความกว้างช่องละ 11 ตัวอักษร"""
    if not coins:
        return "  • ไม่มี"
    rows = []
    for i in range(0, len(coins), cols):
        chunk = coins[i:i + cols]
        row_str = "  " + " ".join([f"`{c:<11}`" for c in chunk])
        rows.append(row_str)
    return "\n".join(rows)

def send_telegram(message):
    """ส่งข้อความแจ้งเตือนเข้า Telegram พร้อม Fallback ป้องกัน Markdown หลุด"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Error: ไม่พบ TELEGRAM_TOKEN หรือ TELEGRAM_CHAT_ID ใน Secrets")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            payload_plain = {
                "chat_id": TELEGRAM_CHAT_ID, 
                "text": message.replace("*", "").replace("`", "")
            }
            requests.post(url, json=payload_plain, timeout=10)
    except Exception as e:
        print(f"[!] Telegram API error: {e}")

# ======================== 5. MAIN EXECUTION ========================
def main():
    print("🚀 เริ่มต้นสแกน TF 4H (Pure Cloud)...")
    buy_list = []
    sell_list = []
    unknown_list = []

    for sym in WATCHLIST:
        df = get_market_candles_4h(sym)

        if df is None:
            unknown_list.append(sym)
            print(f"[{sym}] ⚠️ ไม่สามารถดึงข้อมูลได้ -> UNKNOWN")
            continue

        status = analyze_4h_cloud(df)

        if status == "BUY":
            buy_list.append(sym)
            print(f"[{sym}] 🟢 BUY (เหนือเมฆ)")
        elif status == "SELL":
            sell_list.append(sym)
            print(f"[{sym}] 🔴 SELL (ใต้เมฆ)")
        else:
            unknown_list.append(sym)
            print(f"[{sym}] ⚪ UNKNOWN (ในเมฆ)")

        time.sleep(0.05)

    msg = [
        "📊 *สรุปภาพรวมเหรียญ TF 4H (Pure Cloud)*",
        "────────────────────────",
        f"🟢 *BUY (เหนือเมฆ) [{len(buy_list)}]*",
        format_grid(buy_list, cols=3),
        "",
        f"🔴 *SELL (ใต้เมฆ) [{len(sell_list)}]*",
        format_grid(sell_list, cols=3),
        "",
        f"⚪️ *UNKNOWN (ในเมฆ) [{len(unknown_list)}]*",
        format_grid(unknown_list, cols=3),
        "────────────────────────"
    ]

    send_telegram("\n".join(msg))
    print("✅ สแกน 4H เสร็จสิ้นและส่งแจ้งเตือนสำเร็จ")

if __name__ == "__main__":
    main()
