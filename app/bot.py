from vkbottle.bot import Bot, Message
from vkbottle.dispatch.rules.base import StateRule
from vkbottle import BaseStateGroup

bot = Bot(token='')

class RegistrationState(BaseStateGroup):
    WAITING_CATEGORY = "waiting_category"
    WAITING_AGE = "waiting_age"
    WAITING_ABOUT = "waiting_about"

@bot.on.message(lev="/reg")
async def start_reg(message: Message):
    full_name = await get_user_info(bot, message.from_id)
    await bot.state_dispenser.set(
        message.peer_id,
        RegistrationState.WAITING_CATEGORY,
        full_name=full_name,          # ← передаём в payload
    )
    await message.answer(
        f"Привет, {full_name}! Выбери категорию:"
        "\n1) Новичок \n2) Любитель \n3) Профи"
        )


@bot.on.message(StateRule(RegistrationState.WAITING_CATEGORY))
async def get_about(message: Message):
    payload = message.state_peer.payload or {}
    full_name = payload.get("full_name", "Неизвестный пользователь")
    if message.text == '1':
        category = 'Новичок'
    elif message.text == '2':
        category = 'Любитель'
    elif message.text == '3':
        category = 'Профи'
    else:
        await message.answer(
            f"{full_name}, неверный ввод. Введите число:\n"
            f"1 — Новичок\n2 — Любитель\n3 — Профи"
        )
        return    

    await message.answer(
        f"Спасибо {full_name}! Регистрация завершена.\n"
        f"Категория: {category}"
    )
    await bot.state_dispenser.delete(message.peer_id)
    

async def get_user_info(bot, from_id: int) -> str:
    try:
        user_info = await bot.api.users.get(
            user_ids=from_id,
            fields="first_name,last_name",
        )
        user = user_info[0]
        full_name = f"{user.first_name} {user.last_name}"
    except Exception as e:
        print("Ошибка получения данных пользователя:", e)
        full_name = "Неизвестный пользователь"
    return full_name

bot.run_forever()