"""Embeds every chunk that has no embedding yet, in batches. Safe to stop and run again.

Run:  python scripts/backfill_embeddings.py [--batch-size 50]
Rate limits (429) and temporary errors are retried with backoff inside embeddings.embed_texts.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from documine import embeddings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=embeddings.BATCH_SIZE)
    args = parser.parse_args()
    try:
        total = embeddings.backfill_embeddings(
            batch_size=args.batch_size, on_progress=lambda done: print(f"embedded {done} chunks", flush=True))
    except Exception as e:
        print(f"Backfill stopped: {e}\nChunks embedded so far are saved; run the script again to continue.")
        return 1
    print(f"Done. {total} chunks embedded." if total else "Nothing to do: every chunk already has an embedding.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
