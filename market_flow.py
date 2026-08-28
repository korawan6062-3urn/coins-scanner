import os
import sys
import requests
import pandas as pd
import warnings
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from google import genai

warnings.filterwarnings("ignore")
http = requests.Session()

# --- ดึง Token จาก GitHub Secrets ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# จัดกลุ่มสินทรัพย์ (อิงตามระบบหลักที่เสถียร)
SECTORS = {
    "Macro & King": ["BTCUSDT", "XAUUSDT"],
    "Tier 1 Bluechip": ["ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
    "AI & Big Data": ["ARKMUSDT", "FETUSDT", "NEARUSDT", "RENDERUSDT", "TAOUSDT", "WLDUSDT"],
    "DeFi & RWA": ["AAVEUSDT", "DYDXUSDT", "ENAUSDT", "JUPUSDT", "LINKUSDT", "ONDOUSDT", "PENDLEUSDT"],
    "Layer 1 & 0": ["ADAUSDT", "APTUSDT", "ATOMUSDT", "AVAXUSDT", "DOTUSDT", "GRTUSDT", "ICPUSDT", "INJUSDT", "KASUSDT", "PYTHUSDT", "SEIUSDT", "SUIUSDT"],
    "Layer 2": ["ARBUSDT", "MANTAUSDT", "POLUSDT", "OPUSDT", "STRKUSDT", "TIAUSDT", "ZKUSDT"],
    "Memes & Beta": ["DOGEUSDT", "GALAUSDT", "PEPEUSDT", "RUNEUSDT", "SANDUSDT", "SHIBUSDT"]
}

# ==========================================
# ROUTER FETCHING LOGIC (Binance -> Gateio -> Kucoin)
# ==========================================
def get_binance_candles(symbol, timeframe, limit=1000):
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
                for col in ["open", "high", "low", "close"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_gateio_candles(symbol, timeframe, limit=1000):
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
                        records.append({"timestamp": float(item.get("t", 0)), "open": float(item.get("o", 0)), "high": float(item.get("h", 0)), "low": float(item.get("l", 0)), "close": float(item.get("c", 0))})
                    elif isinstance(item, list) and len(item) >= 6:
                        records.append({"timestamp": float(item[0]), "open": float(item[5]), "high": float(item[3]), "low": float(item[4]), "close": float(item[2])})
                if records:
                    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
                    return df[["open", "high", "low", "close"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_kucoin_candles(symbol, timeframe, limit=1000):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    tf_map = {"5m": "5min", "15m": "15min", "1h": "1hour", "4h": "4hour"}
    url = f"https://api.kucoin.com/api/v1/market/candles?type={tf_map.get(timeframe, timeframe)}&symbol={base_sym}-USDT"
    try:
        res = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= limit // 2:
            records = [{"open": float(i[1]), "close": float(i[2]), "high": float(i[3]), "low": float(i[4])} for i in res["data"]]
            return pd.DataFrame(records)[::-1].reset_index(drop=True).dropna()
    except: pass
    return None

def fetch_candles(symbol, timeframe, limit=60):
    df = get_binance_candles(symbol, timeframe, limit)
    if df is not None: return df
    df = get_gateio_candles(symbol, timeframe, limit)
    if df is not None: return df
    return get_kucoin_candles(symbol, timeframe, limit)

# ==========================================
# PERFORMANCE ANALYSIS & SESSION CONTEXT
# ==========================================
def get_1h_performance(symbol):
    """คำนวณ % เปลี่ยนแปลงของแท่ง 1H ปิดสมบูรณ์ล่าสุด"""
    df = fetch_candles(symbol, timeframe="1h", limit=60)
    if df is None or len(df) < 3: 
        return symbol, 0.0
    
    close_val = df["close"].iloc[-2]  # แท่ง 1H ที่ปิดแล้วล่าสุด
    prev_close = df["close"].iloc[-3] # แท่งก่อนหน้า
    
    pct_change = ((close_val - prev_close) / prev_close) * 100
    return symbol, pct_change

def get_session_context():
    """เพิ่มบริบทเวลาให้ AI ออกคำสั่งกฎคุมความเสี่ยงได้ตรงช่วงเวลาตลาด"""
    tz = timezone(timedelta(hours=7))
    hour = datetime.now(tz).hour
    
    if 7 <= hour < 14: return "ตลาดเอเชีย (Asia / วอลุ่มซึม)", "ตลาดมักไซด์เวย์ ระวังโดนสับขาหลอกช่วงข่าวเงียบ"
    elif 14 <= hour < 19: return "ตลาดลอนดอน (London / เริ่มฟอร์มเทรนด์)", "วอลุ่มเริ่มไหลเข้า โฟกัสเหรียญที่เริ่มบวกนำตลาด"
    elif 19 <= hour < 23: return "ตลาดสหรัฐฯ (NY Open / ผันผวนสูงมาก)", "⚠️ ระวังข่าวเศรษฐกิจ ลด Margin ลง 50% แล้วดัน SL บังหน้าทุนทันทีที่กำไร"
    else: return "นอกเวลาทำการ (After Hours / วอลุ่มบาง)", "งดเปิดสถานะใหม่ ชะลอการเทรดเพื่อล็อคกำไรรายวัน"

def send_telegram_msg(message, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": parse_mode, "disable_web_page_preview": True}
    try:
        res = http.post(url, json=payload, timeout=8)
        if res.status_code != 200: # Fallback หาก AI แทรกแท็ก HTML ผิดรูป
            plain = message.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
            http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=8)
        print("Telegram message sent successfully.")
    except Exception as e:
        print(f"Telegram Exception: {e}")

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    print("Fetching Market Performance Data...")
    
    all_symbols = [coin for group in SECTORS.values() for coin in group]
    results = {}
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, pct in executor.map(get_1h_performance, all_symbols):
            results[sym] = pct
            
    # คำนวณค่าเฉลี่ยรายกลุ่ม (Sector Average)
    sector_perf = {}
    for sector, coins in SECTORS.items():
        valid_coins = [results[c] for c in coins if c in results and c != "XAUUSDT"]
        avg_pct = sum(valid_coins) / len(valid_coins) if valid_coins else 0.0
        sector_perf[sector] = avg_pct
        
    btc_perf = results.get("BTCUSDT", 0.0)
    gold_perf = results.get("XAUUSDT", 0.0)
    
    # หาสินทรัพย์ที่โดดเด่น (Outliers)
    sorted_coins = sorted([(k, v) for k, v in results.items() if k != "XAUUSDT"], key=lambda x: x[1], reverse=True)
    top_gainers = [f"{s.replace('USDT','')} ({p:+.2f}%)" for s, p in sorted_coins[:2]]
    top_losers = [f"{s.replace('USDT','')} ({p:+.2f}%)" for s, p in sorted_coins[-2:]]
    
    session_name, session_rule = get_session_context()
    
    prompt_data = (
        f"ข้อมูลผลตอบแทนในกรอบ 1 ชั่วโมงล่าสุด (1H % Change):\n"
        f"- BTC: {btc_perf:+.2f}%\n"
        f"- ทองคำ (XAU): {gold_perf:+.2f}%\n\n"
        f"ค่าเฉลี่ยผลตอบแทนรายกลุ่ม (Sector Average % Change):\n"
    )
    for s, p in sector_perf.items():
        if "Macro" not in s:
            prompt_data += f"- {s}: {p:+.2f}%\n"

    # --- PROMPT ใหม่: เน้น Fact & Bullet Point ตามที่ตกลงไว้ ---
    system_prompt = f"""
คุณคือนักวิเคราะห์ Quant เชิงมหภาค (Macro Quant Analyst)
จงวิเคราะห์ทิศทางกระแสเงินทุน (Capital Rotation) จากข้อมูล % Change 1H ของตลาด ณ ปัจจุบัน

[บริบทประกอบการวิเคราะห์]
Session ปัจจุบัน: {session_name}
บวกนำตลาด: {', '.join(top_gainers)}
ลบฉุดตลาด: {', '.join(top_losers)}

[ข้อมูลค่าเฉลี่ยกลุ่มสินทรัพย์]
{prompt_data}

[ฟอร์แมตการตอบ (ห้ามเปลี่ยน Layout และห้ามเขียนคำเกริ่นนำ)]
🛑 <b>สถานะตลาด:</b> [ตอบสั้นๆ เช่น ลุยฝั่ง Long / ทับมือ / ระวังสับขาหลอกช่วงข่าว / ตลาดซึมรอเลือกทาง]

📊 <b>สรุปกระแสเงิน 1H (Fact):</b>
• [Fact 1: วิเคราะห์ทิศทางเงินเข้า Risk-On (BTC/Alts) หรือ Risk-Off (ทองคำ)]
• [Fact 2: เปรียบเทียบ Sector ผู้นำที่เงินกำลังหมุนเข้าไป]

⚠️ <b>กฎคุมความเสี่ยง (Session Rules):</b>
• {session_rule}

🎯 <b>แผนปฏิบัติการ (Action Plan):</b>
• [สรุปกลยุทธ์ชั่วโมงนี้ว่าควรเปิด BUY กลุ่มไหน หรือ SELL กลุ่มไหน หรือ ทับมือ]
"""

    ai_insight = "⚠️ ขัดข้อง ไม่สามารถเชื่อมต่อ AI ได้ในขณะนี้ โปรดตรวจสอบ API Key หรือโควต้าการใช้งาน"
    if GEMINI_API_KEY:
        try:
            print("Sending to Gemini API (gemini-3.6-flash)...")
            client = genai.Client(api_key=GEMINI_API_KEY.strip())
            # บังคับล็อกโมเดลตามคำสั่งเด็ดขาด
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=system_prompt,
            )
            ai_insight = response.text.strip()
            print("✅ AI ประมวลผลสำเร็จ")
        except Exception as e:
            print(f"Gemini API Error: {e}")

    # --- โครงสร้างข้อความ Telegram (อัปเดตให้อ่านง่าย สแกนไว) ---
    msg = (
        f"🧭 <b>[1H MARKET FLOW & MACRO RADAR]</b>\n"
        f"────────────────────────\n"
        f"⏰ <b>เวลา:</b> {session_name}\n\n"
        f"<b>📊 Sector Performance (1H):</b>\n"
        f"👑 BTC: <code>{btc_perf:+.2f}%</code> | 🥇 Gold: <code>{gold_perf:+.2f}%</code>\n"
        f"💎 Tier 1: <code>{sector_perf['Tier 1 Bluechip']:+.2f}%</code>\n"
        f"🧠 AI: <code>{sector_perf['AI & Big Data']:+.2f}%</code>\n"
        f"🏗 L1: <code>{sector_perf['Layer 1 & 0']:+.2f}%</code> | ⚡ L2: <code>{sector_perf['Layer 2']:+.2f}%</code>\n"
        f"🏦 DeFi: <code>{sector_perf['DeFi & RWA']:+.2f}%</code>\n"
        f"🚀 Memes: <code>{sector_perf['Memes & Beta']:+.2f}%</code>\n"
        f"────────────────────────\n"
        f"<b>🤖 AI TACTICAL DIRECTIVE:</b>\n"
        f"{ai_insight}"
    )
    
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
