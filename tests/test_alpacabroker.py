from alpaca_backtrader_api import alpacabroker

def test_alpaca_broker():
	comminfo = alpacabroker.AlpacaCommInfo(mult=1.0, stocklike=False)
	assert comminfo.getvaluesize(1, 100.00) == 100.00