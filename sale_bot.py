import os
import logging
import sqlite3
from datetime import datetime
import re
import random
import string

#ENV
PLANS_STR = os.environ.get('PLANS', 'یک ماهه:199000,سه ماهه:490000,شش ماهه:870000,یک ساله:1470000')
PLANS = {p.split(":")[0]: int(p.split(":")[1]) for p in PLANS_STR.split(",")}
CARD_NUMBER = os.environ.get('CARD_NUMBER', '').strip('\'"')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '').strip('\'"')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip('\'"')
GMAIL_CREDIT = 50000 # اعتبار هدیه برای هر جیمیل

#IMPORTS
from telegram import __version__ as TG_VER
from telegram import (ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton)
from telegram.ext import (
    Application, ApplicationBuilder,
    CommandHandler, ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

#LOGGING
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

#DATABASE
def setup_database():
    conn = sqlite3.connect('sales_bot.db', check_same_thread=False)
    c = conn.cursor()
    # جدول کاربران
    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        chat_id INTEGER UNIQUE,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        wallet_balance INTEGER DEFAULT 0
    )
    ''')
    # جدول سفارش‌ها
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
    # جدول کدهای تخفیف
    c.execute('''
    CREATE TABLE IF NOT EXISTS discount_codes (
        code TEXT PRIMARY KEY,
        discount_percent INTEGER,
        status TEXT DEFAULT 'active'
    )
    ''')
    # جدول شارژ کیف پول
    c.execute('''
    CREATE TABLE IF NOT EXISTS wallet_deposits (
        deposit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        receipt_photo BLOB,
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    # جدول جیمیل‌های ارسالی
    c.execute('''
    CREATE TABLE IF NOT EXISTS gmail_submissions (
        submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        gmail_address TEXT,
        gmail_password TEXT,
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # افزودن ستون wallet_balance به جدول users اگر وجود نداشته باشد
    try:
        c.execute("SELECT wallet_balance FROM users LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE users ADD COLUMN wallet_balance INTEGER DEFAULT 0")
        logger.info("Column 'wallet_balance' added to 'users' table.")

    conn.commit()
    conn.close()
    print("✅ Database setup complete.")

setup_database()

#STATES
(EMAIL, PASSWORD, PLAN, DISCOUNT_CODE, CONFIRM_PAYMENT, UPLOAD_RECEIPT,
 ASK_USE_WALLET, GET_DEPOSIT_AMOUNT, UPLOAD_DEPOSIT_RECEIPT,
 GET_GMAIL_ADDRESS, GET_GMAIL_PASSWORD) = range(11)
GET_DISCOUNT_PERCENT = range(1)


#KEYBOARDS
cancel_keyboard = ReplyKeyboardMarkup(
    [["لغو ❌"]], resize_keyboard=True, one_time_keyboard=True
)
back_cancel_keyboard = ReplyKeyboardMarkup(
    [["بازگشت 🔙"], ["لغو ❌"]], resize_keyboard=True, one_time_keyboard=True
)

# --- HELPER FUNCTIONS ---
def get_user_balance(user_id):
    conn = sqlite3.connect('sales_bot.db')
    c = conn.cursor()
    c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    conn = sqlite3.connect('sales_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, chat_id, username, first_name, last_name) VALUES (?, ?, ?, ?, ?)",
              (user.id, chat_id, user.username, user.first_name, user.last_name))
    conn.commit()
    conn.close()
    
    welcome_text = f"سلام **{user.first_name}** عزیز، به بات فروش خوش آمدید. 🤖"
    keyboard = [[InlineKeyboardButton("🚀 شروع", callback_data="show_menu")]]
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    balance = get_user_balance(user_id)
    
    menu_text = f"موجودی کیف پول شما: **{balance:,} تومان**\n\nلطفا یکی از گزینه‌های زیر را انتخاب کنید:"
    keyboard = [
        [InlineKeyboardButton("🛍️ ثبت سفارش جدید", callback_data="new_order")],
        [InlineKeyboardButton(f"💰 کیف پول (شارژ)", callback_data="wallet")],
        [InlineKeyboardButton("✉️ ساخت جیمیل جدید (کسب اعتبار)", callback_data="new_gmail")],
        [InlineKeyboardButton("🧾 سفارش‌های من", callback_data="my_orders")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(text=menu_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.warning(f"Error editing message in show_menu: {e}")
        await query.message.reply_text(text=menu_text, reply_markup=reply_markup, parse_mode='Markdown')


async def show_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    balance = get_user_balance(user_id)
    menu_text = f"موجودی کیف پول شما: **{balance:,} تومان**\n\nمنوی اصلی:"
    keyboard = [
        [InlineKeyboardButton("🛍️ ثبت سفارش جدید", callback_data="new_order")],
        [InlineKeyboardButton(f"💰 کیف پول (شارژ)", callback_data="wallet")],
        [InlineKeyboardButton("✉️ ساخت جیمیل جدید (کسب اعتبار)", callback_data="new_gmail")],
        [InlineKeyboardButton("🧾 سفارش‌های من", callback_data="my_orders")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text=menu_text, reply_markup=reply_markup, parse_mode='Markdown')

def translate_status(status):
    translations = {'pending': "در انتظار تایید ⏳", 'processing': "در حال انجام ⚙️",
                    'approved': "انجام شده ✅", 'rejected': "رد شده ❌"}
    return translations.get(status, status)

# --- MAIN MENU CALLBACK HANDLER ---
async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "new_order":
        context.user_data['order'] = {}
        await query.edit_message_text(text="لطفا جیمیل خود را وارد کنید:")
        return EMAIL
    elif data == "my_orders":
        # Implementation for my_orders...
        await query.edit_message_text("این بخش در حال ساخت است...", reply_markup=back_to_menu_keyboard())
        return ConversationHandler.END
    elif data == "wallet":
        return await wallet_menu(update, context)
    elif data == "new_gmail":
        await query.edit_message_text("لطفا **آدرس جیمیل جدید** را وارد کنید:")
        return GET_GMAIL_ADDRESS
    elif data == "support":
        await query.edit_message_text("📞 برای پشتیبانی با ادمین در تماس باشید: @Admiin_gemini", reply_markup=back_to_menu_keyboard())
        return ConversationHandler.END

# --- WALLET & GMAIL HANDLERS ---
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    # await query.answer()
    user_id = query.from_user.id
    balance = get_user_balance(user_id)
    text = f"موجودی کیف پول: **{balance:,} تومان**\n\n"
    keyboard = [
        [InlineKeyboardButton("💳 شارژ کیف پول", callback_data="charge_wallet")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="show_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return GET_DEPOSIT_AMOUNT

async def ask_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفا مبلغ شارژ را به تومان وارد کنید (مثال: 50000):")
    return GET_DEPOSIT_AMOUNT

async def get_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = int(update.message.text)
        if amount <= 0: raise ValueError
        context.user_data['deposit_amount'] = amount
        payment_info = (f"برای شارژ کیف پول به مبلغ **{amount:,} تومان**، لطفا وجه را به کارت زیر واریز کرده و سپس **عکس رسید** را ارسال نمایید.\n\n"
                        f"`{CARD_NUMBER}`")
        await update.message.reply_text(payment_info, parse_mode='Markdown', reply_markup=cancel_keyboard)
        return UPLOAD_DEPOSIT_RECEIPT
    except (ValueError, TypeError):
        await update.message.reply_text("مبلغ نامعتبر است. لطفا یک عدد صحیح مثبت وارد کنید.")
        return GET_DEPOSIT_AMOUNT

async def upload_deposit_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    amount = context.user_data.pop('deposit_amount')
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    conn = sqlite3.connect('sales_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO wallet_deposits (user_id, amount, receipt_photo) VALUES (?, ?, ?)",
              (user.id, amount, sqlite3.Binary(photo_bytes)))
    deposit_id = c.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ رسید شما دریافت شد و پس از تایید ادمین، کیف پول شما شارژ خواهد شد.", reply_markup=ReplyKeyboardRemove())
    
    admin_caption = (f"💰 **درخواست شارژ کیف پول** (شماره: {deposit_id})\n\n"
                     f"**کاربر:** {user.first_name} (ID: {user.id})\n"
                     f"**مبلغ:** {amount:,} تومان")
    keyboard = [
        [InlineKeyboardButton(f"✅ تایید شارژ ({deposit_id})", callback_data=f"admin_approve_deposit_{deposit_id}")],
        [InlineKeyboardButton(f"❌ رد شارژ ({deposit_id})", callback_data=f"admin_reject_deposit_{deposit_id}")]
    ]
    await context.bot.send_photo(ADMIN_CHAT_ID, update.message.photo[-1].file_id,
                                 caption=admin_caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    await show_menu_message(update, context)
    return ConversationHandler.END

async def get_gmail_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    if not re.match(r"^[a-zA-Z0-9_.+-]+@gmail\.com$", email, re.IGNORECASE):
        await update.message.reply_text("❌ ایمیل نامعتبر است. لطفا یک آدرس جیمیل صحیح وارد کنید.")
        return GET_GMAIL_ADDRESS
    
    context.user_data['new_gmail'] = email
    await update.message.reply_text("✅ ایمیل دریافت شد. حالا **رمز عبور** آن را وارد کنید:")
    return GET_GMAIL_PASSWORD

async def get_gmail_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    password = update.message.text
    email = context.user_data.pop('new_gmail')
    
    conn = sqlite3.connect('sales_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO gmail_submissions (user_id, gmail_address, gmail_password) VALUES (?, ?, ?)",
              (user.id, email, password))
    submission_id = c.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ اطلاعات شما ثبت شد. پس از بررسی توسط ادمین، اعتبار به کیف پول شما اضافه خواهد شد.", reply_markup=ReplyKeyboardRemove())
    
    admin_caption = (f"✉️ **جیمیل جدید برای کسب اعتبار** (شماره: {submission_id})\n\n"
                     f"**کاربر:** {user.first_name} (ID: {user.id})\n"
                     f"**جیمیل:** `{email}`\n"
                     f"**رمزعبور:** `{password}`")
    keyboard = [
        [InlineKeyboardButton(f"✅ تایید جیمیل ({submission_id})", callback_data=f"admin_approve_gmail_{submission_id}")],
        [InlineKeyboardButton(f"❌ رد جیمیل ({submission_id})", callback_data=f"admin_reject_gmail_{submission_id}")]
    ]
    await context.bot.send_message(ADMIN_CHAT_ID, admin_caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    await show_menu_message(update, context)
    return ConversationHandler.END

# --- ORDER CONVERSATION ---
# Functions get_email, get_password, select_plan etc.
async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (no change)
    return PASSWORD

async def get_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (no change)
    return PLAN

async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    # ... (code to select plan) ...
    
    # Check wallet balance
    user_id = query.from_user.id
    balance = get_user_balance(user_id)
    final_price = context.user_data['order']['price']

    if balance >= final_price:
        keyboard = [
            [InlineKeyboardButton(f"✅ بله، پرداخت با کیف پول ({balance:,} تومان)", callback_data="pay_with_wallet")],
            [InlineKeyboardButton("💳 خیر، پرداخت با کارت", callback_data="pay_with_card")]
        ]
        text = f"مبلغ نهایی سفارش شما **{final_price:,} تومان** است.\nموجودی کیف پول شما کافی است. آیا مایل به پرداخت از کیف پول هستید؟"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return ASK_USE_WALLET
    elif balance > 0:
        remaining = final_price - balance
        keyboard = [
            [InlineKeyboardButton(f"✅ بله، استفاده از کیف پول (پرداخت {remaining:,})", callback_data="pay_with_wallet")],
            [InlineKeyboardButton("💳 خیر، پرداخت کامل با کارت", callback_data="pay_with_card")]
        ]
        text = (f"مبلغ نهایی سفارش شما **{final_price:,} تومان** است.\n"
                f"شما **{balance:,} تومان** در کیف پول خود دارید. آیا مایلید از آن استفاده کرده و مابقی را با کارت پرداخت کنید؟")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return ASK_USE_WALLET
    else: # balance is zero
        return await show_payment_info(update, context)

async def handle_payment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "pay_with_card":
        return await show_payment_info(update, context)

    # Pay with wallet
    user_id = query.from_user.id
    balance = get_user_balance(user_id)
    order_data = context.user_data['order']
    final_price = order_data['price']

    if balance >= final_price:
        new_balance = balance - final_price
        
        # Update user balance
        conn = sqlite3.connect('sales_bot.db')
        c = conn.cursor()
        c.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?", (new_balance, user_id))
        # Save order directly as 'processing' since it's paid
        c.execute('''
            INSERT INTO orders (user_id, email, password, plan, price, status)
            VALUES (?, ?, ?, ?, ?, 'processing') 
        ''', (user_id, order_data['email'], order_data['password'], order_data['plan'], final_price))
        new_order_id = c.lastrowid
        conn.commit()
        conn.close()

        await query.edit_message_text(f"✅ پرداخت با موفقیت از کیف پول شما کسر شد.\nسفارش شما (شماره: {new_order_id}) ثبت و در حال انجام است.",
                                      reply_markup=back_to_menu_keyboard(), parse_mode='Markdown')
        
        # Notify Admin
        admin_message = (f"🔔 **سفارش جدید (پرداخت از کیف پول)** (شماره: {new_order_id})\n\n"
                         # ... admin message details ...
                         )
        await context.bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode='Markdown')
        
        context.user_data.clear()
        return ConversationHandler.END
    else: # Partial payment
        context.user_data['order']['using_wallet'] = True
        return await show_payment_info(update, context)

async def show_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE, is_message: bool = False) -> int:
    order_data = context.user_data['order']
    price_to_pay = order_data['price']
    
    if order_data.get('using_wallet'):
        balance = get_user_balance(update.effective_user.id)
        price_to_pay -= balance

    # ... (show payment info for price_to_pay) ...
    return CONFIRM_PAYMENT


async def upload_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ...
    # if order_data.get('using_wallet'):
    #     balance = get_user_balance(user.id)
    #     # Deduct balance from DB
    #     conn = sqlite3.connect('sales_bot.db')
    #     c = conn.cursor()
    #     c.execute("UPDATE users SET wallet_balance = 0 WHERE user_id = ?", (user.id,))
    #     conn.commit()
    #     conn.close()
    # ...
    return ConversationHandler.END
    
# --- ADMIN CALLBACK ---
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    conn = sqlite3.connect('sales_bot.db')
    c = conn.cursor()

    try:
        if data.startswith("admin_approve_deposit_"):
            deposit_id = int(data.split("_")[-1])
            c.execute("SELECT user_id, amount FROM wallet_deposits WHERE deposit_id = ?", (deposit_id,))
            res = c.fetchone()
            if res:
                user_id, amount = res
                c.execute("UPDATE wallet_deposits SET status = 'approved' WHERE deposit_id = ?", (deposit_id,))
                c.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id = ?", (amount, user_id))
                conn.commit()
                new_balance = get_user_balance(user_id)
                await context.bot.send_message(user_id, f"✅ درخواست شارژ کیف پول شما به مبلغ **{amount:,} تومان** تایید شد.\nموجودی جدید: **{new_balance:,} تومان**", parse_mode='Markdown')
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n-- ✅ تایید شد --", parse_mode='Markdown')

        elif data.startswith("admin_reject_deposit_"):
            # ... reject deposit logic
            pass
            
        elif data.startswith("admin_approve_gmail_"):
            submission_id = int(data.split("_")[-1])
            c.execute("SELECT user_id, gmail_address FROM gmail_submissions WHERE submission_id = ?", (submission_id,))
            res = c.fetchone()
            if res:
                user_id, gmail = res
                c.execute("UPDATE gmail_submissions SET status = 'approved' WHERE submission_id = ?", (submission_id,))
                c.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id = ?", (GMAIL_CREDIT, user_id))
                conn.commit()
                new_balance = get_user_balance(user_id)
                await context.bot.send_message(user_id, f"✅ جیمیل ارسالی شما ({gmail}) تایید شد و **{GMAIL_CREDIT:,} تومان** به کیف پول شما اضافه شد.\nموجودی جدید: **{new_balance:,} تومان**", parse_mode='Markdown')
                await query.edit_message_text(text=f"{query.message.text}\n\n-- ✅ تایید شد --", parse_mode='Markdown')

        elif data.startswith("admin_reject_gmail_"):
            # ... reject gmail logic
            pass
        else: # Handle order approvals
             order_id = int(data.split("_")[-1])
             # ... existing order approval logic
             pass

    except Exception as e:
        logger.error(f"Error in admin_callback: {e}")
    finally:
        conn.close()

# --- MAIN FUNCTION ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Define Conversation Handlers
    order_conv = ConversationHandler(entry_points=[], states={}, fallbacks=[]) # Fill this
    wallet_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(wallet_menu, pattern="^wallet$")],
        states={
            GET_DEPOSIT_AMOUNT: [
                CallbackQueryHandler(ask_deposit_amount, pattern="^charge_wallet$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_deposit_amount)
            ],
            UPLOAD_DEPOSIT_RECEIPT: [MessageHandler(filters.PHOTO, upload_deposit_receipt)],
        },
        fallbacks=[MessageHandler(filters.Text("لغو ❌"), cancel), CallbackQueryHandler(show_menu, pattern="^show_menu$")]
    )
    gmail_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback_handler, pattern="^new_gmail$")],
        states={
            GET_GMAIL_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gmail_address)],
            GET_GMAIL_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gmail_password)],
        },
        fallbacks=[MessageHandler(filters.Text("لغو ❌"), cancel)]
    )
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_menu, pattern="^show_menu$"))
    app.add_handler(MessageHandler(filters.Text("🔙 بازگشت به منو اصلی"), show_menu_message))
    app.add_handler(order_conv)
    app.add_handler(wallet_conv)
    app.add_handler(gmail_conv)
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    # ... other handlers ...

    print("✅ Bot started and polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
