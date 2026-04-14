import os
import asyncio
import google.generativeai as genai
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp_socks import ProxyConnector
from dotenv import load_dotenv

# 1. Загрузка настроек
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")
PROXY_URL = os.getenv("PROXY_URL")
MY_ID = int(os.getenv("MY_ID"))

# 2. Настройка Gemini
# Убираем socks5 из системных путей, чтобы не было ошибки URIs
proxy_for_google = PROXY_URL.replace("socks5://", "http://")
os.environ['https_proxy'] = proxy_for_google
os.environ['http_proxy'] = proxy_for_google

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет! Пришли продукты, и я составлю рецепт.")

@dp.message()
async def handle_message(message: types.Message):
    await message.bot.send_chat_action(message.chat.id, action="typing")
    try:
        response = model.generate_content(message.text)
        await message.answer(response.text)
    except Exception as e:
        # Если прокси отвалился или таймаут — мы увидим это здесь
        await message.answer(f"Ошибка ИИ: {e}")

async def main():
    # Создаем коннектор отдельно
    connector = ProxyConnector.from_url(PROXY_URL)
    
    # СОЗДАЕМ СЕССИЮ ПУСТОЙ — чтобы точно не было TypeError
    session = AiohttpSession()
    
    # Внедряем коннектор напрямую в объект (это обходит проверку аргументов)
    session._connector = connector 

    # Инициализация бота
    bot = Bot(token=BOT_TOKEN, session=session)

    # Контрольная точка
    try:
        await bot.send_message(MY_ID, ".")
        print(f"Бот запущен! Точка отправлена на ID {MY_ID}")
    except Exception as e:
        print(f"Ошибка при старте: {e}")

    # Запуск
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass