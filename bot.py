import asyncio
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.dispatcher.middlewares.base import BaseMiddleware
import aiosqlite

# ---------- НАСТРОЙКИ ----------
TOKEN = "7991920232:AAEKMDzj0s4L8U81pNK4EVpeEazn0UoJYv0"
DB_PATH = "ogonok.db"

# ---------- MIDDLEWARE ДЛЯ ИГНОРИРОВАНИЯ СТАРЫХ СООБЩЕНИЙ ----------
class IgnoreOldMessagesMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: dict):
        now = datetime.now(timezone.utc)
        if now - event.date > timedelta(seconds=10):
            return
        return await handler(event, data)

# ---------- БАЗА ДАННЫХ ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS couples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user1_id INTEGER NOT NULL,
                user2_id INTEGER NOT NULL,
                fire_name TEXT DEFAULT NULL,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                name_changed_at TIMESTAMP DEFAULT 0,
                series_days INTEGER DEFAULT 0,
                balance INTEGER DEFAULT 0,
                last_daily_bonus TIMESTAMP DEFAULT 0,
                cooldown_level INTEGER DEFAULT 0,
                lifetime_level INTEGER DEFAULT 0,
                age INTEGER DEFAULT 0,
                warned_1h BOOLEAN DEFAULT 0,
                is_alive BOOLEAN DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def create_invite(chat_id, from_user_id, to_user_id, message_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO invites (chat_id, from_user_id, to_user_id, message_id) VALUES (?,?,?,?)",
            (chat_id, from_user_id, to_user_id, message_id)
        )
        await db.commit()

async def get_invite_by_message(chat_id, message_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM invites WHERE chat_id=? AND message_id=?",
            (chat_id, message_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"id": row[0], "chat_id": row[1], "from_user_id": row[2], "to_user_id": row[3], "message_id": row[4]}
            return None

async def delete_invite(invite_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM invites WHERE id=?", (invite_id,))
        await db.commit()

async def create_couple(chat_id, user1_id, user2_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO couples (chat_id, user1_id, user2_id, last_activity, last_daily_bonus, age) VALUES (?,?,?, CURRENT_TIMESTAMP, 0, 0)",
            (chat_id, user1_id, user2_id)
        )
        await db.commit()

async def get_active_couple(chat_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM couples WHERE chat_id=? AND (user1_id=? OR user2_id=?) AND is_alive=1",
            (chat_id, user_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(zip([c[0] for c in cursor.description], row))
            return None

async def update_activity(chat_id, user_id):
    couple = await get_active_couple(chat_id, user_id)
    if not couple:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE couples SET last_activity=CURRENT_TIMESTAMP, warned_1h=0 WHERE id=?", (couple["id"],))
        await db.commit()
    return True

async def set_fire_name(chat_id, user_id, name):
    couple = await get_active_couple(chat_id, user_id)
    if not couple:
        return False, "У вас нет активного огонька"
    cooldown_hours = max(0.5, 1 - 0.5 * couple["cooldown_level"])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name_changed_at FROM couples WHERE id=?", (couple["id"],)) as cursor:
            row = await cursor.fetchone()
            last_change = datetime.fromisoformat(row[0]) if row[0] else datetime.min
            if datetime.now() - last_change < timedelta(hours=cooldown_hours):
                return False, f"Имя можно менять раз в {cooldown_hours} ч"
        await db.execute(
            "UPDATE couples SET fire_name=?, name_changed_at=CURRENT_TIMESTAMP WHERE id=?",
            (name, couple["id"])
        )
        await db.commit()
    return True, f"🔥 вашего огонька зовут {name}\nНапиши\nОгонёк"

async def get_fire_stats(chat_id, user_id):
    couple = await get_active_couple(chat_id, user_id)
    if not couple:
        return None
    base_hours = 24
    extra_hours = couple["lifetime_level"] * 12
    total_hours = base_hours + extra_hours
    total_seconds = total_hours * 3600
    last_act = datetime.fromisoformat(couple["last_activity"])
    now = datetime.now()
    elapsed = (now - last_act).total_seconds()
    remaining = total_seconds - elapsed
    if remaining <= 0:
        percent = 0
        time_left = "0 мин"
    else:
        percent = int((remaining / total_seconds) * 100)
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        time_left = f"{hours} ч {minutes} мин"
    bar_len = 30
    filled = int(bar_len * percent / 100)
    bar = "█" * filled + "." * (bar_len - filled)
    name = couple["fire_name"] or "нет имени"
    return {
        "id": couple["id"],
        "name": name,
        "percent": percent,
        "time_left": time_left,
        "bar": bar,
        "series_days": couple["series_days"],
        "balance": couple["balance"],
        "cooldown_level": couple["cooldown_level"],
        "lifetime_level": couple["lifetime_level"],
        "age": couple["age"],
        "total_hours": total_hours,
        "user1_id": couple["user1_id"],
        "user2_id": couple["user2_id"],
        "warned_1h": couple["warned_1h"]
    }

async def add_daily_bonus(couple_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT last_daily_bonus, balance, series_days, age FROM couples WHERE id=?", (couple_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            last_bonus = datetime.fromisoformat(row[0]) if row[0] else datetime.min
            if datetime.now() - last_bonus >= timedelta(hours=24):
                await db.execute(
                    "UPDATE couples SET balance = balance + 1, series_days = series_days + 1, age = age + 1, last_daily_bonus = CURRENT_TIMESTAMP WHERE id=?",
                    (couple_id,)
                )
                await db.commit()
                return True
    return False

async def get_top_couples(chat_id, limit=50):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT fire_name, series_days, balance FROM couples WHERE chat_id=? AND is_alive=1 ORDER BY series_days DESC LIMIT ?",
            (chat_id, limit)
        ) as cursor:
            return await cursor.fetchall()

async def buy_upgrade(chat_id, user_id, upgrade_type):
    couple = await get_active_couple(chat_id, user_id)
    if not couple:
        return False, "У вас нет активного огонька"
    if upgrade_type == "cooldown":
        cost = 3
        new_level = couple["cooldown_level"] + 1
        if new_level > 3:
            return False, "Максимальный уровень кулдауна уже достигнут"
        if couple["balance"] < cost:
            return False, f"Не хватает {cost - couple['balance']} дней"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE couples SET balance = balance - ?, cooldown_level = ? WHERE id = ?",
                (cost, new_level, couple["id"])
            )
            await db.commit()
        return True, f"🔥 Кулдаун уменьшен! Теперь менять имя можно раз в {max(0.5, 1 - 0.5*new_level)} ч"
    elif upgrade_type == "lifetime":
        cost = 5
        new_level = couple["lifetime_level"] + 1
        if new_level > 5:
            return False, "Максимальный уровень времени жизни уже достигнут"
        if couple["balance"] < cost:
            return False, f"Не хватает {cost - couple['balance']} дней"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE couples SET balance = balance - ?, lifetime_level = ? WHERE id = ?",
                (cost, new_level, couple["id"])
            )
            await db.commit()
        return True, f"🔥 Время жизни увеличено! Теперь огонёк живёт {24 + new_level*12} ч"
    return False, "Неизвестное улучшение"

# ---------- ПЛАНИРОВЩИК ФОНОВЫХ ЗАДАЧ ----------
async def scheduler_task(bot: Bot):
    while True:
        await asyncio.sleep(300)
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT id, chat_id, user1_id, user2_id, last_activity, lifetime_level, age, warned_1h, fire_name FROM couples WHERE is_alive=1") as cursor:
                    rows = await cursor.fetchall()
                    now = datetime.now()
                    for row in rows:
                        cid, chat_id, u1, u2, last_act_str, lvl, age, warned, name = row
                        last_act = datetime.fromisoformat(last_act_str)
                        total_hours = 24 + lvl * 12
                        expires_at = last_act + timedelta(hours=total_hours)
                        remaining = expires_at - now

                        bonus_added = await add_daily_bonus(cid)
                        if bonus_added:
                            try:
                                u1_obj = await bot.get_chat(u1)
                                u2_obj = await bot.get_chat(u2)
                                age_new = age + 1
                                await bot.send_message(
                                    chat_id,
                                    f"🔥 Огонёк стал ещё больше!\nВырос: +1\nЛет: {age_new}\nПродолжай общаться чтобы добавлять рост."
                                )
                            except:
                                pass

                        if remaining <= timedelta(hours=1) and remaining > timedelta(0) and not warned:
                            try:
                                u1_obj = await bot.get_chat(u1)
                                u2_obj = await bot.get_chat(u2)
                                await bot.send_message(
                                    chat_id,
                                    f"@{u1_obj.username or u1} и @{u2_obj.username or u2}\n"
                                    f"Ваш огонек тухнет\nПотухнет через час\nОбщайтесь чтобы он возобновился"
                                )
                                await db.execute("UPDATE couples SET warned_1h=1 WHERE id=?", (cid,))
                                await db.commit()
                            except:
                                pass

                        if remaining <= timedelta(0):
                            await db.execute("UPDATE couples SET is_alive=0 WHERE id=?", (cid,))
                            await db.commit()
                            try:
                                u1_obj = await bot.get_chat(u1)
                                u2_obj = await bot.get_chat(u2)
                                await bot.send_message(
                                    chat_id,
                                    f"💔 @{u1_obj.username or u1} и @{u2_obj.username or u2}\n"
                                    f"От неактивности ваш огонек потух\n"
                                    f"Ну вы можете еще раз просто вылупи серийчика"
                                )
                            except:
                                pass
        except Exception as e:
            logging.error(f"Scheduler error: {e}")

# ---------- РОУТЕР КОМАНД ----------
router = Router()
router.message.middleware(IgnoreOldMessagesMiddleware())
router.callback_query.middleware(IgnoreOldMessagesMiddleware())

async def on_user_action(message: types.Message):
    if not message.from_user.is_bot:
        updated = await update_activity(message.chat.id, message.from_user.id)
        if updated:
            stats = await get_fire_stats(message.chat.id, message.from_user.id)
            if stats and stats["warned_1h"]:
                u1 = await message.bot.get_chat(stats["user1_id"])
                u2 = await message.bot.get_chat(stats["user2_id"])
                await message.answer(
                    f"@{u1.username or u1} и @{u2.username or u2}\n"
                    f"Один из вас активничал и за этого огонек все ещё живёт ну чтобы он жил дальше активнее будьте!"
                )
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE couples SET warned_1h=0 WHERE id=?", (stats["id"],))
                    await db.commit()

@router.message(F.text.lower() == "старт")
async def start_cmd(message: types.Message):
    await on_user_action(message)
    await message.answer(
        "🔥 Бот Огонёк прям как в Тик Токе\n"
        "Просто пригласи этого бота в чат\n"
        "• ответь на сообщение партнёра командой Вылупить или Реплаем\n"
        "• общайся с партнёром чтобы он не потух\n\n"
        "Команды:\n"
        "Вылупить / Реплаем (в ответ на сообщение) — пригласить\n"
        "Огонек — статус\n"
        "Серийчик — ваша серия дней\n"
        "Огонек имя [кличка] — дать имя\n"
        "Топ огонек — рейтинг пар\n"
        "Огонек шоп — магазин улучшений"
    )

@router.message(F.text.lower() == "команды")
async def commands_list(message: types.Message):
    await on_user_action(message)
    await message.answer(
        "Список команд:\n"
        "Вылупить / Реплаем (ответом на сообщение) — пригласить\n"
        "Огонек — посмотреть статы\n"
        "Серийчик — сколько дней серия\n"
        "Огонек имя Кличка — дать имя\n"
        "Топ огонек — топ 50 огоньков\n"
        "Огонек шоп — магазин улучшений"
    )

@router.message(F.text.lower() == "реплаем")
@router.message(F.text.lower() == "вылупить")
async def invite_by_reply(message: types.Message):
    await on_user_action(message)
    
    # Проверяем, что это ответ на сообщение
    if not message.reply_to_message:
        await message.reply("❌ Эту команду нужно отправлять **ответом на сообщение** партнёра!")
        return
    
    to_user = message.reply_to_message.from_user
    from_user = message.from_user
    
    # Нельзя пригласить бота или самого себя
    if to_user.is_bot:
        await message.reply("❌ Нельзя вылупить огонька с ботом!")
        return
    if to_user.id == from_user.id:
        await message.reply("❌ Нельзя вылупить огонька с самим собой!")
        return
    
    # Проверяем, нет ли уже активной пары
    existing_from = await get_active_couple(message.chat.id, from_user.id)
    if existing_from:
        await message.reply("❌ У вас уже есть активный огонёк!")
        return
    
    existing_to = await get_active_couple(message.chat.id, to_user.id)
    if existing_to:
        await message.reply(f"❌ У @{to_user.username or to_user.first_name} уже есть активный огонёк!")
        return
    
    # Создаём кнопки
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Принять", callback_data=f"accept_{from_user.id}")],
        [InlineKeyboardButton(text="❌ Отказать", callback_data=f"decline_{from_user.id}")]
    ])
    
    sent = await message.answer(
        f"🔥 @{to_user.username or to_user.first_name}, вас пригласили для того чтобы вылупить огонёк!\n"
        f"Пригласил: @{from_user.username or from_user.first_name}",
        reply_markup=kb
    )
    
    await create_invite(message.chat.id, from_user.id, to_user.id, sent.message_id)
    await message.delete()  # Удаляем сообщение с командой

@router.message(F.text.lower() == "огонек")
async def show_stats(message: types.Message):
    await on_user_action(message)
    stats = await get_fire_stats(message.chat.id, message.from_user.id)
    if not stats:
        await message.reply("❌ У вас нет активного огонька. Пригласите партнёра командой Вылупить (ответом на его сообщение)")
        return
    text = (
        f"🔥 Огонёк: {stats['name']}\n"
        f"Время до потухания: {stats['time_left']} (из {stats['total_hours']} ч)\n"
        f"[{stats['bar']}]\n"
        f"👆 {stats['percent']}% для потушения\n"
        f"📅 Серия: {stats['series_days']} дней\n"
        f"💰 Баланс: {stats['balance']} дней\n"
        f"🌱 Возраст: {stats['age']} лет"
    )
    await message.reply(text)

@router.message(F.text.lower() == "серийчик")
async def series_cmd(message: types.Message):
    await on_user_action(message)
    stats = await get_fire_stats(message.chat.id, message.from_user.id)
    if not stats:
        await message.reply("❌ У вас нет активного огонька.")
        return
    await message.reply(f"🔥 Серийчик: {stats['series_days']} дней")

@router.message(F.text.lower().startswith("огонек имя "))
async def set_name_cmd(message: types.Message):
    await on_user_action(message)
    name = message.text[11:].strip()
    if not name or len(name) > 20:
        await message.reply("❌ Имя должно быть от 1 до 20 символов")
        return
    success, msg = await set_fire_name(message.chat.id, message.from_user.id, name)
    await message.reply(msg)

@router.message(F.text.lower() == "топ огонек")
async def top_cmd(message: types.Message):
    await on_user_action(message)
    rows = await get_top_couples(message.chat.id)
    if not rows:
        await message.reply("В этом чате пока нет активных огоньков.")
        return
    text = "🏆 Топ огоньков:\n"
    for i, (name, days, balance) in enumerate(rows[:50], 1):
        display_name = name if name else "Безымянный"
        text += f"{i}. {display_name} — {days} дн. (💰{balance})\n"
    await message.reply(text)

@router.message(F.text.lower() == "огонек шоп")
async def shop_cmd(message: types.Message):
    await on_user_action(message)
    stats = await get_fire_stats(message.chat.id, message.from_user.id)
    if not stats:
        await message.reply("❌ У вас нет активного огонька.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌀 Кулдаун (3 дня)", callback_data="shop_cooldown")],
        [InlineKeyboardButton(text="⏳ Время потушения (5 дней)", callback_data="shop_lifetime")]
    ])
    await message.reply(
        f"🛒 Магазин улучшений\n"
        f"Общайтесь чтобы покупать улучшение\n"
        f"Вы общались: {stats['balance']} дней\n\n"
        f"🌀 Кулдаун — уменьшает время между сменами имени\n"
        f"⏳ Время потушения — увеличивает время жизни огонька",
        reply_markup=kb
    )

# ---------- КНОПКИ ПРИНЯТЬ/ОТКАЗАТЬ ----------
@router.callback_query(F.data.startswith("accept_"))
async def accept_callback(callback: types.CallbackQuery):
    await update_activity(callback.message.chat.id, callback.from_user.id)
    
    # Получаем ID пригласившего из callback_data
    from_user_id = int(callback.data.split("_")[1])
    to_user_id = callback.from_user.id
    
    # Ищем приглашение по message_id
    invite = await get_invite_by_message(callback.message.chat.id, callback.message.message_id)
    if not invite:
        await callback.answer("Приглашение устарело!", show_alert=True)
        return
    
    # Проверяем, что нажимает правильный человек
    if invite["to_user_id"] != to_user_id:
        await callback.answer("Это приглашение не для вас!", show_alert=True)
        return
    
    # Проверяем, нет ли уже активной пары
    existing_to = await get_active_couple(callback.message.chat.id, to_user_id)
    if existing_to:
        await callback.message.edit_text("❌ У вас уже есть активный огонёк!")
        await delete_invite(invite["id"])
        return
    
    existing_from = await get_active_couple(callback.message.chat.id, from_user_id)
    if existing_from:
        await callback.message.edit_text("❌ У пригласившего уже есть активный огонёк!")
        await delete_invite(invite["id"])
        return
    
    # Создаём пару
    await create_couple(callback.message.chat.id, from_user_id, to_user_id)
    await delete_invite(invite["id"])
    
    from_user = await callback.bot.get_chat(from_user_id)
    to_user = await callback.bot.get_chat(to_user_id)
    
    await callback.message.edit_text(
        f"🔥 @{from_user.username or from_user.first_name} и @{to_user.username or to_user.first_name}\n"
        f"Вы вылупили серийчика (огонёк)!\n"
        f"Чтобы он не потух — общайтесь!\n"
        f"⏳ Неактив 24 часа — огонёк потухнет\n\n"
        f"Статы:\n"
        f"Огонек: нет имени\n"
        f"Время до потухания: 24 ч\n"
        f"[{'█'*30}]\n"
        f"👆 100% для потушения\n\n"
        f"Напиши 'Огонек имя Кличка' чтобы дать имя!"
    )
    await callback.answer("✅ Огонёк вылуплен!")

@router.callback_query(F.data.startswith("decline_"))
async def decline_callback(callback: types.CallbackQuery):
    await update_activity(callback.message.chat.id, callback.from_user.id)
    
    from_user_id = int(callback.data.split("_")[1])
    to_user_id = callback.from_user.id
    
    invite = await get_invite_by_message(callback.message.chat.id, callback.message.message_id)
    if not invite:
        await callback.answer("Приглашение устарело!", show_alert=True)
        return
    
    if invite["to_user_id"] != to_user_id:
        await callback.answer("Это приглашение не для вас!", show_alert=True)
        return
    
    await delete_invite(invite["id"])
    
    from_user = await callback.bot.get_chat(from_user_id)
    to_user = await callback.bot.get_chat(to_user_id)
    
    await callback.message.edit_text(
        f"❌ @{to_user.username or to_user.first_name} отказался вылуплять огонька.\n"
        f"@{from_user.username or from_user.first_name}, попробуй найти другого партнёра!"
    )
    await callback.answer("❌ Отказано")

# ---------- КНОПКИ МАГАЗИНА ----------
@router.callback_query(F.data == "shop_cooldown")
async def buy_cooldown(callback: types.CallbackQuery):
    await update_activity(callback.message.chat.id, callback.from_user.id)
    stats = await get_fire_stats(callback.message.chat.id, callback.from_user.id)
    if not stats:
        await callback.answer("Огонёк не найден", show_alert=True)
        return
    success, msg = await buy_upgrade(callback.message.chat.id, callback.from_user.id, "cooldown")
    if success:
        await callback.message.edit_text(
            f"🔥 Отлично! Вы приобрели улучшение 'Кулдаун'.\n"
            f"Потрачено дней: 3\n"
            f"Ваши дни: {stats['balance'] - 3}"
        )
    else:
        await callback.answer(msg, show_alert=True)

@router.callback_query(F.data == "shop_lifetime")
async def buy_lifetime(callback: types.CallbackQuery):
    await update_activity(callback.message.chat.id, callback.from_user.id)
    stats = await get_fire_stats(callback.message.chat.id, callback.from_user.id)
    if not stats:
        await callback.answer("Огонёк не найден", show_alert=True)
        return
    success, msg = await buy_upgrade(callback.message.chat.id, callback.from_user.id, "lifetime")
    if success:
        await callback.message.edit_text(
            f"🔥 Отлично! Вы приобрели улучшение 'Время потушения'.\n"
            f"Потрачено дней: 5\n"
            f"Ваши дни: {stats['balance'] - 5}"
        )
    else:
        await callback.answer(msg, show_alert=True)

# ---------- ГЛАВНАЯ ФУНКЦИЯ ----------
async def main():
    await init_db()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    asyncio.create_task(scheduler_task(bot))

    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
