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
            AllTimeWatchlist.update_watchlist(watchlist=exchange['watchlist'], exchange=EXCHANGE__BINANCE)

        return ex
