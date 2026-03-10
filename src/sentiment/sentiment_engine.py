from src.sentiment.news_fetcher import NewsFetcher
from src.sentiment.sentiment_model import SentimentModel


class SentimentEngine:

    def __init__(self):

        self.fetcher = NewsFetcher()
        self.model = SentimentModel()

    def get_sentiment(self):

        headlines = self.fetcher.fetch_news()

        sentiment = self.model.analyze(headlines)

        return sentiment