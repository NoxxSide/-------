import os
import time # Добавьте в начало файла
import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"), 
    base_url="https://api.deepseek.com"
)

# --- Состояния ---
class BotStates(StatesGroup):
    MainMenu = State()
    # Кейс 1: Поиск по ингредиентам
    WaitingForIngredients = State()
    # Кейс 1: Поиск по названию/кухне
    WaitingForDishQuery = State()
    WaitingForDishType = State() # Выбор: десерт, основное и т.д.
    # Общее
    WaitingForRecipeSelection = State()

dp = Dispatcher(storage=MemoryStorage())

# --- Клавиатуры ---

def get_main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍎 Поиск по ингредиентам", callback_data="mode_ingredients")],
        [InlineKeyboardButton(text="🍜 Поиск по блюду/кухне", callback_data="mode_dish")],
        [InlineKeyboardButton(text="📖 Поваренная книга (в разработке)", callback_data="cook_book")]
    ])

def get_dish_type_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥘 Основное блюдо", callback_data="type:основное блюдо")],
        [InlineKeyboardButton(text="🥗 Второе блюдо/Закуска", callback_data="type:закуска")],
        [InlineKeyboardButton(text="🍹 Напиток", callback_data="type:напиток")],
        [InlineKeyboardButton(text="🍰 Десерт", callback_data="type:десерт")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="start")]
    ])

def get_back_to_menu_btn():
    # Кнопка, которую можно добавить к любому сообщению
    return InlineKeyboardButton(text="🏠 В главное меню", callback_data="start")

# --- Вспомогательные функции ---

async def get_deepseek_response(prompt: str, is_check: bool = False):
    try:
        max_tokens = 50 if is_check else 2000 
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system", 
                    "content": "Ты — строгий кулинарный робот. ЗАПРЕЩЕНО писать вводные фразы, оценки вкуса и пожелания. Только факты и структура."
                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"DeepSeek Error: {e}")
        return None

# --- Обработка команд ---

@dp.message(Command("start"))
@dp.callback_query(F.data == "start")
async def cmd_start(event: types.Message | types.CallbackQuery, state: FSMContext):
    await state.clear()
    text = "👋 Добро пожаловать! Выберите режим работы:"
    kb = get_main_menu_kb()
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb)
    else:
        await event.message.edit_text(text, reply_markup=kb)
    await state.set_state(BotStates.MainMenu)

# --- КЕЙС 1: Поиск по ингредиентам ---

@dp.callback_query(F.data == "mode_ingredients")
async def start_ingredients_mode(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("🍎 Напишите список продуктов через запятую:", 
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[get_back_to_menu_btn()]]))
    await state.set_state(BotStates.WaitingForIngredients)

@dp.message(BotStates.WaitingForIngredients)
async def handle_ingredients(message: types.Message, state: FSMContext):
    raw_text = message.text.strip()
    if len(raw_text) < 3: return
    
    status_msg = await message.answer("🔍 Анализирую продукты...")
    await process_cooking(message, state, f"ингредиенты: {raw_text}", status_msg)

# --- КЕЙС 1: Поиск по блюду/кухне ---

@dp.callback_query(F.data == "mode_dish")
async def start_dish_mode(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("🍜 Какую кухню или направление вы хотите? (Например: Азиатская, Мясные блюда, Итальянская)",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[get_back_to_menu_btn()]]))
    await state.set_state(BotStates.WaitingForDishQuery)

@dp.message(BotStates.WaitingForDishQuery)
async def handle_dish_query(message: types.Message, state: FSMContext):
    await state.update_data(dish_query=message.text.strip())
    await message.answer("🎯 Уточните тип блюда:", reply_markup=get_dish_type_kb())
    await state.set_state(BotStates.WaitingForDishType)

@dp.callback_query(BotStates.WaitingForDishType, F.data.startswith("type:"))
async def handle_dish_type(call: types.CallbackQuery, state: FSMContext):
    dish_type = call.data.split(":")[1]
    data = await state.get_data()
    query = data.get("dish_query")
    
    await call.message.edit_text(f"🔍 Ищу лучшие варианты ({dish_type})...")
    await process_cooking(call.message, state, f"кухня/направление: {query}, категория: {dish_type}", call.message)

# --- Общая логика выдачи вариантов ---

# 1. Обновленная функция выдачи вариантов (исправляет повторы и ошибку "не изменено")
async def process_cooking(message: types.Message, state: FSMContext, search_params: str, status_msg: types.Message):
    data = await state.get_data()
    previous_titles = data.get('saved_recipes', [])
    
    # Добавляем в промпт исключение старых названий
    exclude_str = f" ИСКЛЮЧИ эти блюда: {', '.join(previous_titles)}." if previous_titles else ""
    
    prompt = (
        f"На основе запроса ({search_params}) предложи 3 подходящих блюда.{exclude_str} "
        "Формат: Название / Краткое описание (1 предложение). Строго 3 строки."
    )
    
    res_text = await get_deepseek_response(prompt)
    if not res_text:
        return await status_msg.edit_text("❌ Ошибка. Попробуйте снова.", reply_markup=get_main_menu_kb())

    kb_list = []
    titles = []
    for line in res_text.split('\n'):
        if '/' not in line: continue
        name = re.sub(r'[*_#`~]', '', line.split('/', 1)[0]).strip()
        name = re.sub(r'^\d+[.)]\s*', '', name)
        if name:
            titles.append(name)
            kb_list.append([InlineKeyboardButton(text=f"🍴 {name[:25]}", callback_data=f"sel:{len(titles)-1}")])

    kb_list.append([InlineKeyboardButton(text="🔄 Другие варианты", callback_data="refresh")])
    kb_list.append([get_back_to_menu_btn()])
    
    # Добавляем метку времени, чтобы текст сообщения ВСЕГДА отличался (исправляет TelegramBadRequest)
    timestamp = time.strftime("%H:%M:%S")
    
    try:
        await status_msg.edit_text(
            f"🥗 <b>Варианты для вас (обновлено в {timestamp}):</b>", 
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Edit error: {e}")

    await state.update_data(saved_recipes=titles, current_search=search_params)
    await state.set_state(BotStates.WaitingForRecipeSelection)

# --- Финальная выдача рецепта ---

@dp.callback_query(F.data.startswith("sel:"))
async def finalize_recipe(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(call.data.split(":")[1])
    name = data['saved_recipes'][idx]
    
    status_msg = await call.message.answer(f"👨‍🍳 Генерирую рецепт: <b>{name}</b>...", parse_mode=ParseMode.HTML)
    
    prompt = (
        f"Напиши строгий технический рецепт блюда '{name}'. "
        "Соблюдай формат:\n"
        "## [Название]\n"
        "## Ингредиенты\n"
        "(Список с граммовками, используй ## для групп)\n"
        "## Пошаговый рецепт\n"
        "### Шаг X: Название\n"
        "Никаких вступлений, никакой воды и нижних подчеркиваний."
    )
    
    recipe_text = await get_deepseek_response(prompt)
    
    # Очистка текста от символов, которые ломают Markdown в Telegram
    if recipe_text:
        # Убираем одиночные символы, которые нейросеть может вставить по привычке
        recipe_text = recipe_text.replace("_", "") 
    
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="refresh")],
        [get_back_to_menu_btn()]
    ])

    try:
        # Используем HTML, так как он более стабилен при генерации от ИИ
        # Для этого превратим наши ## в жирный текст программно
        formatted_text = recipe_text.replace("## ", "\n<b>").replace("\n", "</b>\n", 1) # Примерная логика
        
        # Если хотите оставить Markdown, используйте простую очистку:
        await status_msg.edit_text(
            recipe_text or "❌ Ошибка.", 
            reply_markup=back_kb, 
            parse_mode=None # Отключаем парсинг, если ИИ выдает мусор, или используйте Markdown
        )
    except Exception as e:
        # Если упало с ошибкой парсинга — отправляем как чистый текст
        await status_msg.edit_text(recipe_text, reply_markup=back_kb)

@dp.callback_query(F.data == "refresh")
async def refresh(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await process_cooking(call.message, state, data.get('current_search'), call.message)

async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Бот с меню запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())