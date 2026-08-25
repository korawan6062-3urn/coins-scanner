# scanner_1h.py
import os
import sys
import requests
import pandas as pd
import warnings
from concurrent.futures import ThreadPoolExecutor
from google import genai

warnings.filterwarnings("ignore")
http = requests.Session()

# ======================== 1. CONFIGURATION & TIER MAP ========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# โครงสร้าง Tier สำหรับจัดกลุ่มวิเคราะห์ Sector Flow และ Money Rotation
TIER_STRUCTURE = {
    # 🌟 Tier 1: King & Majors
    "BTCUSDT": "King & Majors", 
    "ETHUSDT": "King & Majors", 
    "BNBUSDT": "King & Majors", 
    "SOLUSDT": "King & Majors", 
    "XRPUSDT": "King & Majors",
    
    # 🧠 Tier 2: AI & Hot Narrative
    "ARKMUSDT": "AI & Hot Narrative", 
    "FETUSDT": "AI & Hot Narrative", 
    "NEARUSDT": "AI & Hot Narrative", 
    "RENDERUSDT": "AI & Hot Narrative", 
    "TAOUSDT": "AI & Hot Narrative", 
    "WLDUSDT": "AI & Hot Narrative",
    
    # 💎 Tier 3: DeFi & RWA
    "AAVEUSDT": "DeFi & RWA", 
    "DYDXUSDT": "DeFi & RWA", 
    "ENAUSDT": "DeFi & RWA", 
    "JUPUSDT": "DeFi & RWA", 
    "LINKUSDT": "DeFi & RWA", 
    "ONDOUSDT": "DeFi & RWA", 
    "PENDLEUSDT": "DeFi & RWA",
    
    # ⚡️ Tier 4: Fast L1s & High-Performance Ecosystems
    "ADAUSDT": "Fast L1s", 
    "APTUSDT": "Fast L1s", 
    "ATOMUSDT": "Fast L1s", 
    "AVAXUSDT": "Fast L1s", 
    "DOTUSDT": "Fast L1s", 
    "GRTUSDT": "Fast L1s", 
    "ICPUSDT": "Fast L1s", 
    "INJUSDT": "Fast L1s", 
    "KASUSDT": "Fast L1s", 
    "PYTHUSDT": "Fast L1s", 
    "SEIUSDT": "Fast L1s", 
    "SUIUSDT": "Fast L1s",
    
    # 🌐 Tier 5: Layer 2s & Modular
    "ARBUSDT": "Layer 2s", 
    "MANTAUSDT": "Layer 2s", 
    "POLUSDT": "Layer 2s", 
    "OPUSDT": "Layer 2s", 
    "STRKUSDT": "Layer 2s", 
    "TIAUSDT": "Layer 2s", 
    "ZKUSDT": "Layer 2s",
    
    # 🏛️ Tier 6: Legacy & PoW
    "BCHUSDT": "Legacy & PoW", 
    "ETCUSDT": "Legacy & PoW", 
    "LTCUSDT": "Legacy & PoW", 
    "STXUSDT": "Legacy & PoW", 
    "UNIUSDT": "Legacy & PoW", 
    "ZECUSDT": "Legacy & PoW"
}

WATCHLIST = list(TIER_STRUCTURE.keys())

def format_price(val):
    if pd.isna(val): return "0.00"
    val = float(val)
    if abs(val) >= 1000: return f"{val:,.2f}"
    elif abs(val) >= 1: return f"{val:.4f}"
    else: return f"{val:.6f}"

# ======================== 2. DATA FETCHER (1H - MIN 200 CANDLES) ========================
def get_binance_candles_1h(symbol, limit=300):
    if symbol == "XAUUSDT": return None
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1h&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = http.get(url, timeout=5).json()
            if isinstance(res, list) and len(res) >= 200:
                df = pd.DataFrame(res, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
                for col in ["high", "low", "close"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["high", "low", "close"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_gateio_candles_1h(symbol, limit=300):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    endpoints = [
        f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval=1h&limit={limit}",
        f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval=1h&limit={limit}"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in endpoints:
        try:
            res = http.get(url, headers=headers, timeout=5).json()
            if isinstance(res, list) and len(res) >= 200:
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

def get_kucoin_candles_1h(symbol):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    url = f"https://api.kucoin.com/api/v1/market/candles?type=1hour&symbol={base_sym}-USDT"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = http.get(url, headers=headers, timeout=5).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= 200:
            records = [{"close": float(i[2]), "high": float(i[3]), "low": float(i[4])} for i in res["data"]]
            df = pd.DataFrame(records)
            return df.iloc[::-1].reset_index(drop=True)
    except: pass
    return None

def fetch_candles(symbol):
    df = get_binance_candles_1h(symbol)
    if df is not None: return df
    df = get_gateio_candles_1h(symbol)
    if df is not None: return df
    return get_kucoin_candles_1h(symbol)

# ======================== 3. TYA.AUN SYSTEM ANALYSIS ========================
def analyze_1h_tya_system(symbol):
    df = fetch_candles(symbol)
    if df is None or len(df) < 200: 
        return symbol, "UNKNOWN", [], {}

    try:
        df_c = df.iloc[:-1].copy().reset_index(drop=True)
        
        # EMA Ribbon (21, 35, 89, 200)
        ema21 = df_c["close"].ewm(span=21, adjust=False).mean()
        ema35 = df_c["close"].ewm(span=35, adjust=False).mean()
        ema89 = df_c["close"].ewm(span=89, adjust=False).mean()
        ema200 = df_c["close"].ewm(span=200, adjust=False).mean()

        # MACD (Standard 12, 26, 9)
        exp1 = df_c["close"].ewm(span=12, adjust=False).mean()
        exp2 = df_c["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.rolling(window=9).mean()
        hist = macd - signal

        # Value Extraction
        c_val = df_c["close"].iloc[-1]
        e21_v, e35_v, e89_v, e200_v = ema21.iloc[-1], ema35.iloc[-1], ema89.iloc[-1], ema200.iloc[-1]
        m_c, s_c = macd.iloc[-1], signal.iloc[-1]

        if pd.isna(e200_v): return symbol, "UNKNOWN", [], {}
        
        # 1H Macro Filter Rule (Strict TYA.AUN)
        regime = "CHOPPY"
        if (e89_v > e200_v) and (e21_v > e35_v): regime = "BUY"
        elif (e89_v < e200_v) and (e21_v < e35_v): regime = "SELL"

        tags = []
        if regime == "BUY":
            if (e21_v > e35_v > e89_v > e200_v): tags.append("EMA_STACK")
            if (m_c > 0): tags.append("ZERO_STATION_SETUP")
            if (c_val > e89_v and e89_v > e200_v): tags.append("SLINGSHOT_PRIMED")
        elif regime == "SELL":
            if (e21_v < e35_v < e89_v < e200_v): tags.append("EMA_STACK")
            if (m_c < 0): tags.append("ZERO_STATION_SETUP")
            if (c_val < e89_v and e89_v < e200_v): tags.append("SLINGSHOT_PRIMED")

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

# ======================== 5. MAIN LOGIC & AI PROMPT ========================
def main():
    print("🚀 เริ่มสแกน 1H (TYA.AUN Macro Filter)...")
    
    buy_list, sell_list, choppy_list = [], [], []
    priority_targets = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, regime, tags, data in executor.map(analyze_1h_tya_system, WATCHLIST):
            if regime == "BUY": buy_list.append(sym)
            elif regime == "SELL": sell_list.append(sym)
            elif regime == "CHOPPY": choppy_list.append(sym)
            
            if len(tags) > 0:
                priority_targets.append({
                    "symbol": sym, "regime": regime, "tags": tags,
                    "price": data.get("price", 0), "pct": data.get("pct", 0), "ema89": data.get("ema89", 0)
                })

    buy_list.sort(); sell_list.sort(); choppy_list.sort()

    raw_data_str = "รายการเหรียญที่เกิด Signal ใน 1H (Priority Data):\n"
    for p in priority_targets:
        tier_name = TIER_STRUCTURE.get(p['symbol'], "Other")
        raw_data_str += f"- {p['symbol']} [{tier_name}]: Regime={p['regime']}, Tags={p['tags']}, Price={p['price']}, Change={p['pct']:.2f}%, EMA89={p['ema89']}\n"
    
    raw_data_str += f"\nภาพรวมตลาด:\nBUY Trend: {len(buy_list)} เหรียญ\nSELL Trend: {len(sell_list)} เหรียญ\nCHOPPY: {len(choppy_list)} เหรียญ"

    system_prompt = f"""
คุณคือ 'TYA.AUN System Analyst' หน้าที่ของคุณคือการแปลผลข้อมูลดิบจาก Python ให้เป็นแผนการเทรดที่เข้าใจง่าย

กฎเหล็ก (ห้ามฝ่าฝืน):
1. ระบบ 1H TYA.AUN ของเราใช้เพียง EMA (21,35,89,200) เป็นเบรกเกอร์หลัก (89>200 และ 21>35 คือ BUY) ห้ามอ้างอิง Ichimoku, RSI หรือ Stochastic เด็ดขาด
2. เลือกเหรียญจาก 'Priority Data' ที่น่าสนใจที่สุดมาแค่ 2-3 เหรียญ เพื่อจัดเป็น High Priority Targets โดยอ้างอิง Tier หมวดหมู่ประกอบ
3. เขียน Action Plan ให้สอดคล้อง (เช่น ถ้า 1H เป็น BUY ให้บอกว่ารอจุดเข้า 5M Zero-Station / Slingshot เพื่อ Long)
4. คง Layout และ Emoji ตามรูปแบบตัวอย่างด้านล่าง ห้ามใส่ข้อความเกริ่นนำหรือลงท้ายใดๆ

รูปแบบที่ต้องการ:
🧭 *[1H TYA.AUN MACRO FLOW & TARGETS]*
────────────────────────────
🤖 *AI Tactical Briefing (TYA.AUN 1H):*
(สรุปสภาวะตลาดจากสัดส่วน BUY/SELL และการไหลของ Sector ภายใน 2 บรรทัด)

🎯 *[HIGH PRIORITY 1H TARGETS]*
🟢 *COIN_NAME* `[TAG_1 + TAG_2]`
  • *ราคา:* `ราคา` (เปอร์เซ็นต์%) | *EMA 89 (1H):* `ราคาEMA89`
  • *โครงสร้าง 1H:* (อธิบายตาม Tags ที่เห็น เช่น EMA 89 > 200 และ 21 > 35 ชัดเจน)
  • *Action Plan:* (เช่น รอคลื่น 5M เข้าสู่ Zero-Station เพื่อเคาะ BUY)

🔴 *COIN_NAME* ... (ทำรูปแบบเดียวกัน หากเป็น SELL)

────────────────────────────
📊 *[1H TYA.AUN STRUCTURE OVERVIEW]*
🟢 *BUY TREND (89>200 & 21>35):* {', '.join(buy_list[:10])}... ({len(buy_list)})
🔴 *SELL TREND (89<200 & 21<35):* {', '.join(sell_list[:10])}... ({len(sell_list)})
⚪️ *NO TREND / CHOPPY:* {len(choppy_list)} เหรียญ
────────────────────────────
📌 *Checklist:* 1H Macro Filter ➔ 5M Zero-Station / Slingshot Entry

ข้อมูลดิบ:
{raw_data_str}
"""

    ai_success = False
    final_message = ""

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

    # Fallback (Python Rendering)
    if not ai_success:
        print("⚠️ [FALLBACK] AI Error, using Python rendering...")
        
        best_targets = ""
        count = 0
        for p in priority_targets:
            if count >= 3: break
            icon = "🟢" if p['regime'] == "BUY" else "🔴"
            action = "รอจุดเข้า 5M Zero-Station / Slingshot เพื่อเคาะ BUY (Long)" if p['regime'] == "BUY" else "รอจุดเข้า 5M Zero-Station / Slingshot เพื่อเคาะ SELL (Short)"
            tag_str = " + ".join(p['tags']).replace("_", " ")
            
            best_targets += f"{icon} *{p['symbol']}* `[{tag_str}]`\n"
            best_targets += f"  • *ราคา:* `{format_price(p['price'])}` ({p['pct']:+.2f}%) | *EMA 89:* `{format_price(p['ema89'])}`\n"
            best_targets += f"  • *Action Plan:* {action}\n\n"
            count += 1
            
        if not best_targets: best_targets = "  • ยังไม่มีเหรียญเข้าเกณฑ์ 1H TYA.AUN Structure ที่ชัดเจน\n"

        final_message = (
            f"🧭 *[1H TYA.AUN MACRO FLOW & TARGETS]*\n"
            f"────────────────────────────\n"
            f"⚠️ *[API ERROR: ระบบวิเคราะห์โดย Python เท่านั้น (ไม่ผ่าน AI)]*\n"
            f"_ตลาดประมวลผลผ่านสมการคณิตศาสตร์ Pure 1H TYA.AUN 100%_\n\n"
            f"🎯 *[HIGH PRIORITY 1H TARGETS: โครงสร้างชัดตามระบบ]*\n"
            f"{best_targets.strip()}\n"
            f"────────────────────────────\n"
            f"📊 *[1H TYA.AUN STRUCTURE OVERVIEW (Top 10)]*\n"
            f"🟢 *BUY TREND (89>200 & 21>35):*\n  `{', '.join(buy_list[:10])}`\n"
            f"🔴 *SELL TREND (89<200 & 21<35):*\n  `{', '.join(sell_list[:10])}`\n"
            f"⚪️ *NO TREND / CHOPPY:* {len(choppy_list)} เหรียญ\n"
            f"────────────────────────────\n"
            f"📌 *Checklist:* 1H Macro Filter ➔ 5M Zero-Station / Slingshot Entry"
        )

    send_telegram(final_message)
    print("✅ สแกน 1H และส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
