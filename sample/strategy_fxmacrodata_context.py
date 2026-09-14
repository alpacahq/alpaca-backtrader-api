import os
from datetime import datetime

import alpaca_backtrader_api
import backtrader as bt


ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_PAPER = True


class MacroAwareSmaCross(bt.SignalStrategy):
    def __init__(self):
        sma1 = bt.ind.SMA(period=10)
        sma2 = bt.ind.SMA(period=30)
        self.signal_add(bt.SIGNAL_LONG, bt.ind.CrossOver(sma1, sma2))


if __name__ == "__main__":
    macro = alpaca_backtrader_api.FXMacroDataClient()
    print(macro.calendar("usd", limit=5))

    cerebro = bt.Cerebro()
    cerebro.addstrategy(MacroAwareSmaCross)

    store = alpaca_backtrader_api.AlpacaStore(
        key_id=ALPACA_API_KEY,
        secret_key=ALPACA_SECRET_KEY,
        paper=ALPACA_PAPER,
    )
    data0 = store.getdata(
        dataname="AAPL",
        historical=True,
        fromdate=datetime(2020, 1, 1),
        timeframe=bt.TimeFrame.Days,
    )
    cerebro.adddata(data0)
    cerebro.run()
