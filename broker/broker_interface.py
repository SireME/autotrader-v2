from abc import ABC, abstractmethod


class BrokerInterface(ABC):
    @abstractmethod
    def place_trade(self, trade):
        raise NotImplementedError

    @abstractmethod
    def get_open_positions_count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def get_today_pnl(self) -> float:
        raise NotImplementedError
