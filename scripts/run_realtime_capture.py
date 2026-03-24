from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.data.microstructure_store import MicrostructureParquetStore
from backend.src.data.multi_venue_realtime import MultiVenueRealtimeIngestor
from backend.src.data.venue_adapters import build_adapter


async def _run(venues: list[str], symbols: list[str], out_dir: str, flush_every: int) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _stop())

    tasks: list[asyncio.Task] = []
    for venue in venues:
        adapter = build_adapter(venue)
        store = MicrostructureParquetStore(root_dir=out_dir, flush_every=flush_every)
        ingestor = MultiVenueRealtimeIngestor(adapter=adapter, symbols=symbols, store=store)
        tasks.append(asyncio.create_task(ingestor.run(stop_event)))

    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run realtime multi-venue microstructure capture")
    parser.add_argument("--venues", nargs="+", default=["binance"], help="Supported: binance bybit okx")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT"], help="Symbols, e.g. BTCUSDT ETHUSDT")
    parser.add_argument("--output-dir", default="data/microstructure")
    parser.add_argument("--flush-every", type=int, default=2000)
    args = parser.parse_args()

    asyncio.run(
        _run(
            venues=[str(v).lower() for v in args.venues],
            symbols=[str(s).upper() for s in args.symbols],
            out_dir=str(args.output_dir),
            flush_every=int(args.flush_every),
        )
    )


if __name__ == "__main__":
    main()
