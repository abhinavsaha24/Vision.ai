export function executeTrade(prediction, price, portfolio) {

  if (!prediction || !price) return portfolio;

  const newPortfolio = { ...portfolio };

  const tradeSize = portfolio.cash * 0.01 / price;

  if (prediction.direction === "UP") {

    if (newPortfolio.cash > price * tradeSize) {

      newPortfolio.cash -= price * tradeSize;
      newPortfolio.btc += tradeSize;

      newPortfolio.history.push({
        type: "BUY",
        price: price,
        size: tradeSize,
        time: new Date().toLocaleTimeString()
      });

    }

  }

  if (prediction.direction === "DOWN") {

    if (newPortfolio.btc >= tradeSize) {

      newPortfolio.cash += price * tradeSize;
      newPortfolio.btc -= tradeSize;

      newPortfolio.history.push({
        type: "SELL",
        price: price,
        size: tradeSize,
        time: new Date().toLocaleTimeString()
      });

    }

  }

  return newPortfolio;
}