import os
import time
import requests
import pandas as pd

# ======================== 1. CONFIGURATION & SECRETS ========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

WATCHLIST = [
    # --- Tier A (Core Blue Chips & Macro | เรียง A-Z) ---
    "BNBUSDT",
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XAUUSDT",
    "XRPUSDT",

    # --- DeFi & Real World Assets (เรียง A-Z) ---
    "AAVEUSDT",
    "ENAUSDT",
    "JUPUSDT",
    "LINKUSDT",
    "ONDOUSDT",
    "PENDLEUSDT",
    "UNIUSDT",

    # --- AI & Decentralized Compute (เรียง A-Z) ---
    "FETUSDT",
    "NEARUSDT",
    "RENDERUSDT",
    "TAOUSDT",
    "WLDUSDT",

    # --- Layer 1 & Modular (เรียง A-Z) ---
    "INJUSDT",
    "SEIUSDT",
    "SUIUSDT",
    "TIAUSDT",

    # --- Legacy & เพิ่มเติม (เรียง A-Z) ---
    "LTCUSDT",
    "ZECUSDT",
]

# ======================== 2. DATA FETCHER ROUTER (15M) ========================
def get_binance_candles_15m(symbol):
    """ดึงแท่งเทียน 15M จาก Binance (ข้าม XAUUSDT อัตโนมัติ)"""
    if symbol == "XAUUSDT":
        return None

    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=200",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=15m&limit=200",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=15m&limit=200"
    ]
    for url in endpoints:
        try:
            res = requests.get(url, timeout=8).json()
            if isinstance(res, list) and len(res) >= 100:
                df = pd.DataFrame(res, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"
                ])
                for col in ["high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["high", "low", "close"]].dropna().reset_index(drop=True)
        except Exception:
            continue
    return None

def get_gateio_candles_15m(symbol, limit=150):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    endpoints = [
        f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval=15m&limit={limit}",
        f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval=15m&limit={limit}"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in endpoints:
        try:
            res = requests.get(url, headers=headers, timeout=6).json()
            if isinstance(res, list) and len(res) >= 60:
                records = []
                for item in res:
                    if isinstance(item, dict):
                        records.append({
                            "timestamp": float(item.get("t", 0)),
                            "open": float(item.get("o", 0)),
                            "high": float(item.get("h", 0)),
                            "low": float(item.get("l", 0)),
                            "close": float(item.get("c", 0))
                        })
                    elif isinstance(item, list) and len(item) >= 6:
                        records.append({
                            "timestamp": float(item[0]),
                            "open": float(item[5]),
                            "high": float(item[3]),
                            "low": float(item[4]),
                            "close": float(item[2])
                        })
                if records:
                    df = pd.DataFrame(records)
                    # จัดเรียงแท่งเทียนจากอดีตไปปัจจุบัน
                    df = df.sort_values("timestamp").reset_index(drop=True)
                    return df[["open", "high", "low", "close"]].dropna().reset_index(drop=True)
        except Exception:
            continue
    return None

# สร้าง alias กันพลาดในกรณีที่จุดอื่นเรียกชื่อสั้น
get_gateio_candles = get_gateio_candles_15m

def get_kucoin_candles_15m(symbol):
    """ดึงแท่งเทียน 15M จาก KuCoin Public API"""
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    url = f"https://api.kucoin.com/api/v1/market/candles?type=15min&symbol={base_sym}-USDT"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=8).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= 100:
            records = [{"close": float(i[2]), "high": float(i[3]), "low": float(i[4])} for i in res["data"]]
            df = pd.DataFrame(records)
            return df.iloc[::-1].reset_index(drop=True)
    except Exception as e:
        print(f"[!] KuCoin API Error ({symbol}): {e}")
    return None

def get_market_candles_15m(symbol):
    """Router ดึงข้อมูล 15M: Binance -> Gate.io -> KuCoin"""
    df = get_binance_candles_15m(symbol)
    if df is not None:
        return df

    df = get_gateio_candles_15m(symbol)
    if df is not None:
        return df

    df = get_kucoin_candles_15m(symbol)
    return df

# ======================== 3. ANALYSIS FUNCTIONS ========================
def analyze_macd_and_ema(df):
    """คำนวณ MACD (12, 26, 9) และ EMA 89 บนแท่งที่ปิดสมบูรณ์แล้ว"""
    try:
        exp1 = df["close"].ewm(span=12, adjust=False).mean()
        exp2 = df["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        ema89 = df["close"].ewm(span=89, adjust=False).mean()

        m_curr, s_curr = macd.iloc[-2], signal.iloc[-2]
        m_prev, s_prev = macd.iloc[-3], signal.iloc[-3]

        low_curr, high_curr = df["low"].iloc[-2], df["high"].iloc[-2]
        low_prev, high_prev = df["low"].iloc[-3], df["high"].iloc[-3]
        ema_curr = ema89.iloc[-2]
        ema_prev = ema89.iloc[-3]

        events = []

        # 1. MACD Cross
        if m_prev <= s_prev and m_curr > s_curr:
            events.append("GOLDEN_CROSS")
        elif m_prev >= s_prev and m_curr < s_curr:
            events.append("DEATH_CROSS")

        # 2. MACD Zero Line
        if m_prev <= 0 and m_curr > 0:
            events.append("OVER_0")
        elif m_prev >= 0 and m_curr < 0:
            events.append("UNDER_0")

        # 3. EMA 89 Re-test
        if low_prev > ema_prev and low_curr <= ema_curr:
            events.append("TOUCH_SUPPORT")
        elif high_prev < ema_prev and high_curr >= ema_curr:
            events.append("TOUCH_RESIST")

        return events
    except Exception:
        return []

def analyze_pivots(df, left=10, right=10):
    """ตรวจจับ Pivot Structure Period 10 (HH, HL, LH, LL)"""
    try:
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        n = len(df)

        pivot_highs = []
        pivot_lows = []

        for i in range(left, n - right):
            if all(highs[i] >= highs[i - k] for k in range(1, left + 1)) and \
               all(highs[i] > highs[i + k] for k in range(1, right + 1)):
                pivot_highs.append((i, highs[i]))

            if all(lows[i] <= lows[i - k] for k in range(1, left + 1)) and \
               all(lows[i] < lows[i + k] for k in range(1, right + 1)):
                pivot_lows.append((i, lows[i]))

        events = []

        if len(pivot_highs) >= 2:
            curr_ph = pivot_highs[-1][1]
            prev_ph = pivot_highs[-2][1]
            ph_idx = pivot_highs[-1][0]
            if ph_idx == (n - right - 1):
                events.append("HH" if curr_ph > prev_ph else "LH")

        if len(pivot_lows) >= 2:
            curr_pl = pivot_lows[-1][1]
            prev_pl = pivot_lows[-2][1]
            pl_idx = pivot_lows[-1][0]
            if pl_idx == (n - right - 1):
                events.append("HL" if curr_pl > prev_pl else "LL")

        return events
    except Exception:
        return []

# ======================== 4. NOTIFICATION ========================
def send_telegram(message):
    """ส่งข้อความเข้า Telegram พร้อม Fallback Plain Text"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Error: ไม่พบ Secret Telegram")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            plain = message.replace("*", "").replace("`", "").replace("_", "")
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=10)
        print("Telegram sent successfully.")
    except Exception as e:
        print(f"[!] Telegram Exception: {e}")

# ======================== 5. MAIN EXECUTION ========================
def main():
    print("🚀 สแกน 15M MACD, EMA 89 & Pivots (Clean Build)...")

    results = {
        "GOLDEN_CROSS": [],
        "DEATH_CROSS": [],
        "OVER_0": [],
        "UNDER_0": [],
        "TOUCH_SUPPORT": [],
        "TOUCH_RESIST": [],
        "HH": [],
        "HL": [],
        "LH": [],
        "LL": []
    }

    for symbol in WATCHLIST:
        df = get_market_candles_15m(symbol)
        if df is not None:
            for ev in analyze_macd_and_ema(df):
                if ev in results:
                    results[ev].append(symbol)
            for pv in analyze_pivots(df, left=10, right=10):
                if pv in results:
                    results[pv].append(symbol)
        time.sleep(0.03)

    # จัดเรียงลำดับเหรียญ A-Z ทุกหมวดหมู่
    for key in results:
        results[key].sort()

    def fmt(lst):
        return "  • " + ", ".join(lst) if lst else "  • ไม่มี"

    msg = [
        "⚡️ *[15M SCANNER & STRUCTURE]*",
        "────────────────────────────",
        "🟢 *GOLDEN CROSS :* ➔ ซูม 5M หาจังหวะ BUY",
        fmt(results["GOLDEN_CROSS"]),
        "",
        "🔴 *DEATH CROSS  :* ➔ ซูม 5M หาจังหวะ SELL",
        fmt(results["DEATH_CROSS"]),
        "",
        "🚀 *OVER 0        :* ➔ โมเมนตัมขึ้นแข็งแกร่ง",
        fmt(results["OVER_0"]),
        "",
        "🔻 *UNDER 0       :* ➔ โมเมนตัมลงแข็งแกร่ง",
        fmt(results["UNDER_0"]),
        "────────────────────────────",
        "🎯 *EMA 89 TOUCH :*",
        "📥 *แตะรับ        :* ➔ ซูม 5M ดูแท่งกลับตัวโซนรับ",
        fmt(results["TOUCH_SUPPORT"]),
        "",
        "📤 *แตะต้าน      :* ➔ ซูม 5M ดูแท่งกลับตัวโซนต้าน",
        fmt(results["TOUCH_RESIST"]),
        "────────────────────────────",
        "📐 *PIVOT (P10)  :*",
        "📈 *HH            :* ➔ ห้ามไล่ รอ 15M ทำ HL",
        fmt(results["HH"]),
        "",
        "🔼 *HL            :* ➔ ย่อจบ ซูม 5M เคาะ BUY",
        fmt(results["HL"]),
        "",
        "📉 *LH            :* ➔ เด้งจบ ซูม 5M เคาะ SELL",
        fmt(results["LH"]),
        "",
        "🔽 *LL            :* ➔ ห้ามตาม รอ 15M เด้งทำ LH",
        fmt(results["LL"]),
        "────────────────────────────",
        "📌 *Check:* 4H เมฆ ➔ 15M Signal ➔ 5M Entry"
    ]

    send_telegram("\n".join(msg))
    print("✅ สแกน 15M เสร็จสิ้นและส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
