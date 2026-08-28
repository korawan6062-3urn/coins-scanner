import os
import time
import requests
import pandas as pd
import warnings
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from google import genai

warnings.filterwarnings("ignore")
http = requests.Session()

# ======================== 1. CONFIGURATION & TIER MAP ========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# โครงสร้าง Tier 33+1 (A.Aun Setup)
TIER_STRUCTURE = {
    "BTCUSDT": "Macro Core", "XAUUSDT": "Macro Core",
    "ETHUSDT": "Tier 1", "SOLUSDT": "Tier 1", "BNBUSDT": "Tier 1", "XRPUSDT": "Tier 1",
    "BCHUSDT": "PoW", "ETCUSDT": "PoW", "KASUSDT": "PoW", "LTCUSDT": "PoW", "ZECUSDT": "PoW",
    "APTUSDT": "Layer 1", "AVAXUSDT": "Layer 1", "INJUSDT": "Layer 1", "NEARUSDT": "Layer 1", "SUIUSDT": "Layer 1",
    "ARBUSDT": "Layer 2", "OPUSDT": "Layer 2", "POLUSDT": "Layer 2",
    "ONDOUSDT": "RWA",
    "ARKMUSDT": "AI", "FETUSDT": "AI", "RENDERUSDT": "AI", "TAOUSDT": "AI", "WLDUSDT": "AI",
    "AAVEUSDT": "DeFi", "DYDXUSDT": "DeFi", "ENAUSDT": "DeFi", "PENDLEUSDT": "DeFi", "UNIUSDT": "DeFi",
    "GRTUSDT": "Infra", "JUPUSDT": "Infra", "LINKUSDT": "Infra", "PYTHUSDT": "Infra"
}

WATCHLIST = list(TIER_STRUCTURE.keys())

def format_price(val):
    if pd.isna(val): return "0.00"
    val = float(val)
    if abs(val) >= 1000: return f"{val:,.2f}"
    elif abs(val) >= 1: return f"{val:.4f}"
    else: return f"{val:.6f}"

# ======================== 2. DATA FETCHER (1H & 15M) ========================
def get_binance_candles(symbol, timeframe="1h", limit=200):
    if symbol in ["XAUUSDT", "XAUTUSDT"]: return None
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    try:
        res = http.get(url, timeout=5).json()
        if isinstance(res, list) and len(res) >= limit // 2:
            df = pd.DataFrame(res, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
            for col in ["high", "low", "close"]: df[col] = pd.to_numeric(df[col], errors="coerce")
            return df[["high", "low", "close"]].dropna().reset_index(drop=True)
    except: pass
    return None

def get_gateio_candles(symbol, timeframe="1h", limit=200):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    url = f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval={timeframe}&limit={limit}"
    try:
        res = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5).json()
        if isinstance(res, list) and len(res) >= limit // 2:
            records = [{"timestamp": float(i.get("t", 0)), "high": float(i.get("h", 0)), "low": float(i.get("l", 0)), "close": float(i.get("c", 0))} for i in res]
            return pd.DataFrame(records).dropna().reset_index(drop=True)
    except: pass
    return None

def get_kucoin_candles(symbol, timeframe="1h", limit=200):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    tf_map = {"1h": "1hour", "15m": "15min"}
    url = f"https://api.kucoin.com/api/v1/market/candles?type={tf_map.get(timeframe, timeframe)}&symbol={base_sym}-USDT"
    try:
        res = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5).json()
        if res.get("code") == "200000" and "data" in res:
            records = [{"close": float(i[2]), "high": float(i[3]), "low": float(i[4])} for i in res["data"]]
            return pd.DataFrame(records)[::-1].reset_index(drop=True).dropna()
    except: pass
    return None

def fetch_candles(symbol, timeframe="1h"):
    df = get_binance_candles(symbol, timeframe)
    if df is not None: return df
    df = get_gateio_candles(symbol, timeframe)
    if df is not None: return df
    return get_kucoin_candles(symbol, timeframe)

# ======================== 3. MULTI-TIMEFRAME ANALYSIS (1H + 15M) ========================
def analyze_tya_system(symbol):
    df_1h = fetch_candles(symbol, "1h")
    df_15m = fetch_candles(symbol, "15m")
    
    if df_1h is None or df_15m is None or len(df_1h) < 100 or len(df_15m) < 100: 
        return symbol, "CHOPPY", "AVOID", [], {}

    try:
        # --- 1H Macro Trend ---
        ema21_1h = df_1h["close"].ewm(span=21, adjust=False).mean().iloc[-1]
        ema35_1h = df_1h["close"].ewm(span=35, adjust=False).mean().iloc[-1]
        ema89_1h = df_1h["close"].ewm(span=89, adjust=False).mean().iloc[-1]
        ema200_1h = df_1h["close"].ewm(span=200, adjust=False).mean().iloc[-1]
        
        macro_regime = "CHOPPY"
        if (ema89_1h > ema200_1h) and (ema21_1h > ema35_1h): macro_regime = "BUY"
        elif (ema89_1h < ema200_1h) and (ema21_1h < ema35_1h): macro_regime = "SELL"

        # --- 15M Radar (Setup & Entry) ---
        c_val = df_15m["close"].iloc[-1]
        ema89_15m = df_15m["close"].ewm(span=89, adjust=False).mean()
        ema200_15m = df_15m["close"].ewm(span=200, adjust=False).mean()
        e89_15m_v, e200_15m_v = ema89_15m.iloc[-1], ema200_15m.iloc[-1]

        # EMA 89 Distance Guard
        dist_pct = (abs(c_val - e89_15m_v) / e89_15m_v) * 100

        # MACD (12,26)
        exp1 = df_15m["close"].ewm(span=12, adjust=False).mean()
        exp2 = df_15m["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        
        # MACD Balance 3.0 Lookback 48
        macd_peak = macd.rolling(window=48).max().iloc[-1]
        macd_trough = macd.rolling(window=48).min().iloc[-1]
        m_val = macd.iloc[-1]
        
        is_zero_buy = (m_val > 0) and (m_val <= (macd_peak * 0.20))
        is_zero_sell = (m_val < 0) and (m_val >= (macd_trough * 0.20))
        is_reversal_up = (c_val > e200_15m_v) and (df_15m["close"].iloc[-2] <= ema200_15m.iloc[-2])

        # --- Tagging & Action Buckets ---
        bucket = "AVOID"
        tags = []

        if dist_pct > 0.50:
            bucket = "AVOID"
            tags.append(f"ปลายน้ำ (ห่าง {dist_pct:.2f}%)")
        elif macro_regime == "BUY":
            if is_zero_buy:
                bucket = "BUY"
                tags.append("ZERO-STATION")
            elif is_reversal_up:
                bucket = "BUY"
                tags.append("REVERSAL WATCH (เบรก 200)")
            else:
                bucket = "AVOID"
                tags.append("รอพักตัว")
        elif macro_regime == "SELL":
            if is_zero_sell:
                bucket = "SELL"
                tags.append("ZERO-STATION")
            else:
                bucket = "AVOID"
                tags.append("รอเด้ง")
        else:
            tags.append("ไซด์เวย์")

        pct_change = ((c_val - df_15m["close"].iloc[-96]) / df_15m["close"].iloc[-96]) * 100 # 24H change approx
        price_data = {"price": c_val, "pct": pct_change, "ema89": e89_15m_v, "dist": dist_pct}

        return symbol, macro_regime, bucket, tags, price_data

    except Exception:
        return symbol, "CHOPPY", "AVOID", [], {}

# ======================== 3.5 DYNAMIC SESSION PROTOCOL ========================
def get_session_context():
    """แบ่ง โซนเวลา และ แผนคุมความเสี่ยงที่ชัดเจนตามพฤติกรรมแต่ละตลาด"""
    tz = timezone(timedelta(hours=7))
    hour = datetime.now(tz).hour
    
    if 7 <= hour < 14:
        session_name = "ตลาดเอเชีย (Asian Session / ผันผวนต่ำถึงปานกลาง)"
        risk_rule = "*คำสั่งพิเศษ (Asian Session):* ตลาดมักซึม หรือวิ่งในกรอบแคบ ให้ระวัง False Breakout เน้นเข้าเทรดเฉพาะไม้ที่ย่อลึกแตะ Zero-Station ชัดเจนเท่านั้น ถ้าระยะไม่สวยให้ทับมือ"
    elif 14 <= hour < 19:
        session_name = "ตลาดลอนดอน (London Session / ฟอร์มเทรนด์)"
        risk_rule = "*คำสั่งพิเศษ (London Session):* วอลุ่มเริ่มเข้า อาจมีการทำ Fakeout เพื่อสะบัดกวาด Low/High ของตลาดเอเชียก่อน ให้เน้นเทรดไปในทิศทางเดียวกับ 1H Macro Trend เป็นหลัก สามารถรันเทรนด์ได้"
    elif 19 <= hour < 23:
        session_name = "ตลาดสหรัฐฯ & ข่าวเศรษฐกิจ (NY Open / ผันผวนสูงมาก)"
        risk_rule = "*คำสั่งพิเศษ (NY/US Session):* ระวังข่าวเศรษฐกิจ! ให้ลด Margin ลง 50% (ใช้โควต้าไฟ YELLOW), งดสเกลป์สั้น 5M, รอแท่ง 15M ยืนยันหลังกวาดสภาพคล่อง, และเน้นปิด TP1 (1.5R) แล้วดัน SL บังทุนทันที"
    else:
        session_name = "นอกเวลาทำการหลัก (After Hours / วอลุ่มบาง ไซด์เวย์ซึม)"
        risk_rule = "*คำสั่งพิเศษ (After Hours):* สภาพคล่องต่ำ กราฟมักไซด์เวย์ออกข้างหรือซึมลง แนะนำให้ชะลอการเปิดออเดอร์ใหม่ หากมีไม้อยู่ให้ตั้ง SL บังหน้าทุนเพื่อล็อคความเสี่ยง"
        
    return session_name, risk_rule

# ======================== 4. TELEGRAM SENDER ========================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: http.post(url, json=payload, timeout=10)
    except: pass

# ======================== 5. MAIN LOGIC & AI PROMPT ========================
def main():
    print("🚀 เริ่มสแกน Multi-Timeframe (1H Macro + 15M Setup)...")
    
    macro_buy, macro_sell, macro_chop = [], [], []
    action_buy, action_sell, action_avoid = [], [], []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, regime, bucket, tags, data in executor.map(analyze_tya_system, WATCHLIST):
            if regime == "BUY": macro_buy.append(sym)
            elif regime == "SELL": macro_sell.append(sym)
            else: macro_chop.append(sym)
            
            tier = TIER_STRUCTURE.get(sym, "Other")
            item_str = f"{sym} [{tier}] (ราคา: {format_price(data.get('price',0))}, ห่าง EMA89: {data.get('dist',0):.2f}%, Tags: {', '.join(tags)})"
            
            if bucket == "BUY": action_buy.append(item_str)
            elif bucket == "SELL": action_sell.append(item_str)
            else:
                if "ปลายน้ำ" in str(tags): action_avoid.append(item_str)

    session_str, risk_protocol = get_session_context()

    raw_data_str = (
        f"ข้อมูลตลาดปัจจุบัน (จำนวนเหรียญ 34 สินทรัพย์):\n"
        f"- 1H โครงสร้างขาขึ้น (BUY): {len(macro_buy)}\n"
        f"- 1H โครงสร้างขาลง (SELL): {len(macro_sell)}\n"
        f"- 1H ไซด์เวย์ (CHOPPY): {len(macro_chop)}\n\n"
        f"[เป้าหมายเข้าเทรด 15M BUY (ดักย่อ / ต้นเทรนด์)]\n" + "\n".join(action_buy[:5]) + "\n\n"
        f"[เป้าหมายเข้าเทรด 15M SELL (ดักเด้ง)]\n" + "\n".join(action_sell[:5]) + "\n\n"
        f"[โซนอันตราย เลี่ยงเทรด/ปลายน้ำ]\n" + "\n".join(action_avoid[:5])
    )

    system_prompt = f"""
คุณคือ 'หัวหน้าคุมความเสี่ยงประจำห้องเทรด (TYA.AUN 15M Radar)'
แปลผลข้อมูลด้านล่างเป็น "ภาษาไทยวงการเทรด (สั้น กระชับ ตรงจุด)"

[บริบทเวลาและความเสี่ยง]
เวลาปัจจุบัน: {session_str}
{risk_protocol}

[ข้อมูลสแกนเนอร์ 1H และ 15M]
{raw_data_str}

[รูปแบบการตอบ (ห้ามเปลี่ยน Layout และห้ามพูดเกริ่นนำ)]
🧭 *[15M TYA.AUN RADAR & 1H MACRO FLOW]*
────────────────────────────
⏰ *ช่วงเวลา:* {session_str}
🌐 *โครงสร้าง 1H:* 🟢 ขาขึ้น {len(macro_buy)} | 🔴 ขาลง {len(macro_sell)} | ⚪️ ไซด์เวย์ {len(macro_chop)} (34 สินทรัพย์)

⚠️ *กฎคุมความเสี่ยง & แผนปฏิบัติการ:*
(สรุปคำแนะนำการเทรดให้สอดคล้องกับ "คำสั่งพิเศษตาม Session" ด้านบน ผสมกับ Market Breadth ที่เห็น ด้วยภาษาเทรดเดอร์ที่เฉียบขาด เช่น ดักย่อ, ทับมือ, ระวังกวาด SL, หากมี BTC ดูดสภาพคล่องให้แจ้งเตือนด้วย)

🎯 *[โฟกัสพิเศษ: 15M เข้าโซนยิง / เฝ้ากลับตัว]*
(เลือกเหรียญจากเป้าหมาย BUY/SELL ด้านบนมา 2-3 เหรียญ อธิบายโครงสร้าง 1H/15M และระบุ Action Plan ที่เจาะจง เช่น 'รอสัญญาณสายฟ้า 15M เข้า BUY')
🟢 *COIN_NAME* `[1H: ขาขึ้น + 15M: ZERO-STATION]`
  • *ราคา:* `ราคา` | *สถานะ:* (เช่น 1H คุมเทรนด์ขาขึ้น / 15M พักตัวลึกแตะโซนสมดุล)
  • *Action:* (เช่น รอสัญญาณสายฟ้าบน 15M แล้วเข้า BUY)

⛔️ *[โซนเลี่ยงเทรด / เสี่ยงติดดอย & สับขาหลอก]*
(เลือกจากโซนอันตรายมาเตือน 2-3 เหรียญ เช่น ห้ามไล่ราคาเพราะปลายน้ำ)

────────────────────────────
📌 *Checklist:* 1H กรองเทรนด์ ➔ 15M ดักย่อ Zero-Station ➔ 5M คอนเฟิร์มจุดตัด SL แคบ
"""

    ai_insight = "⚠️ ขัดข้อง ไม่สามารถเชื่อมต่อ AI ได้"
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY.strip())
            # ลูป Retry แบบ Exponential Backoff สำหรับ 3.6-flash
            for attempt in range(1, 5):
                try:
                    print(f"Sending to Gemini API (gemini-3.6-flash) [Attempt {attempt}/4]...")
                    response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=system_prompt,
                    )
                    if response and response.text:
                        ai_insight = response.text.strip()
                        print("Gemini API call successful.")
                        break
                except Exception as err:
                    print(f"Gemini API Attempt {attempt} Error: {err}")
                    if attempt < 4:
                        time.sleep(attempt * 3)
        except Exception as e:
            print(f"Gemini Client Init Error: {e}")

    send_telegram(ai_insight)
    print("✅ สแกน Multi-TF และส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
