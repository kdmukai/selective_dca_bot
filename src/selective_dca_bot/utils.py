import numpy

from decimal import Decimal
from peewee import fn

from .models import LongPosition, Candle, AllTimeWatchlist
from .exchanges import EXCHANGE__BINANCE


def open_positions_report():
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

        (num_positions, quantity, spent, min, avg, max, min_sell_price) = LongPosition.select(
                fn.COUNT(LongPosition.id),
                fn.SUM(LongPosition.buy_quantity),
                fn.SUM(LongPosition.buy_quantity * LongPosition.purchase_price),
                fn.MIN(LongPosition.purchase_price),
                fn.AVG(LongPosition.purchase_price),
                fn.MAX(LongPosition.purchase_price),
                fn.MIN(LongPosition.sell_price)
            ).where(
                LongPosition.market == market,
                LongPosition.sell_timestamp.is_null(True)
            ).scalar(as_tuple=True)

        quantity = Decimal(quantity).quantize(Decimal('0.00000001'))
        spent = Decimal(spent)

        current_value = quantity * current_price

        profit = (current_value - spent).quantize(Decimal('0.00000001'))
        total_net += profit
        total_spent += spent
        current_profit_percentage = (current_value / spent * Decimal('100.0')).quantize(Decimal('0.01'))

        results.append({
            "market": market,
            "num_positions": num_positions,
            "min_position": min.quantize(Decimal('0.00000001')),
            "avg_position": avg.quantize(Decimal('0.00000001')),
            "max_position": max.quantize(Decimal('0.00000001')),
            "min_sell_price": min_sell_price.quantize(Decimal('0.00000001')),
            "min_profit_percentage": (min_sell_price / min * Decimal('100.00')).quantize(Decimal('0.01')),
            "profit": profit,
            "current_profit_percentage": current_profit_percentage,
            "quantity": quantity.normalize()
        })

    total_percentage = (total_net / total_spent * Decimal('100.0')).quantize(Decimal('0.01'))
    for result in sorted(results, key=lambda i: i['profit'], reverse=True):
        result_str += f"{'{:>8}'.format(result['market'])}: {result['min_position']:0.8f} | {result['min_sell_price']:0.8f} ({'{:>6}'.format(str(result['min_profit_percentage']))}%) | {'{:>2}'.format(str(result['num_positions']))} | {'{:>6}'.format(str(result['current_profit_percentage']))}%\n"

    result_str += f"{'-' * 53}\n"
    result_str += f"   total: {'{:>11}'.format(str(total_net))} | {'{:>6}'.format(str(total_percentage))}%\n"

    return result_str


def scalped_positions_report():
    markets = [lp.market for lp in LongPosition.select(
                    LongPosition.market
                ).where(
                    LongPosition.scalped_quantity.is_null(False)
                ).distinct()]

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

        (num_positions, spent, quantity_scalped) = LongPosition.select(
                fn.COUNT(LongPosition.id),
                fn.SUM(LongPosition.buy_quantity * LongPosition.purchase_price),
                fn.SUM(LongPosition.scalped_quantity)
            ).where(
                LongPosition.market == market,
                LongPosition.sell_timestamp.is_null(False)
            ).scalar(as_tuple=True)

        quantity = Decimal(quantity_scalped).quantize(Decimal('0.00000001'))
        spent = Decimal(spent).quantize(Decimal('0.00000001'))

        current_value = (quantity * current_price).quantize(Decimal('0.00000001'))

        total_net += current_value
        total_spent += spent

        results.append({
            "market": market,
            "num_positions": num_positions,
            "spent": spent,
            "current_value": current_value,
            "quantity": quantity.normalize()
        })

    total_net = total_net.quantize(Decimal('0.00000001'))
    total_spent = total_spent.quantize(Decimal('0.00000001'))
    for result in sorted(results, key=lambda i: i['current_value'], reverse=True):
        result_str += f"{'{:>8}'.format(result['market'])}: current_value {'{:>10}'.format(str(result['current_value']))} | {'{:>6f}'.format(result['quantity'])} | {result['num_positions']:3d}\n"

    result_str += f"{'-' * 49}\n"
    result_str += f"   total: {'{:>10}'.format(str(total_net))}\n"

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

