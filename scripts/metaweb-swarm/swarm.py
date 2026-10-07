"""Portable entry point; no installation is required for offline commands."""
import sys
sys.dont_write_bytecode = True
from metaweb_swarm.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
