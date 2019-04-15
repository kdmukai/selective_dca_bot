import argparse
import boto3
import configparser
import datetime
import time

from decimal import Decimal
from datetime import timedelta

from selective_dca_bot import config
from selective_dca_bot.exchanges import BinanceExchange, ExchangesManager
from selective_dca_bot.models import Candle


parser = argparse.ArgumentParser(description='Selective DCA (Dollar Cost Averaging) Bot')

# Required positional arguments
parser.add_argument('buy_amount', type=Decimal,
                    help="The quantity of the crypto to spend (e.g. 0.05)")
parser.add_argument('base_pair',
                    help="""The ticker of the currency to spend (e.g. 'BTC',
                        'ETH', 'USD', etc)""")

# Optional switches
parser.add_argument('-n', '--num_buys',
                    default=1,
                    dest="num_buys",
                    type=int,
                    help="Divide up the 'amount' across 'n' selective buys")

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

parser.add_argument('-r', '--daily_report',
                    action='store_true',
                    default=False,
                    dest="daily_report",
                    help="""Send out summary of day's activity""")

parser.add_argument('-w', '--weekly_report',
                    action='store_true',
                    default=False,
                    dest="weekly_report",
                    help="""Send out summary of the week's activity""")


def get_timestamp():
    ts = time.time()
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


if __name__ == '__main__':
    args = parser.parse_args()
    buy_amount = args.buy_amount
    base_pair = args.base_pair
    live_mode = args.live_mode
    config.is_test = not live_mode
    daily_report = args.daily_report
    weekly_report = args.weekly_report
    num_buys = args.num_buys
    exchange_list = args.exchanges.split(',')

    # Read settings
    arg_config = configparser.ConfigParser()
    arg_config.read(args.settings_config)

    binance_key = arg_config.get('API', 'BINANCE_KEY')
    binance_secret = arg_config.get('API', 'BINANCE_SECRET')

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

    if daily_report:
        from selective_dca_bot.models import LongPosition
        from selective_dca_bot import Twitter
        print("Tweeting out daily report!")
        results = LongPosition.get_24hr_results()
        message = "Results from the last 24hrs:\n\n"
        message += f"Total trades: {results['num_trades']}\n"
        message += f"Profit: {results['profit_percentage'] * 100.0:.2f}%\n"
        Twitter().tweet(message)
        exit()

    elif weekly_report:
        from selective_dca_bot.models import LongPosition
        from selective_dca_bot import Twitter
        print("Tweeting out weekly report!")
        results = LongPosition.get_results(since=timedelta(days=7))
        message = "Results from the last week:\n\n"
        message += f"Total trades: {results['num_trades']}\n"
        message += f"Profit: {results['profit_percentage'] * 100.0:.2f}%\n"
        Twitter().tweet(message)
        exit()

    # Read crypto watchlist
    arg_config = configparser.ConfigParser()
    arg_config.read(args.portfolio_config)

    watchlist = []
    binance_watchlist = [x.strip() for x in arg_config.get('WATCHLIST', 'BINANCE').split(',')]
    watchlist.extend(binance_watchlist)

    params = {
        "num_buys": num_buys,
    }

    test_period = 9  # days

    # Setup package-wide settings
    config.params = params
    config.interval = Candle.INTERVAL__1HOUR

    exchanges_data = []
    if 'binance' in exchange_list:
        exchanges_data.append(
            {
                'name': 'binance',
                'key': binance_key,
                'secret': binance_secret,
                'watchlist': binance_watchlist,
            }
        )

    ma_periods = [200, 100]

    # Retrieve exchanges, initialize each crypto on its watchlist, and update latest candles
    exchanges = ExchangesManager.get_exchanges(exchanges_data)
    metrics = []
    for exchange in exchanges:
        metrics.extend(exchange.calculate_latest_metrics(base_pair=base_pair, ma_periods=ma_periods))


    for metric in sorted(metrics, key = lambda i: i['price_to_ma']):
        print(f"{metric['market']}: close: {metric['close']:0.8f} | {metric['ma_period']}-hr MA: {metric['ma']:0.8f} | price-to-MA: {metric['price_to_ma']:0.4f}")




