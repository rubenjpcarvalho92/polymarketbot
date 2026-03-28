import time
from polymarket.client import PolymarketClient  # ajusta ao teu client

def score_market(m):
    spread = m["best_ask"] - m["best_bid"]
    liquidity = m["bid_size"] + m["ask_size"]

    if spread <= 0:
        return 0

    return liquidity / spread


def is_valid_market(m):
    if m["best_bid"] is None or m["best_ask"] is None:
        return False

    spread = m["best_ask"] - m["best_bid"]
    liquidity = m["bid_size"] + m["ask_size"]

    if spread > 0.03:
        return False

    if liquidity < 10000:
        return False

    if m["best_bid"] < 0.05 or m["best_ask"] > 0.95:
        return False

    return True


def main():
    client = PolymarketClient()

    print("Fetching markets...\n")
    markets = client.get_markets()  # depende do teu client

    scored = []

    for m in markets:
        try:
            if not is_valid_market(m):
                continue

            s = score_market(m)

            scored.append({
                "token_id": m["token_id"],
                "question": m.get("question", "N/A"),
                "best_bid": m["best_bid"],
                "best_ask": m["best_ask"],
                "spread": round(m["best_ask"] - m["best_bid"], 4),
                "liquidity": m["bid_size"] + m["ask_size"],
                "score": round(s, 2),
            })
        except Exception as e:
            continue

    scored.sort(key=lambda x: x["score"], reverse=True)

    print("TOP 10 MARKETS:\n")

    for i, m in enumerate(scored[:10], 1):
        print(f"{i}. {m['question']}")
        print(f"   token: {m['token_id']}")
        print(f"   bid/ask: {m['best_bid']} / {m['best_ask']}")
        print(f"   spread: {m['spread']}")
        print(f"   liquidity: {m['liquidity']}")
        print(f"   score: {m['score']}")
        print()


if __name__ == "__main__":
    main()