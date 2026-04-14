import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp_socks import ProxyConnector
from gigachat import GigaChat
from dotenv import load_dotenv

# 1. Загружаем настройки
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
PROXY_URL = os.getenv("PROXY_URL") # Проверь, что в .env есть эта строка!
MY_ID = int(os.getenv("MY_ID"))

# 2. Инициализируем GigaChat (работает напрямую без прокси)
giga = GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False)

dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет! Я GigaChef. Пришли ингредиенты, и я предложу рецепт!")

@dp.message()
async def handle_message(message: types.Message):
    await message.bot.send_chat_action(message.chat.id, action="typing")
    try:
        # Запрос к GigaChat
        response = giga.chat(f"Напиши пошаговый рецепт из этих продуктов: {message.text}")
        await message.answer(response.choices[0].message.content)
    except Exception as e:
        await message.answer(f"Ошибка ИИ: {e}")

async def main():
    # Настраиваем прокси ТОЛЬКО для Telegram
    if not PROXY_URL:
        print("Ошибка: PROXY_URL не найден в .env!")
        return

    connector = ProxyConnector.from_url(PROXY_URL)
    session = AiohttpSession()
    session._connector = connector 
    
    bot = Bot(token=BOT_TOKEN, session=session)

    # Очищаем очередь обновлений (решает проблему Conflict со скрина image_530393)
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await bot.send_message(MY_ID, "Бот успешно запущен на GigaChat!")
        print("Бот запущен и готов к работе!")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")