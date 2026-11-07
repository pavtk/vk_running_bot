from datetime import datetime, date, timezone
from decimal import Decimal
import enum

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
    Text,
    UniqueConstraint,
    Enum
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)


class EventType(str, enum.Enum):
    RUNS_PER_WEEK = 'runs_per_week'
    DISTANCE = 'distance'


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
            "age IS NULL OR (age BETWEEN 0 AND 150)",
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
        back_populates='category',
        cascade="all, delete-orphan",
        passive_deletes=True,
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
        CheckConstraint(
            "(event_type = 'runs_per_week' AND runs_per_week IS NOT NULL "
            " AND runs_per_week > 0) OR "
            "(event_type = 'distance' AND runs_per_week IS NULL)",
            name="check_event_type_runs_per_week",
        ),
    )

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    registration_open: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    registrations: Mapped[list['Registration']] = relationship(
        back_populates='event', cascade='all, delete'
    )
    event_categories: Mapped[list["EventCategory"]] = relationship(
        back_populates='event', cascade='all, delete-orphan'
    )
    event_type: Mapped[EventType] = mapped_column(
        Enum(
            EventType,
            name='event_type_enum',
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        )
    )
    runs_per_week: Mapped[int | None] = mapped_column(Integer, default=None)


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
        CheckConstraint(
            'distance_km > 0',
            name='check_event_category_distance_positive'
        )
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
        Numeric(6, 2),
        nullable=False,
        comment=(
            'Для event_type=runs_per_week — минимальная дистанция категории; '
            'для event_type=distance — целевая дистанция категории.'
        ),
    )

    registrations: Mapped[list["Registration"]] = relationship(
        back_populates='event_category', cascade='all, delete'
    )
    event: Mapped['Event'] = relationship(back_populates='event_categories')
    category: Mapped['Category'] = relationship(
        back_populates='event_categories'
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
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_category_id: Mapped[int] = mapped_column(Integer, index=True)
    user: Mapped["User"] = relationship(back_populates="registrations")
    event: Mapped["Event"] = relationship(back_populates="registrations")
    event_category: Mapped["EventCategory"] = relationship(
        back_populates="registrations"
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="registration",
        cascade="all, delete-orphan",
    )


class Report(Base):
    __table_args__ = (
        UniqueConstraint(
            "peer_id", "conversation_message_id",
            name="uq_report_vk_message",
        ),
        CheckConstraint(
            'distance_km > 0',
            name='check_event_category_distance_positive'
        )
    )
    registration_id: Mapped[int] = mapped_column(
        ForeignKey('registrations.id', ondelete='CASCADE'),
        index=True,
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    distance_km: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    peer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_message_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False)
    registration: Mapped["Registration"] = relationship(
        back_populates="reports")
