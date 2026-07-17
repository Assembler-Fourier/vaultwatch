"""Standalone convenience script: prints a sample of the synthetic data the
service generates in-process at startup, and fits the pre-filter once as a
sanity check. Not required for the service to run - it self-seeds - but
useful for eyeballing what "synthetic" means here before you trust it.
"""

from __future__ import annotations

from app.prefilter import AnomalyPreFilter
from app.synthetic import (
    account_profile,
    generate_demo_transaction,
    generate_entity_graph,
    generate_transaction_history,
)


def main() -> None:
    account_id = "acct_seed_demo"
    print(f"Account profile for {account_id}: {account_profile(account_id)}\n")
    print("Sample transaction history:")
    for row in generate_transaction_history(account_id, n=5):
        print(f"  {row}")

    print(f"\nEntity graph: {generate_entity_graph(account_id)}")

    print("\nSample normal transaction:", generate_demo_transaction(force_risky=False, account_id=account_id))
    print("Sample risky transaction:  ", generate_demo_transaction(force_risky=True, account_id=account_id))

    prefilter = AnomalyPreFilter()
    prefilter.fit()
    print("\nIsolationForest pre-filter fitted on synthetic baseline OK.")


if __name__ == "__main__":
    main()
