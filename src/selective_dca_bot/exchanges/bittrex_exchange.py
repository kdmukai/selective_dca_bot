import decimal
import json
import random
import time

from bittrex.bittrex import Bittrex
from decimal import Decimal
from termcolor import cprint

from .constants import EXCHANGE__BITTREX
from .abstract_exchange import AbstractExchange

from .. import config
from ..models import Candle, MarketParams, ONE_SATOSHI



class BittrexExchange(AbstractExchange):
    _exchange_name = EXCHANGE__BITTREX
    _exchange_token = None
    # _intervals = {
    #     Candle.INTERVAL__1MINUTE: Client.KLINE_INTERVAL_1MINUTE,
    #     Candle.INTERVAL__5MINUTE: Client.KLINE_INTERVAL_5MINUTE,
    #     Candle.INTERVAL__15MINUTE: Client.KLINE_INTERVAL_15MINUTE,
    #     Candle.INTERVAL__1HOUR: Client.KLINE_INTERVAL_1HOUR
    # }


    def __init__(self, api_key, api_secret, watchlist):
        super().__init__(api_key, api_secret, watchlist)
        self.client = Bittrex(api_key, api_secret)


    def build_market_name(self, crypto, base_currency):
        # Bittrex uses BTC-HYDRO format
        return f"{base_currency}-{crypto}"


    def initialize_market(self, crypto, base_currency, recheck=False):
        """
            Make sure we have MarketParams for the given market
        """
        market = self.build_market_name(crypto, base_currency)
        params = MarketParams.get_market(market, exchange=MarketParams.EXCHANGE__BITTREX)
        if not params or recheck:
            # Have to query the API and get all markets...
            """
                 {
                    "success": true,
                    "message": "",
                    "result": [
                        {
                            "MarketCurrency": "LTC",
                            "BaseCurrency": "BTC",
                            "MarketCurrencyLong": "Litecoin",
                            "BaseCurrencyLong": "Bitcoin",
                            "MinTradeSize": 0.01686767,
                            "MarketName": "BTC-LTC",
                            "IsActive": true,
                            "IsRestricted": false,
                            "Created": "2014-02-13T00:00:00",
                            "Notice": null,
                            "IsSponsored": null,
                            "LogoUrl": "https://bittrexblobstorage.blob.core.windows.net/public/6defbc41-582d-47a6-bb2e-d0fa88663524.png"
                        },
                        ...
                    ]
                }

            """
            result = self.client.get_markets()
            if not "success" in result:
                raise Exception("Couldn't retrieve markets from Bittrex")

            market_details = next(x for x in result["result"] if x["MarketCurrency"] == crypto and x["BaseCurrency"] == base_currency)
            min_trade_size = Decimal(market_details["MinTradeSize"]).quantize(ONE_SATOSHI)

            # Also have to query current market price of the target market
            """
                {
                    "success": true,
                    "message": "",
                    "result": {
                        "Bid": 0.01259751,
                        "Ask": 0.012607,
                        "Last": 0.01260665
                    }
                }
            """
            ticker = self.client.get_ticker(self.build_market_name(crypto, base_currency))
            if not "success" in result:
                raise Exception(f"Couldn't retrieve current ticker for {self.build_market_name(crypto, base_currency)} Bittrex")

            price = Decimal(ticker["result"]["Last"]).quantize(ONE_SATOSHI)

            # Note: The minimum BTC trade value for orders is 50,000 Satoshis (0.0005)
            tick_size = ONE_SATOSHI
            step_size = ONE_SATOSHI
            min_notional = (min_trade_size * price).quantize(ONE_SATOSHI)   # Varies from about 0.0001 - 0.0002 BTC
            multiplier_up = None
            avg_price_minutes = None

            if params:
                params.tick_size = tick_size
                params.step_size = step_size
                params.min_notional = min_notional
                params.multiplier_up = multiplier_up
                params.avg_price_minutes = avg_price_minutes
                params.save()

                print(f"Re-loaded MarketParams for {market}")
            else:
                MarketParams.create(
                    exchange=MarketParams.EXCHANGE__BITTREX,
                    market=market,
                    price_tick_size=tick_size,
                    lot_step_size=step_size,
                    min_notional=min_notional,
                    multiplier_up=multiplier_up,
                    avg_price_minutes=avg_price_minutes
                )

                print(f"Loaded MarketParams for {market}")


    def ingest_latest_candles(self, market, interval, since=None, limit=5):
        # Dead-end here until python library is updated to support Bittrex's v3 API
        raise Exception("Bittrex v3 API not yet supported")



    def get_current_ask(self, market):
        pass


    def buy(self, market, quantity):
        pass


    def market_sell(self, market, quantity):
        pass


    def limit_sell(self, market, quantity, bid_price):
        pass


    def get_current_balance(self, asset):
        pass


    def get_sell_order_status(self, position):
        pass


    def update_order_statuses(self, market, positions):
        pass


    def cancel_order(self, market, order_id):
        pass

