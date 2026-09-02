## =========================================================================
## LOG VER: 3.9 (1H Macro Flow & Pure Radar - Time-Gated & Bi-Directional)
## - หัวข้อการแก้ไข: อัปเกรดระบบ AI Directive ปรับรอบรายงานปฏิทินเศรษฐกิจ Tier-1 สหรัฐฯ เป็นรอบ 07:00 น. วันละครั้ง และปลดล็อกการวิเคราะห์สองฝั่ง (BUY/SELL)
## - ตัด Option เดิม: ตัดการรายงานปฏิทินเศรษฐกิจล่วงหน้า 1 ชั่วโมงในรอบปกติ (ซ่อนหัวข้อตั้งแต่ 08:00 - 06:00 น.)
## - เพิ่มจากสิ่งที่ไม่มี: เพิ่มมิติวิเคราะห์ดัชนีดอลลาร์ (DXY) ใน Capital Flow, เพิ่มระบบจัดสรร 50% Margin ระบุสัดส่วนสินทรัพย์ และระบุทิศทาง Buy/Sell สองหน้า
## =========================================================================
import os
import sys
import time
import datetime
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

# 📋 WATCHLIST 50 ASSETS
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
    """จัดระเบียบตาราง 3 คอลัมน์ ความกว้าง 11 ตัวอักษร เพื่อเว้นช่องไฟให้สวยงามตามต้นฉบับ"""
    if not coins: 
        return "  • ไม่มี"
    rows = []
    for i in range(0, len(coins), cols):
        chunk = coins[i : i + cols]
        rows.append("  " + " ".join([f"`{c:<11}`" for c in chunk]))
    return "\n".join(rows)

# ======================== 2. DATA FETCHER ROUTER (1H) ========================
def get_binance_candles(symbol, timeframe="1h", limit=500):
    if symbol in ["XAUUSDT", "XAUTUSDT"]: 
        return None
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = http.get(url, timeout=4).json()
            if isinstance(res, list) and len(res) >= 100:
                df = pd.DataFrame(res, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
                for col in ["open", "high", "low", "close", "volume"]: 
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        except Exception: 
            continue
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
            if isinstance(res, list) and len(res) >= 100:
                records = []
                for item in res:
                    if isinstance(item, dict):
                        records.append({"timestamp": float(item.get("t", 0)), "open": float(item.get("o", 0)), "high": float(item.get("h", 0)), "low": float(item.get("l", 0)), "close": float(item.get("c", 0)), "volume": float(item.get("v", 0))})
                    elif isinstance(item, list) and len(item) >= 6:
                        records.append({"timestamp": float(item[0]), "open": float(item[5]), "high": float(item[3]), "low": float(item[4]), "close": float(item[2]), "volume": float(item[1])})
                if records:
                    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
                    return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        except Exception: 
            continue
    return None

def get_kucoin_candles(symbol, timeframe="1h", limit=500):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    tf_map = {"5m": "5min", "15m": "15min", "1h": "1hour", "4h": "4hour"}
    url = f"https://api.kucoin.com/api/v1/market/candles?type={tf_map.get(timeframe, timeframe)}&symbol={base_sym}-USDT&pageSize={limit}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = http.get(url, headers=headers, timeout=4).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= 100:
            records = [{"open": float(i[1]), "close": float(i[2]), "high": float(i[3]), "low": float(i[4]), "volume": float(i[5])} for i in res["data"]]
            df = pd.DataFrame(records)
            return df.iloc[::-1].reset_index(drop=True).dropna()
    except Exception: 
        pass
    return None

def fetch_candles(symbol, timeframe="1h", limit=500):
    df = get_binance_candles(symbol, timeframe, limit)
    if df is not None: 
        return df
    df = get_gateio_candles(symbol, timeframe, limit)
    if df is not None: 
        return df
    return get_kucoin_candles(symbol, timeframe, limit)

# ==========================================
# 📊 1H STRUCTURAL ANALYSIS (PURE EMA REGIME)
# ==========================================
def analyze_1h_structure(symbol):
    df = fetch_candles(symbol, "1h", 500)
    if df is None or len(df) < 250: 
        return symbol, 0.0, 0.0, 1.0, "NONE"

    try:
        c_closed = float(df["close"].iloc[-2])
        prev_close = float(df["close"].iloc[-3])
        pct_change_1h = ((c_closed - prev_close) / prev_close) * 100.0
        
        close_24h_ago = float(df["close"].iloc[-26]) if len(df) >= 26 else float(df["close"].iloc[0])
        pct_change_24h = ((c_closed - close_24h_ago) / close_24h_ago) * 100.0
        
        vol_current = float(df["volume"].iloc[-2])
        vol_avg = float(df["volume"].iloc[-26:-2].mean())
        vol_surge = (vol_current / vol_avg) if vol_avg > 0 else 1.0

        ema21 = float(df["close"].ewm(span=21, adjust=False).mean().iloc[-2])
        ema35 = float(df["close"].ewm(span=35, adjust=False).mean().iloc[-2])
        ema89 = float(df["close"].ewm(span=89, adjust=False).mean().iloc[-2])
        ema200 = float(df["close"].ewm(span=200, adjust=False).mean().iloc[-2])

        state = "NONE"
        if ema89 > ema200:
            if ema21 > ema35:
                state = "BUY_GREEN"
            elif ema21 < ema35:
                state = "BUY_YELLOW"
        elif ema89 < ema200:
            if ema21 < ema35:
                state = "SELL_GREEN"
            elif ema21 > ema35:
                state = "SELL_YELLOW"

        return symbol, pct_change_1h, pct_change_24h, vol_surge, state
    except Exception:
        return symbol, 0.0, 0.0, 1.0, "NONE"

def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
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
            sanitized = message.replace("_", " ").replace("*", "")
            payload["text"] = sanitized
            http.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[!] Telegram Exception: {e}")

# ==========================================
# 🚀 MAIN PIPELINE
# ==========================================
def main():
    print(f"🚀 เริ่มสแกน 1H Structural Radar (Watchlist: {len(WATCHLIST)} เหรียญ)...")
    
    results = {}
    crypto_data = []
    
    regime_data = {
        "BUY_GREEN": [],
        "BUY_YELLOW": [],
        "SELL_GREEN": [],
        "SELL_YELLOW": []
    }

    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, pct_1h, pct_24h, vol, state in executor.map(analyze_1h_structure, WATCHLIST):
            results[sym] = {"pct_1h": pct_1h, "pct_24h": pct_24h, "vol": vol}
            if state in regime_data:
                regime_data[state].append(sym)

    for key in regime_data:
        regime_data[key].sort()

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

    # ⏰ ตรวจสอบเวลาประเทศไทย (UTC+7) สำหรับเงื่อนไขรอบ 07:00 น.
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_bkk = now_utc + datetime.timedelta(hours=7)
    is_morning_report = (now_bkk.hour == 7)

    # --- GEMINI STRICT INSTRUCTION (gemini-3.6-flash ONLY) ---
    calendar_prompt_block = ""
    if is_morning_report:
        calendar_prompt_block = """
🏛️ *ปฏิทินเศรษฐกิจสหรัฐฯ Tier-1 ประจำวันนี้:*
• [ตรวจสอบและแจ้งกำหนดการตัวเลขเศรษฐกิจสำคัญระดับ Tier-1 ของสหรัฐฯ ตลอดทั้งวันพร้อมระบุเวลาไทย (หากไม่มี ให้ระบุว่าไม่มีกำหนดการสำคัญ ตลาดขับเคลื่อนด้วย Technical Flow)]
"""

    system_prompt = f"""
คุณคือนักวิเคราะห์เศรษฐศาสตร์ Macro และ Quant Risk Manager หน้าที่ของคุณคือวิเคราะห์สภาวะตลาดประจำชั่วโมงและให้คำแนะนำด้านการคุมความเสี่ยง (Risk & Portfolio Allocation) อย่างมืออาชีพ ห้ามใช้คำสแลงเด็ดขาด ตอบตามโครงสร้างนี้เป๊ะๆ (ไม่ต้องมีคำเกริ่นนำหรือคำลงท้าย):

🎙️ *AI MACRO & CAPITAL FLOW DIRECTIVE*
{calendar_prompt_block}
🌊 *USD (DXY) & ทิศทางการหมุนเวียนเงินทุน (Capital Flow):*
• [ประเมินดัชนีดอลลาร์ (DXY) สภาพคล่อง และทิศทางการหมุนเวียนของเงินทุนเปรียบเทียบ 4 มิติ: เงินสด (USD) vs ทองคำ (Gold) vs BTC vs Altcoins อ้างอิงความเคลื่อนไหว BTC 24H: {btc_perf_24h:+.2f}% และ Gold 24H: {gold_perf_24h:+.2f}% พร้อมสรุปการไหลเวียน เช่น USD > Gold > BTC > Altcoins]

🎯 *การบริหารความเสี่ยง & การจัดสรรพอร์ต (Portfolio Risk & Margin Strategy):*
• *ระดับ Margin:* [แนะนำการใช้ Margin เช่น 100% Full Margin / แบ่ง 50% Defensive Margin พร้อมเหตุผลความเสี่ยง]
• *การจัดสรร Margin (50% Split):* [หากใช้ 50% แนะนำชัดเจนว่าจะแบ่งไปที่ใด เช่น BTC ___%, Altcoins ___%, Gold ___%]
• *ทิศทางการเทรดประจำชั่วโมง (Tactical Bias - สองฝั่ง BUY / SELL):*
  * *BTC / Core Assets:* [ระบุชัดเจนว่าชั่วโมงนี้ควรเน้นฝั่ง BUY (Long) หรือ SELL (Short) สำหรับ Futures พร้อมจุดเฝ้าระวัง ห้ามสั่งทับมือเพียงเพราะตลาดลง]
  * *Altcoins:* [ระบุชัดเจนว่าควรเน้นเก็งกำไรฝั่ง BUY หรือ SELL ในกลุ่มใด]
  * *Gold (XAU):* [ระบุทิศทาง BUY หรือ SELL และบทบาทในการเป็นสินทรัพย์ Hedge]
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
                        clean_text = response.text.strip().replace("`", "'")
                        ai_insight = clean_text
                        break
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        break
                    time.sleep(3)
        except Exception:
            pass

    msg = [
        "🧭 *MARKET FLOW & MACRO RADAR*",
        "────────────────────────────",
        f"👑 *BTC (24H):* `{btc_perf_24h:+.2f}%` | 🥇 *Gold (24H):* `{gold_perf_24h:+.2f}%`\n",
        "⚡️ *Outliers & Volume Surge (1H):*",
        f"🚀 *Gainers:* `{', '.join(top_gainers) if top_gainers else '-'}`",
        f"🩸 *Losers:* `{', '.join(top_losers) if top_losers else '-'}`",
        f"⚠️ *Volume Surge:* `{', '.join(top_vol) if top_vol else 'ปกติ'}`",
        "────────────────────────────",
        "🎯 *1H EMA STRUCTURAL REGIME*\n",
        "🟢 *1. BUY ZONE (EMA 89 > 200)*",
        "• *GREEN (21 > 35 | เทรนด์สมบูรณ์) :*",
        format_grid(regime_data["BUY_GREEN"]), "",
        "• *YELLOW (21 < 35 | ย่อตัว/พักฐาน) :*",
        format_grid(regime_data["BUY_YELLOW"]),
        "────────────────────────────",
        "🔴 *2. SELL ZONE (EMA 89 < 200)*",
        "• *GREEN (21 < 35 | เทรนด์สมบูรณ์) :*",
        format_grid(regime_data["SELL_GREEN"]), "",
        "• *YELLOW (21 > 35 | ดีดรีบาวด์)   :*",
        format_grid(regime_data["SELL_YELLOW"]),
        "────────────────────────────",
        f"{ai_insight}"
    ]

    send_telegram_msg("\n".join(msg))
    print("✅ สแกน 1H Structural Radar เสร็จสิ้นและส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
