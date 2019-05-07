import argparse
import boto3
import configparser
import datetime
import random
import time

from decimal import Decimal, ROUND_UP
from datetime import timedelta

from selective_dca_bot import config, utils
from selective_dca_bot.exchanges import BinanceExchange, ExchangesManager, EXCHANGE__BINANCE
from selective_dca_bot.models import Candle, LongPosition, MarketParams, AllTimeWatchlist


parser = argparse.ArgumentParser(description='Selective DCA (Dollar Cost Averaging) Bot')

# Required positional arguments
parser.add_argument('buy_amount', type=Decimal,
                    help="The quantity of the crypto to spend (e.g. 0.05)")
parser.add_argument('base_pair',
                    help="""The ticker of the currency to spend (e.g. 'BTC',
                        'ETH', 'USD', etc)""")

# Optional switches
# parser.add_argument('-n', '--num_buys',
#                     default=1,
#                     dest="num_buys",
#                     type=int,
#                     help="Divide up the 'amount' across 'n' selective buys")

parser.add_argument('-e', '--exchanges',
                    default='binance',
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
    base_pair = args.base_pair
    live_mode = args.live_mode
    update_order_status = args.update_order_status
    config.is_test = not live_mode
    performance_report = args.performance_report
    # num_buys = args.num_buys
    exchange_list = args.exchanges.split(',')

    # Read settings
    arg_config = configparser.ConfigParser()
    arg_config.read(args.settings_config)

    binance_key = arg_config.get('API', 'BINANCE_KEY')
    binance_secret = arg_config.get('API', 'BINANCE_SECRET')

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
    binance_watchlist = [x.strip() for x in arg_config.get('WATCHLIST', 'BINANCE').split(',')]
    watchlist.extend(binance_watchlist)

    do_not_sell_list = []
    binance_do_not_sell_list = arg_config.get('DO_NOT_SELL_LIST', 'BINANCE', fallback=None)
    if binance_do_not_sell_list:
        binance_do_not_sell_list = [x.strip() for x in binance_do_not_sell_list.split(',')]
        do_not_sell_list.extend(binance_do_not_sell_list)

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
    if EXCHANGE__BINANCE in exchange_list:
        exchanges_data.append(
            {
                'name': EXCHANGE__BINANCE,
                'key': binance_key,
                'secret': binance_secret,
                'watchlist': binance_watchlist,
            }
        )

    exchanges = ExchangesManager.get_exchanges(exchanges_data)
    metrics = []
    for name, exchange in exchanges.items():
        metrics.extend(exchange.calculate_latest_metrics(base_pair=base_pair, interval=config.interval, ma_periods=ma_periods))
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
                            LongPosition.sell_quantity.is_null(True)
                        ).order_by(
                            LongPosition.sell_order_id
                        )
                if positions.count() == 0:
                    continue

                positions_sold = exchange.update_order_statuses(market, positions)

                for position in positions_sold:
                    num_positions_sold += 1
                    recently_sold += f"{position.market}: sold {'{:f}'.format(position.sell_quantity.normalize())} | recouped {'{:f}'.format((position.sell_quantity * position.sell_price).quantize(Decimal('0.00000001')))} {base_pair} | scalped {'{:f}'.format(position.scalped_quantity.normalize())}\n"

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
                current_ma = metric['ma'].quantize(market_params.price_tick_size)

                # Get this market's open positions
                positions = LongPosition.select(
                        ).where(
                            LongPosition.exchange == exchange_name,
                            LongPosition.market == market,
                            LongPosition.sell_timestamp.is_null(True),
                        ).order_by(
                            LongPosition.purchase_price,
                            LongPosition.id
                        )

                if positions.count() == 0:
                    continue

                for position in positions:
                    min_sell_price = (position.purchase_price * profit_threshold).quantize(market_params.price_tick_size)

                    # Account for cryptos like LTC with high-value price_tick_sizes
                    (sell_quantity, target_price) = position.calculate_scalp_sell_price(market_params, min_sell_price)
                    if target_price > current_ma:
                        if target_price == position.sell_price:
                            # This position is already at its min profit. Just have to keep holding
                            #print(f"Keeping {market} {position.id:3d} at: {position.purchase_price.quantize(market_params.price_tick_size)} | {target_price}")
                            continue
                        else:
                            # MA just dropped below the min_sell_price. Update to the target_price we just calculated.
                            pass

                    else:
                        (sell_quantity, target_price) = position.calculate_scalp_sell_price(market_params, current_ma)
        
                    print(f"Revise  {market} {position.id:3d} {position.sell_price} to: {target_price} | {(target_price / position.purchase_price * Decimal('100.0')):.2f}%")

                    (success, result) = exchange.cancel_order(market, position.sell_order_id)

                    if not success:
                        print(f"ERROR CANCELING: {json.dumps(result, indent=4)}")

                    # Save changes in our local DB here so that it'll be easy to spot if the next step fails.
                    position.sell_order_id = None
                    position.save()

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
        market = f"{crypto}{base_pair}"
        num_positions[crypto] = LongPosition.get_open_positions(market).count()
        if Decimal(num_positions[crypto] / total_positions) >= max_crypto_holdings_percentage:
            over_positioned.append(crypto)

    ma_ratios = ""
    buy_candidates = []
    total_entries = Decimal('0')
    for metric in sorted(metrics, key = lambda i: i['price_to_ma']):
        market = metric['market']
        crypto = metric['market'][:(-1 * len(base_pair))]
        if crypto not in watchlist:
            # This is a historical crypto being updated
            continue

        price_to_ma = metric['price_to_ma']
        ma_ratios += f"{crypto}: price-to-MA: {price_to_ma:0.4f} | positions: {num_positions[crypto]}\n"

        # Consider any crypto that isn't overpositioned, hasn't had too many consecutive
        #   buys, and whose price-to-MA is below 1.0.
        #   Calculate a number of entries for a lottery selection process, based on
        #   price-to-MA.
        if (crypto not in over_positioned
                and (market not in recent_markets or len(recent_markets) > 1)
                and price_to_ma < Decimal('1.0')):
            # Use a cubed distance function to more heavily weight the lower price-to-MAs
            entries = (((Decimal('1.0') / price_to_ma * Decimal('100.0')) - Decimal('100.0')) ** Decimal('3')).quantize(Decimal('1'))
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
    crypto = market[:(-1 * len(base_pair))]
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

    print(f"Buy: {'{:f}'.format(quantized_buy_qty.normalize())} {crypto} @ {current_price:0.8f} {base_pair}\n")

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
        #   Initial sell price will be aggressive: the current MA. This will get adjusted
        #   down later if the MA continues to drop. But if the current MA is less than the
        #   min profit target, we'll use that instead.
        target_price = target_metric['ma'].quantize(market_params.price_tick_size, rounding=ROUND_UP)
        min_profit_price = (position.purchase_price * profit_threshold).quantize(market_params.price_tick_size, rounding=ROUND_UP)

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


