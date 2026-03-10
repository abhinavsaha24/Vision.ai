from textblob import TextBlob


class SentimentModel:

    def analyze(self, headlines):

        if not headlines:
            return 0

        scores = []

        for text in headlines:

            blob = TextBlob(text)

            scores.append(blob.sentiment.polarity)

        sentiment = sum(scores) / len(scores)

        return sentiment