from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
from curses import has_key
import logging
import os
import collections
import time
from enum import Enum
import traceback

from datetime import datetime, timedelta, time as dtime
from typing import Tuple
from dateutil.parser import parse as date_parse
import time as _time
import exchange_calendars
import threading
import asyncio

import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame
from alpaca_trade_api.stream import Stream
import pytz
import requests

import backtrader as bt
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import queue, with_metaclass


# Extend the exceptions to support extra cases
class AlpacaError(Exception):
    """ Generic error class, catches Alpaca response errors
    """

    def __init__(self, error_response):
        self.error_response = error_response
        msg = "Alpaca API returned error code %s (%s) " % \
              (error_response['code'], error_response['message'])

        super(AlpacaError, self).__init__(msg)


class AlpacaRequestError(AlpacaError):
    def __init__(self):
        er = dict(code=599, message='Request Error', description='')
        super(self.__class__, self).__init__(er)


class AlpacaStreamError(AlpacaError):
    def __init__(self, content=''):
        er = dict(code=598, message='Failed Streaming', description=content)
        super(self.__class__, self).__init__(er)


class AlpacaTimeFrameError(AlpacaError):
    def __init__(self, content):
        er = dict(code=597, message='Not supported TimeFrame', description='')
        super(self.__class__, self).__init__(er)


class AlpacaNetworkError(AlpacaError):
    def __init__(self):
        er = dict(code=596, message='Network Error', description='')
        super(self.__class__, self).__init__(er)


class API(tradeapi.REST):

    def _request(self,
                 method,
                 path,
                 data=None,
                 base_url=None,
                 api_version=None):

        # Added the try block
        try:
            return super(API, self)._request(
                method, path, data, base_url, api_version)
        except requests.RequestException as e:
            resp = AlpacaRequestError().error_response
            resp['description'] = str(e)
            return resp
        except tradeapi.rest.APIError as e:
            # changed from raise to return
            return e._error
        except Exception as e:
            resp = AlpacaNetworkError().error_response
            resp['description'] = str(e)
            return resp

        return None


class Granularity(Enum):
    Ticks = "ticks"
    Daily = "day"
    Minute = "minute"


class StreamingMethod(Enum):
    AccountUpdate = 'account_update'
    Quote = "quote"
    MinuteAgg = "minute_agg"


class Streamer:
    conn = None

    def __init__(
            self,
            q,
            api_key='',
            api_secret='',
            instrument='',
            method: StreamingMethod = StreamingMethod.AccountUpdate,
            base_url='',
            data_url='',
            data_feed='iex',
            *args,
            **kwargs):
        try:
            # make sure we have an event loop, if not create a new one
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        self.logger = logging.getLogger(self.__class__.__name__)
        self.conn = Stream(api_key,
                           api_secret,
                           base_url,
                           data_stream_url=data_url,
                           data_feed=data_feed)
        self.instrument = instrument
        self.method = method
        self.q = q

    def run(self):
        self.logger.info("Starting streamer for: %s %s" % (self.instrument, self.method.name))
        if self.method == StreamingMethod.AccountUpdate:
            self.conn.subscribe_trade_updates(self.on_trade)
        elif self.method == StreamingMethod.MinuteAgg:
            self.conn.subscribe_bars(self.on_agg_min, self.instrument)
        elif self.method == StreamingMethod.Quote:
            self.conn.subscribe_quotes(self.on_quotes, self.instrument)

        # this code runs in a new thread. we need to set the loop for it
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.conn.run()

    async def on_listen(self, conn, stream, msg):
        pass

    async def on_quotes(self, msg):
        msg._raw['time'] = msg.timestamp
        self.logger.debug("Got: %s" % msg)
        self.q.put(msg._raw)

    async def on_agg_min(self, msg):
        msg._raw['time'] = msg.timestamp
        self.logger.debug("Got: %s" % msg)
        self.q.put(msg._raw)

    async def on_account(self, msg):
        self.logger.debug("Got: %s" % msg)
        self.q.put(msg)

    async def on_trade(self, msg):
        self.logger.debug("Got: %s" % msg)
        self.q.put(msg)


class MetaSingleton(MetaParams):
    '''Metaclass to make a metaclassed class a singleton'''

    def __init__(cls, name, bases, dct):
        super(MetaSingleton, cls).__init__(name, bases, dct)
        cls._singleton = None

    def __call__(cls, *args, **kwargs):
        if cls._singleton is None:
            cls._singleton = (
                super(MetaSingleton, cls).__call__(*args, **kwargs))

        return cls._singleton


class AlpacaStore(with_metaclass(MetaSingleton, object)):
    '''Singleton class wrapping to control the connections to Alpaca.

    Params:

      - ``key_id`` (default:``None``): Alpaca API key id

      - ``secret_key`` (default: ``None``): Alpaca API secret key

      - ``paper`` (default: ``False``): use the paper trading environment

      - ``account_tmout`` (default: ``10.0``): refresh period for account
        value/cash refresh

      - ``order_tmout`` (default: ``0.05``): how often the order creation queue
        is checked within _t_create_order
    '''

    BrokerCls = None  # broker class will autoregister
    DataCls = None  # data class will auto register

    params = (
        ('key_id', ''),
        ('secret_key', ''),
        ('paper', False),
        ('account_tmout', 10.0),  # account balance refresh timeout
        ('order_tmout', 0.05),   
        ('api_version', None)
    )

    _DTEPOCH = datetime(1970, 1, 1)
    _ENVPRACTICE = 'paper'
    _ENVLIVE = 'live'
    _ENV_PRACTICE_URL = 'https://paper-api.alpaca.markets'
    _ENV_LIVE_URL = 'https://api.alpaca.markets'
    _ENV_DATA_URL = 'https://data.alpaca.markets'

    @classmethod
    def getdata(cls, *args, **kwargs):
        '''Returns ``DataCls`` with args, kwargs'''
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        '''Returns broker with *args, **kwargs from registered ``BrokerCls``'''
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self):
        super(AlpacaStore, self).__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        self.notifs = collections.deque()  # store notifications for cerebro

        self._env = None  # reference to cerebro for general notifications
        self.broker = None  # broker instance
        self.datas = list()  # datas that have registered over start

        self._orders = collections.OrderedDict()  # map order.ref to oid
        self._ordersrev = collections.OrderedDict()  # map oid to order.ref
        self._transpend = collections.defaultdict(collections.deque)
        self._cancel_pending = {}

        if self.p.paper:
            self._oenv = self._ENVPRACTICE
            self.p.base_url = self._ENV_PRACTICE_URL
        else:
            self._oenv = self._ENVLIVE
            self.p.base_url = self._ENV_LIVE_URL
        self.oapi = API(self.p.key_id,
                        self.p.secret_key,
                        self.p.base_url,
                        self.p.api_version)
        self.data_api = API(self.p.key_id,
                        self.p.secret_key,
                        self._ENV_DATA_URL,
                        self.p.api_version)

        self._cash = 0.0
        self._value = 0.0
        self._evt_acct = threading.Event()

    def start(self, data=None, broker=None):
        # Datas require some processing to kickstart data reception
        if data is None and broker is None:
            self.cash = None
            return

        if data is not None:
            self._env = data._env
            # For datas simulate a queue with None to kickstart co
            self.datas.append(data)

            if self.broker is not None:
                self.broker.data_started(data)

        elif broker is not None:
            self.broker = broker
            self.streaming_events()
            self.broker_threads()

    def stop(self):
        # signal end of thread
        if self.broker is not None:
            self.q_order.put(None)
            #self.q_orderclose.put(None)
            self.q_account.put(None)

    def put_notification(self, msg, *args, **kwargs):
        self.notifs.append((msg, args, kwargs))

    def get_notifications(self):
        '''Return the pending "store" notifications'''
        self.notifs.append(None)  # put a mark / threads could still append
        return [x for x in iter(self.notifs.popleft, None)]

    # Alpaca supported granularities
    _GRANULARITIES = {
        (bt.TimeFrame.Minutes, 1):  '1Min',
        (bt.TimeFrame.Minutes, 5):  '5Min',
        (bt.TimeFrame.Minutes, 15): '15Min',
        (bt.TimeFrame.Minutes, 60): '1H',
        (bt.TimeFrame.Days, 1):     '1D',
    }

    def get_orders(self):
        try:
            orders = self.oapi.list_orders()
        except (AlpacaError, AlpacaRequestError,):
            return []
        if orders:
            if 'code' in orders[0]._raw:
                return []
        return orders


    def get_positions(self):
        try:
            positions = self.oapi.list_positions()
        except (AlpacaError, AlpacaRequestError,):
            return []
        if positions:
            if 'code' in positions[0]._raw:
                return []
        # poslist = positions.get('positions', [])
        return positions

    def get_granularity(self, timeframe, compression) -> Granularity:
        if timeframe == bt.TimeFrame.Ticks:
            return Granularity.Ticks
        if timeframe == bt.TimeFrame.Minutes:
            return Granularity.Minute
        elif timeframe == bt.TimeFrame.Days:
            return Granularity.Daily

    def get_instrument(self, dataname):
        try:
            insts = self.oapi.get_asset(dataname)
        except (AlpacaError, AlpacaRequestError,):
            return None

        return insts or None

    def streaming_events(self, tmout=None):
        q = queue.Queue()
        kwargs = {'q': q, 'tmout': tmout}

        t = threading.Thread(target=self._t_streaming_listener, kwargs=kwargs)
        t.daemon = True
        t.start()

        t = threading.Thread(target=self._t_streaming_events, kwargs=kwargs)
        t.daemon = True
        t.start()
        return q

    def _t_streaming_listener(self, q, tmout=None):
        while True:
            trans = q.get()
            self._transaction(trans.order)

    def _t_streaming_events(self, q, tmout=None):
        if tmout is not None:
            _time.sleep(tmout)
        streamer = Streamer(q,
                            api_key=self.p.key_id,
                            api_secret=self.p.secret_key,
                            base_url=self.p.base_url,
                            data_url=os.environ.get("DATA_PROXY_WS", ''),
                            )

        streamer.run()

    def candles(self, dataname, dtbegin, dtend, timeframe, compression,
                candleFormat, includeFirst):
        """

        :param dataname: symbol name. e.g AAPL
        :param dtbegin: datetime start
        :param dtend: datetime end
        :param timeframe: bt.TimeFrame
        :param compression: distance between samples. e.g if 1 =>
                 get sample every day. if 3 => get sample every 3 days
        :param candleFormat: (bidask, midpoint, trades) - not used we get bars
        :param includeFirst:
        :return:
        """

        kwargs = locals().copy()
        kwargs.pop('self')
        kwargs['q'] = q = queue.Queue()
        t = threading.Thread(target=self._t_candles, kwargs=kwargs)
        t.daemon = True
        t.start()
        return q

    @staticmethod
    def iso_date(date_str):
        """
        this method will make sure that dates are formatted properly
        as with isoformat
        :param date_str:
        :return: YYYY-MM-DD date formatted
        """
        return date_parse(date_str).date().isoformat()

    def _t_candles(self, dataname, dtbegin, dtend, timeframe, compression,
                   candleFormat, includeFirst, q):
        granularity: Granularity = self.get_granularity(timeframe, compression)
        dtbegin, dtend = self._make_sure_dates_are_initialized_properly(
            dtbegin, dtend, granularity)
        self.logger.info(f"Fetching candles from {dtbegin} to {dtend}")

        if granularity is None:
            e = AlpacaTimeFrameError('granularity is missing')
            q.put(e.error_response)
            return
        try:
            cdl = self.get_aggs_from_alpaca(dataname,
                                            dtbegin,
                                            dtend,
                                            granularity,
                                            compression)
        except AlpacaError as e:
            print(str(e))
            q.put(e.error_response)
            q.put(None)
            return
        except Exception:
            traceback.print_exc()
            q.put({'code': 'error'})
            q.put(None)
            return

        # don't use dt.replace. use localize
        # (https://stackoverflow.com/a/1592837/2739124)
        if not cdl.empty:
            cdl = cdl.loc[
                pytz.utc.localize(dtbegin) if
                not dtbegin.tzname() else dtbegin:
                pytz.utc.localize(dtend) if
                not dtend.tzname() else dtend
                ].dropna(subset=['high'])
            records = cdl.reset_index().to_dict('records')
            for r in records:
                r['time'] = r['timestamp']
                q.put(r)
            q.put({})  # end of transmission

    def _make_sure_dates_are_initialized_properly(self, dtbegin, dtend,
                                                  granularity):
        """
        dates may or may not be specified by the user.
        when they do, they are probably don't include NY timezome data
        also, when granularity is minute, we want to make sure we get data when
        market is opened. so if it doesn't - let's set end date to be last
        known minute with opened market.
        this nethod takes care of all these issues.
        :param dtbegin:
        :param dtend:
        :param granularity:
        :return:
        """
        #if not dtend:
        #    dtend = pd.Timestamp('now', tz=pytz.utc)
        #else:
        #    dtend = pd.Timestamp(pytz.utc.localize(dtend)) if \
        #      not dtend.tzname() else dtend
        #if granularity == Granularity.Minute:
        #    calendar = exchange_calendars.get_calendar(name='NYSE')
        #    if calendar.is_open_on_minute(dtend.ceil(freq='T')):
        #        dtend = calendar.previous_open(dtend)
        #if not dtbegin:
        #    days = 30 if granularity == Granularity.Daily else 3
        #    delta = timedelta(days=days)
        #    dtbegin = dtend - delta
        #else:
        #    dtbegin = pd.Timestamp(pytz.utc.localize(dtbegin)) if \
        #      not dtbegin.tzname() else dtbegin
        #while dtbegin > dtend:
        #    # if we start the script during market hours we could get this
        #    # situation. this resolves that.
        #    dtbegin -= timedelta(days=1)
        #return dtbegin.astimezone(pytz.utc), dtend.astimezone(pytz.utc)

        return dtbegin.replace(tzinfo = pytz.utc), dtend.replace(tzinfo = pytz.utc)

    def get_aggs_from_alpaca(self,
                             dataname,
                             start,
                             end,
                             granularity: Granularity,
                             compression):
        """
        https://alpaca.markets/docs/api-documentation/api-v2/market-data/bars/
        Alpaca API as a limit of 1000 records per api call. meaning, we need to
        do multiple calls to get all the required data if the date range is
        large.
        also, the alpaca api does not support compression (or, you can't get
        5 minute bars e.g) so we need to resample the received bars.
        also, we need to drop out of market records.
        this function does all of that.

        note:
        this was the old way of getting the data
          response = self.oapi.get_aggs(dataname,
                                        compression,
                                        granularity,
                                        self.iso_date(start_dt),
                                        self.iso_date(end_dt))
          the thing is get_aggs work nicely for days but not for minutes, and
          it is not a documented API. barset on the other hand does
          but we need to manipulate it to be able to work with it
          smoothly
        """

        def _granularity_to_timeframe(granularity):
            if granularity in [Granularity.Minute, Granularity.Ticks]:
                timeframe = TimeFrame.Minute
            elif granularity == Granularity.Daily:
                timeframe = TimeFrame.Day
            elif granularity == 'ticks':
                timeframe = "minute"
            else:
                # default to day if not configured properly. subject to
                # change.
                timeframe = TimeFrame.Day
            return timeframe

        def _get_bars():
            """
            """
            timeframe = _granularity_to_timeframe(granularity)
            self.logger.debug(f"Getting bars for: {dataname} from: {start} to {end} by {compression} {granularity}")
            try:
                response = self.data_api.get_bars(dataname,
                                        timeframe,
                                        start.isoformat(),
                                    end.isoformat())
                return response.df
            except RuntimeError as e:
                self.logger.warn("Got empty response from _get_bars!")
                return None

        def _clear_out_of_market_hours(df):
            """
            only interested in samples between 9:30, 16:00 NY time, which is 14:30 to 21:00 UTC
            """
            if df.empty:
                return df  
            return df.between_time("14:30", "21:00")

        def _drop_early_samples(df):
            """
            samples from server don't start at 9:30 NY time (14:30 UTC)
            let's drop earliest samples
            """
            if df.empty:
                return df  
            for i, b in df.iterrows():
                if i.time() >= dtime(14, 30):
                    return df[i:]

        def _resample(df):
            """
            samples returned with certain window size (1 day, 1 minute) user
            may want to work with different window size (5min)
            """
            if df.empty:
                return df  

            if granularity == Granularity.Minute:
                sample_size = f"{compression}Min"
            else:
                sample_size = f"{compression}D"
            df = df.resample(sample_size).agg(
                collections.OrderedDict([
                    ('open', 'first'),
                    ('high', 'max'),
                    ('low', 'min'),
                    ('close', 'last'),
                    ('volume', 'sum'),
                ])
            )
            if granularity == Granularity.Minute:
                return _clear_out_of_market_hours(df)
            else:
                return df

        if not start:
            start = end - timedelta(days=1)
        response = _get_bars()
        while response.empty: #for free accounts you cannot request the last 15 minutes of data, this results as an empty response
                end = end - timedelta(minutes=15)
                self.logger.debug(f"Got empty response! Trying bars for: {dataname} from: {start} to {end} by {compression} {granularity}")
                response = _get_bars()

        self.logger.debug(f"Got: {response}")
        if not response.empty:
            cdl = response
            if granularity == Granularity.Minute:
                cdl = _clear_out_of_market_hours(cdl)
                cdl = _drop_early_samples(cdl)
            if compression != 1:
                response = _resample(cdl)
            else:
                response = cdl
        response = response.dropna()
        response = response[~response.index.duplicated()]
        self.logger.debug(f"Response: {response}")
        return response

    def streaming_prices(self,
                         dataname, timeframe, tmout=None, data_feed='iex'):
        q = queue.Queue()
        kwargs = {'q':         q,
                  'dataname':  dataname,
                  'timeframe': timeframe,
                  'data_feed': data_feed,
                  'tmout':     tmout}
        t = threading.Thread(target=self._t_streaming_prices, kwargs=kwargs)
        t.daemon = True
        t.start()
        return q

    def _t_streaming_prices(self, dataname, timeframe, q, tmout, data_feed):
        if tmout is not None:
            _time.sleep(tmout)

        if timeframe == bt.TimeFrame.Ticks:
            method = StreamingMethod.Quote
        elif timeframe == bt.TimeFrame.Minutes:
            method = StreamingMethod.MinuteAgg
        else:
            method = StreamingMethod.MinuteAgg

        streamer = Streamer(q,
                            api_key=self.p.key_id,
                            api_secret=self.p.secret_key,
                            instrument=dataname,
                            method=method,
                            base_url=self.p.base_url,
                            data_url=os.environ.get("DATA_PROXY_WS", ''),
                            data_feed=data_feed)

        streamer.run()

    def get_cash(self):
        return self._cash

    def get_value(self):
        return self._value

    _ORDEREXECS = {
        bt.Order.Market:    'market',
        bt.Order.Limit:     'limit',
        bt.Order.Stop:      'stop',
        bt.Order.StopLimit: 'stop_limit',
        bt.Order.StopTrail: 'trailing_stop',
    }

    def broker_threads(self):
        self.q_account = queue.Queue()
        self.q_account.put(True)  # force an immediate update
        t = threading.Thread(target=self._t_account)
        t.daemon = True
        t.start()

        self.q_order = queue.Queue()
        t = threading.Thread(target=self._t_order)
        t.daemon = True
        t.start()

        #self.q_ordercreate = queue.Queue()
        #t = threading.Thread(target=self._t_order_create)
        #t.daemon = True
        #t.start()

        #self.q_orderclose = queue.Queue()
        #t = threading.Thread(target=self._t_order_cancel)
        #t.daemon = True
        #t.start()

        # Wait once for the values to be set
        self._evt_acct.wait(self.p.account_tmout)

    def _t_account(self):
        while True:
            try:
                msg = self.q_account.get(timeout=self.p.account_tmout)
                if msg is None:
                    break  # end of thread
            except queue.Empty:  # tmout -> time to refresh
                pass

            try:
                accinfo = self.oapi.get_account()
            except Exception as e:
                self.put_notification(e)
                continue

            if 'code' in accinfo._raw:
                self.put_notification(accinfo.message)
                continue
            try:
                self._cash = float(accinfo.cash)
                self._value = float(accinfo.portfolio_value)
            except KeyError:
                pass

            self._evt_acct.set()

    def order_create(self, order, stopside=None, takeside=None, **kwargs):
        okwargs = dict()
        # different data feeds may set _name or _dataname so we cover both
        okwargs['symbol'] = order.data._name if order.data._name else \
            order.data._dataname
        okwargs['qty'] = abs(int(order.created.size))
        okwargs['side'] = 'buy' if order.isbuy() else 'sell'
        okwargs['type'] = self._ORDEREXECS[order.exectype]
        okwargs['time_in_force'] = "gtc"
        if order.exectype not in [bt.Order.Market, bt.Order.StopTrail,
                                  bt.Order.Stop]:
            okwargs['limit_price'] = str(order.created.price)

        if order.exectype in [bt.Order.StopLimit, bt.Order.Stop]:
            okwargs['stop_price'] = order.created.pricelimit

        # Not supported in the alpaca api
        # if order.exectype == bt.Order.StopTrail:
        #     okwargs['trailingStop'] = order.trailamount

        if stopside:
            okwargs['stop_loss'] = {'stop_price': stopside.price}

        if takeside:
            okwargs['take_profit'] = {'limit_price': takeside.price}

        if stopside or takeside:
            okwargs['order_class'] = "bracket"

        if order.exectype == bt.Order.StopTrail:
            if order.trailpercent and order.trailamount:
                raise Exception("You can't create trailing stop order with "
                                "both TrailPrice and TrailPercent. choose one")
            if order.trailpercent:
                okwargs['trail_percent'] = order.trailpercent
            elif order.trailamount:
                okwargs['trail_price'] = order.trailamount
            else:
                raise Exception("You must provide either trailpercent or "
                                "trailamount when creating StopTrail order")

        # anything from the user
        okwargs.update(order.info)
        okwargs.update(**kwargs)

        self.q_order.put((order.ref, okwargs,))
        return order

    def _t_order(self):
        while True:
            try:
                try:
                    msg = self.q_order.get(timeout=self.p.order_tmout)
                    if msg is None: 
                        continue
                    if isinstance(msg, tuple):
                        oref, okwargs = msg
                        self._t_order_create(oref, okwargs)
                    else:
                        self._t_order_cancel(msg)
                except queue.Empty:
                    continue
            except Exception as e:
                traceback.print_exc()

    def _t_order_create(self, oref, okwargs):
        def _check_if_transaction_occurred(order_id):
            # a transaction may have happened and was stored. if so let's
            # process it
            tpending = self._transpend[order_id]
            tpending.append(None)  # eom marker
            while True:
                trans = tpending.popleft()
                if trans is None:
                    break
                self._process_transaction(order_id, trans)

        try:
            self.logger.debug(f"Submitting order {oref} {okwargs}")
            o = self.oapi.submit_order(**okwargs)
            self.logger.debug(f"Order successfully submitted order {oref} (res: {o})")
            oid = o.id
            if okwargs['type'] == 'market':
                self.broker._accept(oref)  # taken immediately

            self._orders[oref] = oid
            self._ordersrev[oid] = oref  # maps ids to backtrader order
            _check_if_transaction_occurred(oid)
            if o.legs:
                index = 1
                for leg in o.legs:
                    self._orders[oref + index] = leg.id
                    self._ordersrev[leg.id] = oref + index
                    _check_if_transaction_occurred(leg.id)
                #this seems entirely broken
                self.broker._submit(oref)  # inside it submits the legs too
                if okwargs['type'] == 'market':
                    self.broker._accept(oref)  # taken immediately

        except Exception as e:
            self.logger.error(f"Error handling submitted order {oref} {okwargs}", exc_info=e)
            if 'code' in o._raw:
                desc = o.description if hasattr(o, "description") else ''
                self.put_notification(f"error submitting order "
                                        f"code: {o.code}. msg: "
                                        f"{o.message}, desc: {desc}")
            else:
                self.put_notification(
                    f"General error from the Alpaca server: {e}")
            self.broker._reject(oref)
            pass

        

    def order_cancel(self, order):
        self.q_order.put(order.ref)

    def _t_order_cancel(self, oref):
        oid = self._orders.get(oref, None)
        if oid is None:
            self.logger.warning(f"Cannot cancel unknown order: {oid} (ref: {oref})")
            pass  # the order is no longer there
        try:
            self.logger.debug(f"Canceling order: {oid}")
            self.oapi.cancel_order(oid)
        except Exception as e:
            self.put_notification(
                "Order not cancelled: {}, {}".format(
                    oid, e))
            pass

        self._cancel_pending[oref] = oid
        #wait for cancelation to succeed, helps avoid errors with future orders
        count = 0
        while count <= 5 and oref in self._cancel_pending:
            count += 1
            time.sleep(1)
        if not oref in self._cancel_pending:
            self.logger.debug(f"Successfully canceled order: {oid}")
        else:
            self._cancel_pending.pop(oref, None)
            self.logger.warning(f"Timeout waiting for cancel on {oid}.  Giving up...")
            self.broker._cancel(oref)

    _X_ORDER_CREATE = (
        'new',
        'accepted',
        'pending_new',
        'accepted_for_bidding',
    )

    def _transaction(self, trans):
        # Invoked from Streaming Events. May actually receive an event for an
        # oid which has not yet been returned after creating an order. Hence
        # store if not yet seen, else forward to processer

        oid = trans['id']
        if not self._ordersrev.get(oid, False):
            self.logger.info(f"Storing pending transaction for {oid}")
            self._transpend[oid].append(trans)
        else:
            self._process_transaction(oid, trans)

    _X_ORDER_FILLED = ('partially_filled', 'filled',)

    _X_ORDER_FINAL = ('filled', 'rejected', 'canceled', 'expired')

    def _process_transaction(self, oid, trans):
        oref = self._ordersrev.get(oid, False)
        if not oref: 
            self.logger.warning(f"Unable to find oref for oid = {oid} (type = {ttype})", stack_info=True)
            return

        ttype = trans['status']
        self.logger.debug(f"Processing transaction for oid = {oid} (oref = {oref}, type = {ttype})")

        if ttype in self._X_ORDER_FINAL:
            self._ordersrev.pop(oid, None) #we won't see anymore updates for this order

        if ttype in self._X_ORDER_FILLED:
            size = float(trans['filled_qty'])
            if trans['side'] == 'sell':
                size = -size
            price = float(trans['filled_avg_price'])
            self.broker._fill(oref, size, price, ttype=ttype)
        elif ttype in self._X_ORDER_CREATE:
            self.broker._accept(oref)
            self._ordersrev[oid] = oref
        elif ttype == 'calculated':
            return
        elif ttype == 'expired':
            self.broker._expire(oref)
        elif ttype == 'canceled': #seems like somtimes we only see the `pending_cancel` notification, and this seems to be enough
            self._cancel_pending.pop(oref, None)
            self.broker._cancel(oref)
        elif ttype == 'rejected':
            self.broker._reject(oref)
        elif ttype == 'pending_cancel':
            return
        else:  # default action ... if nothing else
            self.logger.warning(f"Ingnoring unknown transaction type: {ttype} for order: {oref} (oid = {oid})")
            return
