import os
import sys
import time
import requests
import pandas as pd
import warnings
from concurrent.futures import ThreadPoolExecutor
from google import genai

warnings.filterwarnings("ignore")
http = requests.Session()
http.headers.update({"User-Agent": "Mozilla/5.0"})

# ======================== 1. CONFIGURATION & SECRETS ========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

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

# ======================== 2. DATA FETCHER ROUTER ========================
# ⚡️ [อัปเดต] ขยาย limit=500 เพื่อ Warm-up สมการ EMA200 ให้แม่นยำสูงสุด
def get_binance_candles(symbol, timeframe="1h", limit=500):
    if symbol in ["XAUUSDT", "XAUTUSDT"]: return None
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = http.get(url, timeout=4).json()
            if isinstance(res, list) and len(res) >= limit // 2:
                df = pd.DataFrame(res, columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
                for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_gateio_candles(symbol, timeframe="1h", limit=500):
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
            if isinstance(res, list) and len(res) >= limit // 2:
                records = []
                for item in res:
                    if isinstance(item, dict):
                        records.append({"timestamp": float(item.get("t", 0)), "open": float(item.get("o", 0)), "high": float(item.get("h", 0)), "low": float(item.get("l", 0)), "close": float(item.get("c", 0)), "volume": float(item.get("v", 0))})
                    elif isinstance(item, list) and len(item) >= 6:
                        records.append({"timestamp": float(item[0]), "open": float(item[5]), "high": float(item[3]), "low": float(item[4]), "close": float(item[2]), "volume": float(item[1])})
                if records:
                    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
                    return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_kucoin_candles(symbol, timeframe="1h", limit=500):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    tf_map = {"5m": "5min", "15m": "15min", "1h": "1hour", "4h": "4hour"}
    url = f"https://api.kucoin.com/api/v1/market/candles?type={tf_map.get(timeframe, timeframe)}&symbol={base_sym}-USDT&pageSize={limit}"
    try:
        res = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= limit // 2:
            records = [{"open": float(i[1]), "close": float(i[2]), "high": float(i[3]), "low": float(i[4]), "volume": float(i[5])} for i in res["data"]]
            return pd.DataFrame(records)[::-1].reset_index(drop=True).dropna()
    except: pass
    return None

def fetch_candles(symbol, timeframe="1h", limit=500):
    df = get_binance_candles(symbol, timeframe, limit)
    if df is not None: return df
    df = get_gateio_candles(symbol, timeframe, limit)
    if df is not None: return df
    return get_kucoin_candles(symbol, timeframe, limit)

# ==========================================
# 📊 1H STRUCTURAL ANALYSIS (PURE LOGIC)
# ==========================================
def analyze_1h_structure(symbol):
    df = fetch_candles(symbol, "1h", 500)
    # ⚡️ เช็คความเพียงพอของข้อมูลขั้นต่ำ (ต้องมากกว่า 250 แท่งเพื่อให้ EMA200 อุ่นเครื่องเสร็จ)
    if df is None or len(df) < 250: 
        return symbol, 0.0, 0.0, 1.0, "NONE", {}

    try:
        c_closed = df["close"].iloc[-2]
        h_closed = df["high"].iloc[-2]
        l_closed = df["low"].iloc[-2]
        
        # 1H & 24H Change
        prev_close = df["close"].iloc[-3]
        pct_change_1h = ((c_closed - prev_close) / prev_close) * 100
        close_24h_ago = df["close"].iloc[-26] if len(df) >= 26 else df["close"].iloc[0]
        pct_change_24h = ((c_closed - close_24h_ago) / close_24h_ago) * 100
        
        # Volume Surge
        vol_current = df["volume"].iloc[-2]
        vol_avg = df["volume"].iloc[-26:-2].mean()
        vol_surge = (vol_current / vol_avg) if vol_avg > 0 else 1.0

        # Indicators
        ema21_series = df["close"].ewm(span=21, adjust=False).mean()
        ema35_series = df["close"].ewm(span=35, adjust=False).mean()
        ema89_series = df["close"].ewm(span=89, adjust=False).mean()
        ema200_series = df["close"].ewm(span=200, adjust=False).mean()
        
        ema21, ema35, ema89, ema200 = ema21_series.iloc[-2], ema35_series.iloc[-2], ema89_series.iloc[-2], ema200_series.iloc[-2]
        ema21_prev, ema35_prev = ema21_series.iloc[-3], ema35_series.iloc[-3]

        macd_line = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
        macd_sig = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_sig

        # 1H Anti-Saw Math (Squeeze & Cross)
        spread_1h = (abs(ema21_series - ema35_series) / ema35_series) * 100.0
        squeeze_count = int((spread_1h <= 0.25).astype(int).iloc[-3:-1].sum())
        ema_state = (ema21_series > ema35_series).astype(int)
        cross_count = int((ema_state.diff().abs() > 0).iloc[-25:-1].sum())

        dist_89_pct = (abs(c_closed - ema89) / ema89) * 100
        dist_21_35_pct = (abs(ema21 - ema35) / ema35) * 100
        
        cross_up = (ema21_prev <= ema35_prev) and (ema21 > ema35)
        cross_dn = (ema21_prev >= ema35_prev) and (ema21 < ema35)
        
        bucket = "NONE"

        # 1. กรอง Overextended และ Choppy Market
        if dist_89_pct > 3.0 or squeeze_count >= 2 or cross_count >= 2:
            bucket = "AVOID"
        
        # 2. คัดกรองตามระบบ (Pure EMA Guard, ไม่ใช้ MACD บน 1H)
        elif bucket == "NONE":
            # 🟢 [BULLISH REGIME]
            if ema89 > ema200 and ema21 > ema35:
                if dist_89_pct <= 0.50:
                    bucket = "PLAN_A_BUY"
                elif cross_up or dist_21_35_pct <= 0.10:
                    bucket = "PLAN_B_BUY"
            
            # 🔴 [BEARISH REGIME]
            elif ema89 < ema200 and ema21 < ema35:
                if dist_89_pct <= 0.50:
                    bucket = "PLAN_A_SELL"
                elif cross_dn or dist_21_35_pct <= 0.10:
                    bucket = "PLAN_B_SELL"
        
        # 3. ตรวจจับ Divergence 1H
        if bucket == "NONE":
            if l_closed < df["low"].iloc[-10:-2].min() and macd_hist.iloc[-2] > macd_hist.iloc[-10:-2].min():
                bucket = "REV_BULL"
            elif h_closed > df["high"].iloc[-10:-2].max() and macd_hist.iloc[-2] < macd_hist.iloc[-10:-2].max():
                bucket = "REV_BEAR"

        return symbol, pct_change_1h, pct_change_24h, vol_surge, bucket, {"price": c_closed}
    except Exception:
        return symbol, 0.0, 0.0, 1.0, "NONE", {}

def send_telegram_msg(message, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": parse_mode, "disable_web_page_preview": True}, timeout=8)
    except Exception as e:
        print(f"Telegram Exception: {e}")

# ==========================================
# 🚀 MAIN PIPELINE
# ==========================================
def main():
    print("🚀 สแกนข้อมูล 1H Structural Radar (50 Assets)...")
    
    results = {}
    crypto_data = []
    
    plan_a_buy, plan_a_sell = [], []
    plan_b_buy, plan_b_sell = [], []
    rev_bull, rev_bear = [], []
    avoid_list = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, pct_1h, pct_24h, vol, bucket, data in executor.map(analyze_1h_structure, WATCHLIST):
            results[sym] = {"pct_1h": pct_1h, "pct_24h": pct_24h, "vol": vol}
            
            if bucket != "NONE":
                price = format_price(data.get('price', 0))
                tag = f"<code>{sym}</code> [{price}]"
                
                if bucket == "PLAN_A_BUY": plan_a_buy.append(tag)
                elif bucket == "PLAN_A_SELL": plan_a_sell.append(tag)
                elif bucket == "PLAN_B_BUY": plan_b_buy.append(tag)
                elif bucket == "PLAN_B_SELL": plan_b_sell.append(tag)
                elif bucket == "REV_BULL": rev_bull.append(tag)
                elif bucket == "REV_BEAR": rev_bear.append(tag)
                elif bucket == "AVOID": avoid_list.append(f"<code>{sym}</code>")

    for c in WATCHLIST:
        if c != "XAUUSDT" and c in results:
            crypto_data.append((c, results[c]["pct_1h"], results[c]["vol"]))

    crypto_data.sort(key=lambda x: x[1], reverse=True)
    top_gainers = [f"{s.replace('USDT','')} ({p:+.2f}%)" for s, p, v in crypto_data[:2]]
    top_losers = [f"{s.replace('USDT','')} ({p:+.2f}%)" for s, p, v in crypto_data[-2:]]
    crypto_data.sort(key=lambda x: x[2], reverse=True)
    top_vol = [f"{s.replace('USDT','')} (x{v:.1f})" for s, p, v in crypto_data if v >= 2.0][:2]

    btc_perf_24h = results.get("BTCUSDT", {}).get("pct_24h", 0.0)
    gold_perf_24h = results.get("XAUUSDT", {}).get("pct_24h", 0.0)

    # --- GEMINI 3.6 FLASH STRICT INSTRUCTION ---
    system_prompt = f"""
คุณคือนักวิเคราะห์เศรษฐศาสตร์ Macro และสาย Quant หน้าที่ของคุณคือรายงานทิศทางตลาดประจำชั่วโมง ห้ามใช้คำสแลง (เช่น 'ตึงจัด', 'กาว') ให้ใช้ภาษาทางการและเป็นมืออาชีพเท่านั้น ตอบตามโครงสร้างนี้เป๊ะๆ (ไม่ต้องมีคำเกริ่นนำหรือลงท้าย):

🎙️ <b>AI MACRO & CAPITAL FLOW DIRECTIVE</b>

🏛️ <b>ปฏิทินเศรษฐกิจสหรัฐฯ (ช่วง 1 ชั่วโมงข้างหน้า):</b>
• [ตรวจสอบและแจ้งว่ามีข่าวตัวเลขเศรษฐกิจสหรัฐฯ ที่จะประกาศใน 1 ชั่วโมงนี้หรือไม่ เช่น ดอกเบี้ย Fed, ว่างงาน, CPI หากไม่มีให้รายงานว่าไม่มีกำหนดการสำคัญ ตลาดเคลื่อนไหวตาม Technical Flow ปกติ]

🌊 <b>BTC Dominance & ทิศทางการหมุนเวียนเงินทุน (Capital Flow):</b>
• [ประเมินว่าเม็ดเงินไหลเข้า BTC, Gold หรือ Altcoins ให้วิเคราะห์ผลกระทบสภาพคล่อง อ้างอิงความแข็งแกร่งจาก BTC {btc_perf_24h:+.2f}% และ Gold {gold_perf_24h:+.2f}% ใช้ภาษาเชิงเทคนิค]

🎯 <b>คำแนะนำการบริหารขนาดเงินลงทุน (Margin Allocation):</b>
• [แนะนำระดับ Margin (เช่น 100% สำหรับสินทรัพย์หลักเกาะแนวรับ หรือ 50% โหมดจำกัดความเสี่ยงสำหรับกลุ่มผันผวน) และย้ำให้หลีกเลี่ยง Avoid List เด็ดขาด]
"""

    ai_insight = "⚠️ ขัดข้อง ไม่สามารถเชื่อมต่อ AI ได้"
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY.strip())
            for attempt in range(1, 4):
                try:
                    response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=system_prompt,
                    )
                    if response and response.text:
                        ai_insight = response.text.strip()
                        break
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        break
                    time.sleep(3)
        except Exception: pass

    # จัดหน้า UI แบบ No-Water (ไม่มีคำบรรยาย)
    str_a_buy = ", ".join(plan_a_buy) if plan_a_buy else "<i>ไม่มี</i>"
    str_a_sell = ", ".join(plan_a_sell) if plan_a_sell else "<i>ไม่มี</i>"
    str_b_buy = ", ".join(plan_b_buy) if plan_b_buy else "<i>ไม่มี</i>"
    str_b_sell = ", ".join(plan_b_sell) if plan_b_sell else "<i>ไม่มี</i>"
    str_r_bull = ", ".join(rev_bull) if rev_bull else "<i>ไม่มี</i>"
    str_r_bear = ", ".join(rev_bear) if rev_bear else "<i>ไม่มี</i>"
    str_avoid = ", ".join(avoid_list) if avoid_list else "<i>ไม่มี</i>"

    msg = (
        f"🧭 <b>[MARKET FLOW & MACRO RADAR]</b>\n"
        f"────────────────────────────\n"
        f"👑 <b>BTC (24H):</b> <code>{btc_perf_24h:+.2f}%</code> | 🥇 <b>Gold (24H):</b> <code>{gold_perf_24h:+.2f}%</code>\n\n"
        f"⚡️ <b>Outliers & Volume Surge (1H):</b>\n"
        f"🚀 <b>Gainers:</b> <code>{', '.join(top_gainers) if top_gainers else '-'}</code>\n"
        f"🩸 <b>Losers:</b> <code>{', '.join(top_losers) if top_losers else '-'}</code>\n"
        f"⚠️ <b>Volume Surge:</b> <code>{', '.join(top_vol) if top_vol else 'ปกติ'}</code>\n"
        f"────────────────────────────\n"
        f"🎯 <b>[1H STRUCTURAL RADAR]</b>\n"
        f"<i>(คัดกรองด้วย 1H Anti-Saw Matrix & EMA Guard)</i>\n\n"
        f"⚡️ <b>PLAN A [ZERO-STATION: ดักย่อ/เด้ง ชิดฐาน EMA89]</b>\n"
        f"• 🟢 <b>BUY:</b> {str_a_buy}\n"
        f"• 🔴 <b>SELL:</b> {str_a_sell}\n\n"
        f"🚀 <b>PLAN B [MOMENTUM TRIGGER: จ่อตัด/ทะลุ EMA 21x35]</b>\n"
        f"• 🟢 <b>BUY:</b> {str_b_buy}\n"
        f"• 🔴 <b>SELL:</b> {str_b_sell}\n\n"
        f"🔄 <b>REVERSAL / DIVERGENCE</b>\n"
        f"• 🟢 <b>BULL:</b> {str_r_bull}\n"
        f"• 🔴 <b>BEAR:</b> {str_r_bear}\n\n"
        f"⛔️ <b>AVOID LIST (Overextended >3.0% / Choppy Squeeze)</b>\n"
        f"• {str_avoid}\n"
        f"────────────────────────────\n"
        f"{ai_insight}"
    )
    
    send_telegram_msg(msg)
    print("✅ สแกน 50 สินทรัพย์ และส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
