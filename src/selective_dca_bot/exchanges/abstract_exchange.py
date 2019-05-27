from abc import ABC, abstractmethod     # ABC = Abstract Base Class
from decimal import Decimal



class AbstractExchange(ABC):
    _exchange_name = None


    def __init__(self, api_key, api_secret, watchlist):
        super().__init__()
        self.watchlist = watchlist

    @property
    def exchange_name(self):
        return self._exchange_name

    @abstractmethod
    def build_market_name(self, crypto, base_currency):
        pass

    @abstractmethod
    def initialize_market(self, crypto, base_currency):
        pass


    @abstractmethod
    def get_current_ask(self, market):
        pass


    @abstractmethod
    def buy(self, market, quantity):
        pass


    @abstractmethod
    def market_sell(self, market, quantity):
        pass


    @abstractmethod
    def limit_sell(self, market, quantity, bid_price):
        pass


    @abstractmethod
    def get_current_balance(self, asset):
        pass


    @abstractmethod
    def get_sell_order_status(self, position):
        pass

    @abstractmethod
    def update_order_statuses(self, market, positions):
        pass

    @abstractmethod
    def cancel_order(self, market, order_id):
        pass


    @abstractmethod
    def ingest_latest_candles(self, market, interval, since=None, limit=5):
        pass


    def calculate_latest_metrics(self, base_currency, interval, ma_periods):
        from ..models import Candle, AllTimeWatchlist

        metrics = []

        # update ALL cryptos ever watched for this exchange (to support historical back testing)
        for crypto in AllTimeWatchlist.get_watchlist(exchange=self.exchange_name):
            if not crypto:
                continue
                
            market = f"{crypto}{base_currency}"
            self.initialize_market(crypto, base_currency)

            # How many candles do we need to catch up on?
            last_candle = Candle.get_last_candle(market, interval)
            timestamp = None
            if last_candle:
                num_candles = last_candle.num_periods_from_now()
                if num_candles > max(ma_periods):
                    num_candles = max(ma_periods)
                timestamp = last_candle.timestamp
            else:
                num_candles = max(ma_periods) + 1

            self.ingest_latest_candles(market, interval, since=timestamp, limit=num_candles)

            # Calculate the metrics for the current candle
            last_candle = Candle.get_last_candle(market, interval)

            min_ma_period = None
            min_ma = Decimal('99999999.0')
            min_price_to_ma = None
            for ma_period in ma_periods:
                ma = last_candle.calculate_moving_average(ma_period)
                price_to_ma = last_candle.close / ma

                # use the lowest MA across all supplied ma_periods
                if ma < min_ma:
                    min_price_to_ma = price_to_ma
                    min_ma_period = ma_period
                    min_ma = ma

            metrics.append({
                'exchange': self.exchange_name,
                'market': market,
                'close': last_candle.close,
                'ma_period': min_ma_period,
                'ma': min_ma,
                'price_to_ma': min_price_to_ma
            })

            # print(f"{last_candle.market}: close: {last_candle.close:0.8f} | 200H_MA: {ma:0.8f} | price-to-MA: {price_to_ma:0.4f}")

        return metrics



