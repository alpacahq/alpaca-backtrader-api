"""
SMA50/SMA70 Trading Strategy
============================
Entry: When stock closes above SMA50
Exit:  When stock closes below BOTH SMA50 and SMA70

Universe: TSLA, NVDA, AAPL, AMZN, NFLX, AMD
"""

import alpaca_backtrader_api
import backtrader as bt
from datetime import datetime
import logging

# Alpaca API Credentials
API_KEY = 'PKBTEWQBIUWV3F45ZID1'
API_SECRET = 'TYkkJXbXwh6U2BYlwJxBhZfRSus8Y11SdMsqx4iY'
BASE_URL = 'https://paper-api.alpaca.markets'

# Trading universe
SYMBOLS = ['TSLA', 'NVDA', 'AAPL', 'AMZN', 'NFLX', 'AMD']

# Trading mode options
IS_BACKTEST = True   # True = backtest, False = paper/live
IS_LIVE = False      # Only matters if IS_BACKTEST=False


class SMA50_70Strategy(bt.Strategy):
    """
    Entry: Close > SMA50 (and no existing position)
    Exit:  Close < SMA50 AND Close < SMA70
    """
    params = dict(
        sma_fast=50,
        sma_slow=70,
        size=10,  # shares per trade
    )

    def __init__(self):
        self.live_bars = False
        self.orders = {}  # track pending orders per symbol
        self.sma50 = {}
        self.sma70 = {}

        # Create indicators for each data feed
        for data in self.datas:
            symbol = data._name
            self.sma50[symbol] = bt.ind.SMA(data, period=self.p.sma_fast)
            self.sma70[symbol] = bt.ind.SMA(data, period=self.p.sma_slow)
            self.orders[symbol] = None

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime[0]
        dt = bt.num2date(dt)
        print(f'{dt.isoformat()} | {txt}')

    def notify_data(self, data, status, *args, **kwargs):
        status_name = data._getstatusname(status)
        self.log(f'Data Status [{data._name}]: {status_name}')
        if status_name == "LIVE":
            self.live_bars = True

    def notify_order(self, order):
        symbol = order.data._name
        if order.status in [order.Submitted, order.Accepted]:
            return  # wait for execution

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f'BUY EXECUTED [{symbol}] @ {order.executed.price:.2f}')
            else:
                self.log(f'SELL EXECUTED [{symbol}] @ {order.executed.price:.2f}')

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'Order {order.getstatusname()} [{symbol}]')

        self.orders[symbol] = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'TRADE CLOSED [{trade.getdataname()}] '
                     f'PnL: Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}')

    def next(self):
        # Skip historical bars during live trading
        if not self.live_bars and not IS_BACKTEST:
            return

        for data in self.datas:
            symbol = data._name
            pos = self.getposition(data)
            close = data.close[0]
            sma50_val = self.sma50[symbol][0]
            sma70_val = self.sma70[symbol][0]

            # Skip if we have a pending order
            if self.orders[symbol]:
                continue

            # Entry: Close > SMA50 and no position
            if not pos.size and close > sma50_val:
                self.log(f'BUY SIGNAL [{symbol}] Close={close:.2f} > SMA50={sma50_val:.2f}')
                self.orders[symbol] = self.buy(data=data, size=self.p.size)

            # Exit: Close < SMA50 AND Close < SMA70
            elif pos.size > 0 and close < sma50_val and close < sma70_val:
                self.log(f'SELL SIGNAL [{symbol}] Close={close:.2f} < SMA50={sma50_val:.2f} '
                         f'AND < SMA70={sma70_val:.2f}')
                self.orders[symbol] = self.close(data=data)

    def stop(self):
        print('\n' + '=' * 60)
        print('STRATEGY RESULTS')
        print('=' * 60)
        print(f'Starting Value: ${self.broker.startingcash:,.2f}')
        print(f'Ending Value:   ${self.broker.getvalue():,.2f}')
        pnl = self.broker.getvalue() - self.broker.startingcash
        pnl_pct = (pnl / self.broker.startingcash) * 100
        print(f'Total P&L:      ${pnl:,.2f} ({pnl_pct:.2f}%)')
        print('=' * 60)


def run_strategy():
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(SMA50_70Strategy)

    # Connect to Alpaca
    store = alpaca_backtrader_api.AlpacaStore(
        key_id=API_KEY,
        secret_key=API_SECRET,
        paper=not IS_LIVE,
    )

    DataFactory = store.getdata

    # Add data feeds for each symbol
    for symbol in SYMBOLS:
        if IS_BACKTEST:
            data = DataFactory(
                dataname=symbol,
                historical=True,
                fromdate=datetime(2023, 1, 1),
                todate=datetime(2024, 1, 1),
                timeframe=bt.TimeFrame.Days,
                data_feed='iex'
            )
        else:
            data = DataFactory(
                dataname=symbol,
                historical=False,
                timeframe=bt.TimeFrame.Days,
                backfill_start=True,
                data_feed='iex'
            )
        cerebro.adddata(data)

    # Set up broker
    if IS_BACKTEST:
        cerebro.broker.setcash(100000.0)
        cerebro.broker.setcommission(commission=0.0)  # Alpaca has no commissions
    else:
        broker = store.getbroker()
        cerebro.setbroker(broker)

    # Add analyzers for backtesting
    if IS_BACKTEST:
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    print('\n' + '=' * 60)
    print('SMA50/70 STRATEGY')
    print('=' * 60)
    print(f'Mode: {"Backtest" if IS_BACKTEST else "Paper Trading" if not IS_LIVE else "LIVE"}')
    print(f'Universe: {", ".join(SYMBOLS)}')
    print(f'Entry: Close > SMA50')
    print(f'Exit:  Close < SMA50 AND Close < SMA70')
    print('=' * 60)
    print(f'Starting Portfolio Value: ${cerebro.broker.getvalue():,.2f}\n')

    # Run the strategy
    results = cerebro.run()

    print(f'\nFinal Portfolio Value: ${cerebro.broker.getvalue():,.2f}')

    # Print analyzer results for backtest
    if IS_BACKTEST:
        strat = results[0]
        print('\n' + '-' * 40)
        print('ANALYZER RESULTS')
        print('-' * 40)

        # Sharpe Ratio
        sharpe = strat.analyzers.sharpe.get_analysis()
        print(f'Sharpe Ratio: {sharpe.get("sharperatio", "N/A")}')

        # Drawdown
        dd = strat.analyzers.drawdown.get_analysis()
        print(f'Max Drawdown: {dd.get("max", {}).get("drawdown", 0):.2f}%')

        # Trade stats
        trades = strat.analyzers.trades.get_analysis()
        total = trades.get('total', {}).get('total', 0)
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        print(f'Total Trades: {total}')
        print(f'Won: {won}, Lost: {lost}')
        if total > 0:
            print(f'Win Rate: {(won/total)*100:.1f}%')

        # Plot results
        cerebro.plot(style='candlestick')


if __name__ == '__main__':
    run_strategy()
