"""SQLAlchemy 2.0 declarative Base."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 LLMOps ORM 모델의 부모."""
    pass
