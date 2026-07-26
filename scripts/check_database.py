#!/usr/bin/env python3
"""Database checking script for StrongChat"""
import sys
import os

# Add src directory to path to import SQLite utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.sqlite.utils import check_database, get_database_stats


def main():
    """Check the database structure and display statistics."""
    print("StrongChat Database Check")
    print("=" * 30)
    
    # Check database structure
    check_database()
    
    # Get and display statistics
    print("\nDatabase Statistics:")
    print("=" * 30)
    try:
        stats = get_database_stats()
        for key, value in stats.items():
            print(f"{key.replace('_', ' ').title()}: {value}")
    except Exception as e:
        print(f"Error getting statistics: {e}")


if __name__ == "__main__":
    main()