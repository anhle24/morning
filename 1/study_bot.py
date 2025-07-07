import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button
from datetime import datetime, timedelta
from pytz import timezone
from flask import Flask
from threading import Thread
import aiohttp
from io import BytesIO
import os, json, asyncio

# === CONFIG ===
GUILD_ID = 1388137676900663347
CHANNEL_ID = 1391086941834838078
TIMEZONE = timezone("Asia/Ho_Chi_Minh")
DATA_FILE = "checkin_data.json"
TOKEN = os.getenv("DISCORD_TOKEN")

# === DISCORD CLIENT ===
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
client = commands.Bot(command_prefix="/", intents=intents)
tree = client.tree

# === KEEP ALIVE ===
app = Flask('')
@app.route('/')
def home(): return "Bot is running!"
def keep_alive(): Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

# === UTILS ===
def load_data():
    if not os.path.exists(DATA_FILE): return {}
    with open(DATA_FILE, 'r') as f: return json.load(f)

def save_data(data):
    with open(DATA_FILE, 'w') as f: json.dump(data, f, indent=2)

def get_today(): return datetime.now(TIMEZONE).strftime('%Y-%m-%d')
def get_today_display(): return datetime.now(TIMEZONE).strftime('%d/%m/%Y')

def get_monday_key(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TIMEZONE)
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime('%Y-%m-%d')

def get_week_range(week_key):
    start = datetime.strptime(week_key, "%Y-%m-%d").replace(tzinfo=TIMEZONE)
    end = start + timedelta(days=6)
    return f"({start.strftime('%d/%m/%Y')} – {end.strftime('%d/%m/%Y')})"

# === /checkin ===
@tree.command(name="checkin", description="Điểm danh kèm ảnh (trước 7h)", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(image="Ảnh minh chứng")
async def checkin(interaction: discord.Interaction, image: discord.Attachment):
    try:
        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("❌ Lệnh này chỉ dùng trong kênh GM.", ephemeral=True)
            return

        now = datetime.now(TIMEZONE)
        if now.hour >= 7:
            await interaction.response.send_message("❌ Đã quá giờ điểm danh hôm nay.", ephemeral=True)
            return

        if not image.content_type.startswith("image"):
            await interaction.response.send_message("❌ Thiếu ảnh. Không được điểm danh.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        today = get_today()
        data = load_data()
        user = data.setdefault(user_id, {
            "checkins": [], "missed_weeks": 0, "fine": 0, "paid": 0,
            "proof": {}, "weeks": {}
        })

        if today in user["checkins"]:
            await interaction.response.send_message("❌ Bạn đã điểm danh hôm nay rồi.", ephemeral=True)
            return

        user["checkins"].append(today)
        user["proof"][today] = {"image": image.url, "time": now.strftime('%H:%M')}
        save_data(data)

        async with aiohttp.ClientSession() as session:
            async with session.get(image.url) as resp:
                if resp.status == 200:
                    img_bytes = BytesIO(await resp.read())
                    discord_file = discord.File(img_bytes, filename=image.filename)
                    await interaction.response.send_message(
                        content=f"✅ <@{interaction.user.id}> đã điểm danh ngày {get_today_display()}!",
                        file=discord_file,
                        ephemeral=False
                    )
    except Exception as e:
        print("[LỖI /checkin]", e)
        await interaction.response.send_message("⚠ Đã xảy ra lỗi khi điểm danh.", ephemeral=True)

# === /history ===
@tree.command(name="history", description="Xem lịch sử điểm danh", guild=discord.Object(id=GUILD_ID))
async def history(interaction: discord.Interaction):
    try:
        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("❌ Lệnh này chỉ dùng trong kênh GM.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        data = load_data()
        user = data.get(user_id, {})
        checkins = set(user.get("checkins", []))
        proof = user.get("proof", {})

        if not checkins:
            await interaction.response.send_message(f"📜 LỊCH SỬ – <@{user_id}>\n\nBạn chưa có lịch sử điểm danh nào.", ephemeral=False)
            return

        first_day = min(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=TIMEZONE) for day in checkins)
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

        msg = f"📜 LỊCH SỬ – <@{user_id}>\n\n" + "\n".join(lines)
        await interaction.response.send_message(msg, ephemeral=False)
    except Exception as e:
        print("[LỖI /history]", e)
        await interaction.response.send_message("⚠ Đã xảy ra lỗi khi hiển thị lịch sử.", ephemeral=True)

# === /report ===
@tree.command(name="report", description="Tổng kết tuần (thủ công, không phạt)", guild=discord.Object(id=GUILD_ID))
async def report(interaction: discord.Interaction):
    try:
        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("❌ Lệnh này chỉ dùng trong kênh GM.", ephemeral=True)
            return

        data = load_data()
        today = datetime.now(TIMEZONE).date()
        monday = today - timedelta(days=today.weekday())
        week_days = [(monday + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
        members = interaction.guild.members

        passed, failed = [], []
        for m in members:
            if m.bot: continue
            uid = str(m.id)
            user = data.setdefault(uid, {
                "checkins": [], "missed_weeks": 0, "fine": 0, "paid": 0,
                "proof": {}, "weeks": {}
            })
            count = len([d for d in week_days if d in user["checkins"]])
            if count >= 5:
                passed.append(m.mention)
            else:
                failed.append(m.mention)

        week_range = f"{monday.strftime('%d/%m')} – {(monday + timedelta(days=6)).strftime('%d/%m')}"
        msg = f"📊 TIẾN ĐỘ TUẦN {week_range}\n\n"
        if passed: msg += f"✅ {', '.join(passed)}\n"
        if failed: msg += f"❌ {', '.join(failed)}\n"
        msg += "\n⏳ Cần ≥5d để không bị phạt!"

        await interaction.response.send_message(msg, ephemeral=False)
    except Exception as e:
        print("[LỖI /report]", e)
        await interaction.response.send_message("⚠ Đã xảy ra lỗi khi tổng kết tuần.", ephemeral=True)

# === /fine ===
@tree.command(name="fine", description="Xem và thanh toán tiền phạt", guild=discord.Object(id=GUILD_ID))
async def fine(interaction: discord.Interaction):
    try:
        if interaction.channel.id != CHANNEL_ID:
            await interaction.response.send_message("❌ Lệnh này chỉ dùng trong kênh GM.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        data = load_data()
        user = data.setdefault(user_id, {
            "checkins": [], "missed_weeks": 0, "fine": 0, "paid": 0,
            "proof": {}, "weeks": {}
        })
        debt = user["fine"] - user["paid"]

        if user["fine"] == 0:
            await interaction.response.send_message(f"🥳 <@{user_id}> chưa từng bị phạt tuần nào! Giữ vững phong độ nhé! 💪", ephemeral=False)
            return

        msg = f"📄 PHẠT – <@{user_id}>\n\n- Tuần không đạt: {user['missed_weeks']}\n- Tổng phạt: {user['fine']:,} VNĐ\n- Đã trả: {user['paid']:,} VNĐ\n"
        if debt > 0:
            msg += f"- Còn lại: {debt:,} VNĐ"

            class PayFineView(View):
                def __init__(self, user_id): super().__init__(timeout=None); self.user_id = user_id

                @discord.ui.button(label="✅ Đã thanh toán thêm 100k", style=discord.ButtonStyle.success)
                async def pay(self, btn: discord.Interaction, button: Button):
                    if str(btn.user.id) != self.user_id:
                        await btn.response.send_message("❌ Bạn không thể thanh toán thay người khác!", ephemeral=True)
                        return
                    user = data[self.user_id]
                    user["paid"] += 100_000
                    save_data(data)
                    new_debt = user["fine"] - user["paid"]
                    new_msg = f"📄 PHẠT – <@{self.user_id}>\n\n- Tuần không đạt: {user['missed_weeks']}\n- Tổng phạt: {user['fine']:,} VNĐ\n- Đã trả: {user['paid']:,} VNĐ\n"
                    if new_debt > 0:
                        new_msg += f"- Còn lại: {new_debt:,} VNĐ"
                        await btn.response.edit_message(content=new_msg, view=self)
                    else:
                        new_msg += "✅ Không còn nợ! 🧾"
                        await btn.response.edit_message(content=new_msg, view=None)

            await interaction.response.send_message(msg, view=PayFineView(user_id), ephemeral=False)
        else:
            msg += "\n✅ Không còn nợ! 🧾"
            await interaction.response.send_message(msg, ephemeral=False)
    except Exception as e:
        print("[LỖI /fine]", e)
        await interaction.response.send_message("⚠ Đã xảy ra lỗi khi xử lý phạt.", ephemeral=True)

# === TÁC VỤ NỀN ===

async def daily_7h_check():
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now(TIMEZONE)
        if now.hour == 7 and now.minute == 0:
            try:
                data = load_data()
                today = get_today()
                channel = client.get_channel(CHANNEL_ID)
                guild = discord.utils.get(client.guilds, id=GUILD_ID)
                members = guild.members
                missing = []
                for m in members:
                    if m.bot: continue
                    uid = str(m.id)
                    udata = data.get(uid, {})
                    if today not in udata.get("checkins", []):
                        missing.append(m.mention)
                if not missing:
                    await channel.send("✅ Tất cả đã điểm danh trước 7h sáng. Tuyệt vời! 💪")
                else:
                    msg = "📢 7h rồi – Chưa điểm danh:\n\n" + "\n".join([f"❌ {m}" for m in missing])
                    await channel.send(msg)
            except Exception as e:
                print("[LỖI daily_7h_check]", e)
            await asyncio.sleep(60)
        await asyncio.sleep(20)

async def auto_report_task():
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now(TIMEZONE)
        if now.weekday() == 6 and now.hour == 20 and now.minute == 0:
            try:
                data = load_data()
                today = now.date()
                monday = today - timedelta(days=today.weekday())
                week_key = monday.strftime('%Y-%m-%d')
                channel = client.get_channel(CHANNEL_ID)
                guild = discord.utils.get(client.guilds, id=GUILD_ID)
                members = guild.members
                passed, failed = [], []
                for m in members:
                    if m.bot: continue
                    uid = str(m.id)
                    user = data.setdefault(uid, {
                        "checkins": [], "missed_weeks": 0, "fine": 0, "paid": 0,
                        "proof": {}, "weeks": {}
                    })
                    week_days = [(monday + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
                    count = len([d for d in week_days if d in user["checkins"]])
                    if count >= 5:
                        passed.append(m.mention)
                        user["weeks"][week_key] = {"reported": True, "status": "pass"}
                    else:
                        failed.append(m.mention)
                        user["weeks"][week_key] = {"reported": True, "status": "fail"}
                        user["missed_weeks"] += 1
                        user["fine"] += 100_000
                save_data(data)
                week_range = f"{monday.strftime('%d/%m')} – {(monday + timedelta(days=6)).strftime('%d/%m')}"
                msg = f"📊 TUẦN {week_range}\n\n"
                if passed: msg += f"✅ {', '.join(passed)}\n"
                if failed: msg += f"❌ {', '.join(failed)}\n"
                if passed and not failed:
                    msg += "🎉 Tất cả mọi người đều đạt! Tuyệt vời! 💪"
                elif failed and not passed:
                    msg += "🚫 Tuần này không ai đạt."
                await channel.send(msg)
            except Exception as e:
                print("[LỖI auto_report_task]", e)
            await asyncio.sleep(60)
        await asyncio.sleep(20)

# === ON READY ===
@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"✅ Bot đã sẵn sàng: {client.user}")
    client.loop.create_task(auto_report_task())
    client.loop.create_task(daily_7h_check())

# === START ===
keep_alive()
client.run(TOKEN)
