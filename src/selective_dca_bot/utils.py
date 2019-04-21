import numpy

from decimal import Decimal
from peewee import fn

from .models import LongPosition, Candle, AllTimeWatchlist
from .exchanges import EXCHANGE__BINANCE


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



def generate_performance_report(base_pair='BTC',
                                interval=Candle.INTERVAL__1HOUR,
                                test_iterations=100000,
                                exchanges=[EXCHANGE__BINANCE]):
    positions = LongPosition.select()

    # Prep back-testing data for every buy
    for position in positions:
        watchlist = position.watchlist.split(',')

        position.possible_buys = []
        for crypto in watchlist:
            market = f"{crypto}{base_pair}"
            price = Candle.get_historical_candles(market, interval, position.timestamp, 1)[0].close
            quantity = (position.spent / price).quantize(Decimal('0.00000001'))
            position.possible_buys.append({
                "market": market,
                "price": price,
                "quantity": quantity
            })

    # Grab latest price for all cryptos ever watched
    current_prices = {}
    for exchange in exchanges:
        for crypto in AllTimeWatchlist.get_watchlist(exchange=exchange):
            market = f"{crypto}{base_pair}"
            candle = Candle.get_last_candle(market, interval=interval)
            current_prices[market] = candle.close

    test_runs = []
    for i in range(0, test_iterations):
        # For each historical LongPosition, randomly select a possible buy and calculate net profitability
        net_profit = Decimal('0.0')
        for position in positions:
            rand_buy_index = numpy.random.randint(low=0, high=len(position.possible_buys))
            buy = position.possible_buys[rand_buy_index]
            net_profit += buy['quantity'] * current_prices[buy['market']] - position.spent

        test_runs.append(net_profit)
        # print(f"{str(i):5s} net profit: {net_profit:0.08f} {base_pair}")

    test_runs = sorted(test_runs)
    median_profit = test_runs[int(test_iterations/2)]
    print(f"min | median | max: {test_runs[0]:0.08f} | {median_profit:0.08f} | {test_runs[test_iterations - 1]:0.08f}")

    print(current_profit())



