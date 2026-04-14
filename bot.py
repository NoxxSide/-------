import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from gigachat import GigaChat
from dotenv import load_dotenv

load_dotenv()

# Логирование для отладки
logging.basicConfig(level=logging.INFO)

giga = GigaChat(credentials=os.getenv("GIGACHAT_CREDENTIALS"), verify_ssl_certs=False)

class RecipeStates(StatesGroup):
    WaitingForIngredients = State()
    WaitingForRecipeSelection = State()

dp = Dispatcher(storage=MemoryStorage())

async def get_giga_response(prompt: str, timeout: int = 35):
    """Обертка для запроса к ИИ с таймаутом и проверкой"""
    try:
        res = await asyncio.wait_for(giga.achat(prompt), timeout=timeout)
        return res.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"GigaChat Error: {e}")
        return None

async def process_cooking(message: types.Message, state: FSMContext, ingredients: str):
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Смягченный промпт: просим блюда, где эти продукты ПРЕОБЛАДАЮТ
    prompt = (
        f"У меня есть: {ingredients}. Предложи 3 реальных названия блюд, "
        f"где эти продукты являются основными. "
        f"Пиши СТРОГО формат: Название / Описание. Ровно 3 строки. "
        f"Если это совсем несъедобно, напиши ОШИБКА."
    )
    
    res_text = await get_giga_response(prompt)
    
    if not res_text or "ОШИБКА" in res_text.upper():
        return await message.answer("🤔 Не удалось подобрать блюда. Попробуй изменить список продуктов!")

    kb_list = []
    titles = []
    
    for line in res_text.split('\n')[:3]:
        line = line.replace('*', '').strip()
        if not line: continue
        
        # Парсим название
        name = line.split('/', 1)[0].strip().lstrip('0123456789. ')
        if name and "НАЗВАНИЕ" not in name.upper():
            titles.append(name)
            kb_list.append([InlineKeyboardButton(text=f"🍴 {name[:25]}", callback_data=f"sel:{len(titles)-1}")])

    if not kb_list:
        return await message.answer("⚠️ ИИ выдал ответ в странном формате. Попробуй еще раз.")

    kb_list.append([InlineKeyboardButton(text="🔄 Другие варианты", callback_data="refresh")])
    await state.update_data(saved_recipes=titles, all_products=ingredients)
    
    await message.answer("🥗 **Вот что можно приготовить:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))
    await state.set_state(RecipeStates.WaitingForRecipeSelection)

# --- Хендлеры ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Напиши список продуктов через запятую!")
    await state.set_state(RecipeStates.WaitingForIngredients)

@dp.message(RecipeStates.WaitingForIngredients)
async def handle_ingr(message: types.Message, state: FSMContext):
    await process_cooking(message, state, message.text)

@dp.callback_query(F.data == "refresh")
async def refresh(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await call.message.delete()
    await process_cooking(call.message, state, data.get('all_products'))

@dp.callback_query(F.data.startswith("sel:"))
async def finalize_recipe(call: types.CallbackQuery, state: FSMContext):
    # Моментальный ответ, чтобы Telegram не закрыл соединение
    await call.answer()
    
    data = await state.get_data()
    if not data or 'saved_recipes' not in data:
        return await call.message.answer("⚠️ Сессия истекла. Начни сначала: /start")

    idx = int(call.data.split(":")[1])
    name = data['saved_recipes'][idx]
    
    await call.message.bot.send_chat_action(chat_id=call.message.chat.id, action="typing")
    status_msg = await call.message.answer(f"⏳ Составляю рецепт для: {name}...")
    
    recipe_prompt = (
        f"Напиши пошаговый рецепт блюда '{name}' из продуктов: {data['all_products']}. "
        f"Включи граммовки и этапы приготовления."
    )
    
    recipe_text = await get_giga_response(recipe_prompt, timeout=45)
    
    if recipe_text:
        await status_msg.edit_text(recipe_text, parse_mode="Markdown")
    else:
        await status_msg.edit_text("❌ Ошибка связи с ИИ. Попробуй нажать на кнопку еще раз.")

async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())