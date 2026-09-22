"""`python -m laplaces_hoard [--port P] [--data-dir DIR] [--demo] [--no-browser]`"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__
from .api import create_app
from .demo import seed_demo_data

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8812


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laplaces_hoard", description="Laplace's Hoard: exact numbers for language models.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--demo", action="store_true", help="use ./data-demo seeded with synthetic data")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab on start")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    if args.data_dir is not None:
        data_dir = args.data_dir
    elif args.demo:
        data_dir = REPO_ROOT / "data-demo"
    else:
        import os
        data_dir = Path(os.environ.get("LAPLACE_DATA_DIR", REPO_ROOT / "data"))

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.demo:
        seed_demo_data(data_dir, REPO_ROOT / "data-demo" / "files")

    static_dir = REPO_ROOT / "frontend" / "dist"
    app = create_app(data_dir=data_dir, static_dir=static_dir if static_dir.is_dir() else None, port=args.port)

    url = f"http://{args.host}:{args.port}"
    print(f"Laplace's Hoard v{__version__} — {url}  (data: {data_dir})", file=sys.stderr)
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
