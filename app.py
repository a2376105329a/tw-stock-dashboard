import streamlit as st
import pandas as pd
import yfinance as yf
import requests, io, json, os
from datetime import datetime, timedelta
import google.generativeai as genai

st.set_page_config(page_title="台股低基期起漲量化戰情室", layout="wide")

# --- 🔒 密碼防護解鎖機制 ---
def check_password():
    def password_entered():
        correct_pwd = st.secrets.get("PASSWORD", "1234")
        current_pwd = st.session_state.get("password", "")
        if current_pwd == correct_pwd:
            st.session_state["password_correct"] = True
            if "password" in st.session_state:
                del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.markdown("### 🔒 【台股量化戰情室】請輸入存取密碼")
        st.text_input("密碼", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.markdown("### 🔒 【台股量化戰情室】請輸入存取密碼")
        st.text_input("密碼", type="password", on_change=password_entered, key="password")
        st.error("😕 密碼錯誤，請重新輸入")
        return False
    else:
        return True

if not check_password():
    st.stop()

st.title("🎯 台股量化作戰室：三柱共振 ＆ AI 決策系統")

# 產業分類與本益比基準
INDUSTRY_MAP = {
    "半導體業": "半導體 / 先進製程 / 封測",
    "電腦及週邊設備業": "電腦硬體 / AI伺服器代工",
    "電子零組件業": "電子零組件 / PCB / 散熱",
    "通信網路業": "網通設備 / CPO光通訊",
    "電機機械": "重電設備 / 綠能電網",
    "電機機械業": "重電設備 / 綠能電網"
}

INDUSTRY_PE_BENCHMARK = {
    "半導體 / 先進製程 / 封測": {"low": 15, "mid": 20, "high": 25},
    "電腦硬體 / AI伺服器代工": {"low": 12, "mid": 16, "high": 22},
    "電子零組件 / PCB / 散熱": {"low": 14, "mid": 18, "high": 25},
    "網通設備 / CPO光通訊": {"low": 16, "mid": 22, "high": 30},
    "重電設備 / 綠能電網": {"low": 15, "mid": 20, "high": 28},
    "其他板塊": {"low": 12, "mid": 15, "high": 20}
}

@st.cache_data(ttl=86400)
def get_tw_stock_meta():
    headers = {'User-Agent': 'Mozilla/5.0'}
    name_map, industry_map = {}, {}
    urls = [
        "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
        "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    ]
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            df = pd.read_html(io.StringIO(resp.text))[0]
            df.columns = df.iloc[0]
            df = df.iloc[1:]
            for _, row in df.iterrows():
                raw = str(row['有價證券代號及名稱']).split()
                if len(raw) >= 2 and len(raw[0]) == 4:
                    ticker = f"{raw[0]}{'.TW' if 'strMode=2' in url else '.TWO'}"
                    name_map[raw[0]] = raw[1]
                    name_map[ticker] = raw[1]
                    raw_ind = str(row.get('產業別', '其他')).strip()
                    ind = INDUSTRY_MAP.get(raw_ind, "其他板塊")
                    industry_map[raw[0]] = ind
                    industry_map[ticker] = ind
        except:
            pass
    return name_map, industry_map

name_map, industry_map = get_tw_stock_meta()

@st.cache_data(ttl=3600)
def get_active_market_stocks():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            df = pd.DataFrame(res.json())
            df = df.rename(columns={'Code': 'id', 'Name': 'name', 'ClosingPrice': 'close', 'TradeVolume': 'volume'})
            df = df[df['id'].str.len() == 4]
            df['close'] = pd.to_numeric(df['close'].str.replace(',', ''), errors='coerce')
            df['volume'] = pd.to_numeric(df['volume'].str.replace(',', ''), errors='coerce') / 1000
            df = df.dropna(subset=['close', 'volume'])
            return df
    except:
        pass
    return pd.DataFrame([{"id": "2303", "name": "聯電", "volume": 50000, "close": 50}])

@st.cache_data(ttl=86400)
def get_fundamental_info(symbol):
    for suffix in [".TW", ".TWO"]:
        try:
            ticker = yf.Ticker(f"{symbol}{suffix}")
            info = ticker.info
            if info and ('symbol' in info or 'shortName' in info):
                return info
        except:
            pass
    return {}

def get_stock_history(symbol):
    for suffix in [".TW", ".TWO"]:
        ticker = yf.Ticker(f"{symbol}{suffix}")
        hist = ticker.history(period="6mo")
        if not hist.empty:
            if isinstance(hist.columns, pd.MultiIndex): 
                hist.columns = hist.columns.get_level_values(0)
            return hist
    return pd.DataFrame()

# 【技術指標運算核心 (含 KD、RSI、布林通道)】
def calculate_indicators(df):
    close = df['Close'].astype(float)
    df['MA5'] = close.rolling(5).mean()
    df['MA10'] = close.rolling(10).mean()
    df['MA20'] = close.rolling(20).mean()
    df['MA60'] = close.rolling(60).mean()
    
    # 布林通道
    df['STD20'] = close.rolling(20).std()
    df['BB_UP'] = df['MA20'] + 2 * df['STD20']
    df['BB_LOW'] = df['MA20'] - 2 * df['STD20']
    df['BB_WIDTH'] = (df['BB_UP'] - df['BB_LOW']) / df['MA20']
    
    # KD 指標 (9天)
    l9 = df['Low'].rolling(window=9).min()
    h9 = df['High'].rolling(window=9).max()
    rsv = ((close - l9) / (h9 - l9) * 100).fillna(50)
    df['K'] = rsv.ewm(alpha=1/3, adjust=False).mean()
    df['D'] = df['K'].ewm(alpha=1/3, adjust=False).mean()
    
    # RSI 指標 (14天)
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=13, adjust=False).mean()
    ema_down = down.ewm(com=13, adjust=False).mean()
    rs = ema_up / ema_down
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

# 【型態辨識引擎 (升級版)】
def detect_bottom_patterns(df):
    if len(df) < 60: return ""
    close = df['Close']
    open_p = df['Open']
    high = df['High']
    low = df['Low']
    vol = df['Volume']
    curr_price = close.iloc[-1]
    
    # 1. 均線糾結突破
    ma_prev = [df['MA5'].iloc[-2], df['MA10'].iloc[-2], df['MA20'].iloc[-2], df['MA60'].iloc[-2]]
    if (max(ma_prev) - min(ma_prev)) / min(ma_prev) <= 0.04 and curr_price > max(ma_prev):
        return "【均線極致糾結 ＋ 帶量突破】"
        
    # 2. VCP 價格波動收縮
    range_old = high.iloc[-40:-20].max() - low.iloc[-40:-20].min()
    range_recent = high.iloc[-20:-2].max() - low.iloc[-20:-2].min()
    vol_recent_mean = vol.iloc[-20:-2].mean()
    if range_recent < range_old * 0.6 and curr_price > high.iloc[-20:-2].max() and vol.iloc[-1] > vol_recent_mean * 1.5:
        return "【VCP 波動收縮 (彈簧發動)】"
        
    # 3. 頭肩大底
    left_shoulder = low.iloc[-60:-40].min()
    head = low.iloc[-40:-20].min()
    right_shoulder = low.iloc[-20:-5].min()
    if head < left_shoulder and head < right_shoulder and abs(left_shoulder - right_shoulder) / right_shoulder < 0.1:
        neckline = high.iloc[-40:-5].max()
        if curr_price >= neckline * 0.98: 
            return "【頭肩大底 (長線終極反轉)】"

    # 4. W底 (雙重底)
    recent_low = low.iloc[-20:-5].min()
    older_low = low.iloc[-60:-20].min()
    if abs(recent_low - older_low) / older_low < 0.05 and curr_price > high.iloc[-20:-1].max():
        return "【W底 (雙腳打底) 突破頸線】"
        
    # 5. 量先價行 (底部偷偷吸籌)
    if 'MA60' in df.columns:
        bias_60 = abs(curr_price - df['MA60'].iloc[-1]) / df['MA60'].iloc[-1]
        if bias_60 < 0.05:
            red_volume_spikes = sum([1 for i in range(-21, -1) if close.iloc[i] > open_p.iloc[i] and vol.iloc[i] > df['MA20'].iloc[i] * 1.5])
            if red_volume_spikes >= 3:
                return "【量先價行 (底部連續紅K吃貨)】"
                
    # 6. 碗型底
    if low.iloc[-40:-10].mean() < low.iloc[-60:-40].mean() and curr_price > df['MA60'].iloc[-1]:
        return "【碗型大底 (長線洗盤結束)】"
        
    return ""

@st.cache_data(ttl=3600)
def get_real_chip_data(symbol, current_price):
    s_trust, s_big, s_foreign = 4, 4, 2
    desc_trust = "🟡 投信近10日無明顯連續佈局"
    desc_big = "🟡 千張大戶持股比例維持中性"
    desc_foreign = "🟡 外資近期進出交替，無連續方向"
    
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
    
    try:
        url_inst = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={symbol}&start_date={start_date}&end_date={end_date}"
        res_inst = requests.get(url_inst, timeout=5)
        if res_inst.status_code == 200:
            df_inst = pd.DataFrame(res_inst.json().get("data", []))
            if not df_inst.empty:
                df_trust = df_inst[df_inst['name'].str.contains("投信")].tail(10)
                if not df_trust.empty:
                    df_trust['net'] = pd.to_numeric(df_trust['buy'], errors='coerce') - pd.to_numeric(df_trust['sell'], errors='coerce')
                    total_net = df_trust['net'].sum()
                    if total_net > 100:
                        s_trust, desc_trust = 8, f"✅ 投信近10日呈現買超 (淨買超 {int(total_net)} 張)"
                    elif total_net < -100:
                        s_trust, desc_trust = 0, f"🚨 投信近10日倒貨 (淨賣超 {int(abs(total_net))} 張)"

                df_foreign = df_inst[df_inst['name'].str.contains("外資")].tail(5)
                if not df_foreign.empty:
                    df_foreign['net'] = pd.to_numeric(df_foreign['buy'], errors='coerce') - pd.to_numeric(df_foreign['sell'], errors='coerce')
                    buy_days = len(df_foreign[df_foreign['net'] > 0])
                    if buy_days >= 3:
                        s_foreign, desc_foreign = 4, f"✅ 外資近 5 日出現 {buy_days} 日買超"
                    elif buy_days == 0:
                        s_foreign, desc_foreign = 0, "🚨 外資近 5 日連續倒貨"

        url_share = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockShareholding&data_id={symbol}&start_date={start_date}&end_date={end_date}"
        res_share = requests.get(url_share, timeout=5)
        if res_share.status_code == 200:
            df_share = pd.DataFrame(res_share.json().get("data", []))
            col_name = 'HoldingSharesLevel' if 'HoldingSharesLevel' in df_share.columns else ('holding_shares_level' if 'holding_shares_level' in df_share.columns else None)
            if col_name:
                df_big = df_share[df_share[col_name].astype(str) == '15']
                if len(df_big) >= 2:
                    pct_col = 'percent' if 'percent' in df_big.columns else 'Percent'
                    latest_ratio = float(df_big.iloc[-1].get(pct_col, 40))
                    prev_ratio = float(df_big.iloc[-2].get(pct_col, 40))
                    if latest_ratio > prev_ratio:
                        s_big, desc_big = 8, f"✅ 千張大戶最新持股升至 {latest_ratio}% (偷偷吸籌)"
                    elif latest_ratio < prev_ratio:
                        s_big, desc_big = 0, f"🚨 千張大戶最新持股降至 {latest_ratio}% (大戶退場)"
    except:
        pass

    return s_trust + s_big + s_foreign, {"投信防守": (s_trust, 8, desc_trust), "大戶增減": (s_big, 8, desc_big), "外資佈局": (s_foreign, 4, desc_foreign)}

def evaluate_single_stock(info, hist, symbol, s_ind):
    # 【第三柱：技術面 (四等分矩陣，滿分 40分)】
    curr_p = round(hist['Close'].iloc[-1], 2)
    ma60 = round(hist['MA60'].iloc[-1], 2)
    vol_today = hist['Volume'].iloc[-1]
    vol_ma20 = hist['Volume'].rolling(20).mean().iloc[-1]
    
    # 1. 季線防守 (10分)
    bias60 = round(((curr_p - ma60) / ma60) * 100, 2)
    if 0 <= bias60 <= 10.0:
        s_ma60, desc_ma60 = 10, f"✅ 站上季線且乖離僅 {bias60}% (極低風險區)"
    elif bias60 > 10.0:
        s_ma60, desc_ma60 = 5, f"🟡 站上季線但乖離達 {bias60}% (追高風險升)"
    else:
        s_ma60, desc_ma60 = 0, f"❌ 跌破季線 (乖離 {bias60}%)"

    # 2. 布林通道 (10分)
    bb_up = hist['BB_UP'].iloc[-1]
    bb_width = hist['BB_WIDTH'].iloc[-1]
    if bb_width < 0.12 and curr_p >= bb_up * 0.99 and vol_today > vol_ma20 * 1.3:
        s_bb, desc_bb = 10, f"🔥 布林極度壓縮後，今日帶量突破上軌"
    elif curr_p > hist['MA20'].iloc[-1]:
        s_bb, desc_bb = 5, f"🟡 股價於布林中軌之上溫和震盪"
    else:
        s_bb, desc_bb = 0, f"❌ 跌破布林中軌，趨勢轉弱"

    # 3. KD 與 RSI 雙重動能 (10分)
    k_val = round(hist['K'].iloc[-1], 1)
    d_val = round(hist['D'].iloc[-1], 1)
    rsi_val = round(hist['RSI'].iloc[-1], 1)
    
    if k_val > d_val and rsi_val >= 50:
        s_kdrsi, desc_kdrsi = 10, f"✅ KD金叉 (K:{k_val}) 且 RSI 站上多方 ({rsi_val})"
    elif k_val > d_val or rsi_val >= 50:
        s_kdrsi, desc_kdrsi = 5, f"🟡 KD與RSI未完全共振，動能加溫中"
    else:
        s_kdrsi, desc_kdrsi = 0, f"❌ KD死叉且 RSI 弱勢 ({rsi_val})"

    # 4. 底部起漲型態 (10分)
    pattern = detect_bottom_patterns(hist)
    if pattern:
        s_pat, desc_pat = 10, f"🔥 命中底部型態：{pattern}"
    else:
        s_pat, desc_pat = 0, "⚪ 無特殊底部反轉型態"

    tech_total = s_ma60 + s_bb + s_kdrsi + s_pat
    tech_details = {
        "季線防守": (s_ma60, 10, desc_ma60), 
        "布林軌道": (s_bb, 10, desc_bb), 
        "KD與RSI": (s_kdrsi, 10, desc_kdrsi), 
        "底部型態": (s_pat, 10, desc_pat)
    }

    # 【第一柱：基本面 (動態四均分，滿分 40分)】
    valid_max = 0
    s_gm, s_om, s_yoy, s_pe = 0, 0, 0, 0
    
    gm = info.get('grossMargins')
    if gm is None: desc_gm = "⚪ 無毛利率資料"
    else:
        valid_max += 10
        if gm >= 0.30: s_gm, desc_gm = 10, f"✅ 毛利率達 {round(gm*100,1)}% (享有產品定價權)"
        elif gm >= 0.15: s_gm, desc_gm = 5, f"🟡 毛利率 {round(gm*100,1)}% (穩健製造水準)"
        else: s_gm, desc_gm = 0, f"❌ 毛利率偏低 {round(gm*100,1)}%"

    om = info.get('operatingMargins')
    if om is None: desc_om = "⚪ 無營益率資料"
    else:
        valid_max += 10
        if om >= 0.10: s_om, desc_om = 10, f"✅ 營益率達 {round(om*100,1)}% (本業獲利極佳)"
        elif om > 0: s_om, desc_om = 5, f"🟡 營益率 {round(om*100,1)}% (維持本業獲利)"
        else: s_om, desc_om = 0, f"❌ 本業呈現虧損"

    yoy = info.get('earningsQuarterlyGrowth')
    if yoy is None: desc_yoy = "⚪ 無 EPS YoY 資料"
    else:
        valid_max += 10
        if yoy >= 0.20: s_yoy, desc_yoy = 10, f"✅ 近一季 EPS 年增 YoY {round(yoy*100,1)}% (獲利爆發)"
        elif yoy > 0: s_yoy, desc_yoy = 5, f"🟡 近一季 EPS 年增 YoY {round(yoy*100,1)}% (溫和成長)"
        else: s_yoy, desc_yoy = 0, f"❌ 近一季 EPS 呈現衰退"

    pe = info.get('trailingPE')
    pe_bench = INDUSTRY_PE_BENCHMARK.get(s_ind, {"low": 12, "mid": 15, "high": 20})
    if pe is None: desc_pe = "⚪ 無本益比資料"
    else:
        valid_max += 10
        if pe < pe_bench['low']: s_pe, desc_pe = 10, f"✅ 本益比 {round(pe,1)} 倍 (低於產業低標 {pe_bench['low']}X，絕對便宜)"
        elif pe <= pe_bench['high']: s_pe, desc_pe = 5, f"🟡 本益比 {round(pe,1)} 倍 (落在產業合理區間)"
        else: s_pe, desc_pe = 0, f"❌ 本益比 {round(pe,1)} 倍 (大於高標 {pe_bench['high']}X，偏貴)"

    fund_earned = s_gm + s_om + s_yoy + s_pe
    final_fund_score = int((fund_earned / valid_max) * 40) if valid_max > 0 else 0
    fund_details = {"毛利率": (s_gm, 10, desc_gm), "營益率": (s_om, 10, desc_om), "EPS YoY": (s_yoy, 10, desc_yoy), "本益比": (s_pe, 10, desc_pe)}

    # 【第二柱：籌碼面 (滿分 20分)】
    s_chip_total, chip_details = get_real_chip_data(symbol, curr_p)
    
    total_score = final_fund_score + s_chip_total + tech_total
    light = "🟢 超級起漲" if total_score >= 85 else ("🟡 潛力加溫" if total_score >= 65 else "⚪ 區間觀望")
    
    pillars = {
        "Fund": (final_fund_score, fund_details),
        "Chip": (s_chip_total, chip_details),
        "Tech": (tech_total, tech_details)
    }
    
    # 算好給 AI 停損利計畫的關鍵點位與指標
    key_prices = {
        "pressure": round(hist['High'].iloc[-60:].max(), 2),
        "support": round(hist['Low'].iloc[-30:].min(), 2),
        "ma60": ma60,
        "k_val": k_val,
        "d_val": d_val,
        "rsi_val": rsi_val
    }
    
    return total_score, light, pillars, key_prices, curr_p

# ==================== UI 介面開始 ====================
tab1, tab3 = st.tabs(["🚀 起漲掃描", "🔍 個股診斷 ＆ 戰情室大腦"])

with tab1:
    st.info("起漲掃描模組準備就緒。在未來的擴充中可以在此加入批次掃描邏輯！")

# ==================== 分頁三：個股深度診斷 ====================
with tab3:
    st.subheader("🔍 個股深度診斷 ＆ 三相評分儀表板")
    target_stock = st.text_input("請輸入台股代號（例：3617, 2303, 6278）：", value="2303")

    if target_stock:
        info = get_fundamental_info(target_stock)
        hist = get_stock_history(target_stock)
        
        if not hist.empty and len(hist) >= 60:
            hist = calculate_indicators(hist)
            s_name, s_ind = name_map.get(target_stock, ""), industry_map.get(target_stock, "其他板塊")
            display_title = f"{target_stock} {s_name}"
            
            score, light, pillars, key_prices, curr_p = evaluate_single_stock(info, hist, target_stock, s_ind)
            
            st.markdown(f"## {display_title} ｜ 綜合總分：{score} 分 ({light})")
            st.info(f"🏢 產業板塊：{s_ind} ｜ 現價：${curr_p}")
            
            col1, col2, col3 = st.columns(3)
            
            # --- 🏛️ 第一柱：基本面 ---
            with col1:
                f_score, f_details = pillars["Fund"]
                st.markdown(f"### 🏛️ 基本防雷 ({f_score}/40)")
                for k, (s, m, desc) in f_details.items(): st.write(f"- {desc}")
                
                if "GEMINI_API_KEY" in st.secrets:
                    if st.button("🤖 預估 2027 年 EPS", key="ai_eps"):
                        with st.spinner("解析法說會展望..."):
                            try:
                                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                                prompt = f"現在時間是2026年10月，請以資深分析師角度，預估台股 {display_title} ({s_ind}) 2027年全年的 EPS 展望與營運動能，字數100字內。"
                                try:
                                    res = genai.GenerativeModel("gemini-1.5-flash").generate_content(prompt)
                                except:
                                    res = genai.GenerativeModel("gemini-1.5-flash-8b").generate_content(prompt)
                                st.success(res.text)
                            except Exception as e:
                                st.error("⚠️ 伺服器忙線中或限流，請稍後再試！")

            # --- ⛽ 第二柱：籌碼面 ---
            with col2:
                c_score, c_details = pillars["Chip"]
                st.markdown(f"### ⛽ 主力燃料 ({c_score}/20)")
                for k, (s, m, desc) in c_details.items(): st.write(f"- {desc}")

            # --- 🔫 第三柱：技術面 ---
            with col3:
                t_score, t_details = pillars["Tech"]
                st.markdown(f"### 🔫 買點扳機 ({t_score}/40)")
                for k, (s, m, desc) in t_details.items(): st.write(f"- {desc}")
                
                st.markdown(f"**🎯 運算關鍵價**：前高壓力 ${key_prices['pressure']} ｜ 季線防禦 ${key_prices['ma60']}")
                
                if "GEMINI_API_KEY" in st.secrets:
                    if st.button("🤖 制定停損利計畫", key="ai_tech"):
                        with st.spinner("計算風報比中..."):
                            try:
                                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                                prompt = f"目標股票【{display_title}】，現價 {curr_p}。季線 {key_prices['ma60']}，近期高點壓力 {key_prices['pressure']}，近期低點支撐 {key_prices['support']}，目前KD值(K:{key_prices['k_val']}, D:{key_prices['d_val']})，RSI為{key_prices['rsi_val']}。請根據以上技術數據，提供明確的進場區間、停損價、停利價。100字內，語氣果斷。"
                                try:
                                    res = genai.GenerativeModel("gemini-1.5-flash").generate_content(prompt)
                                except:
                                    res = genai.GenerativeModel("gemini-1.5-flash-8b").generate_content(prompt)
                                st.warning(res.text)
                            except Exception as e:
                                st.error("⚠️ 伺服器忙線中或限流，請稍後再試！")

            st.markdown("---")
            
            # --- 👑 終極大腦：公司業務與綜合解析 ---
            if "GEMINI_API_KEY" in st.secrets:
                st.markdown("### 👑 戰情室終極大腦")
                if st.button("🚀 生成【公司業務 / 同業競品 / 實戰綜合總結】", use_container_width=True):
                    with st.spinner("正在整合基本面、籌碼面、技術面數據，撰寫終極戰情報告..."):
                        try:
                            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                            master_prompt = f"""
                            現在時間是2026年10月。你是一位頂尖的台股操盤手兼產業分析師。請針對【{display_title}】產出一份「終極戰情報告」。
                            
                            【系統偵測數據】
                            - 綜合總分：{score} / 100 ({light})
                            - 產業板塊：{s_ind}
                            - 基本得分：{f_score}/40 (重點：{f_details['毛利率'][2]} / {f_details['EPS YoY'][2]})
                            - 籌碼得分：{c_score}/20 (重點：{c_details['投信防守'][2]} / {c_details['大戶增減'][2]})
                            - 技術得分：{t_score}/40 (重點：{t_details['季線防守'][2]} / {t_details['KD與RSI'][2]} / {t_details['底部型態'][2]})
                            
                            請提供以下三個段落的精要分析（使用 Markdown 排版，語氣專業果斷）：
                            1. 👑 **【公司業務與核心題材】**：這家公司主要做什麼？有什麼潛在利多題材或供應鏈地位？
                            2. 🏢 **【同業競品與關聯股】**：列出 3-5 檔同產業或具備相同題材的關聯股票，供替換觀察。
                            3. 🎯 **【戰情室綜合診斷】**：請根據上述硬數據與分數，告訴我這檔股票目前的「真實位階」，以及最終的操作定調（例如：適合波段重倉、適合零股試單、或是有跌破風險建議放棄）。
                            """
                            try:
                                final_res = genai.GenerativeModel("gemini-1.5-flash").generate_content(master_prompt)
                            except:
                                final_res = genai.GenerativeModel("gemini-1.5-flash-8b").generate_content(master_prompt)
                            st.info(final_res.text)
                        except Exception as e:
                            st.error("⚠️ 伺服器忙線中或限流，請稍後再試！")
