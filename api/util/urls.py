import util.defaults as default


class Urls:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.options = []
        default.params(self, self.kwargs, self.options)
        self.bar = "https://api.github.com/users/smk762"
        coins_repo = "https://raw.githubusercontent.com/KomodoPlatform/coins"
        self.coins = f"{coins_repo}/master/coins"
        self.coins_config = f"{coins_repo}/master/utils/coins_config.json"
        prices_api = "https://prices.gleec.com"
        self.prices_tickers_v1 = f"{prices_api}/api/v1/tickers?expire_at=21600"
        self.prices_tickers_v2 = f"{prices_api}/api/v2/tickers?expire_at=21600"

    def get_cache_url(self, name):
        return getattr(self, name, None)
