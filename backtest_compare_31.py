import requests
import pandas as pd
import numpy as np
import time

WATCHLIST = sorted([
    "AAVE", "ADA", "APT", "AVAX", "BCH",
    "BNB", "BTC", "DOT", "ENA", "ETH",
    "FET", "INJ", "JTO", "KAS", "LDO",
    "LINK", "LTC", "NEAR", "ONDO", "PAXG",
    "PENDLE", "RENDER", "SEI", "SOL", "SUI",
    "TAO", "TIA", "TRX", "UNI", "XLM", "XRP"
])

def get_historical_candles(coin, interval="15m", limit=1000):
    """ดึงข้อมูลกราฟย้อนหลัง 15M"""
    try:
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval={interval}&limit={limit}"
        res = requests.get(url, timeout=7).json()
        if isinstance(res, list) and len(res) >= 200:
            df = pd.DataFrame(res, columns=["time", "volume", "close", "high", "low", "open"])
            df["time"] = pd.to_numeric(df["time"], errors="coerce")
            df = df.sort_values(by="time").reset_index(drop=True)
            for col in ["close", "high", "low", "open"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df.dropna().reset_index(drop=True)
    except Exception:
        pass
    return None

def run_backtest_for_coin(coin):
    df_15m = get_historical_candles(coin, interval="15m", limit=1000)
    if df_15m is None or len(df_15m) < 250:
        return None

    # สร้างแท่ง 4H จาก 15M (16 แท่ง 15M = 1 แท่ง 4H)
    df_15m["bar_4h"] = np.arange(len(df_15m)) // 16
    df_4h = df_15m.groupby("bar_4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last"
    }).reset_index()

    # 4H Indicators (Ichimoku + EMA 89)
    df_4h["ema89"] = df_4h["close"].ewm(span=89, adjust=False).mean()
    tenkan = (df_4h["high"].rolling(9).max() + df_4h["low"].rolling(9).min()) / 2
    kijun = (df_4h["high"].rolling(26).max() + df_4h["low"].rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((df_4h["high"].rolling(52).max() + df_4h["low"].rolling(52).min()) / 2).shift(26)
    df_4h["top_kumo"] = np.maximum(span_a, span_b)
    df_4h["bot_kumo"] = np.minimum(span_a, span_b)

    trend_4h = []
    for idx in range(len(df_4h)):
        c, e, tk, bk = df_4h["close"].iloc[idx], df_4h["ema89"].iloc[idx], df_4h["top_kumo"].iloc[idx], df_4h["bot_kumo"].iloc[idx]
        if pd.notna(tk) and pd.notna(bk):
            if c > tk and c > e: trend_4h.append("BUY")
            elif c < bk and c < e: trend_4h.append("SELL")
            else: trend_4h.append("UNKNOWN")
        else:
            trend_4h.append("UNKNOWN")

    df_4h["trend_4h"] = trend_4h
    df_4h["trend_lag"] = df_4h["trend_4h"].shift(1)
    map_trend = df_4h.set_index("bar_4h")["trend_lag"].to_dict()
    df_15m["trend_4h"] = df_15m["bar_4h"].map(map_trend).fillna("UNKNOWN")

    # 15M MACD (12, 26, SMA 9)
    fast = df_15m["close"].ewm(span=12, adjust=False).mean()
    slow = df_15m["close"].ewm(span=26, adjust=False).mean()
    df_15m["macd"] = fast - slow
    df_15m["signal"] = df_15m["macd"].rolling(window=9).mean()

    std_trades = []
    aaun_trades = []

    for i in range(120, len(df_15m) - 30):
        t4h = df_15m["trend_4h"].iloc[i]
        if t4h == "UNKNOWN":
            continue

        m_prev, m_now = df_15m["macd"].iloc[i-1], df_15m["macd"].iloc[i]
        s_prev, s_now = df_15m["signal"].iloc[i-1], df_15m["signal"].iloc[i]
        c_now = df_15m["close"].iloc[i]

        is_gc = (m_prev <= s_prev) and (m_now > s_now)
        is_dc = (m_prev >= s_prev) and (m_now < s_now)

        # 1. ฝั่ง BUY (LONG)
        if t4h == "BUY" and is_gc:
            sl = df_15m["low"].iloc[i-6:i+1].min()
            risk = c_now - sl
            if risk > 0:
                tp = c_now + (risk * 1.5)
                win = False
                for f in range(i+1, min(i+35, len(df_15m))):
                    if df_15m["high"].iloc[f] >= tp:
                        win = True
                        break
                    elif df_15m["low"].iloc[f] <= sl:
                        win = False
                        break
                std_trades.append(win)
                if m_now < 0:  # A.Aun Filter: ตัดใต้ 0 เท่านั้น
                    aaun_trades.append(win)

        # 2. ฝั่ง SELL (SHORT)
        elif t4h == "SELL" and is_dc:
            sl = df_15m["high"].iloc[i-6:i+1].max()
            risk = sl - c_now
            if risk > 0:
                tp = c_now - (risk * 1.5)
                win = False
                for f in range(i+1, min(i+35, len(df_15m))):
                    if df_15m["low"].iloc[f] <= tp:
                        win = True
                        break
                    elif df_15m["high"].iloc[f] >= sl:
                        win = False
                        break
                std_trades.append(win)
                if m_now > 0:  # A.Aun Filter: ตัดเหนือ 0 เท่านั้น
                    aaun_trades.append(win)

    n_std = len(std_trades)
    wr_std = (sum(std_trades) / n_std * 100) if n_std > 0 else 0

    n_aaun = len(aaun_trades)
    wr_aaun = (sum(aaun_trades) / n_aaun * 100) if n_aaun > 0 else 0

    return {
        "Coin": coin,
        "Std Trades": n_std,
        "Std WR (%)": round(wr_std, 1),
        "A.Aun Trades": n_aaun,
        "A.Aun WR (%)": round(wr_aaun, 1),
        "Diff (%)": round(wr_aaun - wr_std, 1)
    }

def main():
    print("⏳ กำลังเริ่มทำการทดสอบย้อนหลังเปรียบเทียบทั้ง 31 เหรียญ...")
    results = []
    for coin in WATCHLIST:
        res = run_backtest_for_coin(coin)
        time.sleep(0.04)
        if res:
            results.append(res)

    res_df = pd.DataFrame(results)
    print("\n" + "="*80)
    print("📊 รายงานเปรียบเทียบ WIN RATE: Standard 15M vs A.Aun Zone Setup (31 COINS)")
    print("="*80)
    print(res_df.to_string(index=False))
    print("="*80)

    avg_std_wr = res_df["Std WR (%)"].mean()
    avg_aaun_wr = res_df["A.Aun WR (%)"].mean()
    tot_std_trades = res_df["Std Trades"].sum()
    tot_aaun_trades = res_df["A.Aun Trades"].sum()

    print(f"\n📌 สรุปเปรียบเทียบภาพรวม:")
    print(f"• จำนวนไม้แบบเดิม: {tot_std_trades} ไม้  |  Win Rate: {avg_std_wr:.2f}%")
    print(f"• จำนวนไม้แบบ A.Aun: {tot_aaun_trades} ไม้  |  Win Rate: {avg_aaun_wr:.2f}%")
    print(f"• สรุป: ระบบ A.Aun กรองสัญญาณหลอกทิ้ง {((tot_std_trades - tot_aaun_trades)/tot_std_trades)*100:.1f}% และเพิ่ม Win Rate เฉลี่ย +{avg_aaun_wr - avg_std_wr:.2f}%")

if __name__ == "__main__":
    main()
