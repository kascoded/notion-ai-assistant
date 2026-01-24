"""
Telegram Bot Interface for Notion Assistant.

Provides a Telegram bot that accepts natural language inputs
and routes them through the NotionAssistant agent.

Environment Variables:
    TELEGRAM_BOT_TOKEN: Bot token from @BotFather
    TELEGRAM_ALLOWED_USERS: Comma-separated list of allowed user IDs (optional)
    WEBHOOK_URL: The public URL of the application (for webhooks)
    PORT: The port to listen on (for webhooks, provided by Railway)

Usage:
    # Run directly
    python -m src.notion_assistant.interfaces.telegram_bot
    
    # Or import and run
    from src.notion_assistant.interfaces.telegram_bot import run_bot
    run_bot()
"""
import os
import asyncio
import logging
from typing import Optional, Set
from functools import wraps

from dotenv import load_dotenv

# Telegram imports
try:
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ContextTypes,
        filters,
    )
except ImportError:
    raise ImportError(
        "python-telegram-bot not installed. Run: uv add python-telegram-bot"
    )

from src.notion_assistant.agent import NotionAssistant

load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TelegramNotionBot:
    """
    Telegram bot wrapper for NotionAssistant.
    
    Features:
    - Natural language processing via NotionAssistant
    - User allowlist for security
    - Typing indicators for better UX
    - Command handlers for common operations
    
    Attributes:
        assistant: The NotionAssistant instance
        allowed_users: Set of allowed Telegram user IDs (None = allow all)
    """
    
    def __init__(
        self,
        token: Optional[str] = None,
        allowed_users: Optional[Set[int]] = None,
    ):
        """
        Initialize the Telegram bot.
        
        Args:
            token: Telegram bot token (or set TELEGRAM_BOT_TOKEN env var)
            allowed_users: Set of allowed user IDs (or set TELEGRAM_ALLOWED_USERS env var)
        """
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError(
                "Telegram bot token required. Set TELEGRAM_BOT_TOKEN env var "
                "or pass token= to TelegramNotionBot()"
            )
        
        # Parse allowed users from env if not provided
        if allowed_users is None:
            allowed_env = os.getenv("TELEGRAM_ALLOWED_USERS", "")
            if allowed_env.strip():
                self.allowed_users = {
                    int(uid.strip()) 
                    for uid in allowed_env.split(",") 
                    if uid.strip()
                }
            else:
                self.allowed_users = None  # Allow all users
        else:
            self.allowed_users = allowed_users
        
        self.assistant = NotionAssistant()
        self._initialized = False
    
    def _check_user(self, user_id: int) -> bool:
        """Check if user is allowed to use the bot."""
        if self.allowed_users is None:
            return True
        return user_id in self.allowed_users
    
    def authorized(self, func):
        """Decorator to check user authorization."""
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            if not self._check_user(user_id):
                logger.warning(f"Unauthorized access attempt from user {user_id}")
                await update.message.reply_text(
                    "⛔ Sorry, you're not authorized to use this bot.\n\n"
                    f"Your user ID: `{user_id}`",
                    parse_mode="Markdown"
                )
                return
            return await func(update, context)
        return wrapper
    
    async def _ensure_initialized(self):
        """Ensure the assistant is initialized."""
        if not self._initialized:
            # In a webhook environment, initialization might need to be handled differently
            # For now, we assume it's quick enough to happen on the first request.
            # A more robust solution might involve a startup task.
            logger.info("Performing first-time initialization of assistant...")
            await self.assistant.initialize()
            self._initialized = True
    
    # ========================================
    # Command Handlers
    # ========================================
    
    @authorized
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user = update.effective_user
        await self._ensure_initialized()
        
        # Get available databases
        db_list = ", ".join(self.assistant.available_databases[:5])
        if len(self.assistant.available_databases) > 5:
            db_list += f" (+{len(self.assistant.available_databases) - 5} more)"
        
        await update.message.reply_text(
            f"👋 Hi {user.first_name}!\n\n"
            "I'm your Notion Assistant. Send me natural language messages "
            "and I'll help you manage your Notion workspace.\n\n"
            "**Available databases:**\n"
            f"`{db_list}`\n\n"
            "**Example commands:**\n"
            "• Create a note about FastMCP with tags python, mcp\n"
            "• Search for notes about machine learning\n"
            "• Ate breakfast, did 30 min cardio, finished task\n\n"
            "**Commands:**\n"
            "/help - Show this message\n"
            "/databases - List all databases\n"
            "/status - Check connection status",
            parse_mode="Markdown"
        )
    
    @authorized
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await update.message.reply_text(
            "📚 **Notion Assistant Help**\n\n"
            "Just send me natural language messages describing what you want to do. "
            "I support multi-intent parsing, so you can combine multiple actions!\n\n"
            "**Examples:**\n"
            "• `Create a note about X with tags Y, Z`\n"
            "• `Search for notes about machine learning`\n"
            "• `Ate breakfast, did cardio, finished project`\n"
            "• `Log 8 hours of sleep and 2000 calories`\n\n"
            "**Commands:**\n"
            "/start - Welcome message\n"
            "/help - This help message\n"
            "/databases - List available databases\n"
            "/status - Check system status\n"
            "/refresh - Refresh database schemas",
            parse_mode="Markdown"
        )

    @authorized
    async def databases_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /databases command."""
        await self._ensure_initialized()
        
        databases = self.assistant.available_databases
        if not databases:
            await update.message.reply_text("❌ No databases found.")
            return
        
        db_list = "\n".join(f"• `{db}`" for db in databases)
        await update.message.reply_text(
            f"📊 **Available Databases ({len(databases)})**\n\n{db_list}",
            parse_mode="Markdown"
        )

    @authorized
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        status_parts = [
            "🔧 **System Status**\n",
            f"• Assistant initialized: {'✅' if self._initialized else '❌'}",
        ]
        if self._initialized:
             status_parts.append(f"• Databases loaded: {len(self.assistant.available_databases)}")

        await update.message.reply_text(
            "\n".join(status_parts),
            parse_mode="Markdown"
        )

    @authorized
    async def refresh_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /refresh command to refresh schemas."""
        await update.message.reply_text("🔄 Refreshing database schemas...")
        
        try:
            await self.assistant.refresh_schemas()
            await update.message.reply_text(
                f"✅ Schemas refreshed!\n"
                f"Loaded {len(self.assistant.available_databases)} databases."
            )
        except Exception as e:
            logger.error(f"Failed to refresh schemas: {e}")
            await update.message.reply_text(f"❌ Failed to refresh: {e}")
    
    # ========================================
    # Message Handler
    # ========================================
    
    @authorized
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle natural language messages."""
        user_input = update.message.text.strip()
        if not user_input:
            return
        
        logger.info(f"Processing message from {update.effective_user.id}: {user_input[:50]}...")
        
        await update.message.chat.send_action("typing")
        
        try:
            await self._ensure_initialized()
            response = await self.assistant.process(user_input)
            
            if len(response) > 4000:
                chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(response)
        
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ Sorry, something went wrong:\n\n`{str(e)[:200]}`",
                parse_mode="Markdown"
            )
    
    # ========================================
    # Error Handler
    # ========================================
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors in the bot."""
        logger.error(f"Update {update} caused error: {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An unexpected error occurred. Please try again."
            )
    
    # ========================================
    # Run Bot
    # ========================================
    
    def build_application(self) -> Application:
        """Build the Telegram application with handlers."""
        app = Application.builder().token(self.token).build()
        
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("databases", self.databases_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(CommandHandler("refresh", self.refresh_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        app.add_error_handler(self.error_handler)
        
        return app
    
    def run_polling(self):
        """Run the bot with polling (for local development)."""
        logger.info("Starting bot with polling...")
        app = self.build_application()
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Bot stopped.")

    def run_webhook(self):
        """Run the bot with a webhook (for production)."""
        port_str = os.getenv("PORT")
        webhook_url = os.getenv("WEBHOOK_URL")

        if not port_str:
            raise ValueError("PORT environment variable not set.")
        if not webhook_url:
            raise ValueError("WEBHOOK_URL environment variable not set.")
        
        port = int(port_str)
        
        logger.info(f"Starting bot with webhook on port {port}...")
        app = self.build_application()

        # Using the bot token as the secret URL path is a common practice
        url_path = self.token

        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=url_path,
            webhook_url=f"{webhook_url}/{url_path}"
        )
        logger.info("Bot started successfully with webhook.")

# ========================================
# Standalone Functions
# ========================================

def run_bot():
    """
    Run the bot.
    Determines whether to use polling or webhook based on environment.
    """
    bot = TelegramNotionBot()
    
    # Use webhook if PORT and WEBHOOK_URL are set (like on Railway)
    if os.getenv("PORT") and os.getenv("WEBHOOK_URL"):
        bot.run_webhook()
    else:
        # Fallback to polling for local development
        logger.warning("PORT/WEBHOOK_URL not set, falling back to polling.")
        bot.run_polling()


# ========================================
# Main Entry Point
# ========================================

if __name__ == "__main__":
    run_bot()
