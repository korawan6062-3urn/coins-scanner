import requests
import pandas as pd
import numpy as np
import time

# --- 1. ข้อมูลการแจ้งเตือน Telegram ---
TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

# --- ละเว้น Stablecoin และ Wrapped Token ---
EXCLUDE_TOKENS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDD", "USDE", "PYUSD",
    "BUSD", "EUR", "USD", "USTC", "FRAX", "LUSD", "WBTC", "WETH",
    "STETH", "WEETH", "CBETH", "RETH", "CETH", "BSC-USD"
}

def get_top_20_coins():
    """ดึง Top 20 Market Cap สดจาก CoinGecko หรือ CryptoCompare"""
    # ช่องทางที่ 1: CoinGecko API
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=45&page=1"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10).json()
        if isinstance(res, list) and len(res) > 0:
            top_coins = []
            for item in res:
                sym = item.get("symbol", "").upper()
                if sym and sym not in EXCLUDE_TOKENS:
                    top_coins.append(sym)
                if len(top_coins) == 20:
                    return top_coins
    except Exception:
        pass

    # ช่องทางที่ 2: CryptoCompare API
    try:
        url = "https://min-api.cryptocompare.com/data/top/mktcapfull?limit=40&tsym=USD"
        res = requests.get(url, timeout=10).json()
        if "Data" in res and res["Data"]:
            top_coins = []
            for item in res["Data"]:
                coin_info = item.get("CoinInfo", {})
                sym = coin_info.get("Name", "").upper()
                if sym and sym not in EXCLUDE_TOKENS:
                    top_coins.append(sym)
                if len(top_coins) == 20:
                    return top_coins
    except Exception:
        pass

    # ช่องทางที่ 3: ลิสต์สำรองกรณีฉุกเฉิน
    return [
        "BTC", "ETH", "SOL", "BNB", "XRP",
        "DOGE", "ADA", "AVAX", "SUI", "LINK",
        "NEAR", "DOT", "TRX", "APT", "ICP",
        "LTC", "FET", "UNI", "TAO", "AAVE"
    ]

def get_4h_data(coin):
    """ดึงกราฟ 4H จาก KuCoin หรือ Gate.io"""
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type=4hour&symbol={coin}-USDT"
        res = requests.get(url, timeout=10).json()
        if res.get("code") == "200000" and res.get("data"):
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

    url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval=4h&limit=150"
    res = requests.get(url, timeout=10).json()
    df = pd.DataFrame(res, columns=["time", "volume", "close", "high", "low", "open"])
    df["time"] = df["time"].astype(int)
    df = df.sort_values(by="time").reset_index(drop=True)
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    return df

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
    top_20_coins = get_top_20_coins()

    buy_list = []
    sell_list = []
    unknown_list = []

    for rank, coin in enumerate(top_20_coins, start=1):
        sym = f"{coin}USDT"
        try:
            df = get_4h_data(coin)
            category, reason = check_setup(df)
            item_text = f"• `#{rank:<2}` *{sym}* : {reason}"

            if category == "BUY":
                buy_list.append(item_text)
            elif category == "SELL":
                sell_list.append(item_text)
            else:
                unknown_list.append(item_text)
        except Exception:
            unknown_list.append(f"• `#{rank:<2}` *{sym}* : ⚠️ ดึงข้อมูลล้มเหลว")
        
        time.sleep(0.1)

    # 3. จัด Format ข้อความส่งออก
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
