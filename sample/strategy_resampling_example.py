import alpaca_backtrader_api
import backtrader as bt
from datetime import datetime

# Your credentials here
ALPACA_API_KEY = "<key_id>"
ALPACA_SECRET_KEY = "<secret_key>"


IS_LIVE = False
symbol = "GOOG"


class Resample(bt.Strategy):
    def notify_data(self, data, status, *args, **kwargs):
        super().notify_data(data, status, *args, **kwargs)
        print('*' * 5, 'DATA NOTIF:', data._getstatusname(status), *args)
        if data._getstatusname(status) == "LIVE":
            self.live_bars = True

    def __init__(self):
        self.live_bars = False

    def next(self):
        if not self.live_bars:
            return
        print(datetime.utcnow())


if __name__ == '__main__':
    import logging
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(Resample)

    store = alpaca_backtrader_api.AlpacaStore(
        key_id=ALPACA_API_KEY,
        secret_key=ALPACA_SECRET_KEY,
        paper=not IS_LIVE,
    )
    DataFactory = store.getdata
    data0 = DataFactory(dataname=symbol,
                        historical=False,
                        timeframe=bt.TimeFrame.Minutes,
                        qcheck=10.0,
                        backfill_start=False,
                        data_feed='iex'
                        )
    broker = store.getbroker()
    cerebro.setbroker(broker)
    cerebro.resampledata(data0,
                         compression=2,
                         timeframe=bt.TimeFrame.Minutes)
    cerebro.run()
