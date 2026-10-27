# Telegram to Supabase Auto-Importer

This project is a worker application built with FastAPI, Telethon, and asyncpg. It automatically fetches posts (videos, images, text, and links) from a Telegram Channel or Bot and inserts them directly into a Supabase PostgreSQL database. Media files are seamlessly uploaded to Supabase Storage.

## Features
- **Multi-format Support:** Handles text, images, short videos (reels), and long videos.
- **Link Extraction:** Automatically detects URLs in posts and saves them directly to the database while keeping the main description clean.
- **AI Integration (Optional):** Uses OpenAI-compatible endpoints (like Google Gemini) to rewrite text naturally and extract smart hashtags.
- **Deduplication:** Prevents duplicate posts using a state tracking table.
- **Dual Modes:** Works as a Telegram Bot or as a regular User (User-mode).

## Prerequisites

1. **Python 3.10+**
2. **Telegram API Credentials:** Get your `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org).
3. **Telegram Bot Token:** (Optional, but recommended) from [@BotFather](https://t.me/botfather).
4. **Supabase Project:** You need an active Supabase project with Database and Storage enabled.

## Installation

1. Clone this repository to your local machine:
   ```bash
   git clone <your-repo-url>
   cd <your-repo-folder>
   ```

2. Install the required Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Setup Instructions

### 1. Database Setup
Run the SQL queries in your Supabase SQL Editor to prepare your database:
- **For a fresh project:** Run the contents of `test_setup.sql`.
- **For an existing project:** Run the contents of `schema.sql` to add the required `telegram_imports` tracking table.

### 2. Environment Variables
Create a `.env` file in the root directory. You can use `.env.example` as a reference.

```env
# ---- Telegram ----
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash
TG_SESSION=           # (Only if tracking a channel via User mode. See Step 3)
TG_BOT_TOKEN=your_bot_token

# Define where to read from. "author_id" MUST exist in your public.profiles table!
TG_SOURCES=[{"via":"bot","author_id":"your-author-uuid","allowed_senders":[123456789],"ai_rewrite":false},{"chat":"@your_channel_username","author_id":"your-author-uuid","ai_rewrite":false}]

# ---- Supabase ----
DATABASE_URL=postgresql://postgres.xxxx:PASSWORD@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres
SUPABASE_URL=https://YOUR-PROJECT-REF.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
SUPABASE_BUCKET=media

# ---- Behaviour ----
DRY_RUN=false           # true = test mode (logs only), false = save to DB
MAX_UPLOAD_MB=50        
BACKFILL_LIMIT=0        
CONTENT_SOURCE_VALUE=external

# ---- AI (optional) ----
AI_API_KEY=your_ai_api_key
AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
AI_MODEL=gemini-2.5-flash
```

### 3. Generate Telegram Session (For User Mode Only)
If your bot isn't an admin in the channel you want to monitor, you must use a user session. Run this script locally and follow the terminal prompts (you will need to enter your phone number and OTP):

```bash
python make_session.py
```
Copy the generated session string and paste it into the `TG_SESSION` variable in your `.env` file. **Keep this string secret!**

### 4. Running the Application
Start the worker application locally using Uvicorn:

```bash
uvicorn main:app --host 0.0.0.0 --port 10000
```

To verify the app is running smoothly, visit the health check endpoint in your browser:
`http://localhost:10000/health`

## Deployment (Render)

This project is optimized for deployment on Render as a Web Service.

1. Connect your GitHub repository to Render and create a new **Web Service**.
2. **Build Command:** `pip install -r requirements.txt`
3. **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Go to the "Environment" tab in Render and add all the variables from your `.env` file.
5. Save and Deploy!
