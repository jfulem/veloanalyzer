#!/usr/bin/env python3
"""CLI wrapper — run a one-off ingest into Postgres.

Requires DATABASE_URL. The real implementation lives in mtb_analyzer/ingest.py
so the API process can schedule it without importing from scripts/.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtb_analyzer.ingest import run

if __name__ == "__main__":
    run()
