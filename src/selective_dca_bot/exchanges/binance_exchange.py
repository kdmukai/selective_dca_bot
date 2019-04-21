import binance
import decimal
import random
import time

from binance.client import Client
from decimal import Decimal
from termcolor import cprint

from .constants import EXCHANGE__BINANCE
from .abstract_exchange import AbstractExchange

from .. import config
from ..models import Candle, MarketParams



class BinanceExchange(AbstractExchange):
    _exchange_name = EXCHANGE__BINANCE
    _exchange_token = 'BNB'
    _intervals = {
        Candle.INTERVAL__1MINUTE: Client.KLINE_INTERVAL_1MINUTE,
        Candle.INTERVAL__5MINUTE: Client.KLINE_INTERVAL_5MINUTE,
        Candle.INTERVAL__15MINUTE: Client.KLINE_INTERVAL_15MINUTE,
        Candle.INTERVAL__1HOUR: Client.KLINE_INTERVAL_1HOUR
    }


    def __init__(self, api_key, api_secret, watchlist):
        super().__init__(api_key, api_secret, watchlist)
        self.client = Client(api_key, api_secret)


    @property
    def exchange_token(self):
        return self._exchange_token

    @property
    def exchange_name(self):
        return self._exchange_name


    def initialize_market(self, market):
        """
            Make sure we have MarketParams for the given market
        """
        params = MarketParams.get_market(market, exchange=MarketParams.EXCHANGE__BINANCE)
        if not params:
            # Have to query the API and populate
            """
                {
                    'symbol': 'ASTBTC',
                    'status': 'TRADING',
                    'baseAsset': 'AST',
                    'baseAssetPrecision': 8,
                    'quoteAsset': 'BTC',
                    'quotePrecision': 8,
                    'orderTypes': ['LIMIT', 'LIMIT_MAKER', 'MARKET', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT'],
                    'icebergAllowed': False,
                    'filters': [
                        {
                            'filterType': 'PRICE_FILTER',
                            'minPrice': '0.00000001',
                            'maxPrice': '100000.00000000',
                            'tickSize': '0.00000001'
                        },
                        {
                            'filterType': 'LOT_SIZE',
                            'minQty': '1.00000000',
                            'maxQty': '90000000.00000000',
                            'stepSize': '1.00000000'
                        },
                        {
                            'filterType': 'MIN_NOTIONAL',
                            'minNotional': '0.00100000'
                        }
                    ]
                }
            """
            response = self.client.get_symbol_info(symbol=market)
            tick_size = None
            step_size = None
            min_notional = None
            for filter in response["filters"]:
                if "tickSize" in filter:
                    tick_size = Decimal(filter["tickSize"])
                elif "stepSize" in filter:
                    step_size = Decimal(filter["stepSize"])
                elif "minNotional" in filter:
                    min_notional = Decimal(filter["minNotional"])

            MarketParams.create(
                exchange=MarketParams.EXCHANGE__BINANCE,
                market=market,
                price_tick_size=tick_size,
                lot_step_size=step_size,
                min_notional=min_notional
            )

            print(f"Loaded MarketParams for {market}")


    def ingest_latest_candles(self, market, interval, limit=5):
        """
            Get the most recent n (limit) candles.

              [
                1499040000000,      // Open time
                "0.01634790",       // Open
                "0.80000000",       // High
                "0.01575800",       // Low
                "0.01577100",       // Close
                "148976.11427815",  // Volume
                1499644799999,      // Close time
                "2434.19055334",    // Quote asset volume
                308,                // Number of trades
                "1756.87402397",    // Taker buy base asset volume
                "28.46694368",      // Taker buy quote asset volume
                "17928899.62484339" // Ignore
              ]
        """
        if limit == 1:
            # Never ingest the most recent (still-open) candle
            return

        print(f"num {market} candles: {limit}")

        # Give the exchange a breather so we don't get API limited
        if limit > 10:
            time.sleep(5)

        raw_data = self.client.get_klines(symbol=market, interval=self._intervals[interval], limit=limit)

        # Never ingest the most recent (still-open) candle (most recent is last)
        Candle.batch_create_candles(market, interval, self._format_candles(raw_data[:-1]))


    def load_historical_candles(self, market, interval, since):
        """
            This is a historical batch update of all candles from 'since' to now.

              [
                1499040000000,      // Open time
                "0.01634790",       // Open
                "0.80000000",       // High
                "0.01575800",       // Low
                "0.01577100",       // Close
                "148976.11427815",  // Volume
                1499644799999,      // Close time
                "2434.19055334",    // Quote asset volume
                308,                // Number of trades
                "1756.87402397",    // Taker buy base asset volume
                "28.46694368",      // Taker buy quote asset volume
                "17928899.62484339" // Ignore
              ]
        """
        candles = self.client.get_historical_klines(market, self._intervals[interval], since)
        return self._format_candles(candles)


    def _format_candles(self, candles):
        results = []
        for candle in candles:
            results.append({
                "timestamp": candle[0] / 1000.0,
                "open": Decimal(candle[1]),
                "high": Decimal(candle[2]),
                "low": Decimal(candle[3]),
                "close": Decimal(candle[4])
            })

        return results


    def get_current_balance(self, asset='BTC'):
        if config.is_test:
            raise Exception("Test mode shouldn't end up here")
        return Decimal(self.client.get_asset_balance(asset=asset)["free"])


    def get_current_balances(self):
        if config.is_test:
            pass

        else:
            """ {
                    'asset': 'BTC', 
                    'free': '0.00000000', 
                    'locked': '0.00000000'
                }
            """
            return {
                'BTC': self.get_current_balance(asset='BTC'),
                'BNB': self.get_current_balance(asset='BNB')
            }


    def buy(self, market, quantity):
        """
            Place a market buy order. As soon as it completes submit a stop-loss
            limit order.
        """
        # Adjust quantity as needed to conform to MarketParams; quantity can only
        #   be divided down to so many digits of precision, depending on the
        #   particular market.
        market_params = MarketParams.get_market(market)
        quantized_qty = quantity.quantize(market_params.lot_step_size)

        """ {
                'symbol': 'BNBBTC',
                'orderId': 58158667,
                'clientOrderId': 'jFTEtmTTUTqspMi6Oq08R9',
                'transactTime': 1529546953007,
                'price': '0.00000000',
                'origQty': '1.55000000',
                'executedQty': '1.55000000',
                'status': 'FILLED',
                'timeInForce': 'GTC',
                'type': 'MARKET',
                'side': 'BUY'
            }
        """
        try:
            buy_order_response = self.client.order_market_buy(
                symbol=market,
                quantity=quantized_qty,
                newOrderRespType=Client.ORDER_RESP_TYPE_FULL    # Need the full details to get 'commission' (aka fees).
            )
        except Exception as e:
            print(f"-------------- MARKET BUY EXCEPTION!! --------------" +
                  f" | {market}" +
                  f" | quantized_qty: {quantized_qty}"
                )

            # Throw it back up to bomb us out
            raise e

        if config.verbose:
            print(f"BUY ORDER: {buy_order_response}")

        order_id = buy_order_response["orderId"]
        timestamp = buy_order_response["transactTime"] / 1000

        if buy_order_response["status"] != 'FILLED':
            # TODO: handle unfilled market buys
            raise Exception(f"Buy order not FILLED (yet?)\n{buy_order_response}")

        elif buy_order_response["status"] == 'FILLED':
            # Calculate an aggregate purchase price
            total_spent = Decimal(0.0)
            total_qty = Decimal(0.0)
            total_commission = Decimal(0.0)
            for fill in buy_order_response["fills"]:
                """ {
                        "price": "4000.00000000",
                        "qty": "1.00000000",
                        "commission": "4.00000000",
                        "commissionAsset": "USDT"
                    }
                """
                total_spent += Decimal(fill["price"]) * Decimal(fill["qty"])
                total_qty += Decimal(fill["qty"])
                total_commission += Decimal(fill["commission"])

            purchase_price = total_spent / total_qty

            return {
                "order_id": order_id,
                "price": purchase_price,
                "quantity": total_qty,
                "fees": total_commission,
                "timestamp": timestamp
            }


    def reload_exchange_token(self, quantity):
        print(f"Reloading {quantity:.4f} {self.exchange_token} exchange tokens")
        market = f'{self.exchange_token}BTC'
        return self.buy(market, quantity)


    def market_sell(self, market, quantity):
        # Round prices to conform to price_tick_size for this market
        market_params = MarketParams.get_market(market)

        # Round the quantity to one less decimal place than specified
        #   e.g. lot_step_size = '0.001' but round 0.123 to 0.12
        #   see: https://redd.it/7ej5cn
        exp = market_params.lot_step_size
        if market_params.lot_step_size < Decimal('1.0'):
            exp = Decimal(10.0) ** Decimal(market_params.lot_step_size.as_tuple().exponent + 1)
        quantized_qty = quantity.quantize(exp, rounding=decimal.ROUND_DOWN)

        if config.is_test:
            sell_price = self.get_current_price(market=market)

            # Add a discount factor to mimic ask-buy spread
            sell_price += sell_price * Decimal(random.uniform(-0.002, 0.001))

            # Calculate the fees
            exchange_token_price = self.get_current_price(market=f"{self.exchange_token}BTC")
            total_commission = sell_price * quantized_qty * Decimal('0.0005') / exchange_token_price
            total_commission = total_commission.quantize(Decimal('0.00000001'), rounding=decimal.ROUND_DOWN)

            return {
                "order_id": 1,
                "price": sell_price,
                "quantity": quantized_qty,
                "fees": total_commission,
                "timestamp": config.historical_timestamp
            }

        else:
            try:
                response = self.client.order_market_sell(
                    symbol=market,
                    quantity=quantized_qty,
                    newOrderRespType=Client.ORDER_RESP_TYPE_FULL    # Need the full details to get 'commission' (aka fees).
                )
            except Exception as e:
                error_msg = (f"MARKET SELL ORDER: {market}" +
                             f" | quantity: {quantity}" +
                             f" | quantized_qty: {quantized_qty}\n" +
                             f"{e}")
                cprint(error_msg, "red")

                # TODO: Email error notifications?
                raise e


            if config.verbose:
                print(f"MARKET SELL ORDER: {response}")

            order_id = response["orderId"]
            timestamp = response["transactTime"] / 1000

            if response["status"] != 'FILLED':
                # TODO: handle unfilled market sells
                raise Exception(f"Market sell order not FILLED (yet?)\n{response}")

            elif response["status"] == 'FILLED':
                # Calculate an aggregate sale price
                total_made = Decimal(0.0)
                total_qty = Decimal(response["executedQty"])
                total_commission = Decimal(0.0)
                for fill in response["fills"]:
                    """ {
                            "price": "4000.00000000",
                            "qty": "1.00000000",
                            "commission": "4.00000000",
                            "commissionAsset": "BNB"
                        }
                    """
                    total_made += Decimal(fill["price"]) * Decimal(fill["qty"])
                    total_commission += Decimal(fill["commission"])

                sell_price = total_made / total_qty

                return {
                    "order_id": order_id,
                    "price": sell_price,
                    "quantity": total_qty,
                    "fees": total_commission,
                    "timestamp": timestamp
                }

            else:
                raise Exception("Unhandled case!")


    def set_stop_loss(self, market, quantity, stop_loss_price):
        limit_price = stop_loss_price * config.params["stop_loss_limit_percentage"]

        # Round prices to conform to price_tick_size for this market
        market_params = MarketParams.get_market(market)

        # Round the quantity to one less decimal place than specified
        #   e.g. lot_step_size = '0.001' but round 0.123 to 0.12
        #   see: https://redd.it/7ej5cn
        exp = market_params.lot_step_size
        if market_params.lot_step_size < Decimal('1.0'):
            exp = Decimal(10.0) ** Decimal(market_params.lot_step_size.as_tuple().exponent + 1)
        quantized_qty = quantity.quantize(exp, rounding=decimal.ROUND_DOWN)

        # Same for the price
        exp = Decimal(10.0) ** Decimal(market_params.price_tick_size.as_tuple().exponent + 1)
        stop_loss_price = stop_loss_price.quantize(exp)
        limit_price = limit_price.quantize(exp)

        if config.is_test:
            order_id = 1
            timestamp = config.historical_timestamp

        else:
            try:
                response = self.client.create_order(
                    symbol=market,
                    quantity=quantized_qty,
                    price=limit_price,
                    stopPrice=stop_loss_price,
                    type=Client.ORDER_TYPE_STOP_LOSS_LIMIT,
                    side=Client.SIDE_SELL,
                    timeInForce=Client.TIME_IN_FORCE_GTC,
                    newOrderRespType=Client.ORDER_RESP_TYPE_FULL
                )
            except binance.exceptions.BinanceAPIException as e:
                error_msg = (f"STOP LOSS LIMIT ORDER: {market}" +
                             f" | quantity: {quantity}" +
                             f" | quantized_qty: {quantized_qty}" +
                             f" | price: {limit_price}" +
                             f" | stopPrice: {stop_loss_price}\n" +
                             f"{e}")
                cprint(error_msg, "red")
                return {"error_code": e.code}

            except Exception as e:
                error_msg = (f"STOP LOSS LIMIT ORDER: {market}" +
                             f" | quantity: {quantity}" +
                             f" | quantized_qty: {quantized_qty}" +
                             f" | price: {limit_price}" +
                             f" | stopPrice: {stop_loss_price}\n" +
                             f"{e}")
                cprint(error_msg, "red")

                # TODO: Handle binance.exceptions.BinanceAPIException: APIError(code=-2010): Order would trigger immediately.
                #   Immediately submit it as a market sell order instead?

                # TODO: Email error notifications?
                raise e

            order_id = response["orderId"]
            timestamp = response["transactTime"] / 1000


        return {
            "order_id": order_id,
            "quantity": quantized_qty,
            "stop_loss_price": stop_loss_price,
            "limit_price": limit_price,
            "timestamp": timestamp
        }


    def cancel_order(self, market, order_id):
        if config.is_test:
            return

        return self.client.cancel_order(symbol=market, orderId=order_id)


    def update_stop_loss(self, position, stop_loss_price):
        if config.is_test:
            return {
                "success": True,
                "timestamp": config.historical_timestamp,
                "order_id": 1
            }

        else:
            self.cancel_order(
                market=position.market,
                order_id=position.sell_order_id
            )
            return self.set_stop_loss(
                market=position.market,
                quantity=position.sell_quantity,
                stop_loss_price=stop_loss_price
            )


    def get_stop_loss_order_status(self, position):
        if config.is_test:
            # Have to simulate if a stop-loss was triggered at the current historical_timestamp
            candle = Candle.get_historical_candle(position.market, config.interval, config.historical_timestamp)

            if candle and position.stop_loss_price >= candle.low:
                return {
                    "status": "FILLED",
                    "sell_price": position.stop_loss_price,
                    "quantity": position.sell_quantity,
                    "fees": (position.sell_quantity * position.stop_loss_price * Decimal('0.0005')).quantize(Decimal('0.00000001'), rounding=decimal.ROUND_DOWN),
                    "timestamp": candle.timestamp
                }
            else:
                return {
                    "status": "OPEN",
                    "timestamp": candle.timestamp
                }

        else:
            """
                {
                    'symbol': 'BNBBTC',
                    'orderId': 58158667,
                    'clientOrderId': 'jFTEtmTTUTqspMi6Oq08R9',
                    'price': '0.00000000',
                    'origQty': '1.55000000',
                    'executedQty': '1.55000000',
                    'status': 'FILLED',
                    'timeInForce': 'GTC',
                    'type': 'MARKET',
                    'side': 'BUY',
                    'stopPrice': '0.00000000',
                    'icebergQty': '0.00000000',
                    'time': 1529546953007,
                    'isWorking': True
                }
            """
            try:
                if not position.sell_order_id:
                    # Can't look for nothing
                    raise Exception(f"Position {position} has no sell_order_id")

                response = self.client.get_order(symbol=position.market, orderId=position.sell_order_id)
            except Exception as e:
                print(f"GET STOP-LOSS ORDER STATUS:" +
                      f" | symbol: {position.market}" +
                      f" | orderId: {position.sell_order_id}" +
                      f"\n{e}")
                raise e

            if response["status"] == 'FILLED':
                print(f"ORDER STATUS: FILLED: {response}")

                price = Decimal(response["stopPrice"]) if "stopPrice" in response else Decimal(response["price"])
                quantity = Decimal(response["executedQty"])

                # TODO: How to get the 'commission' fees?

                # Calculating unofficial fees for now
                fees = self._calculate_fees(price, quantity)

                # Sell order is done!
                return {
                    "status": response["status"],
                    "sell_price": price,
                    "quantity": quantity,
                    "fees": fees,
                    "timestamp": response["time"] / 1000,
                }
            else:
                return {
                    "status": response["status"]
                }


    def get_buy_order_status(self, position):
        if config.is_test:
            # Have to simulate if the buy order would have filled at the current historical_timestamp
            candle = Candle.get_historical_candle(position.market, config.interval, config.historical_timestamp)

            if candle and position.purchase_price >= candle.low:
                return {
                    "status": "FILLED",
                    "fees": (position.buy_quantity * position.purchase_price * Decimal('0.0005')).quantize(Decimal('0.00000001'), rounding=decimal.ROUND_DOWN),
                    "timestamp": candle.timestamp
                }
            else:
                return {
                    "status": "OPEN",
                    "timestamp": candle.timestamp
                }

        else:
            """
                {
                    'symbol': 'BNBBTC',
                    'orderId': 58158667,
                    'clientOrderId': 'jFTEtmTTUTqspMi6Oq08R9',
                    'price': '0.00000000',
                    'origQty': '1.55000000',
                    'executedQty': '1.55000000',
                    'status': 'FILLED',
                    'timeInForce': 'GTC',
                    'type': 'MARKET',
                    'side': 'BUY',
                    'stopPrice': '0.00000000',
                    'icebergQty': '0.00000000',
                    'time': 1529546953007,
                    'isWorking': True
                }
            """
            try:
                if not position.buy_order_id:
                    # Can't look for nothing
                    raise Exception(f"Position {position} has no buy_order_id")

                response = self.client.get_order(symbol=position.market, orderId=position.buy_order_id)

            except Exception as e:
                print(f"GET BUY ORDER STATUS:" +
                      f" | symbol: {position.market}" +
                      f" | orderId: {position.buy_order_id}" +
                      f"\n{e}")
                raise e

            if response["status"] == 'FILLED':
                print(f"ORDER STATUS: FILLED: {response}")

                # TODO: How to get the 'commission' fees?

                # Calculate unofficial fees for now
                fees = self._calculate_fees(position.purchase_price, position.buy_quantity)

                return {
                    "status": response["status"],
                    "fees": fees,
                    "timestamp": response["time"] / 1000,
                }
            else:
                return {
                    "status": response["status"]
                }


    def _calculate_fees(self, price, quantity):
        fees = price * quantity / self.get_current_price(f"{self.exchange_token}BTC") * Decimal('0.0005')
        return fees.quantize(Decimal('0.00000001'), rounding=decimal.ROUND_DOWN)


    def get_current_price(self, market):
        return Decimal(self.client.get_ticker(symbol=market)["lastPrice"])


    def get_current_ask(self, market):
        return Decimal(self.client.get_order_book(symbol=market).get('asks')[0][0])


    def get_market_depth(self, market):
        return self.client.get_order_book(symbol=market)


    def get_moving_average(self, market, interval, since):
        """
              [
                1499040000000,      // Open time
                "0.01634790",       // Open
                "0.80000000",       // High
                "0.01575800",       // Low
                "0.01577100",       // Close
                "148976.11427815",  // Volume
                1499644799999,      // Close time
                "2434.19055334",    // Quote asset volume
                308,                // Number of trades
                "1756.87402397",    // Taker buy base asset volume
                "28.46694368",      // Taker buy quote asset volume
                "17928899.62484339" // Ignore
              ]
        """
        self.candles = self.client.get_historical_klines(market, self.intervals[interval], since)
        ma = Decimal('0.0')
        for candle in self.candles:
            ma += (Decimal(candle[4]) + Decimal(candle[1])) / Decimal('2.0')

        return ma / Decimal(len(self.candles))



