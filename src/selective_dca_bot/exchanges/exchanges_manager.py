from . import BinanceExchange
from .constants import EXCHANGE__BINANCE


class ExchangesManager():

    @staticmethod
    def get_exchanges(exchanges):
        from ..models import AllTimeWatchlist
        ex = {}
        for exchange in exchanges:
            if exchange['name'] == EXCHANGE__BINANCE:
                ex[EXCHANGE__BINANCE] = BinanceExchange(exchange['key'], exchange['secret'], exchange['watchlist'])

            # Also update the exchange's all-time watchlist
            if not AllTimeWatchlist.get_watchlist(exchange=EXCHANGE__BINANCE):
                AllTimeWatchlist.create(
                    exchange=EXCHANGE__BINANCE,
                    watchlist=','.join(exchange['watchlist'])
                )
            AllTimeWatchlist.update_watchlist(watchlist=exchange['watchlist'], exchange=EXCHANGE__BINANCE)

        return ex
