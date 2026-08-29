import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests, io

st.set_page_config(page_title="台股低基期起漲量化戰情室", layout="wide")
st.title("🎯 台股量化作戰室：低基期起漲 ＆ 法人產業估值診斷")

# 產業中文化對照表
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

# 產業常態本益比評價倍數基準表 (保守 / 合理 / 樂觀)
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
    """抓取全台股名稱與產業別對照表"""
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
    """從證交所開放平台拉取即時交易量較大之上市股票清單"""
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
    
    # 均線系統
    df['MA5'] = close.rolling(5).mean()
    df['MA10'] = close.rolling(10).mean()
    df['MA20'] = close.rolling(20).mean()
    df['MA60'] = close.rolling(60).mean()

    # KD 指標 (9, 3, 3)
    l9, h9 = low.rolling(9).min(), high.rolling(9).max()
    rsv = ((close - l9) / (h9 - l9) * 100).fillna(50)
    df['K'] = rsv.ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()

    # RSI 強弱指標 (14日)
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

def evaluate_single_stock(ticker_obj, hist):
    """計算單一個股的量化得分與得分解剖明細"""
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
        s_bias = 25
        desc_bias = f"✅ 站上月線且乖離僅 {bias_pct}% (緊貼成本區，具備起漲安全邊界)"
    elif (curr_p - ma20) / ma20 > 0.08:
        s_bias = 10
        desc_bias = f"⚠️ 站上月線但乖離達 {bias_pct}% (已脫離起漲區，需防短線拉回)"
    else:
        s_bias = 0
        desc_bias = f"❌ 跌破月線 (乖離 {bias_pct}%)，尚未進入多頭起漲軌道"

    is_vol_surge = vol_today >= (vol_ma20 * 1.3)
    if k_val > d_val and k_val < 65:
        if is_vol_surge:
            s_vol_kd = 25
            desc_vol_kd = f"✅ 低檔多頭金叉 (K:{k_val} > D:{d_val}) ＋ 今日成交量放大至 {vol_ratio} 倍 (主力點火表態)"
        else:
            s_vol_kd = 15
            desc_vol_kd = f"🟡 低檔金叉 (K:{k_val} > D:{d_val}) 但量能僅均量 {vol_ratio} 倍 (動能尚在溫熱期)"
    elif k_val > d_val:
        s_vol_kd = 10
        desc_vol_kd = f"⚠️ KD 處於高檔多頭 (K:{k_val})，留意指標鈍化或高檔修正"
    else:
        s_vol_kd = 0
        desc_vol_kd = f"❌ KD 呈現空頭死叉 (K:{k_val} < D:{d_val})，動能偏弱"

    info = ticker_obj.info
    gm = info.get('grossMargins', 0)
    om = info.get('operatingMargins', 0)
    
    if gm and gm >= 0.30:
        s_gm = 25
        desc_gm = f"✅ 超高毛利率達 {round(gm*100, 1)}% (享有產品定價權與高護城河)"
    elif gm and gm >= 0.15:
        s_gm = 15
        desc_gm = f"🟡 穩健毛利率達 {round(gm*100, 1)}% (符合電子製造業健康水準)"
    else:
        s_gm = 0
        gm_disp = f"{round(gm*100, 1)}%" if gm else "低於15%"
        desc_gm = f"❌ 毛利率偏低 ({gm_disp})，利潤較薄"

    if om and om > 0.10:
        s_om = 25
        desc_om = f"✅ 營益率達 {round(om*100, 1)}% (本業獲利體質極佳)"
    elif om and om > 0:
        s_om = 15
        desc_om = f"🟡 本業維持獲利 (營益率 {round(om*100, 1)}%)"
    else:
        s_om = 0
        desc_om = "❌ 本業呈現微幅虧損或損益兩平"

    pat, pat_t, pat_s = detect_pattern(hist)
    if "均線糾結" in pat or "破底翻" in pat:
        s_pat = 15
        target, stop = pat_t, pat_s
        desc_pat = f"🔥 命中頂級起漲型態：{pat}！籌碼沉澱完成後第一根表態突破"
    elif pat != "":
        s_pat = 10
        target, stop = pat_t, pat_s
        desc_pat = f"🔥 命中突破型態：{pat}，短線動能強勁"
    else:
        target = curr_p * 1.08
        stop = ma20
        desc_pat = "無特殊經典型態突破，以一般均線排列推進"

    total_score = s_bias + s_vol_kd + s_gm + s_om + s_pat
    light = "🟢 超級起漲" if total_score >= 85 else ("🟡 潛力加溫" if total_score >= 65 else "⚪ 區間觀望")

    score_details = {
        "低基期乖離": (s_bias, 25, desc_bias),
        "爆量KD動能": (s_vol_kd, 25, desc_vol_kd),
        "產品毛利率": (s_gm, 25, desc_gm),
        "本業營益率": (s_om, 25, desc_om),
        "突破型態加分": (s_pat, 15, desc_pat)
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

# 簡潔雙分頁架構
tab1, tab2 = st.tabs(["🚀 低基期起漲掃描榜", "🔍 個股搜尋 ＆ 法人產業估值診斷"])

# ==================== 分頁一：起漲掃描榜 ====================
with tab1:
    with st.expander("📖 點擊展開：【量化評分標準與加分邏輯全覽】", expanded=False):
        st.markdown("""
        | 維度 | 評估核心 | 具體加分邏輯 | 滿分 |
        | :--- | :--- | :--- | :---: |
        | **1. 低基期乖離** | 防追高、抓起漲第一棒 | $\bullet$ 站上月線且乖離 $\le 8\%$（緊貼成本區）：**+25分**<br>$\bullet$ 乖離 $> 8\%$（已脫離成本區）：**+10分**<br>$\bullet$ 跌破月線：**0分** | 25分 |
        | **2. 爆量攻擊** | 抓主力點火，避開高檔假金叉 | $\bullet$ 低檔金叉 ($K<65$) 且量放大 1.3 倍以上：**+25分**<br>$\bullet$ 低檔金叉但量能溫和：**+15分**<br>$\bullet$ 高檔鈍化續強：**+10分** | 25分 |
        | **3. 產品定價權** | 產品利潤厚度 | $\bullet$ 最新毛利率 $\ge 30\%$：**+25分**<br>$\bullet$ 穩健毛利率 $15\% \sim 29.9\%$：**+15分** | 25分 |
        | **4. 本業賺錢力** | 扣除費用後的實質獲利 | $\bullet$ 營業利益率 $> 10\%$：**+25分**<br>$\bullet$ 本業維持獲利 ($> 0\%$)：**+15分** | 25分 |
        | **🔥 型態加分** | 主力洗盤結束突破 | $\bullet$ 命中【均線糾結突破】或【破底翻大底】：**額外加 +15分**<br>$\bullet$ 命中【VCP / 箱型 / N字突破】：**額外加 +10分** | Bonus |
        """)

    col_ctrl1, col_ctrl2 = st.columns([1, 2])
    with col_ctrl1:
        min_vol_input = st.slider("最低成交量門檻 (張)", min_value=500, max_value=5000, value=1000, step=100)
        scan_limit = st.slider("掃描候選池數量上限", min_value=15, max_value=60, value=30, step=5)
    
    if st.button("🔥 立即執行低基期起漲掃描"):
        market_stocks = get_active_market_stocks()
        candidates = market_stocks[market_stocks['volume'] >= min_vol_input].sort_values(by="volume", ascending=False).head(scan_limit)
        
        st.write(f"已從市場鎖定 **{len(candidates)} 檔** 動能標的進行深度評分解剖...")
        progress_bar = st.progress(0)
        ranking_list = []
        
        for idx, (_, row) in enumerate(candidates.iterrows()):
            sid = str(row['id'])
            sname = name_map.get(sid, str(row['name']))
            sind = industry_map.get(sid, "其他板塊")
            
            try:
                ticker, hist = get_stock_data(sid)
                if not hist.empty and len(hist) >= 60:
                    hist = calculate_indicators(hist)
                    score, light, target, stop, details = evaluate_single_stock(ticker, hist)
                    curr_p = round(hist['Close'].iloc[-1], 2)
                    pat_desc = details["突破型態加分"][2]
                    tag = pat_desc.split("：")[-1].split("！")[0] if "🔥" in pat_desc else ("低基期起漲" if details["低基期乖離"][0] == 25 else "動能觀察")
                else:
                    curr_p = row['close']
                    score, light, target, stop, tag = 0, "⚪ 數據不足", curr_p * 1.08, curr_p * 0.93, "無資料"
            except Exception:
                curr_p = row['close']
                score, light, target, stop, tag = 0, "⚪ 讀取異常", curr_p * 1.08, curr_p * 0.93, "異常"

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
            progress_bar.progress((idx + 1) / len(candidates))

        df_res = pd.DataFrame(ranking_list).sort_values(by="綜合總分", ascending=False).reset_index(drop=True)
        st.success(f"✅ 掃描完成！共評估 {len(df_res)} 檔活躍股，以下為排行榜：")
        st.dataframe(df_res, use_container_width=True)

# ==================== 分頁二：個股搜尋 ＆ 法人產業估值診斷 ====================
with tab2:
    st.subheader("🔍 個股深度診斷 ＆ 法人產業估值模型")
    target_stock = st.text_input("請輸入台股代號（例：3617, 2486, 2356, 2303, 6278）：", value="3617")

    if target_stock:
        ticker_obj, hist = get_stock_data(target_stock)
        
        if not hist.empty and len(hist) >= 60:
            hist = calculate_indicators(hist)
            info = ticker_obj.info
            s_name = name_map.get(target_stock, "")
            s_ind = industry_map.get(target_stock, "其他板塊")
            
            # 執行量化評分
            score, light, tech_target, tech_stop, details = evaluate_single_stock(ticker_obj, hist)
            
            latest_price = round(hist['Close'].iloc[-1], 2)
            prev_price = round(hist['Close'].iloc[-2], 2)
            price_change = round(((latest_price - prev_price) / prev_price) * 100, 2)
            
            # 基本面數據
            gm = round(info.get('grossMargins', 0) * 100, 2) if info.get('grossMargins') else "N/A"
            om = round(info.get('operatingMargins', 0) * 100, 2) if info.get('operatingMargins') else "N/A"
            eps = round(info.get('trailingEps', 0), 2) if info.get('trailingEps') else None
            curr_pe = round(info.get('trailingPE', 0), 1) if info.get('trailingPE') else None
            
            # ----------------- 🎯 法人預期目標價與產業本益比推估 -----------------
            # 1. 抓取法人機構目標價 (Consensus Target)
            analyst_target = info.get('targetMeanPrice')
            analyst_high = info.get('targetHighPrice')
            analyst_low = info.get('targetLowPrice')
            
            # 2. 產業常態 P/E 基準估值推算
            pe_bench = INDUSTRY_PE_BENCHMARK.get(s_ind, INDUSTRY_PE_BENCHMARK["其他板塊"])
            val_low, val_mid, val_high = None, None, None
            if eps and eps > 0:
                val_low = round(eps * pe_bench["low"], 1)
                val_mid = round(eps * pe_bench["mid"], 1)
                val_high = round(eps * pe_bench["high"], 1)

            # 1. 頂部核心卡片
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("綜合量化評分", f"{score} 分", light)
            k2.metric("最新收盤價", f"${latest_price}", f"{price_change}%")
            k3.metric("目前本益比 (P/E)", f"{curr_pe} 倍" if curr_pe else "N/A")
            k4.metric("近四季 EPS", f"{eps} 元" if eps else "無資料")
            k5.metric("產業板塊", s_ind)

            # 2. 🎯 法人目標價 vs 產業本益比估值推估專區
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
                    st.info("法人目前尚無公開共識目標價（多屬中小型股或尚未出具最新報告）。")
                    st.caption("建議參考右側「產業本益比推算」或「技術結構目標價」。")

            with v_col2:
                st.markdown(f"#### 🏭 產業 P/E 估值推算 ({s_ind})")
                if val_mid:
                    upside_pe = round(((val_mid - latest_price) / latest_price) * 100, 1)
                    st.metric(f"產業合理目標價 ({pe_bench['mid']}X)", f"${val_mid}", f"潛在空間: {upside_pe}%")
                    st.caption(f"估值河流區間：保守 **${val_low}** ({pe_bench['low']}X) ～ 樂觀 **${val_high}** ({pe_bench['high']}X)")
                else:
                    st.info("因近四季 EPS 為負或無資料，無法進行本益比推算。")

            with v_col3:
                st.markdown("#### 📐 技術線型結構點位")
                upside_tech = round(((tech_target - latest_price) / latest_price) * 100, 1)
                st.metric("波段技術壓力目標價", f"${tech_target}", f"潛在空間: {upside_tech}%")
                st.caption(f"關鍵停損防守價：**${tech_stop}** (跌破代表起漲結構破壞)")

            # 3. 獲利基本面輔助列
            st.markdown("---")
            f1, f2, f3 = st.columns(3)
            f1.caption(f"📊 最新毛利率：**{gm}%**" if gm != "N/A" else "📊 最新毛利率：無資料")
            f2.caption(f"🏢 營業利益率：**{om}%**" if om != "N/A" else "🏢 營業利益率：無資料")
            f3.caption(f"💡 估值結論：目前 P/E **{curr_pe} 倍** 對比產業中位 **{pe_bench['mid']} 倍**，評價" + 
                       ("【相對便宜】" if (curr_pe and curr_pe < pe_bench['low']) else ("【位處合理區間】" if (curr_pe and curr_pe <= pe_bench['high']) else "【偏向高估/已反應成長】")))

            # 4. 得分解剖與條件判定卡片
            with st.expander(f"📋 點擊查看【{target_stock} {s_name} 低基期起漲得分解剖】", expanded=False):
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
                        st.markdown(f"👉 **觸發情況**：{reason_text}")
                    st.divider()

            # 5. 互動日K線與均線
            st.subheader(f"📈 {target_stock} {s_name} 技術線型 (日K / MA5 / MA10 / MA20 / MA60)")
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=hist.index, open=hist['Open'], high=hist['High'],
                low=hist['Low'], close=hist['Close'], name='日K線'
            ))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA5'], line=dict(color='orange', width=1.2), name='5MA (週線)'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA10'], line=dict(color='purple', width=1.2), name='10MA'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA20'], line=dict(color='blue', width=2), name='20MA (月線)'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60'], line=dict(color='green', width=1.5), name='60MA (季線)'))
            fig.update_layout(xaxis_rangeslider_visible=False, height=450, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)

            # 6. 動能指標 (KD & RSI)
            c_kd, c_rsi = st.columns(2)
            with c_kd:
                st.write("**⚡ KD 指標走勢 (9, 3, 3)**")
                fig_kd = go.Figure()
                fig_kd.add_trace(go.Scatter(x=hist.index, y=hist['K'], line=dict(color='red', width=1.5), name='K值'))
                fig_kd.add_trace(go.Scatter(x=hist.index, y=hist['D'], line=dict(color='green', width=1.5), name='D值'))
                fig_kd.add_hline(y=80, line_dash="dash", line_color="gray")
                fig_kd.add_hline(y=20, line_dash="dash", line_color="gray")
                fig_kd.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10), yaxis_range=[0, 100])
                st.plotly_chart(fig_kd, use_container_width=True)
            
            with c_rsi:
                st.write("**📊 RSI 強弱指標 (14日)**")
                fig_rsi = go.Figure()
                fig_rsi.add_trace(go.Scatter(x=hist.index, y=hist['RSI'], line=dict(color='blue', width=1.5), name='RSI'))
                fig_rsi.add_hline(y=70, line_dash="dash", line_color="red")
                fig_rsi.add_hline(y=30, line_dash="dash", line_color="green")
                fig_rsi.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10), yaxis_range=[0, 100])
                st.plotly_chart(fig_rsi, use_container_width=True)
        else:
            st.error("查無此代號技術數據或歷史長度不足 60 天，請確認代號是否正確。")
