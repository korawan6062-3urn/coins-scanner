import requests
import pandas as pd
import numpy as np
import time

# --- 1. ข้อมูลการแจ้งเตือน Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- 2. Top 31 Curated Watchlist (รวม PAXG ทองคำ) เรียง A -> Z ---
WATCHLIST = sorted([
    "AAVE", "ADA", "APT", "AVAX", "BCH",
    "BNB", "BTC", "DOT", "ENA", "ETH",
    "FET", "INJ", "JTO", "KAS", "LDO",
    "LINK", "LTC", "NEAR", "ONDO", "PAXG",
    "PENDLE", "RENDER", "SEI", "SOL", "SUI",
    "TAO", "TIA", "TRX", "UNI", "XLM", "XRP"
])

def get_4h_candles(coin):
    """ดึงข้อมูลกราฟ 4H จาก Gate.io หรือ KuCoin (ดึง 150 แท่งเพื่อความแม่นยำ)"""
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

def detect_macd_divergence(df, lookback=100):
    """
    ตรวจจับ Divergence แบบ Dual-Mode:
    1. Micro Divergence (คลื่นสั้น 4-15 แท่งล่าสุด เช่น ADA)
    2. Macro Divergence (คลื่นยาว 15-80 แท่ง เช่น ONDO)
    """
    try:
        fast_ema = df["close"].ewm(span=12, adjust=False).mean()
        slow_ema = df["close"].ewm(span=26, adjust=False).mean()
        macd = fast_ema - slow_ema

        sub_df = df.tail(lookback).copy().reset_index(drop=True)
        sub_macd = macd.tail(lookback).values
        highs = sub_df["high"].values
        lows = sub_df["low"].values
        n = len(sub_df)

        if n < 20:
            return ""

        curr_price = lows[-1]
        curr_macd = sub_macd[-1]

        # ----------------------------------------------------
        # 1. เช็ก Bullish Divergence (สำหรับเตือนฝั่ง SELL)
        # ----------------------------------------------------
        # โหมดที่ 1: Micro Bull Div (ก้นย่อย 4-15 แท่งล่าสุดแบบ ADA)
        micro_macd_win = sub_macd[n-15: n-3]
        micro_lows_win = lows[n-15: n-3]
        if len(micro_macd_win) > 0:
            min_micro_macd = np.min(micro_macd_win)
            idx_micro = np.argmin(micro_macd_win)
            price_micro = micro_lows_win[idx_micro]

            if curr_price <= price_micro and curr_macd > min_micro_macd and curr_macd < 0:
                return " 🔥 Bull Div"

        # โหมดที่ 2: Macro Bull Div (ก้นคลื่นใหญ่ 15-80 แท่งแบบ ONDO)
        macro_macd_win = sub_macd[max(0, n-80): n-15]
        macro_lows_win = lows[max(0, n-80): n-15]
        if len(macro_macd_win) > 0:
            min_macro_macd = np.min(macro_macd_win)
            idx_macro = np.argmin(macro_macd_win)
            price_macro = macro_lows_win[idx_macro]

            if curr_price <= price_macro and curr_macd > (min_macro_macd * 0.75) and min_macro_macd < 0:
                return " 🔥 Bull Div"

        # ----------------------------------------------------
        # 2. เช็ก Bearish Divergence (สำหรับเตือนฝั่ง BUY)
        # ----------------------------------------------------
        # โหมดที่ 1: Micro Bear Div
        micro_highs_win = highs[n-15: n-3]
        if len(micro_macd_win) > 0:
            max_micro_macd = np.max(micro_macd_win)
            idx_micro_h = np.argmax(micro_macd_win)
            price_micro_h = micro_highs_win[idx_micro_h]

            if curr_price >= price_micro_h and curr_macd < max_micro_macd and curr_macd > 0:
                return " ⚠️ Bear Div"

        # โหมดที่ 2: Macro Bear Div
        macro_highs_win = highs[max(0, n-80): n-15]
        if len(macro_macd_win) > 0:
            max_macro_macd = np.max(macro_macd_win)
            idx_macro_h = np.argmax(macro_macd_win)
            price_macro_h = macro_highs_win[idx_macro_h]

            if curr_price >= price_macro_h and curr_macd < (max_macro_macd * 0.75) and max_macro_macd > 0:
                return " ⚠️ Bear Div"

    except Exception:
        pass

    return ""

def check_setup(df):
    """คำนวณแยกสถานะ Ichimoku Cloud + EMA89 และตรวจ Divergence ตามสูตร A.Aun"""
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

    # 3. จัดหมวดหมู่ Action หลัก
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

    # รวมผลสรุปรายงานแยก 3 หมวดหมู่ชัดเจน
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
