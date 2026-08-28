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

# --- ดึง Token จาก GitHub Secrets / Environment Variables ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==========================================
# 1. ฐานข้อมูล WATCHLIST 33+1 (A.Aun Setup)
# ==========================================
SECTORS = {
    "Macro Core": ["BTCUSDT", "XAUUSDT"],
    "Tier 1 Majors": ["ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
    "PoW": ["BCHUSDT", "ETCUSDT", "KASUSDT", "LTCUSDT", "ZECUSDT"],
    "Layer 1": ["APTUSDT", "AVAXUSDT", "INJUSDT", "NEARUSDT", "SUIUSDT"],
    "Layer 2": ["ARBUSDT", "OPUSDT", "POLUSDT"],
    "RWA": ["ONDOUSDT"],
    "AI & DePIN": ["ARKMUSDT", "FETUSDT", "RENDERUSDT", "TAOUSDT", "WLDUSDT"],
    "DeFi": ["AAVEUSDT", "DYDXUSDT", "ENAUSDT", "PENDLEUSDT", "UNIUSDT"],
    "Infra & Oracles": ["GRTUSDT", "JUPUSDT", "LINKUSDT", "PYTHUSDT"]
}

# ==========================================
# 2. ROUTER FETCHING LOGIC (ดึงราคา + Volume)
# ==========================================
def get_binance_candles(symbol, timeframe, limit=48):
    if symbol in ["XAUUSDT", "XAUTUSDT"]: return None
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    try:
        res = http.get(url, timeout=4).json()
        if isinstance(res, list) and len(res) >= limit // 2:
            df = pd.DataFrame(res, columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
            for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
            return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
    except: pass
    return None

def get_gateio_candles(symbol, timeframe, limit=48):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    url = f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval={timeframe}&limit={limit}"
    try:
        res = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4).json()
        if isinstance(res, list) and len(res) >= limit // 2:
            records = [{"open": float(i.get("o", 0)), "high": float(i.get("h", 0)), "low": float(i.get("l", 0)), "close": float(i.get("c", 0)), "volume": float(i.get("v", 0))} for i in res]
            df = pd.DataFrame(records).dropna().reset_index(drop=True)
            return df
    except: pass
    return None

def get_kucoin_candles(symbol, timeframe, limit=48):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    tf_map = {"1h": "1hour"}
    url = f"https://api.kucoin.com/api/v1/market/candles?type={tf_map.get(timeframe, timeframe)}&symbol={base_sym}-USDT"
    try:
        res = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4).json()
        if res.get("code") == "200000" and "data" in res:
            records = [{"open": float(i[1]), "close": float(i[2]), "high": float(i[3]), "low": float(i[4]), "volume": float(i[5])} for i in res["data"]]
            return pd.DataFrame(records)[::-1].reset_index(drop=True).dropna()
    except: pass
    return None

def fetch_candles(symbol, timeframe, limit=48):
    df = get_binance_candles(symbol, timeframe, limit)
    if df is not None: return df
    df = get_gateio_candles(symbol, timeframe, limit)
    if df is not None: return df
    return get_kucoin_candles(symbol, timeframe, limit)

# ==========================================
# 3. PERFORMANCE & OUTLIERS ANALYSIS
# ==========================================
def get_1h_performance(symbol):
    df = fetch_candles(symbol, timeframe="1h", limit=48)
    if df is None or len(df) < 26: 
        return symbol, 0.0, 1.0
    
    # คำนวณ % Change
    close_val = df["close"].iloc[-2]  
    prev_close = df["close"].iloc[-3] 
    pct_change = ((close_val - prev_close) / prev_close) * 100
    
    # คำนวณ Volume Surge (เทียบ 1H ล่าสุด กับค่าเฉลี่ย 24 แท่งก่อนหน้า)
    current_vol = df["volume"].iloc[-2]
    avg_vol_24 = df["volume"].iloc[-26:-2].mean()
    vol_surge = (current_vol / avg_vol_24) if avg_vol_24 > 0 else 1.0
    
    return symbol, pct_change, vol_surge

def get_market_session():
    tz = timezone(timedelta(hours=7))
    now = datetime.now(tz)
    hour = now.hour
    
    if 7 <= hour < 14: return "ตลาดเอเชีย (Asian Session / ผันผวนต่ำถึงปานกลาง)"
    elif 14 <= hour < 19: return "ตลาดลอนดอน (London Session / ฟอร์มเทรนด์)"
    elif 19 <= hour < 23: return "ตลาดสหรัฐฯ & ข่าวเศรษฐกิจ (NY Open / ผันผวนสูงมาก)"
    else: return "นอกเวลาทำการหลัก (After Hours / วอลุ่มบาง ไซด์เวย์)"

# ==========================================
# 4. TELEGRAM NOTIFICATION
# ==========================================
def send_telegram_msg(message, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": parse_mode, "disable_web_page_preview": True}
    try: http.post(url, json=payload, timeout=8)
    except: pass

# ==========================================
# 5. MAIN EXECUTION & STRICT GEMINI 3.6
# ==========================================
def main():
    print("Fetching Market Performance Data...")
    
    all_symbols = [coin for group in SECTORS.values() for coin in group]
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, pct, vol in executor.map(get_1h_performance, all_symbols):
            results[sym] = {"pct": pct, "vol": vol}
            
    # คำนวณ Sector & Breadth
    sector_perf = {}
    green_count, red_count = 0, 0
    crypto_data = []
    
    for sector, coins in SECTORS.items():
        valid_coins = [results[c]["pct"] for c in coins if c in results]
        avg_pct = sum(valid_coins) / len(valid_coins) if valid_coins else 0.0
        sector_perf[sector] = avg_pct
        
        for c in coins:
            if c != "XAUUSDT" and c in results:
                crypto_data.append((c, results[c]["pct"], results[c]["vol"]))
                if results[c]["pct"] > 0: green_count += 1
                elif results[c]["pct"] < 0: red_count += 1

    total_crypto = green_count + red_count
    red_pct_str = f"{(red_count / total_crypto * 100):.0f}" if total_crypto > 0 else "0"
    
    # หาสิ่งผิดปกติ (Outliers)
    crypto_data.sort(key=lambda x: x[1], reverse=True)
    top_gainers = crypto_data[:2]
    top_losers = crypto_data[-2:]
    
    crypto_data.sort(key=lambda x: x[2], reverse=True)
    top_vol_surges = [x for x in crypto_data if x[2] >= 2.0][:2]
    
    btc_perf = results.get("BTCUSDT", {}).get("pct", 0.0)
    gold_perf = results.get("XAUUSDT", {}).get("pct", 0.0)
    
    session_info = get_market_session()
    
    gain_str = ", ".join([f"{s.replace('USDT','')} (+{p:.2f}%)" for s, p, v in top_gainers]) if top_gainers else "ไม่มี"
    lose_str = ", ".join([f"{s.replace('USDT','')} ({p:.2f}%)" for s, p, v in top_losers]) if top_losers else "ไม่มี"
    surge_str = ", ".join([f"{s.replace('USDT','')} (x{v:.1f})" for s, p, v in top_vol_surges]) if top_vol_surges else "วอลุ่มตลาดปกติ"

    # --- PROMPT ภาษาไทยสำหรับนักเทรด ---
    system_prompt = f"""
คุณคือ "หัวหน้าคุมความเสี่ยงประจำห้องเทรด" (ระบบ A.Aun Setup)
หน้าที่ของคุณคือประเมินสภาพแวดล้อมตลาดจากข้อมูลตัวเลขด้านล่าง แล้วออกคำสั่งปฏิบัติการให้เทรดเดอร์ด้วย "ภาษาไทยของนักเทรดที่เข้าใจง่าย ชัดเจน ตรงไปตรงมา"

[ข้อมูลตลาดล่าสุด]
- ช่วงเวลาตลาด: {session_info}
- ทิศทางตลาด (เขียว/แดง): 🟢 {green_count} เหรียญ / 🔴 {red_count} เหรียญ (ฝั่งลงครองตลาด {red_pct_str}%)
- พี่ใหญ่ BTC: {btc_perf:+.2f}% | ทองคำ (XAU): {gold_perf:+.2f}%
- ภาพรวมรายกลุ่ม:
  Tier 1 Majors: {sector_perf['Tier 1 Majors']:+.2f}%, Layer 1: {sector_perf['Layer 1']:+.2f}%, Layer 2: {sector_perf['Layer 2']:+.2f}%
  DeFi: {sector_perf['DeFi']:+.2f}%, AI: {sector_perf['AI & DePIN']:+.2f}%, PoW: {sector_perf['PoW']:+.2f}%
- เหรียญบวกแรง: {gain_str}
- เหรียญร่วงหนัก: {lose_str}
- วอลุ่มพุ่งผิดปกติ (>2 เท่า): {surge_str}

[กฎเหล็กในการตอบ]
1. ห้ามเกริ่นนำ ห้ามทวนตัวเลขเปอร์เซ็นต์ซ้ำซ้อน
2. ใช้ภาษาไทยวงการเทรดที่อ่านแล้วเข้าใจทันที หลีกเลี่ยงภาษาอังกฤษปนไทยที่ไม่จำเป็น (เช่น ให้ใช้ "นั่งทับมือ", "ห้ามรับมีด", "ห้ามเปิด BUY", "ระวังกวาด Stop Loss", "เทรนด์จริงเริ่มวิ่ง", "ตลาดไม่มีแรงหนุน")
3. ตอบตามโครงสร้างนี้เป๊ะๆ:

🛑 สถานะ: [เลือก 1 ข้อที่ตรงที่สุด:
- นั่งทับมือ ชะลอเปิดไม้ (ตลาดนิ่ง ไม่มีแรงหนุน)
- ระวังโดนดูดสภาพคล่อง (เงินเข้า BTC ตัวเดียว Altcoins พักก่อน)
- เทรนด์จริงเริ่มวิ่ง ลุยตามแผน (เงินไหลเข้าทั้งกระดาน มีวอลุ่มหนุน)
- เทขายยกแผง ห้ามรับมีด (ตลาดดิ่งหนัก เงินหนีเข้าทอง)]

• สภาวะกระแสเงิน: [อธิบายการหมุนเงินว่าไหลเข้าหรือออก อิงจากจำนวนเหรียญเขียว/แดง และตัวนำตลาด]
• ประเมินความเสี่ยง: [อธิบายความน่าเชื่อถือของการวิ่ง เช็คว่ามีวอลุ่มหนุนจริงหรือแค่สะบัดหลอก/กวาด Stop Loss ช่วงข่าว]
• คำแนะนำหน้างาน: [ระบุคำสั่งชัดเจน เช่น นั่งทับมือฝั่ง BUY, โฟกัสตามน้ำฝั่ง SHORT, หรือรอแท่งเทียนนิ่งก่อนเข้า]
"""

    ai_insight = "ไม่สามารถเชื่อมต่อ AI ได้ในขณะนี้"
    if GEMINI_API_KEY:
        client = genai.Client(api_key=GEMINI_API_KEY.strip())
        for attempt in range(1, 4):
            try:
                print(f"Sending to Gemini API (gemini-3.6-flash) [Attempt {attempt}/3]...")
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=system_prompt,
                )
                if response and response.text:
                    ai_insight = response.text.strip()
                    print("Gemini API call successful.")
                    break
            except Exception as e:
                print(f"Gemini API Error (Attempt {attempt}): {e}")
                if attempt < 3:
                    time.sleep(3)

    # --- สร้างข้อความสรุปส่งเข้า Telegram ---
    msg = (
        f"🧭 <b>[MARKET FLOW & AI REGIME 1H]</b>\n"
        f"────────────────────────\n"
        f"⏰ <b>ช่วงเวลา:</b> {session_info}\n"
        f"🌐 <b>ภาพรวมตลาด:</b> 🟢 {green_count} / 🔴 {red_count} (ฝั่งลงครองตลาด {red_pct_str}%)\n\n"
        f"📊 <b>Macro & Sector Performance (1H):</b>\n"
        f"👑 BTC: <code>{btc_perf:+.2f}%</code> | 🥇 Gold: <code>{gold_perf:+.2f}%</code>\n"
        f"💎 Tier 1: <code>{sector_perf['Tier 1 Majors']:+.2f}%</code> | 🧠 AI: <code>{sector_perf['AI & DePIN']:+.2f}%</code>\n"
        f"🏗 L1: <code>{sector_perf['Layer 1']:+.2f}%</code>     | ⚡️ L2: <code>{sector_perf['Layer 2']:+.2f}%</code>\n"
        f"🏦 DeFi: <code>{sector_perf['DeFi']:+.2f}%</code>   | ⛏️ PoW: <code>{sector_perf['PoW']:+.2f}%</code>\n"
        f"🏛️ RWA: <code>{sector_perf['RWA']:+.2f}%</code>    | 🔗 Infra: <code>{sector_perf['Infra & Oracles']:+.2f}%</code>\n\n"
        f"⚡️ <b>Outliers & Volume Spike (1H):</b>\n"
        f"🚀 <b>บวกแรง:</b> <code>{gain_str}</code>\n"
        f"🩸 <b>ลบหนัก:</b> <code>{lose_str}</code>\n"
        f"⚠️ <b>วอลุ่มพุ่ง:</b> <code>{surge_str}</code>\n"
        f"────────────────────────\n"
        f"🤖 <b>AI Tactical Directive:</b>\n"
        f"{ai_insight}"
    )
    
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
