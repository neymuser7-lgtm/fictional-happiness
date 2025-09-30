# battle_bot.py
import telebot
from telebot import types
import random
import sqlite3
import time
import threading

# ==== SOZLAMALAR ====
TOKEN = "8417418020:AAGjtjA43XOOpwc2TEUfJ039cNoBdT4JQCA"  # <<<<<<<<<<<< tokenni shu yerga qo'ying
bot = telebot.TeleBot(TOKEN)
DB = "battle_bot.db"

# In-memory sessions: chat_id -> session
sessions = {}

# ==== DB: leaderboard va stats ====
def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        last_seen INTEGER
      )
    """)
    conn.commit()
    conn.close()

def record_result(user_id, username, won: bool):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(user_id, username, wins, losses, last_seen) VALUES(?,?,?,?,?)",
                (user_id, username, 0, 0, int(time.time())))
    if won:
        cur.execute("UPDATE users SET wins = wins + 1, username=?, last_seen=? WHERE user_id=?",
                    (username, int(time.time()), user_id))
    else:
        cur.execute("UPDATE users SET losses = losses + 1, username=?, last_seen=? WHERE user_id=?",
                    (username, int(time.time()), user_id))
    conn.commit()
    conn.close()

def get_stats(user_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT wins, losses FROM users WHERE user_id=?", (user_id,))
    r = cur.fetchone()
    conn.close()
    return r if r else (0,0)

def top_leaderboard(limit=10):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT username, wins, losses FROM users ORDER BY wins DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows

# ==== Game mechanics ====
def make_bot_stats(level=1):
    # bot stats scale with randomness and level
    base_hp = 80 + level*10 + random.randint(-10,15)
    base_atk = 12 + level*3 + random.randint(-3,5)
    base_def = 6 + level*2 + random.randint(-2,3)
    special_power = 1.6 + random.random()*0.6
    return {"hp": base_hp, "atk": base_atk, "def": base_def, "sp": special_power}

def make_player_stats():
    # default player stats (equalizer)
    return {"hp": 100, "atk": 14, "def": 8, "sp": 1.7}

def ai_choose_action(bot_state, player_state):
    # simple AI: if low hp -> defend or special; else attack
    if bot_state["hp"] < player_state["atk"] * 2 and random.random() < 0.6:
        return "defend"
    # occasional special
    if random.random() < 0.18:
        return "special"
    return "attack"

def resolve_round(player_action, bot_action, player, bot):
    # returns tuple (player_damage_to_bot, bot_damage_to_player, text)
    log = []
    pdmg = 0
    bdmg = 0

    # player action effect
    if player_action == "attack":
        pdmg = max(0, int(player["atk"] - bot["def"]*0.5 + random.randint(-3,5)))
        log.append(f"Siz hujum qildingiz — zarar: {pdmg}")
    elif player_action == "defend":
        pdmg = 0
        player_def_buff = player["def"] * 1.6
        log.append("Siz mudofaa holatidasiz — keyingi hujumga kamroq zarar olasiz.")
    elif player_action == "special":
        pdmg = max(0, int(player["atk"] * player["sp"] + random.randint(-2,6)))
        log.append(f"Siz maxsus hujum qildingiz — kuch: {pdmg}")
    else:
        log.append("Noma'lum harakat.")

    # bot action effect
    if bot_action == "attack":
        bdmg = max(0, int(bot["atk"] - (player["def"]*0.5) + random.randint(-3,4)))
        log.append(f"Bot hujum qildi — zarar: {bdmg}")
    elif bot_action == "defend":
        bdmg = 0
        bot_def_buff = bot["def"] * 1.6
        log.append("Bot mudofaa holatida.")
    elif bot_action == "special":
        bdmg = max(0, int(bot["atk"] * bot["sp"] + random.randint(-2,6)))
        log.append(f"Bot maxsus hujum qildi — kuch: {bdmg}")

    # Interaction: if defender present reduce incoming damage
    if player_action == "defend":
        bdmg = int(bdmg * 0.5)
    if bot_action == "defend":
        pdmg = int(pdmg * 0.5)

    # apply
    bot["hp"] -= pdmg
    player["hp"] -= bdmg

    return pdmg, bdmg, "\n".join(log)

# ==== Bot commands & handlers ====
@bot.message_handler(commands=['start'])
def cmd_start(m):
    text = ("Salom, *BattleBot* ga xush kelibsiz!\n\n"
            "Siz bilan jang qilib, reyting va tajriba to‘plash mumkin.\n"
            "Buyruqlar:\n"
            "/battle — bot bilan jang\n"
            "/stats — sizning g‘alaba/mag‘lubiyatlar\n"
            "/leaderboard — eng ko‘p g‘alaba qozonganlar")
    bot.send_message(m.chat.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['stats'])
def cmd_stats(m):
    r = get_stats(m.from_user.id)
    wins, losses = r if r else (0,0)
    bot.send_message(m.chat.id, f"Sizning statistikangiz:\nGʻalabalar: {wins}\nMagʻlubiyatlar: {losses}")

@bot.message_handler(commands=['leaderboard'])
def cmd_lb(m):
    rows = top_leaderboard(10)
    if not rows:
        bot.send_message(m.chat.id, "Hech kim hali reytingga kirmagan.")
        return
    txt = "🏆 Top reyting — eng ko‘p g‘alaba:\n\n"
    for i,(u,w,l) in enumerate(rows, start=1):
        txt += f"{i}. {u} — {w} gʻalaba, {l} magʻlubiyat\n"
    bot.send_message(m.chat.id, txt)

@bot.message_handler(commands=['battle'])
def cmd_battle(m):
    chat = m.chat.id
    user = m.from_user
    # create session
    player = make_player_stats()
    # bot level scaled with number of wins
    wins, losses = get_stats(user.id)
    level = 1 + (wins // 5)
    enemy = make_bot_stats(level)
    sess = {
        "player": player,
        "bot": enemy,
        "turn": 1,
        "user_id": user.id,
        "username": user.username or f"{user.first_name or 'Anon'}",
        "last_action_time": time.time(),
        "cooldown": {"special":0}
    }
    sessions[chat] = sess

    # send initial message with keyboard
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("Hujum ⚔️", callback_data="act_attack"),
               types.InlineKeyboardButton("Mudofaa 🛡️", callback_data="act_defend"))
    markup.row(types.InlineKeyboardButton("Maxsus 🌩️", callback_data="act_special"))
    msg = bot.send_message(chat, f"Jang boshlanadi! Bot HP: {enemy['hp']}, Siz HP: {player['hp']}\n\nTanlang:", reply_markup=markup)
    # store message id for edits
    sess["msg_id"] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("act_"))
def callback_action(call):
    chat = call.message.chat.id
    if chat not in sessions:
        bot.answer_callback_query(call.id, "Sizda aktiv jang topilmadi. /battle bilan boshlang.")
        return
    sess = sessions[chat]
    player = sess["player"]
    bot_state = sess["bot"]
    action = call.data.split("_",1)[1]  # attack/defend/special

    # enforce special cooldown (one special per 3 turns)
    now = time.time()
    if action == "special":
        last = sess["cooldown"].get("special_at",0)
        if now - last < 12:  # 12 seconds cooldown (tuneable)
            bot.answer_callback_query(call.id, "Maxsus hujum sovush ekan — biroz kuting.")
            return
        sess["cooldown"]["special_at"] = now

    # choose bot action
    bot_action = ai_choose_action(bot_state, player)

    pdmg, bdmg, summary = resolve_round(action, bot_action, player, bot_state)

    # create reply
    text = (f"🔹 Turn {sess['turn']}\n\n"
            f"Siz: {action.upper()}  |  Bot: {bot_action.upper()}\n\n"
            f"{summary}\n\n"
            f"Siz HP: {max(0,player['hp'])}  |  Bot HP: {max(0,bot_state['hp'])}")

    # edit original message to show results and fresh keyboard (unless finished)
    if player["hp"] <= 0 or bot_state["hp"] <= 0:
        # battle finished
        if bot_state["hp"] <= 0 and player["hp"] > 0:
            text = "🎉 Siz g‘alaba qozondingiz!\n\n" + text
            record_result(sess["user_id"], sess["username"], True)
        else:
            text = "😞 Siz mag‘lub bo‘ldingiz. Bot kuchliroq ekan.\n\n" + text
            record_result(sess["user_id"], sess["username"], False)

        # present final keyboard (replay)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Yana jang /battle", callback_data="play_again"))
        try:
            bot.edit_message_text(text, chat, sess["msg_id"], reply_markup=kb, parse_mode=None)
        except Exception:
            bot.send_message(chat, text)
        # cleanup session
        del sessions[chat]
    else:
        # continue: update turn and keyboard
        sess["turn"] += 1
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Hujum ⚔️", callback_data="act_attack"),
                   types.InlineKeyboardButton("Mudofaa 🛡️", callback_data="act_defend"))
        markup.row(types.InlineKeyboardButton("Maxsus 🌩️", callback_data="act_special"))
        try:
            bot.edit_message_text(text, chat, sess["msg_id"], reply_markup=markup)
        except Exception:
            bot.send_message(chat, text, reply_markup=markup)

    bot.answer_callback_query(call.id, "Harakat qayd etildi.")

@bot.callback_query_handler(func=lambda call: call.data == "play_again")
def callback_play_again(call):
    bot.answer_callback_query(call.id)
    chat = call.message.chat.id
    # simulate as if user sent /battle
    fake_msg = types.Message()  # not used
    # call the command function to start a new session
    cmd_battle(call.message)

# ==== background cleaning thread ====
def cleanup_sessions():
    while True:
        now = time.time()
        to_del = []
        for k,s in list(sessions.items()):
            if now - s.get("last_action_time", now) > 60*15:  # 15 min timeout
                to_del.append(k)
        for k in to_del:
            del sessions[k]
        time.sleep(60)

if __name__ == "__main__":
    init_db()
    t = threading.Thread(target=cleanup_sessions, daemon=True)
    t.start()
    print("Bot ishga tayyor. Polling boshlanmoqda...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
