from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

class Base(DeclarativeBase):
    pass

db_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
engine = create_engine(
    db_url,
    echo=False,
    pool_pre_ping=True,       # test connection before using it, auto-reconnects on stale connections
    pool_recycle=300,         # recycle connections after 5 min to avoid server-side timeouts
    connect_args={"connect_timeout": 10},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
