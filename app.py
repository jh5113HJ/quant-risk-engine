import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import os
from datetime import datetime

# --- 1. 界面与样式配置 ---
st.set_page_config(page_title="极速量化风控终端 v8.2", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #E0E0E0; }
    [data-testid="stMetricValue"] { color: #00FF41 !important; text-shadow: 0 0 5px #00FF41; }
    .stAlert { background-color: #1E1E1E; border: 1px solid #3B82F6; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 数据库核心逻辑 ---
def get_conn():
    return st.connection("gsheets", type=GSheetsConnection)

def load_logs():
    try:
        conn = get_conn()
        target_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        df = conn.read(spreadsheet=target_url, ttl=0)
        return df.dropna(how="all") if df is not None else pd.DataFrame()
    except: return pd.DataFrame()

def save_log(new_data_dict):
    try:
        conn = get_conn()
        target_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        existing_data = load_logs()
        new_df = pd.DataFrame([new_data_dict])
        updated_data = pd.concat([existing_data, new_df], ignore_index=True) if not existing_data.empty else new_df
        conn.update(spreadsheet=target_url, data=updated_data)
        return True
    except: return False

# --- 3. 主逻辑推演 ---
def main():
    st.title("⚡ 极速量化风控终端 (资本效率版 v8.2)")
    
    with st.sidebar:
        st.header("⚙️ 账户基准")
        balance = st.number_input("账户总资产 (USDT)", min_value=0.1, value=35000.0, step=100.0)
        fixed_risk = st.number_input("单笔固定止损金额 (Risk)", min_value=0.0, value=35.0, step=5.0)
        
        st.divider()
        st.header("🔧 杠杆设置")
        # 核心改动：由你决定在交易所开几倍杠杆
        exchange_leverage = st.slider("交易所执行杠杆 (Exchange Leverage)", 1, 200, 20)
        st.info(f"💡 你的风险系数: {(fixed_risk/balance)*100:.3f}%")

    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📊 仓位与本金测算")
        symbol = st.text_input("交易标的", "BTC/USDT")
        
        c1, c2, c3 = st.columns(3)
        entry_price = c1.number_input("入场价", value=60000.0)
        stop_loss = c2.number_input("止损价", value=59500.0)
        take_profit = c3.number_input("止盈价", value=62000.0)

        if entry_price != stop_loss:
            # 1. 计算名义仓位 (Position Value)
            sl_pct = abs(entry_price - stop_loss) / entry_price
            pos_value = fixed_risk / sl_pct
            
            # 2. 计算投入成本 (Actual USDT Cost)
            # 公式：成本 = 名义价值 / 交易所杠杆
            actual_cost = pos_value / exchange_leverage
            
            # 3. 计算账户杠杆 (Effective Leverage)
            # 衡量你账户整体风险的指标
            effective_leverage = pos_value / balance
            
            # 4. 盈亏比
            rr_ratio = abs(take_profit - entry_price) / abs(entry_price - stop_loss) if entry_price != stop_loss else 0

            # 5. 结果矩阵
            st.divider()
            m1, m2 = st.columns(2)
            with m1:
                st.metric("名义价值 (Position Value)", f"{pos_value:.2f} U")
                # 这里显示你真正要付出的钱
                st.metric("实际投入本金 (USDT Cost)", f"{actual_cost:.2f} U")
            with m2:
                st.metric("账户杠杆 (Real Leverage)", f"{effective_leverage:.2f} x")
                st.metric("盈亏比 (RR Ratio)", f"{rr_ratio:.2f}")

            # 安全边际检测
            if actual_cost > balance:
                st.error("❌ 警告：保证金不足！请调高交易所杠杆或减少风险金额。")
            elif effective_leverage > 200:
                st.error("❌ 警告：账户杠杆超过 200x，极易爆仓！")

            if st.button("🚀 确认记录并同步云端"):
                log_entry = {
                    "时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "标的": symbol,
                    "入场/止损/止盈": f"{entry_price}/{stop_loss}/{take_profit}",
                    "实际投入成本": round(actual_cost, 2),
                    "交易所杠杆": f"{exchange_leverage}x",
                    "名义价值": round(pos_value, 2),
                    "账户真实杠杆": round(effective_leverage, 2)
                }
                if save_log(log_entry):
                    st.success("数据已同步至 Google Sheets")
                    st.balloons()

    with col2:
        st.subheader("📜 历史风控记录")
        logs = load_logs()
        if not logs.empty:
            st.dataframe(logs.sort_index(ascending=False), use_container_width=True)

if __name__ == "__main__":
    main()