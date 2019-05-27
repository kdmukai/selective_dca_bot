import argparse
import boto3
import configparser
import datetime
import random
import time

from decimal import Decimal, ROUND_UP
from datetime import timedelta

from selective_dca_bot import config, utils
from selective_dca_bot.exchanges import (
    BinanceExchange, ExchangesManager, EXCHANGE__BINANCE, EXCHANGE__BITTREX)
from selective_dca_bot.models import Candle, LongPosition, MarketParams, AllTimeWatchlist


parser = argparse.ArgumentParser(description='Selective DCA (Dollar Cost Averaging) Bot')


# Required positional arguments
parser.add_argument('buy_amount', type=Decimal,
                    help="The quantity of the crypto to spend (e.g. 0.05)")

parser.add_argument('base_currency',
                    help="""The ticker of the currency to spend (e.g. 'BTC',
                        'ETH', 'USD', etc)""")


# Optional switches
parser.add_argument('-e', '--exchanges',
                    default=f"{EXCHANGE__BINANCE},{EXCHANGE__BITTREX}",
                    dest="exchanges",
                    help="Comma-separated list of exchanges to include in this run")

parser.add_argument('-c', '--settings',
                    default="settings.conf",
                    dest="settings_config",
                    help="Override default settings config file location")

parser.add_argument('-p', '--portfolio',
                    default="portfolio.conf",
                    dest="portfolio_config",
                    help="Override default portfolio config file location")

parser.add_argument('-l', '--live',
                    action='store_true',
                    default=False,
                    dest="live_mode",
                    help="""Submit live orders. When omitted runs in simulation mode""")

parser.add_argument('-u', '--update_order_status',
                    action='store_true',
                    default=False,
                    dest="update_order_status",
                    help="""Checks limit sell orders' statuses""")

parser.add_argument('-r', '--performance_report',
                    action='store_true',
                    default=False,
                    dest="performance_report",
                    help="""Compare purchase decisions against random portfolio selections""")


def get_timestamp():
    ts = time.time()
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


if __name__ == '__main__':
    print(f"{'*' * 90}")
    print(f"* {get_timestamp()}")
    args = parser.parse_args()
    buy_amount = args.buy_amount
    base_currency = args.base_currency
    live_mode = args.live_mode
    update_order_status = args.update_order_status
    config.is_test = not live_mode
    performance_report = args.performance_report
    exchange_list = args.exchanges.split(',')

    # Read settings
    arg_config = configparser.ConfigParser()
    arg_config.read(args.settings_config)

    binance_key = arg_config.get('API', 'BINANCE_KEY')
    binance_secret = arg_config.get('API', 'BINANCE_SECRET')

    try:
        bittrex_key = arg_config.get('API', 'BITTREX_KEY')
        bittrex_secret = arg_config.get('API', 'BITTREX_SECRET')
    except configparser.NoOptionError:
        bittrex_key = None
        bittrex_secret = None



    max_crypto_holdings_percentage = Decimal(arg_config.get('CONFIG', 'MAX_CRYPTO_HOLDINGS_PERCENTAGE'))
    max_consecutive_buys = Decimal(arg_config.get('CONFIG', 'MAX_CONSECUTIVE_BUYS'))
    profit_threshold = Decimal(arg_config.get('CONFIG', 'PROFIT_THRESHOLD'))

    try:
        sns_topic = arg_config.get('AWS', 'SNS_TOPIC')
        aws_access_key_id = arg_config.get('AWS', 'AWS_ACCESS_KEY_ID')
        aws_secret_access_key = arg_config.get('AWS', 'AWS_SECRET_ACCESS_KEY')

        # Prep boto SNS client for email notifications
        sns = boto3.client(
            "sns",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name="us-east-1"     # N. Virginia
        )
    except configparser.NoSectionError:
        sns_topic = None

    if performance_report:
        from selective_dca_bot.models import LongPosition, Candle
        results = LongPosition.get_performance_report()
        exit()

    # Read crypto watchlist
    arg_config = configparser.ConfigParser()
    arg_config.read(args.portfolio_config)

    watchlist = []
    binance_watchlist = [x.strip() for x in arg_config.get('WATCHLIST', 'BINANCE').split(',') if x != '']
    bittrex_watchlist = [x.strip() for x in arg_config.get('WATCHLIST', 'BITTREX').split(',') if x != '']

    watchlist.extend(binance_watchlist)
    watchlist.extend(bittrex_watchlist)


    params = {
        # "num_buys": num_buys,
    }

    # Setup package-wide settings
    config.params = params
    config.interval = Candle.INTERVAL__1HOUR

    # If multiple MA periods are passed, will calculate the price-to-MA with the lowest MA
    ma_periods = [200]


    #------------------------------------------------------------------------------------
    # UPDATE latest candles
    exchanges_data = []
    if EXCHANGE__BINANCE in exchange_list and binance_watchlist:
        exchanges_data.append(
            {
                'name': EXCHANGE__BINANCE,
                'key': binance_key,
                'secret': binance_secret,
                'watchlist': binance_watchlist,
            }
        )

    if EXCHANGE__BITTREX in exchange_list and bittrex_watchlist:
        exchanges_data.append(
            {
                'name': EXCHANGE__BITTREX,
                'key': bittrex_key,
                'secret': bittrex_secret,
                'watchlist': bittrex_watchlist,
            }
        )

    exchanges = ExchangesManager.get_exchanges(exchanges_data)
    metrics = []
    for name, exchange in exchanges.items():
        metrics.extend(exchange.calculate_latest_metrics(base_currency=base_currency, interval=config.interval, ma_periods=ma_periods))
        """
            metrics = [{
                    'exchange': self.exchange_name,
                    'market': market,
                    'close': last_candle.close,
                    'ma_period': min_ma_period,
                    'ma': min_ma,
                    'price_to_ma': min_price_to_ma
                }, {...}, {...}]
        """


    #------------------------------------------------------------------------------------
    #  Check the status of open LongPositions
    if update_order_status:
        recently_sold = ""
        num_positions_sold = 0
        for exchange_name, exchange in exchanges.items():
            markets = [lp.market for lp in LongPosition.select(
                    LongPosition.market
                ).where(
                    LongPosition.exchange == exchange_name,
                    LongPosition.sell_timestamp.is_null(True)
                ).distinct()]

            for market in markets:
                positions = LongPosition.select(
                        ).where(
                            LongPosition.exchange == exchange_name,
                            LongPosition.market == market,
                            LongPosition.sell_order_id.is_null(False),
                            LongPosition.sell_timestamp.is_null(True)
                        ).order_by(
                            LongPosition.sell_order_id
                        )

                positions_sold = exchange.update_order_statuses(market, positions)

                for position in positions_sold:
                    num_positions_sold += 1
                    recently_sold += f"{position.market}: sold {'{:f}'.format(position.sell_quantity.normalize())} | recouped {'{:f}'.format((position.sell_quantity * position.sell_price).quantize(Decimal('0.00000001')))} {base_currency} | scalped {'{:f}'.format(position.scalped_quantity.normalize())}\n"

        if live_mode and num_positions_sold > 0:
            subject = f"SOLD {num_positions_sold} positions"
            print(recently_sold)
            message = recently_sold
            sns.publish(
                TopicArn=sns_topic,
                Subject=subject,
                Message=message
            )


    #------------------------------------------------------------------------------------
    #  Update the LIMIT SELL targets of open LongPositions
    if update_order_status:
        for exchange_name, exchange in exchanges.items():
            markets = [lp.market for lp in LongPosition.select(
                    LongPosition.market
                ).where(
                    LongPosition.exchange == exchange_name,
                    LongPosition.scalped_quantity.is_null(True)
                ).distinct()]

            for market in markets:
                market_params = MarketParams.get_market(market)
                metric = next(m for m in metrics if m['exchange'] == exchange_name and m['market'] == market)
                current_price = metric['close'].quantize(market_params.price_tick_size)
                current_ma = metric['ma'].quantize(market_params.price_tick_size)

                # Get this market's open positions
                positions = LongPosition.select(
                        ).where(
                            LongPosition.exchange == exchange_name,
                            LongPosition.market == market,
                            LongPosition.sell_timestamp.is_null(True),
                        ).order_by(
                            LongPosition.purchase_price.desc(),
                            LongPosition.id
                        )

                if positions.count() == 0:
                    continue

                last_target_price = None
                for index, position in enumerate(positions):
                    if index >= int(len(positions) * 0.75) and last_target_price:
                        # Hold the last 1/4 of the stash at the 75th percentile's target price
                        target_price = last_target_price

                        if position.sell_order_id and position.sell_price and target_price == position.sell_price.quantize(market_params.price_tick_size):
                            # This position is already at its min profit. Just have to keep holding
                            # print(f"Keeping {market} {position.id:3d} {position.purchase_price:0.8f} at {target_price:0.8f}")
                            continue

                    else:
                        min_sell_price = (position.purchase_price * profit_threshold).quantize(market_params.price_tick_size)

                        # Account for cryptos like LTC with high-value price_tick_sizes
                        (sell_quantity, target_price) = position.calculate_scalp_sell_price(market_params, min_sell_price)
                        last_target_price = target_price
                        if target_price > current_ma:
                            # position.sell_price could be None if it was a partially-canceled error position
                            if position.sell_order_id and position.sell_price and target_price == position.sell_price.quantize(market_params.price_tick_size):
                                # This position is already at its min profit. Just have to keep holding
                                # print(f"Keeping {market} {position.id:3d} {position.purchase_price.quantize(market_params.price_tick_size):0.8f} at {target_price:0.8f}")
                                continue
                            else:
                                # Update to the target_price we just calculated.
                                pass

                        else:
                            (sell_quantity, target_price) = position.calculate_scalp_sell_price(market_params, (min_sell_price + current_ma)/Decimal('2.0'))
                            last_target_price = target_price

                            # If the MA has just barely changed, don't bother chasing the tiny difference
                            diff = (max([position.sell_price, target_price]) - min([position.sell_price, target_price])) / min([position.sell_price, target_price])
                            if diff < Decimal('0.0025'):
                                # Current sell_price is close enough
                                print(f"Not going to bother updating {market} {position.id:3d} ({position.purchase_price.quantize(market_params.price_tick_size):0.8f}): {position.sell_price:0.8f} to {target_price:0.8f} ({diff * Decimal('100.0'):.2f}%)")
                                continue
            
                        print(f"Revise  {market} {position.id:3d} {position.purchase_price.quantize(market_params.price_tick_size):0.8f} to: {target_price:0.8f} | {(target_price / position.purchase_price * Decimal('100.0')):.2f}%")

                    # Factor in the max percent price range allowed for API orders
                    max_price = (current_price * market_params.multiplier_up).quantize(market_params.price_tick_size)
                    if target_price > max_price:
                        print(f"{market} {position.id:3d} New price {target_price:0.8f} most likely exceeds PERCENT_PRICE {max_price:0.8f}")
                        # So for now set the LIMIT SELL price for the whole lot at nearly the PERCENT_PRICE limit
                        #   (this will most likely get re-set once the price gets closer).
                        target_price = (max_price * Decimal('0.99')).quantize(market_params.price_tick_size)
                        sell_quantity = position.buy_quantity

                        if target_price == position.sell_price:
                            # Nothing to change
                            continue

                    if target_price * sell_quantity < market_params.min_notional:
                        print(f"{market} {position.id:3d} sell order for {sell_quantity} @ {target_price:0.8f} ({target_price * sell_quantity:0.4f}) is below MIN_NOTIONAL ({market_params.min_notional})")
                        continue

                    # All clean records should have a sell_order_id, but we specifically catch
                    #   bad cases in AbstractExchange.update_order_statuses() so should deal with
                    #   them here.
                    if position.sell_order_id:
                        (success, result) = exchange.cancel_order(market, position.sell_order_id)

                        if not success:
                            print(f"ERROR CANCELING: {json.dumps(result, indent=4)}")

                        # Save changes in our local DB here so that it'll be easy to spot if the next step fails.
                        position.sell_order_id = None
                        position.save()
                    else:
                        # If there's no sell_order_id, it's already been canceled
                        pass

                    results = exchange.limit_sell(
                        market=market,
                        quantity=sell_quantity,
                        bid_price=target_price
                    )
                    """
                        {
                            "order_id": order_id,
                            "price": bid_price,
                            "quantity": quantized_qty
                        }
                    """
                    if results:
                        print(f"LIMIT SELL ORDER: {results}\n")
                        print(f"Revised {market} sell target = {(target_price / position.purchase_price * Decimal('100.0')):.2f}%")
                        position.sell_order_id = results['order_id']
                        position.sell_price = target_price
                        position.sell_quantity = sell_quantity
                        position.save()


    if buy_amount == Decimal('0.0'):
        # Report out status of current holdings, then we're done.
        current_positions = utils.open_positions_report()
        print(current_positions)

        scalped_positions = utils.scalped_positions_report()
        print("\n" + scalped_positions)
        exit()


    #------------------------------------------------------------------------------------
    #  BUY the next target based on the most favorable price_to_ma ratio

    # Don't allow too many consecutive buys
    recent_positions = LongPosition.get_last_positions(max_consecutive_buys)
    recent_markets = {p.market for p in recent_positions}

    # Are we too heavily weighted on a crypto on our watchlist?
    over_positioned = []
    num_positions = {}
    total_positions = LongPosition.get_open_positions().count()
    for crypto in watchlist:
        market = f"{crypto}{base_currency}"
        num_positions[crypto] = LongPosition.get_open_positions(market).count()
        if total_positions > 0 and Decimal(num_positions[crypto] / total_positions) >= max_crypto_holdings_percentage:
            over_positioned.append(crypto)

    ma_ratios = ""
    buy_candidates = []
    total_entries = Decimal('0')
    max_price_to_ma = max(metrics, key=lambda m:m['price_to_ma'])['price_to_ma']
    for metric in sorted(metrics, key = lambda i: i['price_to_ma']):
        market = metric['market']
        crypto = metric['market'][:(-1 * len(base_currency))]
        if crypto not in watchlist:
            # This is a historical crypto being updated
            continue

        price_to_ma = metric['price_to_ma']
        ma_ratios += f"{crypto}: price-to-MA: {price_to_ma:0.4f} | positions: {num_positions[crypto]}\n"

        # Consider any crypto that isn't overpositioned and hasn't had too many
        #   consecutive buys.
        #   Calculate a number of entries for a lottery selection process, based on
        #   price-to-MA distance to max_price_to_ma.
        if (crypto not in over_positioned
                and (market not in recent_markets or len(recent_markets) > 1)):
            # Use a cubed distance function to more heavily weight the lower price-to-MAs
            entries = (((max_price_to_ma - price_to_ma) * Decimal('100.0')) ** Decimal('3')).quantize(Decimal('1'))
            total_entries += entries

            buy_candidates.append({
                'market': market,
                'price_to_ma': price_to_ma,
                'entries': entries
            })
    print(ma_ratios)

    if len(buy_candidates) == 0:
        # They're all overpositioned or their price-to-MA is pumping!
        print(f"No buy candidates found.")
        exit()

    # Now build random odds list based on buy candidates and their price-to-MA;
    #   lower price-to-MA increases odds of being selected.
    lottery_markets = []
    lottery_weights = []
    for candidate in buy_candidates:
        print(f"candidate: {candidate['market']} | {int(candidate['entries']):4d} entries")
        lottery_markets.append(candidate['market'])
        lottery_weights.append(float(candidate['entries'] / total_entries))

    target_market = random.choices( population=lottery_markets,
                                    weights=lottery_weights,
                                    k=1)[0]
    target_metric = next(metric for metric in metrics if metric['market'] == target_market)

    # Set up a market buy for the first result that isn't overpositioned
    market = target_metric['market']
    crypto = market[:(-1 * len(base_currency))]
    exchange_name = target_metric['exchange']
    exchange = exchanges[exchange_name]
    ma_period = target_metric['ma_period']
    price_to_ma = target_metric['price_to_ma']

    current_price = exchange.get_current_ask(market)

    quantity = buy_amount / current_price

    market_params = MarketParams.get_market(market)
    quantized_buy_qty = quantity.quantize(market_params.lot_step_size)

    if quantized_buy_qty * current_price < market_params.min_notional:
        # Final order size isn't big enough
        print(f"Must increase quantized_buy_qty: {quantized_buy_qty} * {current_price} < {market_params.min_notional}")
        quantized_buy_qty += market_params.lot_step_size

    print(f"Buy: {'{:f}'.format(quantized_buy_qty.normalize())} {crypto} @ {current_price:0.8f} {base_currency}\n")

    if live_mode:
        results = exchange.buy(market, quantized_buy_qty)

        position = LongPosition.create(
            exchange=exchange_name,
            market=market,
            buy_order_id=results['order_id'],
            buy_quantity=results['quantity'],
            purchase_price=results['price'],
            fees=results['fees'],
            timestamp=results['timestamp'],
            watchlist=",".join(watchlist),
        )

        # Immediately place a LIMIT SELL order for this position.
        #   Initial sell price will be aggressive: avg of the current MA and the min profit target.
        #   This will get adjusted down later if the MA continues to drop. But if the current MA
        #   is less than the min profit target, we'll use that instead.
        min_profit_price = (position.purchase_price * profit_threshold).quantize(market_params.price_tick_size, rounding=ROUND_UP)
        target_price = ((target_metric['ma'] + min_profit_price)/Decimal('2.0')).quantize(market_params.price_tick_size, rounding=ROUND_UP)

        if target_price < min_profit_price:
            target_price = min_profit_price

        (sell_quantity, target_price) = position.calculate_scalp_sell_price(market_params, target_price)

        results = exchange.limit_sell(market, sell_quantity, target_price)
        """
            {
                "order_id": order_id,
                "price": bid_price,
                "quantity": quantized_qty
            }
        """
        print(f"LIMIT SELL ORDER: {results}\n")
        print(f"Sell target = {(target_price / position.purchase_price * Decimal('100.0')):.2f}%")
        position.sell_order_id = results['order_id']
        position.sell_price = results['price']
        position.save()

    # Report out status of updated holdings
    current_positions = utils.open_positions_report()
    print(current_positions)

    scalped_positions = utils.scalped_positions_report()
    print("\n" + scalped_positions)

    if live_mode:
        # Send SNS message
        subject = f"Bought {'{:f}'.format(quantized_buy_qty)} {crypto} ({price_to_ma*Decimal('100.0'):0.2f}% of {ma_period}-hr MA)"
        print(subject)
        message = ma_ratios
        message += "\n\n" + current_positions
        message += "\n\n" + scalped_positions

        sns.publish(
            TopicArn=sns_topic,
            Subject=subject,
            Message=message
        )


