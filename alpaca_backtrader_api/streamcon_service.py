import asyncio
import queue
import threading

import alpaca_trade_api as tradeapi


class Streamer:
    """
    the service is a way for to connect more than one subscriptions through
    the same websocket. so if a strategy is using more than one data (meaning
    more than one equity) we will register all to this service, and this
    service will create one websocket connection and all data will go through
    that. then we will route the response using queues to the right
    subscriber.
    """
    conn = None

    def __init__(
            self,
            api_key='',
            api_secret='',
            base_url='',
            data_stream='',
            ):

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

        self.conn.on('authenticated')(self.on_auth)
        self.conn.on(r'Q.*')(self.on_quotes)
        self.conn.on(r'account_updates')(self.on_account)
        self.conn.on(r'trade_updates')(self.on_trade)

        self.q_mapping = {}  # used to map the response q to right destination
        self.subscription_queue = queue.Queue()

        t = threading.Thread(target=self._subscription_listener)
        t.daemon = True
        t.start()

        global STREAMER
        STREAMER = self

    def _subscription_listener(self):
        """

        :return:
        """
        from datetime import datetime, timedelta
        now = datetime.now()
        channels = []
        while True:
            if datetime.now() - now > timedelta(seconds=10):
                # we want to give enough time to subscribe before we start
                # the shared subscription.
                break
            if not self.subscription_queue.empty():
                channels.extend(self.subscription_queue.get())

        self.conn.run(channels)

    def subscribe(self, q, symbol=None):
        if not symbol:
            channels = ['trade_updates']
        else:
            if self.data_stream == 'polygon':
                maps = {"quote": "Q."}
            elif self.data_stream == 'alpacadatav1':
                maps = {"quote": "alpacadatav1/Q."}
            channels = [maps["quote"] + symbol]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.q_mapping[symbol] = q
        self.subscription_queue.put(channels)

    # # Setup event handlers
    # async def on_auth(self, conn, stream, msg):
    #     pass
    #
    # async def on_listen(self, conn, stream, msg):
    #     pass

    # async def on_agg_sec(self, conn, subject, msg):
    #     self.q_mapping[msg.symbol].put(msg)
    #
    # async def on_agg_min(self, conn, subject, msg):
    #     self.q_mapping[msg.symbol].put(msg)
    #
    # async def on_account(self, conn, stream, msg):
    #     self.q_mapping[msg.symbol].put(msg)

    async def on_quotes(self, conn, subject, msg):
        msg._raw['time'] = msg.timestamp.to_pydatetime().timestamp()
        self.q_mapping[msg.symbol].put(msg._raw)

    async def on_trade(self, conn, stream, msg):
        self.q_mapping[msg.symbol].put(msg)


STREAMER = None


def get_streamer() -> Streamer:
    """
    we want to have only one instance of the Streamer. so we use this global
    which is initialized once, and now when using this we always get the same
    instance.
    """
    return STREAMER
