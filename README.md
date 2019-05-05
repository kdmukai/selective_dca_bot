# SelectiveDCA Scalping Bot
A Dollar Cost Averaging (DCA) bot that does regular buys but opportunistically selects _which_ crypto to buy by comparing market conditions for all the assets in its user-set watchlist. At a specified profit threshold the bot will liquidate enough of a position to recover the initial investment and let the remaining "scalped" tokens ride.

![LRC chart](imgs/lrc_chart.png)
_DCA = Buy on a sched no matter what; SelectiveDCA = Bias toward the cryptos furthest below their 200-hr MA_


## Overview
The Dollar Cost Averaging investment philosophy is the easiest "set it and forget it" approach there is and is quite FOMO-resistant. DCA requires a longer-term commitment; it doesn't matter if the market happens to be up or down today, DCA will keep buying in regardless.

While I love the simplicity of DCA, you do end up buying into inopportune random spikes like LRC's "here today, gone tomorrow" pump in the image above. In the long run the "Averaging" part of DCA will smooth the spikes and valleys out, but I was curious to see if there might be room for some slight improvements by employing a tiny bit more intelligence to the buying process. In short: don't buy into a spike. SelectiveDCA will still buy in on a regular schedule, but it has the flexibility to spend its money on what it thinks is the best opportunity at the moment.

_Big caveat: if the opportunity metric used isn't great, SelectiveDCA will, of course, make bad decisions._

## Scalping
The term sounds nefarious but it just means that when you take profits you only sell off enough to recoup your initial investment. You then hold the remainder as "scalped" tokens to ride to higher profits (or crash to zero). It's a way to delay profit-taking to keep even greater upside potential on the table but with zero risk to your initial capital. Think of it as borrowing some of your base currency (typically BTC) in order to generate free tokens in some crypto XYZ.

_A future enhancement might add a scalped profit preservation threshold: if your scalped tokens drop to X% value, sell them off to lock in whatever profit is left before the price drops further._

## Selection Details
The bot is given a watchlist of cryptos that it can select amongst. For each crypto on its watchlist it will grab the latest hourly candles and compute the 200-hr MA for each. The closing price of the most recently completed candle is then divided by the crypto's 200-hr MA:

```
for crypto in watchlist:
    # get most recent candle and compute 200-hr MA
    ...

    # now compute the price_to_ma percentage:
    price_to_ma = last_candle.close / ma_200hr
```

The resulting `price_to_ma` will determine our sense of how good or poor an investment opportunity it is at the moment. 
```
    LRC: close: 0.00001464 BTC | 200-hr MA: 0.00001621 | price-to-MA: 0.9034
    ICX: close: 0.00007160 BTC | 200-hr MA: 0.00007646 | price-to-MA: 0.9365
    ONT: close: 0.00025990 BTC | 200-hr MA: 0.00027287 | price-to-MA: 0.9525
    XLM: close: 0.00002258 BTC | 200-hr MA: 0.00002352 | price-to-MA: 0.9600
    ETH: close: 0.03215900 BTC | 200-hr MA: 0.03311498 | price-to-MA: 0.9711
    LTC: close: 0.01581300 BTC | 200-hr MA: 0.01625708 | price-to-MA: 0.9727
    AST: close: 0.00000835 BTC | 200-hr MA: 0.00000857 | price-to-MA: 0.9745
    WAN: close: 0.00008180 BTC | 200-hr MA: 0.00008274 | price-to-MA: 0.9887
    XMR: close: 0.01299200 BTC | 200-hr MA: 0.01313567 | price-to-MA: 0.9891
    EOS: close: 0.00105770 BTC | 200-hr MA: 0.00106117 | price-to-MA: 0.9967
    VET: close: 0.00000137 BTC | 200-hr MA: 0.00000137 | price-to-MA: 0.9997
    BAT: close: 0.00005902 BTC | 200-hr MA: 0.00005708 | price-to-MA: 1.0341
    BNB: close: 0.00374330 BTC | 200-hr MA: 0.00358123 | price-to-MA: 1.0453
```

`price_to_ma` values below 1.0 mean that the current price is below the trend from the last 9 days. Currently only cryptos that are below their trendline are considered. If it was a big green candle day where every crypto on the watchlist was above its trendline, the bot would decline to make any buys.

### Heavily weighted randomized lottery selection
The bot takes the `price_to_ma` values that are below 1.0 and weights each crypto based on how far below their trendline they are. A cubed distance function is used so that the weights grow exponentially for lower `price_to_ma` values. These weights are then used to bias a lottery selection process where one crypto is selected from amongst the buy candidates. 

#### Why use a lottery?
First, the crypto with the lowest `price_to_ma` ratio is still the most likely to be selected, which is the overriding idea we're going for in this bot.

But what if two cryptos are both in nearly equally bad shape? Why should the bot keep buying just the lowest one at, say a `price_to_ma` of 0.8830, when its suffering compatriot is at 0.8835? They should really be nearly equally likely to be purchased by the bot which is what the weighted lottery selection allows for.

Finally, a little randomization is a good thing. The weighted randomized selection method was inspired by the NBA draft lottery; even the best team in the league has a non-zero chance of landing the first pick in the draft, but the worst team is still favored with the best odds. We have to be realistic and accept that the bot's selection metric (`price_to_ma` ratio) will never yield the 100% best possible pick. So instead we leave the final selection up to opinionated chance. Set up what we think makes the most sense, then trust in a little dumb luck.


## Philosophy
The core assumption here is that it's better to buy on the downtrends than when an asset is getting hot. Remember that we're starting from a hand-picked watchlist of cryptos; you should believe in the medium- to longer-term future of each crypto that you put on this list. That longer-term faith is what makes buying on the downtrends a reasonable play. 

And while the altcoin market does tend to ebb and flow together, they still seem to take their random turns driving suddenly up or down on their own. With a big enough collection of cryptos (8-10+) the hope is that you can take advantage of these random opportunities without having to keep an eye on everything yourself.

## Why 200-hr MA?
This is where the art and expertise come in (of which I claim neither). First of all I chose a metric on the hourly candles because I'll be running this SelectiveDCA Bot multiple times each day. Daily candles wouldn't have enough resolution while  5/15/30-min candles were more granular and more short-term than I wanted to be concerned with.

The 200-hr MA seemed to strike the right balance of reaction speed vs stability. If the period is too long, the MA shows after-effects long after a move happened and won't capture the current realities of the market. If the period is too short, the MA will be too tightly tied to the day's volatility (a minor pullback amidst a bigger move could seem like a bigger deal than it actually is).

Maybe an EMA would be better? Maybe 150 candles? To each his or her own.

## Sell/Scalp config
_The strategies here are somewhat experimental and in flux._

When the bot makes a buy it will also immediately place a LIMIT SELL order at the `PROFIT_THRESHOLD` you specify in your `settings.conf`. This way you're guaranteed to successfully exit your position whenever the price pumps back up and without having to have the bot constantly monitoring price action. This has the added benefit of making it clearer which tokens on the exchange are being managed by the bot, as they'll be tied up as "In order" tokens in your exchange balances.

_It might make sense to have a secondary, lower profit threshold if a certain amount of time has elapsed on the open position (i.e. we've been stuck in crypto XYZ for weeks without hitting the `PROFIT_THRESHOLD` target; just get us out asap, even at a smaller profit--or even break even or a slight loss if we're really desperate--on the next mini-pump)._

Also note that the LIMIT SELL is set _for each individual position_ the bot takes. So 10 positions for the same crypto could all have different target sell prices. This mirrors the DCA philosophy where now our sell targets are as spread out as our buys are. On a good day some of your positions in crypto XYZ will hit their limit price and exit while other positions won't. There are no monolithic all-or-nothing moves here. Opportunistic nibbles in, opportunistic nibbles out.


### Profit threshold strategy
There will always be a tradeoff between constantly capitalizing on smaller moves up and down vs trying to catch some of crypto's famous violent big swings. 

My current strategy is to keep `PROFIT_THRESHOLD` very modest: 1.05 (aka 5%). I'm hoping most of my positions can hit this target within days or no more than a few short weeks. Playing this kind of small ball would of course be frustrating on a huge green day; your crypto jumps 30% but the bot cashed out its positions in the first 5%. That's life. I'm fine with missing out.

And remember that my small cache of scalped tokens that the bot will retain will ride on to that 30% gain and beyond. It's not the biggest win possible, but still a win.

But why play so conservatively? Well, realistically, those giant moves don't happen as often as it seems. But small moves -- 3-5% losses and gains -- seem to happen every week, if not nearly every day. If you can keep nibbling away, capturing 3-5% scalps and recouping your initial risk capital, over and over and over that will add up over time. Yes, the big, meaty bites are amazing, but maybe 1000 mice can find more scraps of food than the lion that infrequently lands a gazelle. While you're waiting for a +20% home run, a smaller 3-5% setting might have already yielded you more than that by playing the many up-down cycles that occurred on the way up to that +20% price.

This also banks on the idea that chart movements aren't straight lines. The overall trend might be up or down (choose your watchlist wisely!) but there's lots of noise along the way. Profit on the bumpy ride that lives within the trend.

There's also greater risk to your initial capital the higher you set the `PROFIT_THRESHOLD`. More of your funds will be tied up as the bot waits to hit a harder, less likely target.

Play safe(ish) small ball with your risk capital. In the long run you'll profit enough from your scalped tokens while seeing more of your risk capital returned safely home. Or so I think.


## Disclaimer
_I built this to execute my own micro dollar cost-averaging crypto buys. Use and modify it at your own risk. This is also not investment advice. I am not an investment advisor. Always #DYOR - Do Your Own Research and invest in the way that best suits your needs and risk profile._


# Tips
If you found this useful, send me some digital love
- ETH: 0xb581603e2C4eb9a9Ece4476685f0600CeB472241
- BTC: 13u1YbpSzNsvVpPMyzaDAfzP2jRcZUwh96
- LTC: LMtPGHCQ3as6AEC9ueX4tVQw7GvHegv3fA
- DASH: XhCnytvKkV44Mn5WeajGfaifgY8vGtamW4
