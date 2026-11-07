from datetime import datetime, date, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):

    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower() + 's'

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class User(Base):
    """Данные пользователя VK."""

    __table_args__ = (
        CheckConstraint(
            "age IS NULL OR (age >= 0 AND age <= 150)",
            name="check_user_age",
        ),
    )

    vk_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, default=None)
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    registrations: Mapped[list["Registration"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Category(Base):
    __tablename__ = "categories"

    title: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)

    event_categories: Mapped[list["EventCategory"]] = relationship(
        back_populates="category"
    )


class Event(Base):
    __table_args__ = (
        CheckConstraint(
            "ends_on > starts_on",
            name="check_events_period",
        ),
        UniqueConstraint(
            "title", "starts_on",
            name="unique_event_title_date",
        ),
    )

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    registration_open: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    registrations: Mapped[list["Registration"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    event_categories: Mapped[list["EventCategory"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventCategory(Base):
    __tablename__ = "event_categories"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "category_id",
            name="unique_event_category",
        ),
        # нужно для составного FK из Registration:
        UniqueConstraint(
            "id", "event_id",
            name="unique_event_category_event",
        ),
    )

    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    distance_km: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False
    )

    registrations: Mapped[list["Registration"]] = relationship(
        back_populates="event_category", cascade="all, delete-orphan"
    )
    event: Mapped["Event"] = relationship(back_populates="event_categories")
    category: Mapped["Category"] = relationship(
        back_populates="event_categories"
    )


class Registration(Base):
    __table_args__ = (
        UniqueConstraint(
            "user_id", "event_id",
            name="unique_user_event",
        ),
        # гарантирует, что event_category принадлежит тому же event:
        ForeignKeyConstraint(
            ["event_category_id", "event_id"],
            ["event_categories.id", "event_categories.event_id"],
            ondelete="CASCADE",
            name="fk_registration_event_category",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # event_id задаётся через составной FK выше
    event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_category_id: Mapped[int] = mapped_column(Integer, index=True)

    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="registrations")
    event: Mapped["Event"] = relationship(back_populates="registrations")
    event_category: Mapped["EventCategory"] = relationship(
        back_populates="registrations"
    )