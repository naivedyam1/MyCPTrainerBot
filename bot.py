import nest_asyncio
nest_asyncio.apply()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, ConversationHandler, filters
import asyncio
import sqlite3
import requests
import random
import time
import uuid
from pytz import timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler


#---------------------------------------------DATABASE--------------------------------------------------------
conn = sqlite3.connect("mycptrainer.db")
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        handle TEXT UNIQUE,
        chat_id INTEGER UNIQUE,
        rating INTEGER,
        rank TEXT,
        streak INTEGER DEFAULT 0
    )
    '''
)

conn.commit()
conn.close()

def add_user(handle: str, chat_id:int, rating: int, rank: str):
    conn = sqlite3.connect("mycptrainer.db")
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT INTO users (handle, chat_id, rating, rank, streak)
        VALUES(?, ?, ?, ?, ?)
        ''',(handle, chat_id, rating,rank,0))
        conn.commit()
        print("User added")
    except sqlite3.IntegrityError:
        print("User already exists!")
    finally:
        conn.close()

def get_user(handle: str):
    conn = sqlite3.connect("mycptrainer.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE handle = ?", (handle,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_user_rating(handle:str, new_rating:int):
    conn = sqlite3.connect("mycptrainer.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET rating = ? WHERE handle = ?", (new_rating, handle))
    conn.commit()
    conn.close()

def delete_user(handle: str):
    conn = sqlite3.connect("mycptrainer.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE handle = ?", (handle,))
    conn.commit()
    conn.close()

def update_daily_streak(handle: str):
    conn = sqlite3.connect("mycptrainer.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET streak = streak + 1 WHERE handle = ?", (handle,))
    conn.commit()
    conn.close()

def reset_daily_streak(handle: str):
    conn = sqlite3.connect("mycptrainer.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET streak = 0 WHERE handle = ?", (handle,))
    conn.commit()
    conn.close()

def get_leaderboard(limit=10):
    conn = sqlite3.connect("mycptrainer.db")
    cursor = conn.cursor()
    cursor.execute("SELECT handle, streak FROM users ORDER BY streak DESC LIMIT ?", (limit,))
    leaderboard = cursor.fetchall()
    conn.close()
    return leaderboard


#--------------------------------------------CODEFORCES API-----------------------------------------------------------



def get_problems():
    url = "https://codeforces.com/api/problemset.problems"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['status'] == 'OK':
            return data['result']['problems']
        else:
            print("Unknown Error from API")
            return []
    else:
        print("HTTP ERROR: " + str(response.status_code))
        return []


def problems_solved(handle: str):
    url = f"https://codeforces.com/api/user.status?handle={handle}"
    response = requests.get(url)
    solved = set()
    if response.status_code == 200:
        data = response.json()
        if data['status'] == 'OK':
            for submission in data['result']:
                if submission.get('verdict') == 'OK':
                    problem = submission['problem']
                    problem_id = f'{problem.get("contestId", 0)}_{problem.get("index","")}'
                    solved.add(problem_id)
    return solved

def select_problem(problems, rating:int, solved:set):
    target_rating = round(rating/100)*100
    candidates = [
        p for p in problems
        if p.get("rating") == target_rating and f'{p.get("contestId", 0)}_{p.get("index", "")}' not in solved and "*special" not in p.get("tags", [])
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.get("contestId", 0), reverse=True)
    index = random.randint(0,30)
    return candidates[index]

def get_user_data(handle: str):
    url = f"https://codeforces.com/api/user.info?handles={handle}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['status'] == "OK":
            user_info = data['result'][0]
            rating = user_info.get("rating", "This person is unrated.")
            rank = user_info.get("rank", "NA")
            return rating, rank
        else:
            return "Sorry! Looks like you are facting the Error- \n" + data.get("comment", "Unknown Error")
    else:
        return "Incorrect username. Please crosscheck it again for any typos. Type the exact username only."

async def assign_problems(handle:str):
    problems = get_problems()
    solved = problems_solved(handle)
    rating, rank = get_user_data(handle)
    try:
        rating = max(rating, 800)
    except ValueError:
        rating = 800
    easy_problem = select_problem(problems, rating, solved)
    hard_problem = select_problem(problems, rating+200, solved)
    return easy_problem, hard_problem

async def send_problems():
    handle = "naivedyam"
    easy, hard = await assign_problems(handle)
    url_easy = "https://codeforces.com/problemset/problem/" + str(easy['contestId']) + "/" + easy['index']
    url_hard = "https://codeforces.com/problemset/problem/" + str(hard['contestId']) + "/" + hard['index']
    message = "Here are your problems for today: \n \n" + url_easy + "\n \n" + url_hard
    print(message)

daily_assignments = {}

def store_assignment(handle: str, assignment: str, problems: dict):
    daily_assignments[handle] = {
        "assignment": assignment,
        "problems": problems,
        "assigned_time": time.time(),
        "solved": False
    }

def get_assigment(handle:str):
    return daily_assignments.get(handle)

#----------------------------------------BOT-----------------------------------------------------------------

VERIFY_CODEFORCES, COMPLETE_VERIFICATION = range(2)

pending_verifications = {}

TOKEN = '7806890541:AAHKfWX3pAT6jPiPnog7W5xlEJOODxwF9BI'

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Welcome to MyCPTrainer, your very own personal tutor for competitive programming.! Please type /help to see the available commands.\n \n"
                                    "To use this bot you first need to verify your codeforces handle. Send /verify <your_codeforces_username> to do so. \n"
                                    "Example usage - /verify naivedyam.")



def get_submissions(handle:str, problem):
    url = f"https://codeforces.com/api/user.status?handle={handle}"
    response = requests.get(url)
    submissions = []
    if response.status_code == 200:
        data = response.json()
        if data['status'] == "OK":
            for submission in data['result']:
                p = submission.get('problem',{})
                if p.get("contestId") == problem.get("contestId") and p.get("index") == problem.get("index"):
                    submissions.append(submission)

    return submissions


async def verify_handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /verify <your handle>\nFor example: /verify naivedyam"
        )
        return
    handle = context.args[0]
    token = str(uuid.uuid4())[:8]
    problems = get_problems()
    if not problems:
        await update.message.reply_text("Error getting a problem. Please try later.")
        return
    random_problem = random.choice(problems)
    url = f"https://codeforces.com/problemset/problem/{random_problem['contestId']}/{random_problem['index']}"
    pending_verifications[handle] = {
        'token': token,
        'problem': random_problem,
        'timestamp': time.time()
    }
    message = (
        f"To verify your handle, please submit a compile error on this problem:\n{url}\n\n"
        f"Include the following token in your submission:\n\n{token}\n\n"
        "You have 5 minutes to do this.\n \n"
        "After you are done with sending the compilation error with the given code, \n"
        "send a command /complete_verification <handle>. Example usage - /complete_verification naivedyam."
    )
    await update.message.reply_text(message)


async def complete_verification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /complete_verification <handle>\nExample: /complete_verification naivedyam"
        )
        return
    handle = context.args[0]
    if handle not in pending_verifications:
        await update.message.reply_text("No pending verification found. Please use /verify first.")
        return
    verification_data = pending_verifications[handle]
    if time.time() - verification_data['timestamp'] > 300:
        del pending_verifications[handle]
        await update.message.reply_text("Verification timed out. Please try verifying again.")
        return
    problem = verification_data['problem']
    token = verification_data['token']
    submissions = get_submissions(handle, problem)
    verified = False
    for submission in submissions:
        if submission.get('verdict') == 'COMPILATION_ERROR':
            verified = True
            break
    if verified:
        rating, rank = get_user_data(handle)
        try:
            rating = int(rating)
        except (ValueError, TypeError):
            rating = 800
        chat_id = update.effective_chat.id
        add_user(handle, chat_id, rating, rank)
        easy, hard = await assign_problems(handle)
        url_easy = f"https://codeforces.com/problemset/problem/{easy['contestId']}/{easy['index']}"
        url_hard = f"https://codeforces.com/problemset/problem/{hard['contestId']}/{hard['index']}"
        assignment_message = f"Here are your problems for today:\n\n{url_easy}\n\n{url_hard}"
        store_assignment(handle, assignment_message, {"easy": easy, "hard": hard})
        del pending_verifications[handle]
        await update.message.reply_text("Verification Successful! You can now use the bot.\n\n" + assignment_message)
    else:
        await update.message.reply_text(
            "Verification Failed! Please try again by submitting a compile error with the provided token."
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = "Here are the commans you can use:\n" \
                "/start - Begin your training\n" \
                "/help - Check for available commands.\n" \
                "/about - Know about our purpose.\n" \
                "/leaderboard - See the most consistent competitive programmers.\n" \
                "/my_streak - Look at your current streak.\n" \
                "/verify - Verify your codeforces handle. \n" \
                "/complete_verification - Complete your verification if you tried verifying before. \n" \
                "/current - Check today's problems."
    await update.message.reply_text(help_text)


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    about_text = "Welcome to MyCPTrainer - your own personal trainer to train your" \
                 "way to your dream titles on Codeforces. My main job is to provide you" \
                 "the right kind of problems for you to improve and your job is to" \
                 "try to maintain your streak ethically. Each day you solve the two problems" \
                 "I give you, your daily streak would increase by one. But a day missed and the" \
                 "streak is gone! However, be honest with yourself through the journey and try not to" \
                 "see the editorial or copy paste the code until you have given the problems a fair" \
                 "try of atleast 2 hours each. However, try to solve the easier ones in 30 mins and the" \
                 "harder ones in an hour or two."
    await update.message.reply_text(about_text)


async def show_streak(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    handle = context.args[0] if context.args else "naivedyam"
    conn = sqlite3.connect("mycptrainer.db")
    cursor = conn.cursor()
    cursor.execute("SELECT streak FROM users WHERE handle = ?", (handle,))
    result = cursor.fetchone()
    conn.close()
    if result:
        await update.message.reply_text(f'Your current streak is {result[0]}')
    else:
        await update.message.reply_text(f'Your current streak is 0')


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    leaderboard = get_leaderboard()
    message = "Most Consistent Performers: \n \n"
    for rank, (handle, streak) in enumerate(leaderboard, start=1):
        message += f'{rank}. {handle} - {streak}\n'
    await update.message.reply_text(message)



async def current_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /current <codeforces_handle>")
        return
    handle = context.args[0]
    record = get_user(handle)
    if not record:
        await update.message.reply_text("User not registered with us. Please verify this handle first to get your daily problems.")
        return
    assignment_data = get_assigment(handle)
    if assignment_data:
        assigned_problems = assignment_data.get("problems", {})
        easy_problem = assigned_problems.get("easy")
        hard_problem = assigned_problems.get("hard")
        solved_set = problems_solved(handle)
        def problem_id(problem):
            return f"{problem.get('contestId')}_{problem.get('index')}" if problem else None
        easy_id = problem_id(easy_problem)
        hard_id = problem_id(hard_problem)
        if easy_id and hard_id and easy_id in solved_set and hard_id in solved_set:
            await update.message.reply_text("Congratulations, you solved today's problems!")
        else:
            await update.message.reply_text("Today's problems:\n" + assignment_data["assignment"])
    else:
        await update.message.reply_text("Congratulations! You solved today's problems! New problems will be assigned at midnight.")


async def midnight_assignment_job(application):
    conn = sqlite3.connect("mycptrainer.db")
    cursor = conn.cursor()
    cursor.execute("SELECT handle, chat_id FROM users")
    users = cursor.fetchall()
    conn.close()
    for (handle, chat_id) in users:
        easy, hard = await assign_problems(handle)
        url_easy = f"https://codeforces.com/problemset/problem/{easy['contestId']}/{easy['index']}"
        url_hard = f"https://codeforces.com/problemset/problem/{hard['contestId']}/{hard['index']}"
        assignment_message = f"Here are your problems for today:\n\n{url_easy}\n\n{url_hard}"
        store_assignment(handle, assignment_message, {'easy':easy, 'hard':hard})
        try:
            await application.bot.send_message(chat_id=chat_id, text=assignment_message)
            print(f"Assignment sent to {handle} (chat id: {chat_id}).")
        except Exception as e:
            print(f"Failed to send assignment to {handle} (chat id: {chat_id}): {e}")



async def reminder(application):
    for handle, data in daily_assignments.items():
        if not data["solved"]:
            user_record = get_user(handle)
            if user_record:
                chat_id = user_record[2]
                try:
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=f"Reminder: {handle}, you haven't completed your assigned problems for today yet. Please do so to not lose your streak!"
                    )
                except Exception as e:
                    print(f"Error sending reminder to {handle} (chat id: {chat_id}): {e}")
            else:
                print(f"User {handle} not found in database.")



async def daily_update_job():
    for handle, data in daily_assignments.items():
        problems_dict = data.get("problems", {})
        if not problems_dict:
            continue
        def problem_id(problem):
            if not problem:
                return None
            return f"{problem.get('contestId')}_{problem.get('index')}"
        easy_problem = problems_dict.get("easy")
        hard_problem = problems_dict.get("hard")
        easy_id = problem_id(easy_problem)
        hard_id = problem_id(hard_problem)
        solved_set = problems_solved(handle)
        if easy_id in solved_set and hard_id in solved_set:
            update_daily_streak(handle)
            print(f"Streak updated for {handle}.")
        else:
            reset_daily_streak(handle)
            print(f"Streak reset for {handle}.")




async def main() -> None:
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('about', about))
    application.add_handler(CommandHandler('leaderboard', show_leaderboard))
    application.add_handler(CommandHandler('my_streak', show_streak))
    application.add_handler(CommandHandler("verify", verify_handle))
    application.add_handler(CommandHandler("complete_verification", complete_verification))
    application.add_handler(CommandHandler("current", current_command))

    scheduler = AsyncIOScheduler(timezone=timezone('Asia/Kolkata'))
    scheduler.add_job(daily_update_job, 'cron', hour=23, minute=50)
    scheduler.add_job(midnight_assignment_job, 'cron', args=[application], hour=0, minute=0)
    scheduler.add_job(reminder, 'cron', args=[application], hour=6, minute=0)
    scheduler.add_job(reminder, 'cron', args=[application], hour=9, minute=0)
    scheduler.add_job(reminder, 'cron', args=[application], hour=12, minute=0)
    scheduler.add_job(reminder, 'cron', args=[application], hour=15, minute=0)
    scheduler.add_job(reminder, 'cron', args=[application], hour=18, minute=0)
    scheduler.add_job(reminder, 'cron', args=[application], hour=21, minute=0)
    scheduler.add_job(reminder, 'cron', args=[application], hour=22, minute=30)

    scheduler.start()

    print("Bot is running.")
    await application.run_polling(close_loop=False)


if __name__ == '__main__':
    asyncio.run(main())


