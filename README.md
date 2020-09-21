[![PyPI version](https://badge.fury.io/py/alpaca-backtrader-api.svg)](https://badge.fury.io/py/alpaca-backtrader-api)
[![CircleCI](https://circleci.com/gh/alpacahq/alpaca-backtrader-api.svg?style=shield)](https://circleci.com/gh/alpacahq/alpaca-backtrader-api)
[![Updates](https://pyup.io/repos/github/alpacahq/alpaca-backtrader-api/shield.svg)](https://pyup.io/repos/github/alpacahq/alpaca-backtrader-api/)
[![Python 3](https://pyup.io/repos/github/alpacahq/alpaca-backtrader-api/python-3-shield.svg)](https://pyup.io/repos/github/alpacahq/alpaca-backtrader-api/)

# alpaca-backtrader-api

`alpaca-backtrader-api` is a python library for the Alpaca trade API
within `backtrader` framework.
It allows rapid trading algo development easily, with support for the
both REST and streaming interfaces. For details of each API behavior,
please see the online API document.

Note this module supports only python version 3.5 and above, due to
the underlying library `alpaca-trade-api`.

## Install

```bash
$ pip3 install alpaca-backtrader-api
```

## Example

#### These examples only work if you have a funded brokerage account or another means of accessing Polygon data.

you can find example strategies in the [samples](https://github.com/alpacahq/alpaca-backtrader-api/tree/master/sample) folder. 

remember to add you credentials.

you can toggle between backtesting and paper trading by changing `ALPACA_PAPER`

#### a strategy looks like this:

In order to call Alpaca's trade API, you need to obtain API key pairs.
Replace <key_id> and <secret_key> with what you get from the web console.

```python
import alpaca_backtrader_api
import backtrader as bt
from datetime import datetime

ALPACA_API_KEY = <key_id>
ALPACA_SECRET_KEY = <secret_key>
ALPACA_PAPER = True


class SmaCross(bt.SignalStrategy):
  def __init__(self):
    sma1, sma2 = bt.ind.SMA(period=10), bt.ind.SMA(period=30)
    crossover = bt.ind.CrossOver(sma1, sma2)
    self.signal_add(bt.SIGNAL_LONG, crossover)


cerebro = bt.Cerebro()
cerebro.addstrategy(SmaCross)

store = alpaca_backtrader_api.AlpacaStore(
    key_id=ALPACA_API_KEY,
    secret_key=ALPACA_SECRET_KEY,
    paper=ALPACA_PAPER
)

if not ALPACA_PAPER:
  broker = store.getbroker()  # or just alpaca_backtrader_api.AlpacaBroker()
  cerebro.setbroker(broker)

DataFactory = store.getdata  # or use alpaca_backtrader_api.AlpacaData
data0 = DataFactory(dataname='AAPL', historical=True, fromdate=datetime(
    2015, 1, 1), timeframe=bt.TimeFrame.Days)
cerebro.adddata(data0)

print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
cerebro.run()
print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())
cerebro.plot()
```

## API Document

The HTTP API document is located in https://docs.alpaca.markets/

## Authentication

The Alpaca API requires API key ID and secret key, which you can obtain from the
web console after you sign in.  You can set them in the AlpacaStore constructor,
using 'key_id' and 'secret_key'.

## Paper/Live mode

The 'paper' parameter is default to False, which allows live trading.
If you set it to True, then you are in the paper trading mode.

## Running Multiple Strategies/Datas
There's a way to execute an algorithm with multiple datas or/and execute more than one algorithm.<br>
The websocket connection is limited to 1 connection per account. Alpaca backtrader opens a websocket connection for each data you define.<br>
For that exact purpose this ![project](https://github.com/shlomikushchi/alpaca-proxy-agent)  was created<br>
The steps to execute this are:
* Run the Alpaca Proxy Agent as described in the project's README
* Define this env variable: `DATA_PROXY_WS` to be the address of the proxy agent. (e.g: `DATA_PROXY_WS=ws://192.168.99.100:8765`)
* execute your algorithm. it will connect to the servers through the proxy agent allowing you to execute multiple datas/strategies

## Support and Contribution

For technical issues particular to this module, please report the
issue on this GitHub repository. Any API issues can be reported through
Alpaca's customer support.

New features, as well as bug fixes, by sending pull request is always
welcomed.
