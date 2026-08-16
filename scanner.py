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

def get_4h_candles(coin):
    """ดึงข้อมูลกราฟ 4H"""
    try:
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval=4h&limit=150"
        res = requests.get(url, timeout=7).json()
        if isinstance(res, list) and len(res) >= 60:
            df = pd.DataFrame(res, columns=["time", "volume", "close", "high", "low", "open"])
            df["time"] = pd.to_numeric(df["time"], errors="coerce")
            df = df.sort_values(by="time").reset_index(drop=True)
            for col in ["close", "high", "low", "open"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna().reset_index(drop=True)
            if len(df) >= 60:
                return df
    except Exception:
        pass

    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type=4hour&symbol={coin}-USDT"
        res = requests.get(url, timeout=7).json()
        if isinstance(res, dict) and res.get("code") == "200000" and res.get("data"):
            raw = res["data"]
            if len(raw) >= 60:
                df = pd.DataFrame(raw, columns=["time", "open", "close", "high", "low", "volume", "turnover"])
                df["time"] = pd.to_numeric(df["time"], errors="coerce")
                df = df.sort_values(by="time").reset_index(drop=True)
                for col in ["close", "high", "low", "open"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().reset_index(drop=True)
                if len(df) >= 60:
                    return df
    except Exception:
        pass

    return None

def check_setup(df):
    """คำนวณ Ichimoku Cloud (9,26,52) + EMA89"""
    try:
        df["ema89"] = df["close"].ewm(span=89, adjust=False).mean()

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

        if pd.isna(top_kumo) or pd.isna(bot_kumo):
            top_kumo = last_ema89
            bot_kumo = last_ema89

        if last_close > top_kumo:
            ichi_status = "เหนือเมฆ"
        elif last_close < bot_kumo:
            ichi_status = "ใต้เมฆ"
        else:
            ichi_status = "ในเนื้อเมฆ"

        ema_status = "เหนือ EMA89" if last_close >= last_ema89 else "ใต้ EMA89"

        if ichi_status == "เหนือเมฆ" and ema_status == "เหนือ EMA89":
            category = "BUY"
        elif ichi_status == "ใต้เมฆ" and ema_status == "ใต้ EMA89":
            category = "SELL"
        else:
            category = "UNKNOWN"

        return category, ichi_status, ema_status
    except Exception:
        return "UNKNOWN", "ดึงข้อมูลล้มเหลว", "ไม่ระบุ"

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
    buy_list = []
    sell_list = []
    unknown_list = []

    for coin in WATCHLIST:
        sym = f"{coin}USDT"
        df = get_4h_candles(coin)
        if df is not None:
            category, ichi_status, ema_status = check_setup(df)
            item_text = f"• `{sym:<10}:` {ichi_status} | {ema_status}"

            if category == "BUY":
                buy_list.append(item_text)
            elif category == "SELL":
                sell_list.append(item_text)
            else:
                unknown_list.append(item_text)
        else:
            unknown_list.append(f"• `{sym:<10}:` ⚠️ ดึงข้อมูลล้มเหลว")

        time.sleep(0.04)

    report = ["📊 *4H (A.Aun Setup) - Watchlist*", "────────────────────────"]

    report.append(f"🟢 *BUY (LONG)* [{len(buy_list)}]")
    if buy_list:
        report.extend(buy_list)
    else:
        report.append("• _ไม่มีเหรียญที่ตรงเงื่อนไข_")
    report.append("")

    report.append(f"🔴 *SELL (SHORT)* [{len(sell_list)}]")
    if sell_list:
        report.extend(sell_list)
    else:
        report.append("• _ไม่มีเหรียญที่ตรงเงื่อนไข_")
    report.append("")

    report.append(f"⚪ *UNKNOWN (NO TRADE)* [{len(unknown_list)}]")
    if unknown_list:
        report.extend(unknown_list)
    else:
        report.append("• _ไม่มีเหรียญ_")

    report.append("────────────────────────")
    report.append("📌 *กฎเหล็ก 4H (A.Aun Mindset):*")
    report.append("• โฟกัสเฉพาะกลุ่ม 🟢 หรือ 🔴 เท่านั้น (⚪ ข้ามเด็ดขาด)")
    report.append("• ห้ามเปิดออเดอร์ทันทีใน 4H ให้รอบอท 15M แจ้งเตือนจุดพักตัว")
    report.append("• X-ABC?")

    send_telegram("\n".join(report))
    print("4H Scanner completed.")

if __name__ == "__main__":
    main()
