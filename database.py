from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    select,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

engine = create_async_engine("sqlite+aiosqlite:///shop.db", echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SessionItem(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer)
    data: Mapped[str] = mapped_column(Text)
    is_sold: Mapped[bool] = mapped_column(Boolean, default=False)
    sold_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    product_id: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Topup(Base):
    __tablename__ = "topups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String)
    trx_id: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user(user_id: int, username: str | None = None) -> User:
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if not u:
            u = User(id=user_id, username=username)
            s.add(u)
            await s.commit()
            await s.refresh(u)
        return u


async def add_balance(user_id: int, amount: float):
    async with SessionLocal() as s:
        async with s.begin():
            u = await s.get(User, user_id)
            if not u:
                u = User(id=user_id, balance=amount)
                s.add(u)
            else:
                u.balance += amount


async def buy_product(user_id: int, product_id: int):
    """Return (ok: bool, message_or_session: str)"""
    async with SessionLocal() as s:
        async with s.begin():
            user = (
                await s.execute(
                    select(User).where(User.id == user_id).with_for_update()
                )
            ).scalar_one_or_none()
            if not user:
                return False, "❌ User পাওয়া যায়নি"

            product = (
                await s.execute(
                    select(Product).where(
                        Product.id == product_id, Product.is_active == True
                    )
                )
            ).scalar_one_or_none()
            if not product:
                return False, "❌ Product নেই"

            if user.balance < product.price:
                return (
                    False,
                    f"❌ Balance কম। দরকার {product.price}৳, আছে {user.balance:.2f}৳",
                )

            sess = (
                await s.execute(
                    select(SessionItem)
                    .where(
                        SessionItem.product_id == product_id,
                        SessionItem.is_sold == False,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not sess:
                return False, "❌ Stock শেষ"

            user.balance -= product.price
            sess.is_sold = True
            sess.sold_to = user_id
            sess.sold_at = datetime.utcnow()
            s.add(
                Order(
                    user_id=user_id,
                    product_id=product_id,
                    session_id=sess.id,
                    price=product.price,
                )
            )
            return True, sess.data
