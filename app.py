import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta

st.set_page_config(page_title="台股全方位量化戰情室", layout="wide")
st.title("📊 台股量化戰情室：自動評分推薦 ＆ 個股深度診斷")

# 預設自選觀察池
DEFAULT_STOCKS = [
    {"id": "3617", "name": "碩天"},
    {"id": "2486", "name": "一詮"},
    {"id": "6642", "name": "富致"},
    {"id": "2356", "name": "英業達"},
    {"id": "8234", "name": "新漢"},
    {"id": "6278", "name": "台表科"},
    {"id": "6271", "name": "同欣電"},
    {"id": "2369", "name": "菱生"},
    {"id": "6834", "name": "天二科技"},
    {"id": "4931", "name": "新盛力"},
]

def calculate_kd(df, n=9):
    low_list = df['Low'].rolling(window=n, min_periods=n).min()
    high_list = df['High'].rolling(window=n, min_periods=n).max()
    rsv = (df['Close'] - low_list) / (high_list - low_list) * 100
    rsv = rsv.fillna(50)
    
    k = [50.0]
    d = [50.0]
    for r in rsv:
        k_val = (2/3) * k[-1] + (1/3) * r
        d_val = (2/3) * d[-1] + (1/3) * k_val
        k.append(k_val)
        d.append(d_val)
    df['K'] = k[1:]
    df['D'] = d[1:]
    return df

def get_stock_data(symbol):
    ticker_str = f"{symbol}.TW"
    ticker = yf.Ticker(ticker_str)
    hist = ticker.history(period="6mo")
    if hist.empty:
        ticker_str = f"{symbol}.TWO"
        ticker = yf.Ticker(ticker_str)
        hist = ticker.history(period="6mo")
    return ticker, hist

tab1, tab2 = st.tabs(["🚀 全自動多維度評分推薦榜", "🔍 個股深度診斷儀表板"])

# ==================== 分頁一：自動評分推薦榜 ====================
with tab1:
    st.subheader("即時動能與獲利評分排行榜 (滿分 100 分)")
    st.caption("評分權重：技術均線突破 (25分) ＋ KD多頭金叉 (25分) ＋ 獲利毛利率高標 (25分) ＋ 營運利潤健康 (25分)")
    
    if st.button("🔄 立即重新掃描打分"):
        st.rerun()

    progress_bar = st.progress(0)
    scores = []
    
    for idx, s in enumerate(DEFAULT_STOCKS):
        sid = s["id"]
        sname = s["name"]
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
                
                # 1. 技術面：站上月線
                if latest_close > ma20:
                    score += 25
                    signals.append("站上月線(MA20)")
                # 2. 技術面：KD金叉
                if latest_k > latest_d:
                    score += 25
                    signals.append("KD多頭金叉")

                # 財務面指標評估
                info = ticker.info
                gross_margin = info.get('grossMargins', 0)
                operating_margin = info.get('operatingMargins', 0)
                
                if gross_margin and gross_margin >= 0.30:
                    score += 25
                    signals.append(f"高毛利率({round(gross_margin*100, 1)}%)")
                elif gross_margin and gross_margin >= 0.15:
                    score += 15
                    signals.append(f"穩健毛利({round(gross_margin*100, 1)}%)")

                if operating_margin and operating_margin > 0.10:
                    score += 25
                    signals.append("營益率優異(>10%)")
                elif operating_margin and operating_margin > 0:
                    score += 15
                    signals.append("本業維持獲利")
            else:
                signals.append("數據獲取不足")
        except Exception:
            signals.append("讀取異常")

        light = "🟢 超級主升" if score >= 80 else ("🟡 動能加溫" if score >= 60 else "⚪ 區間觀望")
        scores.append({
            "代號": sid,
            "名稱": sname,
            "綜合評分": score,
            "狀態燈號": light,
            "觸發核心特徵": "、".join(signals) if signals else "暫無明確訊號"
        })
        progress_bar.progress((idx + 1) / len(DEFAULT_STOCKS))

    df_score = pd.DataFrame(scores).sort_values(by="綜合評分", ascending=False).reset_index(drop=True)
    st.dataframe(df_score, use_container_width=True)

# ==================== 分頁二：個股深度儀表板 ====================
with tab2:
    col_input, _ = st.columns([1, 2])
    with col_input:
        target_stock = st.text_input("輸入個股代號查看完整數據（例：3617, 2486, 2356）：", value="3617")

    if target_stock:
        ticker, hist = get_stock_data(target_stock)
        
        if not hist.empty:
            hist = calculate_kd(hist)
            info = ticker.info
            
            # KPI 卡片層
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

            # K線與技術圖表
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

            # KD 指標走勢
            st.subheader("⚡ KD 動能走勢 (K值 vs D值)")
            fig_kd = go.Figure()
            fig_kd.add_trace(go.Scatter(x=hist.index, y=hist['K'], line=dict(color='red', width=2), name='K值 (快線)'))
            fig_kd.add_trace(go.Scatter(x=hist.index, y=hist['D'], line=dict(color='green', width=2), name='D值 (慢線)'))
            fig_kd.add_hline(y=80, line_dash="dash", line_color="gray")
            fig_kd.add_hline(y=20, line_dash="dash", line_color="gray")
            fig_kd.update_layout(height=250, margin=dict(l=20, r=20, t=20, b=20), yaxis_range=[0, 100])
            st.plotly_chart(fig_kd, use_container_width=True)
            
            st.info("💡 操盤錦囊：K值 由下往上穿過 D值 呈現黃金交叉，且股價站穩 20MA 時，代表多頭動能轉強。")
        else:
            st.error("查無此代號技術數據，請確認代號是否正確。")
