"""Market: holds current prices and adjusts them based on each round's supply/demand."""

from .config import BASE_PRICES, PRICE_ELASTICITY


class Market:
    def __init__(self):
        self.prices: dict = dict(BASE_PRICES)

    def update(self, round_transactions: list[dict]) -> None:
        net_flow = {resource: 0.0 for resource in self.prices}
        proposed_prices = {resource: [] for resource in self.prices}

        for tx in round_transactions:
            resource = tx.get("resource")
            if tx.get("action") in ("trade", "buy_futures") and resource in net_flow:
                net_flow[resource] += tx.get("amount") or 0
                if tx.get("price_per_unit"):
                    proposed_prices[resource].append(tx["price_per_unit"])

        for resource, price in self.prices.items():
            # More trading volume for a resource this round -> stronger demand signal -> price rises.
            demand_signal = min(net_flow[resource] / 10, 1.0)
            adjusted = price * (1 + PRICE_ELASTICITY * demand_signal)

            # If anyone (typically the Financier) explicitly proposed a price, blend it in.
            proposals = proposed_prices[resource]
            if proposals:
                avg_proposed = sum(proposals) / len(proposals)
                adjusted = (adjusted + avg_proposed) / 2

            self.prices[resource] = round(max(adjusted, 0.1), 2)

    def snapshot(self) -> dict:
        return dict(self.prices)
