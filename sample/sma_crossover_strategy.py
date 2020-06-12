import alpaca_backtrader_api
import backtrader as bt
from datetime import datetime, timedelta

# Your credentials here
# ALPACA_API_KEY = "<key_id>"
# ALPACA_SECRET_KEY = "<secret_key>"


## mine:
ALPACA_API_KEY = "PKEOFXUJRINEGO0YP3CD"
ALPACA_SECRET_KEY = "GGqP1hHwgSWijNk0dh4NRbAt9nD1bCeaV3OZH1LE"
USE_POLYGON = False

# ALPACA_API_KEY = "PKRYEUB4K6RVNTZSFKFT"
# ALPACA_SECRET_KEY = "at6gv6MdJsLWlmTFu5khrL3vZZ8OG8GVKW4NQlMB"
# USE_POLYGON = True


# change to True if you want to do live paper trading with Alpaca Broker.
#  False will do a back test
ALPACA_PAPER = True


class SmaCross1(bt.Strategy):
    # list of parameters which are configurable for the strategy
    params = dict(
        pfast=10,  # period for the fast moving average
        pslow=30   # period for the slow moving average
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
        self.timer = datetime.utcnow()
        sma1 = bt.ind.SMA(self.data0, period=self.p.pfast)
        sma2 = bt.ind.SMA(self.data0, period=self.p.pslow)
        self.crossover0 = bt.ind.CrossOver(sma1, sma2)
        # moving average for 120 min
        self.sma_20 = bt.ind.SMA(self.data1, period=20)
        # moving average for 120 min
        self.sma_20_120 = bt.ind.SMA(self.data2, period=20)

    once = None
    def next(self):
        # if fast crosses slow to the upside
        import datetime
        if datetime.datetime.utcnow() - self.timer < timedelta(seconds=10):
            return
        self.timer = datetime.datetime.utcnow()
        dtfmt = '%Y-%m-%dT%H:%M:%S.%f'
        print(f"next called: {self.data.datetime.datetime(0).strftime(dtfmt)}")
        if not self.positionsbyname["AA"].size:
            self.buy(data=data0, size=5)
        else:
            self.close(data=data0)
        return
        self.log(self.sma_20)
        self.log(self.sma_20_120)
        # print(datetime.datetime.utcnow())
        if not self.positionsbyname["AA"].size:
            if not self.once:
                # self.order_target_percent(data0, 0.01)
                self.once = True
                self.buy_bracket(data=self.data, exectype= bt.Order.Market,
                                 stopprice=list(self.data)[0]*0.998,
                                 limitprice=list(self.data)[0]*1.0021,
                                 size=10)
        # if not self.positionsbyname["AA"].size and self.crossover0 > 0:
        #     self.buy(data=data0, size=5)  # enter long
        #
        # # in the market & cross to the downside
        # if self.positionsbyname["AA"].size and self.crossover0 <= 0:
        #     self.close(data=data0)  # close long position


if __name__ == '__main__':
    cerebro = bt.Cerebro()
    cerebro.notify_store = lambda x: print(x)
    cerebro.addstrategy(SmaCross1)

    store = alpaca_backtrader_api.AlpacaStore(
        key_id=ALPACA_API_KEY,
        secret_key=ALPACA_SECRET_KEY,
        paper=True,
        usePolygon=USE_POLYGON
    )
    import pandas as pd
    DataFactory = store.getdata  # or use alpaca_backtrader_api.AlpacaData
    if ALPACA_PAPER:
        data0 = DataFactory(dataname='AA',
                            historical=False,
                            timeframe=bt.TimeFrame.Minutes,
                            backfill_start=True,
                            fromdate=datetime.utcnow() - timedelta(minutes=20)
                            )
        # fromdate = pd.Timestamp('2020-5-1'),
        # or just alpaca_backtrader_api.AlpacaBroker()
        broker = store.getbroker()
        cerebro.setbroker(broker)
    else:
        data0 = DataFactory(dataname='AA', historical=True,
                            fromdate=datetime(
            2019, 9, 1), timeframe=bt.TimeFrame.Days)
    cerebro.adddata(data0)

    if not ALPACA_PAPER:
        # backtrader broker set initial simulated cash
        cerebro.broker.setcash(100000.0)

    print('Starting Portfolio Value: {}'.format(cerebro.broker.getvalue()))
    store.oapi.get_account()
    cerebro.broker.getcash()

    # cerebro.resampledata(data0, name="Real", timeframe=bt.TimeFrame.Minutes,
    #                      compression=10)
    # data
    cerebro.resampledata(data0, timeframe=bt.TimeFrame.Minutes, compression=1)
    # data1
    cerebro.resampledata(data0, timeframe=bt.TimeFrame.Seconds, compression=20,
                         name='data_30m')
    # data2
    cerebro.resampledata(data0, timeframe=bt.TimeFrame.Seconds,
                         compression=120,
                     name='data_120m')

    cerebro.run()
    print('Final Portfolio Value: {}'.format(cerebro.broker.getvalue()))
    cerebro.plot()
