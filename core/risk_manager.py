class RiskManager:
    def __init__(self, balance, risk_per_trade, max_daily_loss=0.05, max_open_trades=3):
        self.balance = balance
        self.risk_per_trade = risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_open_trades = max_open_trades

    def calculate_lot_size(self, sl_pips, pip_value):
        if sl_pips <= 0 or pip_value <= 0:
            raise ValueError("sl_pips and pip_value must be > 0")
        return round((self.balance * self.risk_per_trade) / (sl_pips * pip_value), 2)

    def can_open_new_trade(self, open_positions_count: int) -> bool:
        return open_positions_count < self.max_open_trades

    def daily_loss_breached(self, today_pnl: float) -> bool:
        max_loss_amount = self.balance * self.max_daily_loss
        return today_pnl <= -abs(max_loss_amount)
