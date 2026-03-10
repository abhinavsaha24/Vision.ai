import requests


class NewsFetcher:

    def __init__(self):

        self.url = "https://cryptopanic.com/api/v1/posts/"

        self.params = {
            "auth_token": "demo",
            "kind": "news"
        }

    def fetch_news(self):

        try:

            response = requests.get(self.url, params=self.params)

            data = response.json()

            headlines = []

            for item in data.get("results", []):

                headlines.append(item["title"])

            return headlines

        except Exception:

            return []