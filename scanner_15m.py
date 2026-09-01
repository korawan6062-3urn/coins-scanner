import os
import sys
import requests
import pandas as pd
import warnings
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")
http = requests.Session()
http.headers.update({"User-Agent": "Mozilla/5.0"})

# ======================== 1. CONFIGURATION & SECRETS ========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 📋 WATCHLIST 50 ASSETS (Alphabetical A-Z)
WATCHLIST = [
    "AAVEUSDT", "ADAUSDT",  "APTUSDT",  "ARBUSDT",  "ARKMUSDT",
    "ATOMUSDT", "AVAXUSDT", "BCHUSDT",  "BNBUSDT",  "BTCUSDT",
    "DOGEUSDT", "DOTUSDT",  "DYDXUSDT", "ENAUSDT",  "ETCUSDT",
    "ETHUSDT",  "FETUSDT",  "GALAUSDT", "GRTUSDT",  "ICPUSDT",
    "INJUSDT",  "JUPUSDT",  "KASUSDT",  "LINKUSDT", "LTCUSDT",
    "MANTAUSDT","NEARUSDT", "ONDOUSDT", "OPUSDT",   "PENDLEUSDT",
    "PEPEUSDT", "POLUSDT",  "PYTHUSDT", "RENDERUSDT","RUNEUSDT",
    "SANDUSDT", "SEIUSDT",  "SHIBUSDT", "SOLUSDT",  "STRKUSDT",
    "STXUSDT",  "SUIUSDT",  "TAOUSDT",  "TIAUSDT",  "UNIUSDT",
    "WLDUSDT",  "XAUUSDT",  "XRPUSDT",  "ZECUSDT",  "ZKUSDT"
]

def format_grid(coins, cols=3):
    """จัดระเบียบตาราง 3 คอลัมน์ ความกว้าง 11 ตัวอักษร เพื่อเว้นช่องไฟให้สวยงาม"""
    if not coins: 
        return "  • ไม่มี"
    rows = []
    for i in range(0, len(coins), cols):
        chunk = coins[i : i + cols]
        rows.append("  " + " ".join([f"`{c:<11}`" for c in chunk]))
    return "\n".join(rows)

# ======================== 2. DATA FETCHER ROUTER (15M) ========================
def get_binance_candles_15m(symbol, limit=500):
    if symbol == "XAUUSDT": 
        return None
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
                for col in ["open", "high", "low", "close"]: 
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close"]].dropna().reset_index(drop=True)
        except Exception: 
            continue
    return None

def get_gateio_candles_15m(symbol, limit=500):
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
                        records.append({"timestamp": float(item.get("t", 0)), "open": float(item.get("o", 0)), "high": float(item.get("h", 0)), "low": float(item.get("l", 0)), "close": float(item.get("c", 0))})
                    elif isinstance(item, list) and len(item) >= 6:
                        records.append({"timestamp": float(item[0]), "open": float(item[5]), "high": float(item[3]), "low": float(item[4]), "close": float(item[2])})
                if records:
                    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
                    return df[["open", "high", "low", "close"]].dropna().reset_index(drop=True)
        except Exception: 
            continue
    return None

def get_kucoin_candles_15m(symbol, limit=500):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    url = f"https://api.kucoin.com/api/v1/market/candles?type=15min&symbol={base_sym}-USDT&pageSize={limit}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = http.get(url, headers=headers, timeout=5).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= 100:
            records = [{"open": float(i[1]), "close": float(i[2]), "high": float(i[3]), "low": float(i[4])} for i in res["data"]]
            df = pd.DataFrame(records)
            return df.iloc[::-1].reset_index(drop=True)
    except Exception: 
        pass
    return None

def fetch_candles(symbol):
    df = get_binance_candles_15m(symbol)
    if df is not None: 
        return df
    df = get_gateio_candles_15m(symbol)
    if df is not None: 
        return df
    return get_kucoin_candles_15m(symbol)

# ======================== 3. ANALYSIS FUNCTION (PURE LOGIC) ========================
def analyze_15m_symbol(symbol):
    df = fetch_candles(symbol)
    if df is None or len(df) < 250: 
        return symbol, [], False

    events = []
    try:
        # ตัดแท่งปัจจุบันที่ยังไม่ปิดออก ตรวจสอบเฉพาะแท่งที่ปิดสมบูรณ์แล้วล่าสุด
        df_c = df.iloc[:-1].copy().reset_index(drop=True)
        
        # ------------------ 1. EMA Calculations ------------------
        ema21_s = df_c["close"].ewm(span=21, adjust=False).mean()
        ema35_s = df_c["close"].ewm(span=35, adjust=False).mean()
        
        e21_c, e35_c = float(ema21_s.iloc[-1]), float(ema35_s.iloc[-1])
        e21_p, e35_p = float(ema21_s.iloc[-2]), float(ema35_s.iloc[-2])

        # ------------------ 2. MACD Balance v3.0 Calculations ------------------
        exp1 = df_c["close"].ewm(span=12, adjust=False).mean()
        exp2 = df_c["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.rolling(window=9).mean()  # SMA 9
        
        m_c = float(macd.iloc[-1])
        m_p = float(macd.iloc[-2])

        # ------------------ 3. Candle Data ------------------
        o_c, c_c = float(df_c["open"].iloc[-1]), float(df_c["close"].iloc[-1])
        h_c, l_c = float(df_c["high"].iloc[-1]), float(df_c["low"].iloc[-1])
        o_p, c_p = float(df_c["open"].iloc[-2]), float(df_c["close"].iloc[-2])

        # ------------------ 4. Filters ------------------
        # 4.1 Pure EMA Anti-Saw (Lookback 16, Cross >= 2 = Choppy | ตัด Squeeze ทิ้ง 100%)
        ema_cross_sig = (ema21_s > ema35_s).astype(int)
        cross_count_ema = int((ema_cross_sig.diff().abs() > 0).iloc[-17:-1].sum())
        is_ema_choppy = cross_count_ema >= 2

        # 4.2 MACD Balance 3.0 Anti-Sawtooth (Lookback 10 Bars, Cross Signal > 1 = Choppy)
        P15_SAW = 10
        macd_cross_sig = (macd > signal).astype(int)
        macd_choppy_count = int((macd_cross_sig.diff().abs() > 0).iloc[-(P15_SAW+1):-1].sum())
        is_macd_choppy = macd_choppy_count > 1

        # ================== 5. Trigger Evaluation ==================

        # ⚡️ 1. EMA MOMENTUM CROSS (เพิ่งตัดสลับขั้ว 21x35 ในแท่งล่าสุด + ผ่าน Pure Anti-Saw)
        if not is_ema_choppy:
            if e21_c > e35_c and e21_p <= e35_p:
                events.append("EMA_BUY")
            elif e21_c < e35_c and e21_p >= e35_p:
                events.append("EMA_SELL")

        # 🌊 2. MACD ZERO-STATION (Peak 0.20 / Mean 0.75 / Lookback 48 / Fresh Trigger)
        if not is_macd_choppy:
            P15_LOOKBACK = 48
            P15_PEAK = 0.20
            P15_MEAN = 0.75
            
            macd_window = macd.iloc[-(P15_LOOKBACK+1):-1]
            macd_peak = float(macd_window.max())
            macd_trough = float(macd_window.min())
            macd_mean = float(macd_window.mean())

            curr_zero_buy = (m_c > 0) and ((m_c <= macd_peak * P15_PEAK) or (m_c <= macd_mean * P15_MEAN))
            curr_zero_sell = (m_c < 0) and ((m_c >= macd_trough * P15_PEAK) or (m_c >= macd_mean * P15_MEAN))

            prev_zero_buy = (m_p > 0) and ((m_p <= macd_peak * P15_PEAK) or (m_p <= macd_mean * P15_MEAN))
            prev_zero_sell = (m_p < 0) and ((m_p >= macd_trough * P15_PEAK) or (m_p >= macd_mean * P15_MEAN))

            # Fresh Entry: เพิ่งดึงกลับเข้าสู่โซนสมดุลในแท่งล่าสุด
            if curr_zero_buy and not prev_zero_buy:
                events.append("MACD_BUY")
            elif curr_zero_sell and not prev_zero_sell:
                events.append("MACD_SELL")

        # 🕯 3. FRESH CANDLESTICK & FALSE BREAK PATTERNS (เพิ่งปิดแท่งล่าสุด)
        body = abs(c_c - o_c)
        total_range = h_c - l_c
        upper_wick = h_c - max(o_c, c_c)
        lower_wick = min(o_c, c_c) - l_c
        
        if total_range > 0 and body > (total_range * 0.1):
            if lower_wick >= (2 * body) and upper_wick <= (0.2 * total_range):
                events.append("PA_HAMMER")
            elif upper_wick >= (2 * body) and lower_wick <= (0.2 * total_range):
                events.append("PA_SHOOTING_STAR")

        body_p = abs(c_p - o_p)
        if body > body_p:
            if c_p < o_p and c_c > o_c and c_c >= o_p and o_c <= c_p:
                events.append("PA_BULL_ENGULF")
            elif c_p > o_p and c_c < o_c and c_c <= o_p and o_c >= c_p:
                events.append("PA_BEAR_ENGULF")

        return symbol, events, True
    except Exception:
        return symbol, [], False

# ======================== 4. NOTIFICATION & MAIN ========================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Error: Missing Telegram Token/Chat ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown", 
        "disable_web_page_preview": True
    }
    try:
        res = http.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            plain = message.replace("*", "").replace("`", "").replace("_", "")
            http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=10)
    except Exception as e:
        print(f"[!] Telegram Exception: {e}")

def main():
    print(f"🚀 เริ่มสแกน 15M A.AUN HYBRID SCANNER (Watchlist: {len(WATCHLIST)} เหรียญ)...")
    results = {
        "EMA_BUY": [], "EMA_SELL": [], 
        "MACD_BUY": [], "MACD_SELL": [], 
        "PA_HAMMER": [], "PA_SHOOTING_STAR": [],
        "PA_BULL_ENGULF": [], "PA_BEAR_ENGULF": []
    }
    failed = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        for symbol, evs, success in executor.map(analyze_15m_symbol, WATCHLIST):
            if not success: 
                failed.append(symbol)
            else:
                for ev in evs: 
                    results[ev].append(symbol)

    for key in results: 
        results[key].sort()

    msg = [
        "⚡️ *[15M A.AUN HYBRID SCANNER]*",
        "────────────────────────────",
        "⚡️ *1. EMA MOMENTUM (เพิ่งตัด 21x35)*",
        "🟢 *BUY (21 ตัดขึ้น 35)  :*", format_grid(results["EMA_BUY"]), "",
        "🔴 *SELL(21 ตัดลง 35)   :*", format_grid(results["EMA_SELL"]),
        "────────────────────────────",
        "🌊 *2. MACD ZERO-STATION (ย่อ/เด้งแตะ 0)*",
        "🟢 *BUY (ย่อแตะ 0)      :*", format_grid(results["MACD_BUY"]), "",
        "🔴 *SELL(เด้งแตะ 0)     :*", format_grid(results["MACD_SELL"]),
        "────────────────────────────",
        "🕯 *3. CANDLESTICK & FALSE BREAK*",
        "🔨 *Hammer (ดักกลับตัวขึ้น):*", format_grid(results["PA_HAMMER"]), "",
        "💫 *Shooting Star (ดักลง):*", format_grid(results["PA_SHOOTING_STAR"]), "",
        "🔥 *Bullish Engulfing  :*", format_grid(results["PA_BULL_ENGULF"]), "",
        "🩸 *Bearish Engulfing  :*", format_grid(results["PA_BEAR_ENGULF"])
    ]

    if failed:
        msg.append(f"\n⚠️ *API Failed ({len(failed)} เหรียญ):* `{', '.join(failed[:10])}`")

    send_telegram("\n".join(msg))
    print("✅ สแกน 15M เสร็จสิ้นและส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
