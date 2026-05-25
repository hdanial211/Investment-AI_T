"""Active trade management modules."""

__all__ = ["ActiveTradeManager"]


def __getattr__(name):
    if name == "ActiveTradeManager":
        from .active_trade_manager import ActiveTradeManager
        return ActiveTradeManager
    raise AttributeError(name)
