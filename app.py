import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import os
from datetime import datetime

# --- 1. 界面与样式配置 ---
st.set_page_config(page_title="极速量化风控终端 v8.1", layout="wide")

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
    except:
        return pd.DataFrame()

def save_log(new_data_dict):
    try:
        conn = get_conn()
        target_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        existing_data = load_logs()
        new_df = pd.DataFrame([new_data_dict])
        updated_data = pd.concat([existing_data, new_df], ignore_index=True) if not existing_data.empty else new_df
        conn.update(spreadsheet=target_url, data=updated_data)
        return True
    except Exception as e:
        st.error(f"写入失败: {e}")
        return False

# --- 3. 主逻辑推演 ---
def main():
    st.title("⚡ 极速量化风控终端 (成本优化版)")
    
    with st.sidebar:
        st.header("⚙️ 账户基准")
        balance = st.number_input("账户总资产 (USDT)", min_value=0.1, value=10000.0, step=100.0)
        fixed_risk = st.number_input("单笔固定止损金额 (Risk)", min_value=0.0, value=200.0, step=10.0)
        # 默认最大杠杆限制
        max_lev_limit = 200.0
        st.divider()
        st.info(f"💡 风险/本金比: {(fixed_risk/balance)*100:.2f}%")

    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📊 仓位与成本测算")
        symbol = st.text_input("交易标的", "BTC/USDT")
        
        c1, c2, c3 = st.columns(3)
        entry_price = c1.number_input("入场价", value=60000.0)
        stop_loss = c2.number_input("止损价", value=59500.0)
        take_profit = c3.number_input("止盈价", value=62000.0)

        if entry_price != stop_loss:
            # 1. 计算核心指标
            sl_pct = abs(entry_price - stop_loss) / entry_price
            sl_dist = abs(entry_price - stop_loss)
            tp_dist = abs(take_profit - entry_price)
            rr_ratio = tp_dist / sl_dist if sl_dist != 0 else 0
            
            # 2. 计算名义仓位 (Position Value)
            # 公式：仓位 = 风险金额 / 止损百分比
            theory_pos_size = fixed_risk / sl_pct
            
            # 3. 计算杠杆与成本 (根据 200x 限制)
            theory_leverage = theory_pos_size / balance
            
            if theory_leverage > max_lev_limit:
                final_leverage = max_lev_limit
                final_pos_size = balance * max_lev_limit
                st.warning(f"⚠️ 触发 200x 强限！名义仓位已缩减至 {final_pos_size:.2f}")
            else:
                final_leverage = theory_leverage
                final_pos_size = theory_pos_size

            # 4. 计算投入成本 (Margin/Cost)
            # 公式：成本 = 名义仓位 / 杠杆
            # 在全逐仓模式下，这笔单子在交易所显示的“成本”
            actual_cost = final_pos_size / final_leverage if final_leverage > 0 else 0

            # 5. 结果矩阵
            st.divider()
            m1, m2 = st.columns(2)
            with m1:
                st.metric("名义价值 (Position)", f"{final_pos_size:.2f} U")
                st.metric("投入成本 (Cost/Margin)", f"{actual_cost:.2f} U")
            with m2:
                st.metric("执行杠杆 (Leverage)", f"{final_leverage:.2f} x")
                st.metric("盈亏比 (RR)", f"{rr_ratio:.2f}")

            st.caption(f"注：投入 {actual_cost:.2f} USDT 开启 {final_leverage:.2f}x 杠杆，若止损将亏损约 {fixed_risk:.2f} USDT。")

            if st.button("🚀 确认记录并同步云端"):
                log_entry = {
                    "时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "标的": symbol,
                    "固定风险额": fixed_risk,
                    "入场价": entry_price,
                    "止损价": stop_loss,
                    "止盈价": take_profit,
                    "投入成本(Margin)": round(actual_cost, 2),
                    "执行杠杆": round(final_leverage, 2),
                    "名义价值": round(final_pos_size, 2),
                    "盈亏比": round(rr_ratio, 2)
                }
                if save_log(log_entry):
                    st.success("数据已成功上云")
                    st.balloons()

    with col2:
        st.subheader("📜 历史风控记录")
        logs = load_logs()
        if not logs.empty:
            st.dataframe(logs.sort_index(ascending=False), use_container_width=True)
        else:
            st.info("等待首笔数据写入...")

if __name__ == "__main__":
    main()