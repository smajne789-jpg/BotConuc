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

waiting_custom_tickets = {}

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
# CRYPTOBOT
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

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎟 Ввести количество билетов",
                        callback_data="custom_ticket"
                    )
                ]
            ]
        )

        await message.answer(
            """
🎟 Покупка билетов

💰 Цена 1 билета = 0.1$

👇 Нажмите кнопку ниже
""",
            reply_markup=keyboard
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

🎟 Цена билета: 0.1$
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
# CUSTOM TICKETS BUTTON
# =============================

@dp.callback_query(F.data == "custom_ticket")
async def custom_ticket(callback: CallbackQuery):

    waiting_custom_tickets[callback.from_user.id] = True

    await callback.message.answer(
        "🎟 Введите количество билетов:"
    )

    await callback.answer()

# =============================
# USER ENTER TICKETS
# =============================

@dp.message()
async def process_custom_tickets(message: Message):

    user_id = message.from_user.id

    if user_id not in waiting_custom_tickets:
        return

    if not message.text.isdigit():

        await message.answer(
            "❌ Введите число"
        )

        return

    tickets = int(message.text)

    if tickets <= 0:

        await message.answer(
            "❌ Количество должно быть больше 0"
        )

        return

    waiting_custom_tickets.pop(user_id)

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

    if user_id == ADMIN_ID:

        buttons.append([
            InlineKeyboardButton(
                text="⚡ Засчитать без оплаты",
                callback_data=f"fakepay_{tickets}"
            )
        ])

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=buttons
    )

    await message.answer(
        f"""
🎟 Билетов: {tickets}
💰 К оплате: {total}$

👇 Нажмите кнопку ниже
""",
        reply_markup=keyboard
    )

    if user_id == ADMIN_ID:
        return

    paid = False

    for _ in range(120):

        status = await check_invoice(invoice_id)

        if status == "paid":

            paid = True
            break

        await asyncio.sleep(5)

    if not paid:

        await message.answer(
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
                message.from_user.id,
                message.from_user.username,
                tickets
            )
        )

        await db.commit()

        async with db.execute(
            "SELECT COUNT(*) FROM tickets"
        ) as cursor:

            result = await cursor.fetchone()

            player_number = result[0]

    await message.answer(
        "✅ Оплата прошла успешно!"
    )

    await bot.send_message(
        CHANNEL_ID,
        f"""
🎟 Новая покупка билетов

👤 Игрок #{player_number}
🎫 Купил билетов: {tickets}
"""
    )

    await bot.send_message(
        ADMIN_ID,
        f"""
💰 Новая оплата

👤 Игрок #{player_number}
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
            "SELECT id, tickets FROM tickets"
        ) as cursor:

            rows = await cursor.fetchall()

    if not rows:

        await callback.message.answer(
            "❌ Нет участников"
        )

        return

    for row in rows:

        player_id = row[0]
        tickets = row[1]

        for _ in range(tickets):

            users.append(player_id)

    winner = random.choice(users)

    await bot.send_message(
        CHANNEL_ID,
        f"""
🎉 РОЗЫГРЫШ ЗАВЕРШЕН

🏆 Победитель:
Игрок #{winner}

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
