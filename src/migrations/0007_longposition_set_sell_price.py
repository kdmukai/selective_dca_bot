import time

from decimal import Decimal

from selective_dca_bot.models import LongPosition, MarketParams


"""
    Fix-up data migration to set LIMIT SELL orders for all existing LongPositions that
    were created in the earlier era where LIMIT SELLs weren't being automatically
    placed immediately after the BUY.

    To run: Move this script up to the `src` dir and run
"""
if __name__ == '__main__':
    profit_threshold = Decimal('1.05')
    positions = LongPosition.select(
            ).where(
                LongPosition.sell_timestamp.is_null(True)
            ).order_by(
                LongPosition.market
            )

    market_params = MarketParams.get_market(positions[0].market)

    for index, position in enumerate(positions):
        market = position.market
        if market_params.market != market:
            market_params = MarketParams.get_market(market)

        target_price = (position.purchase_price * profit_threshold).quantize(market_params.price_tick_size)
        (sell_quantity, target_price) = position.calculate_scalp_sell_price(market_params, target_price)

        print(f"{position.id}: {position.market} | {position.buy_quantity} | {position.purchase_price:0.8f} | {sell_quantity} | {target_price} | {target_price / position.purchase_price * Decimal('100.0'):0.2f}% | {target_price * sell_quantity:0.8f} BTC | {(position.buy_quantity - sell_quantity).quantize(market_params.lot_step_size)}")

        position.sell_price = target_price
        position.sell_quantity = sell_quantity
        position.save()

