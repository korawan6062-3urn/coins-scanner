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

def format_grid(coins, cols=3):
    """จัดระเบียบตาราง 3 คอลัมน์ ความกว้าง 11 ตัวอักษร เพื่อเว้นช่องไฟให้สวยงาม"""
    if not coins: return "  • ไม่มี"
    rows = []
    for i in range(0, len(coins), cols):
        chunk = coins[i : i + cols]
        # จัด Format ให้มีความกว้าง 11 ตัวอักษรและชิดซ้าย
        rows.append("  " + " ".join([f"`{c:<11}`" for c in chunk]))
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
                for col in ["open", "high", "low", "close"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close"]].dropna().reset_index(drop=True)
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
                        records.append({"timestamp": float(item.get("t", 0)), "open": float(item.get("o", 0)), "high": float(item.get("h", 0)), "low": float(item.get("l", 0)), "close": float(item.get("c", 0))})
                    elif isinstance(item, list) and len(item) >= 6:
                        records.append({"timestamp": float(item[0]), "open": float(item[5]), "high": float(item[3]), "low": float(item[4]), "close": float(item[2])})
                if records:
                    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
                    return df[["open", "high", "low", "close"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_kucoin_candles_15m(symbol):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    url = f"https://api.kucoin.com/api/v1/market/candles?type=15min&symbol={base_sym}-USDT"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = http.get(url, headers=headers, timeout=5).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= 100:
            records = [{"open": float(i[1]), "close": float(i[2]), "high": float(i[3]), "low": float(i[4])} for i in res["data"]]
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

# ======================== 3. ANALYSIS FUNCTION (STANDALONE 15M) ========================
def analyze_15m_symbol(symbol):
    df = fetch_candles(symbol)
    if df is None or len(df) < 100: 
        return symbol, [], [], False

    events, pivots = [], []
    try:
        # ตัดแท่งปัจจุบันที่ยังไม่ปิดสมบูรณ์ออก
        df_c = df.iloc[:-1].copy().reset_index(drop=True)
        n = len(df_c)
        if n < 90: return symbol, [], [], False

        # ------------------ Indicator Calculation ------------------
        # MACD (12, 26, 9)
        exp1 = df_c["close"].ewm(span=12, adjust=False).mean()
        exp2 = df_c["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.rolling(window=9).mean()
        
        # EMAs
        ema21 = df_c["close"].ewm(span=21, adjust=False).mean()
        ema35 = df_c["close"].ewm(span=35, adjust=False).mean()
        ema89 = df_c["close"].ewm(span=89, adjust=False).mean()

        m_c = float(macd.iloc[-1])
        c_c = float(df_c["close"].iloc[-1])
        o_c = float(df_c["open"].iloc[-1])
        l_c, h_c = float(df_c["low"].iloc[-1]), float(df_c["high"].iloc[-1])
        l_p, h_p = float(df_c["low"].iloc[-2]), float(df_c["high"].iloc[-2])

        # ------------------ CHOPPY FILTER (Anti-Sawtooth 15M) ------------------
        # พารามิเตอร์ 15M: Anti-Sawtooth = 10 Bars
        P15_SAW = 10
        cross_sig = (macd > signal).astype(int)
        choppy_count = int((cross_sig.diff().abs() > 0).iloc[-(P15_SAW+1):-1].sum())
        is_choppy = choppy_count > 1

        # ------------------ 1. MACD ZERO-STATION (15M Parameters) ------------------
        # ถ้าติด Chop (is_choppy) จะข้ามการประเมิน Zero-Station ทันที และไม่เพิ่มลง events
        if not is_choppy:
            # พารามิเตอร์ 15M (อิงจากภาพ)
            P15_LOOKBACK = 48
            P15_PEAK = 0.20
            P15_MEAN = 0.75
            
            macd_window = macd.iloc[-(P15_LOOKBACK+1):-1]
            macd_peak = float(macd_window.max())
            macd_trough = float(macd_window.min())
            macd_mean = float(macd_window.mean())
            
            # Zero-Buy Approved: MACD > 0 และย่อลงมาต่ำกว่า Peak/Mean
            zero_buy_approved = (m_c > 0) and ((m_c <= macd_peak * P15_PEAK) or (m_c <= macd_mean * P15_MEAN))
            
            # Zero-Sell Approved: MACD < 0 และเด้งขึ้นมาสูงกว่า Trough/Mean
            zero_sell_approved = (m_c < 0) and ((m_c >= macd_trough * P15_PEAK) or (m_c >= macd_mean * P15_MEAN))

            if zero_buy_approved: events.append("ZERO_BUY")
            if zero_sell_approved: events.append("ZERO_SELL")

        # ------------------ 2. DYNAMIC RETEST (EMA TOUCH) ------------------
        if not is_choppy:
            cloud_top = max(float(ema21.iloc[-1]), float(ema35.iloc[-1]))
            cloud_bot = min(float(ema21.iloc[-1]), float(ema35.iloc[-1]))
            cloud_top_p = max(float(ema21.iloc[-2]), float(ema35.iloc[-2]))
            cloud_bot_p = min(float(ema21.iloc[-2]), float(ema35.iloc[-2]))

            if l_p > cloud_top_p and l_c <= cloud_top and c_c >= cloud_bot: 
                events.append("TOUCH_CLOUD")
            elif h_p < cloud_bot_p and h_c >= cloud_bot and c_c <= cloud_top:
                events.append("TOUCH_CLOUD")

            e89_c, e89_p = float(ema89.iloc[-1]), float(ema89.iloc[-2])
            if l_p > e89_p and l_c <= e89_c and c_c >= e89_c: 
                events.append("TOUCH_89")
            elif h_p < e89_p and h_c >= e89_c and c_c <= e89_c:
                events.append("TOUCH_89")

        # ------------------ 3. DIVERGENCE DETECTOR (2-Peak Simple) ------------------
        window_size = 30
        recent_macd = macd.iloc[-window_size:]
        recent_close = df_c["close"].iloc[-window_size:]
        
        if l_c <= float(recent_close.min()) and m_c > float(recent_macd.min()):
            events.append("DIV_BULL")
        elif h_c >= float(recent_close.max()) and m_c < float(recent_macd.max()):
            events.append("DIV_BEAR")

        # ------------------ 4. FALSE BREAK (ดักกิน SL) ------------------
        prev_h = float(df_c["high"].iloc[-3:-1].max())
        prev_l = float(df_c["low"].iloc[-3:-1].min())
        
        body_size = abs(c_c - o_c)
        
        if h_c > prev_h and c_c < prev_h and (h_c - max(o_c, c_c)) > (body_size * 2):
            pivots.append("FAKE_HIGH")
        if l_c < prev_l and c_c > prev_l and (min(o_c, c_c) - l_c) > (body_size * 2):
            pivots.append("FAKE_LOW")

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
    print(f"🚀 เริ่มสแกน 15M AUN-HYBRID RULES (Watchlist: {len(WATCHLIST)} เหรียญ)...")
    results = {
        "ZERO_BUY": [], "ZERO_SELL": [], 
        "TOUCH_CLOUD": [], "TOUCH_89": [], 
        "DIV_BULL": [], "DIV_BEAR": [], 
        "FAKE_HIGH": [], "FAKE_LOW": []
    }
    failed = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        for symbol, evs, pvs, success in executor.map(analyze_15m_symbol, WATCHLIST):
            if not success: failed.append(symbol)
            for ev in evs: results[ev].append(symbol)
            for pv in pvs: results[pv].append(symbol)

    for key in results: results[key].sort()

    msg = [
        "⚡️ *[15M A.AUN HYBRID SCANNER]*",
        "────────────────────────────",
        "🌊 *1. MACD ZERO-STATION*",
        "🟢 *BUY (ย่อแตะ 0)  :*", format_grid(results["ZERO_BUY"]), "",
        "🔴 *SELL(เด้งแตะ 0)*: ", format_grid(results["ZERO_SELL"]),
        "────────────────────────────",
        "🛡 *2. DYNAMIC RETEST*",
        "☁️ *แตะเมฆ (21/35) :*", format_grid(results["TOUCH_CLOUD"]), "",
        "🎯 *แตะเส้น EMA 89 :*", format_grid(results["TOUCH_89"]),
        "────────────────────────────",
        "⚠️ *3. DIVERGENCE*",
        "🟢 *Bullish (15M)  :*", format_grid(results["DIV_BULL"]), "",
        "🔴 *Bearish (15M)  :*", format_grid(results["DIV_BEAR"]),
        "────────────────────────────",
        "🪤 *4. FALSE BREAK*",
        "📉 *Fake Low (SL)  :*", format_grid(results["FAKE_LOW"]), "",
        "📈 *Fake High (SL) :*", format_grid(results["FAKE_HIGH"])
    ]

    if failed:
        msg.append(f"\n⚠️ *API Failed ({len(failed)} เหรียญ):* `{', '.join(failed[:10])}`")

    send_telegram("\n".join(msg))
    print("✅ สแกน 15M เสร็จสิ้นและส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
