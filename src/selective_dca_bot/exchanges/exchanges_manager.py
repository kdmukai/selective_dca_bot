from . import BinanceExchange


class ExchangesManager():
    
    @staticmethod
    def get_exchanges(exchanges):
        ex = {}
        for exchange in exchanges:
            if exchange['name'] == 'binance':
                ex['binance'] = BinanceExchange(exchange['key'], exchange['secret'], exchange['watchlist'])

        return ex
