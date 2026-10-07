import streamlit as st
import pandas as pd
import yfinance as yf
import requests, io, json, os
import concurrent.futures
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

# --- ⚙ 系統設定與常數 ---
INDUSTRY_PE_BENCHMARK = {
    "半導體 / 先進製程 / 封測": {"low": 15, "mid": 20, "high": 25},
    "電腦硬體 / AI伺服器代工": {"low": 12, "mid": 16, "high": 22},
    "電子零組件 / PCB / 散熱 / 被動元件": {"low": 14, "mid": 18, "high": 25},
    "網通設備 / CPO光通訊": {"low": 16, "mid": 22, "high": 30},
    "重電設備 / 綠能電網 / 電線電纜": {"low": 15, "mid": 20, "high": 28},
    "電子零組件通路商": {"low": 10, "mid": 12, "high": 15},
    "資訊軟體 / 系統整合": {"low": 18, "mid": 24, "high": 32},
    "化學工業 / 特用化學": {"low": 12, "mid": 15, "high": 20},
    "生技醫療": {"low": 18, "mid": 25, "high": 35},
    "其他板塊": {"low": 12, "mid": 15, "high": 20}
}

# --- 📂 資料獲取模組 (光速防卡死版) ---
@st.cache_data(ttl=86400)
def get_tw_stock_meta():
    name_map, industry_map = {}, {}
    try:
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=5)
        if res_twse.status_code == 200:
            for item in res_twse.json():
                code = item.get("Code", "")
                name = item.get("Name", "")
                if len(code) == 4:
                    name_map[code] = name
                    name_map[f"{code}.TW"] = name
                    
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=5)
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                code = item.get("SecuritiesCompanyCode", "")
                name = item.get("CompanyName", "")
                if len(code) == 4:
                    name_map[code] = name
                    name_map[f"{code}.TWO"] = name
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
            df = pd.DataFrame(res.json()).rename(columns={'Code': 'id', 'Name': 'name', 'ClosingPrice': 'close', 'TradeVolume': 'volume'})
            df = df[df['id'].str.len() == 4]
            df['close'] = pd.to_numeric(df['close'].str.replace(',', ''), errors='coerce')
            df['volume'] = pd.to_numeric(df['volume'].str.replace(',', ''), errors='coerce') / 1000
            return df.dropna(subset=['close', 'volume'])
    except: pass
    return pd.DataFrame([{"id": "2330", "name": "台積電", "volume": 50000, "close": 1000}])

@st.cache_data(ttl=86400)
def get_fundamental_info(symbol):
    for suffix in [".TW", ".TWO"]:
        try:
            info = yf.Ticker(f"{symbol}{suffix}").info
            if info and ('symbol' in info or 'shortName' in info): return info
        except: pass
    return {}

def get_stock_history(symbol):
    for suffix in [".TW", ".TWO"]:
        try:
            hist = yf.download(f"{symbol}{suffix}", period="6mo", progress=False, timeout=3)
            if not hist.empty:
                if isinstance(hist.columns, pd.MultiIndex): hist.columns = hist.columns.get_level_values(0)
                return hist
        except: pass
    return pd.DataFrame()

# --- 📈 技術指標與型態引擎 ---
def calculate_indicators(df):
    close = df['Close'].astype(float)
    df['MA5'] = close.rolling(5).mean()
    df['MA10'] = close.rolling(10).mean()
    df['MA20'] = close.rolling(20).mean()
    df['MA60'] = close.rolling(60).mean()
    
    df['STD20'] = close.rolling(20).std()
    df['BB_UP'] = df['MA20'] + 2 * df['STD20']
    df['BB_LOW'] = df['MA20'] - 2 * df['STD20']
    df['BB_WIDTH'] = (df['BB_UP'] - df['BB_LOW']) / df['MA20']
    
    l9, h9 = df['Low'].rolling(window=9).min(), df['High'].rolling(window=9).max()
    rsv = ((close - l9) / (h9 - l9) * 100).fillna(50)
    df['K'] = rsv.ewm(alpha=1/3, adjust=False).mean()
    df['D'] = df['K'].ewm(alpha=1/3, adjust=False).mean()
    
    delta = close.diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def detect_historical_breakout(df, idx):
    close, high, low, vol = df['Close'], df['High'], df['Low'], df['Volume']
    curr_price = close.iloc[idx]
    
    ma_prev = [df['MA5'].iloc[idx-1], df['MA10'].iloc[idx-1], df['MA20'].iloc[idx-1], df['MA60'].iloc[idx-1]]
    if (max(ma_prev) - min(ma_prev)) / min(ma_prev) <= 0.04 and curr_price > max(ma_prev): return "均線極致糾結突破"
        
    range_old = high.iloc[idx-39:idx-19].max() - low.iloc[idx-39:idx-19].min()
    range_recent = high.iloc[idx-19:idx-1].max() - low.iloc[idx-19:idx-1].min()
    if range_recent < range_old * 0.6 and curr_price > high.iloc[idx-19:idx-1].max(): return "VCP 波動收縮起漲"
        
    box_high = high.iloc[idx-30:idx-1].max()
    box_low = low.iloc[idx-30:idx-1].min()
    if (box_high - box_low) / box_low <= 0.15 and curr_price > box_high: return "箱型整理強勢突破"
        
    if low.iloc[idx-14:idx-1].min() < low.iloc[idx-59:idx-14].min() and curr_price > high.iloc[idx-14:idx-1].max(): return "破底翻大底起漲"
        
    left, head, right = low.iloc[idx-59:idx-39].min(), low.iloc[idx-39:idx-19].min(), low.iloc[idx-19:idx-4].min()
    if head < left and head < right and abs(left - right) / right < 0.1:
        if curr_price >= high.iloc[idx-39:idx-4].max() * 0.98: return "頭肩底突破頸線"
            
    if abs(low.iloc[idx-19:idx-4].min() - low.iloc[idx-59:idx-19].min()) / low.iloc[idx-59:idx-19].min() < 0.05 and curr_price > high.iloc[idx-19:idx-1].max():
        return "W底雙腳支撐突破"
        
    if high.iloc[idx-1] < low.iloc[idx-2] and low.iloc[idx] > high.iloc[idx-1]: return "島型竭盡反轉跳空"
        
    return ""

def detect_bottom_patterns(df): return detect_historical_breakout(df, -1)

@st.cache_data(ttl=3600)
def get_real_chip_data(symbol, current_price):
    s_trust, s_big, s_foreign = 4, 4, 2
    desc_trust, desc_big, desc_foreign = "🟡 投信無連續佈局", "🟡 千張大戶持股中性", "🟡 外資無連續方向"
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
                    if df_trust['net'].sum() > 100: s_trust, desc_trust = 8, f"✅ 投信買超 ({int(df_trust['net'].sum())} 張)"
                    elif df_trust['net'].sum() < -100: s_trust, desc_trust = 0, f"🚨 投信倒貨 ({int(abs(df_trust['net'].sum()))} 張)"

                df_foreign = df_inst[df_inst['name'].str.contains("外資")].tail(5)
                if not df_foreign.empty:
                    df_foreign['net'] = pd.to_numeric(df_foreign['buy'], errors='coerce') - pd.to_numeric(df_foreign['sell'], errors='coerce')
                    buy_days = len(df_foreign[df_foreign['net'] > 0])
                    if buy_days >= 3: s_foreign, desc_foreign = 4, f"✅ 外資近 5 日出現 {buy_days} 日買超"
                    elif buy_days == 0: s_foreign, desc_foreign = 0, "🚨 外資連續倒貨"

        url_share = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockShareholding&data_id={symbol}&start_date={start_date}&end_date={end_date}"
        res_share = requests.get(url_share, timeout=5)
        if res_share.status_code == 200:
            df_share = pd.DataFrame(res_share.json().get("data", []))
            col_name = 'HoldingSharesLevel' if 'HoldingSharesLevel' in df_share.columns else ('holding_shares_level' if 'holding_shares_level' in df_share.columns else None)
            if col_name:
                df_big = df_share[df_share[col_name].astype(str) == '15']
                if len(df_big) >= 2:
                    latest_ratio, prev_ratio = float(df_big.iloc[-1].get('percent', 40)), float(df_big.iloc[-2].get('percent', 40))
                    if latest_ratio > prev_ratio: s_big, desc_big = 8, f"✅ 大戶持股升至 {latest_ratio}% (偷偷吸籌)"
                    elif latest_ratio < prev_ratio: s_big, desc_big = 0, f"🚨 大戶持股降至 {latest_ratio}%"
    except: pass
    return s_trust + s_big + s_foreign, {"投信防守": (s_trust, 8, desc_trust), "大戶增減": (s_big, 8, desc_big), "外資佈局": (s_foreign, 4, desc_foreign)}

def evaluate_single_stock(info, hist, symbol, s_ind):
    curr_p, ma60 = round(hist['Close'].iloc[-1], 2), round(hist['MA60'].iloc[-1], 2)
    vol_today, vol_ma20 = hist['Volume'].iloc[-1], hist['Volume'].rolling(20).mean().iloc[-1]
    
    bias60 = round(((curr_p - ma60) / ma60) * 100, 2)
    if 0 <= bias60 <= 10.0: s_ma60, desc_ma60 = 10, f"✅ 站上季線且乖離僅 {bias60}%"
    elif bias60 > 10.0: s_ma60, desc_ma60 = 5, f"🟡 站上季線但乖離達 {bias60}%"
    else: s_ma60, desc_ma60 = 0, f"❌ 跌破季線 (乖離 {bias60}%)"

    bb_up, bb_width = hist['BB_UP'].iloc[-1], hist['BB_WIDTH'].iloc[-1]
    if bb_width < 0.12 and curr_p >= bb_up * 0.99 and vol_today > vol_ma20 * 1.3: s_bb, desc_bb = 10, f"🔥 布林壓縮突破"
    elif curr_p > hist['MA20'].iloc[-1]: s_bb, desc_bb = 5, f"🟡 中軌之上溫和震盪"
    else: s_bb, desc_bb = 0, f"❌ 跌破中軌"

    k_val, d_val, rsi_val = round(hist['K'].iloc[-1], 1), round(hist['D'].iloc[-1], 1), round(hist['RSI'].iloc[-1], 1)
    if k_val > d_val and rsi_val >= 50: s_kdrsi, desc_kdrsi = 10, f"✅ KD金叉且 RSI多方 ({rsi_val})"
    elif k_val > d_val or rsi_val >= 50: s_kdrsi, desc_kdrsi = 5, f"🟡 KD/RSI動能加溫"
    else: s_kdrsi, desc_kdrsi = 0, f"❌ KD死叉且 RSI弱勢"

    pattern = detect_bottom_patterns(hist)
    s_pat, desc_pat = (10, f"🔥 命中型態：{pattern}") if pattern else (0, "⚪ 無底部型態")
    tech_total, tech_details = s_ma60 + s_bb + s_kdrsi + s_pat, {"季線防守": (s_ma60, 10, desc_ma60), "布林軌道": (s_bb, 10, desc_bb), "KD與RSI": (s_kdrsi, 10, desc_kdrsi), "底部型態": (s_pat, 10, desc_pat)}

    # --- 第一柱：基本面 (數據具體化) ---
    valid_max, s_gm, s_om, s_yoy, s_pe = 0, 0, 0, 0, 0
    gm, om, yoy, pe = info.get('grossMargins'), info.get('operatingMargins'), info.get('earningsQuarterlyGrowth'), info.get('trailingPE')
    pe_bench = INDUSTRY_PE_BENCHMARK.get(s_ind, {"low": 12, "mid": 15, "high": 20})
    
    if gm is not None:
        valid_max += 10
        if gm >= 0.30: s_gm, desc_gm = 10, f"✅ 毛利率達 {round(gm*100,1)}%"
        elif gm >= 0.15: s_gm, desc_gm = 5, f"🟡 毛利率 {round(gm*100,1)}%"
        else: s_gm, desc_gm = 0, f"❌ 毛利率僅 {round(gm*100,1)}% (偏低)"
    else: desc_gm = "⚪ 無資料"
    
    if om is not None:
        valid_max += 10
        if om >= 0.10: s_om, desc_om = 10, f"✅ 營益率達 {round(om*100,1)}%"
        elif om > 0: s_om, desc_om = 5, f"🟡 營益率 {round(om*100,1)}%"
        else: s_om, desc_om = 0, f"❌ 營益率 {round(om*100,1)}% (本業虧損)"
    else: desc_om = "⚪ 無資料"
    
    if yoy is not None:
        valid_max += 10
        if yoy >= 0.20: s_yoy, desc_yoy = 10, f"✅ YoY 爆發 {round(yoy*100,1)}%"
        elif yoy > 0: s_yoy, desc_yoy = 5, f"🟡 YoY 成長 {round(yoy*100,1)}%"
        else: s_yoy, desc_yoy = 0, f"❌ YoY 衰退 {round(yoy*100,1)}%"
    else: desc_yoy = "⚪ 無資料"
    
    if pe is not None:
        valid_max += 10
        if pe < pe_bench['low']: s_pe, desc_pe = 10, f"✅ 本益比 {round(pe,1)}X (低於低標 {pe_bench['low']}X)"
        elif pe <= pe_bench['high']: s_pe, desc_pe = 5, f"🟡 本益比 {round(pe,1)}X (合理區間)"
        else: s_pe, desc_pe = 0, f"❌ 本益比達 {round(pe,1)}X (高於高標 {pe_bench['high']}X，偏貴)"
    else: desc_pe = "⚪ 無資料"

    fund_earned = s_gm + s_om + s_yoy + s_pe
    final_fund_score = int((fund_earned / valid_max) * 40) if valid_max > 0 else 0
    fund_details = {"毛利率": (s_gm, 10, desc_gm), "營益率": (s_om, 10, desc_om), "EPS YoY": (s_yoy, 10, desc_yoy), "本益比": (s_pe, 10, desc_pe)}

    s_chip_total, chip_details = get_real_chip_data(symbol, curr_p)
    total_score = final_fund_score + s_chip_total + tech_total
    light = "🟢 超級起漲" if total_score >= 85 else ("🟡 潛力加溫" if total_score >= 65 else "⚪ 區間觀望")
    
    key_prices = {"pressure": round(hist['High'].iloc[-60:].max(), 2), "support": round(hist['Low'].iloc[-30:].min(), 2), "ma60": ma60, "k_val": k_val, "d_val": d_val, "rsi_val": rsi_val}
    return total_score, light, {"Fund": (final_fund_score, fund_details), "Chip": (s_chip_total, chip_details), "Tech": (tech_total, tech_details)}, key_prices, curr_p

# ==================== UI 介面 ====================
tab1, tab3 = st.tabs(["🛡️ 量縮回測洗盤雷達 (支撐買點)", "🔍 個股深度 AI 診斷"])

# ==================== 分頁一：量縮回測洗盤雷達 ====================
with tab1:
    st.subheader("🛡️ 法人級策略：買在起漲後的量縮洗盤點")
    st.caption("條件：昨日/今日緊貼均線支撐 ＋ 近期量縮降溫 ＋ 過去 3~10 天內曾爆量出現【七大底部起漲型態】。")

    col_btn, col_opt = st.columns([1, 2])
    with col_btn:
        run_scan = st.button("🚀 立即掃描低風險支撐股", use_container_width=True)
    with col_opt:
        min_vol_limit = st.slider("設定今日最低成交量門檻 (張)", min_value=500, max_value=5000, value=1500, step=500)

    if run_scan:
        market_stocks = get_active_market_stocks()
        filtered_stocks = market_stocks[market_stocks['volume'] >= min_vol_limit].sort_values(by="volume", ascending=False)
        
        with st.spinner(f"正在分析全市場 {len(filtered_stocks)} 檔高流動性標的... (請耐心等候)"):
            buy_signals = []
            
            def quick_scan(row):
                sid = str(row['id'])
                sname = name_map.get(sid, str(row.get('name', '')))
                sind = industry_map.get(sid, "其他板塊")
                
                hist = get_stock_history(sid)
                if hist.empty or len(hist) < 70: return None
                
                hist = calculate_indicators(hist)
                close, open_p, low = hist['Close'].astype(float), hist['Open'].astype(float), hist['Low'].astype(float)
                vol = hist['Volume'].astype(float)
                
                curr_price = round(close.iloc[-1], 2)
                vol_today = vol.iloc[-1]
                vol_ma5 = vol.rolling(5).mean().iloc[-1]
                vol_ma20 = vol.rolling(20).mean()
                ma5, ma10, ma60 = hist['MA5'], hist['MA10'], hist['MA60']
                rsi = round(hist['RSI'].iloc[-1], 1)
                
                if vol_ma5 <= 1500: return None
                if vol_today >= vol_ma5: return None 
                if curr_price <= ma60.iloc[-1]: return None
                if ma60.iloc[-1] <= ma60.iloc[-2]: return None 
                if not (50 <= rsi <= 65): return None 
                
                bias_ma5 = (curr_price - ma5.iloc[-1]) / ma5.iloc[-1]
                bias_ma10 = (curr_price - ma10.iloc[-1]) / ma10.iloc[-1]
                if not ((0 <= bias_ma5 <= 0.02) or (0 <= bias_ma10 <= 0.02)): return None
                
                lower_shadow = min(curr_price, open_p.iloc[-1]) - low.iloc[-1]
                real_body = abs(curr_price - open_p.iloc[-1])
                is_supported = (curr_price >= close.iloc[-2]) or (lower_shadow > real_body and lower_shadow > 0)
                if not is_supported: return None
                
                found_pattern = ""
                trigger_days_ago = 0
                for i in range(-10, -2): 
                    if vol.iloc[i] > vol_ma20.iloc[i] * 2 and close.iloc[i] > open_p.iloc[i]:
                        pat = detect_historical_breakout(hist, i)
                        if pat:
                            found_pattern = pat
                            trigger_days_ago = abs(i) - 1 
                            break
                            
                if found_pattern:
                    struct_stop = min(ma5.iloc[-1], ma10.iloc[-1]) 
                    target_price = hist['High'].iloc[-60:].max() * 1.1 
                    return {"代號": sid, "名稱": sname, "產業": sind, "現價": curr_price, "歷史發動點": f"{trigger_days_ago} 天前", "主力起漲型態": found_pattern, "建議停損": round(struct_stop, 2), "目標停利": round(target_price, 2), "RSI指標": rsi}
                return None

            progress_bar = st.progress(0)
            status_text = st.empty()

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(quick_scan, row): row for _, row in filtered_stocks.iterrows()}
                completed = 0
                for f in concurrent.futures.as_completed(futures):
                    completed += 1
                    status_text.text(f"🔍 正在尋找量縮回測洗盤買點... (進度: {completed} / {len(filtered_stocks)})")
                    progress_bar.progress(completed / len(filtered_stocks))
                    res = f.result()
                    if res: buy_signals.append(res)
            
            status_text.empty()
            progress_bar.empty()
            
            if buy_signals:
                df_result = pd.DataFrame(buy_signals)
                st.success(f"🎯 掃描完成！目前市場上有 {len(df_result)} 檔標的符合【起漲後量縮回測支撐】之低風險買點：")
                top_cols = st.columns(min(len(df_result), 3))
                for i in range(min(len(df_result), 3)):
                    item = df_result.iloc[i]
                    with top_cols[i]:
                        st.markdown(f"#### 🏆 No.{i+1} {item['代號']} {item['名稱']}")
                        st.info(f"**回測洗盤點確認 (RSI: {item['RSI指標']})**")
                        st.write(f"🏢 產業：{item['產業']} ｜ 💰 現價：**${item['現價']}**")
                        st.write(f"🔥 主力軌跡：{item['歷史發動點']} 觸發【{item['主力起漲型態']}】")
                        st.write(f"🎯 目標價：${item['目標停利']} ｜ 🚨 防守極限：${item['建議停損']}")
                st.markdown("---")
                st.markdown("### 📋 完整符合清單")
                st.dataframe(df_result, use_container_width=True)
            else:
                st.warning("目前盤面暫無完美符合【起漲後量縮回踩 5日/10日線】之個股，建議保留資金耐心等候洗盤結束。")

# ==================== 分頁三：個股深度診斷 ====================
with tab3:
    st.subheader("🔍 個股深度診斷 ＆ 三相評分儀表板")
    target_stock = st.text_input("請輸入台股代號（例：2330, 4960, 2303）：", value="2330")

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
                                # ✅ 完全退回最初最穩定不挑版本的 gemini-pro
                                res = genai.GenerativeModel("gemini-pro").generate_content(prompt)
                                st.success(res.text)
                            except Exception as e:
                                st.error(f"⚠ 系統錯誤，詳細原因：{e}")

            with col2:
                c_score, c_details = pillars["Chip"]
                st.markdown(f"### ⛽ 主力燃料 ({c_score}/20)")
                for k, (s, m, desc) in c_details.items(): st.write(f"- {desc}")

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
                                # ✅ 完全退回最初最穩定不挑版本的 gemini-pro
                                res = genai.GenerativeModel("gemini-pro").generate_content(prompt)
                                st.warning(res.text)
                            except Exception as e:
                                st.error(f"⚠ 系統錯誤，詳細原因：{e}")

            st.markdown("---")
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
                            3. 🎯 **【戰情室綜合診斷】**：請根據上述硬數據與分數，告訴我這檔股票目前的「真實位階」，以及最終的操作定調。
                            """
                            # ✅ 完全退回最初最穩定不挑版本的 gemini-pro
                            res = genai.GenerativeModel("gemini-pro").generate_content(master_prompt)
                            st.info(res.text)
                        except Exception as e:
                            st.error(f"⚠️ 系統錯誤，詳細原因：{e}")
