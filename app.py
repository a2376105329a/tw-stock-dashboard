import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests, io

st.set_page_config(page_title="台股量化戰情室：低基期起漲偵測系統", layout="wide")
st.title("🎯 台股量化作戰室：低基期起漲 ＆ 型態突破量化看板")

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
    """偵測六大起漲突破型態"""
    if len(df) < 60: return "", 0, 0
    close = df['Close']
    curr_price = close.iloc[-1]
    ma20 = df['MA20'].iloc[-1]
    high, low = df['High'], df['Low']
    
    if curr_price < ma20:
        return "", 0, 0

    pattern = ""
    struct_stop_loss = ma20
    
    # 1. 均線糾結突破 (低基期經典起漲)
    ma_prev = [df['MA5'].iloc[-2], df['MA10'].iloc[-2], df['MA20'].iloc[-2], df['MA60'].iloc[-2]]
    if (max(ma_prev) - min(ma_prev)) / min(ma_prev) <= 0.03 and curr_price > max(ma_prev):
        pattern = "【均線糾結突破】"
        struct_stop_loss = min(ma_prev)
    # 2. 箱型整理突破
    elif (high.iloc[-31:-1].max() - low.iloc[-31:-1].min()) / low.iloc[-31:-1].min() <= 0.15 and curr_price > high.iloc[-31:-1].max():
        pattern = "【箱型整理突破】"
        struct_stop_loss = (high.iloc[-31:-1].max() + low.iloc[-31:-1].min()) / 2
    # 3. 碗型 VCP 壓縮收斂突破
    elif (high.iloc[-21:-1].max() - low.iloc[-21:-1].min()) < (high.iloc[-41:-21].max() - low.iloc[-41:-21].min()) * 0.7 and curr_price > high.iloc[-21:-1].max():
        pattern = "【碗型VCP突破】"
        struct_stop_loss = low.iloc[-21:-1].min()
    # 4. 階梯 N 字續強突破
    elif low.iloc[-21:-1].min() > low.iloc[-41:-21].min() and curr_price > high.iloc[-21:-1].max():
        pattern = "【階梯N字突破】"
        struct_stop_loss = low.iloc[-21:-1].min()
    # 5. 破底翻大底 (洗盤洗乾淨起漲)
    elif (low.iloc[-15:-3] < low.iloc[-60:-15].min()).any() and (close.iloc[-3:-1] > low.iloc[-60:-15].min()).any() and curr_price > high.iloc[-15:-1].max():
        pattern = "【破底翻大底】"
        struct_stop_loss = low.iloc[-15:-1].min()
    # 6. KD 新金叉 / 多頭續強
    elif df['K'].iloc[-1] > df['D'].iloc[-1] and df['K'].iloc[-1] > df['K'].iloc[-2] and df['RSI'].iloc[-1] > 50:
        pattern = "【新金叉發動】" if df['K'].iloc[-2] <= df['D'].iloc[-2] else "【多頭續強】"
        struct_stop_loss = max(low.iloc[-1], ma20)

    if pattern != "":
        pressure = high.iloc[-20:].max()
        target = curr_price * 1.1 if curr_price >= pressure * 0.98 else pressure
        return pattern, target, struct_stop_loss

    return "", 0, 0

def get_stock_data(symbol):
    for suffix in [".TW", ".TWO"]:
        ticker = yf.Ticker(f"{symbol}{suffix}")
        hist = ticker.history(period="6mo")
        if not hist.empty:
            if isinstance(hist.columns, pd.MultiIndex): hist.columns = hist.columns.get_level_values(0)
            return ticker, hist
    return None, pd.DataFrame()

# 簡潔雙分頁
tab1, tab2 = st.tabs(["🚀 低基期起漲量化掃描榜", "🔍 個股深度多維度診斷"])

# ==================== 分頁一：起漲掃描榜 ====================
with tab1:
    st.subheader("🎯 低基期起漲 ＆ 爆量突破排行榜 (滿分 100 分 ＋ 型態加分)")
    st.caption("核心打分邏輯：低基期乖離控制 (防追高25分) ＋ 低檔KD金叉放量 (主力表態25分) ＋ 高毛利定價權 (25分) ＋ 本業獲利 (25分) ＋ 破底翻/均線糾結加分")
    
    col_ctrl1, col_ctrl2 = st.columns([1, 2])
    with col_ctrl1:
        min_vol_input = st.slider("最低成交量門檻 (張)", min_value=500, max_value=5000, value=1000, step=100)
        scan_limit = st.slider("掃描候選池數量上限", min_value=15, max_value=60, value=30, step=5)
    
    if st.button("🔥 立即執行低基期起漲掃描"):
        market_stocks = get_active_market_stocks()
        candidates = market_stocks[market_stocks['volume'] >= min_vol_input].sort_values(by="volume", ascending=False).head(scan_limit)
        
        st.write(f"已從市場鎖定 **{len(candidates)} 檔** 動能標的進行【低基期起漲條件】量化計算...")
        progress_bar = st.progress(0)
        ranking_list = []
        
        for idx, (_, row) in enumerate(candidates.iterrows()):
            sid = str(row['id'])
            sname = name_map.get(sid, str(row['name']))
            sind = industry_map.get(sid, "其他板塊")
            score = 0
            features = []
            
            try:
                ticker, hist = get_stock_data(sid)
                if not hist.empty and len(hist) >= 60:
                    hist = calculate_indicators(hist)
                    curr_p = hist['Close'].iloc[-1]
                    ma20 = hist['MA20'].iloc[-1]
                    k_val = hist['K'].iloc[-1]
                    d_val = hist['D'].iloc[-1]
                    vol_today = hist['Volume'].iloc[-1]
                    vol_ma20 = hist['Volume'].rolling(20).mean().iloc[-1]
                    
                    # 1. 低基期乖離控制 (防追高，站上月線且距離月線不超過 8%)
                    bias_ma20 = (curr_p - ma20) / ma20
                    if 0 < bias_ma20 <= 0.08:
                        score += 25
                        features.append("低基期起漲(近月線)")
                    elif bias_ma20 > 0.08:
                        score += 10
                        features.append("已脫離成本區(注意乖離)")
                    
                    # 2. 量能點火與 KD 低檔金叉 (避開高檔假金叉)
                    is_vol_surge = vol_today >= (vol_ma20 * 1.3)
                    if k_val > d_val and k_val < 65:
                        if is_vol_surge:
                            score += 25
                            features.append("帶量低檔金叉(主力表態)")
                        else:
                            score += 15
                            features.append("低檔金叉(量能尚溫)")
                    elif k_val > d_val:
                        score += 10
                        features.append("KD高檔續強")
                    
                    # 3. 基本面毛利指標
                    info = ticker.info
                    gm = info.get('grossMargins', 0)
                    om = info.get('operatingMargins', 0)
                    
                    if gm and gm >= 0.30:
                        score += 25
                        features.append(f"高毛利({round(gm*100, 1)}%)")
                    elif gm and gm >= 0.15:
                        score += 15
                        features.append(f"穩健毛利({round(gm*100, 1)}%)")

                    # 4. 本業營益率
                    if om and om > 0.10:
                        score += 25
                        features.append("營益率優良")
                    elif om and om > 0:
                        score += 15
                        features.append("本業維持獲利")
                        
                    # 5. 起漲型態加分 (Bonus)
                    pat, target, stop = detect_pattern(hist)
                    if "均線糾結" in pat or "破底翻" in pat:
                        score += 15
                        features.append(f"🔥極佳起漲型態:{pat}(+15分)")
                    elif pat != "":
                        score += 10
                        features.append(f"🔥突破型態:{pat}(+10分)")
                    else:
                        target = curr_p * 1.08
                        stop = ma20
                else:
                    features.append("數據獲取中")
                    curr_p = row['close']
                    target = curr_p * 1.08
                    stop = curr_p * 0.93
            except Exception:
                features.append("讀取異常")
                curr_p = row['close']
                target = curr_p * 1.08
                stop = curr_p * 0.93

            light = "🟢 超級起漲" if score >= 85 else ("🟡 潛力加溫" if score >= 65 else "⚪ 區間觀望")
            ranking_list.append({
                "代號": sid,
                "名稱": sname,
                "產業類別": sind,
                "綜合評分": score,
                "狀態燈號": light,
                "目前現價": round(curr_p, 2),
                "短線目標價": round(target, 2),
                "結構防守價": round(stop, 2),
                "觸發特徵": "、".join(features)
            })
            progress_bar.progress((idx + 1) / len(candidates))

        df_rank = pd.DataFrame(ranking_list).sort_values(by="綜合評分", ascending=False).reset_index(drop=True)
        st.success("✅ 掃描完成！以下為符合低基期起漲條件的領先個股：")
        st.dataframe(df_rank, use_container_width=True)

# ==================== 分頁二：個股深度診斷 ====================
with tab2:
    target_stock = st.text_input("輸入要檢測的個股代號（例：3617, 2486, 2356）：", value="3617")

    if target_stock:
        ticker_obj, hist = get_stock_data(target_stock)
        
        if not hist.empty:
            hist = calculate_indicators(hist)
            info = ticker_obj.info
            
            latest_price = round(hist['Close'].iloc[-1], 2)
            prev_price = round(hist['Close'].iloc[-2], 2)
            price_change = round(((latest_price - prev_price) / prev_price) * 100, 2)
            
            gm = round(info.get('grossMargins', 0) * 100, 2) if info.get('grossMargins') else "N/A"
            om = round(info.get('operatingMargins', 0) * 100, 2) if info.get('operatingMargins') else "N/A"
            eps = round(info.get('trailingEps', 0), 2) if info.get('trailingEps') else "N/A"

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("最新收盤價", f"${latest_price}", f"{price_change}%")
            k2.metric("最新毛利率", f"{gm}%" if gm != "N/A" else "無資料")
            k3.metric("營業利益率", f"{om}%" if om != "N/A" else "無資料")
            k4.metric("每股盈餘 (EPS)", f"{eps} 元" if eps != "N/A" else "無資料")

            curr_pat, pat_target, pat_stop = detect_pattern(hist)
            if curr_pat:
                st.success(f"🔥 今日技術面型態判定：**{curr_pat}** ｜ 短線目標價：**${round(pat_target, 1)}** ｜ 結構防守價：**${round(pat_stop, 1)}**")

            st.subheader(f"📈 {target_stock} {name_map.get(target_stock, '')} 技術線型 (日K / MA5 / MA10 / MA20 / MA60)")
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
            st.error("查無此代號技術數據，請確認代號是否正確。")
