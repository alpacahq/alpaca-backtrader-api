# CLAUDE.md - Alpaca Backtrader API

## Overview
Python library integrating Alpaca trading API with the backtrader framework for algorithmic trading. Supports backtesting, paper trading, and live trading.

## Project Structure
```
alpaca_backtrader_api/
├── alpacastore.py    # Core singleton: API connection, streaming, order management
├── alpacabroker.py   # Broker interface: positions, orders, account management
├── alpacadata.py     # Data feed: historical + live streaming data
sample/               # Example strategies (SMA crossover, multi-asset, etc.)
tests/                # Unit tests
```

## Key Components

### AlpacaStore (Singleton)
Central hub managing Alpaca connections:
```python
store = alpaca_backtrader_api.AlpacaStore(
    key_id='...',
    secret_key='...',
    paper=True  # Paper trading mode
)
broker = store.getbroker()
data = store.getdata(dataname='AAPL', ...)
```

### AlpacaBroker
Backtrader broker implementation for order execution and position tracking.

### AlpacaData
Data feed supporting both historical backfill and live streaming. States: START → HISTORBACK → LIVE → OVER.

## Strategy Pattern
```python
class MyStrategy(bt.Strategy):
    params = dict(period=20)

    def __init__(self):
        self.sma = bt.ind.SMA(self.data, period=self.p.period)

    def next(self):
        if self.data.close[0] > self.sma[0] and not self.position:
            self.buy()
        elif self.data.close[0] < self.sma[0] and self.position:
            self.sell()
```

## Common Commands
```bash
# Install
pip install -e .

# Run a strategy
python sample/strategy_sma_crossover.py

# Run tests
pytest tests/
```

## Timeframes Supported
- `bt.TimeFrame.Minutes` (1, 5, 15, 60)
- `bt.TimeFrame.Days` (1)

## Key Parameters for getdata()
- `dataname`: Symbol (e.g., 'AAPL')
- `historical`: True for backtest only, False for live
- `fromdate`/`todate`: Date range
- `timeframe`: bt.TimeFrame.Days or bt.TimeFrame.Minutes
- `compression`: Bar size multiplier

## Dependencies
- backtrader >= 1.9.76.123
- alpaca-trade-api >= 1.4.3
- exchange-calendars, pandas, numpy

## Running the SMA50/70 Strategy

### Strategy Logic
- **Entry**: Buy when stock closes above SMA50
- **Exit**: Sell when stock closes below BOTH SMA50 and SMA70
- **Universe**: TSLA, NVDA, AAPL, AMZN, NFLX, AMD

### Quick Start
```bash
# 1. Install dependencies
pip install -e .

# 2. Run backtest (default mode)
python sample/strategy_sma_50_70.py

# 3. For paper trading, edit the file:
#    Set IS_BACKTEST = False
#    Set IS_LIVE = False
```

### Trading Modes
Edit `IS_BACKTEST` and `IS_LIVE` in the strategy file:
| IS_BACKTEST | IS_LIVE | Mode |
|-------------|---------|------|
| True | False | Backtest (historical data) |
| False | False | Paper trading (simulated) |
| False | True | LIVE trading (real money!) |
