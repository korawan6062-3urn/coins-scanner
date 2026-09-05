## =========================================================================
## 📜 CHANGELOG HISTORY: MARKET FLOW & TACTICAL RADAR
## -------------------------------------------------------------------------
## LOG VER 4.0: [Base] อัปเกรดโครงสร้างจากการรายงานเหมาเข่ง 1H เป็น 15M Pre-Trigger (ดัก Pullback และ Squeeze), คำนวณ MACD (SMA) 100% ตาม TV, แจ้งข่าวเฉพาะ 07:00 น.
## LOG VER 4.1: [Weekend Gate & AI Logic Lock] ติดตั้งระบบกรองวันหยุดสุดสัปดาห์ บล็อก AI มโนข่าว CPI และล็อกสถานะตลาด Gold (XAU) ปิดทำการ พร้อมบังคับตรรกะระดับ Margin ให้สอดคล้องกับ Capital Flow เด็ดขาด
## LOG VER 4.2: [Full Strict Logic] ล็อกเงื่อนไข 15M Pullback/Squeeze ด้วย EMA21 และตำแหน่งราคา (Close) ป้องกันการรับมีด
## LOG VER 4.3: [Unbound AI Bias] ถอดระบบ AI BTC Grounding ออก คืนอิสระให้กราฟหน้างานและปลดล็อก Bias จาก BTC เพื่อรองรับ Altcoins ที่มี Volume ไหลเข้าอิสระ
## =========================================================================
import os
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

WATCHLIST = [
    "XAUUSDT", "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ZECUSDT", "XLMUSDT", "LINKUSDT", "ADAUSDT", "UNIUSDT", "BCHUSDT", 
    "LTCUSDT", "HBARUSDT", "AVAXUSDT", "SUIUSDT", "TAOUSDT", "NEARUSDT", 
    "WLDUSDT", "ONDOUSDT", "ENAUSDT", "DOTUSDT", "ETCUSDT", "ARBUSDT",
    "FILUSDT", "POLUSDT", "ALGOUSDT", "ATOMUSDT", "JUPUSDT", "ZROUSDT", 
    "ETHFIUSDT", "DASHUSDT", "ENSUSDT", "PENDLEUSDT", "APTUSDT",
    "INJUSDT", "PYTHUSDT", "OPUSDT", "FETUSDT", "TIAUSDT", "LDOUSDT"
]

# ======================== 2. DATA FETCHER ROUTER ========================
def get_binance_candles(symbol, timeframe="1h", limit=300):
    if symbol in ["XAUUSDT", "XAUTUSDT"]: return None
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = http.get(url, timeout=4).json()
            if isinstance(res, list) and len(res) >= 100:
                df = pd.DataFrame(res, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
                for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        except Exception: continue
    return None

def get_gateio_candles(symbol, timeframe="1h", limit=300):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    endpoints = [
        f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval={timeframe}&limit={limit}",
        f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}&interval={timeframe}&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = http.get(url, timeout=4).json()
            if isinstance(res, list) and len(res) >= 100:
                records = []
                for item in res:
                    if isinstance(item, dict): records.append({"timestamp": float(item.get("t", 0)), "open": float(item.get("o", 0)), "high": float(item.get("h", 0)), "low": float(item.get("l", 0)), "close": float(item.get("c", 0)), "volume": float(item.get("v", 0))})
                    elif isinstance(item, list) and len(item) >= 6: records.append({"timestamp": float(item[0]), "open": float(item[5]), "high": float(item[3]), "low": float(item[4]), "close": float(item[2]), "volume": float(item[1])})
                if records:
                    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
                    return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        except Exception: continue
    return None

def fetch_candles(symbol, timeframe="1h", limit=300):
    df = get_binance_candles(symbol, timeframe, limit)
    if df is not None: return df
    return get_gateio_candles(symbol, timeframe, limit)

# ==========================================
# 📊 3. PURE LOGIC MARKET ANALYZER (1H + 15M)
# ==========================================
def analyze_market(symbol):
    # --- 1H Macro Fetch ---
    df_1h = fetch_candles(symbol, "1h", 250)
    if df_1h is None or len(df_1h) < 200: return None

    c_1h, prev_1h = float(df_1h["close"].iloc[-2]), float(df_1h["close"].iloc[-3])
    pct_1h = ((c_1h - prev_1h) / prev_1h) * 100.0
    c_24h = float(df_1h["close"].iloc[-26]) if len(df_1h) >= 26 else float(df_1h["close"].iloc[0])
    pct_24h = ((c_1h - c_24h) / c_24h) * 100.0
    
    vol_cur = float(df_1h["volume"].iloc[-2])
    vol_avg = float(df_1h["volume"].iloc[-22:-2].mean())
    vol_surge = (vol_cur / vol_avg) if vol_avg > 0 else 1.0

    e21_1h = float(df_1h["close"].ewm(span=21, adjust=False).mean().iloc[-2])
    e35_1h = float(df_1h["close"].ewm(span=35, adjust=False).mean().iloc[-2])
    e89_1h = float(df_1h["close"].ewm(span=89, adjust=False).mean().iloc[-2])
    e200_1h = float(df_1h["close"].ewm(span=200, adjust=False).mean().iloc[-2])

    trend_1h = "NONE"
    if e89_1h > e200_1h and e21_1h > e35_1h: trend_1h = "BULL"
    elif e89_1h < e200_1h and e21_1h < e35_1h: trend_1h = "BEAR"

    # --- 15M Tactical Fetch (Pure Match with TV) ---
    df_15m = fetch_candles(symbol, "15m", 300)
    tactical = None
    if df_15m is not None and len(df_15m) >= 250:
        c_15m = float(df_15m["close"].iloc[-2])
        e21_15m = float(df_15m["close"].ewm(span=21, adjust=False).mean().iloc[-2])
        e35_15m = float(df_15m["close"].ewm(span=35, adjust=False).mean().iloc[-2])
        e89_15m = float(df_15m["close"].ewm(span=89, adjust=False).mean().iloc[-2])
        e200_15m = float(df_15m["close"].ewm(span=200, adjust=False).mean().iloc[-2])

        dist_89 = (abs(c_15m - e89_15m) / e89_15m) * 100.0
        spread = (abs(e89_15m - e200_15m) / e200_15m) * 100.0

        # MACD (Signal เป็น SMA ตรงตาม TradingView)
        exp1 = df_15m["close"].ewm(span=12, adjust=False).mean()
        exp2 = df_15m["close"].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.rolling(window=9).mean()
        hist = macd - signal

        m_val, h_val, h_prev = macd.iloc[-2], hist.iloc[-2], hist.iloc[-3]
        
        # Zero-Station Check (Lookback 48)
        m_window = macd.iloc[-49:-1]
        m_peak, m_trough, m_mean = m_window.max(), m_window.min(), m_window.mean()
        
        zero_buy = (m_val > 0) and ((m_val <= m_peak * 0.236) or (m_val <= m_mean * 0.786))
        zero_sell = (m_val < 0) and ((m_val >= m_trough * 0.236) or (m_val >= m_mean * 0.786))

        tactical = {
            "dist_89": dist_89,
            "spread": spread,
            "is_zero": zero_buy or zero_sell,
            "turn_up": h_val > h_prev,
            "turn_down": h_val < h_prev,
            "c_above_89": c_15m > e89_15m,
            "c_below_89": c_15m < e89_15m,
            "c_above_200": c_15m > e200_15m,
            "c_below_200": c_15m < e200_15m,
            "e21_above_89": e21_15m > e89_15m,
            "e21_below_89": e21_15m < e89_15m,
            "e21_above_35": e21_15m > e35_15m,
            "e21_below_35": e21_15m < e35_15m
        }

    return {"symbol": symbol, "pct_1h": pct_1h, "pct_24h": pct_24h, "vol_surge": vol_surge, "trend_1h": trend_1h, "tactical": tactical}

def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        res = http.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            payload["text"] = message.replace("_", " ").replace("*", "")
            http.post(url, json=payload, timeout=10)
    except Exception as e: print(f"[!] Telegram Error: {e}")

# ==========================================
# 🚀 4. MAIN PIPELINE & TELEGRAM FORMATTING
# ==========================================
def main():
    print(f"🚀 เริ่มสแกน 15M Tactical Radar (Watchlist: {len(WATCHLIST)} เหรียญ)...")
    
    # ⏰ ตรวจสอบเวลาและวันหยุด (Time & Weekend Gate)
    now_bkk = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=7)
    is_weekend = now_bkk.weekday() >= 5 # 5 = Saturday, 6 = Sunday
    is_0700 = (now_bkk.hour == 7)

    results, buy_pullback, buy_squeeze, sell_bounce, sell_squeeze = [], [], [], [], []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        for data in executor.map(analyze_market, WATCHLIST):
            if data: results.append(data)

    for r in results:
        sym, t = r["symbol"], r["tactical"]
        if not t: continue
        
        # บล็อกสัญญาณ XAUUSDT ในช่วงสุดสัปดาห์
        if is_weekend and sym == "XAUUSDT": continue
        
        sym_clean = sym.replace('USDT', '')
        macd_tags = []
        if t["is_zero"]: macd_tags.append("⚡ Zero-Station")
        
        if r["trend_1h"] == "BULL":
            if t["turn_up"]: macd_tags.append("🟢 Turn-Up")
            tag_str = f" `[{' | '.join(macd_tags)}]`" if macd_tags else ""
            
            # 15M Squeeze Plan B (BUY)
            if t["spread"] <= 0.382 and t["e21_above_35"] and t["c_above_89"] and t["c_above_200"]:
                buy_squeeze.append(f"• `{sym_clean:<6}` ➔ Spread `{t['spread']:.2f}%`{tag_str}")
            # Pullback Plan A (BUY)
            elif t["dist_89"] <= 0.80 and t["e21_above_89"] and t["c_above_89"]:
                buy_pullback.append(f"• `{sym_clean:<6}` ➔ ห่าง 89 `{t['dist_89']:.2f}%`{tag_str}")
                
        elif r["trend_1h"] == "BEAR":
            if t["turn_down"]: macd_tags.append("🔴 Turn-Down")
            tag_str = f" `[{' | '.join(macd_tags)}]`" if macd_tags else ""
            
            # 15M Squeeze Plan B (SELL)
            if t["spread"] <= 0.382 and t["e21_below_35"] and t["c_below_89"] and t["c_below_200"]:
                sell_squeeze.append(f"• `{sym_clean:<6}` ➔ Spread `{t['spread']:.2f}%`{tag_str}")
            # Bounce Short Plan A (SELL)
            elif t["dist_89"] <= 0.80 and t["e21_below_89"] and t["c_below_89"]:
                sell_bounce.append(f"• `{sym_clean:<6}` ➔ ห่าง 89 `{t['dist_89']:.2f}%`{tag_str}")

    # Top Gain/Loss/Vol
    sorted_1h = sorted([r for r in results if r["symbol"] != "XAUUSDT"], key=lambda x: x["pct_1h"], reverse=True)
    sorted_vol = sorted([r for r in results if r["symbol"] != "XAUUSDT"], key=lambda x: x["vol_surge"], reverse=True)
    
    top_gainers = [f"{r['symbol'].replace('USDT','')} ({r['pct_1h']:+.2f}%)" for r in sorted_1h[:2]]
    top_losers = [f"{r['symbol'].replace('USDT','')} ({r['pct_1h']:+.2f}%)" for r in sorted_1h[-2:]]
    top_vol = [f"{r['symbol'].replace('USDT','')} (x{r['vol_surge']:.1f})" for r in sorted_vol[:2] if r["vol_surge"] >= 2.0]

    btc_perf = next((r["pct_24h"] for r in results if r["symbol"] == "BTCUSDT"), 0.0)
    gold_perf = next((r["pct_24h"] for r in results if r["symbol"] == "XAUUSDT"), 0.0)

    # --- GEMINI STRICT AI DIRECTIVE & WEEKEND LOCK ---
    calendar_prompt = ""
    if is_0700:
        if is_weekend:
            calendar_prompt = "\n📅 *ตารางข่าวเศรษฐกิจประจำวัน:*\n• วันเสาร์-อาทิตย์ ตลาดการเงินสหรัฐฯ ปิดทำการ (ไม่มีประกาศตัวเลขเศรษฐกิจ Tier-1)"
        else:
            calendar_prompt = "\n📅 *ตารางข่าวเศรษฐกิจประจำวัน (รอบ 07:00 น.):*\n• [สรุปกำหนดการข่าวเศรษฐกิจ Tier-1 สหรัฐฯ ของวันนี้ทั้งหมด พร้อมระบุเวลาไทย หากวันนี้ไม่มีให้ระบุว่าไม่มี]"

    news_instruction = (
        "• สภาวะตลาดสุดสัปดาห์ ขับเคลื่อนด้วย Technical & Crypto Flow 100% (ห้ามอ้างอิงข่าวเศรษฐกิจสหรัฐฯ)" 
        if is_weekend else 
        "• [ตรวจสอบตัวเลขเศรษฐกิจ Tier-1 สหรัฐฯ หรือข่าวเทขายรุนแรงในชั่วโมงนี้ หากมีให้ระบุตัวเลขจริง สรุปผลกระทบ 1 บรรทัด และสั่ง '🛑 ให้นั่งทับมือรอจนกว่า...ระบุเวลา' หากไม่มีให้ระบุว่า 'สภาวะปกติ ขับเคลื่อนด้วย Technical Flow']"
    )

    gold_instruction = (
        "• Gold (XAU): ตลาดปิดทำการ (Weekend Close) - ไม่เปิดสถานะเทรด" 
        if is_weekend else 
        "• Gold (XAU): [ระบุ BUY หรือ SELL] ➔ [ระบุบทบาททางเทคนิคหรือการเป็น Asset Hedge 1 ประโยค]"
    )

    system_prompt = f"""
คุณคือนักวิเคราะห์ Macro และ Quant Risk Manager หน้าที่ของคุณคือฟันธงทิศทางตลาดและออกคำสั่งความเสี่ยงประจำชั่วโมง ห้ามเขียนคำเกริ่นนำ ห้ามใช้คำกำกวม และห้ามจินตนาการข่าวเศรษฐกิจในวันหยุด ตอบตามโครงสร้างนี้อย่างเคร่งครัด:

🎙️ *AI MACRO & CAPITAL FLOW DIRECTIVE*
{calendar_prompt}
⚠️ *สถานการณ์ข่าวเศรษฐกิจ & เหตุการณ์สำคัญ:*
{news_instruction}

🌊 *USD (DXY) & Capital Flow:*
• [ประเมินดัชนีดอลลาร์สั้นๆ สรุปทิศทางการไหลเวียน เช่น USD > Gold > BTC > Altcoins]

🎯 *คำสั่งบริหารพอร์ตและระดับ Margin ประจำชั่วโมง:*
• ระดับ Margin: [เลือกตอบเพียง 1 อย่าง: "เทรดเต็มกำลัง (100% Full Margin)" หรือ "ลดความเสี่ยง 50% (Defensive Margin)" หรือ "🛑 นั่งทับมือ 100% (Cash Only)"] (บังคับ: การลด Margin ต้องเกิดจากความเสี่ยงทางกราฟหรือข่าวจริงเท่านั้น ห้ามสั่งลด Margin หากย้อนแย้งกับทิศทางเงินทุนที่ไหลเข้าสินทรัพย์เสี่ยง)
• การจัดสรร Margin: [ระบุสัดส่วนสั้นๆ เช่น เงินสด/USDT __% | BTC __% | Altcoins __% | Gold __%]

🧭 *ทิศทางการเทรดประจำชั่วโมง (Tactical Bias):*
• BTC: [ระบุ BUY หรือ SELL] ➔ [ระบุจุดสังเกตหรือเงื่อนไข 1 ประโยค]
• Altcoins: [ระบุ BUY หรือ SELL] ➔ [ระบุกลุ่ม Sector ที่มีเทรนด์ชัดเจนที่สุด เช่น Layer 1, AI, DeFi, High-Beta]
{gold_instruction}
"""

    ai_insight = "⚠️ ขัดข้อง ไม่สามารถเชื่อมต่อ AI ได้"
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY.strip())
            for _ in range(3):
                try:
                    response = client.models.generate_content(model='gemini-3.6-flash', contents=system_prompt)
                    if response and response.text:
                        ai_insight = response.text.strip().replace("`", "'")
                        break
                except Exception as e:
                    if "429" in str(e) or "RESOURCE" in str(e): break
                    time.sleep(3)
        except Exception: pass

    # --- COMPILE TELEGRAM MESSAGE ---
    msg = [
        "🧭 *MARKET FLOW & 15M TACTICAL RADAR*",
        "────────────────────────────",
        f"👑 *BTC (24H):* `{btc_perf:+.2f}%` | 🥇 *Gold (24H):* `{gold_perf:+.2f}%`",
        f"⚡️ *Outliers (1H):* 🚀 {', '.join(top_gainers) if top_gainers else '-'} | 🩸 {', '.join(top_losers) if top_losers else '-'}",
        f"⚠️ *Volume Surge:* {', '.join(top_vol) if top_vol else 'ปกติ'}",
        "────────────────────────────",
        "🎯 *15M PRE-TRIGGER: จ่อคิวเข้าแผนเทรดสั้น*\n",
        "🟢 *ฝั่ง BUY (โครงสร้าง 1H ขาขึ้น):*",
        "• *Pullback Zone (ย่อชิดแนวรับ):*",
        "\n".join(buy_pullback) if buy_pullback else "  - ไม่มีเหรียญเข้าโซน",
        "• *15M Squeeze (บีบอัดเตรียมระเบิดขึ้น):*",
        "\n".join(buy_squeeze) if buy_squeeze else "  - ไม่มีเหรียญเข้าโซน\n",
        "🔴 *ฝั่ง SELL (โครงสร้าง 1H ขาลง):*",
        "• *Short on Bounce (เด้งชนแนวต้าน):*",
        "\n".join(sell_bounce) if sell_bounce else "  - ไม่มีเหรียญเข้าโซน",
        "• *15M Squeeze (บีบอัดเตรียมระเบิดลง):*",
        "\n".join(sell_squeeze) if sell_squeeze else "  - ไม่มีเหรียญเข้าโซน",
        "────────────────────────────",
        f"{ai_insight}"
    ]

    send_telegram_msg("\n".join(msg))
    print("✅ สแกน 15M Radar และส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
