import discord
from discord import app_commands, Embed, ButtonStyle
from discord.ext import tasks
from discord.ui import View, Button
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta
from pytz import timezone
import os, json

TOKEN = os.getenv("DISCORD_TOKEN")  # hoặc gán trực tiếp: TOKEN = "YOUR_TOKEN"
GUILD_ID = 1388137676900663347
CHANNEL_ID = 1391086941834838078
TIMEZONE = timezone("Asia/Ho_Chi_Minh")
DATA_FILE = "checkin_data.json"

# Flask keep-alive
app = Flask('')
@app.route('/')
def home():
    return "Bot is running!"
def keep_alive():
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

# Utility
def get_today_key():
    return datetime.now(TIMEZONE).strftime('%Y-%m-%d')
def get_today_display():
    return datetime.now(TIMEZONE).strftime('%d/%m/%Y')
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, 'r') as f:
        return json.load(f)
def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
def get_members(guild):
    return [m for m in guild.members if not m.bot]

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Lệnh /checkin
@tree.command(name="checkin", description="Điểm danh kèm ảnh (trước 7h)", guild=discord.Object(id=GUILD_ID))
async def checkin(interaction: discord.Interaction, image: discord.Attachment):
    if interaction.channel.id != CHANNEL_ID:
        await interaction.response.send_message("❌ Lệnh này chỉ dùng trong kênh GM: good morning.", ephemeral=True)
        return
    now = datetime.now(TIMEZONE)
    if now.hour >= 7:
        await interaction.response.send_message("❌ Đã quá giờ điểm danh hôm nay (sau 7h).", ephemeral=True)
        return
    if not image.content_type.startswith("image"):
        await interaction.response.send_message("❌ Thiếu ảnh. Không được điểm danh.", ephemeral=True)
        return
    user_id = str(interaction.user.id)
    today = get_today_key()
    data = load_data()
    data.setdefault(user_id, {"checkins": [], "missed_weeks": 0, "fine": 0, "paid": 0, "proof": {}, "weeks_fined": []})
    if today in data[user_id]["checkins"]:
        await interaction.response.send_message("❌ Bạn đã điểm danh hôm nay rồi.", ephemeral=True)
        return
    data[user_id]["checkins"].append(today)
    data[user_id]["proof"][today] = {"image": image.url, "time": now.strftime('%H:%M')}
    save_data(data)
    embed = Embed(title=f"✅ Đã điểm danh ngày {get_today_display()}!", color=discord.Color.green())
    embed.set_image(url=image.url)
    await interaction.response.send_message(embed=embed)

# Lệnh /fine
@tree.command(name="fine", description="Xem và thanh toán tiền phạt", guild=discord.Object(id=GUILD_ID))
async def fine(interaction: discord.Interaction):
    if interaction.channel.id != CHANNEL_ID:
        await interaction.response.send_message("❌ Lệnh này chỉ dùng trong kênh GM: good morning.", ephemeral=True)
        return
    user_id = str(interaction.user.id)
    data = load_data()
    user = data.setdefault(user_id, {"checkins": [], "missed_weeks": 0, "fine": 0, "paid": 0, "proof": {}, "weeks_fined": []})
    remaining = user["fine"] - user["paid"]

    if user["missed_weeks"] == 0 and user["fine"] == 0:
        msg = f"📄 PHẠT – <@{user_id}>\nBạn chưa từng bị phạt. Tiếp tục giữ phong độ nhé! 💪"
        await interaction.response.send_message(msg)
        return

    view = None
    if remaining > 0:
        class PayView(View):
            @discord.ui.button(label="✅ Đã thanh toán thêm 100k", style=ButtonStyle.success)
            async def pay(self, i: discord.Interaction, b: Button):
                if i.user.id != interaction.user.id:
                    await i.response.send_message("❌ Bạn không thể thanh toán thay người khác!", ephemeral=True)
                    return
                if user["paid"] >= user["fine"]:
                    await i.response.send_message("✅ Bạn đã thanh toán đầy đủ rồi!", ephemeral=True)
                    return
                user["paid"] += 100000
                save_data(data)
                new_remain = user["fine"] - user["paid"]
                msg = f"📄 PHẠT – <@{user_id}>\n- Tuần không đạt: {user['missed_weeks']}\n- Tổng phạt: {user['fine']:,} VNĐ\n- Đã trả: {user['paid']:,} VNĐ"
                if new_remain <= 0:
                    msg += "\n✅ Không còn nợ! 🧾"
                    await i.response.edit_message(content=msg, view=None)
                else:
                    msg += f"\n- Còn lại: {new_remain:,} VNĐ"
                    await i.response.edit_message(content=msg, view=self)
        view = PayView()

    msg = f"📄 PHẠT – <@{user_id}>\n- Tuần không đạt: {user['missed_weeks']}\n- Tổng phạt: {user['fine']:,} VNĐ\n- Đã trả: {user['paid']:,} VNĐ"
    if remaining <= 0:
        msg += "\n✅ Không còn nợ! 🧾"
    else:
        msg += f"\n- Còn lại: {remaining:,} VNĐ"
    await interaction.response.send_message(msg, view=view)

# Lệnh /report
@tree.command(name="report", description="Xem báo cáo điểm danh tuần", guild=discord.Object(id=GUILD_ID))
async def report(interaction: discord.Interaction):
    if interaction.channel.id != CHANNEL_ID:
        await interaction.response.send_message("❌ Lệnh này chỉ dùng trong kênh GM: good morning.", ephemeral=True)
        return
    data = load_data()
    members = get_members(interaction.guild)
    today = datetime.now(TIMEZONE)
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    dates = [(monday + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
    week_key = monday.strftime('%Y-%m-%d')
    passed, failed = [], []
    for m in members:
        uid = str(m.id)
        d = data.setdefault(uid, {"checkins": [], "missed_weeks": 0, "fine": 0, "paid": 0, "proof": {}, "weeks_fined": []})
        count = sum(1 for day in dates if day in d["checkins"])
        if count >= 5:
            passed.append(m.mention)
        else:
            failed.append(m.mention)
            if week_key not in d["weeks_fined"]:
                d["missed_weeks"] += 1
                d["fine"] += 100000
                d["weeks_fined"].append(week_key)
    save_data(data)
    start = monday.strftime('%d/%m')
    end = sunday.strftime('%d/%m')
    msg = f"📊 TUẦN {start} – {end}\n\n"
    if passed:
        msg += f"✅ {', '.join(passed)}\n"
    if failed:
        msg += f"❌ {', '.join(failed)}\n"
    if passed and not failed:
        msg += "🎉 Tất cả mọi người đều đạt! Tuyệt vời! 💪"
    elif failed and not passed:
        msg += "🚫 Tuần này không ai đạt."
    await interaction.response.send_message(msg)

# Lệnh /history
@tree.command(name="history", description="Xem toàn bộ lịch sử điểm danh", guild=discord.Object(id=GUILD_ID))
async def history(interaction: discord.Interaction):
    if interaction.channel.id != CHANNEL_ID:
        await interaction.response.send_message("❌ Lệnh này chỉ dùng trong kênh GM: good morning.", ephemeral=True)
        return
    user_id = str(interaction.user.id)
    data = load_data()
    d = data.get(user_id, {})
    checkins = set(d.get("checkins", []))
    proof = d.get("proof", {})
    if not checkins:
        await interaction.response.send_message("📭 Bạn chưa có dữ liệu điểm danh nào.")
        return
    first_day = min(datetime.strptime(day, "%Y-%m-%d") for day in checkins)
    today = datetime.now(TIMEZONE)
    lines = []
    current = first_day
    while current <= today:
        key = current.strftime('%Y-%m-%d')
        label = current.strftime('%d/%m/%Y')
        if key in checkins and key in proof:
            lines.append(f"📅 {label} – ✅ lúc {proof[key]['time']}")
        else:
            lines.append(f"📅 {label} – ❌")
        current += timedelta(days=1)
    msg = f"🕓 LỊCH SỬ ĐIỂM DANH – <@{user_id}>\n\n" + "\n".join(lines)
    await interaction.response.send_message(msg)

# Schedule tự động
@tasks.loop(minutes=1)
async def schedule_tasks():
    now = datetime.now(TIMEZONE)
    if now.strftime('%A %H:%M') == 'Sunday 20:00':
        class DummyInteraction:
            def __init__(self, guild): self.guild = guild; self.channel = guild.get_channel(CHANNEL_ID)
        await report(DummyInteraction(client.get_guild(GUILD_ID)))

@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"✅ Bot đã kết nối: {client.user}")
    schedule_tasks.start()

# Run bot
keep_alive()
client.run(TOKEN)
