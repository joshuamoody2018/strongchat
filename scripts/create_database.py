#!/usr/bin/env python3
"""Database creation script for StrongChat"""
import sys
import os

# Add src directory to path to import SQLite utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.sqlite.utils import create_database


def main():
    """Create the database and tables."""
    print("Creating StrongChat database...")
    create_database()
    print("Database creation complete!")


if __name__ == "__main__":
    main()