import time
import requests
import pandas as pd

TELEGRAM_TOKEN = "8903982584:AAF1EJ1OzjFpYzWJzAHeti8_xbQgVpYy8CU"
TELEGRAM_CHAT_ID = "1376495243"

WATCHLIST = sorted([
    "AAVE", "ADA", "APT", "ARB", "AVAX",
    "BCH", "BNB", "BTC", "DOGE", "DOT",
    "ENA", "ETH", "FET", "INJ", "LINK",
    "LTC", "NEAR", "ONDO", "OP", "PAXG",
    "PENDLE", "RENDER", "SEI", "SOL", "SUI",
    "TAO", "TIA", "UNI", "XLM", "XRP"
])

def get_candles(coin, interval="4h", limit=150):
    try:
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval={interval}&limit={limit}"
        res = requests.get(url, timeout=7).json()
        if isinstance(res, list) and len(res) >= 60:
            df = pd.DataFrame(res, columns=["time", "volume", "close", "high", "low", "open"])
            for c in ["close", "high", "low", "open", "time"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.sort_values(by="time").dropna().reset_index(drop=True)
    except Exception:
        pass
    return None

def analyze_4h(df):
    try:
        tenkan = (df["high"].rolling(9).max() + df["low"].rolling(9).min()) / 2
        kijun = (df["high"].rolling(26).max() + df["low"].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df["high"].rolling(52).max() + df["low"].rolling(52).min()) / 2).shift(26)

        # ใช้แท่งที่ปิดแล้วล่าสุด (iloc[-2]) เพื่อความแน่นอน
        close_val = df["close"].iloc[-2]
        top_kumo = max(span_a.iloc[-2], span_b.iloc[-2])
        bot_kumo = min(span_a.iloc[-2], span_b.iloc[-2])

        if pd.isna(top_kumo) or pd.isna(bot_kumo):
            return "UNKNOWN"

        if close_val > top_kumo:
            return "BUY"
        elif close_val < bot_kumo:
            return "SELL"
        else:
            return "UNKNOWN"
    except Exception:
        return "UNKNOWN"

def format_grid(coins, cols=3):
    if not coins:
        return "  • ไม่มี"
    rows = []
    for i in range(0, len(coins), cols):
        chunk = coins[i:i + cols]
        row_str = "  " + "  ".join([f"`{c:<10}`" for c in chunk])
        rows.append(row_str)
    return "\n".join(rows)

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    buy_list, sell_list, unknown_list = [], [], []

    for coin in WATCHLIST:
        df = get_candles(coin, interval="4h", limit=150)
        sym = f"{coin}USDT"
        if df is None:
            unknown_list.append(sym)
            continue

        status = analyze_4h(df)
        if status == "BUY":
            buy_list.append(sym)
        elif status == "SELL":
            sell_list.append(sym)
        else:
            unknown_list.append(sym)
        time.sleep(0.04)

    msg = [
        "📊 *สรุปภาพรวมเหรียญ TF 4H (Pure Cloud)*",
        "────────────────────────",
        f"🟢 *BUY (เหนือเมฆ) [{len(buy_list)}]*",
        format_grid(buy_list),
        "",
        f"🔴 *SELL (ใต้เมฆ) [{len(sell_list)}]*",
        format_grid(sell_list),
        "",
        f"⚪️ *UNKNOWN (ในเมฆ) [{len(unknown_list)}]*",
        format_grid(unknown_list),
        "────────────────────────",
        "📌 *แนวทาง:* รอแจ้งเตือนรอบคลื่น 15M แล้วคุมโครงสร้าง EMA 89 หน้างาน"
    ]
    send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
