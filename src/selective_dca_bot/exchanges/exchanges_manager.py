from . import BinanceExchange, BittrexExchange
from .constants import EXCHANGE__BINANCE, EXCHANGE__BITTREX


class ExchangesManager():

    @staticmethod
    def get_exchanges(exchanges):
        from ..models import AllTimeWatchlist
        ex = {}
        for exchange in exchanges:
            if exchange['name'] == EXCHANGE__BINANCE:
                ex[EXCHANGE__BINANCE] = BinanceExchange(exchange['key'], exchange['secret'], exchange['watchlist'])

            elif exchange['name'] == EXCHANGE__BITTREX:
                ex[EXCHANGE__BITTREX] = BittrexExchange(exchange['key'], exchange['secret'], exchange['watchlist'])

            else:
                raise Exception("Exchange not implemented")


            # Also update the exchange's all-time watchlist
            if not AllTimeWatchlist.get_watchlist(exchange=exchange['name']):
                AllTimeWatchlist.create(
                    exchange=exchange['name'],
                    watchlist=','.join(exchange['watchlist'])
                )
            AllTimeWatchlist.update_watchlist(watchlist=exchange['watchlist'], exchange=exchange['name'])

        return ex

