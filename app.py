import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests, io
import json
from datetime import datetime, timedelta
import google.generativeai as genai

st.set_page_config(page_title="台股低基期起漲量化戰情室", layout="wide")

# --- 🔒 密碼防護解鎖機制 ---
def check_password():
    def password_entered():
        # 預設密碼若沒在 Secrets 設定，則預設為 "1234"
        correct_pwd = st.secrets.get("PASSWORD", "1234")
        if st.session_state["password"] == correct_pwd:
            st.session_state["password_correct"] = True
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

# 如果密碼不正確，直接停止執行後續網頁內容
if not check_password():
    st.stop()
# -------------------------

st.title("🎯 台股量化作戰室：低基期起漲 ＆ AI 題材方格儀表板 ＆ 個人持股戰情室")

DEFAULT_THEME_POOLS = {
    "🌐 CPO 光通訊 / 矽光子": ["6442", "3450", "4979", "3163", "6451", "3081", "4908"],
    "📦 IC 載板 ＆ 高階 PCB": ["3037", "3189", "8046", "4958", "2383", "6274", "2368"],
    "⚡ PCB 銅箔基板 (CCL)": ["6213", "2383", "6274", "5347", "8358"],
    "🧵 玻纖布 ＆ 上游材料": ["1815", "5388", "5475", "1314"],
    "🔋 功率半導體 / 碳化矽": ["5425", "2481", "8261", "6573", "3707"],
    "🔮 矽晶圓 ＆ 半導體材料": ["6488", "3532", "6182", "5483", "3702"],
    "📌 導線架 ＆ 封裝零組件": ["2351", "5285", "6531"],
    "🛰️ 低軌衛星 ＆ 航太通訊": ["2314", "3491", "6285", "2313", "3062", "2317"],
    "⚙️ 半導體 / AI 設備": ["3131", "3583", "6187", "5443", "2467", "8064", "2404"],
    "💾 記憶體 ＆ 模組": ["2408", "8299", "3260", "2344", "4967"],
    "❄️ AI 散熱 ＆ 液冷架構": ["3017", "3324", "8996", "3653", "6642", "3483"],
    "🔌 重電電網 ＆ 綠能儲能": ["1519", "1503", "1513", "1514", "2371", "6806"],
    "🖥️ AI 伺服器 ＆ 電源機殼": ["6669", "2382", "3231", "2376", "2356", "8210", "3617", "2059"]
}

INDUSTRY_MAP = {
    "半導體業": "半導體 / 先進製程 / 封測",
    "電腦及週邊設備業": "電腦硬體 / AI伺服器代工",
    "電子零組件業": "電子零組件 / PCB / 散熱 / 被動元件",
    "通信網路業": "網通設備 / CPO光通訊",
    "電機機械": "重電設備 / 綠能電網 / 電線電纜",
    "電機機械業": "重電設備 / 綠能電網 / 電線電纜",
    "電子通路業": "電子零組件通路商",
    "資訊服務業": "資訊軟體 / 系統整合",
    "化學工業": "化學工業 / 特用化學",
    "鋼鐵工業": "鋼鐵鋼筋",
    "生技醫療業": "生技醫療",
    "航運業": "航運航港 / 貨櫃 / 航空"
}

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
                    ind = INDUSTRY_MAP.get(raw_ind, raw_ind)
                    industry_map[raw[0]] = ind
                    industry_map[ticker] = ind
        except Exception:
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
    except Exception:
        pass
    
    return pd.DataFrame([
        {"id": "3617", "name": "碩天", "volume": 1800, "close": 350},
        {"id": "2486", "name": "一詮", "volume": 3500, "close": 150},
        {"id": "6642", "name": "富致", "volume": 900, "close": 75},
        {"id": "2356", "name": "英業達", "volume": 15000, "close": 50},
        {"id": "8234", "name": "新漢", "volume": 2500, "close": 70},
        {"id": "6278", "name": "台表科", "volume": 3000, "close": 115},
        {"id": "6271", "name": "同欣電", "volume": 2200, "close": 180},
        {"id": "2369", "name": "菱生", "volume": 5000, "close": 40},
    ])

def calculate_indicators(df):
    close = df['Close'].astype(float)
    low, high = df['Low'].astype(float), df['High'].astype(float)
    
    df['MA5'] = close.rolling(5).mean()
    df['MA10'] = close.rolling(10).mean()
    df['MA20'] = close.rolling(20).mean()
    df['MA60'] = close.rolling(60).mean()

    l9, h9 = low.rolling(9).min(), high.rolling(9).max()
    rsv = ((close - l9) / (h9 - l9) * 100).fillna(50)
    df['K'] = rsv.ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()

    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def detect_pattern(df):
    if len(df) < 60: return "", 0, 0
    close = df['Close']
    curr_price = close.iloc[-1]
    ma20 = df['MA20'].iloc[-1]
    high, low = df['High'], df['Low']
    
    if curr_price < ma20:
        return "", 0, 0

    pattern = ""
    struct_stop_loss = ma20
    
    ma_prev = [df['MA5'].iloc[-2], df['MA10'].iloc[-2], df['MA20'].iloc[-2], df['MA60'].iloc[-2]]
    if (max(ma_prev) - min(ma_prev)) / min(ma_prev) <= 0.03 and curr_price > max(ma_prev):
        pattern = "【均線糾結突破】"
        struct_stop_loss = min(ma_prev)
    elif (high.iloc[-31:-1].max() - low.iloc[-31:-1].min()) / low.iloc[-31:-1].min() <= 0.15 and curr_price > high.iloc[-31:-1].max():
        pattern = "【箱型整理突破】"
        struct_stop_loss = (high.iloc[-31:-1].max() + low.iloc[-31:-1].min()) / 2
    elif (high.iloc[-21:-1].max() - low.iloc[-21:-1].min()) < (high.iloc[-41:-21].max() - low.iloc[-41:-21].min()) * 0.7 and curr_price > high.iloc[-21:-1].max():
        pattern = "【碗型VCP突破】"
        struct_stop_loss = low.iloc[-21:-1].min()
    elif low.iloc[-21:-1].min() > low.iloc[-41:-21].min() and curr_price > high.iloc[-21:-1].max():
        pattern = "【階梯N字突破】"
        struct_stop_loss = low.iloc[-21:-1].min()
    elif (low.iloc[-15:-3] < low.iloc[-60:-15].min()).any() and (close.iloc[-3:-1] > low.iloc[-60:-15].min()).any() and curr_price > high.iloc[-15:-1].max():
        pattern = "【破底翻大底】"
        struct_stop_loss = low.iloc[-15:-1].min()
    elif df['K'].iloc[-1] > df['D'].iloc[-1] and df['K'].iloc[-1] > df['K'].iloc[-2] and df['RSI'].iloc[-1] > 50:
        pattern = "【新金叉發動】" if df['K'].iloc[-2] <= df['D'].iloc[-2] else "【多頭續強】"
        struct_stop_loss = max(low.iloc[-1], ma20)

    if pattern != "":
        pressure = high.iloc[-20:].max()
        target = curr_price * 1.1 if curr_price >= pressure * 0.98 else pressure
        return pattern, target, struct_stop_loss

    return "", 0, 0

@st.cache_data(ttl=3600)
def get_real_chip_data(symbol):
    track_a_score, track_b_score = 5, 5
    desc_a, desc_b = "🟡 集保大戶持股結構中性穩定", "🟡 三大法人近期買賣超動能平緩"
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    
    try:
        url_inst = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={symbol}&start_date={start_date}&end_date={end_date}"
        res_inst = requests.get(url_inst, timeout=5)
        if res_inst.status_code == 200:
            data_inst = res_inst.json().get("data", [])
            if data_inst:
                df_inst = pd.DataFrame(data_inst)
                df_inst['net'] = pd.to_numeric(df_inst['buy'], errors='coerce') - pd.to_numeric(df_inst['sell'], errors='coerce')
                recent_net = df_inst.tail(5)['net'].sum()
                if recent_net > 500:
                    track_b_score = 10
                    desc_b = f"✅ 三大法人近期強力買超 (5日累計淨買超 +{int(recent_net)} 張)"
                elif recent_net < -500:
                    track_b_score = 2
                    desc_b = f"❌ 三大法人近期呈現調節賣超 (5日累計淨買超 {int(recent_net)} 張)"
        
        url_share = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockShareholding&data_id={symbol}&start_date={start_date}&end_date={end_date}"
        res_share = requests.get(url_share, timeout=5)
        if res_share.status_code == 200:
            data_share = res_share.json().get("data", [])
            if data_share:
                df_share = pd.DataFrame(data_share)
                if 'holding_shares_level' in df_share.columns:
                    df_big = df_share[df_share['holding_shares_level'].astype(str).str.contains('1000', na=False)]
                    if len(df_big) >= 2:
                        latest_ratio = float(df_big.iloc[-1].get('percent', 40))
                        prev_ratio = float(df_big.iloc[-2].get('percent', 40))
                        if latest_ratio > prev_ratio or latest_ratio >= 50:
                            track_a_score = 10
                            desc_a = f"✅ 集保大戶持股集中 (千張大戶持股比達 {latest_ratio}%，較前週增加)"
                        else:
                            track_a_score = 4
                            desc_a = f"⚠️ 集保大戶持股比微幅下滑至 {latest_ratio}%"
    except Exception:
        pass

    total_chip_score = track_a_score + track_b_score
    chip_desc_combined = f"【軌道A-集保大戶】{desc_a}\n【軌道B-三大法人】{desc_b}"
    return total_chip_score, chip_desc_combined

def evaluate_single_stock(ticker_obj, hist, symbol):
    s_bias, s_vol_kd, s_gm, s_om, s_pat = 0, 0, 0, 0, 0
    desc_bias, desc_vol_kd, desc_gm, desc_om, desc_pat = "", "", "", "", ""
    
    curr_p = round(hist['Close'].iloc[-1], 2)
    ma20 = round(hist['MA20'].iloc[-1], 2)
    k_val = round(hist['K'].iloc[-1], 1)
    d_val = round(hist['D'].iloc[-1], 1)
    vol_today = hist['Volume'].iloc[-1]
    vol_ma20 = hist['Volume'].rolling(20).mean().iloc[-1]
    vol_ratio = round(vol_today / vol_ma20, 2) if vol_ma20 > 0 else 1.0
    
    bias_pct = round(((curr_p - ma20) / ma20) * 100, 2)
    if 0 < (curr_p - ma20) / ma20 <= 0.08:
        s_bias = 20
        desc_bias = f"✅ 站上月線且乖離僅 {bias_pct}% (緊貼成本區，具備起漲安全邊界)"
    elif (curr_p - ma20) / ma20 > 0.08:
        s_bias = 8
        desc_bias = f"⚠️ 站上月線但乖離達 {bias_pct}% (已脫離起漲區，需防短線拉回)"
    else:
        s_bias = 0
        desc_bias = f"❌ 跌破月線 (乖離 {bias_pct}%)，尚未進入多頭起漲軌道"

    is_vol_surge = vol_today >= (vol_ma20 * 1.3)
    if k_val > d_val and k_val < 65:
        if is_vol_surge:
            s_vol_kd = 20
            desc_vol_kd = f"✅ 低檔多頭金叉 (K:{k_val} > D:{d_val}) ＋ 今日成交量放大至 {vol_ratio} 倍 (主力點火表態)"
        else:
            s_vol_kd = 12
            desc_vol_kd = f"🟡 低檔金叉 (K:{k_val} > D:{d_val}) 但量能僅均量 {vol_ratio} 倍"
    elif k_val > d_val:
        s_vol_kd = 8
        desc_vol_kd = f"⚠️ KD 處於高檔多頭 (K:{k_val})"
    else:
        s_vol_kd = 0
        desc_vol_kd = f"❌ KD 呈現空頭死叉"

    info = ticker_obj.info
    gm = info.get('grossMargins', 0)
    om = info.get('operatingMargins', 0)
    
    if gm and gm >= 0.30:
        s_gm = 20
        desc_gm = f"✅ 超高毛利率達 {round(gm*100, 1)}% (享有產品定價權)"
    elif gm and gm >= 0.15:
        s_gm = 12
        desc_gm = f"🟡 穩健毛利率達 {round(gm*100, 1)}%"
    else:
        s_gm = 0
        desc_gm = f"❌ 毛利率偏低"

    if om and om > 0.10:
        s_om = 20
        desc_om = f"✅ 營益率達 {round(om*100, 1)}% (本業獲利體質極佳)"
    elif om and om > 0:
        s_om = 12
        desc_om = f"🟡 本業維持獲利 (營益率 {round(om*100, 1)}%)"
    else:
        s_om = 0
        desc_om = f"❌ 本業呈現虧損"

    s_chip, desc_chip = get_real_chip_data(symbol)

    pat, pat_t, pat_s = detect_pattern(hist)
    if "均線糾結" in pat or "破底翻" in pat:
        s_pat = 10
        target, stop = pat_t, pat_s
        desc_pat = f"🔥 命中頂級起漲型態：{pat}！"
    elif pat != "":
        s_pat = 5
        target, stop = pat_t, pat_s
        desc_pat = f"🔥 命中突破型態：{pat}"
    else:
        target = curr_p * 1.08
        stop = ma20
        desc_pat = "一般均線排列推進"

    total_score = s_bias + s_vol_kd + s_gm + s_om + s_chip + s_pat
    light = "🟢 超級起漲" if total_score >= 85 else ("🟡 潛力加溫" if total_score >= 65 else "⚪ 區間觀望")

    score_details = {
        "低基期乖離": (s_bias, 20, desc_bias),
        "爆量KD動能": (s_vol_kd, 20, desc_vol_kd),
        "產品毛利率": (s_gm, 20, desc_gm),
        "本業營益率": (s_om, 20, desc_om),
        "雙軌籌碼追蹤(集保大戶+三大法人)": (s_chip, 20, desc_chip),
        "突破型態加分": (s_pat, 10, desc_pat)
    }
    return total_score, light, round(target, 2), round(stop, 2), score_details

def get_stock_data(symbol):
    for suffix in [".TW", ".TWO"]:
        ticker = yf.Ticker(f"{symbol}{suffix}")
        hist = ticker.history(period="6mo")
        if not hist.empty:
            if isinstance(hist.columns, pd.MultiIndex): hist.columns = hist.columns.get_level_values(0)
            return ticker, hist
    return None, pd.DataFrame()

tab1, tab2, tab3, tab4 = st.tabs(["🚀 起漲掃描榜", "🔥 AI 題材儀表板", "🔍 個股深度診斷", "💼 個人持股戰情室"])

# ==================== 分頁一：起漲掃描榜 ====================
with tab1:
    with st.expander("📖 點擊展開：【六大維度量化評分標準與雙軌籌碼邏輯】", expanded=False):
        st.markdown("""
        | 維度 | 評估核心 | 具體加分邏輯 | 滿分 |
        | :--- | :--- | :--- | :---: |
        | **1. 低基期乖離** | 防追高、抓起漲第一棒 | 站上月線且乖離 $\le 8\%$：**20分** | 20分 |
        | **2. 爆量攻擊** | 主力點火、低檔金叉 | 低檔金叉 ($K<65$) 且量放大 1.3 倍：**20分** | 20分 |
        | **3. 產品毛利率** | 產品定價權與護城河 | 毛利率 $\ge 30\%$：**20分** | 20分 |
        | **4. 本業營益率** | 實質本業獲利能力 | 營益率 $> 10\%$：**20分** | 20分 |
        | **5. 雙軌籌碼追蹤** | 軌道A(集保大戶) ＋ 軌道B(三大法人連買) | 大戶持股集中或法人強勢連買：**最高20分** | 20分 |
        | **🔥 型態加分** | 洗盤結束突破 | 均線糾結 / 破底翻 / VCP 突破：**額外 +10分** | Bonus |
        """)

    col_ctrl1, col_ctrl2 = st.columns([1, 2])
    with col_ctrl1:
        min_vol_input = st.slider("最低成交量門檻 (張)", min_value=500, max_value=5000, value=1000, step=100)
        scan_limit = st.slider("掃描候選池數量上限", min_value=15, max_value=60, value=30, step=5)
    
    if st.button("🔥 立即執行低基期起漲掃描"):
        market_stocks = get_active_market_stocks()
        candidates = market_stocks[market_stocks['volume'] >= min_vol_input].sort_values(by="volume", ascending=False).head(scan_limit)
        
        st.write(f"已從市場鎖定 **{len(candidates)} 檔** 動能標的進行全方位評分解剖...")
        progress_bar = st.progress(0)
        ranking_list = []
        detail_dict = {}
        
        for idx, (_, row) in enumerate(candidates.iterrows()):
            sid = str(row['id'])
            sname = name_map.get(sid, str(row['name']))
            sind = industry_map.get(sid, "其他板塊")
            
            try:
                ticker, hist = get_stock_data(sid)
                if not hist.empty and len(hist) >= 60:
                    hist = calculate_indicators(hist)
                    score, light, target, stop, details = evaluate_single_stock(ticker, hist, sid)
                    curr_p = round(hist['Close'].iloc[-1], 2)
                    tag = "雙軌籌碼共振" if details["雙軌籌碼追蹤(集保大戶+三大法人)"][0] >= 15 else "動能觀察"
                else:
                    curr_p = row['close']
                    score, light, target, stop, details = 0, "⚪ 數據不足", curr_p * 1.08, curr_p * 0.93, {}
                    tag = "無資料"
            except Exception:
                curr_p = row['close']
                score, light, target, stop, details = 0, "⚪ 異常", curr_p * 1.08, curr_p * 0.93, {}
                tag = "異常"

            ranking_list.append({
                "代號": sid,
                "名稱": sname,
                "產業類別": sind,
                "綜合總分": score,
                "狀態燈號": light,
                "目前現價": curr_p,
                "短線目標價": target,
                "結構防守價": stop,
                "主要特徵標籤": tag
            })
            
            detail_dict[f"{sid} {sname}"] = {
                "現價": curr_p, "目標價": target, "防守價": stop,
                "總分": score, "燈號": light, "產業": sind, "細項得分": details
            }
            progress_bar.progress((idx + 1) / len(candidates))

        st.session_state['scan_df'] = pd.DataFrame(ranking_list).sort_values(by="綜合總分", ascending=False).reset_index(drop=True)
        st.session_state['scan_details'] = detail_dict

    if 'scan_df' in st.session_state:
        st.success(f"✅ 掃描完成！共評估 {len(st.session_state['scan_df'])} 檔活躍股：")
        st.dataframe(st.session_state['scan_df'], use_container_width=True)

        st.markdown("---")
        st.subheader("🔍 點擊查看排行榜個股【六大維度得分解剖明細】")
        selected_stock = st.selectbox("請選擇欲深入查看得分解剖的股票：", list(st.session_state['scan_details'].keys()))
        
        if selected_stock:
            info_data = st.session_state['scan_details'][selected_stock]
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("綜合量化總分", f"{info_data['總分']} 分", info_data['燈號'])
            k2.metric("目前現價", f"${info_data['現價']}")
            k3.metric("短線目標價", f"${info_data['目標價']}")
            k4.metric("結構防守價", f"${info_data['防守價']}")

            st.info(f"🏢 **產業板塊歸屬**：{info_data['產業']}")

            st.write("#### 📊 六大維度具體得分與條件觸發原因：")
            for cat_name, (score_val, max_val, reason_text) in info_data["細項得分"].items():
                with st.container():
                    c_badge, c_text = st.columns([1, 4])
                    with c_badge:
                        if score_val >= max_val * 0.8:
                            st.success(f"**{cat_name}**：{score_val} / {max_val} 分")
                        elif score_val > 0:
                            st.warning(f"**{cat_name}**：{score_val} / {max_val} 分")
                        else:
                            st.error(f"**{cat_name}**：{score_val} / {max_val} 分")
                    with c_text:
                        st.markdown(f"👉 **觸發情況**：\n{reason_text}")
                    st.divider()

# ==================== 分頁二：AI 智慧題材方格儀表板 ====================
with tab2:
    st.subheader("🔥 AI 智慧題材板塊 ＆ 族群熱力方格戰情室")
    st.caption("戰略應用：點擊下方任何一個【題材方格卡片】，即可立刻載入該族群的詳細個股量化對比與起漲推薦！")
    
    with st.expander("✨ 找不到想看的題材？點此使用 AI 動態新增自訂題材池", expanded=False):
        c_in1, c_in2 = st.columns([3, 1])
        with c_in1:
            custom_theme_input = st.text_input("輸入新題材名稱（例如：『機器人概念股』、『太空低軌衛星』）：", value="")
        with c_in2:
            st.write("")
            st.write("")
            add_ai_theme_btn = st.button("🤖 讓 AI 生成加入方格")
        
        if add_ai_theme_btn and custom_theme_input and "GEMINI_API_KEY" in st.secrets:
            with st.spinner(f"AI 正在為您建立【{custom_theme_input}】成分股代號池中..."):
                try:
                    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                    prompt = f"""
                    請列出台灣股市（台股）中與「{custom_theme_input}」高度相關的 5 到 8 間代表性上市公司或上櫃公司的【4位數股票代號】。
                    請直接回傳一個純 JSON 格式的 4 位數代號字串陣列（List of string），例如：["6488", "3532", "6182"]。不要包含任何額外的文字或 Markdown 標記。
                    """
                    model = genai.GenerativeModel("gemini-3.6-flash")
                    res = model.generate_content(prompt)
                    cleaned_text = res.text.replace("```json", "").replace("```", "").strip()
                    ai_tickers = json.loads(cleaned_text)
                    
                    theme_key = f"✨ {custom_theme_input}"
                    DEFAULT_THEME_POOLS[theme_key] = ai_tickers
                    st.success(f"✅ 成功新增題材【{theme_key}】！請在下方方格點擊查看。")
                except Exception as e:
                    st.error(f"AI 生成題材失敗：{e}")

    st.markdown("---")
    
    if 'active_theme' not in st.session_state:
        st.session_state['active_theme'] = list(DEFAULT_THEME_POOLS.keys())[0]

    st.write("#### 🧱 點擊方格以切換檢視族群戰情：")
    
    themes_list = list(DEFAULT_THEME_POOLS.keys())
    cols_per_row = 4
    for i in range(0, len(themes_list), cols_per_row):
        row_themes = themes_list[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, theme_name in enumerate(row_themes):
            with cols[j]:
                is_selected = (st.session_state['active_theme'] == theme_name)
                btn_label = f"📌 【選中】{theme_name}" if is_selected else theme_name
                
                if st.button(btn_label, use_container_width=True, key=f"tile_{theme_name}"):
                    st.session_state['active_theme'] = theme_name

    active_theme = st.session_state['active_theme']
    st.markdown(f"### 📌 目前選中檢視板塊：**{active_theme}**")
    
    theme_tickers = DEFAULT_THEME_POOLS[active_theme]
    
    with st.spinner(f"正在計算【{active_theme}】族群即時行情與量化評分中..."):
        theme_results = []
        for tid in theme_tickers:
            t_name = name_map.get(tid, tid)
            try:
                ticker, hist = get_stock_data(tid)
                if not hist.empty and len(hist) >= 60:
                    hist = calculate_indicators(hist)
                    score, light, target, stop, details = evaluate_single_stock(ticker, hist, tid)
                    curr_p = round(hist['Close'].iloc[-1], 2)
                    prev_p = round(hist['Close'].iloc[-2], 2)
                    pct_change = round(((curr_p - prev_p) / prev_p) * 100, 2)
                    
                    ma20 = hist['MA20'].iloc[-1]
                    bias_ma20 = round(((curr_p - ma20) / ma20) * 100, 2)
                    vol_today = int(hist['Volume'].iloc[-1] / 1000)
                    
                    theme_results.append({
                        "代號": tid,
                        "名稱": t_name,
                        "今日收盤價": curr_p,
                        "今日漲跌幅(%)": pct_change,
                        "月線乖離率(%)": bias_ma20,
                        "成交量(張)": vol_today,
                        "量化總評分": score,
                        "評分狀態": light,
                        "短線目標價": target,
                        "結構防守價": stop
                    })
            except Exception:
                pass

        if theme_results:
            df_theme = pd.DataFrame(theme_results).sort_values(by="今日漲跌幅(%)", ascending=False).reset_index(drop=True)
            
            avg_pct = round(df_theme["今日漲跌幅(%)"].mean(), 2)
            up_count = len(df_theme[df_theme["今日漲跌幅(%)"] > 0])
            leader_stock = df_theme.iloc[0]["名稱"]
            
            heat_color = "🔥 強勢漲停/大漲" if avg_pct > 1.5 else ("🟢 溫和上漲" if avg_pct > 0 else "📉 整理回檔")
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("族群平均漲跌幅", f"{avg_pct}%", heat_color)
            c2.metric("族群上漲家數比", f"{up_count} / {len(df_theme)} 家")
            c3.metric("今日最強領頭羊", f"{leader_stock}", f"+{df_theme.iloc[0]['今日漲跌幅(%)']}%")
            
            low_bias_candidates = df_theme[df_theme["月線乖離率(%)"] <= 8].sort_values(by="量化總評分", ascending=False)
            best_pick = low_bias_candidates.iloc[0]["名稱"] if not low_bias_candidates.empty else "無(皆已脫離成本區)"
            c4.metric("族群低基期推薦", f"{best_pick}")

            st.markdown("---")
            st.write(f"#### 📋 【{active_theme}】成分股量化數據對比表")
            st.dataframe(df_theme, use_container_width=True)

            st.markdown("#### 📊 成分股月線乖離率分佈 (尋找 $\le 8\%$ 安全起漲區)")
            fig_bar = go.Figure()
            colors = ['#2ca02c' if b <= 8 and b >= 0 else ('#ff7f0e' if b > 8 else '#d62728') for b in df_theme['月線乖離率(%)']]
            fig_bar.add_trace(go.Bar(
                x=df_theme['名稱'],
                y=df_theme['月線乖離率(%)'],
                marker_color=colors,
                text=[f"{b}%" for b in df_theme['月線乖離率(%)']],
                textposition='auto'
            ))
            fig_bar.add_hline(y=8, line_dash="dash", line_color="orange", annotation_text="8% 起漲安全邊界線")
            fig_bar.add_hline(y=0, line_dash="solid", line_color="gray")
            fig_bar.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20), yaxis_title="月線乖離率 (%)")
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.error("目前讀取族群行情異常或查無對應成分股。")

# ==================== 分頁三：個股深度診斷 ====================
with tab3:
    st.subheader("🔍 個股深度診斷 ＆ AI 產業分析師 ＆ 估值模型")
    target_stock = st.text_input("請輸入台股代號（例：3617, 2486, 2356, 2303, 6278）：", value="3617")

    if target_stock:
        ticker_obj, hist = get_stock_data(target_stock)
        
        if not hist.empty and len(hist) >= 60:
            hist = calculate_indicators(hist)
            info = ticker_obj.info
            
            s_name = name_map.get(target_stock, "")
            display_title = f"{target_stock} {s_name}" if s_name else target_stock
            s_ind = industry_map.get(target_stock, "其他板塊")
            
            score, light, tech_target, tech_stop, details = evaluate_single_stock(ticker_obj, hist, target_stock)
            
            latest_price = round(hist['Close'].iloc[-1], 2)
            prev_price = round(hist['Close'].iloc[-2], 2)
            price_change = round(((latest_price - prev_price) / prev_price) * 100, 2)
            
            gm = round(info.get('grossMargins', 0) * 100, 2) if info.get('grossMargins') else "N/A"
            om = round(info.get('operatingMargins', 0) * 100, 2) if info.get('operatingMargins') else "N/A"
            eps = round(info.get('trailingEps', 0), 2) if info.get('trailingEps') else None
            curr_pe = round(info.get('trailingPE', 0), 1) if info.get('trailingPE') else None
            
            analyst_target = info.get('targetMeanPrice')
            analyst_high = info.get('targetHighPrice')
            analyst_low = info.get('targetLowPrice')
            
            pe_bench = INDUSTRY_PE_BENCHMARK.get(s_ind, INDUSTRY_PE_BENCHMARK["其他板塊"])
            val_low, val_mid, val_high = None, None, None
            if eps and eps > 0:
                val_low = round(eps * pe_bench["low"], 1)
                val_mid = round(eps * pe_bench["mid"], 1)
                val_high = round(eps * pe_bench["high"], 1)

            st.markdown(f"### 📌 當前檢測標的：**{display_title}**")

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("綜合量化評分", f"{score} 分", light)
            k2.metric("最新收盤價", f"${latest_price}", f"{price_change}%")
            k3.metric("目前本益比 (P/E)", f"{curr_pe} 倍" if curr_pe else "N/A")
            k4.metric("近四季 EPS", f"{eps} 元" if eps else "無資料")

            st.info(f"🏢 **產業板塊歸屬**：{s_ind} ｜ **常態合理 P/E 區間**：{pe_bench['low']}X ~ {pe_bench['high']}X (中位數基準: {pe_bench['mid']}X)")

            st.markdown("---")
            st.subheader(f"🤖 AI 產業分析師：{display_title} 業務解密")
            
            if "GEMINI_API_KEY" in st.secrets:
                if st.button(f"✨ 點擊生成 {display_title} 深度業務與競爭力解析"):
                    with st.spinner("AI 正在深度解析該公司業務模式、供應鏈地位與市場題材中..."):
                        try:
                            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                            summary_en = info.get('longBusinessSummary', '無官方簡介')
                            
                            prompt = f"""
                            請以台股專業操盤手與產業分析師的角度，針對台灣股票「{display_title}」（產業板塊：{s_ind}，近四季EPS：{eps}元，目前本益比：{curr_pe}倍）進行深度業務解析。
                            參考英文業務背景：{summary_en}
                            
                            請分為以下四大區塊回答：
                            1. **核心業務與主要產品**：這間公司到底靠什麼賺錢？主力產品或服務是什麼？
                            2. **產業供應鏈地位與 AI 關聯性**：它在該產業（{s_ind}）中是龍頭、中游供應商還是利基型黑馬？特別說明它與當前 AI 浪潮是否有高度相關？在 AI 興起的階段，它是否有成功搭上順風車？
                            3. **AI 供應鏈中的角色（上中下游）**：若與 AI 相關，它屬於上游（如關鍵零組件、矽智財、晶圓代工）、中游（如伺服器組裝、散熱、PCB、機殼、CPO光通訊）還是下游應用？若與 AI 無關，其主要核心應用領域為何？
                            4. **近期營運亮點或題材**：結合當前市場趨勢，它具備什麼題材或成長潛力？
                            
                            請使用繁體中文回答，語氣專業、精煉、條理分明，適合投資人快速掌握。
                            """
                            
                            model = genai.GenerativeModel("gemini-3.6-flash")
                            response = model.generate_content(prompt)
                            st.markdown(response.text)
                        except Exception as e:
                            st.error(f"AI 生成報告發生錯誤：{e}")
            else:
                st.info("💡 提示：若想啟用專屬 AI 分析報告，請至 Streamlit Cloud 的 Secrets 中設定您的 `GEMINI_API_KEY`。")

            st.markdown("---")
            st.subheader("🎯 目標價與估值空間解剖 (法人共識 ＆ 產業本益比推估)")
            
            v_col1, v_col2, v_col3 = st.columns(3)
            with v_col1:
                st.markdown("#### 🏢 法人機構目標價")
                if analyst_target:
                    upside_analyst = round(((analyst_target - latest_price) / latest_price) * 100, 1)
                    st.metric("法人共識平均目標價", f"${round(analyst_target, 1)}", f"潛在空間: {upside_analyst}%")
                    st.caption(f"法人預估區間：**${round(analyst_low, 1)} ~ ${round(analyst_high, 1)}**" if analyst_high else "")
                else:
                    st.info("法人目前尚無公開共識目標價。")

            with v_col2:
                st.markdown(f"#### 🏭 產業 P/E 估值推算")
                if val_mid:
                    upside_pe = round(((val_mid - latest_price) / latest_price) * 100, 1)
                    st.metric(f"產業合理目標價 ({pe_bench['mid']}X)", f"${val_mid}", f"潛在空間: {upside_pe}%")
                    st.caption(f"估值河流區間：保守 **${val_low}** ～ 樂觀 **${val_high}**")
                else:
                    st.info("因近四季 EPS 為負或無資料，無法進行本益比推算。")

            with v_col3:
                st.markdown("#### 📐 技術線型結構點位")
                upside_tech = round(((tech_target - latest_price) / latest_price) * 100, 1)
                st.metric("波段技術壓力目標價", f"${tech_target}", f"潛在空間: {upside_tech}%")
                st.caption(f"關鍵停損防守價：**${tech_stop}**")

            st.markdown("---")
            with st.expander(f"📋 點擊查看【{display_title}】六大維度得分解剖與雙軌籌碼追蹤", expanded=True):
                for cat_name, (score_val, max_val, reason_text) in details.items():
                    c_badge, c_text = st.columns([1, 4])
                    with c_badge:
                        if score_val >= max_val * 0.8:
                            st.success(f"**{cat_name}**：{score_val} / {max_val} 分")
                        elif score_val > 0:
                            st.warning(f"**{cat_name}**：{score_val} / {max_val} 分")
                        else:
                            st.error(f"**{cat_name}**：{score_val} / {max_val} 分")
                    with c_text:
                        st.markdown(f"👉 **觸發情況**：\n{reason_text}")
                    st.divider()

            st.subheader(f"📈 {display_title} 技術線型 (日K / MA5 / MA10 / MA20 / MA60)")
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=hist.index, open=hist['Open'], high=hist['High'],
                low=hist['Low'], close=hist['Close'], name='日K線'
            ))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA5'], line=dict(color='orange', width=1.2), name='5MA'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA10'], line=dict(color='purple', width=1.2), name='10MA'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA20'], line=dict(color='blue', width=2), name='20MA (月線)'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60'], line=dict(color='green', width=1.5), name='60MA (季線)'))
            fig.update_layout(xaxis_rangeslider_visible=False, height=450, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("查無此代號技術數據或歷史長度不足 60 天，請確認代號是否正確。")

# ==================== 分頁四：個人持股戰情室 ====================
with tab4:
    st.subheader("💼 個人持股部位戰情室 ＆ 智慧操作建議")
    st.caption("戰略應用：在此輸入您目前擁有的持股與成本，系統將即時比對量化評分與防守價，為您提供續抱、加碼或停損建議！")
    
    if 'my_portfolio' not in st.session_state:
        st.session_state['my_portfolio'] = pd.DataFrame([
            {"代號": "3617", "張數": 2, "成本價": 320.0},
            {"代號": "2486", "張數": 5, "成本價": 135.0}
        ])

    st.write("#### 📝 輸入或編輯您的庫存清單：")
    edited_portfolio = st.data_editor(
        st.session_state['my_portfolio'],
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "代號": st.column_config.TextColumn("股票 4 位數代號", max_chars=4, required=True),
            "張數": st.column_config.NumberColumn("持有張數", min_value=0.1, step=1, required=True),
            "成本價": st.column_config.NumberColumn("每股平均成本 (元)", min_value=0.1, step=0.1, required=True)
        }
    )
    st.session_state['my_portfolio'] = edited_portfolio

    if st.button("🚀 開始檢測與診斷我的持股部位"):
        if edited_portfolio.empty:
            st.warning("請先在上方表格輸入至少一筆持股資料。")
        else:
            with st.spinner("正在連線即時股價、計算未實現損益與量化評分中..."):
                results = []
                total_cost_all = 0
                total_market_all = 0
                
                for _, row in edited_portfolio.iterrows():
                    sid = str(row['代號']).strip()
                    shares = float(row['張數'])
                    cost = float(row['成本價'])
                    
                    if len(sid) != 4:
                        continue
                        
                    sname = name_map.get(sid, sid)
                    
                    try:
                        ticker_obj, hist = get_stock_data(sid)
                        if not hist.empty and len(hist) >= 60:
                            hist = calculate_indicators(hist)
                            score, light, target, stop, details = evaluate_single_stock(ticker_obj, hist, sid)
                            curr_p = round(hist['Close'].iloc[-1], 2)
                            
                            market_val = curr_p * shares * 1000
                            cost_val = cost * shares * 1000
                            pnl = market_val - cost_val
                            pnl_pct = round(((curr_p - cost) / cost) * 100, 2)
                            
                            total_cost_all += cost_val
                            total_market_all += market_val
                            
                            advice = "🟢 續抱/多頭排列"
                            if curr_p < stop:
                                advice = "🚨 跌破防守價，建議停損"
                            elif score >= 85 and pnl_pct > 0:
                                advice = "🔥 強勢飆股，可續抱或沿月線加碼"
                            elif score < 60:
                                advice = "⚠️ 量化評分偏低，留意回檔風險"
                            elif pnl_pct <= -10:
                                advice = "⚠️ 虧損達 10%，檢視是否觸及停損點"

                            results.append({
                                "代號": sid,
                                "名稱": sname,
                                "持股張數": shares,
                                "平均成本": cost,
                                "即時現價": curr_p,
                                "未實現損益(元)": int(pnl),
                                "報酬率(%)": pnl_pct,
                                "量化總分": score,
                                "結構防守價": stop,
                                "操盤建議": advice
                            })
                    except Exception:
                        pass

                if results:
                    df_res = pd.DataFrame(results)
                    total_pnl = total_market_all - total_cost_all
                    total_pnl_pct = round((total_pnl / total_cost_all) * 100, 2) if total_cost_all > 0 else 0
                    
                    st.markdown("---")
                    st.subheader("📊 庫存資產總覽")
                    rc1, rc2, rc3 = st.columns(3)
                    rc1.metric("總持股市值", f"${int(total_market_all):,}")
                    rc2.metric("總投入成本", f"${int(total_cost_all):,}")
                    rc3.metric("總未實現損益", f"${int(total_pnl):,}", f"{total_pnl_pct}%", delta_color="normal" if total_pnl >= 0 else "inverse")

                    st.markdown("---")
                    st.subheader("📋 個股部位戰略體檢表")
                    st.dataframe(df_res, use_container_width=True)
                    
                    st.success("💡 **操盤心法提醒**：若個股出現「🚨 跌破防守價，建議停損」或量化總分掉到 60 分以下，請果斷執行紀律，將資金轉往起漲掃描榜中的高分標的！")
                else:
                    st.error("無法讀取持股資料，請確認輸入的 4 位數台股代號是否正確。")
