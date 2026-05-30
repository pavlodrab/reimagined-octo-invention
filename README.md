# Chelsea Voting Bot

A Telegram bot with a Mini App for voting on Chelsea players' performance after matches.

## Features

- Vote for players using a unique rating scale (0 to N, where N is configurable).
- Each user must assign distinct ratings to all players in a match.
- Results are aggregated and displayed as average ratings.
- Admin panel to configure voting period, rating scale, match selection, and more.
- Personal and global background customization.
- Built with Python (Flask for backend/API, python-telegram-bot for the Telegram bot).
- Data stored in SQLite.

## Project Structure

- `app.py` - Flask backend API serving the Mini App and providing endpoints.
- `bot.py` - Telegram bot that serves as an entry point to launch the Mini App.
- `db.py` - Database layer (SQLite).
- `miniapp/` - Frontend Mini App (HTML, CSS, JS).
- `requirements.txt` - Python dependencies.

## Setup

1. **Clone the repository** (or copy the files).

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate   # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set environment variables** (create a `.env` file or export them):
   - `TELEGRAM_TOKEN`: Your Telegram bot token from @BotFather.
   - `MINI_APP_URL`: The public HTTPS URL where the Mini App will be hosted (e.g., `https://yourdomain.com`). 
     For local testing you can use a tool like [ngrok](https://ngrok.com/) to expose port 5000.
   - `OWNER_ID`: Your Telegram user ID (to enable admin commands). Get it from @userinfobot.
   - `SSTATS_TOKEN`: API token for sstats.net (optional, can be set via admin panel).
   - `PORT`: Port to run the Flask app on (default: 5000).

   Example `.env` file:
   ```
   TELEGRAM_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
   MINI_APP_URL=https://your-domain.com
   OWNER_ID=123456789
   SSTATS_TOKEN=your_sstats_token_here
   PORT=5000
   ```

5. **Initialize the database** (done automatically on first run).

## Running the Application

### Option 1: Run both backend and bot in separate terminals

**Terminal 1: Start the Flask backend**
```bash
source venv/bin/activate
export FLASK_APP=app.py
export FLASK_ENV=development
flask run --host=0.0.0.0 --port=5000
```
   Or simply:
   ```bash
   source venv/bin/activate
   python app.py
   ```

**Terminal 2: Start the Telegram bot**
```bash
source venv/bin/activate
python bot.py
```

### Option 2: Run using Docker (not provided, but you can create a Dockerfile).

## Usage

1. Start a chat with your bot in Telegram.
2. Send `/start` to receive a button to open the Mini App.
3. Press the button to launch the Mini App (must be accessed via HTTPS in Telegram).
4. In the Mini App:
   - Vote for players on the "Vote" tab.
   - View other votes, your profile, and adjust settings.
5. Admins can access the admin panel (if OWNER_ID is set) to configure the bot.

## Notes

- The Mini App must be served over HTTPS for Telegram to load it. For development, use ngrok or similar to expose your local Flask server.
- The bot uses the `web_app` feature of Telegram Bot API, which requires the bot to be in a group or private chat with the Mini App URL set.
- The default voting period is 24 hours, after which average ratings are computed (though the current implementation does not automatically post results; this can be added via a background job).
- The sstats.net API integration is implemented with caching; replace mock data with real API calls when a valid token is provided.

## License

MIT
