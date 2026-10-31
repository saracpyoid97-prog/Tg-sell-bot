import asyncio

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import select

import config
from database import (
    Order,
    Product,
    SessionItem,
    SessionLocal,
    Topup,
    User,
    add_balance,
    buy_product,
    get_or_create_user,
    init_db,
)

bot = Bot(config.BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ===================== KEYBOARDS =====================

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Shop"), KeyboardButton(text="💰 Add Balance")],
            [KeyboardButton(text="👤 My Account"), KeyboardButton(text="📞 Support")],
        ],
        resize_keyboard=True,
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Shop"), KeyboardButton(text="💰 Add Balance")],
            [KeyboardButton(text="👤 My Account"), KeyboardButton(text="📞 Support")],
            [KeyboardButton(text="🔧 Admin Panel")],
        ],
        resize_keyboard=True,
    )


def menu_for(user_id: int):
    return admin_menu() if user_id in config.ADMIN_IDS else main_menu()


# ===================== STATES =====================

class TopupStates(StatesGroup):
    method = State()
    amount = State()
    trx = State()


class AdminStates(StatesGroup):
    addstock_data = State()
    addproduct_name = State()
    addproduct_price = State()


# ===================== HELPERS =====================

def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


async def notify_admins_topup(topup_id, user_id, username, amount, method, trx):
    text = (
        f"💰 <b>New Topup Request</b>\n\n"
        f"👤 User: {username or user_id}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"💳 Method: {method}\n"
        f"💵 Amount: {amount}৳\n"
        f"🧾 TrxID: <code>{trx}</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve", callback_data=f"topup_ok:{topup_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Reject", callback_data=f"topup_no:{topup_id}"
                ),
            ]
        ]
    )
    for aid in config.ADMIN_IDS:
        try:
            await bot.send_message(aid, text, reply_markup=kb)
        except Exception:
            pass


# ===================== /start =====================

@router.message(Command("start"))
async def cmd_start(m: Message):
    await get_or_create_user(m.from_user.id, m.from_user.username)
    await m.answer(
        f"👋 স্বাগতম <b>{m.from_user.first_name}</b>!\n\n"
        f"🎯 এই bot থেকে আপনি Telegram account session কিনতে পারবেন।\n\n"
        f"👉 প্রথমে <b>💰 Add Balance</b> থেকে balance যোগ করুন।",
        reply_markup=menu_for(m.from_user.id),
    )


# ===================== SHOP =====================

@router.message(F.text == "🛒 Shop")
async def shop(m: Message):
    async with SessionLocal() as s:
        products = (
            (await s.execute(select(Product).where(Product.is_active == True)))
            .scalars()
            .all()
        )

    if not products:
        return await m.answer("❌ এখনো কোনো product নেই।")

    buttons = []
    for p in products:
        async with SessionLocal() as s:
            stock = (
                (
                    await s.execute(
                        select(SessionItem).where(
                            SessionItem.product_id == p.id,
                            SessionItem.is_sold == False,
                        )
                    )
                )
                .scalars()
                .all()
            )
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{p.name} — {p.price}৳ ({len(stock)} in stock)",
                    callback_data=f"prod:{p.id}",
                )
            ]
        )
    await m.answer(
        "🛒 <b>Products</b>\nএকটা বেছে নিন:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("prod:"))
async def show_product(cq: CallbackQuery):
    pid = int(cq.data.split(":")[1])
    async with SessionLocal() as s:
        p = await s.get(Product, pid)
        stock = (
            (
                await s.execute(
                    select(SessionItem).where(
                        SessionItem.product_id == pid,
                        SessionItem.is_sold == False,
                    )
                )
            )
            .scalars()
            .all()
        )
    if not p:
        return await cq.answer("Product নেই", show_alert=True)

    text = (
        f"📦 <b>{p.name}</b>\n\n"
        f"📝 {p.description or 'কোনো description নেই'}\n\n"
        f"💵 Price: <b>{p.price}৳</b>\n"
        f"📊 Stock: {len(stock)}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💳 Buy for {p.price}৳", callback_data=f"buy:{pid}"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="shop_back")],
        ]
    )
    await cq.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "shop_back")
async def shop_back(cq: CallbackQuery):
    async with SessionLocal() as s:
        products = (
            (await s.execute(select(Product).where(Product.is_active == True)))
            .scalars()
            .all()
        )
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{p.name} — {p.price}৳", callback_data=f"prod:{p.id}"
            )
        ]
        for p in products
    ]
    await cq.message.edit_text(
        "🛒 <b>Products</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("buy:"))
async def do_buy(cq: CallbackQuery):
    pid = int(cq.data.split(":")[1])
    ok, result = await buy_product(cq.from_user.id, pid)
    if not ok:
        return await cq.answer(result, show_alert=True)

    await cq.message.edit_text(
        "✅ <b>Purchase successful!</b>\n\n"
        "নিচের session string আপনার। এটা save করে রাখুন।"
    )
    await bot.send_message(
        cq.from_user.id,
        f"🔑 <b>Your Session</b>\n\n<code>{result}</code>\n\n"
        f"⚠️ এটা কারো সাথে শেয়ার করবেন না।",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Delete this message", callback_data="del_self")]
            ]
        ),
    )


@router.callback_query(F.data == "del_self")
async def del_self(cq: CallbackQuery):
    try:
        await cq.message.delete()
    except Exception:
        pass


# ===================== ADD BALANCE (TOPUP) =====================

@router.message(F.text == "💰 Add Balance")
async def topup_start(m: Message, state: FSMContext):
    buttons = [
        [InlineKeyboardButton(text=method, callback_data=f"pm:{method}")]
        for method in config.PAYMENT_METHODS
    ]
    await m.answer(
        "💳 কোন মাধ্যমে payment করবেন?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(TopupStates.method)


@router.callback_query(TopupStates.method, F.data.startswith("pm:"))
async def topup_method(cq: CallbackQuery, state: FSMContext):
    method = cq.data.split(":", 1)[1]
    await state.update_data(method=method)
    await cq.message.edit_text(
        f"💳 Method: <b>{method}</b>\n"
        f"📲 Send Money to: <code>{config.PAYMENT_NUMBER}</code>\n\n"
        f"এখন কত টাকা পাঠিয়েছেন লিখুন (শুধু সংখ্যা):"
    )
    await state.set_state(TopupStates.amount)


@router.message(TopupStates.amount)
async def topup_amount(m: Message, state: FSMContext):
    try:
        amt = float(m.text.strip())
        if amt <= 0:
            raise ValueError
    except ValueError:
        return await m.answer("❌ সঠিক amount লিখুন (যেমন: 100)")
    await state.update_data(amount=amt)
    await m.answer("🧾 এখন <b>Transaction ID</b> পাঠান:")
    await state.set_state(TopupStates.trx)


@router.message(TopupStates.trx)
async def topup_trx(m: Message, state: FSMContext):
    data = await state.get_data()
    trx = m.text.strip()
    async with SessionLocal() as s:
        existing = (
            await s.execute(select(Topup).where(Topup.trx_id == trx))
        ).scalar_one_or_none()
        if existing:
            await state.clear()
            return await m.answer("❌ এই TrxID আগেই ব্যবহার হয়েছে।")
        t = Topup(
            user_id=m.from_user.id,
            amount=data["amount"],
            method=data["method"],
            trx_id=trx,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        await notify_admins_topup(
            t.id,
            m.from_user.id,
            m.from_user.username,
            t.amount,
            t.method,
            t.trx_id,
        )
    await state.clear()
    await m.answer(
        "✅ Request পাঠানো হয়েছে। Admin approve করলে balance যোগ হবে।",
        reply_markup=menu_for(m.from_user.id),
    )


# ===================== MY ACCOUNT =====================

@router.message(F.text == "👤 My Account")
async def my_account(m: Message):
    user = await get_or_create_user(m.from_user.id, m.from_user.username)
    async with SessionLocal() as s:
        orders = (
            (await s.execute(select(Order).where(Order.user_id == m.from_user.id)))
            .scalars()
            .all()
        )
    await m.answer(
        f"👤 <b>My Account</b>\n\n"
        f"🆔 ID: <code>{m.from_user.id}</code>\n"
        f"💰 Balance: <b>{user.balance:.2f}৳</b>\n"
        f"📦 Total orders: {len(orders)}"
    )


# ===================== SUPPORT =====================

@router.message(F.text == "📞 Support")
async def support(m: Message):
    await m.answer(f"📞 Support: {config.SUPPORT_USERNAME}")


# ===================== ADMIN — PANEL =====================

@router.message(F.text == "🔧 Admin Panel")
async def admin_panel(m: Message):
    if not is_admin(m.from_user.id):
        return
    text = (
        "🔧 <b>Admin Commands</b>\n\n"
        "• <code>/addbal &lt;uid&gt; &lt;amount&gt;</code> — balance add\n"
        "• <code>/setprice &lt;pid&gt; &lt;price&gt;</code> — price set\n"
        "• <code>/products</code> — product list + stock\n"
        "• <code>/addproduct</code> — নতুন product\n"
        "• <code>/addstock &lt;pid&gt;</code> — stock upload\n"
        "• <code>/pending</code> — pending topups\n"
        "• <code>/broadcast &lt;msg&gt;</code> — সব user-কে message\n"
    )
    await m.answer(text)


# ===================== ADMIN — BALANCE =====================

@router.message(Command("addbal"))
async def cmd_addbal(m: Message):
    if not is_admin(m.from_user.id):
        return
    try:
        _, uid, amt = m.text.split()
        uid, amt = int(uid), float(amt)
    except Exception:
        return await m.answer("ব্যবহার: /addbal &lt;user_id&gt; &lt;amount&gt;")
    await add_balance(uid, amt)
    await m.answer(f"✅ {uid} কে {amt}৳ যোগ হয়েছে")
    try:
        await bot.send_message(uid, f"💰 Balance added: <b>{amt}৳</b>")
    except Exception:
        pass


# ===================== ADMIN — PRODUCTS =====================

@router.message(Command("products"))
async def cmd_products(m: Message):
    if not is_admin(m.from_user.id):
        return
    async with SessionLocal() as s:
        products = (await s.execute(select(Product))).scalars().all()
    if not products:
        return await m.answer("কোনো product নেই। /addproduct দিয়ে বানান।")
    lines = ["📦 <b>Products</b>\n"]
    for p in products:
        async with SessionLocal() as s:
            stock = (
                (
                    await s.execute(
                        select(SessionItem).where(
                            SessionItem.product_id == p.id,
                            SessionItem.is_sold == False,
                        )
                    )
                )
                .scalars()
                .all()
            )
        lines.append(
            f"ID <code>{p.id}</code> — {p.name} — {p.price}৳ — Stock: {len(stock)}"
        )
    await m.answer("\n".join(lines))


@router.message(Command("setprice"))
async def cmd_setprice(m: Message):
    if not is_admin(m.from_user.id):
        return
    try:
        _, pid, price = m.text.split()
        pid, price = int(pid), float(price)
    except Exception:
        return await m.answer("ব্যবহার: /setprice &lt;product_id&gt; &lt;price&gt;")
    async with SessionLocal() as s:
        async with s.begin():
            p = await s.get(Product, pid)
            if not p:
                return await m.answer("❌ Product নেই")
            p.price = price
    await m.answer(f"✅ Product {pid} price → {price}৳")


# ===================== ADMIN — ADD PRODUCT =====================

@router.message(Command("addproduct"))
async def cmd_addproduct(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await m.answer("📝 Product-এর নাম লিখুন:")
    await state.set_state(AdminStates.addproduct_name)


@router.message(AdminStates.addproduct_name)
async def addproduct_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await m.answer("💵 Price লিখুন (৳):")
    await state.set_state(AdminStates.addproduct_price)


@router.message(AdminStates.addproduct_price)
async def addproduct_price(m: Message, state: FSMContext):
    try:
        price = float(m.text.strip())
    except ValueError:
        return await m.answer("❌ সঠিক price লিখুন")
    data = await state.get_data()
    async with SessionLocal() as s:
        p = Product(name=data["name"], price=price, description="")
        s.add(p)
        await s.commit()
        await s.refresh(p)
        pid = p.id
    await state.clear()
    await m.answer(
        f"✅ Product তৈরি হয়েছে। ID: <code>{pid}</code>\n"
        f"এখন <code>/addstock {pid}</code> দিয়ে stock দিন।"
    )


# ===================== ADMIN — ADD STOCK =====================

@router.message(Command("addstock"))
async def cmd_addstock(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    try:
        pid = int(m.text.split()[1])
    except Exception:
        return await m.answer("ব্যবহার: /addstock &lt;product_id&gt;")
    async with SessionLocal() as s:
        p = await s.get(Product, pid)
        if not p:
            return await m.answer("❌ Product নেই")
    await state.update_data(pid=pid)
    await m.answer("📥 এখন session string গুলো পাঠান — <b>প্রতি লাইনে একটা</b>।")
    await state.set_state(AdminStates.addstock_data)


@router.message(AdminStates.addstock_data)
async def addstock_data(m: Message, state: FSMContext):
    data = await state.get_data()
    pid = data["pid"]
    lines = [x.strip() for x in m.text.splitlines() if x.strip()]
    if not lines:
        return await m.answer("❌ খালি। আবার পাঠান।")
    async with SessionLocal() as s:
        for line in lines:
            s.add(SessionItem(product_id=pid, data=line))
        await s.commit()
    await state.clear()
    await m.answer(f"✅ {len(lines)} টা session যোগ হয়েছে product {pid} এ।")


# ===================== ADMIN — PENDING TOPUPS =====================

@router.message(Command("pending"))
async def cmd_pending(m: Message):
    if not is_admin(m.from_user.id):
        return
    async with SessionLocal() as s:
        pending = (
            (
                await s.execute(
                    select(Topup)
                    .where(Topup.status == "pending")
                    .order_by(Topup.id.desc())
                )
            )
            .scalars()
            .all()
        )
    if not pending:
        return await m.answer("✅ কোনো pending নেই")
    for t in pending:
        await notify_admins_topup(t.id, t.user_id, None, t.amount, t.method, t.trx_id)


# ===================== ADMIN — APPROVE / REJECT =====================

@router.callback_query(F.data.startswith("topup_ok:"))
async def approve_topup(cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        return await cq.answer("Access denied", show_alert=True)
    tid = int(cq.data.split(":")[1])
    async with SessionLocal() as s:
        async with s.begin():
            t = (
                await s.execute(
                    select(Topup).where(Topup.id == tid).with_for_update()
                )
            ).scalar_one_or_none()
            if not t or t.status != "pending":
                return await cq.answer("Already processed", show_alert=True)
            t.status = "approved"
            u = await s.get(User, t.user_id)
            if not u:
                u = User(id=t.user_id, balance=0)
                s.add(u)
            u.balance += t.amount
            user_id = t.user_id
            amount = t.amount
    await cq.message.edit_text(cq.message.text + "\n\n✅ APPROVED")
    await cq.answer("Approved")
    try:
        await bot.send_message(user_id, f"✅ {amount}৳ balance added!")
    except Exception:
        pass


@router.callback_query(F.data.startswith("topup_no:"))
async def reject_topup(cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        return await cq.answer("Access denied", show_alert=True)
    tid = int(cq.data.split(":")[1])
    async with SessionLocal() as s:
        async with s.begin():
            t = (
                await s.execute(
                    select(Topup).where(Topup.id == tid).with_for_update()
                )
            ).scalar_one_or_none()
            if not t or t.status != "pending":
                return await cq.answer("Already processed", show_alert=True)
            t.status = "rejected"
            user_id = t.user_id
    await cq.message.edit_text(cq.message.text + "\n\n❌ REJECTED")
    await cq.answer("Rejected")
    try:
        await bot.send_message(user_id, "❌ আপনার topup request reject হয়েছে।")
    except Exception:
        pass


# ===================== ADMIN — BROADCAST =====================

@router.message(Command("broadcast"))
async def cmd_broadcast(m: Message):
    if not is_admin(m.from_user.id):
        return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("ব্যবহার: /broadcast &lt;message&gt;")
    msg = parts[1]
    async with SessionLocal() as s:
        users = (await s.execute(select(User))).scalars().all()
    ok = 0
    for u in users:
        try:
            await bot.send_message(u.id, msg)
            ok += 1
        except Exception:
            pass
    await m.answer(f"✅ {ok}/{len(users)} user-কে পাঠানো হয়েছে")


# ===================== MAIN =====================

async def main():
    await init_db()
    print("✅ Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
