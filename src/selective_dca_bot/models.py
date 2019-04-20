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

from selective_dca_bot import config

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



class Balance(BaseModel):
    date_created = TimestampField(default=datetime.datetime.now)
    asset = CharField(default='BTC')
    balance = DecimalField()
    is_test = BooleanField(default=True)

    @staticmethod
    def get_current_balance(asset='BTC'):
        b = Balance.select(
            ).where(
                Balance.asset == asset,
                Balance.is_test == config.is_test
            ).order_by(-Balance.id).limit(1)
        if b.exists():
            return b[0].balance
        else:
            return None


    @staticmethod
    def get_initial_balance(asset='BTC'):
        b = Balance.select(
            ).where(
                Balance.asset == asset,
                Balance.is_test == config.is_test
            ).order_by(Balance.id).limit(1)
        if b.exists():
            return b[0].balance
        else:
            return None


    @staticmethod
    def set_balance(new_current_balance, asset='BTC'):
        b = Balance.select(
            ).where(
                Balance.asset == asset,
                Balance.is_test == config.is_test
            ).order_by(-Balance.id).limit(1)

        # Create a new Balance if there's no previous entry or if the balance has changed.
        if not b or len(b) == 0 or b[0].balance != new_current_balance:
            Balance.create(
                asset=asset,
                balance=new_current_balance,
                is_test=config.is_test
            )


    @staticmethod
    def increment_balance(amount, asset='BTC'):
        """
            We always preserve the Balance at each point in time so this
                just creates a new Balance with the updated total.
        """
        b = Balance.select(
            ).where(
                Balance.asset == asset,
                Balance.is_test == config.is_test
            ).order_by(-Balance.id).limit(1)[0]

        Balance.create(
            asset=asset,
            balance=(b.balance + amount).quantize(Decimal('0.00000001'), rounding=decimal.ROUND_DOWN),
            is_test=config.is_test
        )


    @staticmethod
    def reset_test_balance(initial_BTC_balance=Decimal('0.05'), initial_BNB_balance=Decimal('0.005')):
        if config.verbose:
            print(f"Reseting test balance to {initial_BTC_balance} BTC / {initial_BNB_balance} BNB")
        Balance.delete().where(Balance.is_test == True).execute()  # noqa: E712,E501; query fails with 'is'
        Balance.create(
            asset='BTC',
            balance=initial_BTC_balance,
            is_test=True
        )
        Balance.create(
            asset='BNB',
            balance=initial_BNB_balance,
            is_test=True
        )



class ExchangeTokenReload(BaseModel):
    """
        Log exchange token buys separately from LongPositions to avoid any confusion
        about open trades vs exchange token reloads.
    """
    market = CharField()
    date_created = DateTimeField(default=datetime.datetime.now)
    buy_quantity = DecimalField()
    purchase_price = DecimalField()
    fees = DecimalField()



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

    @staticmethod
    def current_profit():
        markets = [lp.market for lp in LongPosition.select(LongPosition.market).distinct()]

        results = []
        result_str = ""
        total_net = Decimal('0.0')
        total_spent = Decimal('0.0')
        for market in markets:
            current_price = Candle.select(
                ).where(
                    Candle.market == market
                ).order_by(
                    Candle.timestamp.desc()
                ).limit(1)[0].close

            (quantity, spent) = LongPosition.select(
                    fn.SUM(LongPosition.buy_quantity),
                    fn.SUM(LongPosition.buy_quantity * LongPosition.purchase_price)
                ).where(
                    LongPosition.market == market
                ).scalar(as_tuple=True)

            quantity = Decimal(quantity)
            spent = Decimal(spent)

            current_value = quantity * current_price

            profit = (current_value - spent).quantize(Decimal('0.00000001'))
            total_net += profit
            total_spent += spent
            profit_percentage = (current_value / spent * Decimal('100.0')).quantize(Decimal('0.01'))

            results.append({
                "market": market,
                "profit": profit,
                "profit_percentage": profit_percentage
            })

        total_percentage = (total_net / total_spent * Decimal('100.0')).quantize(Decimal('0.01'))
        for result in sorted(results, key=lambda i: i['profit'], reverse=True):
            result_str += f"{'{:>8}'.format(result['market'])}: {'{:>11}'.format(str(result['profit']))} | {'{:>6}'.format(str(result['profit_percentage']))}%\n"

        result_str += f"{'-' * 31}\n"
        result_str += f"   total: {'{:>11}'.format(str(total_net))} | {'{:>6}'.format(str(total_percentage))}%\n"

        return result_str


    @staticmethod
    def overall_stats():
        if LongPosition.select().where(LongPosition.is_test == config.is_test).count() == 0:
            return {}

        lps = LongPosition.select(
                ((LongPosition.profit) / LongPosition.sell_quantity / LongPosition.purchase_price).alias('profit_percentage')
            ).where(
                LongPosition.profit >= Decimal('0.0'),
                LongPosition.is_test == config.is_test
            ).order_by(SQL('profit_percentage'))
        if len(lps) > 0:
            median_profit_percentage = Decimal(lps[round((len(lps) - 1)/2)].profit_percentage)
        else:
            median_profit_percentage = Decimal('0.0')

        lps = LongPosition.select(
                ((LongPosition.profit) / LongPosition.sell_quantity / LongPosition.purchase_price).alias('profit_percentage')
            ).where(
                LongPosition.profit < Decimal('0.0'),
                LongPosition.is_test == config.is_test
            ).order_by(SQL('profit_percentage'))
        if len(lps) > 0:
            median_loss_percentage = Decimal(lps[round((len(lps) - 1)/2)].profit_percentage)
        else:
            median_loss_percentage = Decimal('0.0')

        return {
            "profit": Decimal(LongPosition.select(fn.SUM(LongPosition.profit)
                ).where(LongPosition.is_test == config.is_test
                ).scalar()),
            "median_profit_percentage": median_profit_percentage,
            "median_loss_percentage": median_loss_percentage,
            "max_profit_percentage": Decimal(LongPosition.select(
                    fn.MAX(LongPosition.profit / LongPosition.sell_quantity / LongPosition.purchase_price)
                ).where(LongPosition.is_test == config.is_test
                ).scalar()),
            "min_profit_percentage": Decimal(LongPosition.select(
                    fn.MIN(LongPosition.profit / LongPosition.sell_quantity / LongPosition.purchase_price)
                ).where(LongPosition.is_test == config.is_test
                ).scalar()),
            "num_positions": LongPosition.select(fn.COUNT()
                ).where(LongPosition.is_test == config.is_test
                ).scalar(),
            "avg_order_size": Decimal(LongPosition.select(
                    fn.AVG(LongPosition.sell_quantity * LongPosition.purchase_price)
                ).where(LongPosition.is_test == config.is_test
                ).scalar()),
            "total_fees": Decimal(LongPosition.select(fn.SUM(LongPosition.fees)
                ).where(LongPosition.is_test == config.is_test
                ).scalar()),
        }


    @staticmethod
    def detailed_stats():
        result = ""

        # Report by day
        result += "Daily Results:\n"
        positions = LongPosition.select(
            ).where(LongPosition.is_test == config.is_test
            ).order_by(LongPosition.date_created)

        if not positions or len(positions) == 0:
            return "No trades"

        daily_profit = Decimal('0.0')
        daily_positions = 0
        daily_spent = Decimal('0.0')
        cur_date = datetime.datetime.fromtimestamp(positions[0].date_created).astimezone(pytz.timezone('UTC'))
        for i, position in enumerate(positions):
            pos_date = datetime.datetime.fromtimestamp(position.date_created).astimezone(pytz.timezone('UTC'))
            if (pos_date.year == cur_date.year and
                    pos_date.month == cur_date.month and
                    pos_date.day == cur_date.day):
                if position.profit:
                    daily_profit += position.profit
                    daily_spent += position.purchase_price * position.sell_quantity
                daily_positions += 1

            if (pos_date.year != cur_date.year or
                    pos_date.month != cur_date.month or
                    pos_date.day != cur_date.day or
                    i == len(positions) - 1):
                # Write out the results
                result += (f"{cur_date.date()}: " +
                           f"{Fore.GREEN if daily_profit >= Decimal('0.0') else Fore.RED}" +
                           f"{daily_profit:12.8f} BTC" +
                           f" | {daily_profit / daily_spent * Decimal('100.0'):6.2f}%" +
                           f"{Style.RESET_ALL}" +
                           f" | num_positions: {daily_positions:3}\n")

                # Update for the next loop, if there is one
                cur_date = pos_date
                if position.profit:
                    daily_profit = position.profit
                daily_positions = 1

        result += "\n"
        result += "Individual Crypto Performance\n"
        positions = LongPosition.select(LongPosition.market,
                                        fn.SUM(LongPosition.profit).alias('net_profit'),
                                        (fn.SUM(LongPosition.profit) / fn.SUM(LongPosition.purchase_price * LongPosition.sell_quantity)).alias('profit_percentage'),
                                        fn.COUNT().alias('num_positions')
                                    ).where(
                                        LongPosition.is_test == config.is_test,
                                        LongPosition.profit != None     # noqa: E711
                                    ).group_by(LongPosition.market
                                    ).order_by(SQL('net_profit').desc())

        for position in positions:
            # Write out the results
            result += (f"{Fore.GREEN if position.net_profit >= 0.0 else Fore.RED}" +
                       f"{position.market}: {position.net_profit:12.8f} BTC" +
                       f" | {position.profit_percentage * 100.0:6.2f}%" +
                       f"{Style.RESET_ALL}" +
                       f" | num_positions: {position.num_positions:3}\n")

        result += "\n"
        result += "Trade History\n"
        positions = LongPosition.select(
            ).where(LongPosition.is_test == config.is_test
            ).order_by(LongPosition.id)

        for position in positions:
            result += ( f"{datetime.datetime.fromtimestamp(position.date_created):%Y-%m-%d %H:%M}" +
                        f" | {Fore.GREEN if position.profit and position.profit >= 0.0 else Fore.RED}" +
                        f"{position.market[:-3]}{Style.RESET_ALL}" +
                        f" | bought {position.buy_quantity:6f} @ {position.purchase_price:.8f} BTC")
            if position.profit:
                result += ( f" | {datetime.datetime.fromtimestamp(position.date_closed):%Y-%m-%d %H:%M}" +
                            f" | {int(position.time_open / 60):4}" +
                            f" | sold @ {position.stop_loss_price:.8f} BTC" +
                            f" | {Fore.GREEN if position.profit >= 0.0 else Fore.RED}" +
                            f"{position.profit:11.8f} BTC" +
                            f" | {position.profit / (position.purchase_price * position.sell_quantity) * Decimal('100.0'):6.2f}%" +
                            f"{Style.RESET_ALL}")
            else:
                result += " | (position still open)"

            result += "\n"


        return result



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



if not Candle.table_exists():
    Candle.create_table(True)

if not Balance.table_exists():
    Balance.create_table(True)

if not ExchangeTokenReload.table_exists():
    ExchangeTokenReload.create_table(True)

if not LongPosition.table_exists():
    LongPosition.create_table(True)

if not MarketParams.table_exists():
    MarketParams.create_table(True)

