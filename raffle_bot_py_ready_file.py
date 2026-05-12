# Полный готовый файл raffle bot
# Сохрани как bot.py

import asyncio
import logging
import os
import random
import sqlite3

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from aiocryptopay import AioCryptoPay, Networks

# =========================
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
TICKET_PRICE = float(os.getenv("TICKET_PRICE", "0.15"))

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)

# =========================
# BOT
# =========================
bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
crypto = AioCryptoPay(token=CRYPTOBOT_TOKEN, network=Networks.MAIN_NET)

# =========================
# DATABASE
# =========================
conn = sqlite3.connect("raffle.db")
cur = conn.cursor()

cur.execute('''
CREATE TABLE IF NOT EXISTS raffles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    prize TEXT,
    active INTEGER DEFAULT 1
)
''')

cur.execute('''
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raffle_id INTEGER,
    user_id INTEGER,
    username TEXT,
    amount INTEGER
)
''')

conn.commit()

# =========================
# STATES
# =========================
class CreateRaffle(StatesGroup):
    waiting_title = State()
    waiting_prize = State()

class BuyTickets(StatesGroup):
    waiting_amount = State()

class AdminPanel(StatesGroup):
    waiting_finish_id = State()

# =========================
# ADMIN PANEL
# =========================
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать розыгрыш", callback_data="create_raffle")],
            [InlineKeyboardButton(text="🏁 Завершить розыгрыш", callback_data="finish_raffle")]
        ]
    )

    await message.answer("⚙️ Админ панель", reply_markup=kb)

# =========================
# START
# =========================
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    args = message.text.split()

    if len(args) >= 2:
        data = args[1]

        if data.startswith("buy_"):
            raffle_id = int(data.split("_")[1])

            cur.execute(
                "SELECT title, prize FROM raffles WHERE id=? AND active=1",
                (raffle_id,)
            )

            raffle = cur.fetchone()

            if not raffle:
                await message.answer("❌ Розыгрыш не найден")
                return

            await state.update_data(raffle_id=raffle_id)

            await message.answer(
                f"<tg-emoji emoji-id='5436296829903870886'></tg-emoji> Розыгрыш: {raffle[0]}\n"
                f"<tg-emoji emoji-id='5330312778093704176'></tg-emoji> Приз: {raffle[1]}\n\n"
                f"Введите сколько билетов хотите купить:"
            )

            await state.set_state(BuyTickets.waiting_amount)
            return

    await message.answer("🎟 Добро пожаловать в розыгрыш")

# =========================
# CREATE RAFFLE
# =========================
@dp.callback_query(F.data == "create_raffle")
async def create_raffle_button(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer("Введите название розыгрыша:")
    await state.set_state(CreateRaffle.waiting_title)

@dp.message(CreateRaffle.waiting_title)
async def raffle_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите приз:")
    await state.set_state(CreateRaffle.waiting_prize)

@dp.message(CreateRaffle.waiting_prize)
async def raffle_prize(message: Message, state: FSMContext):
    data = await state.get_data()

    title = data["title"]
    prize = message.text

    cur.execute(
        "INSERT INTO raffles (title, prize, active) VALUES (?, ?, 1)",
        (title, prize)
    )

    conn.commit()

    raffle_id = cur.lastrowid

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎟 Купить билет",
                    url=f"https://t.me/{(await bot.get_me()).username}?start=buy_{raffle_id}"
                )
            ]
        ]
    )

    text = (
        f"<tg-emoji emoji-id='546341228988335340'></tg-emoji> <b>НОВЫЙ РОЗЫГРЫШ</b>\n\n"
        f"<tg-emoji emoji-id='5197434882321567830'></tg-emoji> {title}\n"
        f"<tg-emoji emoji-id='5330312778093704176'></tg-emoji> Приз: <b>{prize}</b>\n"
        f"<tg-emoji emoji-id='5325547803936572038'></tg-emoji> Цена билета: <b>{TICKET_PRICE}$</b>"
    )

    await bot.send_message(CHANNEL_ID, text, reply_markup=kb)

    await message.answer("✅ Розыгрыш создан")
    await state.clear()

# =========================
# BUY TICKETS
# =========================
@dp.message(BuyTickets.waiting_amount)
async def buy_tickets(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите число")
        return

    amount = int(message.text)

    if amount <= 0:
        await message.answer("Минимум 1 билет")
        return

    data = await state.get_data()
    raffle_id = data["raffle_id"]

    total = round(amount * TICKET_PRICE, 2)

    invoice = await crypto.create_invoice(
        asset="USDT",
        amount=total,
        description=f"Покупка {amount} билетов"
    )

    await state.update_data(
        amount=amount,
        invoice_id=invoice.invoice_id
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=invoice.bot_invoice_url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data="check_pay")]
        ]
    )

    await message.answer(
        f"<tg-emoji emoji-id='5197434882321567830'></tg-emoji> К оплате: <b>{total}$</b>\n"
        f"<tg-emoji emoji-id='5325547803936572038'></tg-emoji> Билетов: <b>{amount}</b>",
        reply_markup=kb
    )

# =========================
# CHECK PAYMENT
# =========================
@dp.callback_query(F.data == "check_pay")
async def check_payment(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    invoice_id = data.get("invoice_id")
    amount = data.get("amount")
    raffle_id = data.get("raffle_id")

    invoices = await crypto.get_invoices(invoice_ids=invoice_id)

    if not invoices.items:
        await callback.answer("Инвойс не найден", show_alert=True)
        return

    invoice = invoices.items[0]

    if invoice.status != "paid":
        await callback.answer("❌ Оплата не найдена", show_alert=True)
        return

    username = callback.from_user.username

    if username:
        username = f"@{username}"
    else:
        username = callback.from_user.full_name

    cur.execute(
        "INSERT INTO tickets (raffle_id, user_id, username, amount) VALUES (?, ?, ?, ?)",
        (raffle_id, callback.from_user.id, username, amount)
    )

    conn.commit()

    cur.execute(
        "SELECT title FROM raffles WHERE id=?",
        (raffle_id,)
    )

    raffle_title = cur.fetchone()[0]

    await bot.send_message(
        CHANNEL_ID,
        f"<tg-emoji emoji-id='5325547803936572038'></tg-emoji> Новый участник!\n\n"
        f"<tg-emoji emoji-id='5436296829903870886'></tg-emoji> {username}\n"
        f"<tg-emoji emoji-id='5325547803936572038'></tg-emoji> Купил билетов: <b>{amount}</b>\n"
        f"🏆 Розыгрыш: {raffle_title}"
    )

    await callback.message.edit_text("✅ Оплата прошла успешно")
    await state.clear()

# =========================
# FINISH RAFFLE
# =========================
@dp.callback_query(F.data == "finish_raffle")
async def finish_raffle_button(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    cur.execute("SELECT id, title FROM raffles WHERE active=1")
    raffles = cur.fetchall()

    if not raffles:
        await callback.message.answer("❌ Нет активных розыгрышей")
        return

    text = "🏁 Активные розыгрыши:\n\n"

    for raffle in raffles:
        text += f"ID: {raffle[0]} — {raffle[1]}\n"

    text += "\nВведите ID розыгрыша:"

    await callback.message.answer(text)
    await state.set_state(AdminPanel.waiting_finish_id)

@dp.message(AdminPanel.waiting_finish_id)
async def process_finish_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите ID числом")
        return

    raffle_id = int(message.text)

    cur.execute(
        "SELECT title, prize FROM raffles WHERE id=? AND active=1",
        (raffle_id,)
    )

    raffle = cur.fetchone()

    if not raffle:
        await message.answer("❌ Розыгрыш не найден")
        return

    cur.execute(
        "SELECT username, amount FROM tickets WHERE raffle_id=?",
        (raffle_id,)
    )

    rows = cur.fetchall()

    if not rows:
        await message.answer("Нет участников")
        return

    pool = []

    for username, amount in rows:
        for _ in range(amount):
            pool.append(username)

    winner = random.choice(pool)

    cur.execute(
        "UPDATE raffles SET active=0 WHERE id=?",
        (raffle_id,)
    )

    conn.commit()

    await bot.send_message(
        CHANNEL_ID,
        f"<tg-emoji emoji-id='5891211893221100564'></tg-emoji> <b>РОЗЫГРЫШ ЗАВЕРШЕН</b>\n\n"
        f"<tg-emoji emoji-id='5330312778093704176'></tg-emoji> Приз: <b>{raffle[1]}</b>\n"
        f"<tg-emoji emoji-id='5891211893221100564'></tg-emoji> Победитель: {winner}\n\n"
        f"🎉 Поздравляем!"
    )

    await message.answer("✅ Победитель выбран")
    await state.clear()

# =========================
# START BOT
# =========================
async def main():
    me = await bot.get_me()
    print(f"Bot started: @{me.username}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
