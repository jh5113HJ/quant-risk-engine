import streamlit as st
import pandas as pd
import math
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict
from streamlit_gsheets import GSheetsConnection

# -------------------- 1. 页面配置 --------------------
st.set_page_config(page_title="量化交易风控引擎 v7.0", page_icon="📈", layout="wide")

# -------------------- 2. 合约规范与核心风控类 --------------------
@dataclass
class ContractSpec:
    """合约规格（参考主流交易所永续合约）"""
    symbol: str
    min_qty: float               # 最小交易数量
    price_tick: float             # 价格最小变动单位
    max_leverage: int             # 最大允许杠杆（≤200）
    mmr: float                    # 维持保证金率，例如 0.005 (0.5%)
    taker_fee_rate: float         # Taker 手续费率，例如 0.0004
    liquidation_fee_rate: float   # 强平手续费率，例如 0.0004

    def round_qty(self, qty: float) -> float:
        """按最小数量向下取整（交易所通常只允许向下取整开仓）"""
        if self.min_qty <= 0:
            return qty
        precision = 0
        if self.min_qty < 1:
            precision = len(str(self.min_qty).split('.')[-1])
        factor = 10 ** precision
        return math.floor(qty * factor) / factor

    def round_price(self, price: float) -> float:
        """按价格最小变动单位取整"""
        if self.price_tick <= 0:
            return price
        precision = 0
        if self.price_tick < 1:
            precision = len(str(self.price_tick).split('.')[-1])
        factor = 10 ** precision
        return round(price / self.price_tick) * self.price_tick


class CrossMarginPosition:
    """
    全仓模式单个仓位风控类（假设账户仅此仓位，用于强平价格等计算）
    """

    def __init__(self, symbol: str, contract_spec: ContractSpec, balance: float):
        self.symbol = symbol
        self.spec = contract_spec
        self.balance = balance            # 账户总余额
        self.entry_price: Optional[float] = None
        self.quantity: float = 0.0
        self.leverage: Optional[int] = None
        self.mark_price: Optional[float] = None

    def open_position(self, entry_price: float, quantity: float, leverage: int) -> 'CrossMarginPosition':
        if not 1 <= leverage <= self.spec.max_leverage:
            raise ValueError(f"杠杆必须介于 1 和 {self.spec.max_leverage} 之间")
        if quantity == 0:
            raise ValueError("开仓数量不能为0")

        abs_qty = abs(quantity)
        notional = abs_qty * entry_price
        initial_margin = notional / leverage

        if initial_margin > self.balance:
            raise ValueError(f"余额不足：需保证金 {initial_margin:.2f} USDT，可用余额 {self.balance:.2f} USDT")

        rounded_qty = self.spec.round_qty(abs_qty) * (1 if quantity > 0 else -1)
        self.entry_price = entry_price
        self.quantity = rounded_qty
        self.leverage = leverage
        self.mark_price = entry_price
        return self

    def update_mark_price(self, price: float) -> None:
        self.mark_price = price

    def get_unrealized_pnl(self) -> float:
        if self.quantity == 0 or self.mark_price is None:
            return 0.0
        if self.quantity > 0:
            return (self.mark_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.mark_price) * abs(self.quantity)

    def get_maintenance_margin(self) -> float:
        if self.quantity == 0:
            return 0.0
        current_notional = abs(self.quantity) * self.mark_price
        return current_notional * self.spec.mmr

    def get_margin_ratio(self) -> float:
        if self.quantity == 0:
            return float('inf')
        mm = self.get_maintenance_margin()
        if mm == 0:
            return float('inf')
        return (self.balance + self.get_unrealized_pnl()) / mm

    def get_liquidation_price(self) -> Optional[float]:
        if self.quantity == 0:
            return None
        abs_qty = abs(self.quantity)
        entry = self.entry_price
        bal = self.balance
        mmr = self.spec.mmr
        liq_fee = self.spec.liquidation_fee_rate

        if self.quantity > 0:  # 多仓
            numerator = bal - entry * abs_qty
            denominator = abs_qty * (mmr + liq_fee - 1)
            if denominator == 0:
                return None
            p = numerator / denominator
            return p if p > 0 else None
        else:  # 空仓
            numerator = bal + entry * abs_qty
            denominator = abs_qty * (mmr + liq_fee + 1)
            if denominator == 0:
                return None
            p = numerator / denominator
            return p if p > 0 else None

    def adjust_leverage(self, new_leverage: int) -> None:
        if not 1 <= new_leverage <= self.spec.max_leverage:
            raise ValueError(f"杠杆必须介于 1 和 {self.spec.max_leverage} 之间")
        if self.quantity == 0:
            self.leverage = new_leverage
            return

        notional = abs(self.quantity) * self.entry_price
        new_margin = notional / new_leverage
        total_equity = self.balance + self.get_unrealized_pnl()

        if new_margin > total_equity:
            raise ValueError(f"权益不足：新杠杆需保证金 {new_margin:.2f}，当前权益 {total_equity:.2f}")

        self.leverage = new_leverage

    @staticmethod
    def calculate_from_risk(entry_price: float,
                            stop_loss: float,
                            risk_amount: float,
                            balance: float,
                            contract_spec: ContractSpec,
                            take_profit: Optional[float] = None) -> Dict:
        """
        根据固定止损金额反向计算建议仓位和杠杆（不改变当前对象，静态工厂）
        :return: 字典包含：quantity, leverage, margin, notional, profit, rr, liquidation_price (预估)
        """
        if entry_price == stop_loss:
            raise ValueError("止损价不能等于开仓价")

        is_long = entry_price > stop_loss
        price_diff = abs(entry_price - stop_loss)

        raw_qty = risk_amount / price_diff
        qty = contract_spec.round_qty(raw_qty)
        if qty <= 0:
            raise ValueError("计算出的数量过小，请增大风险金额或更换合约")

        qty = qty if is_long else -qty
        abs_qty = abs(qty)
        notional = abs_qty * entry_price

        if balance <= 0:
            raise ValueError("余额必须为正")
        min_leverage_needed = math.ceil(notional / balance)
        if min_leverage_needed > contract_spec.max_leverage:
            raise ValueError(f"所需最低杠杆 {min_leverage_needed}x 超过最大允许 {contract_spec.max_leverage}x，请减少风险金额或增加余额")

        leverage = min_leverage_needed
        actual_margin = notional / leverage

        # 预估强平价格（模拟开仓后立即计算，标记价格假设等于开仓价）
        # 这里为了显示，临时创建一个虚拟仓位计算强平价格
        temp_pos = CrossMarginPosition(contract_spec.symbol, contract_spec, balance)
        temp_pos.open_position(entry_price, qty, leverage)
        liq_price = temp_pos.get_liquidation_price()

        profit = None
        rr = None
        if take_profit is not None:
            tp_diff = abs(take_profit - entry_price)
            profit = abs_qty * tp_diff
            rr = profit / risk_amount if risk_amount != 0 else 0

        return {
            'quantity': qty,
            'leverage': leverage,
            'margin': actual_margin,
            'notional': notional,
            'profit': profit,
            'rr': rr,
            'liquidation_price': liq_price
        }


# -------------------- 3. 默认合约参数 --------------------
DEFAULT_SPEC = ContractSpec(
    symbol="BTCUSDT",
    min_qty=0.0001,
    price_tick=0.1,
    max_leverage=200,
    mmr=0.005,               # 0.5% 维持保证金率
    taker_fee_rate=0.0004,
    liquidation_fee_rate=0.0004
)


# -------------------- 4. Google Sheets 日志读写 --------------------
def load_logs():
    """从 Google Sheets 拉取历史数据"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read()
        df = df.dropna(how="all")
        return df
    except Exception as e:
        st.error(f"数据库连接异常: {e}")
        return pd.DataFrame()


def save_log(new_data_dict):
    """将单条新日志追加到 Google Sheets"""
    conn = st.connection("gsheets", type=GSheetsConnection)
    existing_data = load_logs()
    new_df = pd.DataFrame([new_data_dict])
    if existing_data.empty:
        updated_data = new_df
    else:
        updated_data = pd.concat([existing_data, new_df], ignore_index=True)
    conn.update(data=updated_data)


# -------------------- 5. 主界面 --------------------
def main():
    st.title("🛡️ 交易杠杆与风控推导系统 v7.0")
    st.markdown("基于 **固定亏损金额** 全自动反推安全杠杆、最优仓位，并计算强平价格。")

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
        take_profit = st.number_input("止盈价格 (Take Profit) - 可选", min_value=0.00001, value=62000.0, format="%.5f")

        calculate_btn = st.button("⚡ 执行风控推导", type="primary", use_container_width=True)

    with col2:
        st.subheader("2. 智能风控执行面板")

        if calculate_btn:
            try:
                # 基础校验
                if entry_price == stop_loss:
                    st.error("止损价不能等于开仓价！")
                    st.stop()

                is_long = entry_price > stop_loss
                direction = "做多 (Long)" if is_long else "做空 (Short)"

                if is_long and take_profit <= entry_price and take_profit != 0:
                    st.error("逻辑错误：多单止盈必须高于开仓价！")
                    st.stop()
                if not is_long and take_profit >= entry_price and take_profit != 0:
                    st.error("逻辑错误：空单止盈必须低于开仓价！")
                    st.stop()

                # 调用核心计算
                result = CrossMarginPosition.calculate_from_risk(
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    risk_amount=risk_amount,
                    balance=balance,
                    contract_spec=DEFAULT_SPEC,
                    take_profit=take_profit if take_profit != 0 else None
                )

                # 提取结果
                qty = result['quantity']
                leverage = result['leverage']
                margin = result['margin']
                notional = result['notional']
                profit = result['profit']
                rr = result['rr']
                liq_price = result['liquidation_price']

                # 显示
                st.markdown(f"### {symbol_input} | {direction}")

                m1, m2, m3 = st.columns(3)
                m1.metric("建议下单数量 (币)", f"{qty:.4f}")
                m2.metric("系统分配杠杆", f"{leverage} x")
                m3.metric("实际占用本金", f"${margin:.2f}")

                m4, m5, m6 = st.columns(3)
                if profit is not None:
                    m4.metric("预期止盈利润", f"+${profit:.2f}")
                    m5.metric("盈亏比 (R:R)", f"{rr:.2f}")
                else:
                    m4.metric("预期止盈利润", "未设置")
                    m5.metric("盈亏比 (R:R)", "—")
                m6.metric("预估强平价格", f"${liq_price:.2f}" if liq_price else "无法计算")

                # 风险评估
                warnings = []
                if margin > balance:
                    warnings.append(f"❌ **资金不足**：该单需占用本金 ${margin:.2f}，可用余额仅为 ${balance}。")
                if liq_price and is_long and liq_price > entry_price * 0.9:  # 多仓强平价格高于当前价90%区域（示例）
                    warnings.append("⚠️ **强平风险**：当前强平价格距离开仓价较近，建议降低杠杆或增加保证金。")
                if liq_price and not is_long and liq_price < entry_price * 1.1:
                    warnings.append("⚠️ **强平风险**：当前强平价格距离开仓价较近，建议降低杠杆或增加保证金。")

                if not warnings:
                    st.success("✅ **风控通过**：仓位处于安全范围。")
                else:
                    for w in warnings:
                        st.error(w)

                # 记录日志
                log_data = {
                    'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'symbol': symbol_input,
                    'direction': direction,
                    'leverage': leverage,
                    'size': qty,
                    'balance': balance,
                    'entry': entry_price,
                    'sl': stop_loss,
                    'tp': take_profit if take_profit != 0 else None,
                    'risk': -risk_amount,
                    'profit': round(profit, 2) if profit else None,
                    'rr': round(rr, 2) if rr else None,
                    'liq_price': round(liq_price, 2) if liq_price else None
                }
                save_log(log_data)
                st.info("📝 交易记录已自动写入底层日志库。")

            except Exception as e:
                st.error(f"计算错误: {e}")

    st.divider()
    st.subheader("📊 历史交易日志复盘")
    logs_df = load_logs()
    if not logs_df.empty:
        st.dataframe(logs_df.tail(10), use_container_width=True)
    else:
        st.write("暂无历史交易数据。")


if __name__ == "__main__":
    main()