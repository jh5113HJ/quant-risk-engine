import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import os
import math
from datetime import datetime

# --- 1. 配置界面 ---
st.set_page_config(page_title="量化交易风控引擎", layout="wide")

# 注入暗黑硬核 CSS
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #E0E0E0; }
    [data-testid="stMetricValue"] { color: #00FF41 !important; text-shadow: 0 0 5px #00FF41; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 数据库核心逻辑 (已修复 UnsupportedOperationError) ---

def get_conn():
    """建立并返回数据库连接"""
    return st.connection("gsheets", type=GSheetsConnection)

def load_logs():
    """从云端表格读取数据"""
    try:
        conn = get_conn()
        # 显式传递 URL 确保连接稳定
        target_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        df = conn.read(spreadsheet=target_url, ttl=0) # ttl=0 确保实时读取不使用缓存
        return df.dropna(how="all") if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def save_log(new_data_dict):
    """写入云端表格 (强力注入模式)"""
    try:
        conn = get_conn()
        target_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        
        # 1. 获取现有数据
        existing_data = load_logs()
        
        # 2. 合并新数据
        new_df = pd.DataFrame([new_data_dict])
        if existing_data.empty:
            updated_data = new_df
        else:
            updated_data = pd.concat([existing_data, new_df], ignore_index=True)
        
        # 3. 核心修复：显式指定 spreadsheet 参数进行覆写
        conn.update(
            spreadsheet=target_url, 
            data=updated_data
        )
        return True
    except Exception as e:
        st.error(f"写入失败详情: {e}")
        return False

# --- 3. 交互界面逻辑 ---
def main():
    st.title("🛡️ A-Share 量化交易风控引擎 v7.0")
    
    with st.sidebar:
        st.header("账户参数")
        balance = st.number_input("当前账户总资产 (USDT/CNY)", min_value=1.0, value=10000.0)
        risk_pct = st.slider("单笔最高亏损风险 (%)", 0.5, 5.0, 2.0)
        max_risk_money = balance * (risk_pct / 100)
        st.info(f"💡 允许最大亏损: {max_risk_money:.2f}")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("开仓测算")
        symbol = st.text_input("交易标的 (如 BTC/SOL)", "BTC")
        entry_price = st.number_input("拟入场价格", value=60000.0)
        stop_loss = st.number_input("止损触发价格", value=59000.0)
        
        if entry_price != stop_loss:
            loss_dist = abs(entry_price - stop_loss)
            loss_ratio = (loss_dist / entry_price) * 100
            # 计算仓位：金额 = 允许亏损 / 止损百分比
            pos_size = max_risk_money / (loss_ratio / 100)
            leverage = pos_size / balance
            
            st.metric("推荐仓位金额", f"{pos_size:.2f}")
            st.metric("推荐理论杠杆", f"{leverage:.2f}x")

            if st.button("⚡ 执行风控推导并记录"):
                log_data = {
                    "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "标的": symbol,
                    "账户总额": balance,
                    "风险比例%": risk_pct,
                    "入场价": entry_price,
                    "止损价": stop_loss,
                    "建议仓位": round(pos_size, 2),
                    "建议杠杆": round(leverage, 2)
                }
                if save_log(log_data):
                    st.success("✅ 交易记录已实时同步至 Google Sheets 数据库")
                    st.balloons()

    with col2:
        st.subheader("历史风险日志 (云端实时)")
        history_df = load_logs()
        if not history_df.empty:
            st.dataframe(history_df.sort_index(ascending=False), use_container_width=True)
        else:
            st.warning("目前云端数据库尚无记录")

if __name__ == "__main__":
    main()