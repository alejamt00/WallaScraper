import os, time
from sqlalchemy import create_engine, Column, Integer, Text, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)  # telegram user id
    username = Column(Text)
    active = Column(Boolean, default=True)
    created_at = Column(Integer, default=lambda: int(time.time()))
    searches = relationship("SavedSearch", back_populates="user")


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    query = Column(Text, nullable=False)
    active = Column(Boolean, default=True)   # 👈 sirve para toggle ON/OFF
    created_at = Column(Integer, default=lambda: int(time.time()))
    user = relationship("User", back_populates="searches")


def init_db():
    Base.metadata.create_all(engine)


def ensure_user(user_id: int, username: str):
    with SessionLocal() as s:
        u = s.get(User, user_id)
        if not u:
            u = User(id=user_id, username=username, active=True)
            s.add(u)
            s.commit()
        return u
