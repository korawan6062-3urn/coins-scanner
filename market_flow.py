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
http.headers.update({"User-Agent": "Mozilla/5.0"})

# ======================== 1. CONFIG & WATCHLIST (CORE เดิม) ========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SECTORS = {
    "Macro Core": ["BTCUSDT", "XAUUSDT"],
    "Tier 1": ["ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
    "PoW": ["BCHUSDT", "ETCUSDT", "KASUSDT", "LTCUSDT", "ZECUSDT"],
    "Layer 1": ["APTUSDT", "AVAXUSDT", "INJUSDT", "NEARUSDT", "SUIUSDT"],
    "Layer 2": ["ARBUSDT", "OPUSDT", "POLUSDT"],
    "RWA": ["ONDOUSDT"],
    "AI": ["ARKMUSDT", "FETUSDT", "RENDERUSDT", "TAOUSDT", "WLDUSDT"],
    "DeFi": ["AAVEUSDT", "DYDXUSDT", "ENAUSDT", "PENDLEUSDT", "UNIUSDT"],
    "Infra": ["GRTUSDT", "JUPUSDT", "LINKUSDT", "PYTHUSDT"]
}

WATCHLIST = [coin for group in SECTORS.values() for coin in group]
TIER_MAP = {coin: sector for sector, coins in SECTORS.items() for coin in coins}

def format_price(val):
    if pd.isna(val): return "0.00"
    val = float(val)
    if abs(val) >= 1000: return f"{val:,.2f}"
    elif abs(val) >= 1: return f"{val:.4f}"
    else: return f"{val:.6f}"

# ======================== 2. ROBUST DATA FETCHER (CORE เดิม) ========================
def get_binance_candles(symbol, timeframe="1h", limit=250):
    if symbol in ["XAUUSDT", "XAUTUSDT"]: return None
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = http.get(url, timeout=5).json()
            if isinstance(res, list) and len(res) >= 200:
                df = pd.DataFrame(res, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"])
                for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
        except: continue
    return None

def get_gateio_candles(symbol, timeframe="1h", limit=250):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    pair = f"{base_sym}_USDT"
    url = f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={pair}&interval={timeframe}&limit={limit}"
    try:
        res = http.get(url, timeout=5).json()
        if isinstance(res, list) and len(res) >= 200:
            records = [{"open": float(i.get("o", 0)), "high": float(i.get("h", 0)), "low": float(i.get("l", 0)), "close": float(i.get("c", 0)), "volume": float(i.get("v", 0))} for i in res]
            return pd.DataFrame(records).dropna().reset_index(drop=True)
    except: pass
    return None

def get_kucoin_candles(symbol, timeframe="1h", limit=250):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    url = f"https://api.kucoin.com/api/v1/market/candles?type=1hour&symbol={base_sym}-USDT"
    try:
        res = http.get(url, timeout=5).json()
        if res.get("code") == "200000" and "data" in res:
            records = [{"open": float(i[1]), "close": float(i[2]), "high": float(i[3]), "low": float(i[4]), "volume": float(i[5])} for i in res["data"]]
            return pd.DataFrame(records)[::-1].reset_index(drop=True).dropna()
    except: pass
    return None

def fetch_candles(symbol):
    df = get_binance_candles(symbol)
    if df is not None: return df
    df = get_gateio_candles(symbol)
    if df is not None: return df
    return get_kucoin_candles(symbol)

# ======================== 3. STRUCTURAL ANALYSIS ========================
def analyze_1h_structure(symbol):
    df = fetch_candles(symbol)
    if df is None or len(df) < 200: 
        return symbol, 0.0, 1.0, "CHOPPY", "NONE", "", {}

    try:
        c_closed = df["close"].iloc[-2]
        o_closed = df["open"].iloc[-2]
        h_closed = df["high"].iloc[-2]
        l_closed = df["low"].iloc[-2]
        
        prev_close = df["close"].iloc[-3]
        pct_change = ((c_closed - prev_close) / prev_close) * 100
        vol_current = df["volume"].iloc[-2]
        vol_avg = df["volume"].iloc[-26:-2].mean()
        vol_surge = (vol_current / vol_avg) if vol_avg > 0 else 1.0

        ema21_series = df["close"].ewm(span=21, adjust=False).mean()
        ema35_series = df["close"].ewm(span=35, adjust=False).mean()
        ema89_series = df["close"].ewm(span=89, adjust=False).mean()
        ema200_series = df["close"].ewm(span=200, adjust=False).mean()
        
        ema21, ema35, ema89, ema200 = ema21_series.iloc[-2], ema35_series.iloc[-2], ema89_series.iloc[-2], ema200_series.iloc[-2]
        ema21_prev, ema35_prev = ema21_series.iloc[-3], ema35_series.iloc[-3]

        macd_line = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
        macd_sig = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_sig
        
        regime = "CHOPPY"
        if (ema89 > ema200) and (ema21 > ema35): regime = "BUY"
        elif (ema89 < ema200) and (ema21 < ema35): regime = "SELL"

        dist_89_pct = (abs(c_closed - ema89) / ema89) * 100
        body = abs(o_closed - c_closed)
        lower_wick = min(o_closed, c_closed) - l_closed
        upper_wick = h_closed - max(o_closed, c_closed)
        
        is_bull_pinbar = (lower_wick > (1.5 * body)) and (lower_wick > upper_wick)
        is_bear_pinbar = (upper_wick > (1.5 * body)) and (upper_wick > lower_wick)
        touch_ema89 = (l_closed <= ema89 <= h_closed) or (dist_89_pct < 0.3)
        cross_up = (ema21_prev <= ema35_prev) and (ema21 > ema35)
        cross_dn = (ema21_prev >= ema35_prev) and (ema21 < ema35)

        bucket, fact_str = "NONE", ""

        if dist_89_pct > 3.0:
            bucket = "AVOID"
            fact_str = f"ราคาตึงจัด ห่าง EMA89 ถึง {dist_89_pct:.2f}% เสี่ยงโดนเทขายทำกำไร"
        elif regime == "BUY":
            if is_bull_pinbar and touch_ema89:
                bucket, fact_str = "BUY", "ย่อทดสอบ EMA89 ไม่หลุด + ทิ้งไส้ล่างกวาด SL (Bullish Rejection)"
            elif cross_up:
                bucket, fact_str = "BUY", "EMA 21 ตัด 35 ขึ้น (Golden Setup) ยืนยันเทรนด์วิ่งต่อ"
            elif touch_ema89 and c_closed > ema89:
                bucket, fact_str = "BUY", "ราคาย่อแตะ EMA89 แล้วยืนทรงตัวได้ รอสัญญาณทะยาน"
        elif regime == "SELL":
            if is_bear_pinbar and touch_ema89:
                bucket, fact_str = "SELL", "เด้งทดสอบ EMA89 ไม่ผ่าน + ทิ้งไส้บนยาว (Bearish Rejection)"
            elif cross_dn:
                bucket, fact_str = "SELL", "EMA 21 ตัด 35 ลง ยืนยันเทรนด์ขาลงกดดันต่อ"
        
        if bucket == "NONE":
            if l_closed < df["low"].iloc[-10:-2].min() and macd_hist.iloc[-2] > macd_hist.iloc[-10:-2].min():
                if regime == "SELL" or ema89 < ema200:
                    bucket, fact_str = "REVERSAL", "เกิด Bullish Divergence 1H กราฟทำ False Break ล่าสุด"
            elif h_closed > df["high"].iloc[-10:-2].max() and macd_hist.iloc[-2] < macd_hist.iloc[-10:-2].max():
                if regime == "BUY" or ema89 > ema200:
                    bucket, fact_str = "REVERSAL", "เกิด Bearish Divergence โมเมนตัม 1H เริ่มแผ่ว"

        if bucket == "NONE" and (ema21 > ema89 and ema35 < ema89):
            bucket, fact_str = "AVOID", "ตลาดฟันปลา (EMA พันกันไร้ทรง) เสี่ยงโดนสับขาหลอก"

        return symbol, pct_change, vol_surge, regime, bucket, fact_str, {"price": c_closed}
    except Exception:
        return symbol, 0.0, 1.0, "CHOPPY", "NONE", "", {}

# ======================== 4. SESSION PROTOCOL & TELEGRAM ========================
def get_session_context():
    tz = timezone(timedelta(hours=7))
    hour = datetime.now(tz).hour
    
    if 7 <= hour < 14: return "ตลาดเอเชีย (Asia / วอลุ่มซึม)", "ระวัง False Breakout ทับมือรอตลาดยุโรป หรือเข้าเฉพาะตัวที่ Rejection ชัดๆ"
    elif 14 <= hour < 19: return "ตลาดลอนดอน (London / ฟอร์มเทรนด์)", "วอลุ่มเข้า รันเทรนด์ตามโครงสร้าง 1H ได้ ให้โฟกัสเหรียญที่มี Volume Surge"
    elif 19 <= hour < 23: return "ตลาดสหรัฐฯ (NY Open / ผันผวนสูงมาก)", "⚠️ ลด Margin 50% (ไฟ YELLOW) รอ 1H ปิดแท่งยืนยันแนวรับ ไม่เปิดสวนกลางแท่ง TP1 แล้วดัน SL บังทุนทันที"
    else: return "ดึก (After Hours / วอลุ่มบาง)", "ชะลอเปิดออเดอร์ใหม่ ขยับ SL บังทุนไม้เก่า ล็อคกำไรเข้านอน"

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: 
        res = http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=8)
        # 🛡️ Fallback: หาก AI แทรก HTML ผิดรูป (Error 400) ให้ส่งเป็นข้อความธรรมดาแทน ป้องกันการเงียบหาย
        if res.status_code != 200:
            print(f"⚠️ Telegram HTML Format Error: {res.text} -> กำลังส่งแบบ Plain Text แทน")
            clean_msg = message.replace('<b>', '').replace('</b>', '').replace('<code>', '').replace('</code>', '').replace('<i>', '').replace('</i>', '')
            http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": clean_msg, "disable_web_page_preview": True}, timeout=8)
    except Exception as e:
        print(f"❌ Telegram Post Error: {e}")

# ======================== 5. MAIN EXECUTION ========================
def main():
    print("🚀 ดึงข้อมูล 1H Structural Radar (Using Robust Core)...")
    
    results, sector_pct = {}, {}
    green_count, red_count = 0, 0
    crypto_data = []
    
    action_buy, action_sell, action_rev, action_avoid = [], [], [], []

    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, pct, vol, regime, bucket, fact_str, data in executor.map(analyze_1h_structure, WATCHLIST):
            results[sym] = {"pct": pct, "vol": vol}
            
            if bucket != "NONE":
                tier = TIER_MAP.get(sym, 'Other')
                price = format_price(data.get('price', 0))
                item_str = f"  • <b>{sym}</b> <code>[{tier}]</code> | ราคา: <code>{price}</code>\n    └ <i>Fact:</i> {fact_str}"
                
                if bucket == "BUY": action_buy.append(item_str)
                elif bucket == "SELL": action_sell.append(item_str)
                elif bucket == "REVERSAL": action_rev.append(item_str)
                elif bucket == "AVOID": action_avoid.append(item_str)

    # คำนวณ Sector & Breadth อย่างปลอดภัย
    for sector, coins in SECTORS.items():
        valid_pct = [results[c]["pct"] for c in coins if c in results and c != "XAUUSDT"]
        sector_pct[sector] = (sum(valid_pct) / len(valid_pct)) if valid_pct else 0.0

    for c in WATCHLIST:
        if c != "XAUUSDT" and c in results:
            pct_val = results[c]["pct"]
            crypto_data.append((c, pct_val, results[c]["vol"]))
            if pct_val > 0: green_count += 1
            elif pct_val < 0: red_count += 1

    crypto_data.sort(key=lambda x: x[1], reverse=True)
    top_gainers = [f"{s.replace('USDT','')} ({p:+.2f}%)" for s, p, v in crypto_data[:2]]
    top_losers = [f"{s.replace('USDT','')} ({p:+.2f}%)" for s, p, v in crypto_data[-2:]]
    
    crypto_data.sort(key=lambda x: x[2], reverse=True)
    top_vol = [f"{s.replace('USDT','')} (x{v:.1f})" for s, p, v in crypto_data if v >= 2.0][:2]

    session_name, session_rule = get_session_context()
    btc_perf = results.get("BTCUSDT", {}).get("pct", 0.0)
    gold_perf = results.get("XAUUSDT", {}).get("pct", 0.0)

    # --- AI PROMPT ---
    system_prompt = f"""
คุณคือ Risk Manager หน้าที่ของคุณคือวิเคราะห์ข้อมูลแล้วสรุป "Fact (ข้อเท็จจริง)" และ "Action (แผน)" เป็น Bullet point สั้นๆ กระชับ ห้ามเขียนบรรยายยาว

[ข้อมูลตลาด 1H]
Session: {session_name}
ทิศทาง: เขียว {green_count} / แดง {red_count}
BTC: {btc_perf:+.2f}% | XAU: {gold_perf:+.2f}%
Gainers: {', '.join(top_gainers)} | Losers: {', '.join(top_losers)}
Vol Surge: {', '.join(top_vol) if top_vol else 'ไม่มี'}

[ฟอร์แมตการตอบ (ห้ามเปลี่ยน Layout ห้ามใส่คำเกริ่นนำ)]
🤖 <b>AI TACTICAL DIRECTIVE:</b>
🛑 <b>สถานะตลาด:</b> [เช่น ลุยฝั่ง Long / ทับมือ / ระวังสับขาหลอกช่วงข่าว / ตลาดซึมรอเลือกทาง]

📊 <b>สรุปกระแสเงิน 1H (Fact):</b>
• [Fact 1: วิเคราะห์ทิศทางเงินอ้างอิงจากเขียว/แดง และ Gainer]
• [Fact 2: วิเคราะห์วอลุ่มเชื่อมโยง เช่น มีวอลุ่มหนุนชัดเจน หรือ ทองคำขึ้นสวน]

⚠️ <b>กฎคุมความเสี่ยง (Session Rules):</b>
• {session_rule}

🎯 <b>แผนปฏิบัติการ (Action Plan):</b>
• [สรุปว่าชั่วโมงนี้ควรทำอะไร โฟกัสไปที่ทิศทางไหน หรือควรงดเทรด]
"""

    ai_insight = "⚠️ ขัดข้อง ไม่สามารถเชื่อมต่อ AI ได้ โปรดตรวจสอบ API หรือ โควต้าใช้งาน"
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY.strip())
            
            # 🛡️ Auto-Model Fallback: ลำดับโมเดล ลองใช้ 3.6 ก่อนตามที่คุณสั่ง 
            # ถ้า API คืนค่า 404 (ไม่พบโมเดล) จะสลับไปใช้ 1.5-flash ให้อัตโนมัติ งานจะได้ไม่สะดุด
            models_to_try = ['gemini-3.6-flash', 'gemini-1.5-flash', 'gemini-2.0-flash']
            
            for model_name in models_to_try:
                success = False
                for attempt in range(1, 3):
                    try:
                        print(f"⏳ ส่งข้อมูลให้ AI ประมวลผลด้วยโมเดล: {model_name} [ครั้งที่ {attempt}/2]...")
                        res = client.models.generate_content(model=model_name, contents=system_prompt)
                        if res and res.text:
                            ai_insight = res.text.strip()
                            success = True
                            print(f"✅ AI ประมวลผลสำเร็จ ({model_name})")
                            break
                    except Exception as e:
                        print(f"⚠️ API Error ({model_name}): {e}")
                        time.sleep(2)
                if success:
                    break # หลุดออกจากลูปเปลี่ยนโมเดลเมื่อยิงสำเร็จแล้ว
        except Exception as e: 
            print(f"❌ Gemini Setup Error: {e}")

    buy_str = "\n".join(action_buy[:3]) if action_buy else "  • (ไม่มีเหรียญเข้าเกณฑ์)"
    sell_str = "\n".join(action_sell[:3]) if action_sell else "  • (ไม่มีเหรียญเข้าเกณฑ์)"
    rev_str = "\n".join(action_rev[:3]) if action_rev else "  • (ไม่มีเหรียญเข้าเกณฑ์)"
    avoid_str = "\n".join(action_avoid[:3]) if action_avoid else "  • (ไม่มีเหรียญที่อันตรายชัดเจน)"

    msg = (
        f"🧭 <b>[1H MARKET FLOW & MACRO RADAR]</b>\n"
        f"────────────────────────────\n"
        f"⏰ <b>เวลา:</b> {session_name}\n"
        f"🌐 <b>ภาพรวม 1H:</b> 🟢 ขาขึ้น {green_count} | 🔴 ขาลง {red_count}\n\n"
        f"📊 <b>Macro Performance (1H):</b>\n"
        f"👑 BTC: <code>{btc_perf:+.2f}%</code> | 🥇 Gold: <code>{gold_perf:+.2f}%</code>\n"
        f"💎 Tier1: <code>{sector_pct.get('Tier 1', 0.0):+.2f}%</code> | 🧠 AI: <code>{sector_pct.get('AI', 0.0):+.2f}%</code>\n"
        f"🏗 L1: <code>{sector_pct.get('Layer 1', 0.0):+.2f}%</code> | 🏦 DeFi: <code>{sector_pct.get('DeFi', 0.0):+.2f}%</code>\n\n"
        f"⚡️ <b>Outliers & Volume Spike:</b>\n"
        f"🚀 <b>บวกแรง:</b> <code>{', '.join(top_gainers) if top_gainers else '-'}</code>\n"
        f"🩸 <b>ลบหนัก:</b> <code>{', '.join(top_losers) if top_losers else '-'}</code>\n"
        f"⚠️ <b>วอลุ่มพุ่ง:</b> <code>{', '.join(top_vol) if top_vol else 'ปกติ'}</code>\n"
        f"────────────────────────────\n"
        f"🎯 <b>[1H STRUCTURAL RADAR: พฤติกรรมราคา]</b>\n\n"
        f"🟢 <b>BUY WATCH (ดักย่อ EMA / จ่อตัด / ทิ้งไส้ล่าง):</b>\n{buy_str}\n\n"
        f"🔴 <b>SELL WATCH (ดักเด้ง EMA / จ่อหลุด / ทิ้งไส้บน):</b>\n{sell_str}\n\n"
        f"🔄 <b>REVERSAL (Divergence / จบรอบ / False Break):</b>\n{rev_str}\n\n"
        f"⛔️ <b>โซนเลี่ยงเทรด (ปลายน้ำตึงจัด / ไซด์เวย์ไร้ทรง):</b>\n{avoid_str}\n"
        f"────────────────────────────\n"
        f"{ai_insight}"
    )
    send_telegram(msg)
    print("✅ สแกน 1H เรียบร้อย")

if __name__ == "__main__":
    main()
