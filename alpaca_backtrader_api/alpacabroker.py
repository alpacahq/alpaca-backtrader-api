from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import collections

from backtrader import BrokerBase, Order, BuyOrder, SellOrder
from backtrader.utils.py3 import with_metaclass, iteritems
from backtrader.comminfo import CommInfoBase
from backtrader.position import Position

from alpaca_backtrader_api import alpacastore


class AlpacaCommInfo(CommInfoBase):
    def getvaluesize(self, size, price):
        # In real life the margin approaches the price
        return abs(size) * price

    def getoperationcost(self, size, price):
        """
        Returns the needed amount of cash an operation would cost
        """
        # Same reasoning as above
        return abs(size) * price


class MetaAlpacaBroker(BrokerBase.__class__):
    def __init__(cls, name, bases, dct):
        """
        Class has already been created ... register
        """
        # Initialize the class
        super(MetaAlpacaBroker, cls).__init__(name, bases, dct)
        alpacastore.AlpacaStore.BrokerCls = cls


class AlpacaBroker(with_metaclass(MetaAlpacaBroker, BrokerBase)):
    """
    Broker implementation for Alpaca.

    This class maps the orders/positions from Alpaca to the
    internal API of ``backtrader``.

    Params:

      - ``use_positions`` (default:``True``): When connecting to the broker
        provider use the existing positions to kickstart the broker.

        Set to ``False`` during instantiation to disregard any existing
        position
    """
    params = (
        ('use_positions', True),
    )

    def __init__(self, **kwargs):
        super(AlpacaBroker, self).__init__()

        self.o = alpacastore.AlpacaStore(**kwargs)

        self.orders = collections.OrderedDict()  # orders by order id
        self.notifs = collections.deque()  # holds orders which are notified

        self.opending = collections.defaultdict(list)  # pending transmission
        self.brackets = dict()  # confirmed brackets

        self.startingcash = self.cash = 0.0
        self.startingvalue = self.value = 0.0
        self.addcommissioninfo(self, AlpacaCommInfo(mult=1.0, stocklike=False))

    def update_positions(self):
        """
        this method syncs the Alpaca real broker positions and the Backtrader
        broker instance. the positions is defined in BrokerBase(in getposition)
        and used in bbroker (the backtrader broker instance) with Data as the
        key. so we do the same here. we create a defaultdict of Position() with
        data as the key.
        :return: collections.defaultdict ({data: Position})
        """
        positions = collections.defaultdict(Position)
        if self.p.use_positions:
            broker_positions = self.o.oapi.list_positions()
            broker_positions_symbols = [p.symbol for p in broker_positions]
            broker_positions_mapped_by_symbol = \
                {p.symbol: p for p in broker_positions}

            for name, data in iteritems(self.cerebro.datasbyname):
                if name in broker_positions_symbols:
                    size = int(broker_positions_mapped_by_symbol[name].qty)
                    positions[data] = Position(
                        size,
                        float(broker_positions_mapped_by_symbol[
                            name].avg_entry_price)
                    )
        return positions

    def start(self):
        super(AlpacaBroker, self).start()
        self.addcommissioninfo(self, AlpacaCommInfo(mult=1.0, stocklike=False))
        self.o.start(broker=self)
        self.startingcash = self.cash = self.o.get_cash()
        self.startingvalue = self.value = self.o.get_value()
        self.positions = self.update_positions()

    def data_started(self, data):
        pos = self.getposition(data)

        if pos.size < 0:
            order = SellOrder(data=data,
                              size=pos.size, price=pos.price,
                              exectype=Order.Market,
                              simulated=True)

            order.addcomminfo(self.getcommissioninfo(data))
            order.execute(0, pos.size, pos.price,
                          0, 0.0, 0.0,
                          pos.size, 0.0, 0.0,
                          0.0, 0.0,
                          pos.size, pos.price)

            order.completed()
            self.notify(order)

        elif pos.size > 0:
            order = BuyOrder(data=data,
                             size=pos.size, price=pos.price,
                             exectype=Order.Market,
                             simulated=True)

            order.addcomminfo(self.getcommissioninfo(data))
            order.execute(0, pos.size, pos.price,
                          0, 0.0, 0.0,
                          pos.size, 0.0, 0.0,
                          0.0, 0.0,
                          pos.size, pos.price)

            order.completed()
            self.notify(order)

    def stop(self):
        super(AlpacaBroker, self).stop()
        self.o.stop()

    def getcash(self):
        # This call cannot block if no answer is available from Alpaca
        self.cash = cash = self.o.get_cash()
        return cash

    def getvalue(self, datas=None):
        """
        if datas then we will calculate the value of the positions if not
        then the value of the entire portfolio (positions + cash)
        :param datas: list of data objects
        :return: float
        """
        if not datas:
            # don't use self.o.get_value(). it takes time for local store to
            # get update from broker.
            self.value = float(self.o.oapi.get_account().portfolio_value)
            return self.value
        else:
            # let's calculate the value of the positions
            total_value = 0
            for d in datas:
                pos = self.getposition(d)
                if pos.size:
                    price = list(d)[0]
                    total_value += price * pos.size
            return total_value

    def getposition(self, data, clone=True):
        pos = self.positions[data]
        if clone:
            pos = pos.clone()

        return pos

    def orderstatus(self, order):
        o = self.orders[order.ref]
        return o.status

    def _submit(self, oref):
        order = self.orders[oref]
        order.submit(self)
        self.notify(order)
        for o in self._bracketnotif(order):
            o.submit(self)
            self.notify(o)

    def _reject(self, oref):
        order = self.orders[oref]
        order.reject(self)
        self.notify(order)
        self._bracketize(order, cancel=True)

    def _accept(self, oref):
        order = self.orders[oref]
        order.accept()
        self.notify(order)
        for o in self._bracketnotif(order):
            o.accept(self)
            self.notify(o)

    def _cancel(self, oref):
        order = self.orders[oref]
        order.cancel()
        self.notify(order)
        self._bracketize(order, cancel=True)

    def _expire(self, oref):
        order = self.orders[oref]
        order.expire()
        self.notify(order)
        self._bracketize(order, cancel=True)

    def _bracketnotif(self, order):
        pref = getattr(order.parent, 'ref', order.ref)  # parent ref or self
        br = self.brackets.get(pref, None)  # to avoid recursion
        return br[-2:] if br is not None else []

    def _bracketize(self, order, cancel=False):
        pref = getattr(order.parent, 'ref', order.ref)  # parent ref or self
        br = self.brackets.pop(pref, None)  # to avoid recursion
        if br is None:
            return

        if not cancel:
            if len(br) == 3:  # all 3 orders in place, parent was filled
                br = br[1:]  # discard index 0, parent
                for o in br:
                    o.activate()  # simulate activate for children
                self.brackets[pref] = br  # not done - reinsert children

            elif len(br) == 2:  # filling a children
                oidx = br.index(order)  # find index to filled (0 or 1)
                self._cancel(br[1 - oidx].ref)  # cancel remaining (1 - 0 -> 1)
        else:
            # Any cancellation cancel the others
            for o in br:
                if o.alive():
                    self._cancel(o.ref)

    def _fill(self, oref, size, price, ttype, **kwargs):
        order = self.orders[oref]
        data = order.data
        pos = self.getposition(data, clone=False)
        psize, pprice, opened, closed = pos.update(size, price)

        closedvalue = closedcomm = 0.0
        openedvalue = openedcomm = 0.0
        margin = pnl = 0.0

        order.execute(data.datetime[0], size, price,
                      closed, closedvalue, closedcomm,
                      opened, openedvalue, openedcomm,
                      margin, pnl,
                      psize, pprice)

        if order.executed.remsize:
            order.partial()
            self.notify(order)
        else:
            order.completed()
            self.notify(order)
            self._bracketize(order)

    def _transmit(self, order):
        oref = order.ref
        pref = getattr(order.parent, 'ref', oref)  # parent ref or self
        if order.transmit:
            if oref != pref:  # children order
                # Put parent in orders dict, but add stopside and takeside
                # to order creation. Return the takeside order, to have 3s
                takeside = order  # alias for clarity
                parent, stopside = self.opending.pop(pref)
                for o in parent, stopside, takeside:
                    self.orders[o.ref] = o  # write them down

                self.brackets[pref] = [parent, stopside, takeside]
                self.o.order_create(parent, stopside, takeside)
                return takeside  # parent was already returned

            else:  # Parent order, which is not being transmitted
                self.orders[order.ref] = order
                return self.o.order_create(order)

        # Not transmitting
        self.opending[pref].append(order)
        return order

    def buy(self, owner, data,
            size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            parent=None, transmit=True,
            **kwargs):

        order = BuyOrder(owner=owner, data=data,
                         size=size, price=price, pricelimit=plimit,
                         exectype=exectype, valid=valid, tradeid=tradeid,
                         trailamount=trailamount, trailpercent=trailpercent,
                         parent=parent, transmit=transmit)

        order.addinfo(**kwargs)
        order.addcomminfo(self.getcommissioninfo(data))
        return self._transmit(order)

    def sell(self, owner, data,
             size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None,
             parent=None, transmit=True,
             **kwargs):

        order = SellOrder(owner=owner, data=data,
                          size=size, price=price, pricelimit=plimit,
                          exectype=exectype, valid=valid, tradeid=tradeid,
                          trailamount=trailamount, trailpercent=trailpercent,
                          parent=parent, transmit=transmit)

        order.addinfo(**kwargs)
        order.addcomminfo(self.getcommissioninfo(data))
        return self._transmit(order)

    def cancel(self, order):
        if not self.orders.get(order.ref, False):
            return
        if order.status == Order.Cancelled:  # already cancelled
            return

        return self.o.order_cancel(order)

    def notify(self, order):
        self.positions = self.update_positions()
        self.notifs.append(order.clone())

    def get_notification(self):
        if not self.notifs:
            return None

        return self.notifs.popleft()

    def next(self):
        self.notifs.append(None)  # mark notification boundary
