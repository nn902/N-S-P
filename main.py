import os
import sqlite3
import logging
import asyncio
import time
import aiohttp
from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery, TelegramObject
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "ТВОЙ_ТОКЕН_БОТА")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN", "ТВОЙ_ТОКЕН_CRYPTOBOT")
ADMIN_ID = 7727345054
ADMIN_CONTACT = "@nmproda"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
logging.basicConfig(level=logging.INFO)

# ==============================================================================
# 🗄 БАЗА ДАННЫХ
# ==============================================================================
DB_FILE = "shop.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0.0,
            referrer_id INTEGER,
            ref_count INTEGER DEFAULT 0,
            vip_status INTEGER DEFAULT 0,
            free_email_claimed INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            password TEXT,
            service TEXT,
            price INTEGER DEFAULT 20,
            status TEXT DEFAULT 'available',
            buyer_id INTEGER,
            bought_at INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service TEXT,
            desired_name TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            description TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

# ==============================================================================
# 🧠 СОСТОЯНИЯ (FSM)
# ==============================================================================
class AdminState(StatesGroup):
    waiting_emails = State()
    waiting_broadcast = State()

class CustomOrder(StatesGroup):
    service = State()
    name = State()

class BotOrder(StatesGroup):
    description = State()

# ==============================================================================
# 🕵️‍♂️ MIDDLEWARE ДЛЯ ЛОГИРОВАНИЯ
# ==============================================================================
class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if isinstance(event, Message) and event.from_user and event.from_user.id != ADMIN_ID:
            user = event.from_user
            username = f"@{user.username}" if user.username else "Нет юзернейма"
            
            log_text = (
                f"💬 <b>Новое сообщение от клиента!</b>\n"
                f"👤 Имя: {user.first_name}\n"
                f"🔗 Юзернейм: {username}\n"
                f"🆔 ID: <code>{user.id}</code>\n"
            )
            
            if event.text:
                log_text += f"\n📝 <b>Текст:</b>\n<i>{event.text}</i>"
            elif event.photo:
                log_text += f"\n📸 <i>[Отправил фото]</i>"
            elif event.video:
                log_text += f"\n🎬 <i>[Отправил видео]</i>"
            elif event.document:
                log_text += f"\n📁 <i>[Отправил файл]</i>"
                
            try:
                await bot.send_message(ADMIN_ID, log_text, parse_mode="HTML")
            except Exception as e:
                logging.error(f"Ошибка отправки лога: {e}")

        return await handler(event, data)

# ==============================================================================
# 👤 ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ
# ==============================================================================
def get_main_kb(user_id):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить почту", callback_data="buy_auto", style="success")],
        [InlineKeyboardButton(text="✨ Заказать кастомную", callback_data="buy_custom", style="primary")],
        [InlineKeyboardButton(text="📁 Мои почты", callback_data="my_emails", style="primary"), InlineKeyboardButton(text="👤 Профиль", callback_data="profile", style="primary")],
        [InlineKeyboardButton(text="💻 Заказать бота", callback_data="order_bot", style="primary")],
        [InlineKeyboardButton(text="📜 Правила и гарантия", callback_data="rules", style="danger")]
    ])
    if user_id == ADMIN_ID:
        kb.inline_keyboard.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel", style="danger")])
    return kb

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject = None):
    user_id = message.from_user.id
    args = command.args if command else None
    
    ref_id = None
    if args and args.startswith("ref_"):
        try:
            ref_id = int(args.split("_")[1])
            if ref_id == user_id: ref_id = None
        except: pass

    user = get_user(user_id)
    if not user:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (user_id, username, first_name, referrer_id) VALUES (?, ?, ?, ?)",
                       (user_id, message.from_user.username, message.from_user.first_name, ref_id))
        if ref_id:
            cursor.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?", (ref_id,))
        conn.commit()
        conn.close()

    await message.answer(
        f"🔥 <b>Добро пожаловать в магазин почт!</b>\n\n"
        f"✅ У нас только чистые и свежие аккаунты.\n"
        f"⚠️ Гарантия на все почты — 24 часа.",
        reply_markup=get_main_kb(user_id)
    )

@router.callback_query(F.data == "rules")
async def show_rules(callback: CallbackQuery):
    text = (
        f"📜 <b>Правила и Гарантия</b>\n\n"
        f"1. Мы выдаем только чистые почты (Mail.ru, Gmail).\n"
        f"2. <b>Гарантия 24 часа:</b> Если почта не работает сразу после покупки или слетела в течение 24 часов, мы бесплатно заменим её.\n"
        f"3. Для замены обязательно наличие скриншота ошибки и обращение в поддержку.\n"
        f"4. Оплата Stars и Crypto выдается автоматически.\n"
        f"5. 📋 За 5 приглашенных друзей вы получаете 1 почту бесплатно!\n"
        f"6. ⭐ От 3 покупок открывается VIP-статус и оплата на карту."
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main", style="danger")]]))
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(f"🔥 <b>Главное меню</b>", reply_markup=get_main_kb(callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    user_id, username, first_name, balance, referrer_id, ref_count, vip_status, free_claimed = user
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM emails WHERE buyer_id = ?", (user_id,))
    bought_count = cursor.fetchone()[0]
    conn.close()

    vip_text = f"⭐ <b>VIP Статус: Активен</b>" if vip_status else "Статус: Обычный"
    free_text = "✅ Доступна 1 бесплатная" if ref_count >= 5 and not free_claimed else f"До бесплатной: {5 - (ref_count % 5)} чел."

    text = (
        f"👤 <b>Твой профиль</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {first_name}\n\n"
        f"💰 Баланс: <b>{balance} баллов</b>\n"
        f"👥 Рефералов: <b>{ref_count}</b> ({free_text})\n"
        f"📁 Куплено почт: <b>{bought_count}</b>\n"
        f"{vip_text}\n\n"
        f"<i>Твоя реферальная ссылка:</i>\n<code>{ref_link}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Забрать бесплатную почту", callback_data="claim_free", style="success")]] if ref_count >= 5 and not free_claimed else [])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main", style="danger")])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "claim_free")
async def claim_free_email(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if user[5] < 5 or user[7]:
        return await callback.answer("Условия не выполнены!", show_alert=True)
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, password, service FROM emails WHERE status = 'available' LIMIT 1")
    email = cursor.fetchone()
    
    if not email:
        conn.close()
        return await callback.answer("Нет свободных почт, напишите админу!", show_alert=True)
        
    e_id, e_login, e_pass, e_service = email
    cursor.execute("UPDATE emails SET status = 'sold', buyer_id = ?, bought_at = ? WHERE id = ?", (user_id, int(time.time()), e_id))
    cursor.execute("UPDATE users SET free_email_claimed = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    await callback.message.answer(
        f"🎁 <b>Твоя бесплатная почта:</b>\n\n"
        f"Сервис: {e_service}\n"
        f"Логин: <code>{e_login}</code>\n"
        f"Пароль: <code>{e_pass}</code>\n\n"
        f"<i>Не забудь сменить пароль при входе!</i>"
    )
    await callback.answer("Почта выдана!")

@router.callback_query(F.data == "my_emails")
async def my_emails(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT email, password, service, bought_at FROM emails WHERE buyer_id = ?", (user_id,))
    emails = cursor.fetchall()
    conn.close()

    if not emails:
        return await callback.message.edit_text(f"❗️ Вы еще не покупали почты.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main", style="danger")]]))

    text = f"📋 <b>Ваши почты:</b>\n\n"
    for e in emails:
        e_login, e_pass, e_service, b_time = e
        warranty = "✅ Гарантия" if (time.time() - b_time) < 86400 else "❌ Гарантия истекла"
        text += f"Сервис: {e_service} ({warranty})\nЛогин: <code>{e_login}</code>\nПароль: <code>{e_pass}</code>\n\n"

    text += f"💬 Если почта не работает, обратитесь к админу: {ADMIN_CONTACT}"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main", style="danger")]]))
    await callback.answer()

# --- ЗАКАЗ КАСТОМНОЙ ПОЧТЫ ---
@router.callback_query(F.data == "buy_custom")
async def custom_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomOrder.service)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Mail.ru", callback_data="service_Mail.ru", style="primary")],
        [InlineKeyboardButton(text="Gmail", callback_data="service_Gmail", style="primary")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main", style="danger")]
    ])
    await callback.message.edit_text(f"✨ <b>Заказ кастомной почты</b>\n\nВыберите сервис:", reply_markup=kb)
    await callback.answer()

@router.callback_query(CustomOrder.service, F.data.startswith("service_"))
async def custom_service(callback: CallbackQuery, state: FSMContext):
    service = callback.data.replace("service_", "")
    await state.update_data(service=service)
    await state.set_state(CustomOrder.name)
    await callback.message.edit_text(f"Сервис: <b>{service}</b>\n\n2️⃣ Напиши желаемый никнейм (например: boss, crypto, иван):")
    await callback.answer()

@router.message(CustomOrder.name)
async def custom_name(message: Message, state: FSMContext):
    name = message.text.strip()
    data = await state.get_data()
    service = data['service']
    await state.clear()
    
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO custom_orders (user_id, service, desired_name) VALUES (?, ?, ?)", (user_id, service, name))
    conn.commit()
    conn.close()
    
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
    admin_msg = (
        f"🔔 <b>НОВЫЙ ЗАКАЗ КАСТОМНОЙ ПОЧТЫ!</b>\n\n"
        f"👤 Клиент: {username}\n"
        f"📧 Сервис: {service}\n"
        f"🏷 Желаемый ник: <code>{name}</code>\n\n"
        f"<i>Свяжитесь с клиентом для оплаты (от 35 до 75₽).</i>"
    )
    await bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML")
    
    await message.answer(
        f"✅ Заявка отправлена админу!\n\n"
        f"💬 С вами свяжутся в течение дня.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_main", style="danger")]])
    )

# --- ЗАКАЗ БОТА ---
@router.callback_query(F.data == "order_bot")
async def order_bot_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BotOrder.description)
    await callback.message.edit_text(
        f"💻 <b>Заказ разработки бота</b>\n\n"
        f"Опиши в одном сообщении, какого бота ты хочешь (функции, задачи, идея):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main", style="danger")]])
    )
    await callback.answer()

@router.message(BotOrder.description)
async def order_bot_process(message: Message, state: FSMContext):
    desc = message.text
    await state.clear()
    user_id = message.from_user.id
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO bot_orders (user_id, description) VALUES (?, ?)", (user_id, desc))
    conn.commit()
    conn.close()
    
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
    admin_msg = (
        f"🔔 <b>ЗАКАЗ НА РАЗРАБОТКУ БОТА!</b>\n\n"
        f"👤 Клиент: {username} (<code>{user_id}</code>)\n\n"
        f"📝 <b>ТЗ:</b>\n{desc}"
    )
    await bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML")
    
    await message.answer(
        f"✅ Заявка отправлена!\nАдмин свяжется с тобой.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_main", style="danger")]])
    )

# --- ПОКУПКА ГОТОВОЙ ПОЧТЫ ---
@router.callback_query(F.data == "buy_auto")
async def show_available_emails(callback: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, service, price FROM emails WHERE status = 'available' LIMIT 10")
    emails = cursor.fetchall()
    conn.close()

    if not emails:
        return await callback.message.edit_text(f"❗️ Свободных почт нет.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main", style="danger")]]))

    kb = []
    for e in emails:
        e_id, service, price = e
        kb.append([InlineKeyboardButton(text=f"{service} — {price} ⭐️", callback_data=f"buy_mail_{e_id}_{price}", style="success")])
    
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main", style="danger")])
    await callback.message.edit_text(f"🛒 <b>Выберите почту для покупки:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@router.callback_query(F.data.startswith("buy_mail_"))
async def choose_payment_method(callback: CallbackQuery):
    _, _, m_id, price = callback.data.split("_")
    m_id, price = int(m_id), int(price)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {price} ⭐️ (Stars)", callback_data=f"pay_stars_{m_id}_{price}", style="primary")],
        [InlineKeyboardButton(text="Оплатить CryptoBot ($)", callback_data=f"pay_crypto_{m_id}_{price}", style="success")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_auto", style="danger")]
    ])
    await callback.message.edit_text(f"💳 <b>Выберите способ оплаты:</b>", reply_markup=kb)
    await callback.answer()

# --- ОПЛАТА ЗВЕЗДАМИ ---
@router.callback_query(F.data.startswith("pay_stars_"))
async def process_pay_stars(callback: CallbackQuery):
    _, _, m_id, price = callback.data.split("_")
    m_id, price = int(m_id), int(price)
    
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Покупка почты",
        description="Доступ выдается автоматически",
        payload=f"email_{m_id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Почта", amount=price)]
    )
    await callback.answer()

@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("email_"):
        e_id = int(payload.split("_")[1])
        await fulfill_email_order(message, e_id)

# --- ОПЛАТА КРИПТОБОТ ---
@router.callback_query(F.data.startswith("pay_crypto_"))
async def process_pay_crypto(callback: CallbackQuery):
    _, _, m_id, price = callback.data.split("_")
    m_id, price = int(m_id), int(price)
    
    usd_price = round(price * 0.015, 2)
    if usd_price < 0.1: usd_price = 0.1

    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    payload = f"crypto_{m_id}"
    data = {
        "currency_type": "fiat",
        "fiat": "USD",
        "amount": str(usd_price),
        "payload": payload,
        "description": f"Покупка почты"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as resp:
                res = await resp.json()
                if not res.get("ok"):
                    await callback.answer("Ошибка создания счета!", show_alert=True)
                    return
                inv = res["result"]
    except Exception as e:
        logging.error(f"CryptoBot error: {e}")
        await callback.answer("Ошибка связи с CryptoBot!", show_alert=True)
        return

    invoice_id = inv["invoice_id"]
    pay_url = inv["bot_invoice_url"]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url, style="success")],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_crypto_{invoice_id}_{m_id}", style="primary")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_auto", style="danger")]
    ])
    
    await callback.message.edit_text(
        f"💰 <b>Счет на покупку</b>\n\n"
        f"К оплате: <b>{usd_price}$</b>\n"
        f"После оплаты нажмите кнопку «Проверить оплату».", 
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_payment(callback: CallbackQuery):
    _, _, invoice_id, m_id = callback.data.split("_")
    m_id = int(m_id)
    
    url = f"https://pay.crypt.bot/api/getInvoices?invoice_ids={invoice_id}"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                res = await resp.json()
                if res.get("ok") and res.get("result", {}).get("items"):
                    item = res["result"]["items"][0]
                    if item.get("status") == "paid":
                        await fulfill_email_order(callback.message, m_id, is_edit=True)
                        await callback.answer("Оплата подтверждена!")
                        return
    except Exception as e:
        logging.error(f"Error checking invoice: {e}")

    await callback.answer("⏳ Оплата еще не поступила. Завершите перевод.", show_alert=True)

# --- ФУНКЦИЯ ВЫДАЧИ ПОЧТЫ ---
async def fulfill_email_order(message_or_callback_message: Message, e_id: int, is_edit: bool = False):
    user_id = message_or_callback_message.chat.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT email, password, service FROM emails WHERE id = ? AND status = 'available'", (e_id,))
    email_data = cursor.fetchone()
    
    if email_data:
        e_login, e_pass, e_service = email_data
        cursor.execute("UPDATE emails SET status = 'sold', buyer_id = ?, bought_at = ? WHERE id = ?", (user_id, int(time.time()), e_id))
        
        cursor.execute("SELECT COUNT(*) FROM emails WHERE buyer_id = ?", (user_id,))
        if cursor.fetchone()[0] >= 3:
            cursor.execute("UPDATE users SET vip_status = 1 WHERE user_id = ?", (user_id,))
            
        conn.commit()
        conn.close()
        
        text = (
            f"✅ <b>Оплата успешна! Ваша почта:</b>\n\n"
            f"Сервис: {e_service}\n"
            f"Логин: <code>{e_login}</code>\n"
            f"Пароль: <code>{e_pass}</code>\n\n"
            f"⚠️ <i>Гарантия 24 часа. Если не заходит, пишите в поддержку!</i>"
        )
        
        if is_edit:
            await message_or_callback_message.edit_text(text)
        else:
            await message_or_callback_message.answer(text)
    else:
        conn.close()
        error_msg = f"❗️ Ошибка: почта уже куплена или не найдена."
        if is_edit:
            await message_or_callback_message.edit_text(error_msg)
        else:
            await message_or_callback_message.answer(error_msg)

# ==============================================================================
# ⚙️ АДМИН-ПАНЕЛЬ
# ==============================================================================
@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats", style="primary")],
        [InlineKeyboardButton(text="📣 Рассылка", callback_data="admin_broadcast", style="success")],
        [InlineKeyboardButton(text="➕ Загрузить почты", callback_data="admin_add_emails", style="success")],
        [InlineKeyboardButton(text="📦 Заявки на кастом", callback_data="admin_orders", style="primary")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main", style="danger")]
    ])
    await callback.message.edit_text(f"⚙️ <b>Админ-панель</b>", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users"); total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM emails WHERE status = 'sold'"); sold_emails = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM emails WHERE status = 'available'"); avail_emails = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM custom_orders WHERE status = 'pending'"); pending_custom = cursor.fetchone()[0]
    conn.close()
    
    text = (
        f"📊 <b>СТАТИСТИКА БОТА</b>\n\n"
        f"👤 Всего пользователей: <b>{total_users}</b>\n"
        f"📋 Почты в наличии: <b>{avail_emails}</b>\n"
        f"✅ Почты продано: <b>{sold_emails}</b>\n"
        f"⚠️ Заявок в ожидании: <b>{pending_custom}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats", style="primary")], [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel", style="danger")]])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_broadcast)
    await callback.message.edit_text(
        f"📣 <b>Создание рассылки</b>\n\n"
        f"Отправь мне <b>любое сообщение</b> (текст, фото, видео, эмодзи), и я разошлю его всем пользователям в точности так, как ты его написал!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel", style="danger")]])
    )
    await callback.answer()

@router.message(AdminState.waiting_broadcast)
async def admin_broadcast_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    await message.answer(f"🚀 Начинаю рассылку для {len(users)} пользователей...")
    
    success = 0
    fail = 0
    
    for u_id in users:
        try:
            await message.copy_to(chat_id=u_id)
            success += 1
            await asyncio.sleep(0.05) 
        except Exception:
            fail += 1
            
    await message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"✅ Доставлено: <b>{success}</b>\n"
        f"❌ Ошибок (заблокировали): <b>{fail}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В админку", callback_data="admin_panel")]])
    )

@router.callback_query(F.data == "admin_add_emails")
async def admin_add_emails(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_emails)
    await callback.message.edit_text(
        f"📝 Отправь список почт в формате (каждая с новой строки):\n"
        f"<code>сервис:логин:пароль:цена</code>\n\n"
        f"Например:\n"
        f"<code>Gmail:test1@gmail.com:pass123:20</code>\n"
        f"<code>Mail.ru:test2@mail.ru:pass456:15</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel", style="danger")]])
    )
    await callback.answer()

@router.message(AdminState.waiting_emails)
async def process_emails_upload(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    lines = message.text.strip().split('\n')
    added = 0
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    for line in lines:
        try:
            parts = line.strip().split(':')
            if len(parts) == 4:
                service, login, password, price = parts
                cursor.execute("INSERT INTO emails (service, email, password, price) VALUES (?, ?, ?, ?)", 
                               (service.strip(), login.strip(), password.strip(), int(price)))
                added += 1
        except: continue
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(f"✅ Успешно добавлено: <b>{added}</b> почт!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В админку", callback_data="admin_panel")]]))

@router.callback_query(F.data == "admin_orders")
async def admin_orders(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, service, desired_name FROM custom_orders WHERE status = 'pending' LIMIT 5")
    orders = cursor.fetchall()
    conn.close()
    if not orders:
        return await callback.message.edit_text("📦 Нет новых заявок.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel", style="danger")]]))
    text = "📦 <b>Заявки на кастомные почты:</b>\n\n"
    for o in orders:
        text += f"ID заказа: {o[0]} | Клиент: <code>{o[1]}</code>\nСервис: {o[2]} | Ник: {o[3]}\n\n"
    text += "<i>Свяжись с клиентами для оплаты и выдачи.</i>"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel", style="danger")]]))
    await callback.answer()

# ==============================================================================
# 🚀 ЗАПУСК
# ==============================================================================
async def main():
    init_db()
    dp.message.outer_middleware(LoggingMiddleware())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Бот магазина почт запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
