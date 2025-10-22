"""Database configuration and connection management."""

import os
from typing import Optional

from sqlalchemy import create_engine, Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

Base = declarative_base()


class DatabaseConfig:
    """Database configuration class."""

    def __init__(self):
        self.database_url = os.getenv(
            "DATABASE_URL", "mysql://crypto_user:crypto_pass@mysql:3306/crypto_pachinko"
        )
        self.host = os.getenv("MYSQL_HOST", "mysql")
        self.port = int(os.getenv("MYSQL_PORT", "3306"))
        self.database = os.getenv("MYSQL_DATABASE", "crypto_pachinko")
        self.user = os.getenv("MYSQL_USER", "crypto_user")
        self.password = os.getenv("MYSQL_PASSWORD", "crypto_pass")

    def get_database_url(self) -> str:
        """Get complete database URL."""
        return self.database_url


class DatabaseManager:
    """Database connection manager."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig()
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None

    @property
    def engine(self) -> Engine:
        """Get database engine."""
        if self._engine is None:
            self._engine = create_engine(
                self.config.get_database_url(),
                echo=False,  # Set to True for SQL logging
                pool_pre_ping=True,
                pool_recycle=3600,
            )
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        """Get session factory."""
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                autocommit=False, autoflush=False, bind=self.engine
            )
        return self._session_factory

    def get_session(self) -> Session:
        """Create a new database session."""
        return self.session_factory()

    def create_tables(self) -> None:
        """Create all tables."""
        Base.metadata.create_all(bind=self.engine)

    def test_connection(self) -> bool:
        """Test database connection."""
        try:
            with self.engine.connect() as connection:
                connection.execute("SELECT 1")
            return True
        except Exception as e:
            print(f"Database connection failed: {e}")
            return False


# Global database manager instance
db_manager = DatabaseManager()


def get_db_session() -> Session:
    """Get database session for dependency injection."""
    return db_manager.get_session()
