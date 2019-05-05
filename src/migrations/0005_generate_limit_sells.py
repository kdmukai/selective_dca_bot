import time

from decimal import Decimal

from selective_dca_bot.models import LongPosition, MarketParams
from selective_dca_bot.exchanges import BinanceExchange


"""
    Fix-up data migration to set LIMIT SELL orders for all existing LongPositions that
    were created in the earlier era where LIMIT SELLs weren't being automatically
    placed immediately after the BUY.
"""
if __name__ == '__main__':
    profit_threshold = Decimal('1.05')
    positions = LongPosition.select(
            ).where(
                LongPosition.sell_quantity.is_null(True),
                LongPosition.sell_order_id.is_null(True)
            ).order_by(
                LongPosition.market
            )

    market_params = MarketParams.get_market(positions[0].market)
    exchange = BinanceExchange(api_key, api_secret, positions[0].watchlist)

    for index, position in enumerate(positions):
        market = position.market
        if market_params.market != market:
            market_params = MarketParams.get_market(market)

        target_price = (position.purchase_price * profit_threshold).quantize(market_params.price_tick_size)
        sell_quantity = (position.spent / target_price).quantize(market_params.lot_step_size)

        if sell_quantity >= position.buy_quantity:
            # The lot_step_size is large (e.g. LTC's 0.01) so there's no way to take a profit
            #   slice this small. Have to wait for a bigger jump in order to achieve a scalp.
            sell_quantity = (sell_quantity - market_params.lot_step_size).quantize(market_params.lot_step_size)
            target_price = (position.spent / sell_quantity).quantize(market_params.price_tick_size)

            print(f"Had to revise target_price up to {target_price} to preserve {(position.buy_quantity - sell_quantity)} scalp")

        print(f"{position.id}: {position.market} | {position.buy_quantity} | {position.purchase_price:0.8f} | {sell_quantity} | {target_price} | {target_price / position.purchase_price * Decimal('100.0'):0.2f}% | {target_price * sell_quantity:0.8f} BTC | {(position.buy_quantity - sell_quantity).quantize(market_params.lot_step_size)}")

        results = exchange.limit_sell(market, sell_quantity, target_price)
        """
            {
                "order_id": order_id,
                "price": bid_price,
                "quantity": quantized_qty
            }
        """
        position.sell_order_id = results['order_id']
        position.save()

        if index % 5 == 0:
            time.sleep(1)

