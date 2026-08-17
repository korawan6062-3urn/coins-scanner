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

def get_candles(coin, interval="15m", limit=150):
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

def check_4h_trend(df_4h):
    try:
        tenkan = (df_4h["high"].rolling(9).max() + df_4h["low"].rolling(9).min()) / 2
        kijun = (df_4h["high"].rolling(26).max() + df_4h["low"].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df_4h["high"].rolling(52).max() + df_4h["low"].rolling(52).min()) / 2).shift(26)

        last_close = df_4h["close"].iloc[-2]
        top_kumo = max(span_a.iloc[-2], span_b.iloc[-2])
        bot_kumo = min(span_a.iloc[-2], span_b.iloc[-2])

        if pd.isna(top_kumo) or pd.isna(bot_kumo):
            return "NONE"

        if last_close > top_kumo:
            return "BUY"
        elif last_close < bot_kumo:
            return "SELL"
    except Exception:
        pass
    return "NONE"

def check_15m_trigger(df_15m, trend_4h):
    try:
        fast = df_15m["close"].ewm(span=12, adjust=False).mean()
        slow = df_15m["close"].ewm(span=26, adjust=False).mean()
        macd = fast - slow
        signal = macd.ewm(span=9, adjust=False).mean()

        # ตรวจจุดตัดเฉพาะแท่งปิดล่าสุด (iloc[-2]) เทียบกับแท่งก่อนหน้า (iloc[-3])
        crossover = (macd.iloc[-3] <= signal.iloc[-3]) and (macd.iloc[-2] > signal.iloc[-2])
        crossunder = (macd.iloc[-3] >= signal.iloc[-3]) and (macd.iloc[-2] < signal.iloc[-2])

        if trend_4h == "BUY" and crossover and (macd.iloc[-2] < 0):
            return "TRIGGER_LONG"
        elif trend_4h == "SELL" and crossunder and (macd.iloc[-2] > 0):
            return "TRIGGER_SHORT"
    except Exception:
        pass
    return "NONE"

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    triggers = []
    for coin in WATCHLIST:
        df_4h = get_candles(coin, interval="4h", limit=150)
        if df_4h is None:
            continue

        trend_4h = check_4h_trend(df_4h)
        if trend_4h == "NONE":
            continue

        df_15m = get_candles(coin, interval="15m", limit=150)
        if df_15m is None:
            continue

        signal = check_15m_trigger(df_15m, trend_4h)
        sym = f"{coin}USDT"

        if signal == "TRIGGER_LONG":
            triggers.append(f"🟢 *LONG ENTRY TRIGGER:* `{sym}`\n• เหนือเมฆ 4H + 15M Golden Cross (MACD < 0)")
        elif signal == "TRIGGER_SHORT":
            triggers.append(f"🔴 *SHORT ENTRY TRIGGER:* `{sym}`\n• ใต้เมฆ 4H + 15M Death Cross (MACD > 0)")
        time.sleep(0.04)

    if triggers:
        msg = ["⚡️ *[15M A.Aun SETUP TRIGGER]*", "────────────────────────"]
        msg.extend(triggers)
        msg.append("────────────────────────")
        msg.append("🎯 *Checklist 5M:* ดู Dashboard (UP/DOWN) ➔ รอย่อแตะ EMA 21/35 ➔ คุม SL สวิง 15M")
        send_telegram("\n".join(msg))

if __name__ == "__main__":
    main()
