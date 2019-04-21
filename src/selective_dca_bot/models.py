import datetime
import decimal
import pytz
import time

from datetime import timedelta
from decimal import Decimal

from termcolor import cprint
from peewee import (fn, SqliteDatabase, Model, CharField, SmallIntegerField,
                    TimestampField, FloatField, CompositeKey, TextField,
                    BooleanField, DateTimeField, SQL, DecimalField, IntegerField,
                    Window)

from . import config

import sqlite3
from io import StringIO


def init_sqlite_db(mem_db):
    # Read database to tempfile
    con = sqlite3.connect(config.SQLITE_DB_FILE)
    tempfile = StringIO()
    for line in con.iterdump():
        tempfile.write('%s\n' % line)
    con.close()
    tempfile.seek(0)

    # Create a database in memory and import from tempfile
    mem_db.cursor().executescript(tempfile.read())
    mem_db.commit()
    mem_db.row_factory = sqlite3.Row
    print("imported DB to memory")

# Load into memory?
if 0 == 1:
    db = SqliteDatabase(':memory:')
    init_sqlite_db(db)

else:
    db = SqliteDatabase(config.SQLITE_DB_FILE)



class BaseModel(Model):
    class Meta:
        database = db



class Candle(BaseModel):
    INTERVAL__1MINUTE = 1
    INTERVAL__5MINUTE = 2
    INTERVAL__15MINUTE = 3
    INTERVAL__1HOUR = 4
    INTERVAL__4HOUR = 5
    INTERVAL__1DAY = 6
    _intervals = [
        (INTERVAL__1MINUTE, "1 minute"),
        (INTERVAL__5MINUTE, "5 minutes"),
        (INTERVAL__15MINUTE, "15 minutes"),
        (INTERVAL__1HOUR, "1 hour"),
        (INTERVAL__4HOUR, "4 hours"),
        (INTERVAL__1DAY, "1 day")
    ]

    # Unique together CompositeKey fields
    market = CharField()    # e.g. EOSBTC
    interval = SmallIntegerField(choices=_intervals)
    timestamp = DateTimeField()

    open = DecimalField()
    high = DecimalField()
    low = DecimalField()
    close = DecimalField()

    # metric fields
    rsi_1min = DecimalField(null=True)

    class Meta:
        # Enforce 'unique together' constraint
        primary_key = CompositeKey('market', 'interval', 'timestamp')


    def __str__(self):
        return f"{self.market} {self.interval} {self.timestamp}"


    @property
    def timestamp_utc(self):
        return time.ctime(self.timestamp)


    @staticmethod
    def get_last_candles(market, interval, n):
        c = Candle.select(
            ).where(
                Candle.market == market,
                Candle.interval == interval
            ).order_by(Candle.timestamp.desc()
            ).limit(n)
        if not c or len(c) == 0:
            return None

        return c


    @staticmethod
    def get_last_candle(market, interval):
        return Candle.get_last_candles(market, interval, 1)


    @staticmethod
    def batch_create_candles(market, interval, candle_data):
        for d in candle_data:
            Candle.create(
                market=market,
                interval=interval,
                timestamp=d['timestamp'],
                open=d['open'],
                high=d['high'],
                low=d['low'],
                close=d['close'],
            )


    @staticmethod
    def get_historical_candles(market, interval, historical_timestamp, n):
        c = Candle.select(
            ).where(
                Candle.market == market,
                Candle.interval == interval,
                Candle.timestamp <= historical_timestamp
            ).order_by(Candle.timestamp.desc()
            ).limit(n)
        if not c or len(c) == 0:
            return None

        return c


    @staticmethod
    def get_historical_candle(market, interval, historical_timestamp):
        c = Candle.select(
            ).where(
                Candle.market == market,
                Candle.interval == interval,
                Candle.timestamp == historical_timestamp
            )
        if not c or len(c) == 0:
            return None

        return c[0]


    @staticmethod
    def get_last_candle(market, interval):
        c = Candle.get_last_candles(market, interval, 1)
        if not c:
            return None

        return c[0]


    def num_periods_from_now(self):
        if config.interval == Candle.INTERVAL__1MINUTE:
            timestamp_multiplier = 60
        elif config.interval == Candle.INTERVAL__5MINUTE:
            timestamp_multiplier = 300
        elif config.interval == Candle.INTERVAL__1HOUR:
            timestamp_multiplier = 3600
        else:
            raise Exception("Didn't implement other intervals!")

        cur_timestamp = time.mktime(datetime.datetime.now().timetuple())

        # They are already in seconds, subtract and then divide by timestamp_multiplier
        return int(abs(int(cur_timestamp - self.timestamp)) / timestamp_multiplier)


    def calculate_moving_average(self, periods):
        # Assumes we have continuous data for the full 'periods' range
        # ma = Candle.select(
        #         fn.AVG(Candle.close).over(
        #             order_by=[Candle.timestamp],
        #             start=Window.preceding(periods - 1),
        #             end=Window.CURRENT_ROW
        #         )
        #     ).where(
        #         Candle.market == self.market,
        #         Candle.interval == self.interval,
        #         Candle.timestamp <= self.timestamp
        #     ).scalar()
        ma = Decimal('0.0')
        candles = Candle.select(
            ).where(
                Candle.market == self.market,
                Candle.interval == self.interval,
                Candle.timestamp <= self.timestamp
            ).limit(periods).order_by(Candle.timestamp.desc())
        for candle in candles:
            ma += candle.close
        return ma / Decimal(periods)



class LongPosition(BaseModel):
    market = CharField()
    buy_order_id = IntegerField()
    buy_quantity = DecimalField()
    purchase_price = DecimalField()
    fees = DecimalField()
    timestamp = DateTimeField()
    watchlist = CharField()

    def __str__(self):
        return f"{self.id}: {self.market} {time.ctime(self.timestamp)}"

    def save(self, *args, **kwargs):
        self.last_updated = datetime.datetime.now()
        super(LongPosition, self).save(*args, **kwargs)

    @staticmethod
    def get_last_position(market):
        p = LongPosition.select(
            ).where(
                LongPosition.market == market
            ).limit(1)
        if p and len(p) > 0:
            return p[0]
        else:
            return None

    @staticmethod
    def get_num_positions(market=None, limit=None):
        if market:
            return LongPosition.select(
                ).where(
                    LongPosition.market == market
                ).order_by(
                    LongPosition.timestamp.desc()
                ).limit(limit).count()
        else:
            return LongPosition.select(
                ).order_by(
                    LongPosition.timestamp.desc()
                ).limit(limit).count()

    @staticmethod
    def get_results(since=timedelta(days=1)):
        yesterday = datetime.datetime.now() - since
        d = time.mktime(yesterday.timetuple())
        result = LongPosition.select(
            fn.SUM(LongPosition.profit).alias('total_profit'),
            fn.SUM(LongPosition.buy_quantity * LongPosition.purchase_price).alias('total_spent'),
            fn.SUM(LongPosition.fees).alias('total_fees'),
            fn.COUNT(LongPosition.id).alias('num_positions')
            ).where(
                # position is closed...
                (LongPosition.status << [
                    LongPosition.STATUS__CLOSED_RIDE_PROFIT,
                    LongPosition.STATUS__CLOSED_LOSS
                ]) &
                # ...within the last...
                (LongPosition.date_closed >= d)
            )

        return {
            "profit": result[0].total_profit,
            "spent": result[0].total_spent,
            "profit_percentage": result[0].total_profit / result[0].total_spent if result[0].total_profit else Decimal('0.0'),
            "num_trades": result[0].num_positions,
            "fees": result[0].total_fees,
        }

    @staticmethod
    def get_positions_since(since=timedelta(days=1)):
        yesterday = datetime.datetime.now() - since
        d = time.mktime(yesterday.timetuple())
        return LongPosition.select(
            ).where(
                LongPosition.date_closed >= d
            )

    @property
    def timestamp_str(self):
        return datetime.datetime.fromtimestamp(self.timestamp).strftime('%Y-%m-%d %H:%M:%S')

    @property
    def spent(self, exclude_fees=True):
        return self.buy_quantity * self.purchase_price



class MarketParams(BaseModel):
    EXCHANGE__BINANCE = "B"
    EXCHANGE__KUCOIN = "K"
    _market_choices = (
        (EXCHANGE__BINANCE, "Binance"),
        (EXCHANGE__KUCOIN, "Kucoin"),
    )
    exchange = CharField(default=EXCHANGE__BINANCE, choices=_market_choices)
    market = CharField()
    price_tick_size = DecimalField()
    lot_step_size = DecimalField()
    min_notional = DecimalField()

    @staticmethod
    def get_market(market, exchange=EXCHANGE__BINANCE):
        m = MarketParams.select(
            ).where(
                MarketParams.market == market,
                MarketParams.exchange == exchange
            )
        if not m or len(m) == 0:
            return None
        else:
            return m[0]


class AllTimeWatchlist(BaseModel):
    from .exchanges.constants import EXCHANGE__BINANCE    # Avoid circular deps

    exchange = CharField(default=EXCHANGE__BINANCE)
    watchlist = CharField(null=True)

    @staticmethod
    def get_watchlist(exchange=EXCHANGE__BINANCE):
        try:
            return AllTimeWatchlist.select().where(AllTimeWatchlist.exchange == exchange)[0].watchlist.split(',')
        except Exception:
            return None

    @staticmethod
    def update_watchlist(watchlist, exchange=EXCHANGE__BINANCE):
        atw = AllTimeWatchlist.select().where(AllTimeWatchlist.exchange == exchange)[0]
        alltime = set(atw.watchlist.split(','))
        alltime.update(watchlist)
        atw.watchlist = ",".join(sorted(alltime))
        atw.save()



if not Candle.table_exists():
    Candle.create_table(True)

if not LongPosition.table_exists():
    LongPosition.create_table(True)

if not MarketParams.table_exists():
    MarketParams.create_table(True)

if not AllTimeWatchlist.table_exists():
    AllTimeWatchlist.create_table(True)

