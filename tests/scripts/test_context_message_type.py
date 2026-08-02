#!/usr/bin/env python3
"""Regression test for context_retrieval ref-message-type in migration script.

Tests the _seed_rows() function directly on an in-memory fixture to verify:
- 6 total rows after seeding
- context_retrieval row has correct properties
- creator_type='programmatic' (not 'llm')
- request_schema is summary shape (contains translation_count in required)
- prompt_template IS NULL
- model_slug='n/a'
- Idempotency: second run doesn't increase row count
"""
import json
import sqlite3
import sys
import os

# Add scripts directory to path to import the migration module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

import migrate_pipeline_message_types as migration

def test_context_message_type():
    """Test context_retrieval row properties and idempotency."""
    print("Testing context_retrieval ref-message-type...")
    
    # Create in-memory database and build schema
    conn = sqlite3.connect(':memory:')
    conn.execute("""
        CREATE TABLE "ref_message_types" (
            slug TEXT PRIMARY KEY,
            step_name TEXT NOT NULL,
            creator_type TEXT NOT NULL,
            request_schema TEXT NOT NULL,
            model_slug TEXT NOT NULL,
            temperature REAL DEFAULT 0.1,
            additional_model_settings TEXT,
            max_retries INTEGER DEFAULT 3,
            is_active BOOLEAN DEFAULT TRUE,
            description TEXT,
            prompt_template TEXT
        )
    """)
    
    try:
        # Seed with the 5 existing rows (excluding context_retrieval)
        conn.executemany(migration.INSERT_SQL, migration.PIPELINE_MESSAGE_TYPES)
        conn.execute(migration.INTENT_GENERATION_SQL, migration.INTENT_GENERATION_ROW)
        conn.execute(migration.INTENT_GENERATION_SQL, migration.HYDE_GENERATION_ROW)
        conn.commit()
        
        # Verify initial state (5 rows)
        initial_rows = conn.execute("SELECT COUNT(*) FROM ref_message_types").fetchone()[0]
        assert initial_rows == 5, f"Expected 5 initial rows, got {initial_rows}"
        print(f"✓ Initial state: {initial_rows} rows")
        
        # Add context_retrieval row using the refactored function
        migration._seed_rows(conn)
        conn.commit()
        
        # Verify total rows (6)
        total_rows = conn.execute("SELECT COUNT(*) FROM ref_message_types").fetchone()[0]
        assert total_rows == 6, f"Expected 6 rows after seeding, got {total_rows}"
        print(f"✓ Total rows after seeding: {total_rows}")
        
        # Verify context_retrieval row exists
        conn.row_factory = sqlite3.Row
        context_row = conn.execute(
            "SELECT * FROM ref_message_types WHERE slug = 'context_retrieval'"
        ).fetchone()
        assert context_row is not None, "context_retrieval row not found"
        print("✓ context_retrieval row exists")
        
        # Convert row to dict for easier access
        context_dict = dict(context_row)
        
        # Verify creator_type is 'programmatic' (not 'llm')
        assert context_dict['creator_type'] == 'programmatic', \
            f"Expected creator_type='programmatic', got '{context_dict['creator_type']}'"
        print("✓ creator_type='programmatic'")
        
        # Verify model_slug is 'n/a'
        assert context_dict['model_slug'] == 'n/a', \
            f"Expected model_slug='n/a', got '{context_dict['model_slug']}'"
        print("✓ model_slug='n/a'")
        
        # Verify prompt_template IS NULL
        assert context_dict['prompt_template'] is None, \
            f"Expected prompt_template=NULL, got '{context_dict['prompt_template']}'"
        print("✓ prompt_template IS NULL")
        
        # Verify request_schema is valid JSON and contains translation_count in required
        request_schema = json.loads(context_dict['request_schema'])
        assert 'required' in request_schema, "request_schema missing 'required' field"
        assert 'translation_count' in request_schema['required'], \
            "translation_count not in required list"
        print("✓ request_schema is summary shape with translation_count in required")
        
        # Verify step_name and description
        assert context_dict['step_name'] == 'Context Retrieval', \
            f"Expected step_name='Context Retrieval', got '{context_dict['step_name']}'"
        assert context_dict['description'] == 'Per-intent original-language context enrichment for retrieved verses', \
            f"Unexpected description: '{context_dict['description']}'"
        print("✓ step_name and description are correct")
        
        # Test idempotency: run _seed_rows again and verify row count unchanged
        migration._seed_rows(conn)
        conn.commit()
        
        final_rows = conn.execute("SELECT COUNT(*) FROM ref_message_types").fetchone()[0]
        assert final_rows == 6, f"Expected 6 rows after idempotent run, got {final_rows}"
        print("✓ Idempotency verified: second run didn't increase row count")
        
        print("\nPASS: All context_retrieval ref-message-type tests passed")
        return True
        
    except Exception as e:
        print(f"FAIL: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    success = test_context_message_type()
    sys.exit(0 if success else 1)