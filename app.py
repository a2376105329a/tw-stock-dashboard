import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests

st.set_page_config(page_title="台股全方位量化戰情室", layout="wide")
st.title("📊 台股全市場量化戰情室：全市場掃描 ＆ 深度診斷")

@st.cache_data(ttl=3600)
def get_all_taiwan_stocks():
    """從證交所開放平台取得全體上市股票即時行情清單"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            df = pd.DataFrame(data)
            df = df.rename(columns={
                'Code': 'id',
                'Name': 'name',
                'ClosingPrice': 'close',
                'Change': 'change',
                'TradeVolume': 'volume'
            })
            # 排除權證、存託憑證等非一般個股 (代號長度大於4碼)
            df = df[df['id'].str.len() == 4]
            df['close'] = pd.to_numeric(df['close'].str.replace(',', ''), errors='coerce')
            df['volume'] = pd.to_numeric(df['volume'].str.replace(',', ''), errors='coerce') / 1000  # 轉為張數
            df = df.dropna(subset=['close', 'volume'])
            return df
    except Exception:
        pass
    
    # 備援基礎名單 (若遇證交所伺服器維護時不致崩潰)
    return pd.DataFrame([
        {"id": "3617", "name": "碩天", "volume": 1500, "close": 350},
        {"id": "2486", "name": "一詮", "volume": 3200, "close": 150},
        {"id": "6642", "name": "富致", "volume": 800, "close": 75},
        {"id": "2356", "name": "英業達", "volume": 12000, "close": 50},
        {"id": "8234", "name": "新漢", "volume": 2100, "close": 70},
        {"id": "6278", "name": "台表科", "volume": 2500, "close": 115},
    ])

def calculate_kd(df, n=9):
    low_list = df['Low'].rolling(window=n, min_periods=n).min()
    high_list = df['High'].rolling(window=n, min_periods=n).max()
    rsv = (df['Close'] - low_list) / (high_list - low_list) * 100
    rsv = rsv.fillna(50)
    
    k, d = [50.0], [50.0]
    for r in rsv:
        k_val = (2/3) * k[-1] + (1/3) * r
        d_val = (2/3) * d[-1] + (1/3) * k_val
        k.append(k_val)
        d.append(d_val)
    df['K'] = k[1:]
    df['D'] = d[1:]
    return df

def get_stock_data(symbol):
    for suffix in [".TW", ".TWO"]:
        ticker = yf.Ticker(f"{symbol}{suffix}")
        hist = ticker.history(period="6mo")
        if not hist.empty:
            return ticker, hist
    return None, pd.DataFrame()

tab1, tab2 = st.tabs(["🚀 全市場自動掃描排行榜", "🔍 個股深度診斷儀表板"])

# ==================== 分頁一：全市場自動掃描 ====================
with tab1:
    st.subheader("全市場即時動能與獲利評分排行榜 (滿分 100 分)")
    st.caption("規則：從全台股中自動篩選【成交量充沛且具攻擊動能】之標的，進行均線、KD、毛利率、營益率四大維度交叉評分。")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        min_vol = st.slider("最低成交量門檻 (張)", min_value=300, max_value=5000, value=1000, step=100)
        scan_limit = st.slider("掃描候選池數量上限", min_value=20, max_value=100, value=40, step=10)
    
    start_scan = st.button("🔥 開始全市場掃描打分")
    
    if start_scan:
        all_stocks = get_all_taiwan_stocks()
        # 篩選活躍熱門股
        candidates = all_stocks[all_stocks['volume'] >= min_vol].sort_values(by="volume", ascending=False).head(scan_limit)
        
        st.write(f"已從全市場鎖定 **{len(candidates)} 檔** 高流動性核心標的進行深度量化運算...")
        progress_bar = st.progress(0)
        scores = []
        
        for idx, (_, row) in enumerate(candidates.iterrows()):
            sid = str(row['id'])
            sname = str(row['name'])
            score = 0
            signals = []
            
            try:
                ticker, hist = get_stock_data(sid)
                if not hist.empty and len(hist) >= 30:
                    hist = calculate_kd(hist)
                    latest_close = hist['Close'].iloc[-1]
                    ma20 = hist['Close'].rolling(20).mean().iloc[-1]
                    latest_k = hist['K'].iloc[-1]
                    latest_d = hist['D'].iloc[-1]
                    
                    # 1. 均線突破
                    if latest_close > ma20:
                        score += 25
                        signals.append("站上月線")
                    # 2. KD金叉
                    if latest_k > latest_d:
                        score += 25
                        signals.append("KD多頭金叉")

                    # 3. 獲利基本面指標
                    info = ticker.info
                    gross_margin = info.get('grossMargins', 0)
                    operating_margin = info.get('operatingMargins', 0)
                    
                    if gross_margin and gross_margin >= 0.30:
                        score += 25
                        signals.append(f"高毛利({round(gross_margin*100, 1)}%)")
                    elif gross_margin and gross_margin >= 0.15:
                        score += 15
                        signals.append(f"穩健毛利({round(gross_margin*100, 1)}%)")

                    if operating_margin and operating_margin > 0.10:
                        score += 25
                        signals.append("營益率優良")
                    elif operating_margin and operating_margin > 0:
                        score += 15
                        signals.append("本業獲利")
                else:
                    signals.append("資料不足")
            except Exception:
                signals.append("讀取異常")

            light = "🟢 超級主升" if score >= 80 else ("🟡 動能加溫" if score >= 60 else "⚪ 區間觀望")
            scores.append({
                "代號": sid,
                "名稱": sname,
                "綜合評分": score,
                "狀態燈號": light,
                "收盤價": row['close'],
                "今日成交量(張)": int(row['volume']),
                "觸發特徵": "、".join(signals) if signals else "觀望"
            })
            progress_bar.progress((idx + 1) / len(candidates))

        df_rank = pd.DataFrame(scores).sort_values(by="綜合評分", ascending=False).reset_index(drop=True)
        st.success("✅ 全市場掃描完成！以下為前段班強勢名單：")
        st.dataframe(df_rank, use_container_width=True)

# ==================== 分頁二：個股深度診斷 ====================
with tab2:
    target_stock = st.text_input("輸入要深度檢測的個股代號（例：3617, 2486, 2356）：", value="3617")

    if target_stock:
        ticker, hist = get_stock_data(target_stock)
        
        if not hist.empty:
            hist = calculate_kd(hist)
            info = ticker.info
            
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

            st.subheader("📈 技術線型與均線系統 (日K / MA5 / MA20)")
            hist['MA5'] = hist['Close'].rolling(5).mean()
            hist['MA20'] = hist['Close'].rolling(20).mean()

            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=hist.index, open=hist['Open'], high=hist['High'],
                low=hist['Low'], close=hist['Close'], name='日K線'
            ))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA5'], line=dict(color='orange', width=1.5), name='5MA (週線)'))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['MA20'], line=dict(color='blue', width=2), name='20MA (月線)'))
            fig.update_layout(xaxis_rangeslider_visible=False, height=450, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("⚡ KD 動能走勢 (K值 vs D值)")
            fig_kd = go.Figure()
            fig_kd.add_trace(go.Scatter(x=hist.index, y=hist['K'], line=dict(color='red', width=2), name='K值 (快線)'))
            fig_kd.add_trace(go.Scatter(x=hist.index, y=hist['D'], line=dict(color='green', width=2), name='D值 (慢線)'))
            fig_kd.add_hline(y=80, line_dash="dash", line_color="gray")
            fig_kd.add_hline(y=20, line_dash="dash", line_color="gray")
            fig_kd.update_layout(height=250, margin=dict(l=20, r=20, t=20, b=20), yaxis_range=[0, 100])
            st.plotly_chart(fig_kd, use_container_width=True)
        else:
            st.error("查無此代號技術數據，請確認代號是否正確。")
