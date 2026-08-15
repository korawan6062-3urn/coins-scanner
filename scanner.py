import requests
import pandas as pd
import numpy as np
import time

# --- 1. ข้อมูลการแจ้งเตือน Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- 2. Top 30 Curated Watchlist (A -> Z, No Meme, No Stablecoin) ---
WATCHLIST = sorted([
    "AAVE", "ADA", "APT", "AVAX", "BCH",
    "BNB", "BTC", "DOT", "ENA", "ETH",
    "FET", "INJ", "JTO", "KAS", "LDO",
    "LINK", "LTC", "NEAR", "ONDO", "PENDLE",
    "RENDER", "SEI", "SOL", "SUI", "TAO",
    "TIA", "TRX", "UNI", "XLM", "XRP"
])

def get_4h_candles_from_exchange(coin):
    """ดึงข้อมูลกราฟ 4H จาก Gate.io หรือ KuCoin"""
    # ช่องทางหลัก: Gate.io API
    try:
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval=4h&limit=150"
        res = requests.get(url, timeout=5).json()
        if isinstance(res, list) and len(res) >= 90:
            df = pd.DataFrame(res, columns=["time", "volume", "close", "high", "low", "open"])
            df["time"] = df["time"].astype(int)
            df = df.sort_values(by="time").reset_index(drop=True)
            df["close"] = df["close"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            return df
    except Exception:
        pass

    # ช่องทางสำรอง: KuCoin API
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type=4hour&symbol={coin}-USDT"
        res = requests.get(url, timeout=5).json()
        if res.get("code") == "200000" and res.get("data") and len(res["data"]) >= 90:
            raw = res["data"]
            df = pd.DataFrame(raw, columns=["time", "open", "close", "high", "low", "volume", "turnover"])
            df["time"] = df["time"].astype(int)
            df = df.sort_values(by="time").reset_index(drop=True)
            df["close"] = df["close"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            return df
    except Exception:
        pass

    return None

def check_setup(df):
    """คำนวณตามสูตร A.Aun (EMA89 + Ichimoku Cloud 4H)"""
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
        return "BUY", "เหนือเมฆ + เหนือ EMA89"
    elif last_close < bot_kumo and last_close < last_ema89:
        return "SELL", "ใต้เมฆ + ใต้ EMA89"
    elif bot_kumo <= last_close <= top_kumo:
        return "UNKNOWN", "อยู่ในเนื้อเมฆ (Sideway)"
    else:
        return "UNKNOWN", "ทิศทางขัดแย้งกับ EMA89"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=10)

def main():
    buy_list = []
    sell_list = []
    unknown_list = []

    for coin in WATCHLIST:
        sym = f"{coin}USDT"
        df = get_4h_candles_from_exchange(coin)
        if df is not None:
            category, reason = check_setup(df)
            item_text = f"• *{sym}* : {reason}"

            if category == "BUY":
                buy_list.append(item_text)
            elif category == "SELL":
                sell_list.append(item_text)
            else:
                unknown_list.append(item_text)
        else:
            unknown_list.append(f"• *{sym}* : ⚠️ ดึงข้อมูลล้มเหลว")

        time.sleep(0.05)

    # 3. จัด Format ข้อความส่งออก (คลีน ไม่มีตัวเลขรบกวนสายตา)
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
    report.append("💡 *Action:* เลือกเฉพาะกลุ่ม 🟢 หรือ 🔴 ไปเปิดดู 15M/5M รอย่อ Retest")

    final_message = "\n".join(report)
    send_telegram(final_message)

if __name__ == "__main__":
    main()
