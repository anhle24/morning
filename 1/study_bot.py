import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone
import json
import os

TOKEN = os.environ['TOKEN']

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='/', intents=intents)
tree = bot.tree

DATA_FILE = 'checkin_data.json'
vn_tz = timezone(timedelta(hours=7))

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@tree.command(name="in", description="Điểm danh bắt đầu học 📚")
async def checkin(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    now = datetime.now(vn_tz)
    today = now.strftime("%Y-%m-%d")

    data = load_data()
    if user_id not in data:
        data[user_id] = {}
    if today in data[user_id] and "checkin" in data[user_id][today]:
        await interaction.response.send_message("⚠️ Bạn đã điểm danh rồi hôm nay!")
        return

    data[user_id][today] = {"checkin": now.isoformat()}
    save_data(data)

    time_str = now.strftime("%I:%M %p")
    await interaction.response.send_message(f"✅ Đã bắt đầu học lúc {time_str} 🥰")

@tree.command(name="out", description="Kết thúc giờ học 🎓")
async def checkout(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    now = datetime.now(vn_tz)
    today = now.strftime("%Y-%m-%d")

    data = load_data()
    if user_id not in data or today not in data[user_id] or "checkin" not in data[user_id][today]:
        await interaction.response.send_message("⚠️ Bạn chưa điểm danh hôm nay!")
        return

    if "checkout" in data[user_id][today]:
        await interaction.response.send_message("⚠️ Bạn đã kết thúc phiên học rồi!")
        return

    data[user_id][today]["checkout"] = now.isoformat()
    save_data(data)

    time_str = now.strftime("%I:%M %p")
    await interaction.response.send_message(f"✅ Đã kết thúc giờ học vào lúc {time_str} 🥳")

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot đã sẵn sàng dưới tên {bot.user}!")

bot.run(TOKEN)
