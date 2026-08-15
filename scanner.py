import requests
import pandas as pd
import numpy as np
import time

# --- ข้อมูลการแจ้งเตือน Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- Watchlist คุณภาพสูง 31 ตัว (รวมทองคำ PAXG) เรียง A -> Z ---
WATCHLIST = sorted([
    "AAVE", "ADA", "APT", "AVAX", "BCH",
    "BNB", "BTC", "DOT", "ENA", "ETH",
    "FET", "INJ", "JTO", "KAS", "LDO",
    "LINK", "LTC", "NEAR", "ONDO", "PAXG",
    "PENDLE", "RENDER", "SEI", "SOL", "SUI",
    "TAO", "TIA", "TRX", "UNI", "XLM", "XRP"
])

def get_4h_candles(coin):
    """ดึงข้อมูลกราฟ 4H จาก Gate.io (หลัก) หรือ KuCoin (สำรอง)"""
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

def detect_macd_divergence(df, lookback=35, pivot_period=4):
    """ตรวจจับ 4H Regular Divergence ด้วย Custom MACD (12, 26, SMA 9)"""
    try:
        fast_ema = df["close"].ewm(span=12, adjust=False).mean()
        slow_ema = df["close"].ewm(span=26, adjust=False).mean()
        macd = fast_ema - slow_ema

        sub_df = df.tail(lookback).copy().reset_index(drop=True)
        sub_macd = macd.tail(lookback).values
        highs = sub_df["high"].values
        lows = sub_df["low"].values
        n = len(sub_df)

        ph_idx = []
        pl_idx = []

        for i in range(pivot_period, n - pivot_period):
            if highs[i] == max(highs[i - pivot_period:i + pivot_period + 1]):
                ph_idx.append(i)
            if lows[i] == min(lows[i - pivot_period:i + pivot_period + 1]):
                pl_idx.append(i)

        # Bearish Divergence
        if len(ph_idx) >= 2:
            p1, p2 = ph_idx[-2], ph_idx[-1]
            if (n - 1 - p2) <= 6:
                if highs[p2] > highs[p1] and sub_macd[p2] < sub_macd[p1]:
                    return " [⚠️ Bear Div]"

        # Bullish Divergence
        if len(pl_idx) >= 2:
            p1, p2 = pl_idx[-2], pl_idx[-1]
            if (n - 1 - p2) <= 6:
                if lows[p2] < lows[p1] and sub_macd[p2] > sub_macd[p1]:
                    return " [🔥 Bull Div]"
    except Exception:
        pass

    return ""

def check_setup(df):
    """คำนวณแยกสถานะ Ichimoku Cloud + EMA89 และตรวจ Divergence"""
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

    # 1. สถานะ Ichimoku
    if last_close > top_kumo:
        ichi_status = "เหนือเมฆ"
    elif last_close < bot_kumo:
        ichi_status = "ใต้เมฆ"
    else:
        ichi_status = "ในเนื้อเมฆ"

    # 2. สถานะ EMA 89
    ema_status = "เหนือ EMA89" if last_close >= last_ema89 else "ใต้ EMA89"

    # 3. จัดหมวดหมู่ Action
    if ichi_status == "เหนือเมฆ" and ema_status == "เหนือ EMA89":
        category = "BUY"
    elif ichi_status == "ใต้เมฆ" and ema_status == "ใต้ EMA89":
        category = "SELL"
    else:
        category = "UNKNOWN"

    div_tag = detect_macd_divergence(df)
    return category, ichi_status, ema_status, div_tag

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
        df = get_4h_candles(coin)
        if df is not None:
            category, ichi_status, ema_status, div_tag = check_setup(df)
            item_text = f"• `{sym:<10}:` {ichi_status} | {ema_status}{div_tag}"

            if category == "BUY":
                buy_list.append(item_text)
            elif category == "SELL":
                sell_list.append(item_text)
            else:
                unknown_list.append(item_text)
        else:
            item_text = f"• `{sym:<10}:` ⚠️ ดึงข้อมูลล้มเหลว"
            unknown_list.append(item_text)

        time.sleep(0.04)

    # จัดรูปแบบข้อความส่งออก
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
