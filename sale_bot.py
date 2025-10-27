# sale_bot.py
import os
import logging
import sqlite3
import asyncio
from datetime import datetime
import re
import random
import string
from flask import Flask, request, Response

# ENV
PLANS_STR = "یک ماهه:199000,سه ماهه:490000,شش ماهه:870000,یک ساله:1470000"
PLANS = {p.split(":")[0]: int(p.split(":")[1]) for p in PLANS_STR.split(",")}
CARD_NUMBER = "6219861991747055"
ADMIN_CHAT_ID = "7575064458"
BOT_TOKEN = "8145134646:AAHZ3fazKnYcGH2tN-XatQzilRfbIk51FAQ"
DB_PATH = "/home/ekhtesas/sales_bot.db"

# IMPORTS telegram
from telegram import (ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton)
from telegram.ext import (
    Application,
    CommandHandler, ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

# LOGGING -> file + stream
LOG_FILE = os.path.join(os.path.dirname(__file__), "bot.log")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# DATABASE
def setup_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # users table
    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        chat_id INTEGER UNIQUE,
        username TEXT,
        first_name TEXT,
        last_name TEXT
    )
    ''')
    # orders table
    c.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        email TEXT,
        password TEXT,
        plan TEXT,
        price INTEGER,
        receipt_photo BLOB,
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    # discount codes
    c.execute('''
    CREATE TABLE IF NOT EXISTS discount_codes (
        code TEXT PRIMARY KEY,
        discount_percent INTEGER,
        status TEXT DEFAULT 'active'
    )
    ''')
    conn.commit()

    # set starting order id to 16800 (if empty)
    c.execute("SELECT count(order_id) FROM orders")
    count = c.fetchone()[0]
    if count == 0:
        try:
            c.execute("INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES ('orders', 16799)")
            conn.commit()
            logger.info("Starting order ID set to 16800.")
        except Exception as e:
            logger.warning(f"Could not set auto-increment sequence: {e}")

    conn.close()
    print("✅ Database setup complete (orders starting from 16800).")

setup_database()

# STATES
EMAIL, PASSWORD, PLAN, DISCOUNT_CODE, CONFIRM_PAYMENT, UPLOAD_RECEIPT = range(6)
GET_DISCOUNT_PERCENT = range(1)

# KEYBOARDS
cancel_keyboard = ReplyKeyboardMarkup(
    [["لغو ❌"]], resize_keyboard=True, one_time_keyboard=True
)
back_cancel_keyboard = ReplyKeyboardMarkup(
    [["بازگشت 🔙"], ["لغو ❌"]], resize_keyboard=True, one_time_keyboard=True
)

# FLASK app (exported for passenger_wsgi.py)
flask_app = Flask(__name__)

# Create global Telegram application
application = Application.builder().token(BOT_TOKEN).build()

# === Handlers (همان کد قبلی، بدون تغییر منطقی) ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (user_id, chat_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name
        ''', (user.id, chat_id, user.username, user.first_name, user.last_name))
        conn.commit()
        conn.close()
        logger.info(f"User {user.first_name} (ID: {user.id}) started the bot.")
    except Exception as e:
        logger.error(f"Error saving user {user.id}: {e}")

    welcome_text = f"سلام **{user.first_name}** عزیز، به بات فروش خوش آمدید. 🤖"
    welcome_text += "\n\nلطفا برای ادامه روی دکمه زیر بزنید:"
    keyboard = [[InlineKeyboardButton("🚀 شروع", callback_data="show_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    menu_text = "لطفا یکی از گزینه‌های زیر را انتخاب کنید:"
    keyboard = [
        [InlineKeyboardButton("🛍️ ثبت سفارش جدید", callback_data="new_order")],
        [InlineKeyboardButton("🧾 سفارش‌های من", callback_data="my_orders")],
        [InlineKeyboardButton("💰 تعرفه‌ها", callback_data="plans")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=menu_text, reply_markup=reply_markup)

async def show_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    menu_text = "منوی اصلی:"
    keyboard = [
        [InlineKeyboardButton("🛍️ ثبت سفارش جدید", callback_data="new_order")],
        [InlineKeyboardButton("🧾 سفارش‌های من", callback_data="my_orders")],
        [InlineKeyboardButton("💰 تعرفه‌ها", callback_data="plans")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text=menu_text, reply_markup=reply_markup)

def translate_status(status):
    if status == 'pending':
        return "در انتظار تایید رسید ⏳"
    elif status == 'processing':
        return "در حال انجام ⚙️"
    elif status == 'approved':
        return "انجام شده ✅"
    elif status == 'rejected':
        return "رد شده ❌"
    return status

async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "new_order":
        logger.info("User started new order flow.")
        context.user_data['order'] = {}
        await query.edit_message_text(text="لطفا جیمیل خود را وارد کنید:")
        await query.message.reply_text("... (مرحله ۱ از ۶)", reply_markup=cancel_keyboard, parse_mode='Markdown')
        return EMAIL

    elif data == "my_orders":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT order_id, plan, status, created_at FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user_id,))
        orders = c.fetchall()
        conn.close()

        if not orders:
            await query.edit_message_text(text="شما هنوز سفارشی ثبت نکرده‌اید.", reply_markup=back_to_menu_keyboard())
            return ConversationHandler.END

        message = "🧾 **سفارش‌های شما:**\n\n"
        for order in orders:
            order_id, plan, status, created_at = order
            date_time_obj = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S.%f' if '.' in created_at else '%Y-%m-%d %H:%M:%S')
            f_date = date_time_obj.strftime('%Y/%m/%d')
            f_status = translate_status(status)
            message += f"🔹 **سفارش شماره {order_id}**\n"
            message += f"   - **پلن:** {plan}\n"
            message += f"   - **تاریخ:** {f_date}\n"
            message += f"   - **وضعیت:** {f_status}\n\n"

        await query.edit_message_text(text=message, reply_markup=back_to_menu_keyboard(), parse_mode='Markdown')

    elif data == "plans":
        plan_list = "\n".join([f"🔸 {name}: **{price:,} تومان**" for name, price in PLANS.items()])
        await query.edit_message_text(text=f"💰 **لیست تعرفه‌ها:**\n\n{plan_list}", reply_markup=back_to_menu_keyboard(), parse_mode='Markdown')

    elif data == "support":
        await query.edit_message_text(text="📞 برای پشتیبانی با ادمین در تماس باشید: @Admiin_gemini", reply_markup=back_to_menu_keyboard())

    return ConversationHandler.END

async def go_back_to_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("User going back to EMAIL state.")
    await update.message.reply_text("لطفا جیمیل خود را مجددا وارد کنید:",
                                  reply_markup=cancel_keyboard, parse_mode='Markdown')
    return EMAIL

async def go_back_to_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    logger.info("User going back to PASSWORD state.")
    await query.edit_message_text("لطفا رمز عبور خود را مجددا وارد کنید:")
    await query.message.reply_text("... (مرحله ۲ از ۶)", reply_markup=back_cancel_keyboard)
    return PASSWORD

async def go_back_to_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    logger.info("User going back to PLAN state.")

    keyboard = []
    for plan_name, price in PLANS.items():
        callback_data = f"plan_{plan_name}_{price}"
        keyboard.append([InlineKeyboardButton(f"🔸 {plan_name} ({price:,} تومان)", callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت (به رمز عبور)", callback_data="back_to_PASSWORD")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text="لطفا پلن مورد نظر خود را مجددا انتخاب کنید:", reply_markup=reply_markup)
    return PLAN

async def go_back_to_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_payment_info(update, context)
    return CONFIRM_PAYMENT

EMAIL_REGEX = r"^[a-zA-Z0-9_.+-]+@gmail\.com$"

async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_email = update.message.text.strip()
    if re.match(EMAIL_REGEX, user_email, re.IGNORECASE):
        context.user_data['order']['email'] = user_email
        logger.info(f"Step 1: Valid Email received: {user_email}")
        await update.message.reply_text("✅ ایمیل تایید شد.\nلطفا رمز عبور خود را وارد کنید:",
                                      reply_markup=back_cancel_keyboard)
        return PASSWORD
    else:
        logger.info(f"Step 1: Invalid Email attempt: {user_email}")
        await update.message.reply_text(
            "❌ ایمیل نامعتبر است.\nلطفا **فقط** یک آدرس جیمیل (مانند example@gmail.com) وارد کنید.",
            reply_markup=cancel_keyboard,
            parse_mode='Markdown'
        )
        return EMAIL

async def get_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_password = update.message.text
    context.user_data['order']['password'] = user_password
    logger.info(f"Step 2: Password received.")

    await update.message.reply_text("رمز عبور دریافت شد.", reply_markup=ReplyKeyboardRemove())

    keyboard = []
    for plan_name, price in PLANS.items():
        callback_data = f"plan_{plan_name}_{price}"
        keyboard.append([InlineKeyboardButton(f"🔸 {plan_name} ({price:,} تومان)", callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت (به رمز عبور)", callback_data="back_to_PASSWORD")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("لطفا پلن مورد نظر خود را انتخاب کنید:", reply_markup=reply_markup)
    return PLAN

async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    plan_name = data[1]
    plan_price = int(data[2])

    context.user_data['order']['plan'] = plan_name
    context.user_data['order']['original_price'] = plan_price
    context.user_data['order']['price'] = plan_price
    context.user_data['order']['discount_code'] = None
    logger.info(f"Step 3: Plan selected: {plan_name} for {plan_price}")

    keyboard = [
        [InlineKeyboardButton("✅ بله، کد تخفیف دارم", callback_data="has_discount_code")],
        [InlineKeyboardButton("❌ خیر، ادامه خرید", callback_data="no_discount_code")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=f"پلن **{plan_name}** به مبلغ **{plan_price:,} تومان** انتخاب شد.\n\nآیا کد تخفیف دارید؟",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return DISCOUNT_CODE

async def ask_for_discount_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "has_discount_code":
        await query.edit_message_text(text="لطفا کد تخفیف خود را وارد کنید:")
        await query.message.reply_text("... (مرحله ۴ از ۶)", reply_markup=back_cancel_keyboard)
        return DISCOUNT_CODE
    else:
        return await show_payment_info(update, context)

async def get_discount_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_code = update.message.text.strip().upper()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT discount_percent FROM discount_codes WHERE code = ? AND status = 'active'", (user_code,))
    result = c.fetchone()
    conn.close()

    if result:
        discount_percent = result[0]
        original_price = context.user_data['order']['original_price']
        discount_amount = (original_price * discount_percent) // 100
        final_price = original_price - discount_amount

        context.user_data['order']['price'] = final_price
        context.user_data['order']['discount_code'] = user_code

        await update.message.reply_text(f"✅ کد تخفیف **{discount_percent}%** با موفقیت اعمال شد.", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
        return await show_payment_info(update, context, is_message=True)
    else:
        await update.message.reply_text("❌ کد تخفیف نامعتبر یا استفاده شده است.\nمجددا تلاش کنید یا روی «لغو» بزنید.",
                                      reply_markup=cancel_keyboard)
        return DISCOUNT_CODE

async def show_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE, is_message: bool = False) -> int:
    order_data = context.user_data['order']
    plan_name = order_data['plan']
    final_price = order_data['price']
    discount_code = order_data.get('discount_code')

    payment_info = "اطلاعات سفارش شما:\n\n"
    payment_info += f"**ایمیل:** `{order_data['email']}`\n"
    payment_info += f"**پلن:** {plan_name}\n"

    if discount_code:
        original_price = order_data['original_price']
        payment_info += f"**قیمت اولیه:** `{original_price:,}` تومان\n"
        payment_info += f"**کد تخفیف:** `{discount_code}`\n"
        payment_info += f"**مبلغ نهایی:** **`{final_price:,}` تومان**\n\n"
    else:
        payment_info += f"**مبلغ قابل پرداخت:** **`{final_price:,}` تومان**\n\n"

    payment_info += "لطفا مبلغ را به شماره کارت زیر واریز نمایید:\n"
    payment_info += f"`{CARD_NUMBER}`\n\n"
    payment_info += "پس از واریز، روی دکمه «پرداخت کردم» بزنید و رسید را ارسال کنید."

    keyboard = [[InlineKeyboardButton("✅ پرداخت کردم (ارسال رسید)", callback_data="payment_confirmed")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if is_message:
         await update.message.reply_text("... (مرحله ۵ از ۶)")
         await update.message.reply_text(text=payment_info, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        query = update.callback_query
        await query.edit_message_text(text=payment_info, reply_markup=reply_markup, parse_mode='Markdown')

    return CONFIRM_PAYMENT

async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    logger.info("Step 4: User confirmed payment, awaiting receipt.")

    await query.edit_message_text(text="🖼️ لطفا عکس رسید واریز خود را ارسال کنید.")
    await query.message.reply_text("... (مرحله ۶ از ۶)", reply_markup=back_cancel_keyboard)
    return UPLOAD_RECEIPT

async def upload_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    high_res_photo = update.message.photo[-1]
    photo_file_id_to_send = high_res_photo.file_id
    photo_file_obj = await high_res_photo.get_file()
    photo_bytes_for_db = await photo_file_obj.download_as_bytearray()

    user = update.effective_user
    order_data = context.user_data['order']
    logger.info(f"Step 5: Receipt received. Saving order for user {user.id}.")

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO orders (user_id, email, password, plan, price, receipt_photo, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            user.id,
            order_data['email'],
            order_data['password'],
            order_data['plan'],
            order_data['price'],
            sqlite3.Binary(photo_bytes_for_db),
            'pending'
        ))
        new_order_id = c.lastrowid

        if order_data.get('discount_code'):
            c.execute("UPDATE discount_codes SET status = 'used' WHERE code = ?", (order_data['discount_code'],))

        conn.commit()
        conn.close()
        logger.info(f"Order {new_order_id} saved successfully.")

        await update.message.reply_text(
            f"متشکریم! 🙏\nسفارش شما (شماره: **{new_order_id}**) ثبت شد و پس از بررسی فعال خواهد شد.",
            reply_markup=back_to_menu_keyboard(inline=False),
            parse_mode='Markdown'
        )

        admin_message = f"🔔 **سفارش جدید** (شماره: {new_order_id})\n\n"
        admin_message += f"**کاربر:** {user.first_name} (آیدی: {user.id})\n"
        admin_message += f"**ایمیل:** {order_data['email']}\n"
        admin_message += f"**رمز عبور:** `{order_data['password']}`\n\n"
        admin_message += f"**پلن:** {order_data['plan']}\n"
        admin_message += f"**مبلغ:** {order_data['price']:,} تومان"
        if order_data.get('discount_code'):
             admin_message += f"\n**کد تخفیف:** `{order_data['discount_code']}`"

        admin_keyboard = [
            [InlineKeyboardButton(f"✅ تایید رسید (شماره: {new_order_id})", callback_data=f"admin_approve_receipt_{new_order_id}")],
            [InlineKeyboardButton(f"❌ رد سفارش (شماره: {new_order_id})", callback_data=f"admin_reject_{new_order_id}")]
        ]
        admin_markup = InlineKeyboardMarkup(admin_keyboard)

        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_file_id_to_send,
            caption=admin_message,
            reply_markup=admin_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Failed to save order or notify admin for user {user.id}: {e}")
        await update.message.reply_text("خطایی در ثبت سفارش رخ داد. لطفا با پشتیبانی تماس بگیرید.")

    context.user_data.clear()
    return ConversationHandler.END

# MENU KEYBOARDS
def back_to_menu_keyboard(inline=True):
    if inline:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به منو اصلی", callback_data="show_menu")]]
        return InlineKeyboardMarkup(keyboard)
    else:
        return ReplyKeyboardMarkup([["🔙 بازگشت به منو اصلی"]], resize_keyboard=True, one_time_keyboard=True)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"User {update.effective_user.first_name} cancelled the conversation.")
    await update.message.reply_text(
        "عملیات لغو شد.", reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    await show_menu_message(update, context)
    return ConversationHandler.END

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    logger.info("User returned to main menu via inline button.")
    context.user_data.clear()
    await show_menu(update, context)
    return ConversationHandler.END

# ADMIN FEATURES
async def list_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != ADMIN_CHAT_ID: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT order_id, user_id, plan FROM orders WHERE status = 'pending'")
    orders = c.fetchall()
    conn.close()
    if not orders:
        await update.message.reply_text("هیچ سفارش در انتظار تایید رسیدی وجود ندارد.")
        return
    message = "⏳ **سفارش‌های در انتظار تایید رسید:**\n"
    for o in orders:
        message += f"- شماره: {o[0]} (کاربر: {o[1]}, پلن: {o[2]})\n"
    await update.message.reply_text(message)

async def list_processing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != ADMIN_CHAT_ID: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT order_id, user_id, email, password FROM orders WHERE status = 'processing'")
    orders = c.fetchall()
    conn.close()
    if not orders:
        await update.message.reply_text("هیچ سفارش در حال انجام وجود ندارد.")
        return
    message = "⚙️ **سفارش‌های در حال انجام:**\n"
    for o in orders:
        message += f"- شماره: {o[0]} (کاربر: {o[1]})\n  - ایمیل: {o[2]}\n  - رمز: `{o[3]}`\n"
    await update.message.reply_text(message, parse_mode='Markdown')

async def list_approved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != ADMIN_CHAT_ID: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT order_id, user_id, plan FROM orders WHERE status = 'approved' ORDER BY order_id DESC LIMIT 10")
    orders = c.fetchall()
    conn.close()
    if not orders:
        await update.message.reply_text("هنوز سفارش تایید شده‌ای وجود ندارد.")
        return
    message = "✅ **۱۰ سفارش آخر تایید شده:**\n"
    for o in orders:
        message += f"- شماره: {o[0]} (کاربر: {o[1]}, پلن: {o[2]})\n"
    await update.message.reply_text(message)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    user_id_to_notify = None
    order_id = int(data.split("_")[-1])

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        if data.startswith("admin_approve_receipt_"):
            logger.info(f"Admin: Approving receipt for order {order_id}")
            c.execute("SELECT user_id, email, password, plan, price FROM orders WHERE order_id = ?", (order_id,))
            result = c.fetchone()
            if not result:
                await query.edit_message_caption(caption=f"خطا: سفارش {order_id} یافت نشد.")
                return

            user_id_to_notify, email, password, plan, price = result

            c.execute("UPDATE orders SET status = 'processing' WHERE order_id = ?", (order_id,))
            conn.commit()

            await context.bot.send_message(
                chat_id=user_id_to_notify,
                text=f"🧾 رسید شما برای سفارش شماره **{order_id}** تایید شد.\n\n"
                     f"سفارش شما **در حال انجام است...** ⚙️\n"
                     "لطفا تا پیام بعدی منتظر بمانید.",
                parse_mode='Markdown'
            )

            original_caption = query.message.caption or ""
            new_caption = f"{original_caption}\n\n-- وضعیت: در حال انجام ⚙️ --"

            new_keyboard = [[InlineKeyboardButton(f"🏁 تایید انجام سفارش (شماره: {order_id})", callback_data=f"admin_approve_final_{order_id}")]]
            await query.edit_message_caption(
                caption=new_caption,
                reply_markup=InlineKeyboardMarkup(new_keyboard),
                parse_mode='Markdown'
            )

        elif data.startswith("admin_approve_final_"):
            logger.info(f"Admin: Finalizing order {order_id}")

            c.execute("UPDATE orders SET status = 'approved' WHERE order_id = ?", (order_id,))
            conn.commit()

            c.execute("SELECT user_id FROM orders WHERE order_id = ?", (order_id,))
            user_id_to_notify = c.fetchone()[0]

            await context.bot.send_message(
                chat_id=user_id_to_notify,
                text=f"✅ سفارش شما (شماره: **{order_id}**) با موفقیت انجام شد.\n\n از خرید شما متشکریم! 🙏",
                parse_mode='Markdown'
            )

            original_caption = query.message.caption or ""
            await query.edit_message_caption(
                caption=f"{original_caption}\n\n-- ✅ سفارش با موفقیت انجام شد --",
                parse_mode='Markdown'
            )

        elif data.startswith("admin_reject_"):
            logger.info(f"Admin: Rejecting order {order_id}")

            c.execute("UPDATE orders SET status = 'rejected' WHERE order_id = ?", (order_id,))
            conn.commit()

            c.execute("SELECT user_id FROM orders WHERE order_id = ?", (order_id,))
            user_id_to_notify = c.fetchone()[0]

            await context.bot.send_message(
                chat_id=user_id_to_notify,
                text=f"❌ متاسفانه سفارش شما (شماره: **{order_id}**) رد شد.\n\n"
                     "لطفا برای پیگیری با پشتیبانی در تماس باشید.",
                parse_mode='Markdown'
            )

            original_caption = query.message.caption or ""
            await query.edit_message_caption(
                caption=f"{original_caption}\n\n-- ❌ سفارش رد شد --",
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error processing admin action for order {order_id}: {e}")
        await query.message.reply_text(f"خطا در پردازش سفارش {order_id}: {e}")
    finally:
        conn.close()

async def new_discount_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if str(update.effective_chat.id) != ADMIN_CHAT_ID:
        return ConversationHandler.END
    await update.message.reply_text("لطفا درصد تخفیف را به صورت یک عدد (مثلا 20) وارد کنید:",
                                  reply_markup=cancel_keyboard)
    return GET_DISCOUNT_PERCENT

async def get_discount_percent_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        percent = int(update.message.text)
        if not 0 < percent <= 100:
            raise ValueError("Percentage out of range")
    except ValueError:
        await update.message.reply_text("❌ ورودی نامعتبر است. لطفا یک عدد بین 1 تا 100 وارد کنید.",
                                      reply_markup=cancel_keyboard)
        return GET_DISCOUNT_PERCENT

    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO discount_codes (code, discount_percent) VALUES (?, ?)", (code, percent))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ کد تخفیف `{code}` با **{percent}%** تخفیف با موفقیت ساخته شد.",
                                      reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error creating discount code: {e}")
        await update.message.reply_text("خطایی در ساخت کد تخفیف رخ داد.")

    return ConversationHandler.END

# === Register handlers into global application ===
def register_handlers(app):
    order_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(menu_callback_handler, pattern="^new_order$"),
        ],
        states={
            EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Text("لغو ❌"), get_email)
            ],
            PASSWORD: [
                MessageHandler(filters.Text("بازگشت 🔙"), go_back_to_email),
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Text("لغو ❌"), get_password)
            ],
            PLAN: [
                CallbackQueryHandler(go_back_to_password, pattern="^back_to_PASSWORD$"),
                CallbackQueryHandler(select_plan, pattern="^plan_")
            ],
            DISCOUNT_CODE: [
                CallbackQueryHandler(ask_for_discount_code, pattern="^(has|no)_discount_code$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Text("لغو ❌"), get_discount_code)
            ],
            CONFIRM_PAYMENT: [
                CallbackQueryHandler(go_back_to_plan, pattern="^back_to_PLAN$"),
                CallbackQueryHandler(confirm_payment, pattern="^payment_confirmed$")
            ],
            UPLOAD_RECEIPT: [
                MessageHandler(filters.Text("بازگشت 🔙"), show_payment_info),
                MessageHandler(filters.PHOTO, upload_receipt)
            ],
        },
        fallbacks=[
            MessageHandler(filters.Text("لغو ❌"), cancel),
        ],
    )

    discount_conv = ConversationHandler(
        entry_points=[CommandHandler("new_discount", new_discount_start)],
        states={
            GET_DISCOUNT_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Text("لغو ❌"), get_discount_percent_admin)],
        },
        fallbacks=[MessageHandler(filters.Text("لغو ❌"), cancel)],
    )

    app.add_handler(order_conv)
    app.add_handler(discount_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_menu, pattern="^show_menu$"))
    app.add_handler(CallbackQueryHandler(menu_callback_handler, pattern="^(my_orders|plans|support)$"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(MessageHandler(filters.Text("🔙 بازگشت به منو اصلی"), show_menu_message))

    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    app.add_handler(CommandHandler("orders_pending", list_pending))
    app.add_handler(CommandHandler("orders_processing", list_processing))
    app.add_handler(CommandHandler("orders_approved", list_approved))

register_handlers(application)

# === Webhook endpoint for Telegram ===
@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
async def webhook()
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        await application.process_update(update)
        return "OK", 200
    except Exception as e:
        logger.exception("Error handling webhook update")
        return Response("Error", status=500)

# === Index and logs pages ===
@flask_app.route("/")
def index():
    return "ربات تلگرام در حال اجراست ✅", 200

@flask_app.route("/logs")
def show_logs():
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                content = f.read()[-20000:]
            content = content.replace("<", "&lt;").replace(">", "&gt;")
            return f"<pre>{content}</pre>", 200
        else:
            return "هنوز لاگی وجود ندارد.", 200
    except Exception as e:
        logger.exception("Error reading log file")
        return Response("Error reading logs", status=500)
