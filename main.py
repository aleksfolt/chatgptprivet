import aiohttp
import openai
from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor
import json
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import logging
import io
from aiogram.types import InputFile
import asyncio
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext

file = open('config.json', 'r')
config = json.load(file)

openai.api_key = config['openai']
bot = Bot(config['token'])
dp = Dispatcher(bot)

chat_storage = {}

messages = [
    {"role": "system", "content": "you are chatgpt"},
    {"role": "user", "content": "Привет"}
]


def update(messages, role, content):
    messages.append({"role": role, "content": content})
    return messages


class ChatMode(StatesGroup):
    CHATGPT = State()
    DALLE2 = State()


@dp.message_handler(commands=['chatgpt'])
async def start_chatting(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in chat_storage:
        chat_storage[chat_id] = messages.copy()

    # Отправляем сообщение пользователю с инструкцией
    await message.answer("Теперь отправьте мне ваш запрос")

    # Регистрируем обработчик для дальнейших сообщений пользователя
    @dp.message_handler(chat_id=chat_id)
    async def continue_chatting(message: types.Message):
        # Обновляем историю сообщений пользователя
        chat_id = message.chat.id
        update(chat_storage[chat_id], "user", message.text)

        # Отправляем сообщение с уведомлением, что запрос обрабатывается
        sent_message = await message.answer("ChatGPT обрабатывает запрос...")

        # Запрашиваем ответ у API OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=chat_storage[chat_id]
        )

        # Отправляем ответ пользователю
        await sent_message.delete()
        await message.answer(response.choices[0].get('text') or response.choices[0]['message'].get('content'))

    @dp.message_handler(chat_id=chat_id)
    async def handle_user_message(message: types.Message):
        chat_id = message.chat.id
        if chat_id not in chat_storage:
            chat_storage[chat_id] = messages.copy()

        if not dp.is_conversation_started_with(chat_id=chat_id):
            await dp.start_conversation(chat_id=chat_id, from_user=chat_id)

        await continue_chatting(message)


async def generate_image(text):
    try:
        response = openai.Image.create(
            prompt=text,
            n=1,
            size="1024x1024"
        )
        # Сохранение изображения в буфер
        img = await aiohttp.ClientSession().get(response['data'][0]['url'])
        img = io.BytesIO(await img.read())
        return img
    except openai.error.InvalidRequestError:
        logging.exception("Request contains forbidden symbols.")
        return None
    except Exception as e:
        logging.exception(e)
        return None


async def send_image(chat_id, image):
    try:
        # Конвертация буфера изображения в InputFile для отправки в телеграм-бот
        image = InputFile(image)
        await bot.send_photo(chat_id=chat_id, photo=image)
    except Exception as e:
        logging.exception(e)


# Обработчик команды /dalle22
@dp.message_handler(commands=['dalle2'])
async def dalle2_command(message: types.Message):
    chat_id = message.chat.id
    await message.answer("Отправьте мне ваш запрос для генерации изображения")

    @dp.message_handler(chat_id=chat_id)
    async def continue_dalle2(message: types.Message):
        text = message.text
        sent_message = await message.answer("Dalle2 обрабатывает запрос...")
        image = await generate_image(text)
        if image:
            await send_image(chat_id, image)
        else:
            await bot.send_message(chat_id=chat_id,
                                   text="Запрос содержит запрещённые термины 🚫. Попробуйте переформулировать.")
        await sent_message.delete()


@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_name = message.from_user.first_name
    await message.answer(
        f"Привет, {user_name}! Я ChatGpt бот. Чтобы начать общение со мной, отправьте команду /chatgpt, а после команды запрос, чтобы сгенерировать изображение отправте команду /dalle2 и запрос после, чтобы выйти в меню отправь команду /settings, чтобы удалить переписку команда /chatgptclear, чтобы сохранить /chatgptstore")


@dp.message_handler(commands=['help'])
async def start_command(message: types.Message):
    await message.answer(
        "Привет! Я ChatGpt, чтобы у меня что-то спросить, отправь команду /chatgpt или /dalle2 чтобы сегенерировать изображение. Если хочешь сохранить переписку отправь команду /chatgptstore, а если удалить то /chatgptclear. Если что-то ещё помочь, обращайся сюда @AleksFolt.")


@dp.message_handler(commands=['about'])
async def start_command(message: types.Message):
    await message.answer("Создатель: @AleksFolt, Сделано на Python, По вопросам @AleksFolt")


@dp.message_handler(commands=['chatgptstore'])
async def store_command(message: types.Message):
    chat_id = message.chat.id
    if chat_id in chat_storage:
        with open(f'chat_storage_{chat_id}.json', 'w') as f:
            json.dump(chat_storage[chat_id], f)
        await message.answer("Переписка сохранена!")
    else:
        await message.answer("Переписка пустая. Нет данных для сохранения.")


@dp.message_handler(commands=['chatgptclear'])
async def clear_command(message: types.Message):
    chat_id = message.chat.id
    if chat_id in chat_storage:
        chat_storage[chat_id] = messages.copy()
        await message.answer("Переписка удалена!")
    else:
        await message.answer("Переписка пустая. Нет данных для удаления.")


# Создаем меню с настройками
settings_menu = ReplyKeyboardMarkup(resize_keyboard=True).add(
    KeyboardButton('/chatgpt'),
    KeyboardButton('/dalle2'),
    KeyboardButton('/help'),
    KeyboardButton('/about'),
    KeyboardButton('/chatgptclear'),
    KeyboardButton('/chatgptstore')
)


# Обработчик команды для вывода меню
@dp.message_handler(commands=['settings'])
async def settings_command(message: types.Message):
    await message.answer("Выберите настройку:", reply_markup=settings_menu)


# Обработчики для каждого пункта меню
@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    await message.answer("Помощь")


@dp.message_handler(commands=['about'])
async def about_command(message: types.Message):
    await message.answer("О боте")


@dp.message_handler(commands=['chatgptclear'])
async def chatgptclear_command(message: types.Message):
    await message.answer("Очистка переписки")


@dp.message_handler(commands=['chatgptstore'])
async def chatgptstore_command(message: types.Message):
    await message.answer("Сохранение переписки")


executor.start_polling(dp, skip_updates=True)
