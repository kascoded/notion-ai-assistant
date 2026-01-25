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


def _require_authorization(func):
    """Decorator to check user authorization on a class method."""
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # 'self' is the instance of TelegramNotionBot
        user_id = update.effective_user.id
        if not self._check_user(user_id):
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            await update.message.reply_text(
                "⛔ Sorry, you're not authorized to use this bot."
            )
            return
        return await func(self, update, context)
    return wrapper


class TelegramNotionBot:
    """
    Telegram bot wrapper for NotionAssistant.
    """
    
    def __init__(
        self,
        token: Optional[str] = None,
        allowed_users: Optional[Set[int]] = None,
    ):
        """
        Initialize the Telegram bot.
        """
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError(
                "Telegram bot token required. Set TELEGRAM_BOT_TOKEN env var."
            )
        
        if allowed_users is None:
            allowed_env = os.getenv("TELEGRAM_ALLOWED_USERS", "")
            self.allowed_users = {int(uid.strip()) for uid in allowed_env.split(",") if uid.strip()} if allowed_env else None
        else:
            self.allowed_users = allowed_users
        
        self.assistant = NotionAssistant()
        self._initialized = False
    
    def _check_user(self, user_id: int) -> bool:
        """Check if user is allowed to use the bot."""
        if self.allowed_users is None:
            return True
        return user_id in self.allowed_users
    
    async def _ensure_initialized(self):
        """Ensure the assistant is initialized."""
        if not self._initialized:
            logger.info("Performing first-time initialization of assistant...")
            # In a webhook setup, you might move this to a startup hook
            await self.assistant.initialize()
            self._initialized = True
    
    # ========================================
    # Command Handlers
    # ========================================
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user = update.effective_user
        if not self._check_user(user.id):
            await update.message.reply_text(
                f"⛔ Sorry, you're not authorized to use this bot.\n\n"
                f"Your user ID: `{user.id}`\n\n"
                "Ask the admin to add your ID to the allowlist.",
                parse_mode="Markdown"
            )
            return

        await self._ensure_initialized()
        
        db_list = ", ".join(self.assistant.available_databases[:5])
        if len(self.assistant.available_databases) > 5:
            db_list += f" (+{len(self.assistant.available_databases) - 5} more)"
        
        controls_count = len(self.assistant.controls_loader.controls) if self.assistant.controls_loader else 0
        
        await update.message.reply_text(
            f"👋 Hi {user.first_name}!\n\n"
            "I'm your Notion Assistant. Send me natural language messages to manage your Notion workspace.\n\n"
            f"**Databases:** `{db_list}`\n"
            f"**AI Controls:** {controls_count} active\n\n"
            "**Examples:**\n"
            "• Create a note about FastMCP with tags python, mcp\n"
            "• Ate breakfast, did 30 min cardio, finished task\n"
            "• Search for notes about machine learning\n\n"
            "Use /help to see all commands.",
            parse_mode="Markdown"
        )
    
    @_require_authorization
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await update.message.reply_text(
            "📚 **Notion Assistant Help**\n\n"
            "Just send me natural language messages describing what you want to do.\n\n"
            "**Examples:**\n"
            "• `Create a note about X with tags Y, Z`\n"
            "• `Search for notes about machine learning`\n"
            "• `Ate breakfast, did cardio, finished project`\n\n"
            "**Commands:**\n"
            "/start - Welcome message\n"
            "/help - This help message\n"
            "/databases - List available databases\n"
            "/status - Check system status\n"
            "/refresh - Reload everything (slow)\n"
            "/refresh_controls - Reload AI controls only (fast)\n"
            "/refresh_schemas - Reload database schemas only\n"
            "/preview `<text>` - Preview which controls load for input\n\n"
            "_Tip: Edit AI controls in Notion, then use /refresh_controls!_",
            parse_mode="Markdown"
        )

    @_require_authorization
    async def databases_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /databases command."""
        await self._ensure_initialized()
        databases = self.assistant.available_databases
        db_list = "\n".join(f"• `{db}`" for db in databases) if databases else "No databases found."
        await update.message.reply_text(
            f"📊 **Available Databases ({len(databases)})**\n\n{db_list}",
            parse_mode="Markdown"
        )

    @_require_authorization
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        status_parts = [
            "🔧 **System Status**\n",
            f"• Assistant initialized: {'✅' if self._initialized else '❌'}",
        ]
        if self._initialized:
            status_parts.append(f"• Databases loaded: {len(self.assistant.available_databases)}")
            if self.assistant.controls_loader:
                stats = self.assistant.controls_loader.get_stats()
                status_parts.append(f"• AI Controls: {stats['total']} ({stats['global']} global, {stats['specific']} specific)")
        await update.message.reply_text("\n".join(status_parts), parse_mode="Markdown")

    @_require_authorization
    async def refresh_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /refresh command to refresh both schemas and controls."""
        await update.message.reply_text("🔄 Refreshing everything... (this may take a moment)")
        try:
            await self.assistant.refresh_all()
            
            db_count = len(self.assistant.available_databases)
            controls_count = len(self.assistant.controls_loader.controls) if self.assistant.controls_loader else 0
            
            await update.message.reply_text(
                f"✅ Refreshed!\n\n"
                f"• Databases: {db_count}\n"
                f"• AI Controls: {controls_count}"
            )
        except Exception as e:
            logger.error(f"Failed to refresh: {e}")
            await update.message.reply_text(f"❌ Failed to refresh: {e}")

    @_require_authorization
    async def refresh_controls_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /refresh_controls command to refresh AI controls only."""
        await update.message.reply_text("🔄 Refreshing AI controls...")
        try:
            await self.assistant.refresh_controls()
            
            controls_count = len(self.assistant.controls_loader.controls) if self.assistant.controls_loader else 0
            
            await update.message.reply_text(
                f"✅ Controls refreshed!\n\n"
                f"• AI Controls: {controls_count}"
            )
        except Exception as e:
            logger.error(f"Failed to refresh controls: {e}")
            await update.message.reply_text(f"❌ Failed to refresh: {e}")

    @_require_authorization
    async def refresh_schemas_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /refresh_schemas command to refresh database schemas."""
        await update.message.reply_text("🔄 Refreshing database schemas... (this may take a moment)")
        try:
            await self.assistant.refresh_schemas()
            
            db_count = len(self.assistant.available_databases)
            
            await update.message.reply_text(
                f"✅ Schemas refreshed!\n\n"
                f"• Databases: {db_count}"
            )
        except Exception as e:
            logger.error(f"Failed to refresh schemas: {e}")
            await update.message.reply_text(f"❌ Failed to refresh: {e}")

    @_require_authorization
    async def preview_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /preview command to show which controls would be loaded for an input."""
        # Get the text after /preview
        if context.args:
            test_input = " ".join(context.args)
        else:
            await update.message.reply_text(
                "🔍 **Preview Control Loading**\n\n"
                "Usage: `/preview <your test input>`\n\n"
                "Example: `/preview ate eggs and did my workout`\n\n"
                "This shows which AI controls would be included for a given input.",
                parse_mode="Markdown"
            )
            return
        
        await self._ensure_initialized()
        
        if not self.assistant.controls_loader:
            await update.message.reply_text("❌ Controls loader not initialized")
            return
        
        preview = self.assistant.controls_loader.preview_for_input(test_input)
        
        # Format response
        included = preview['controls_included']
        excluded = preview['controls_excluded']
        
        included_lines = []
        for c in included:
            if c['is_global']:
                included_lines.append(f"  • {c['name']} [global]")
            else:
                targets = ', '.join(c['targets'])
                included_lines.append(f"  • {c['name']} [{targets}]")
        included_list = "\n".join(included_lines) or "  (none)"
        
        excluded_lines = []
        for c in excluded:
            targets = ', '.join(c['targets'])
            excluded_lines.append(f"  • {c['name']} [{targets}]")
        excluded_list = "\n".join(excluded_lines) or "  (none)"
        
        await update.message.reply_text(
            f"🔍 **Control Loading Preview**\n\n"
            f"**Input:** `{test_input}`\n\n"
            f"**Detected databases:** {', '.join(preview['detected_databases']) or 'none'}\n\n"
            f"**Included ({len(included)}):**\n{included_list}\n\n"
            f"**Excluded ({len(excluded)}):**\n{excluded_list}\n\n"
            f"**Prompt size:** ~{preview['total_chars']} chars",
            parse_mode="Markdown"
        )
    
    # ========================================
    # Message Handler
    # ========================================
    
    @_require_authorization
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle natural language messages."""
        user_input = update.message.text.strip()
        if not user_input: return

        logger.info(f"Processing message from {update.effective_user.id}: {user_input[:50]}...")
        await update.message.chat.send_action("typing")
        
        try:
            await self._ensure_initialized()
            response = await self.assistant.process(user_input)
            
            for i in range(0, len(response), 4000):
                await update.message.reply_text(response[i:i+4000])
        
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ Sorry, something went wrong:\n\n`{str(e)[:200]}`",
                parse_mode="Markdown"
            )
    
    # ========================================
    # Error Handler
    # ========================================
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Log Errors caused by Updates."""
        logger.error(f"Update {update} caused error {context.error}")
    
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
        app.add_handler(CommandHandler("refresh_controls", self.refresh_controls_command))
        app.add_handler(CommandHandler("refresh_schemas", self.refresh_schemas_command))
        app.add_handler(CommandHandler("preview", self.preview_command))
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

        if not port_str: raise ValueError("PORT environment variable not set.")
        if not webhook_url: raise ValueError("WEBHOOK_URL environment variable not set.")
        
        port = int(port_str)
        
        logger.info(f"Starting bot with webhook on port {port}...")
        app = self.build_application()
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
    """Run the bot, choosing mode based on environment."""
    bot = TelegramNotionBot()
    if os.getenv("PORT") and os.getenv("WEBHOOK_URL"):
        bot.run_webhook()
    else:
        logger.warning("PORT/WEBHOOK_URL not set, falling back to polling.")
        bot.run_polling()

# ========================================
# Main Entry Point
# ========================================

if __name__ == "__main__":
    run_bot()
