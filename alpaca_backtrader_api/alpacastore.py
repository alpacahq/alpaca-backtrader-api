from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import collections
from datetime import datetime, timedelta
from dateutil.parser import parse as date_parse
import time as _time
import threading
import asyncio

import alpaca_trade_api as tradeapi
import pytz
import requests
import pandas as pd

import backtrader as bt
from alpaca_trade_api.polygon.entity import NY
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


class Streamer:
    conn = None

    def __init__(
            self,
            q,
            api_key='',
            api_secret='',
            instrument='',
            method='',
            base_url='',
            data_stream='',
            *args,
            **kwargs):
        try:
            # make sure we have an event loop, if not create a new one
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        self.data_stream = data_stream
        self.conn = tradeapi.StreamConn(api_key,
                                        api_secret,
                                        base_url,
                                        data_stream=self.data_stream)
        self.instrument = instrument
        self.method = method
        self.q = q
        self.conn.on('authenticated')(self.on_auth)
        self.conn.on(r'Q.*')(self.on_quotes)
        self.conn.on(r'account_updates')(self.on_account)
        self.conn.on(r'trade_updates')(self.on_trade)

    def run(self):
        channels = []
        if not self.method:
            channels = ['trade_updates']  # 'account_updates'
        else:
            if self.data_stream == 'polygon':
                maps = {"quote": "Q."}
            elif self.data_stream == 'alpacadatav1':
                maps = {"quote": "alpacadatav1/Q."}
            channels = [maps[self.method] + self.instrument]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.conn.run(channels)

    # Setup event handlers
    async def on_auth(self, conn, stream, msg):
        pass

    async def on_listen(self, conn, stream, msg):
        pass

    async def on_quotes(self, conn, subject, msg):
        msg._raw['time'] = msg.timestamp.to_pydatetime().timestamp()
        self.q.put(msg._raw)

    async def on_agg_sec(self, conn, subject, msg):
        self.q.put(msg)

    async def on_agg_min(self, conn, subject, msg):
        self.q.put(msg)

    async def on_account(self, conn, stream, msg):
        self.q.put(msg)

    async def on_trade(self, conn, stream, msg):
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
    '''

    BrokerCls = None  # broker class will autoregister
    DataCls = None  # data class will auto register

    params = (
        ('key_id', ''),
        ('secret_key', ''),
        ('paper', False),
        ('usePolygon', False),
        ('account_tmout', 10.0),  # account balance refresh timeout
        ('api_version', None)
    )

    _DTEPOCH = datetime(1970, 1, 1)
    _ENVPRACTICE = 'paper'
    _ENVLIVE = 'live'
    _ENV_PRACTICE_URL = 'https://paper-api.alpaca.markets'
    _ENV_LIVE_URL = ''

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

        self.notifs = collections.deque()  # store notifications for cerebro

        self._env = None  # reference to cerebro for general notifications
        self.broker = None  # broker instance
        self.datas = list()  # datas that have registered over start

        self._orders = collections.OrderedDict()  # map order.ref to oid
        self._ordersrev = collections.OrderedDict()  # map oid to order.ref
        self._transpend = collections.defaultdict(collections.deque)

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
            self.q_ordercreate.put(None)
            self.q_orderclose.put(None)
            self.q_account.put(None)

    def put_notification(self, msg, *args, **kwargs):
        self.notifs.append((msg, args, kwargs))

    def get_notifications(self):
        '''Return the pending "store" notifications'''
        self.notifs.append(None)  # put a mark / threads could still append
        return [x for x in iter(self.notifs.popleft, None)]

    # Alpaca supported granularities
    _GRANULARITIES = {
        (bt.TimeFrame.Minutes, 1): '1Min',
        (bt.TimeFrame.Minutes, 5): '5Min',
        (bt.TimeFrame.Minutes, 15): '15Min',
        (bt.TimeFrame.Minutes, 60): '1H',
        (bt.TimeFrame.Days, 1): '1D',
    }

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

    def get_granularity(self, timeframe, compression):
        if timeframe == bt.TimeFrame.Minutes:
            return "minute"
        elif timeframe == bt.TimeFrame.Days:
            return "day"
        return None

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
                            data_stream='polygon' if self.p.usePolygon else
                            'alpacadatav1'
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
        :param candleFormat: (bidask, midpoint, trades)
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

        granularity = self.get_granularity(timeframe, compression)
        if granularity is None:
            e = AlpacaTimeFrameError()
            q.put(e.error_response)
            return

        dtkwargs = {'start': None, 'end': None}
        if not dtend:
            dtend = datetime.utcnow()
        if not dtbegin:
            days = 30 if 'd' in granularity else 3
            delta = timedelta(days=days)
            dtbegin = dtend - delta
        dtkwargs['start'] = dtbegin
        end_dt = None
        dtkwargs['end'] = dtend
        end_dt = dtend.isoformat()

        cdl = pd.DataFrame()
        prevdt = 0

        while True:
            try:
                start_dt = None
                if dtkwargs['start']:
                    start_dt = dtkwargs['start'].isoformat()
                if self.p.usePolygon:
                    response = \
                        self.oapi.polygon.historic_agg_v2(
                            dataname,
                            compression,
                            granularity,
                            _from=self.iso_date(start_dt),
                            to=self.iso_date(end_dt))
                else:
                    response = self.oapi.get_aggs(dataname,
                                                  compression,
                                                  granularity,
                                                  self.iso_date(start_dt),
                                                  self.iso_date(end_dt))
            except AlpacaError as e:
                print(str(e))
                q.put(e.error_response)
                q.put(None)
                return
            except Exception as e:
                print(str(e))
                q.put({'code': 'error'})
                q.put(None)
                return

            # No result from the server, most likely error
            if response.df.shape[0] == 0:
                print(response)
                q.put({'code': 'error'})
                q.put(None)
                return
            temp = response.df
            cdl.update(temp)
            cdl = pd.concat([cdl, temp])
            cdl = cdl[~cdl.index.duplicated()]
            prevdt = dtkwargs['start']
            dtkwargs['start'] = cdl.index[-1].to_pydatetime()

            if prevdt == dtkwargs['start']:  # end of the data
                break

        freq = str(compression) + ('D' if 'd' in granularity else 'T')

        cdl = cdl.resample(freq).agg({'open': 'first',
                                      'high': 'max',
                                      'low': 'min',
                                      'close': 'last',
                                      'volume': 'sum'})
        cdl = cdl.loc[
              dtbegin.replace(tzinfo=pytz.timezone(NY)):
              dtend.replace(tzinfo=pytz.timezone(NY))
              ].dropna(subset=['high'])
        records = cdl.reset_index().to_dict('records')
        for r in records:
            r['time'] = r['timestamp']
            q.put(r)
        q.put({})  # end of transmission

    def streaming_prices(self, dataname, tmout=None):
        q = queue.Queue()
        kwargs = {'q': q, 'dataname': dataname, 'tmout': tmout}
        t = threading.Thread(target=self._t_streaming_prices, kwargs=kwargs)
        t.daemon = True
        t.start()
        return q

    def _t_streaming_prices(self, dataname, q, tmout):
        if tmout is not None:
            _time.sleep(tmout)
        streamer = Streamer(q,
                            api_key=self.p.key_id,
                            api_secret=self.p.secret_key,
                            instrument=dataname,
                            method='quote',
                            base_url=self.p.base_url,
                            data_stream='polygon' if self.p.usePolygon else
                            'alpacadatav1')

        streamer.run()

    def get_cash(self):
        return self._cash

    def get_value(self):
        return self._value

    _ORDEREXECS = {
        bt.Order.Market: 'market',
        bt.Order.Limit: 'limit',
        bt.Order.Stop: 'stop',
        bt.Order.StopLimit: 'stop_limit',
    }

    def broker_threads(self):
        self.q_account = queue.Queue()
        self.q_account.put(True)  # force an immediate update
        t = threading.Thread(target=self._t_account)
        t.daemon = True
        t.start()

        self.q_ordercreate = queue.Queue()
        t = threading.Thread(target=self._t_order_create)
        t.daemon = True
        t.start()

        self.q_orderclose = queue.Queue()
        t = threading.Thread(target=self._t_order_cancel)
        t.daemon = True
        t.start()

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
        if order.exectype != bt.Order.Market:
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

        okwargs.update(**kwargs)  # anything from the user

        self.q_ordercreate.put((order.ref, okwargs,))
        return order

    def _t_order_create(self):
        while True:
            try:
                # if self.q_ordercreate.empty():
                #     continue
                msg = self.q_ordercreate.get()
                if msg is None:
                    break

                oref, okwargs = msg
                try:
                    o = self.oapi.submit_order(**okwargs)
                except Exception as e:
                    self.put_notification(e)
                    self.broker._reject(oref)
                    return
                try:
                    oid = o.id
                except Exception:
                    if 'code' in o._raw:
                        self.put_notification(o.message)
                    else:
                        self.put_notification(
                            "General error from the Alpaca server")
                    self.broker._reject(oref)
                    return

                self._orders[oref] = oid
                self.broker._submit(oref)
                if okwargs['type'] == 'market':
                    self.broker._accept(oref)  # taken immediately

                self._ordersrev[oid] = oref  # maps ids to backtrader order

                # An transaction may have happened and was stored
                tpending = self._transpend[oid]
                tpending.append(None)  # eom marker
                while True:
                    trans = tpending.popleft()
                    if trans is None:
                        break
                    self._process_transaction(oid, trans)
            except Exception as e:
                print(str(e))

    def order_cancel(self, order):
        self.q_orderclose.put(order.ref)
        return order

    def _t_order_cancel(self):
        while True:
            oref = self.q_orderclose.get()
            if oref is None:
                break

            oid = self._orders.get(oref, None)
            if oid is None:
                continue  # the order is no longer there
            try:
                self.oapi.cancel_order(oid)
            except Exception as e:
                self.put_notification(
                    "Order not cancelled: {}, {}".format(
                        oid, e))
                continue

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
            self._transpend[oid].append(trans)
        self._process_transaction(oid, trans)

    _X_ORDER_FILLED = ('partially_filled', 'filled', )

    def _process_transaction(self, oid, trans):
        try:
            oref = self._ordersrev.pop(oid)
        except KeyError:
            return

        ttype = trans['status']

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
        else:  # default action ... if nothing else
            print("Process transaction - Order type: {}".format(ttype))
            self.broker._reject(oref)
