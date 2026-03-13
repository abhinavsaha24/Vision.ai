import ccxt


class BinanceEngine:

    def __init__(self, api_key: str, secret: str):

        self.exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        })


    def get_balance(self):

        balance = self.exchange.fetch_balance()

        return balance["total"]


    def place_market_buy(self, symbol: str, quantity: float):

        order = self.exchange.create_market_buy_order(
            symbol,
            quantity
        )

        return order


    def place_market_sell(self, symbol: str, quantity: float):

        order = self.exchange.create_market_sell_order(
            symbol,
            quantity
        )

        return order


    def get_open_orders(self, symbol: str):

        return self.exchange.fetch_open_orders(symbol)


    def cancel_order(self, order_id: str, symbol: str):

        return self.exchange.cancel_order(order_id, symbol)