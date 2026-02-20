import sys
from telethon import TelegramClient, events

from config.settings import TELEGRAM_API_HASH, TELEGRAM_API_ID, TELEGRAM_CHANNELS


class TelegramSignalClient:
    def __init__(self, on_signal_callback):
        self.on_signal_callback = on_signal_callback
        self.client = TelegramClient("telegram_session", TELEGRAM_API_ID, TELEGRAM_API_HASH)

    @staticmethod
    def _blocking_input(prompt: str) -> str:
        return input(prompt)

    async def start(self):
        if not TELEGRAM_CHANNELS:
            print("❌ TELEGRAM_CHANNELS is empty. Configure at least one channel in .env")
            sys.exit(1)

        try:
            await self.client.start(
                phone=lambda: self._blocking_input("📱 Enter your phone number: "),
                code_callback=lambda: self._blocking_input("🔑 Enter the OTP code: "),
                password=lambda: self._blocking_input("🔐 Enter 2FA password (or press Enter): "),
            )
        except Exception as exc:
            print(f"❌ Authentication failed: {exc}")
            sys.exit(1)

        entities = []
        for channel in TELEGRAM_CHANNELS:
            try:
                entity = await self.client.get_entity(channel)
                entities.append(entity)
                print(f"✅ Watching channel: {getattr(entity, 'title', channel)}")
            except Exception as exc:
                print(f"⚠️  Cannot watch '{channel}': {exc}")

        if not entities:
            print("❌ No valid Telegram channels resolved. Exiting.")
            sys.exit(1)

        @self.client.on(events.NewMessage(chats=entities))
        async def handler(event):
            try:
                print(f"📩 Signal received:\n{event.raw_text}\n")
                await self.on_signal_callback(event.raw_text)
            except Exception as exc:
                print(f"⚠️  Handler error: {exc}")

        print("📡 Listening for signals … (Ctrl+C to stop)\n")
        await self.client.run_until_disconnected()
