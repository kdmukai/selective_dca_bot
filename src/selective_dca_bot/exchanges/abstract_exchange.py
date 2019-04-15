from abc import ABC, abstractmethod     # ABC = Abstract Base Class


class AbstractExchange(ABC):

    def __init__(self, api_key, api_secret, watchlist):
        super().__init__()
        self.watchlist = watchlist


    @abstractmethod
    def initialize_market(self, market):
        pass

