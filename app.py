import streamlit as st
import pandas as pd
import math
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Union, Dict

# ==========================================
# 核心底层：量化风控引擎 (Binance 标准)
# ==========================================
@dataclass
class TradeResult:
    symbol: str
    direction: str
    position_size: float   # 持仓币数
    leverage: int          # 建议杠杆倍数
    usdt_cost: float       # 投入的USDT本金 (Initial Margin)
    expected_profit: float # 扣除手续费后的净止盈金额
    rr_ratio: float        # 真实盈亏比
    gross_loss: float      # 包含手续费的极限亏损预估

class RiskEngine:
    def __init__(self, taker_fee: float = 0.0005, mmr: float = 0.004, max_leverage: int = 200):
        """
        :param taker_fee: 吃单手续费率 (双边收取)
        :param mmr: 维持保证金率 (控制爆仓线)
        :param max_leverage: 平台最高杠杆限制
        """
        self.taker_fee = taker_fee
        self.mmr = mmr
        self.max_leverage = max_leverage

    def calculate(self, risk_amount: float, entry: float, sl: float, tp: float, symbol: str) -> Union[TradeResult, Dict[str, str]]:
        # 1. 基础异常拦截
        if any(v <= 0 for v in [risk_amount, entry, sl, tp]):
            return {"error": "金额与价格必须大于 0"}
        if entry == sl:
            return {"error": "开仓价不可等于止损价"}
            
        # 2. 标的与方向判定
        symbol_fmt = symbol.strip().upper()
        if not symbol_fmt.endswith("USDT"):
            symbol_fmt += "USDT"
            
        is_long = tp > entry
        direction = "做多 (Long)" if is_long else "做空 (Short)"
        
        # 3. 逻辑冲突拦截
        if is_long and sl >= entry: return {"error": "多单止损价必须低于开仓价"}
        if not is_long and sl <= entry: return {"error": "空单止损价必须高于开仓价"}
        if is_long and tp <= entry: return {"error": "多单止盈价必须高于开仓价"}
        if not is_long and tp >= entry: return {"error": "空单止盈价必须低于开仓价"}

        try:
            # 4. 真实仓位计算 (Position Size)
            # 亏损 = 价格差损耗 + 开仓手续费 + 平仓手续费
            price_diff = abs(entry - sl)
            fee_cost_per_coin = self.taker_fee * (entry + sl)
            position_size = risk_amount / (price_diff + fee_cost_per_coin)
            
            # 5. 动态安全杠杆推导 (Leverage)
            # 初始保证金率必须大于：止损跌幅比例 + 维持保证金率 + 手续费率
            sl_distance_pct = price_diff / entry
            safe_margin_rate = sl_distance_pct + self.mmr + (2 * self.taker_fee)
            raw_leverage = 1 / safe_margin_rate
            
            # 截断处理：1x 至 200x
            final_leverage = max(1, min(self.max_leverage, math.floor(raw_leverage)))
            
            # 6. USDT 成本计算 (USDT Cost)
            notional_value = position_size * entry
            usdt_cost = notional_value / final_leverage
            
            # 7. 止盈利润预估 (扣除开平手续费)
            tp_diff = abs(tp - entry)
            gross_profit = position_size * tp_diff
            tp_fee_cost = self.taker_fee * (entry + tp) * position_size
            net_profit = gross_profit - tp_fee_cost
            
            rr_ratio = net_profit / risk_amount
            
            return TradeResult(
                symbol=symbol_fmt,
                direction=direction,
                position_size=position_size,
                leverage=final_leverage,
                usdt_cost=usdt_cost,
                expected_profit=net_profit,
                rr_ratio=rr_ratio,
                gross_loss=risk_amount
            )
        except Exception as e:
            return {"error": f"系统计算异常: {str(e)}"}

# ==========================================
# 本地日志持久化模块 (替代 GSheets 避免崩溃)
# ==========================================
LOG_FILE = "trade_logs.csv"

def load_logs() -> pd.DataFrame:
    if os.path.exists(LOG_FILE):
        return pd.read_csv(LOG_FILE)
    return pd.DataFrame()

def save_log(data: dict):
    df = pd.DataFrame([data])
    if not os.path.exists(LOG_FILE):
        df.to_csv(LOG_FILE, index=False)
    else:
        df.to_csv(LOG_FILE, mode='a', header=False, index=False)

# ==========================================
# 前端 UI 与 交互主逻辑
# ==========================================
def main():
    st.set_page_config(page_title="量化风控引擎", page_icon="📈", layout="wide")
    st.title("🛡️ 交易杠杆与风控推导系统 (实盘标准版)")
    st.markdown("基于 **绝对亏损金额** 全自动反推安全杠杆与投入本金。已内置币安维持保证金与双边手续费损耗模型。")

    engine = RiskEngine()

    col1, col2 = st.columns([1, 1.5])

    with col1:
        st.subheader("1. 交易参数设置")
        with st.container(border=True):
            raw_symbol = st.text_input("交易币种 (自动追加 USDT)", value="BTC").strip()
            risk_amount = st.number_input("固定止损金额 (Risk USDT)", min_value=1.0, value=50.0, step=10.0)
            
            st.divider()
            entry_price = st.number_input("开仓价格 (Entry)", min_value=0.00001, value=60000.0, format="%.5f")
            stop_loss = st.number_input("止损价格 (Stop Loss)", min_value=0.00001, value=59500.0, format="%.5f")
            take_profit = st.number_input("止盈价格 (Take Profit)", min_value=0.00001, value=62000.0, format="%.5f")
            
            calculate_btn = st.button("⚡ 执行风控推导", type="primary", use_container_width=True)

    with col2:
        st.subheader("2. 智能风控执行面板")
        
        if calculate_btn:
            result = engine.calculate(risk_amount, entry_price, stop_loss, take_profit, raw_symbol)
            
            if isinstance(result, dict) and "error" in result:
                st.error(f"❌ 逻辑错误：{result['error']}")
            else:
                st.success(f"✅ 风控计算通过 | {result.symbol} | {result.direction}")
                
                # 核心指标展示面板
                m1, m2, m3 = st.columns(3)
                m1.metric("系统分配安全杠杆", f"{result.leverage} x")
                m2.metric("投入本金 (USDT Cost)", f"${result.usdt_cost:.2f}")
                m3.metric("建议下单数量 (币)", f"{result.position_size:.5f}")

                m4, m5, m6 = st.columns(3)
                m4.metric("预期净止盈 (扣除手续费)", f"+${result.expected_profit:.2f}")
                m5.metric("真实盈亏比 (R:R)", f"{result.rr_ratio:.2f}")
                m6.metric("严格受控风险", f"-${result.gross_loss:.2f}")
                
                # 记录日志
                log_data = {
                    '时间': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    '标的': result.symbol,
                    '方向': result.direction,
                    '杠杆': f"{result.leverage}x",
                    '投入USDT': round(result.usdt_cost, 2),
                    '开仓价': entry_price,
                    '止损价': stop_loss,
                    '净利润': round(result.expected_profit, 2)
                }
                save_log(log_data)
                st.info("📝 交易策略已通过底层校验，并写入本地日志 `trade_logs.csv`。")

    st.divider()
    st.subheader("📊 历史策略复盘")
    logs_df = load_logs()
    if not logs_df.empty:
        st.dataframe(logs_df.tail(10).iloc[::-1], use_container_width=True) # 倒序显示最新
    else:
        st.write("暂无历史交易数据。")

if __name__ == "__main__":
    main()