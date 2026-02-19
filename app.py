import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import os
from datetime import datetime

# --- 1. 界面与样式配置 ---
st.set_page_config(page_title="极速量化风控引擎 v8.0", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #E0E0E0; }
    [data-testid="stMetricValue"] { color: #00FF41 !important; text-shadow: 0 0 5px #00FF41; }
    /* 警告样式优化 */
    .stAlert { background-color: #1E1E1E; border: 1px solid #FF4B4B; }
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
    st.title("⚡ 极速量化风控终端 (200x 限制版)")
    
    with st.sidebar:
        st.header("⚙️ 账户基准")
        balance = st.number_input("当前账户净值 (Principal)", min_value=0.1, value=10000.0, step=100.0)
        # 核心改动：主动输入固定止损金额
        fixed_risk = st.number_input("单笔固定止损金额 (Risk Amount)", min_value=0.0, value=200.0, step=10.0)
        st.caption(f"当前风险占总仓位: {(fixed_risk/balance)*100:.2f}%")
        st.divider()
        st.markdown("### 杠杆天花板: **200.00x**")

    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📊 交易头寸测算")
        symbol = st.text_input("交易标的", "BTC/USDT")
        
        c1, c2, c3 = st.columns(3)
        entry_price = c1.number_input("入场价", value=60000.0)
        stop_loss = c2.number_input("止损价", value=59500.0)
        take_profit = c3.number_input("止盈价", value=62000.0)

        if entry_price != stop_loss:
            # 止损百分比
            sl_pct = abs(entry_price - stop_loss) / entry_price
            # 盈亏比计算
            tp_dist = abs(take_profit - entry_price)
            sl_dist = abs(entry_price - stop_loss)
            rr_ratio = tp_dist / sl_dist if sl_dist != 0 else 0
            
            # 计算理论仓位
            raw_pos_size = fixed_risk / sl_pct
            raw_leverage = raw_pos_size / balance
            
            # --- 200x 强制风控逻辑 ---
            final_leverage = raw_leverage
            is_capped = False
            if raw_leverage > 200:
                final_leverage = 200.0
                final_pos_size = balance * 200
                is_capped = True
            else:
                final_pos_size = raw_pos_size

            # 结果显示
            m1, m2, m3 = st.columns(3)
            m1.metric("建议仓位", f"{final_pos_size:.2f}")
            m2.metric("执行杠杆", f"{final_leverage:.2f}x")
            m3.metric("盈亏比 (RR)", f"{rr_ratio:.2f}")

            if is_capped:
                st.warning(f"⚠️ 警告：所需杠杆 ({raw_leverage:.2f}x) 超过系统上限！已强制锁定为 200x。实际亏损将小于设定金额。")

            if st.button("🚀 确认交易并同步云端"):
                log_entry = {
                    "时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "标的": symbol,
                    "账户余额": balance,
                    "固定止损额": fixed_risk,
                    "入场价": entry_price,
                    "止损价": stop_loss,
                    "止盈价": take_profit,
                    "盈亏比": round(rr_ratio, 2),
                    "执行杠杆": round(final_leverage, 2),
                    "最终仓位": round(final_pos_size, 2)
                }
                if save_log(log_entry):
                    st.success("数据已穿透至 Google Sheets")
                    st.balloons()

    with col2:
        st.subheader("📜 历史风控档案")
        logs = load_logs()
        if not logs.empty:
            st.dataframe(logs.sort_index(ascending=False), use_container_width=True)
        else:
            st.info("等待首笔数据写入...")

if __name__ == "__main__":
    main()