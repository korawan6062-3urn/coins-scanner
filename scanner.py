import requests
import pandas as pd
import numpy as np
import time

# --- 1. ข้อมูลการแจ้งเตือน Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- รายชื่อ Stablecoin, Wrapped Token และ CeFi Exchange Tokens ที่ต้องตัดทิ้ง ---
EXCLUDE_TOKENS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDD", "USDE", "PYUSD",
    "BUSD", "EUR", "USD", "USTC", "FRAX", "LUSD", "WBTC", "WETH",
    "STETH", "WEETH", "CBETH", "RETH", "CETH", "BSC-USD", "USDS",
    "USD1", "USD0", "LEO", "WBT", "OKB", "MNT", "GT", "KCS", "HT"
}

def is_valid_crypto(symbol):
    """ตรวจสอบว่าเป็นเหรียญคริปโตแท้จริง ไม่ใช่ Stablecoin หรือ RWA"""
    s = symbol.upper()
    if s in EXCLUDE_TOKENS:
        return False
    if "_" in s or "." in s or "-" in s:  # ตัดเหรียญ RWA หุ้น/พันธบัตร
        return False
    if s.startswith("USD") or s.endswith("USD") or s.endswith("EUR"):
        return False
    return True

def get_4h_data(coin):
    """ดึงกราฟ 4H จาก KuCoin หรือ Gate.io"""
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

    return None

def get_top_20_coins_with_data():
    """ดึงเหรียญ Top Market Cap และคัดเฉพาะเหรียญที่มีข้อมูลกราฟสมบูรณ์ครบ 20 ตัว"""
    candidate_coins = []
    
    # 1. ดึงผู้ท้าชิงอันดับ 1-60 จาก CoinGecko
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=60&page=1"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10).json()
        if isinstance(res, list) and len(res) > 0:
            for item in res:
                sym = item.get("symbol", "").upper()
                if is_valid_crypto(sym):
                    candidate_coins.append(sym)
    except Exception:
        pass

    # รายชื่อมาตรฐานสำรองกรณีต่อ CoinGecko ไม่ติด
    fallback_list = [
        "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "TRX", "AVAX", "SUI",
        "LINK", "NEAR", "DOT", "APT", "ICP", "LTC", "FET", "UNI", "TAO", "AAVE",
        "RENDER", "SHIB", "PEPE", "BCH", "XLM", "ATOM", "ETC", "FIL", "ARB", "OP"
    ]

    for c in fallback_list:
        if c not in candidate_coins and is_valid_crypto(c):
            candidate_coins.append(c)

    # 2. คัดเลือกเฉพาะเหรียญที่ดึงกราฟ 4H ได้สำเร็จจริง 20 อันดับแรก
    valid_list = []
    for coin in candidate_coins:
        df = get_4h_data(coin)
        if df is not None:
            valid_list.append((coin, df))
        if len(valid_list) == 20:
            break
        time.sleep(0.05)

    return valid_list

def check_setup(df):
    """คำนวณ EMA 89 และ Ichimoku Cloud 4H"""
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
    # ดึง Top 20 ตัวที่มีข้อมูลกราฟสมบูรณ์
    valid_coins_data = get_top_20_coins_with_data()

    buy_list = []
    sell_list = []
    unknown_list = []

    for rank, (coin, df) in enumerate(valid_coins_data, start=1):
        sym = f"{coin}USDT"
        category, reason = check_setup(df)
        item_text = f"• `#{rank:<2}` *{sym}* : {reason}"

        if category == "BUY":
            buy_list.append(item_text)
        elif category == "SELL":
            sell_list.append(item_text)
        else:
            unknown_list.append(item_text)

    # จัด Format ข้อความส่งออก
    report = ["📊 *4H (A.Aun Setup) - TOP 20*", "────────────────────────"]

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
