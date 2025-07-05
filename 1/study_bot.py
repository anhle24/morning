# attendance_fine_bot.py

import discord
from discord import app_commands
from discord.ext import tasks
from discord.ui import Button, View
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta
from pytz import timezone
import os, json

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1388137676900663347
CHANNEL_ID = 1391086941834838078  # Updated channel ID
TIMEZONE = timezone("Asia/Ho_Chi_Minh")
DATA_FILE = "checkin_data.json"

app = Flask('')
@app.route('/')
def home(): return "Bot is running!"
def keep_alive(): Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

def load_data():
    if not os.path.exists(DATA_FILE): return {}
    with open(DATA_FILE, 'r') as f: return json.load(f)

def save_data(data):
    with open(DATA_FILE, 'w') as f: json.dump(data, f, indent=2)

def get_today():
    return datetime.now(TIMEZONE).strftime('%Y-%m-%d')

def get_week_range():
    today = datetime.now(TIMEZONE)
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime('%d/%m'), sunday.strftime('%d/%m')

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def get_members(guild):
    return [m for m in guild.members if not m.bot]

@tree.command(name="checkin", description="Điểm danh kèm ảnh (trước 7h)", guild=discord.Object(id=GUILD_ID))
async def checkin(interaction: discord.Interaction, image: discord.Attachment):
    now = datetime.now(TIMEZONE)
    if now.hour >= 7:
        await interaction.response.send_message("❌ Đã quá giờ điểm danh hôm nay (sau 7h).", ephemeral=True)
        return
    if not image.content_type.startswith("image"):
        await interaction.response.send_message("❌ Thiếu ảnh. Không được điểm danh.", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    today = get_today()
    data = load_data()
    data.setdefault(user_id, {"checkins": [], "missed_weeks": 0, "fine": 0, "paid": 0, "proof": {}})
    if today not in data[user_id]["checkins"]:
        data[user_id]["checkins"].append(today)
        data[user_id]["proof"][today] = image.url
        save_data(data)
    await interaction.response.send_message(
        f"✅ Đã điểm danh {today}!\n📸 Ảnh đã ghi nhận. 💪",
        ephemeral=False
    )

@tree.command(name="fine", description="Xem và thanh toán tiền phạt", guild=discord.Object(id=GUILD_ID))
async def fine(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    data = load_data()
    d = data.get(user_id, {"missed_weeks": 0, "fine": 0, "paid": 0})
    if d["fine"] == 0:
        await interaction.response.send_message("📄 **PHẠT – <@{}>**\nBạn chưa từng bị phạt. Tiếp tục giữ phong độ nhé! 💪".format(user_id), ephemeral=False)
        return

    remaining = d["fine"] - d["paid"]
    view = None
    if remaining > 0:
        class PayView(View):
            @discord.ui.button(label="✅ Đã thanh toán thêm 100k", style=discord.ButtonStyle.success)
            async def pay(self, i: discord.Interaction, b: Button):
                d["paid"] += 100000
                save_data(data)
                new_remain = d["fine"] - d["paid"]
                msg = f"📄 **PHẠT – <@{user_id}>**\n- Tuần không đạt: {d['missed_weeks']}\n- Tổng phạt: {d['fine']:,} VNĐ\n- Đã trả: {d['paid']:,} VNĐ"
                if new_remain <= 0:
                    msg += "\n✅ Không còn nợ! 🧾"
                    await i.response.edit_message(content=msg, view=None)
                else:
                    msg += f"\n- Còn lại: {new_remain:,} VNĐ"
                    await i.response.edit_message(content=msg, view=self)
        view = PayView()

    msg = f"📄 **PHẠT – <@{user_id}>**\n- Tuần không đạt: {d['missed_weeks']}\n- Tổng phạt: {d['fine']:,} VNĐ\n- Đã trả: {d['paid']:,} VNĐ"
    if remaining <= 0:
        msg += "\n✅ Không còn nợ! 🧾"
    else:
        msg += f"\n- Còn lại: {remaining:,} VNĐ"

    await interaction.response.send_message(msg, view=view, ephemeral=False)

@tree.command(name="report", description="Xem báo cáo điểm danh tuần", guild=discord.Object(id=GUILD_ID))
async def report(interaction: discord.Interaction):
    data = load_data()
    members = get_members(interaction.guild)
    today = datetime.now(TIMEZONE)
    monday = today - timedelta(days=today.weekday())
    dates = [(monday + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
    lines, total_fine = [], 0
    for m in members:
        uid = str(m.id)
        d = data.get(uid, {})
        days = [d.get("checkins", []).count(day) for day in dates]
        count = sum(1 for day in dates if day in d.get("checkins", []))
        if count < 5:
            lines.append(f"<@{uid}>: ❌ {count} ngày → 💸 Phạt 100.000 VNĐ")
            total_fine += 100000
        else:
            lines.append(f"<@{uid}>: ✅ {count} ngày")
    start, end = get_week_range()
    header = f"📊 TỔNG KẾT ĐIỂM DANH TUẦN ({start} – {end})"
    footer = f"\n💰 TỔNG TIỀN PHẠT: {total_fine:,} VNĐ"
    await interaction.response.send_message(f"{header}\n\n" + "\n".join(lines) + footer, ephemeral=False)

@tasks.loop(minutes=1)
async def schedule_tasks():
    now = datetime.now(TIMEZONE)
    if now.strftime('%H:%M') == '07:00':
        guild = client.get_guild(GUILD_ID)
        channel = guild.get_channel(CHANNEL_ID)
        members = get_members(guild)
        data = load_data()
        today = get_today()
        missed = []
        for m in members:
            uid = str(m.id)
            if today not in data.get(uid, {}).get("checkins", []):
                missed.append(m.mention)
        if missed:
            msg = f"📢 KẾT THÚC – {now.strftime('%A (%d/%m/%Y)')}\n\n❌ Những người không điểm danh hôm nay:\n" + " ".join(missed) + "\n\n👉 Tính là bỏ cuộc hôm nay. Tự giác lên nhé!"
        else:
            msg = f"📢 KẾT THÚC – {now.strftime('%A (%d/%m/%Y)')}\n✅ Mọi người đã điểm danh đúng giờ! 🔥"
        await channel.send(msg)

    if now.strftime('%A %H:%M') == 'Sunday 20:00':
        # Tự động gửi báo cáo tuần
        class DummyInteraction:
            def __init__(self, guild): self.guild = guild
            async def response(self): pass
        await report(DummyInteraction(client.get_guild(GUILD_ID)))

@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"✅ Bot đã kết nối: {client.user}")
    schedule_tasks.start()

keep_alive()
client.run(TOKEN)
