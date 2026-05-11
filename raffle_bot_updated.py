import asyncio
import random
import aiohttp
import aiosqlite
import os

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

# =============================
# ENV
# =============================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# =============================
# SETTINGS
# =============================

DB_NAME = "raffle.db"
TICKET_PRICE = 0.1

# =============================
# BOT
# =============================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# =============================
# MEMORY
# =============================

waiting_ticket_amount = {}

# =============================
# DATABASE
# =============================

async def init_db():

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            tickets INTEGER
        )
        """)

        await db.commit()

# =============================
# CRYPTOBOT API
# =============================

async def create_invoice(amount):

    url = "https://pay.crypt.bot/api/createInvoice"

    headers = {
        "Crypto-Pay-API-Token": CRYPTO_TOKEN
    }

    payload = {
        "asset": "USDT",
        "amount": str(amount)
    }

    async with aiohttp.ClientSession() as session:

        async with session.post(
            url,
            json=payload,
            headers=headers
        ) as response:

            data = await response.json()

            return data["result"]

async def check_invoice(invoice_id):

    url = f"https://pay.crypt.bot/api/getInvoices?invoice_ids={invoice_id}"

    headers = {
        "Crypto-Pay-API-Token": CRYPTO_TOKEN
    }

    async with aiohttp.ClientSession() as session:

        async with session.get(
            url,
            headers=headers
        ) as response:

            data = await response.json()

            return data["result"]["items"][0]["status"]

# =============================
# START
# =============================

@dp.message(Command("start"))
async def start(message: Message):

    args = message.text.split()

    if len(args) > 1 and args[1] == "buy":

        waiting_ticket_amount[message.from_user.id] = True

        buttons = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="1 билет 🎟",
                        callback_data="ticket_1"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="5 билетов 🎟",
                        callback_data="ticket_5"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="10 билетов 🎟",
                        callback_data="ticket_10"
                    )
                ]
            ]
        )

        await message.answer(
            "🎟 Выберите количество билетов",
            reply_markup=buttons
        )

        return

    await message.answer(
        "🎟 Добро пожаловать в бот розыгрышей!"
    )

# =============================
# CREATE RAFFLE
# =============================

@dp.message(Command("create"))
async def create_raffle(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:

        await message.answer(
            "Использование:\n/create 500$"
        )

        return

    prize = args[1]

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("DELETE FROM tickets")

        await db.commit()

    me = await bot.get_me()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Купить билеты 🎟️",
                    url=f"https://t.me/{me.username}?start=buy"
                )
            ]
        ]
    )

    await bot.send_message(
        CHANNEL_ID,
        f"""
🎉 РОЗЫГРЫШ НА {prize}

💰 Цена билета: 0.1$
🎲 Победитель выбирается случайно
""",
        reply_markup=keyboard
    )

    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Завершить розыгрыш",
                    callback_data="finish_raffle"
                )
            ]
        ]
    )

    await message.answer(
        "✅ Розыгрыш создан",
        reply_markup=admin_keyboard
    )

# =============================
# TICKET BUTTONS
# =============================

@dp.callback_query(F.data.startswith("ticket_"))
async def ticket_buy(callback: CallbackQuery):

    tickets = int(callback.data.split("_")[1])

    total = round(tickets * TICKET_PRICE, 2)

    invoice = await create_invoice(total)

    invoice_id = invoice["invoice_id"]
    pay_url = invoice["pay_url"]

    buttons = [
        [
            InlineKeyboardButton(
                text="💳 Оплатить",
                url=pay_url
            )
        ]
    ]

    if callback.from_user.id == ADMIN_ID:

        buttons.append([
            InlineKeyboardButton(
                text="⚡ Засчитать без оплаты",
                callback_data=f"fakepay_{tickets}"
            )
        ])

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=buttons
    )

    await callback.message.answer(
        f"""
🎟 Билетов: {tickets}
💰 К оплате: {total}$

👇 Нажмите кнопку ниже
""",
        reply_markup=keyboard
    )

    await callback.answer()

    if callback.from_user.id == ADMIN_ID:
        return

    paid = False

    for _ in range(120):

        status = await check_invoice(invoice_id)

        if status == "paid":

            paid = True
            break

        await asyncio.sleep(5)

    if not paid:

        await callback.message.answer(
            "❌ Время оплаты истекло"
        )

        return

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute(
            """
            INSERT INTO tickets
            (user_id, username, tickets)
            VALUES (?, ?, ?)
            """,
            (
                callback.from_user.id,
                callback.from_user.username,
                tickets
            )
        )

        await db.commit()

    await callback.message.answer(
        "✅ Оплата прошла успешно!"
    )

    await bot.send_message(
        CHANNEL_ID,
        f"""
🎟 Новая покупка!

👤 @{callback.from_user.username}
🎫 Куплено билетов: {tickets}
"""
    )

    await bot.send_message(
        ADMIN_ID,
        f"""
💰 Новая оплата

👤 @{callback.from_user.username}
🎟 Билетов: {tickets}
"""
    )

# =============================
# ADMIN FAKEPAY
# =============================

@dp.callback_query(F.data.startswith("fakepay_"))
async def fakepay(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    tickets = int(callback.data.split("_")[1])

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute(
            """
            INSERT INTO tickets
            (user_id, username, tickets)
            VALUES (?, ?, ?)
            """,
            (
                callback.from_user.id,
                callback.from_user.username,
                tickets
            )
        )

        await db.commit()

    await callback.message.answer(
        "✅ Билеты засчитаны"
    )

    await callback.answer()

# =============================
# FINISH RAFFLE
# =============================

@dp.callback_query(F.data == "finish_raffle")
async def finish_raffle(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    users = []

    async with aiosqlite.connect(DB_NAME) as db:

        async with db.execute(
            "SELECT username, tickets FROM tickets"
        ) as cursor:

            rows = await cursor.fetchall()

    if not rows:

        await callback.message.answer(
            "❌ Нет участников"
        )

        return

    for username, tickets in rows:

        for _ in range(tickets):

            users.append(username)

    winner = random.choice(users)

    await bot.send_message(
        CHANNEL_ID,
        f"""
🎉 РОЗЫГРЫШ ЗАВЕРШЕН

🏆 Победитель:
@{winner}

🎲 Победитель выбран случайно!
"""
    )

    await callback.message.answer(
        "✅ Победитель выбран"
    )

    await callback.answer()

# =============================
# MAIN
# =============================

async def main():

    await init_db()

    print("BOT STARTED")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
