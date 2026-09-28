from datetime import date
from sqlalchemy import (
    Column, Integer, String, Boolean,
    Date, DateTime, ForeignKey, UniqueConstraint, func
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_code = Column(String(20), unique=True, nullable=False, index=True)
    address = Column(String(255), nullable=False)
    timezone = Column(String(50), default="Asia/Yekaterinburg")
    created_at = Column(DateTime, server_default=func.now())

    shifts = relationship("Shift", back_populates="store")
    reports = relationship("Report", back_populates="store")
    users_last = relationship("User", back_populates="last_store",
                              foreign_keys="User.last_store_id")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    max_user_id = Column(String(50), unique=True, nullable=False, index=True)
    role = Column(String(20), default="employee", nullable=False)
    first_name = Column(String(100), nullable=True)
    username = Column(String(100), nullable=True)
    last_store_id = Column(Integer, ForeignKey("stores.id"), nullable=True)
    notify_before_close = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    last_store = relationship("Store", back_populates="users_last",
                              foreign_keys=[last_store_id])
    shifts = relationship("Shift", back_populates="user")
    reports = relationship("Report", back_populates="user")


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    ended_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_auto_closed = Column(Boolean, default=False)
    pending_closing = Column(Boolean, default=False)
    last_message_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="shifts")
    store = relationship("Store", back_populates="shifts")
    reports = relationship("Report", back_populates="shift")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("store_id", "user_id", "report_date", "slot_time",
                         name="uq_report_per_slot_user"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=True, index=True)

    report_date = Column(Date, default=date.today, nullable=False, index=True)
    slot_time = Column(String(10), nullable=False)
    is_closing = Column(Boolean, default=False)

    revenue = Column(Integer, default=0)
    sim_count = Column(Integer, default=0)
    gift_sim_count = Column(Integer, default=0)
    rev = Column(Integer, default=0)
    zc = Column(Integer, default=0)
    subscription = Column(Integer, default=0)
    mnp_requests = Column(Integer, default=0)
    combo_x2 = Column(Integer, default=0)
    accessories_sum = Column(Integer, default=0)
    smartphones_buttons_sum = Column(Integer, default=0)
    paid_services = Column(Integer, default=0)
    credit_requests = Column(Integer, default=0)

    created_at = Column(DateTime, server_default=func.now())

    store = relationship("Store", back_populates="reports")
    user = relationship("User", back_populates="reports")
    shift = relationship("Shift", back_populates="reports")