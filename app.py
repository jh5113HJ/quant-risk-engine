import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import os
from datetime import datetime

# --- 1. 工业级界面配置 (保留原有暗黑风格) ---
st.set_page_config(page_title="量化风控引擎 v7.5", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #E0E0E0; }
    [data-testid="stMetricValue"] { 
        font-size: 1.8rem !important;
        color: #00FF41 !important; 
        text-shadow: 0 0 5px #00FF41; 
    }
    .stMetric label { color: #A0AEC0 !important; font-weight: bold; }
    header, #MainMenu, footer { visibility: hidden; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 数据库连接逻辑 (保留原有功能并修复报错) ---

def get_db_connection():
    """建立数据库连接"""
    return st.connection("gsheets", type=GSheetsConnection)

def load_data():
    """读取云端历史日志"""
    try:
        conn = get_db_connection()
        # 显式从 secrets 获取 URL 解决 UnsupportedOperationError
        target_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        df = conn.read(spreadsheet=target_url, ttl=0)
        return df.dropna(how="all") if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def save_to_db(new_record):
    """安全写入单条记录"""
    try:
        conn = get_db_connection()
        target_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        
        # 1. 预读取现有数据
        history = load_data()
        
        # 2. 合并新记录
        new_row = pd.DataFrame([new_record])
        updated_df = pd.concat([history, new_row], ignore_index=True) if not history.empty else new_row
        
        # 3. 显式指定 spreadsheet 参数进行覆写 (物理修复关键点)
        conn.update(spreadsheet=target_url, data=updated_df)
        return True
    except Exception as e:
        st.error(f"数据库写入拦截: {e}")
        return False

# --- 3. 核心风控交互界面 (保留原有逻辑) ---

def main():
    st.title("🛡️ 量化风控交易终端 (Pro Cloud)")
    
    # 侧边栏：资产配置
    with st.sidebar:
        st.header("账户全局参数")
        balance = st.number_input("账户总资产 (Total Equity)", min_value=0.0, value=10000.0, step=100.0)
        risk_pct = st.slider("单笔风险暴露 (%)", 0.5, 5.0, 2.0, help="每笔交易亏损占总资产的最大百分比")
        
        # 第一性原理公式展示
        max_loss = balance * (risk_pct / 100)
        st.info(f"💡 允许最大亏损金额: {max_loss:.2f}")

    # 主界面：两栏布局
    left_col, right_col = st.columns([1, 1.2])

    with left_col:
        st.subheader("📡 实时开仓推演")
        symbol = st.text_input("交易标的", value="BTC/USDT")
        
        # 开仓参数输入
        price_col1, price_col2 = st.columns(2)
        with price_col1:
            entry = st.number_input("入场价", value=60000.0)
        with price_col2:
            stop_loss = st.number_input("止损价", value=59000.0)

        # 核心逻辑计算
        if entry != stop_loss:
            loss_dist = abs(entry - stop_loss)
            loss_pct = (loss_dist / entry)
            
            # 计算推荐仓位 (不包含杠杆前的名义价值)
            pos_size = max_loss / loss_pct
            # 计算所需杠杆
            theory_lev = pos_size / balance
            
            # UI 指标展示 (保留原有美化风格)
            m1, m2 = st.columns(2)
            m1.metric("建议仓位规模", f"{pos_size:.2f}")
            m2.metric("理论参考杠杆", f"{theory_lev:.2f}x")

            if st.button("⚡ 执行风控记录 (Sync to Cloud)", use_container_width=True):
                log_data = {
                    "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "标的": symbol,
                    "总资产": balance,
                    "风险%": risk_pct,
                    "入场价": entry,
                    "止损价": stop_loss,
                    "仓位": round(pos_size, 2),
                    "杠杆": round(theory_lev, 2)
                }
                if save_to_db(log_data):
                    st.success("数据已穿透容器，成功写入云端数据库")
                    st.balloons()

    with right_col:
        st.subheader("📜 历史交易审计 (Google Sheets)")
        history_data = load_data()
        if not history_data.empty:
            # 倒序排列，最新的在上面
            st.dataframe(history_data.iloc[::-1], use_container_width=True, height=450)
        else:
            st.warning("数据库暂无历史记录，等待首次同步...")

if __name__ == "__main__":
    main()