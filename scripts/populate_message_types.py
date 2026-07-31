#!/usr/bin/env python3
"""Legacy script - intent_classification is no longer used.

This script is deprecated and kept for reference only.
All intent processing now uses intent_generation in the pipeline.
"""

import argparse
import json
import os
import sqlite3
import sys

print("Warning: populate_message_types.py is deprecated.")
print("Use migrate_pipeline_message_types.py instead.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Populate ref_message_types table (idempotent)")
    parser.add_argument(
        '--db-path',
        default='data/chat_database.db',
        help='Path to SQLite database file (default: data/chat_database.db)')
    args = parser.parse_args()
    populate_message_types(args.db_path)
