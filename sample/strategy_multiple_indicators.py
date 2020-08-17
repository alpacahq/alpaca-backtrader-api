import alpaca_backtrader_api
import backtrader as bt
from datetime import datetime

# Your credentials here
ALPACA_API_KEY = "<key_id>"
ALPACA_SECRET_KEY = "<secret_key>"
# change to True if you want to do live paper trading with Alpaca Broker.
#  False will do a back test
IS_BACKTEST = False
SYMBOL = 'AA'

class SmaCross1(bt.Strategy):
    # list of parameters which are configurable for the strategy
    params = dict(
        pfast=10,  # period for the fast moving average
        pslow=30,   # period for the slow moving average
        rsi_per=14,
        rsi_upper=65.0,
        rsi_lower=35.0,
        rsi_out=50.0,
        warmup=35
    )

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime[0]
        dt = bt.num2date(dt)
        print('%s, %s' % (dt.isoformat(), txt))

    def notify_trade(self, trade):
        self.log("placing trade for {}. target size: {}".format(
            trade.getdataname(),
            trade.size))

    def notify_order(self, order):
        pass

    def stop(self):
        print('==================================================')
        print('Starting Value - %.2f' % self.broker.startingcash)
        print('Ending   Value - %.2f' % self.broker.getvalue())
        print('==================================================')

    def __init__(self):
        sma1 = bt.ind.SMA(self.data0, period=self.p.pfast)
        sma2 = bt.ind.SMA(self.data0, period=self.p.pslow)
        self.crossover = bt.ind.CrossOver(sma1, sma2)

        rsi = bt.indicators.RSI(period=self.p.rsi_per,
                                upperband=self.p.rsi_upper,
                                lowerband=self.p.rsi_lower)

        self.crossdown = bt.ind.CrossDown(rsi, self.p.rsi_upper)
        self.crossup = bt.ind.CrossUp(rsi, self.p.rsi_lower)

    def next(self):
        # if fast crosses slow to the upside
        if not self.positionsbyname["AAPL"].size:
            if self.crossover > 0 or self.crossup > 0:
                self.buy(data=data0, size=5)  # enter long

        # in the market & cross to the downside
        if self.positionsbyname["AAPL"].size:
            if self.crossover <= 0 or self.crossdown < 0:
                self.close(data=data0)  # close long position


if __name__ == '__main__':
    import logging
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SmaCross1)

    store = alpaca_backtrader_api.AlpacaStore(
        key_id=ALPACA_API_KEY,
        secret_key=ALPACA_SECRET_KEY,
        paper=True,
        usePolygon=USE_POLYGON
    )

    DataFactory = store.getdata  # or use alpaca_backtrader_api.AlpacaData
    if IS_BACKTEST:
        data0 = DataFactory(dataname=SYMBOL, historical=True,
                            fromdate=datetime(
                                2015, 1, 1), timeframe=bt.TimeFrame.Days)

    else:
        data0 = DataFactory(dataname=SYMBOL,
                            historical=False,
                            timeframe=bt.TimeFrame.Days)
        # or just alpaca_backtrader_api.AlpacaBroker()
        broker = store.getbroker()
        cerebro.setbroker(broker)
    cerebro.adddata(data0)

    if IS_BACKTEST:
        # backtrader broker set initial simulated cash
        cerebro.broker.setcash(100000.0)

    print('Starting Portfolio Value: {}'.format(cerebro.broker.getvalue()))
    cerebro.run()
    print('Final Portfolio Value: {}'.format(cerebro.broker.getvalue()))
    cerebro.plot()
