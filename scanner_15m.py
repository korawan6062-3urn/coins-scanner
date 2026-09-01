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

def format_price(val):
    if pd.isna(val): return "0.00"
    val = float(val)
    if abs(val) >= 1000: return f"{val:,.2f}"
    elif abs(val) >= 1: return f"{val:.4f}"
    else: return f"{val:.6f}"

# ======================== 2. DATA FETCHER ROUTER (1H & 15M) ========================
# ⚡️ [อัปเดต] ขยาย limit=500 เพื่อ Warm-up สมการ EMA200 ให้แม่นยำ 100%
def get_binance_candles(symbol, timeframe="15m", limit=500):
    if symbol in ["XAUUSDT", "XAUTUSDT"]: return None
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = http.get(url, timeout=4).json()
            if isinstance(res, list) and len(res) >= 100:
                df = pd.DataFrame(res, columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
                for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_gateio_candles(symbol, timeframe="15m", limit=500):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    endpoints = [
        f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval={timeframe}&limit={limit}",
        f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval={timeframe}&limit={limit}"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in endpoints:
        try:
            res = http.get(url, headers=headers, timeout=4).json()
            if isinstance(res, list) and len(res) >= 100:
                records = []
                for item in res:
                    if isinstance(item, dict):
                        records.append({"open": float(item.get("o", 0)), "high": float(item.get("h", 0)), "low": float(item.get("l", 0)), "close": float(item.get("c", 0)), "volume": float(item.get("v", 0))})
                    elif isinstance(item, list) and len(item) >= 6:
                        records.append({"open": float(item[5]), "high": float(item[3]), "low": float(item[4]), "close": float(item[2]), "volume": float(item[1])})
                if records:
                    return pd.DataFrame(records).dropna().reset_index(drop=True)
        except: continue
    return None

def get_kucoin_candles(symbol, timeframe="15m", limit=500):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    tf_map = {"5m": "5min", "15m": "15min", "1h": "1hour"}
    url = f"https://api.kucoin.com/api/v1/market/candles?type={tf_map.get(timeframe, timeframe)}&symbol={base_sym}-USDT&pageSize={limit}"
    try:
        res = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= 100:
            records = [{"open": float(i[1]), "close": float(i[2]), "high": float(i[3]), "low": float(i[4]), "volume": float(i[5])} for i in res["data"]]
            return pd.DataFrame(records)[::-1].reset_index(drop=True).dropna()
    except: pass
    return None

def fetch_candles(symbol, timeframe="15m", limit=500):
    df = get_binance_candles(symbol, timeframe, limit)
    if df is not None: return df
    df = get_gateio_candles(symbol, timeframe, limit)
    if df is not None: return df
    return get_kucoin_candles(symbol, timeframe, limit)

# ======================== 3. CORE CONFLUENCE ANALYSIS ========================
def analyze_15m_confluence(symbol):
    # ดึงข้อมูลย้อนหลัง 500 แท่งเพื่อความเสถียรของเส้น EMA
    df_1h = fetch_candles(symbol, "1h", 500)
    df_15m = fetch_candles(symbol, "15m", 500)

    # เช็คความเพียงพอของข้อมูลขั้นต่ำ (ต้องมากกว่า 250 แท่งเพื่อให้ EMA200 อุ่นเครื่องเสร็จ)
    if df_1h is None or len(df_1h) < 250 or df_15m is None or len(df_15m) < 250:
        return symbol, None, False, 0.0, ""

    try:
        # -------------------------------------------------------------
        # 🏛️ LAYER 1: 1H MACRO FILTER & 1H ANTI-SAW MATRIX
        # -------------------------------------------------------------
        e21_1h_s = df_1h["close"].ewm(span=21, adjust=False).mean()
        e35_1h_s = df_1h["close"].ewm(span=35, adjust=False).mean()
        e89_1h_s = df_1h["close"].ewm(span=89, adjust=False).mean()
        e200_1h_s = df_1h["close"].ewm(span=200, adjust=False).mean()

        e21_1h, e35_1h = e21_1h_s.iloc[-2], e35_1h_s.iloc[-2]
        e89_1h, e200_1h = e89_1h_s.iloc[-2], e200_1h_s.iloc[-2]

        is_1h_bull = (e89_1h > e200_1h) and (e21_1h > e35_1h)
        is_1h_bear = (e89_1h < e200_1h) and (e21_1h < e35_1h)

        # 1H Anti-Saw Math
        spread_1h = (abs(e21_1h_s - e35_1h_s) / e35_1h_s) * 100.0
        squeeze_count_1h = int((spread_1h <= 0.25).astype(int).iloc[-3:-1].sum())
        cross_count_1h = int(((e21_1h_s > e35_1h_s).astype(int).diff().abs() > 0).iloc[-25:-1].sum())
        is_1h_choppy = (squeeze_count_1h >= 2) or (cross_count_1h >= 2)

        # -------------------------------------------------------------
        # ⚡️ LAYER 2: 15M TECHNICAL INDICATORS & PRICE ACTION
        # -------------------------------------------------------------
        c_15 = float(df_15m["close"].iloc[-2])
        o_15 = float(df_15m["open"].iloc[-2])
        h_15 = float(df_15m["high"].iloc[-2])
        l_15 = float(df_15m["low"].iloc[-2])
        l_prev = float(df_15m["low"].iloc[-3])
        h_prev = float(df_15m["high"].iloc[-3])

        e21_15_s = df_15m["close"].ewm(span=21, adjust=False).mean()
        e35_15_s = df_15m["close"].ewm(span=35, adjust=False).mean()
        e89_15_s = df_15m["close"].ewm(span=89, adjust=False).mean()

        e21_15, e35_15, e89_15 = e21_15_s.iloc[-2], e35_15_s.iloc[-2], e89_15_s.iloc[-2]
        e21_15_prev, e35_15_prev = e21_15_s.iloc[-3], e35_15_s.iloc[-3]

        # 15M Anti-Saw Math
        spread_15 = (abs(e21_15_s - e35_15_s) / e35_15_s) * 100.0
        squeeze_count_15 = int((spread_15 <= 0.12).astype(int).iloc[-3:-1].sum())
        cross_count_15 = int(((e21_15_s > e35_15_s).astype(int).diff().abs() > 0).iloc[-17:-1].sum())
        is_15m_choppy = (squeeze_count_15 >= 2) or (cross_count_15 >= 2)

        # MACD (12, 26, 9)
        exp1 = df_15m["close"].ewm(span=12, adjust=False).mean()
        exp2 = df_15m["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        sig = macd.rolling(window=9).mean()
        m_c = float(macd.iloc[-2])

        # Overextended Check
        dist_89_15 = (abs(c_15 - e89_15) / e89_15) * 100.0

        # =============================================================
        # 🎯 LAYER 3: CONFLUENCE SETUP EVALUATION
        # =============================================================
        
        # ⛔️ 4. AVOID LIST (ห้ามเข้าเด็ดขาดถ้า 1H Choppy หรือ 15M Overextended)
        if dist_89_15 > 1.50 or is_1h_choppy or is_15m_choppy or (not is_1h_bull and not is_1h_bear):
            return symbol, "AVOID", True, c_15, ""

        # 🎯 1. ZERO-STATION CONFLUENCE (EMA Retest + MACD 0-Zone)
        P15_LOOKBACK = 48
        P15_PEAK = 0.20
        P15_MEAN = 0.75
        macd_window = macd.iloc[-(P15_LOOKBACK+1):-1]
        
        zero_buy_approved = (m_c > 0) and ((m_c <= macd_window.max() * P15_PEAK) or (m_c <= macd_window.mean() * P15_MEAN))
        zero_sell_approved = (m_c < 0) and ((m_c >= macd_window.min() * P15_PEAK) or (m_c >= macd_window.mean() * P15_MEAN))

        cloud_max, cloud_min = max(e21_15, e35_15), min(e21_15, e35_15)
        touch_cloud_buy = (l_15 <= cloud_max and c_15 >= cloud_min)
        touch_cloud_sell = (h_15 >= cloud_min and c_15 <= cloud_max)
        touch_89_buy = (l_15 <= e89_15 and c_15 >= e89_15 * 0.998)
        touch_89_sell = (h_15 >= e89_15 and c_15 <= e89_15 * 1.002)

        if is_1h_bull and (e21_15 > e35_15) and (touch_cloud_buy or touch_89_buy) and zero_buy_approved:
            return symbol, "ZERO_BUY", True, c_15, ""
        if is_1h_bear and (e21_15 < e35_15) and (touch_cloud_sell or touch_89_sell) and zero_sell_approved:
            return symbol, "ZERO_SELL", True, c_15, ""

        # 🚀 2. SLINGSHOT CONFLUENCE (Momentum Breakout after Compression)
        cross_up_15 = (e21_15_prev <= e35_15_prev) and (e21_15 > e35_15)
        cross_dn_15 = (e21_15_prev >= e35_15_prev) and (e21_15 < e35_15)

        if is_1h_bull and (cross_up_15 or (c_15 > cloud_max and o_15 <= cloud_max)):
            return symbol, "SLING_BULL", True, c_15, ""
        if is_1h_bear and (cross_dn_15 or (c_15 < cloud_min and o_15 >= cloud_min)):
            return symbol, "SLING_BEAR", True, c_15, ""

        # 🔄 3. CONFIRMED REVERSAL (Option 1: 1H Trend-Aligned Reversal)
        # ตรวจสอบ Divergence 15M เฉพาะที่ตามโครงสร้างหลักของ 1H ป้องกันการสวนเทรนด์หลัก
        window_size = 30
        recent_macd = macd.iloc[-window_size:]
        recent_close = df_15m["close"].iloc[-window_size:]

        # Bullish DG (ย่อทำ Low ใหม่แต่ MACD ยกฐาน) + โครงสร้าง 1H ยังเป็นขาขึ้น
        is_bull_dg = (l_15 <= float(recent_close.min())) and (m_c > float(recent_macd.min()))
        if is_1h_bull and is_bull_dg and (c_15 > e21_15 or (l_15 < l_prev and c_15 > o_15)):
            return symbol, "REV_BULL", True, c_15, "(Bull DG + เด้งยืนเหนือ EMA 21)"

        # Bearish DG (พุ่งทำ High ใหม่แต่ MACD กดลง) + โครงสร้าง 1H เป็นขาลง
        is_bear_dg = (h_15 >= float(recent_close.max())) and (m_c < float(recent_macd.max()))
        if is_1h_bear and is_bear_dg and (c_15 < e21_15 or (h_15 > h_prev and c_15 < o_15)):
            return symbol, "REV_BEAR", True, c_15, "(Bear DG + ทะลุหลุด EMA 21)"

        return symbol, "NONE", True, c_15, ""

    except Exception:
        return symbol, None, False, 0.0, ""

# ======================== 4. TELEGRAM NOTIFIER & MAIN ========================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Error: Missing Telegram Token/Chat ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": message, 
        "parse_mode": "HTML", 
        "disable_web_page_preview": True
    }
    try:
        res = http.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            plain = message.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", "")
            http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=10)
    except Exception as e:
        print(f"[!] Telegram Exception: {e}")

def main():
    print(f"🚀 เริ่มสแกน 15M A.AUN CONFLUENCE RADAR (Watchlist: {len(WATCHLIST)} เหรียญ)...")
    
    results = {
        "ZERO_BUY": [], "ZERO_SELL": [],
        "SLING_BULL": [], "SLING_BEAR": [],
        "REV_BULL": [], "REV_BEAR": [],
        "AVOID": []
    }
    failed = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        for symbol, category, success, price, note in executor.map(analyze_15m_confluence, WATCHLIST):
            if not success:
                failed.append(symbol)
                continue
            
            p_str = format_price(price)
            if category == "ZERO_BUY":
                results["ZERO_BUY"].append(f"<code>{symbol}</code> [{p_str}]")
            elif category == "ZERO_SELL":
                results["ZERO_SELL"].append(f"<code>{symbol}</code> [{p_str}]")
            elif category == "SLING_BULL":
                results["SLING_BULL"].append(f"<code>{symbol}</code> [{p_str}]")
            elif category == "SLING_BEAR":
                results["SLING_BEAR"].append(f"<code>{symbol}</code> [{p_str}]")
            elif category == "REV_BULL":
                results["REV_BULL"].append(f"<code>{symbol}</code> [{p_str}] <i>{note}</i>")
            elif category == "REV_BEAR":
                results["REV_BEAR"].append(f"<code>{symbol}</code> [{p_str}] <i>{note}</i>")
            elif category == "AVOID":
                results["AVOID"].append(f"<code>{symbol}</code>")

    str_zero_buy = ", ".join(results["ZERO_BUY"]) if results["ZERO_BUY"] else "<i>ไม่มี</i>"
    str_zero_sell = ", ".join(results["ZERO_SELL"]) if results["ZERO_SELL"] else "<i>ไม่มี</i>"
    str_sling_bull = ", ".join(results["SLING_BULL"]) if results["SLING_BULL"] else "<i>ไม่มี</i>"
    str_sling_bear = ", ".join(results["SLING_BEAR"]) if results["SLING_BEAR"] else "<i>ไม่มี</i>"
    str_rev_bull = ", ".join(results["REV_BULL"]) if results["REV_BULL"] else "<i>ไม่มี</i>"
    str_rev_bear = ", ".join(results["REV_BEAR"]) if results["REV_BEAR"] else "<i>ไม่มี</i>"
    str_avoid = " , ".join(results["AVOID"]) if results["AVOID"] else "<i>ไม่มี</i>"

    msg = (
        f"⚡️ <b>[15M A.AUN CONFLUENCE RADAR]</b>\n"
        f"────────────────────────────\n"
        f"🎯 <b>1. ZERO-STATION (ครบองค์ประกอบ EMA + MACD 0):</b>\n"
        f"• 🟢 <b>BUY:</b> {str_zero_buy}\n"
        f"• 🔴 <b>SELL:</b> {str_zero_sell}\n\n"
        f"🚀 <b>2. SLINGSHOT (เบรกโมเมนตัมหลังบีบอัด):</b>\n"
        f"• 🟢 <b>BULL:</b> {str_sling_bull}\n"
        f"• 🔴 <b>BEAR:</b> {str_sling_bear}\n\n"
        f"🔄 <b>3. CONFIRMED REVERSAL (Divergence + ทรงกราฟคอนเฟิร์ม):</b>\n"
        f"• 🟢 <b>BULL:</b> {str_rev_bull}\n"
        f"• 🔴 <b>BEAR:</b> {str_rev_bear}\n\n"
        f"⛔️ <b>4. AVOID / OVEREXTENDED (>1.5% จาก EMA89):</b>\n"
        f"• {str_avoid}"
    )

    if failed:
        msg += f"\n\n⚠️ <i>API Failed ({len(failed)} เหรียญ):</i> <code>{', '.join(failed[:10])}</code>"

    send_telegram(msg)
    print("✅ สแกน 15M Confluence เสร็จสิ้นและส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
