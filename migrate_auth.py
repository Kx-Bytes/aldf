import sys
sys.path.insert(0, '.')
from backend.app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"))
    conn.execute(text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE"))
    conn.execute(text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS verification_token VARCHAR(36)"))
    # Add unique constraint only if it doesn't exist
    conn.execute(text("""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'user_profiles_verification_token_key'
          ) THEN
            ALTER TABLE user_profiles ADD CONSTRAINT user_profiles_verification_token_key UNIQUE (verification_token);
          END IF;
        END
        $$;
    """))
    conn.commit()

print("DB migration complete!")
