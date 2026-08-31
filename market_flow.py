import os
import sys
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

# --- Token & API Key ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==========================================
# 📋 33+1 ASSETS STRUCTURE
# ==========================================
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

# ==========================================
# 🌐 CORE ROUTER FETCHER (Binance -> Gateio -> Kucoin)
# ==========================================
def get_binance_candles(symbol, timeframe="1h", limit=250):
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

def get_gateio_candles(symbol, timeframe="1h", limit=250):
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

def get_kucoin_candles(symbol, timeframe="1h", limit=250):
    base_sym = symbol[:-4] if symbol.endswith("USDT") else symbol
    tf_map = {"5m": "5min", "15m": "15min", "1h": "1hour", "4h": "4hour"}
    url = f"https://api.kucoin.com/api/v1/market/candles?type={tf_map.get(timeframe, timeframe)}&symbol={base_sym}-USDT"
    try:
        res = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4).json()
        if res.get("code") == "200000" and "data" in res and len(res["data"]) >= limit // 2:
            records = [{"open": float(i[1]), "close": float(i[2]), "high": float(i[3]), "low": float(i[4]), "volume": float(i[5])} for i in res["data"]]
            return pd.DataFrame(records)[::-1].reset_index(drop=True).dropna()
    except: pass
    return None

def fetch_candles(symbol, timeframe="1h", limit=250):
    df = get_binance_candles(symbol, timeframe, limit)
    if df is not None: return df
    df = get_gateio_candles(symbol, timeframe, limit)
    if df is not None: return df
    return get_kucoin_candles(symbol, timeframe, limit)

# ==========================================
# 📊 1H STRUCTURAL ANALYSIS (FACT-BASED A.AUN LOGIC)
# ==========================================
def analyze_1h_structure(symbol):
    df = fetch_candles(symbol, "1h", 250)
    if df is None or len(df) < 200: 
        return symbol, 0.0, 0.0, 1.0, "NONE", "", {}

    try:
        c_closed = df["close"].iloc[-2]
        o_closed = df["open"].iloc[-2]
        h_closed = df["high"].iloc[-2]
        l_closed = df["low"].iloc[-2]
        
        # คำนวณ 1H Change
        prev_close = df["close"].iloc[-3]
        pct_change_1h = ((c_closed - prev_close) / prev_close) * 100
        
        # คำนวณ 24H Change (ย้อนหลัง 24 แท่งเทียน)
        close_24h_ago = df["close"].iloc[-26] if len(df) >= 26 else df["close"].iloc[0]
        pct_change_24h = ((c_closed - close_24h_ago) / close_24h_ago) * 100
        
        # คำนวณ Volume Surge
        vol_current = df["volume"].iloc[-2]
        vol_avg = df["volume"].iloc[-26:-2].mean()
        vol_surge = (vol_current / vol_avg) if vol_avg > 0 else 1.0

        # EMA & MACD Indicators
        ema21_series = df["close"].ewm(span=21, adjust=False).mean()
        ema35_series = df["close"].ewm(span=35, adjust=False).mean()
        ema89_series = df["close"].ewm(span=89, adjust=False).mean()
        ema200_series = df["close"].ewm(span=200, adjust=False).mean()
        
        ema21, ema35 = ema21_series.iloc[-2], ema35_series.iloc[-2]
        ema89, ema200 = ema89_series.iloc[-2], ema200_series.iloc[-2]
        ema21_prev, ema35_prev = ema21_series.iloc[-3], ema35_series.iloc[-3]

        macd_line = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
        macd_sig = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_sig
        macd_current = macd_line.iloc[-2]

        # ระยะความตึงและ Anti-Saw
        dist_89_pct = (abs(c_closed - ema89) / ema89) * 100
        dist_21_35_pct = (abs(ema21 - ema35) / ema35) * 100
        
        cross_up = (ema21_prev <= ema35_prev) and (ema21 > ema35)
        cross_dn = (ema21_prev >= ema35_prev) and (ema21 < ema35)
        
        # โครงสร้างแท่งเทียน
        body = abs(o_closed - c_closed)
        lower_wick = min(o_closed, c_closed) - l_closed
        upper_wick = h_closed - max(o_closed, c_closed)
        is_bull_pinbar = (lower_wick > (1.5 * body)) and (lower_wick > upper_wick)
        is_bear_pinbar = (upper_wick > (1.5 * body)) and (upper_wick > lower_wick)

        bucket, fact_str = "NONE", ""

        # กฎข้อ 1: กรอง Overextended และ Choppy Market (Avoid List)
        if dist_89_pct > 3.0:
            bucket = "AVOID"
            fact_str = f"ราคาลอยห่าง EMA89 ถึง {dist_89_pct:.2f}% (Overextended) ห้ามไล่ราคา"
        elif dist_21_35_pct <= 0.05 and not (cross_up or cross_dn):
            bucket = "AVOID"
            fact_str = "เส้น EMA21/35 บีบตัวแคบ (Choppy Squeeze) เสี่ยงสับขาหลอก"
        
        # กฎข้อ 2: คัดกรองตามระบบเทรด (หากผ่านตัวกรอง Choppy)
        if bucket == "NONE":
            # 🟢 [BULLISH REGIME]
            if ema21 > ema35 and ema35 > ema89:
                if dist_89_pct <= 0.50 and macd_current > 0:
                    bucket = "PLAN_A_BUY"
                    fact_str = "ย่อลงฐาน EMA89 ไม่หลุด + โมเมนตัมคลายตัว (พร้อมเข้า)"
                elif cross_up or dist_21_35_pct <= 0.10:
                    bucket = "PLAN_B_BUY"
                    fact_str = "EMA 21 จ่อตัด 35 ขึ้น (Momentum Cross) เหนือฐาน EMA89"
            
            # 🔴 [BEARISH REGIME]
            elif ema21 < ema35 and ema35 < ema89:
                if dist_89_pct <= 0.50 and macd_current < 0:
                    bucket = "PLAN_A_SELL"
                    fact_str = "เด้งชน EMA89 ใต้แนวต้าน ทิ้งไส้บน (พร้อมเข้า)"
                elif cross_dn or dist_21_35_pct <= 0.10:
                    bucket = "PLAN_B_SELL"
                    fact_str = "EMA 21 จ่อตัด 35 ลง (Momentum Cross) ใต้ฐาน EMA89"
        
        # กฎข้อ 3: ตรวจจับ Divergence (Reversal Watch)
        if bucket == "NONE":
            if l_closed < df["low"].iloc[-10:-2].min() and macd_hist.iloc[-2] > macd_hist.iloc[-10:-2].min():
                bucket, fact_str = "REVERSAL", "Bullish Divergence 1H กราฟทำ Low ใหม่แต่ MACD ยกฐาน"
            elif h_closed > df["high"].iloc[-10:-2].max() and macd_hist.iloc[-2] < macd_hist.iloc[-10:-2].max():
                bucket, fact_str = "REVERSAL", "Bearish Divergence 1H กราฟทำ High ใหม่แต่ MACD กดต่ำ"

        return symbol, pct_change_1h, pct_change_24h, vol_surge, bucket, fact_str, {"price": c_closed}
    except Exception:
        return symbol, 0.0, 0.0, 1.0, "NONE", "", {}

def send_telegram_msg(message, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        res = http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": parse_mode, "disable_web_page_preview": True}, timeout=8)
        if res.status_code != 200:
            plain = message.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", "")
            http.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain}, timeout=8)
    except Exception as e:
        print(f"Telegram Exception: {e}")

# ==========================================
# 🚀 MAIN PIPELINE
# ==========================================
def main():
    print("🚀 สแกนข้อมูล 1H Structural Radar (33+1 Assets)...")
    
    results = {}
    crypto_data = []
    
    plan_a_str_list, plan_b_str_list, rev_str_list, avoid_str_list = [], [], [], []

    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, pct_1h, pct_24h, vol, bucket, fact_str, data in executor.map(analyze_1h_structure, WATCHLIST):
            results[sym] = {"pct_1h": pct_1h, "pct_24h": pct_24h, "vol": vol}
            
            if bucket != "NONE":
                tier = TIER_MAP.get(sym, 'Other')
                price = format_price(data.get('price', 0))
                
                # ฟอร์แมต Bullet ย่อย
                if "BUY" in bucket or bucket == "REVERSAL": 
                    icon = "🟢"
                elif "SELL" in bucket or bucket == "AVOID":
                    icon = "🔴"
                else:
                    icon = "•"

                item_str = f"{icon} <b>{sym}</b> <code>[{tier}]</code> | <code>{price}</code> ➔ {fact_str}"
                
                if bucket in ["PLAN_A_BUY", "PLAN_A_SELL"]: plan_a_str_list.append(item_str)
                elif bucket in ["PLAN_B_BUY", "PLAN_B_SELL"]: plan_b_str_list.append(item_str)
                elif bucket == "REVERSAL": rev_str_list.append(item_str)
                elif bucket == "AVOID": avoid_str_list.append(item_str)

    # ดึงค่าจัดอันดับ Volume / Gainers / Losers
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
คุณคือนักวิเคราะห์ข่าวเศรษฐกิจและการลงทุนสาย Quant (Broadcaster) หน้าที่ของคุณคือเล่าสถานการณ์ตลาด 1H ที่เพิ่งจบไป และชี้เป้าแผนการเทรดข้างหน้าแบบตรงไปตรงมา ห้ามใช้คำเกริ่นนำหรือลงท้าย ห้ามเขียนทฤษฎียืดเยื้อ ใช้รูปแบบ Bullet Points ตามฟอร์แมตเป๊ะๆ

[ข้อมูลสรุป 1H Data]
Macro 24H: BTC {btc_perf_24h:+.2f}% | Gold {gold_perf_24h:+.2f}%
Top Gainers (1H): {', '.join(top_gainers)} | Top Losers (1H): {', '.join(top_losers)}
Volume Spike (1H): {', '.join(top_vol) if top_vol else 'ไม่มี'}
แผนหน้างาน: เตรียมเข้า Plan A ({len(plan_a_str_list)} ตัว), รอทะลุ Plan B ({len(plan_b_str_list)} ตัว)

[รูปแบบการตอบ (ห้ามเปลี่ยน Layout)]
🛑 <b>พาดหัวหลัก:</b> [สรุปภาพรวม 1 ประโยค เช่น ตลาดเอเชียเปิดแรง เม็ดเงินไหลออกจากทองคำเข้าเสี่ยงใน Crypto เต็มตัว]

• <b>สรุปเหตุการณ์ 1H ที่ผ่านมา:</b> [อธิบายเม็ดเงินไหลเข้า/ออก ระหว่าง BTC และกลุ่ม Altcoins (Gainers/Losers) เทียบกับ Gold]
• <b>สัญญาณ Volume ผิดปกติ:</b> [รายงานเหรียญใน Volume Spike พร้อมประเมินสั้นๆ ว่าโดนเทขายหรือโดนดันราคา]
• <b>จุดรอเก็บเต็มคำ & แผนข้างหน้า:</b> [ชี้เป้าเหรียญในกลุ่ม Plan A ว่าตัวไหนน่าโฟกัสเข้าเทรด หรือถ้า Plan B เยอะให้บอกว่ารอจุดตัดจบรอบ]
• <b>ข้อควรระวังเร่งด่วน:</b> [เตือนให้เลี่ยงเหรียญ Avoid หรือระวังความเสี่ยงจากความผันผวนของ BTC]
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

    # จัดหน้า UI
    str_plan_a = "\n".join(plan_a_str_list) if plan_a_str_list else "• (ยังไม่มีเหรียญเข้าเกณฑ์)"
    str_plan_b = "\n".join(plan_b_str_list) if plan_b_str_list else "• (ยังไม่มีเหรียญเข้าเกณฑ์)"
    str_rev = "\n".join(rev_str_list) if rev_str_list else "• (ยังไม่มีสัญญาณกลับตัว)"
    str_avoid = "\n".join(avoid_str_list) if avoid_str_list else "• (ยังไม่มีเหรียญที่เสี่ยงชัดเจน)"

    msg = (
        f"🧭 <b>[MARKET FLOW & MACRO RADAR]</b>\n"
        f"────────────────────────────\n"
        f"👑 <b>BTC (24H):</b> <code>{btc_perf_24h:+.2f}%</code> | 🥇 <b>Gold (24H):</b> <code>{gold_perf_24h:+.2f}%</code>\n\n"
        f"⚡️ <b>Outliers & Volume Spike (1H):</b>\n"
        f"🚀 <b>บวกแรง:</b> <code>{', '.join(top_gainers) if top_gainers else '-'}</code>\n"
        f"🩸 <b>ลบหนัก:</b> <code>{', '.join(top_losers) if top_losers else '-'}</code>\n"
        f"⚠️ <b>วอลุ่มพุ่ง:</b> <code>{', '.join(top_vol) if top_vol else 'ปกติ'}</code>\n"
        f"────────────────────────────\n"
        f"🎯 <b>[1H STRUCTURAL RADAR: ชี้เป้าโฟกัส]</b>\n"
        f"*(คัดกรองด้วย Anti-Saw & EMA Guard)*\n\n"
        f"⚡️ <b>PLAN A [ZERO-STATION: ดักย่อ/เด้ง ชิดฐาน EMA89]:</b>\n{str_plan_a}\n\n"
        f"🚀 <b>PLAN B [MOMENTUM TRIGGER: จ่อตัด/พุ่งทะลุ EMA 21x35]:</b>\n{str_plan_b}\n\n"
        f"🔄 <b>REVERSAL / DIVERGENCE:</b>\n{str_rev}\n\n"
        f"⛔️ <b>AVOID LIST (ตึงจัด / ฟันปลา):</b>\n{str_avoid}\n"
        f"────────────────────────────\n"
        f"🎙️ <b>AI TACTICAL DIRECTIVE (Economic Briefing):</b>\n"
        f"{ai_insight}"
    )
    
    send_telegram_msg(msg)
    print("✅ สแกน 33+1 สินทรัพย์ และส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
