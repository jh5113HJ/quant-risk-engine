import streamlit as st
import pandas as pd
import os
import math
from datetime import datetime
from dataclasses import dataclass

# --- 1. 页面与全栈配置 ---
st.set_page_config(page_title="量化交易风控引擎", page_icon="📈", layout="wide")

# --- 2. 合约规范类 (复用核心底层) ---
@dataclass
class ContractSpec:
    symbol: str
    min_qty: float
    price_tick: float
    max_leverage: int
    liq_fee_rate: float

    def round_qty(self, raw_qty):
        if self.min_qty == 0: return raw_qty
        decimals = 0
        if self.min_qty < 1:
            decimals = len(str(self.min_qty).split('.')[1])
        factor = 10 ** decimals
        return math.floor(raw_qty * factor) / factor

DEFAULT_SPEC = ContractSpec(symbol="BTCUSDT", min_qty=0.0001, price_tick=0.1, max_leverage=200, liq_fee_rate=0.0004)

# --- 3. 日志读取保存逻辑 ---
LOG_FILE = 'trading_log.csv'

def save_log(data):
    df = pd.DataFrame([data])
    if not os.path.isfile(LOG_FILE):
        df.to_csv(LOG_FILE, index=False, encoding='utf-8-sig')
    else:
        df.to_csv(LOG_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')

def load_logs():
    if os.path.isfile(LOG_FILE):
        return pd.read_csv(LOG_FILE)
    return pd.DataFrame()

# --- 4. 前端 UI 与 交互主逻辑 ---
def main():
    st.title("🛡️ 交易杠杆与风控推导系统 v6.0")
    st.markdown("基于 **固定亏损金额** 全自动反推安全杠杆与最优仓位。")

    # 布局：左侧输入参数，右侧输出结果
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("1. 交易参数设置")
        
        raw_symbol = st.text_input("交易币种 (默认自动追加 USDT)", value="BTC").strip().upper()
        symbol_input = raw_symbol if raw_symbol.endswith("USDT") else f"{raw_symbol}USDT"
        
        balance = st.number_input("账户总资金 (USDT)", min_value=1.0, value=1000.0, step=100.0)
        risk_amount = st.number_input("固定止损金额 (Risk $)", min_value=1.0, value=50.0, step=10.0)
        
        st.divider()
        entry_price = st.number_input("开仓价格 (Entry)", min_value=0.00001, value=60000.0, format="%.5f")
        stop_loss = st.number_input("止损价格 (Stop Loss)", min_value=0.00001, value=59500.0, format="%.5f")
        take_profit = st.number_input("止盈价格 (Take Profit)", min_value=0.00001, value=62000.0, format="%.5f")
        
        calculate_btn = st.button("⚡ 执行风控推导", type="primary", use_container_width=True)

    with col2:
        st.subheader("2. 智能风控执行面板")
        
        if calculate_btn:
            # --- 核心逻辑防呆校验 ---
            if entry_price == stop_loss:
                st.error("止损价不能等于开仓价！")
                return
                
            is_long = entry_price > stop_loss
            direction = "做多 (Long)" if is_long else "做空 (Short)"
            
            if is_long and take_profit <= entry_price:
                st.error("逻辑错误：多单止盈必须高于开仓价！")
                return
            if not is_long and take_profit >= entry_price:
                st.error("逻辑错误：空单止盈必须低于开仓价！")
                return

            # --- 核心数学计算 ---
            price_diff = abs(entry_price - stop_loss)
            tp_diff = abs(take_profit - entry_price)
            
            raw_qty = risk_amount / price_diff
            final_qty = DEFAULT_SPEC.round_qty(raw_qty)
            
            if final_qty <= 0:
                st.error(f"持仓量过小已被截断为 0。请增加风险金额或更换面值更小的合约。")
                return

            notional_value = final_qty * entry_price
            target_margin = risk_amount * 1.05  # 5% 缓冲
            raw_leverage = notional_value / target_margin
            
            final_leverage = min(int(raw_leverage), DEFAULT_SPEC.max_leverage)
            final_leverage = max(final_leverage, 1) # 至少 1x
            
            actual_margin = notional_value / final_leverage
            projected_profit = final_qty * tp_diff
            rr_ratio = projected_profit / risk_amount
            est_liq_fee = notional_value * DEFAULT_SPEC.liq_fee_rate

            liquidation_risk = (actual_margin - est_liq_fee) <= risk_amount

            # --- 结果可视化呈现 ---
            st.markdown(f"### {symbol_input} | {direction}")
            
            # 使用 Metric 组件展示核心指标
            m1, m2, m3 = st.columns(3)
            m1.metric("建议下单数量 (币)", f"{final_qty:.4f}")
            m2.metric("系统分配杠杆", f"{final_leverage} x")
            m3.metric("实际占用本金", f"${actual_margin:.2f}")

            m4, m5, m6 = st.columns(3)
            m4.metric("预期止盈利润", f"+${projected_profit:.2f}")
            m5.metric("盈亏比 (R:R)", f"{rr_ratio:.2f}")
            m6.metric("预估强平手续费", f"${est_liq_fee:.2f}")

            # 风险评估与拦截
            if liquidation_risk:
                st.error("⚠️ **高危警告**：止损空间过大导致杠杆被压缩，当前保证金可能不足以覆盖强平滑点，有提前爆仓风险。")
            elif actual_margin > balance:
                st.error(f"❌ **资金不足**：该单需要占用本金 ${actual_margin:.2f}，但可用余额仅为 ${balance}。")
            else:
                st.success("✅ **风控通过**：仓位处于安全范围，未触发强平拦截。")
                
                # 记录日志
                log_data = {
                    'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'symbol': symbol_input,
                    'direction': direction,
                    'leverage': final_leverage,
                    'size': final_qty,
                    'balance': balance,
                    'entry': entry_price,
                    'sl': stop_loss,
                    'tp': take_profit,
                    'risk': -risk_amount,
                    'profit': round(projected_profit, 2),
                    'rr': round(rr_ratio, 2)
                }
                save_log(log_data)
                st.info("📝 交易记录已自动写入底层日志库。")

    st.divider()
    st.subheader("📊 历史交易日志复盘")
    logs_df = load_logs()
    if not logs_df.empty:
        # 在网页端以可交互的数据表格展示日志
        st.dataframe(logs_df.tail(10), use_container_width=True)
    else:
        st.write("暂无历史交易数据。")

if __name__ == "__main__":
    main()