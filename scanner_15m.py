import os
import sys
import requests
import pandas as pd
import warnings
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")
http = requests.Session()

# ======================== 1. CONFIGURATION & SECRETS ========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ใส่ Watchlist เต็ม 50 เหรียญตามระบบเทรดหลัก
WATCHLIST = [
    "BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSDT", "XRPUSDT",
    "ARKMUSDT", "FETUSDT", "NEARUSDT", "RENDERUSDT", "TAOUSDT", "WLDUSDT",
    "AAVEUSDT", "DYDXUSDT", "ENAUSDT", "JUPUSDT", "LINKUSDT", "ONDOUSDT", "PENDLEUSDT",
    "ADAUSDT", "APTUSDT", "ATOMUSDT", "AVAXUSDT", "DOTUSDT", "GRTUSDT", 
    "ICPUSDT", "INJUSDT", "KASUSDT", "PYTHUSDT", "SEIUSDT", "SUIUSDT",
    "ARBUSDT", "MANTAUSDT", "POLUSDT", "OPUSDT", "STRKUSDT", "TIAUSDT", "ZKUSDT",
    "DOGEUSDT", "GALAUSDT", "PEPEUSDT", "RUNEUSDT", "SANDUSDT", "SHIBUSDT",
    "BCHUSDT", "ETCUSDT", "LTCUSDT", "STXUSDT", "UNIUSDT", "ZECUSDT"
]

def format_grid(coins, cols=4):
    """จัดระเบียบตาราง 4 คอลัมน์ให้อ่านง่ายบนมือถือ"""
    if not coins: return "  • ไม่มี"
    rows = []
    for i in range(0, len(coins), cols):
        chunk = coins[i : i + cols]
        rows.append("  " + " ".join([f"`{c:<10}`" for c in chunk]))
    return "\n".join(rows)

# ======================== 2. DATA FETCHER ROUTER (15M) ========================
def get_binance_candles_15m(symbol, limit=200):
    if symbol == "XAUUSDT": return None
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=15m&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=15m&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = http.get(url, timeout=5).json()
            if isinstance(res, list) and len(res) >= 100:
                df = pd.DataFrame(res, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
                for col in ["high", "low", "close"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["high", "low", "close"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_gateio_candles_15m(symbol, limit=200):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    endpoints = [
        f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval=15m&limit={limit}",
        f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval=15m&limit={limit}"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in endpoints:
        try:
            res = http.get(url, headers=headers, timeout=5).json()
            if isinstance(res, list) and len(res) >= 100:
                records = []
                for item in res:
                    if isinstance(item, dict):
                        records.append({"timestamp": float(item.get("t", 0)), "high": float(item.get("h", 0)), "low": float(item.get("l", 0)), "close": float(item.get("c", 0))})
                    elif isinstance(item, list) and len(item) >= 6:
                        records.append({"timestamp": float(item[0]), "high": float(item[3]), "low": float(item[4]), "close": float(item[2])})
                if records:
                    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
                    return df[["high", "low", "close"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_kucoin_candles_15m(symbol):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    url = f"https://api.kucoin.com/api/v1/market/candles?type=15min&symbol={base_sym}-USDT"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = http.get(url, headers=headers, timeout=5).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= 100:
            records = [{"close": float(i[2]), "high": float(i[3]), "low": float(i[4])} for i in res["data"]]
            df = pd.DataFrame(records)
            return df.iloc[::-1].reset_index(drop=True)
    except: pass
    return None

def fetch_candles(symbol):
    df = get_binance_candles_15m(symbol)
    if df is not None: return df
    df = get_gateio_candles_15m(symbol)
    if df is not None: return df
    return get_kucoin_candles_15m(symbol)

# ======================== 3. ANALYSIS FUNCTION ========================
def analyze_15m_symbol(symbol):
    df = fetch_candles(symbol)
    if df is None or len(df) < 100: 
        return symbol, [], [], False

    events, pivots = [], []
    try:
        # ตัดแท่งปัจจุบันที่ยังไม่ปิดออก (ดึงเฉพาะแท่งที่ปิดสมบูรณ์)
        df_c = df.iloc[:-1].copy().reset_index(drop=True)
        n = len(df_c)
        if n < 90: return symbol, [], [], False

        # คำนวณ MACD (TradingView: SMA 9) และ EMA 89
        exp1 = df_c["close"].ewm(span=12, adjust=False).mean()
        exp2 = df_c["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.rolling(window=9).mean()
        ema89 = df_c["close"].ewm(span=89, adjust=False).mean()

        m_c, s_c = macd.iloc[-1], signal.iloc[-1]
        m_p, s_p = macd.iloc[-2], signal.iloc[-2]
        l_c, h_c = df_c["low"].iloc[-1], df_c["high"].iloc[-1]
        l_p, h_p = df_c["low"].iloc[-2], df_c["high"].iloc[-2]
        e_c, e_p = ema89.iloc[-1], ema89.iloc[-2]

        # MACD Events
        if m_p <= s_p and m_c > s_c: events.append("GOLDEN_CROSS")
        elif m_p >= s_p and m_c < s_c: events.append("DEATH_CROSS")
        if m_p <= 0 and m_c > 0: events.append("OVER_0")
        elif m_p >= 0 and m_c < 0: events.append("UNDER_0")

        # EMA 89 Touch
        if l_p > e_p and l_c <= e_c: events.append("TOUCH_SUPPORT")
        elif h_p < e_p and h_c >= e_c: events.append("TOUCH_RESIST")

        # Pivot Points (P10)
        highs = df_c["high"].tolist()
        lows = df_c["low"].tolist()
        ph, pl = [], []

        for i in range(10, n - 10):
            if all(highs[i] >= highs[i - k] for k in range(1, 11)) and all(highs[i] > highs[i + k] for k in range(1, 11)):
                ph.append((i, highs[i]))
            if all(lows[i] <= lows[i - k] for k in range(1, 11)) and all(lows[i] < lows[i + k] for k in range(1, 11)):
                pl.append((i, lows[i]))

        if len(ph) >= 2 and ph[-1][0] == (n - 11):
            pivots.append("HH" if ph[-1][1] > ph[-2][1] else "LH")
        if len(pl) >= 2 and pl[-1][0] == (n - 11):
            pivots.append("HL" if pl[-1][1] > pl[-2][1] else "LL")

        return symbol, events, pivots, True
    except Exception:
        return symbol, [], [], False

# ======================== 4. NOTIFICATION & MAIN ========================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Error: Missing Telegram Token/Chat ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        res = http.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            plain = message.replace("*", "").replace("`", "").replace("_", "")
            http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=10)
    except Exception as e:
        print(f"[!] Telegram Exception: {e}")

def main():
    print(f"🚀 เริ่มสแกน 15M (Watchlist: {len(WATCHLIST)} เหรียญ)...")
    results = {"GOLDEN_CROSS": [], "DEATH_CROSS": [], "OVER_0": [], "UNDER_0": [], "TOUCH_SUPPORT": [], "TOUCH_RESIST": [], "HH": [], "HL": [], "LH": [], "LL": []}
    failed = []

    # ใช้ ThreadPool สแกน 50 เหรียญพร้อมกัน (เสร็จภายใน 2-3 วินาที)
    with ThreadPoolExecutor(max_workers=10) as executor:
        for symbol, evs, pvs, success in executor.map(analyze_15m_symbol, WATCHLIST):
            if not success: failed.append(symbol)
            for ev in evs: results[ev].append(symbol)
            for pv in pvs: results[pv].append(symbol)

    for key in results: results[key].sort()

    msg = [
        "⚡️ *[15M SCANNER & STRUCTURE]*",
        "────────────────────────────",
        "🟢 *GOLDEN CROSS :* ➔ ซูม 5M หาจังหวะ BUY", format_grid(results["GOLDEN_CROSS"]), "",
        "🔴 *DEATH CROSS  :* ➔ ซูม 5M หาจังหวะ SELL", format_grid(results["DEATH_CROSS"]), "",
        "🚀 *OVER 0        :* ➔ โมเมนตัมขึ้นแข็งแกร่ง", format_grid(results["OVER_0"]), "",
        "🔻 *UNDER 0       :* ➔ โมเมนตัมลงแข็งแกร่ง", format_grid(results["UNDER_0"]),
        "────────────────────────────",
        "🎯 *EMA 89 TOUCH :*",
        "📥 *แตะรับ        :* ➔ ซูม 5M ดูแท่งกลับตัวโซนรับ", format_grid(results["TOUCH_SUPPORT"]), "",
        "📤 *แตะต้าน      :* ➔ ซูม 5M ดูแท่งกลับตัวโซนต้าน", format_grid(results["TOUCH_RESIST"]),
        "────────────────────────────",
        "📐 *PIVOT (P10)  :*",
        "📈 *HH            :* ➔ ห้ามไล่ รอ 15M ทำ HL", format_grid(results["HH"]), "",
        "🔼 *HL            :* ➔ ย่อจบ ซูม 5M เคาะ BUY", format_grid(results["HL"]), "",
        "📉 *LH            :* ➔ เด้งจบ ซูม 5M เคาะ SELL", format_grid(results["LH"]), "",
        "🔽 *LL            :* ➔ ห้ามตาม รอ 15M เด้งทำ LH", format_grid(results["LL"]),
        "────────────────────────────",
        "📌 *Check:* 4H เมฆ ➔ 15M Signal ➔ 5M Entry"
    ]

    if failed:
        msg.append(f"\n⚠️ *API Failed ({len(failed)} เหรียญ):* `{', '.join(failed[:10])}`")

    send_telegram("\n".join(msg))
    print("✅ สแกน 15M เสร็จสิ้นและส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
