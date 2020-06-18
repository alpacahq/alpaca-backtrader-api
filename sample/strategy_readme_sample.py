# This is the example code from the repo's README
import alpaca_backtrader_api
import backtrader as bt
from datetime import datetime

# Your credentials here
ALPACA_API_KEY = "<key_id>"
ALPACA_SECRET_KEY = "<secret_key>"
# change to True if you want to do live paper trading with Alpaca Broker.
#  False will do a back test
ALPACA_PAPER = False


class SmaCross(bt.SignalStrategy):
  def __init__(self):
    sma1, sma2 = bt.ind.SMA(period=10), bt.ind.SMA(period=30)
    crossover = bt.ind.CrossOver(sma1, sma2)
    self.signal_add(bt.SIGNAL_LONG, crossover)


if __name__ == '__main__':
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SmaCross)

    store = alpaca_backtrader_api.AlpacaStore(
        key_id=ALPACA_API_KEY,
        secret_key=ALPACA_SECRET_KEY,
        paper=True,
        usePolygon=USE_POLYGON
    )

    DataFactory = store.getdata  # or use alpaca_backtrader_api.AlpacaData
    if ALPACA_PAPER:
        data0 = DataFactory(dataname='AAPL',
                            historical=False,
                            timeframe=bt.TimeFrame.Days)
        cerebro.adddata(data0)
        # or just alpaca_backtrader_api.AlpacaBroker()
        broker = store.getbroker()
        cerebro.setbroker(broker)
    else:
        data0 = DataFactory(dataname='AAPL', historical=True, fromdate=datetime(
            2015, 1, 1), timeframe=bt.TimeFrame.Days)
    cerebro.adddata(data0)

    print('Starting Portfolio Value: {}'.format(cerebro.broker.getvalue()))
    cerebro.run()
    print('Final Portfolio Value: {}'.format(cerebro.broker.getvalue()))
    cerebro.plot()
