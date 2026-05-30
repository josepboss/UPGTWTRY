"""
PostPilot - Database Models
SQLAlchemy ORM schema for Accounts, Content Queue, and System Settings.
"""

import os
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime,
    Enum as SAEnum, Boolean, Float
)
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pilot.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


# ─── Accounts ────────────────────────────────────────────────────────────────
class Account(Base):
    """Represents a managed social media account (X/TikTok)."""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(16), nullable=False, default="X")       # "X" or "TikTok"
    username = Column(String(128), nullable=False)
    password = Column(String(512), nullable=False)                   # stored encrypted in production
    profile_folder = Column(String(512), nullable=False,
                            default=lambda: os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                         "profiles", f"profile_{os.urandom(4).hex()}"))
    proxy_string = Column(String(256), default="")                   # http://user:pass@ip:port
        auth_token = Column(String(512), default="")                     # X/Twitter auth_token cookie
        status = Column(String(32), nullable=False, default="Paused")    # Active, Paused, Flagged, Needs Auth
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Account(id={self.id}, {self.platform}:{self.username}, status={self.status})>"


# ─── Content Queue ───────────────────────────────────────────────────────────
class ContentQueue(Base):
    """Queued posts waiting to be published."""
    __tablename__ = "content_queue"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, nullable=False, index=True)         # FK to Account.id
    media_path = Column(String(512), default="")                     # path to raw media file
    caption = Column(Text, default="")
    status = Column(String(32), nullable=False, default="Pending")   # Pending, Processing, Posted, Failed
    scheduled_time = Column(DateTime, nullable=True)                  # None = post ASAP
    platform_post_id = Column(String(256), default="")               # ID returned by platform
    log_message = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ContentQueue(id={self.id}, account={self.account_id}, status={self.status})>"


# ─── System Settings ─────────────────────────────────────────────────────────
class SystemSettings(Base):
    """Global configuration knobs for safety and pacing."""
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(256), default="")

    @classmethod
    def get(cls, session, key: str, default: str = "") -> str:
        """Fetch a setting by key, returning *default* if missing."""
        row = session.query(cls).filter(cls.key == key).first()
        return row.value if row else default

    @classmethod
    def set(cls, session, key: str, value: str, description: str = ""):
        """Upsert a setting."""
        row = session.query(cls).filter(cls.key == key).first()
        if row:
            row.value = value
        else:
            row = cls(key=key, value=value, description=description)
            session.add(row)
        session.commit()


# ─── Log Lines ───────────────────────────────────────────────────────────────
class SystemLog(Base):
    """Appends streaming log entries visible on the dashboard."""
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(16), default="INFO")                       # INFO, WARN, ERROR
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ─── Bootstrap ───────────────────────────────────────────────────────────────
def init_db():
    """Create all tables and seed default system settings."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()

    # Seed defaults if not present
    defaults = {
        "max_posts_per_day": "10",
        "min_delay_minutes": "15",
        "safe_mode": "true",
    }
    for key, val in defaults.items():
        if not session.query(SystemSettings).filter(SystemSettings.key == key).first():
            session.add(SystemSettings(key=key, value=val, description=""))
    session.commit()
    session.close()
    print("[PostPilot] Database initialized at", DB_PATH)
