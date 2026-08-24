import os
import sys
import requests
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor
from google import genai

# --- ดึง Token จาก GitHub Secrets ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# จัดกลุ่มสินทรัพย์เพื่อดู Capital Rotation (ใช้เหรียญ Spot)
SECTORS = {
    "Macro & King": ["BTCUSDT", "PAXGUSDT"],
    "Tier 1 Bluechip": ["ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
    "AI & Big Data": ["ARKMUSDT", "FETUSDT", "NEARUSDT", "RENDERUSDT", "TAOUSDT", "WLDUSDT"],
    "DeFi & RWA": ["AAVEUSDT", "DYDXUSDT", "ENAUSDT", "JUPUSDT", "LINKUSDT", "ONDOUSDT", "PENDLEUSDT"],
    "Layer 1 & 0": ["ADAUSDT", "APTUSDT", "ATOMUSDT", "AVAXUSDT", "DOTUSDT", "GRTUSDT", "ICPUSDT", "INJUSDT", "KASUSDT", "PYTHUSDT", "SEIUSDT", "SUIUSDT"],
    "Layer 2": ["ARBUSDT", "MANTAUSDT", "POLUSDT", "OPUSDT", "STRKUSDT", "TIAUSDT", "ZKUSDT"],
    "Memes & Beta": ["DOGEUSDT", "GALAUSDT", "PEPEUSDT", "RUNEUSDT", "SANDUSDT", "SHIBUSDT"]
}

def get_binance_spot_candles(symbol, interval="4h", limit=10):
    """ดึงข้อมูล Spot ตรงจาก Binance Vision (เสถียร 100% ไม่โดนบล็อก IP)"""
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = requests.get(url, timeout=10).json()
            if isinstance(res, list) and len(res) >= 2:
                df = pd.DataFrame(res, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades", "taker_buy_base",
                    "taker_buy_quote", "ignore"
                ])
                for col in ["open", "high", "low", "close", "open_time"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df.sort_values(by="open_time").dropna().reset_index(drop=True)
        except Exception:
            continue
    return None

def get_4h_performance(symbol):
    """คำนวณ % เปลี่ยนแปลงของแท่ง 4H ปิดสมบูรณ์ล่าสุด"""
    df = get_binance_spot_candles(symbol, interval="4h", limit=5)
    if df is None or len(df) < 2: return symbol, 0.0
    
    close_val = df["close"].iloc[-2]  # แท่ง 4H ที่ปิดแล้วล่าสุด
    prev_close = df["close"].iloc[-3] # แท่งก่อนหน้า
    
    pct_change = ((close_val - prev_close) / prev_close) * 100
    return symbol, pct_change

def send_telegram(message):
    """ส่งข้อความเข้า Telegram พร้อมระบบ Fallback Plain Text"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            # Fallback หากมีปัญหา HTML tags
            plain_text = message.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": plain_text}, timeout=10)
        print("Telegram message sent successfully.")
    except Exception as e:
        print(f"Telegram Exception: {e}")

def main():
    print("Fetching Market Performance Data...")
    
    # 1. ดึงข้อมูลทุกเหรียญพร้อมกัน (Threading ช่วยให้เสร็จภายใน 2-3 วินาที)
    all_symbols = [coin for group in SECTORS.values() for coin in group]
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for sym, pct in executor.map(get_4h_performance, all_symbols):
            results[sym] = pct
            
    # 2. คำนวณค่าเฉลี่ยของแต่ละ Sector
    sector_perf = {}
    for sector, coins in SECTORS.items():
        valid_coins = [results[c] for c in coins if c in results]
        avg_pct = sum(valid_coins) / len(valid_coins) if valid_coins else 0.0
        sector_perf[sector] = avg_pct
        
    btc_perf = results.get("BTCUSDT", 0.0)
    gold_perf = results.get("PAXGUSDT", 0.0) # ใช้ PaxG เป็น Proxy ทองคำบน Spot
    
    # 3. เตรียมข้อมูลส่งให้ AI วิเคราะห์
    prompt_data = (
        f"ข้อมูลผลตอบแทนในกรอบ 4 ชั่วโมงล่าสุด (4H % Change):\n"
        f"- BTC: {btc_perf:.2f}%\n"
        f"- ทองคำ (PAXG): {gold_perf:.2f}%\n\n"
        f"ค่าเฉลี่ยผลตอบแทนรายกลุ่ม (Sector Average % Change):\n"
    )
    for s, p in sector_perf.items():
        if "Macro" not in s:
            prompt_data += f"- {s}: {p:.2f}%\n"

    system_prompt = f"""
คุณคือนักวิเคราะห์ Quant เชิงมหภาค (Macro Quant Analyst)
จงวิเคราะห์ทิศทางกระแสเงินทุน (Capital Rotation) จากข้อมูล % Change 4H นี้
เขียนรายงานภาษาไทยสั้นๆ กระชับ ไม่เกิน 5 บรรทัด โดยสรุป 3 ประเด็นหลัก (ใช้ Emojis ตกแต่ง):
1. ทิศทางมหภาค: เงินไหลเข้า Risk-On (BTC) หรือ Risk-Off (ทองคำ)?
2. สภาวะเงินหมุนเวียน (Rotation): เทียบ BTC กับกลุ่ม Altcoins เงินกำลังเทไปฝั่งไหน? ใครคือ Sector ผู้นำ?
3. กลยุทธ์พอร์ต (Action): ตลาดแบบนี้ควรเทรดฝั่งไหน กลุ่มไหน หรือควรชะลอการเทรด?

ห้ามเขียนเกริ่นนำ ให้ตอบผลการวิเคราะห์ทันที
ข้อมูล:
{prompt_data}
"""

    ai_insight = "ไม่สามารถเชื่อมต่อ AI ได้ในขณะนี้ กรุณาประเมินจากตัวเลขด้านบน"
    if GEMINI_API_KEY:
        try:
            print("Sending to Gemini API...")
            client = genai.Client(api_key=GEMINI_API_KEY.strip())
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=system_prompt,
            )
            ai_insight = response.text.strip()
        except Exception as e:
            print(f"Gemini API Error: {e}")

    # 4. ประกอบร่างข้อความรายงาน
    msg = (
        f"🧭 <b>[MARKET FLOW & AI REGIME 4H]</b>\n"
        f"────────────────────────\n"
        f"<b>📊 Sector Performance (4H):</b>\n"
        f"👑 BTC: <code>{btc_perf:+.2f}%</code> | 🥇 Gold: <code>{gold_perf:+.2f}%</code>\n"
        f"💎 Tier 1: <code>{sector_perf['Tier 1 Bluechip']:+.2f}%</code>\n"
        f"🧠 AI: <code>{sector_perf['AI & Big Data']:+.2f}%</code>\n"
        f"🏗 L1/L0: <code>{sector_perf['Layer 1 & 0']:+.2f}%</code> | L2: <code>{sector_perf['Layer 2']:+.2f}%</code>\n"
        f"🏦 DeFi: <code>{sector_perf['DeFi & RWA']:+.2f}%</code>\n"
        f"🚀 Memes: <code>{sector_perf['Memes & Beta']:+.2f}%</code>\n"
        f"────────────────────────\n"
        f"<b>🤖 AI Executive Summary:</b>\n"
        f"{ai_insight}"
    )
    
    send_telegram(msg)

if __name__ == "__main__":
    main()
