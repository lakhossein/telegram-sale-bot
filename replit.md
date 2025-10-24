# Persian Telegram Sales Bot

## Overview
This is a Persian-language Telegram bot designed for managing product subscriptions and orders. The bot allows customers to purchase subscription plans, submit payment receipts, and track their orders. Admins receive notifications of new orders and can approve or reject them.

## Project Architecture
- **Language**: Python 3.11
- **Framework**: python-telegram-bot (v21.4)
- **Database**: SQLite (sales_bot.db)
- **Bot Type**: Backend service (no frontend)

## Features
- 🛍️ New order registration with email and password collection
- 💰 Multiple subscription plans (1-month, 3-month, 6-month, 1-year)
- 🖼️ Payment receipt upload and verification
- 👨‍💼 Admin panel for order management
- 📊 Order tracking and status updates
- 🔔 Admin notifications for new orders

## Setup & Configuration

### Required Environment Variables (Secrets)
These are configured in Replit Secrets:
- **BOT_TOKEN**: Your Telegram Bot API token from @BotFather
- **ADMIN_CHAT_ID**: Telegram user ID for admin notifications
- **CARD_NUMBER**: Bank card number for payments

### Optional Environment Variables
- **PLANS**: Custom pricing plans (default: یک ماهه:199000,سه ماهه:490000,شش ماهه:870000,یک ساله:1470000)

## Database Schema

### Users Table
- user_id (PRIMARY KEY)
- chat_id (UNIQUE)
- username
- first_name
- last_name

### Orders Table
- order_id (AUTO INCREMENT, starts from 16800)
- user_id (FOREIGN KEY)
- email
- password
- plan
- price
- receipt_photo (BLOB)
- status (pending/processing/approved/rejected)
- created_at

## Order Flow
1. Customer starts the bot with /start
2. Selects "ثبت سفارش جدید" (New Order)
3. Provides Gmail address
4. Provides password
5. Selects subscription plan
6. Views payment information with card number
7. Uploads payment receipt
8. Admin receives notification with receipt
9. Admin approves/rejects order
10. Customer receives status update

## Admin Commands
- `/pending` - List all pending orders awaiting receipt approval
- `/processing` - List orders in processing (receipt approved, awaiting completion)
- `/approved` - List last 10 approved/completed orders

## Current State
- ✅ Python 3.11 installed
- ✅ Dependencies installed (python-telegram-bot==21.4)
- ✅ Environment variables configured
- ✅ Database auto-initialization on startup
- ✅ Bot running and polling for messages

## Running the Bot
The bot runs automatically via the "Telegram Bot" workflow. It connects to Telegram's servers and polls for updates continuously.

## Recent Changes
- **2025-10-24**: Initial import from GitHub
  - Removed Colab-specific pip install line
  - Migrated hardcoded credentials to Replit Secrets
  - Added .gitignore for Python and database files
  - Configured workflow to run bot as console application
  - Fixed environment variable handling (strip quotes)

## Notes
- The bot uses Persian (Farsi) language for all user interactions
- Order IDs start from 16800 by default
- Receipt photos are stored as BLOBs in the database
- The bot uses SQLite for data persistence
