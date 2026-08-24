import os
import sys
import requests
import pandas as pd
import warnings
from concurrent.futures import ThreadPoolExecutor
from google import genai

warnings.filterwarnings("ignore")
http = requests.Session()

# ======================== 1. CONFIGURATION ========================
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

# ======================== 2. DATA FETCHER (4H) ========================
def get_binance_candles_4h(symbol, limit=150):
    if symbol == "XAUUSDT": return None
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=4h&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=4h&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=4h&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = http.get(url, timeout=5).json()
            if isinstance(res, list) and len(res) >= 80:
                df = pd.DataFrame(res, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
                for col in ["high", "low", "close"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["high", "low", "close"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_gateio_candles_4h(symbol, limit=150):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    endpoints = [
        f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval=4h&limit={limit}",
        f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval=4h&limit={limit}"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in endpoints:
        try:
            res = http.get(url, headers=headers, timeout=5).json()
            if isinstance(res, list) and len(res) >= 80:
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

def get_kucoin_candles_4h(symbol):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    url = f"https://api.kucoin.com/api/v1/market/candles?type=4hour&symbol={base_sym}-USDT"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = http.get(url, headers=headers, timeout=5).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= 80:
            records = [{"close": float(i[2]), "high": float(i[3]), "low": float(i[4])} for i in res["data"]]
            df = pd.DataFrame(records)
            return df.iloc[::-1].reset_index(drop=True)
    except: pass
    return None

def fetch_candles(symbol):
    df = get_binance_candles_4h(symbol)
    if df is not None: return df
    df = get_gateio_candles_4h(symbol)
    if df is not None: return df
    return get_kucoin_candles_4h(symbol)

# ======================== 3. BG SYSTEM ANALYSIS (PYTHON CORE) ========================
def analyze_4h_bg_system(symbol):
    df = fetch_candles(symbol)
    if df is None or len(df) < 100: 
        return symbol, "UNKNOWN", [], df

    try:
        df_c = df.iloc[:-1].copy().reset_index(drop=True)
        
        # 1. Ichimoku Cloud
        tenkan = (df_c["high"].rolling(9).max() + df_c["low"].rolling(9).min()) / 2
        kijun = (df_c["high"].rolling(26).max() + df_c["low"].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df_c["high"].rolling(52).max() + df_c["low"].rolling(52).min()) / 2).shift(26)

        # 2. EMA Ribbon
        ema21 = df_c["close"].ewm(span=21, adjust=False).mean()
        ema35 = df_c["close"].ewm(span=35, adjust=False).mean()
        ema89 = df_c["close"].ewm(span=89, adjust=False).mean()

        # 3. MACD (TradingView Standard: EMA 12, EMA 26, SMA 9)
        exp1 = df_c["close"].ewm(span=12, adjust=False).mean()
        exp2 = df_c["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.rolling(window=9).mean() # SMA 9
        hist = macd - signal

        # Current values
        c_val = df_c["close"].iloc[-1]
        sa_v, sb_v = span_a.iloc[-1], span_b.iloc[-1]
        e21_v, e35_v, e89_v = ema21.iloc[-1], ema35.iloc[-1], ema89.iloc[-1]
        m_c, s_c, h_c = macd.iloc[-1], signal.iloc[-1], hist.iloc[-1]
        m_p, s_p = macd.iloc[-2], signal.iloc[-2]

        if pd.isna(sa_v) or pd.isna(sb_v): return symbol, "UNKNOWN", [], df_c
        
        kumo_top, kumo_bot = max(sa_v, sb_v), min(sa_v, sb_v)
        
        # Regime Detection
        regime = "CHOPPY"
        if c_val > kumo_top: regime = "BUY"
        elif c_val < kumo_bot: regime = "SELL"

        tags = []
        # Structural Confluence (EMA Alignment)
        if regime == "BUY" and (e21_v > e35_v > e89_v):
            tags.append("BULL_EMA_RIBBON")
        elif regime == "SELL" and (e21_v < e35_v < e89_v):
            tags.append("BEAR_EMA_RIBBON")

        # MACD Events
        if m_p <= s_p and m_c > s_c: tags.append("MACD_BULL_CROSS")
        elif m_p >= s_p and m_c < s_c: tags.append("MACD_BEAR_CROSS")
        if m_p <= 0 and m_c > 0: tags.append("MACD_OVER_0")
        elif m_p >= 0 and m_c < 0: tags.append("MACD_UNDER_0")
        
        # Zero-Station Proxy
        if abs(m_c) < (df_c["close"].iloc[-1] * 0.005) and m_c > s_c: 
            tags.append("ZERO_STATION_HOOK")

        # EMA 89 Test
        low_curr, high_curr = df_c["low"].iloc[-1], df_c["high"].iloc[-1]
        low_prev, high_prev = df_c["low"].iloc[-2], df_c["high"].iloc[-2]
        ema89_prev = ema89.iloc[-2]

        if low_prev > ema89_prev and low_curr <= e89_v: tags.append("EMA89_SUPPORT_TEST")
        elif high_prev < ema89_prev and high_curr >= e89_v: tags.append("EMA89_RESIST_TEST")

        # Price Info for AI
        pct_change = ((c_val - df_c["close"].iloc[-2]) / df_c["close"].iloc[-2]) * 100
        price_data = {"price": c_val, "pct": pct_change, "ema89": e89_v}

        return symbol, regime, tags, price_data

    except Exception:
        return symbol, "UNKNOWN", [], {}

# ======================== 4. TELEGRAM SENDER ========================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        res = http.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            plain = message.replace("*", "").replace("`", "").replace("_", "")
            http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=10)
    except: pass

# ======================== 5. MAIN LOGIC & AI FILTER ========================
def main():
    print("🚀 เริ่มสแกน 4H (Pure BG Structure)...")
    
    buy_list, sell_list, choppy_list = [], [], []
    priority_targets = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, regime, tags, data in executor.map(analyze_4h_bg_system, WATCHLIST):
            if regime == "BUY": buy_list.append(sym)
            elif regime == "SELL": sell_list.append(sym)
            elif regime == "CHOPPY": choppy_list.append(sym)
            
            # กรองเฉพาะเหรียญที่มี Confluence แรงๆ เพื่อส่งให้ AI วิเคราะห์ลึก
            if len(tags) > 0:
                priority_targets.append({
                    "symbol": sym, "regime": regime, "tags": tags,
                    "price": data.get("price", 0), "pct": data.get("pct", 0), "ema89": data.get("ema89", 0)
                })

    # เรียงลำดับตัวอักษร
    buy_list.sort(); sell_list.sort(); choppy_list.sort()

    # เตรียม Data ให้ AI 
    raw_data_str = "รายการเหรียญที่เกิด Signal ใน 4H (Priority Data):\n"
    for p in priority_targets:
        raw_data_str += f"- {p['symbol']}: Regime={p['regime']}, Tags={p['tags']}, Price={p['price']}, Change={p['pct']:.2f}%, EMA89={p['ema89']}\n"
    
    raw_data_str += f"\nภาพรวมตลาด:\nBUY Trend: {len(buy_list)} เหรียญ\nSELL Trend: {len(sell_list)} เหรียญ\nCHOPPY: {len(choppy_list)} เหรียญ"

    system_prompt = f"""
คุณคือ 'BG System Analyst' หน้าที่ของคุณคือการแปลผลข้อมูลดิบจาก Python ให้เป็นแผนการเทรดที่เข้าใจง่าย

กฎเหล็ก (ห้ามฝ่าฝืน):
1. ระบบ BG ของเราใช้เพียง Ichimoku Cloud, EMA Ribbon (21,35,89), และ MACD (EMA12, EMA26, ตัดกับ SMA9) ห้ามอ้างอิง RSI หรือ Stochastic เด็ดขาด
2. เลือกเหรียญจาก 'Priority Data' ที่น่าสนใจที่สุดมาแค่ 2-3 เหรียญ เพื่อจัดเป็น High Priority Targets
3. เขียน Action Plan ให้สอดคล้อง (เช่น ถ้า 4H เป็น BUY ให้บอกว่ารอสัญญาณ 15M/5M เพื่อ Long)
4. คง Layout และ Emoji ตามรูปแบบตัวอย่างด้านล่าง ห้ามใส่ข้อความเกริ่นนำหรือลงท้ายใดๆ

รูปแบบที่ต้องการ:
🧭 *[4H BG RADAR & TARGET WATCHLIST]*
────────────────────────────
🤖 *AI Tactical Briefing:*
(สรุปสภาวะตลาดจากสัดส่วน BUY/SELL ภายใน 2 บรรทัด)

🎯 *[HIGH PRIORITY TARGETS: ตัวเด่นตามกรอบ BG]*
🟢 *COIN_NAME* `[TAG_1 + TAG_2]`
  • *ราคา:* `ราคา` (เปอร์เซ็นต์%) | *EMA 89 (4H):* `ราคาEMA89`
  • *โครงสร้าง BG:* (อธิบายตาม Tags ที่เห็น เช่น เรียงตัวเหนือเมฆ, MACD ตัด SMA9)
  • *Action:* (เช่น เฝ้าระวังกรอบ 15M หาจังหวะย่อเพื่อ Long)

🔴 *COIN_NAME* ... (ทำรูปแบบเดียวกัน หากเป็น SELL)

────────────────────────────
📊 *[4H CLOUD & STRUCTURE OVERVIEW]*
🟢 *BUY (เหนือเมฆ 4H):* {', '.join(buy_list[:10])}... ({len(buy_list)})
🔴 *SELL (ใต้เมฆ 4H):* {', '.join(sell_list[:10])}... ({len(sell_list)})
⚪️ *CHOPPY (ในเมฆ):* {len(choppy_list)} เหรียญ
────────────────────────────
📌 *Checklist:* 4H เมฆ & โครงสร้าง ➔ 15M Radar Signal ➔ 5M Entry

ข้อมูลดิบ:
{raw_data_str}
"""

    ai_success = False
    final_message = ""

    # ลองเรียก Gemini AI 
    if GEMINI_API_KEY:
        try:
            print("Sending data to Gemini AI...")
            client = genai.Client(api_key=GEMINI_API_KEY.strip())
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=system_prompt,
            )
            final_message = response.text.strip()
            ai_success = True
        except Exception as e:
            print(f"Gemini API Error: {e}")

    # ================= Fallback (Python Only) =================
    if not ai_success:
        print("⚠️ [FALLBACK] AI Error, using Python rendering...")
        
        # คัดกรองตัวที่ดีที่สุด 3 ตัวด้วย Python เปล่าๆ
        best_targets = ""
        count = 0
        for p in priority_targets:
            if count >= 3: break
            icon = "🟢" if p['regime'] == "BUY" else "🔴"
            action = "หาจังหวะ 15M/5M เคาะ BUY (Long)" if p['regime'] == "BUY" else "หาจังหวะ 15M/5M เคาะ SELL (Short)"
            tag_str = " + ".join(p['tags']).replace("_", " ")
            
            best_targets += f"{icon} *{p['symbol']}* `[{tag_str}]`\n"
            best_targets += f"  • *ราคา:* `{format_price(p['price'])}` ({p['pct']:+.2f}%) | *EMA 89:* `{format_price(p['ema89'])}`\n"
            best_targets += f"  • *Action:* {action}\n\n"
            count += 1
            
        if not best_targets: best_targets = "  • ยังไม่มีเหรียญเข้าเกณฑ์ BG Structure ที่ชัดเจน\n"

        final_message = (
            f"🧭 *[4H BG RADAR & TARGET WATCHLIST]*\n"
            f"────────────────────────────\n"
            f"⚠️ *[API ERROR: ระบบวิเคราะห์โดย Python เท่านั้น (ไม่ผ่าน AI)]*\n"
            f"_ตลาดประมวลผลผ่านสมการคณิตศาสตร์ Pure BG Structure 100%_\n\n"
            f"🎯 *[HIGH PRIORITY TARGETS: โครงสร้างชัดตามระบบ]*\n"
            f"{best_targets.strip()}\n"
            f"────────────────────────────\n"
            f"📊 *[4H CLOUD OVERVIEW (Top 10)]*\n"
            f"🟢 *BUY (เหนือเมฆ):*\n  `{', '.join(buy_list[:10])}`\n"
            f"🔴 *SELL (ใต้เมฆ):*\n  `{', '.join(sell_list[:10])}`\n"
            f"⚪️ *CHOPPY (ในเมฆ):* {len(choppy_list)} เหรียญ\n"
            f"────────────────────────────\n"
            f"📌 *Checklist:* 4H เมฆ & โครงสร้าง ➔ 15M Radar Signal ➔ 5M Entry"
        )

    send_telegram(final_message)
    print("✅ สแกน 4H และส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
