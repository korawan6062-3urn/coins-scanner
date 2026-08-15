import requests
import pandas as pd
import numpy as np
import time

# --- 1. ข้อมูลการแจ้งเตือน Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- รายชื่อ Stablecoin / Wrapped Token ที่ต้องละเว้นจาก CoinGecko ---
EXCLUDE_TOKENS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDD", "USDE", "PYUSD",
    "BUSD", "EUR", "USD", "USTC", "FRAX", "LUSD", "WBTC", "WETH",
    "STETH", "WEETH", "CBETH", "RETH", "CETH", "BSC-USD", "USDS",
    "USD1", "USD0", "LEO", "WBT", "MNT", "KCS", "OKB", "GT", "HT"
}

def is_valid_token(symbol):
    s = symbol.upper()
    if s in EXCLUDE_TOKENS:
        return False
    if "_" in s or "." in s or "-" in s:
        return False
    if s.startswith("USD") or s.endswith("USD") or s.endswith("EUR"):
        return False
    return True

# ========================================================
# 1. ส่วนดึงอันดับ Market Cap สดแท้จริงจาก CoinGecko
# ========================================================
def get_coingecko_top_candidates():
    """ดึงลิสต์เหรียญ Top Market Cap จาก CoinGecko โดยตรง"""
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=50&page=1"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=10).json()
        if isinstance(res, list) and len(res) > 0:
            candidates = []
            for item in res:
                sym = item.get("symbol", "").upper()
                if is_valid_token(sym):
                    candidates.append(sym)
            return candidates
    except Exception:
        pass

    # ลิสต์สำรองมาตรฐานระดับโลก กรณีเชื่อมต่อ CoinGecko ไม่สำเร็จ
    return [
        "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "TRX", "AVAX", "SUI",
        "LINK", "NEAR", "DOT", "APT", "ICP", "LTC", "FET", "UNI", "TAO", "AAVE",
        "RENDER", "SHIB", "PEPE", "BCH", "XLM", "ATOM", "ETC", "FIL", "ARB", "OP"
    ]

# ========================================================
# 2. ส่วนดึงข้อมูลแท่งเทียน 4H จาก Gate.io / KuCoin
# ========================================================
def get_4h_candles_from_exchange(coin):
    """ดึงข้อมูลกราฟ 4H โดยใช้ Gate.io เป็นหลัก และ KuCoin เป็นสำรอง"""
    # ช่องทางหลัก: Gate.io API
    try:
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval=4h&limit=150"
        res = requests.get(url, timeout=5).json()
        if isinstance(res, list) and len(res) >= 90:
            # Gate.io: [timestamp, volume, close, high, low, open]
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
            # KuCoin: [time, open, close, high, low, volume, turnover]
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

# ========================================================
# 3. คำนวณเทคนิคอลตามระบบ A.Aun
# ========================================================
def check_setup(df):
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

# ========================================================
# 4. ประมวลผลหลัก
# ========================================================
def main():
    # ดึงรายชื่อเหรียญตามอันดับ Market Cap แท้จริงจาก CoinGecko
    candidates = get_coingecko_top_candidates()

    buy_list = []
    sell_list = []
    unknown_list = []
    scanned_count = 0

    # วนลูปดึงกราฟจาก Exchange ให้ครบ 20 ตัวที่มีข้อมูลสมบูรณ์
    for coin in candidates:
        df = get_4h_candles_from_exchange(coin)
        if df is not None:
            scanned_count += 1
            sym = f"{coin}USDT"
            category, reason = check_setup(df)
            item_text = f"• `#{scanned_count:<2}` *{sym}* : {reason}"

            if category == "BUY":
                buy_list.append(item_text)
            elif category == "SELL":
                sell_list.append(item_text)
            else:
                unknown_list.append(item_text)

        if scanned_count == 20:
            break
        time.sleep(0.05)

    # จัดรูปแบบข้อความส่งออก
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
