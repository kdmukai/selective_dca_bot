import argparse
import boto3
import configparser
import datetime
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
    ma_ratio_profit_threshold = Decimal(arg_config.get('CONFIG', 'MA_RATIO_PROFIT_THRESHOLD'))
    min_profit = Decimal(arg_config.get('CONFIG', 'MIN_PROFIT'))
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
    #  Update the status of open LongPositions
    if update_order_status:
        recently_sold = ""
        positions_sold = []
        for exchange_name, exchange in exchanges.items():
            positions = LongPosition.select(
                    ).where(
                        LongPosition.sell_quantity.is_null(True),
                        LongPosition.exchange == exchange_name
                    ).order_by(
                        LongPosition.market,
                        LongPosition.id
                    )
            for position in positions:
                result = exchange.get_sell_order_status(position)
                """
                    {
                        "status": NEW, etc,
                        "sell_price": price,
                        "quantity": quantity,
                        # "fees": fees,
                        "timestamp": ,
                    }
                """
                if result['status'] == 'FILLED':
                    position.sell_price = result['sell_price']
                    position.sell_quantity = result['quantity']
                    position.sell_timestamp = result['timestamp']
                    position.scalped_quantity = position.buy_quantity - position.sell_quantity
                    position.save()

                    positions_sold.append(position)
                    recently_sold += f"{position.market}: sold {'{:f}'.format(position.sell_quantity.normalize())} | recouped {'{:f}'.format((position.sell_quantity * position.sell_price).quantize(Decimal('0.00000001')))} {base_pair} | scalped {'{:f}'.format(position.scalped_quantity.normalize())}\n"

        if live_mode and len(positions_sold) > 0:
            subject = f"SOLD {len(positions_sold)} positions"
            print(recently_sold)
            message = recently_sold
            sns.publish(
                TopicArn=sns_topic,
                Subject=subject,
                Message=message
            )
            exit()


    if buy_amount == Decimal('0.0'):
        # Report out status of current holdings, then we're done.
        current_positions = utils.open_positions_report()
        print(current_positions)

        if update_order_status and len(positions_sold) > 0:
            print("\n" + recently_sold)

        scalped_positions = utils.scalped_positions_report()
        print("\n" + scalped_positions)
        exit()


    #------------------------------------------------------------------------------------
    #  BUY the next target based on the most favorable price_to_ma ratio
    metrics_sorted = sorted(metrics, key = lambda i: i['price_to_ma'])
    ma_ratios = ""
    target_metric = None

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

    for metric in metrics_sorted:
        market = metric['market']
        crypto = metric['market'][:(-1 * len(base_pair))]
        if crypto not in watchlist:
            # This is a historical crypto being updated
            continue

        ma_ratios += f"{crypto}: price-to-MA: {metric['price_to_ma']:0.4f} | positions: {num_positions[crypto]}\n"

        # Our target crypto's metric will be the first one on this list that isn't overpositioned
        #   and hasn't had too many consecutive buys.
        if (    not target_metric
                and crypto not in over_positioned
                and (market not in recent_markets or len(recent_markets) > 1)):
            target_metric = metric
    print(ma_ratios)

    if not target_metric:
        # All of the cryptos failed the over positioned test?!
        target_metric = metrics_sorted[0]

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

    print(f"Buy: {quantized_buy_qty.normalize()} {crypto} @ {current_price:0.8f} {base_pair}\n")

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

        # Immediately place a LIMIT SELL order for this position at the target profit level
        target_price = (position.purchase_price * profit_threshold).quantize(market_params.price_tick_size, rounding=ROUND_UP)

        # Must ROUND_UP to make sure we cover our initial investment
        sell_quantity = (position.spent / target_price).quantize(market_params.lot_step_size, rounding=ROUND_UP)

        if sell_quantity >= position.buy_quantity:
            # The lot_step_size is large (e.g. LTC's 0.01) so there's no way to take a profit
            #   slice this small. Have to target a bigger price jump in order to achieve a scalp.
            #   Resulting scalp quantity will equal the lot_step_size minimum.
            sell_quantity = (position.buy_quantity - market_params.lot_step_size).quantize(market_params.lot_step_size)
            target_price = (position.spent / sell_quantity).quantize(market_params.price_tick_size, rounding=ROUND_UP)

            print(f"Had to revise target_price up to {target_price} to preserve {(position.buy_quantity - sell_quantity)} scalp")

        results = exchange.limit_sell(market, sell_quantity, target_price)
        """
            {
                "order_id": order_id,
                "price": bid_price,
                "quantity": quantized_qty
            }
        """
        print(f"LIMIT SELL ORDER: {results}\n")
        position.sell_order_id = results['order_id']
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


