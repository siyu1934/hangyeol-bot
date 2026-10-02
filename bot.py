import os
import sqlite3
from datetime import timedelta

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv


# =========================================================
# 기본 설정
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN이 .env에 없습니다.")


intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# =========================================================
# 데이터베이스
# =========================================================

db = sqlite3.connect("warnings.db")
cursor = db.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS warning_settings (
    guild_id INTEGER PRIMARY KEY,
    warning_limit INTEGER NOT NULL DEFAULT 5
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS punishment_log_settings (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL
)
""")


db.commit()


# =========================================================
# 경고 함수
# =========================================================

def get_warning_count(guild_id, user_id):

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM warnings
        WHERE guild_id = ?
        AND user_id = ?
        """,
        (guild_id, user_id)
    )

    return cursor.fetchone()[0]


def add_warning(
    guild_id,
    user_id,
    moderator_id,
    reason,
    amount
):

    for _ in range(amount):

        cursor.execute(
            """
            INSERT INTO warnings
            (
                guild_id,
                user_id,
                moderator_id,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            (
                guild_id,
                user_id,
                moderator_id,
                reason
            )
        )

    db.commit()


def remove_warnings(
    guild_id,
    user_id,
    amount
):

    cursor.execute(
        """
        SELECT id
        FROM warnings
        WHERE guild_id = ?
        AND user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            guild_id,
            user_id,
            amount
        )
    )

    ids = [
        row[0]
        for row in cursor.fetchall()
    ]

    if not ids:
        return 0

    placeholders = ",".join(
        "?" for _ in ids
    )

    cursor.execute(
        f"""
        DELETE FROM warnings
        WHERE id IN ({placeholders})
        """,
        ids
    )

    db.commit()

    return len(ids)


def get_warnings(
    guild_id,
    user_id
):

    cursor.execute(
        """
        SELECT
            id,
            moderator_id,
            reason,
            created_at
        FROM warnings
        WHERE guild_id = ?
        AND user_id = ?
        ORDER BY id DESC
        """,
        (
            guild_id,
            user_id
        )
    )

    return cursor.fetchall()


# =========================================================
# 경고 제한
# =========================================================

def get_warning_limit(guild_id):

    cursor.execute(
        """
        SELECT warning_limit
        FROM warning_settings
        WHERE guild_id = ?
        """,
        (guild_id,)
    )

    result = cursor.fetchone()

    if result:
        return result[0]

    cursor.execute(
        """
        INSERT INTO warning_settings
        (
            guild_id,
            warning_limit
        )
        VALUES (?, 5)
        """,
        (guild_id,)
    )

    db.commit()

    return 5


def set_warning_limit(
    guild_id,
    limit
):

    cursor.execute(
        """
        INSERT INTO warning_settings
        (
            guild_id,
            warning_limit
        )
        VALUES (?, ?)

        ON CONFLICT(guild_id)
        DO UPDATE SET
            warning_limit = excluded.warning_limit
        """,
        (
            guild_id,
            limit
        )
    )

    db.commit()


# =========================================================
# 처벌 로그 채널
# =========================================================

def get_log_channel_id(guild_id):

    cursor.execute(
        """
        SELECT channel_id
        FROM punishment_log_settings
        WHERE guild_id = ?
        """,
        (guild_id,)
    )

    result = cursor.fetchone()

    if result:
        return result[0]

    return None


def set_log_channel(
    guild_id,
    channel_id
):

    cursor.execute(
        """
        INSERT INTO punishment_log_settings
        (
            guild_id,
            channel_id
        )
        VALUES (?, ?)

        ON CONFLICT(guild_id)
        DO UPDATE SET
            channel_id = excluded.channel_id
        """,
        (
            guild_id,
            channel_id
        )
    )

    db.commit()


# =========================================================
# 처벌 대상 확인
# =========================================================

def can_moderate(
    guild,
    moderator,
    target
):

    if target is None:
        return False

    if target == moderator:
        return False

    if target.top_role >= moderator.top_role:
        return False

    if guild.me:

        if target.top_role >= guild.me.top_role:
            return False

    return True


# =========================================================
# 처벌 로그
# =========================================================

async def send_punishment_log(
    guild,
    action,
    target_name,
    target_id,
    moderator,
    reason=None,
    extra=None
):

    channel_id = get_log_channel_id(
        guild.id
    )

    if not channel_id:
        return

    channel = guild.get_channel(
        channel_id
    )

    if not channel:
        return


    titles = {
        "ban": "서버 차단",
        "kick": "서버 추방",
        "unban": "차단 해제",
        "timeout": "타임아웃",
        "warning": "경고 추가",
        "warning_remove": "경고 삭제"
    }


    descriptions = {
        "ban": "멤버가 서버에서 차단되었습니다.",
        "kick": "멤버가 서버에서 추방되었습니다.",
        "unban": "멤버의 서버 차단이 해제되었습니다.",
        "timeout": "멤버에게 타임아웃이 적용되었습니다.",
        "warning": "멤버에게 경고가 추가되었습니다.",
        "warning_remove": "멤버의 경고가 삭제되었습니다."
    }


    embed = discord.Embed(
        title=titles.get(
            action,
            "처벌 기록"
        ),
        description=(
            f"**{target_name}**\n\n"
            f"{descriptions.get(action, '')}"
        ),
        timestamp=discord.utils.utcnow()
    )


    if reason:

        embed.add_field(
            name="사유",
            value=reason,
            inline=False
        )


    if extra:

        embed.add_field(
            name="처리 내용",
            value=extra,
            inline=False
        )


    embed.add_field(
        name="처리자",
        value=(
            f"{moderator.mention}\n"
            f"`{moderator.id}`"
        ),
        inline=True
    )


    embed.add_field(
        name="사용자 ID",
        value=f"`{target_id}`",
        inline=True
    )


    embed.set_footer(
        text="Punishment Log"
    )


    try:

        await channel.send(
            embed=embed
        )

    except (
        discord.Forbidden,
        discord.HTTPException
    ):

        pass


# =========================================================
# DM
# =========================================================

async def send_action_dm(
    member,
    guild,
    action,
    reason,
    extra=None
):

    titles = {
        "ban": "서버에서 차단되었습니다",
        "kick": "서버에서 추방되었습니다",
        "warning": "서버에서 경고를 받았습니다",
        "timeout": "서버에서 타임아웃되었습니다"
    }


    if action not in titles:
        return


    embed = discord.Embed(
        title=titles[action],
        description=(
            f"**{guild.name}**에서 "
            "아래 처리가 이루어졌습니다."
        ),
        timestamp=discord.utils.utcnow()
    )


    if extra:

        embed.add_field(
            name="처리 내용",
            value=extra,
            inline=False
        )


    embed.add_field(
        name="사유",
        value=reason or "사유 없음",
        inline=False
    )


    embed.set_footer(
        text="자동 안내 메시지"
    )


    try:

        await member.send(
            embed=embed
        )

    except (
        discord.Forbidden,
        discord.HTTPException
    ):

        pass


# =========================================================
# ! 명령어 오류
# =========================================================

@bot.event
async def on_command_error(
    ctx,
    error
):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return


    if isinstance(
        error,
        commands.MissingPermissions
    ):

        await ctx.send(
            f"{ctx.author.mention}\n"
            "이 명령어를 사용할 권한이 없습니다."
        )

        return


    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        usages = {

            "ban": (
                "!ban <유저ID> <사유>",
                "!ban 123456789 도배"
            ),

            "밴": (
                "!ban <유저ID> <사유>",
                "!ban 123456789 도배"
            ),

            "unban": (
                "!unban <유저ID>",
                "!unban 123456789"
            ),

            "언밴": (
                "!unban <유저ID>",
                "!unban 123456789"
            ),

            "kick": (
                "!kick <유저ID> <사유>",
                "!kick 123456789 규칙 위반"
            ),

            "킥": (
                "!kick <유저ID> <사유>",
                "!kick 123456789 규칙 위반"
            ),

            "warn": (
                "!warn <유저ID> <횟수> <사유>",
                "!warn 123456789 2 도배"
            ),

            "경고": (
                "!warn <유저ID> <횟수> <사유>",
                "!warn 123456789 2 도배"
            ),

            "warnremove": (
                "!warnremove <유저ID> <횟수>",
                "!warnremove 123456789 1"
            ),

            "경고삭제": (
                "!warnremove <유저ID> <횟수>",
                "!warnremove 123456789 1"
            ),

            "clear": (
                "!clear <개수>",
                "!clear 30"
            ),

            "청소": (
                "!clear <개수>",
                "!clear 30"
            )
        }


        command = ctx.command.name


        if command in usages:

            usage, example = usages[
                command
            ]

            await ctx.send(
                f"{ctx.author.mention}\n\n"
                f"**사용 방법**\n"
                f"`{usage}`\n\n"
                f"**예시**\n"
                f"`{example}`"
            )

        return


    if isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.send(
            f"{ctx.author.mention}\n"
            "입력값이 올바르지 않습니다."
        )

        return


    print(
        f"[명령어 오류] "
        f"{type(error).__name__}: {error}"
    )


# =========================================================
# !청소
# =========================================================

@bot.command(
    name="청소",
    aliases=["clear"]
)
@commands.has_permissions(
    manage_messages=True
)
async def clear_command(
    ctx,
    개수: int
):

    if 개수 < 1 or 개수 > 100:

        await ctx.send(
            f"{ctx.author.mention}\n\n"
            "**사용 방법**\n"
            "`!clear <1~100>`\n\n"
            "**예시**\n"
            "`!clear 30`"
        )

        return


    try:

        deleted = await ctx.channel.purge(
            limit=개수 + 1
        )

        real_count = max(
            len(deleted) - 1,
            0
        )


        msg = await ctx.send(
            f"{ctx.author.mention}\n"
            f"**{real_count}개**의 메시지를 삭제했습니다."
        )


        await msg.delete(
            delay=5
        )


    except discord.Forbidden:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "봇에게 메시지 관리 권한이 없습니다."
        )


# =========================================================
# !밴
# =========================================================

@bot.command(
    name="밴",
    aliases=["ban"]
)
@commands.has_permissions(
    ban_members=True
)
async def ban_command(
    ctx,
    유저: str,
    *,
    사유="사유 없음"
):

    try:

        user_id = int(유저)

    except ValueError:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "올바른 유저 ID를 입력해주세요."
        )

        return


    member = ctx.guild.get_member(
        user_id
    )


    if member is None:

        try:

            member = await ctx.guild.fetch_member(
                user_id
            )

        except (
            discord.NotFound,
            discord.HTTPException
        ):

            await ctx.send(
                f"{ctx.author.mention}\n"
                "해당 ID의 서버 멤버를 찾을 수 없습니다."
            )

            return


    if not can_moderate(
        ctx.guild,
        ctx.author,
        member
    ):

        await ctx.send(
            f"{ctx.author.mention}\n"
            "해당 멤버를 처리할 수 없습니다."
        )

        return


    name = member.display_name
    user_id = member.id


    await send_action_dm(
        member,
        ctx.guild,
        "ban",
        사유
    )


    try:

        await member.ban(
            reason=사유
        )


        await send_punishment_log(
            ctx.guild,
            "ban",
            name,
            user_id,
            ctx.author,
            사유
        )


        await ctx.send(
            f"{ctx.author.mention}\n"
            f"**{name}**님을 차단했습니다."
        )


    except discord.Forbidden:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "봇에게 차단 권한이 없습니다."
        )


# =========================================================
# !언밴
# =========================================================

@bot.command(
    name="언밴",
    aliases=["unban"]
)
@commands.has_permissions(
    ban_members=True
)
async def unban_command(
    ctx,
    유저: str
):

    try:

        user_id = int(유저)

    except ValueError:

        await ctx.send(
            f"{ctx.author.mention}\n\n"
            "**사용 방법**\n"
            "`!unban <유저ID>`\n\n"
            "**예시**\n"
            "`!unban 123456789`"
        )

        return


    target = None


    try:

        async for entry in ctx.guild.bans():

            if entry.user.id == user_id:

                target = entry.user
                break


    except discord.Forbidden:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "차단 목록을 확인할 권한이 없습니다."
        )

        return


    if target is None:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "해당 사용자는 차단되어 있지 않습니다."
        )

        return


    try:

        await ctx.guild.unban(
            target,
            reason=f"처리자: {ctx.author.id}"
        )


        await send_punishment_log(
            ctx.guild,
            "unban",
            str(target),
            target.id,
            ctx.author
        )


        await ctx.send(
            f"{ctx.author.mention}\n"
            f"**{target}**님의 차단을 해제했습니다."
        )


    except discord.Forbidden:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "봇에게 차단 해제 권한이 없습니다."
        )


# =========================================================
# !킥
# =========================================================

@bot.command(
    name="킥",
    aliases=["kick"]
)
@commands.has_permissions(
    kick_members=True
)
async def kick_command(
    ctx,
    유저: str,
    *,
    사유="사유 없음"
):

    try:

        user_id = int(유저)

    except ValueError:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "올바른 유저 ID를 입력해주세요."
        )

        return


    member = ctx.guild.get_member(
        user_id
    )


    if member is None:

        try:

            member = await ctx.guild.fetch_member(
                user_id
            )

        except (
            discord.NotFound,
            discord.HTTPException
        ):

            await ctx.send(
                f"{ctx.author.mention}\n"
                "해당 ID의 서버 멤버를 찾을 수 없습니다."
            )

            return


    if not can_moderate(
        ctx.guild,
        ctx.author,
        member
    ):

        await ctx.send(
            f"{ctx.author.mention}\n"
            "해당 멤버를 처리할 수 없습니다."
        )

        return


    name = member.display_name
    user_id = member.id


    await send_action_dm(
        member,
        ctx.guild,
        "kick",
        사유
    )


    try:

        await member.kick(
            reason=사유
        )


        await send_punishment_log(
            ctx.guild,
            "kick",
            name,
            user_id,
            ctx.author,
            사유
        )


        await ctx.send(
            f"{ctx.author.mention}\n"
            f"**{name}**님을 추방했습니다."
        )


    except discord.Forbidden:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "봇에게 추방 권한이 없습니다."
        )


# =========================================================
# !경고
# =========================================================

@bot.command(
    name="경고",
    aliases=["warn"]
)
@commands.has_permissions(
    moderate_members=True
)
async def warn_command(
    ctx,
    유저: str,
    횟수: int,
    *,
    사유="사유 없음"
):

    if 횟수 < 1 or 횟수 > 100:

        await ctx.send(
            f"{ctx.author.mention}\n\n"
            "**사용 방법**\n"
            "`!warn <유저ID> <횟수> <사유>`\n\n"
            "**예시**\n"
            "`!warn 123456789 2 도배`"
        )

        return


    try:

        user_id = int(유저)

    except ValueError:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "올바른 유저 ID를 입력해주세요."
        )

        return


    member = ctx.guild.get_member(
        user_id
    )


    if member is None:

        try:

            member = await ctx.guild.fetch_member(
                user_id
            )

        except (
            discord.NotFound,
            discord.HTTPException
        ):

            await ctx.send(
                f"{ctx.author.mention}\n"
                "해당 ID의 서버 멤버를 찾을 수 없습니다."
            )

            return


    if not can_moderate(
        ctx.guild,
        ctx.author,
        member
    ):

        await ctx.send(
            f"{ctx.author.mention}\n"
            "해당 멤버를 처리할 수 없습니다."
        )

        return


    add_warning(
        ctx.guild.id,
        member.id,
        ctx.author.id,
        사유,
        횟수
    )


    current = get_warning_count(
        ctx.guild.id,
        member.id
    )


    limit = get_warning_limit(
        ctx.guild.id
    )


    await send_action_dm(
        member,
        ctx.guild,
        "warning",
        사유,
        f"추가 경고: {횟수}회\n현재 경고: {current}/{limit}"
    )


    await send_punishment_log(
        ctx.guild,
        "warning",
        member.display_name,
        member.id,
        ctx.author,
        사유,
        f"+{횟수}회 / {current}/{limit}"
    )


    if current >= limit:

        auto_reason = (
            f"경고 제한 도달 "
            f"({current}/{limit})"
        )


        try:

            await send_action_dm(
                member,
                ctx.guild,
                "ban",
                auto_reason
            )


            await member.ban(
                reason=auto_reason
            )


            await send_punishment_log(
                ctx.guild,
                "ban",
                member.display_name,
                member.id,
                ctx.author,
                auto_reason
            )


            await ctx.send(
                f"{ctx.author.mention}\n"
                f"**{member.display_name}**님에게 "
                f"경고 {횟수}회를 추가했습니다.\n"
                f"현재 경고: **{current}/{limit}**\n\n"
                "**경고 제한에 도달하여 자동 차단했습니다.**"
            )

            return


        except discord.Forbidden:

            await ctx.send(
                f"{ctx.author.mention}\n"
                "경고는 추가했지만 자동 차단에 실패했습니다."
            )

            return


    await ctx.send(
        f"{ctx.author.mention}\n"
        f"**{member.display_name}**님에게 "
        f"경고 {횟수}회를 추가했습니다.\n"
        f"현재 경고: **{current}/{limit}**"
    )


# =========================================================
# !경고삭제
# =========================================================

@bot.command(
    name="경고삭제",
    aliases=[
        "warnremove",
        "delwarn"
    ]
)
@commands.has_permissions(
    moderate_members=True
)
async def warn_remove_command(
    ctx,
    유저: str,
    횟수: int
):

    if 횟수 < 1:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "`!warnremove <유저ID> <횟수>`\n\n"
            "예시: `!warnremove 123456789 1`"
        )

        return


    try:

        user_id = int(유저)

    except ValueError:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "올바른 유저 ID를 입력해주세요."
        )

        return


    member = ctx.guild.get_member(
        user_id
    )


    if member is None:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "해당 멤버를 찾을 수 없습니다."
        )

        return


    current = get_warning_count(
        ctx.guild.id,
        member.id
    )


    if current <= 0:

        await ctx.send(
            f"{ctx.author.mention}\n"
            "삭제할 경고가 없습니다."
        )

        return


    deleted = remove_warnings(
        ctx.guild.id,
        member.id,
        min(횟수, current)
    )


    new_count = get_warning_count(
        ctx.guild.id,
        member.id
    )


    limit = get_warning_limit(
        ctx.guild.id
    )


    await send_punishment_log(
        ctx.guild,
        "warning_remove",
        member.display_name,
        member.id,
        ctx.author,
        extra=f"-{deleted}회 / {new_count}/{limit}"
    )


    await ctx.send(
        f"{ctx.author.mention}\n"
        f"**{member.display_name}**님의 "
        f"경고 {deleted}회를 삭제했습니다.\n"
        f"현재 경고: **{new_count}/{limit}**"
    )


# =========================================================
# /타임아웃
# =========================================================
#
# 사용 예:
#
# /타임아웃
# 유저: @홍길동
# 시간: 30
# 단위: 분
# 사유: 도배
#
# 또는
#
# /타임아웃
# 유저: @홍길동
# 시간: 2
# 단위: 시간
# 사유: 도배
#
# =========================================================

TIMEOUT_UNITS = [
    app_commands.Choice(
        name="분",
        value="minutes"
    ),
    app_commands.Choice(
        name="시간",
        value="hours"
    )
]


@bot.tree.command(
    name="타임아웃",
    description="멤버에게 타임아웃을 적용합니다."
)
@app_commands.describe(
    유저="타임아웃할 멤버",
    시간="타임아웃 시간",
    단위="시간 단위를 선택하세요.",
    사유="타임아웃 사유"
)
@app_commands.choices(
    단위=TIMEOUT_UNITS
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def timeout_command(
    interaction: discord.Interaction,
    유저: discord.Member,
    시간: int,
    단위: app_commands.Choice[str],
    사유: str = "사유 없음"
):

    # -----------------------------------------
    # 숫자 검사
    # -----------------------------------------

    if 시간 < 1:

        await interaction.response.send_message(
            "시간은 1 이상이어야 합니다.",
            ephemeral=True
        )

        return


    # -----------------------------------------
    # 단위에 따라 실제 분으로 변환
    # -----------------------------------------

    if 단위.value == "minutes":

        total_minutes = 시간
        display_time = f"{시간}분"

    else:

        total_minutes = 시간 * 60
        display_time = f"{시간}시간"


    # Discord 최대 타임아웃 28일
    MAX_MINUTES = 40320


    if total_minutes > MAX_MINUTES:

        await interaction.response.send_message(
            "타임아웃은 최대 **28일(40320분)**까지 가능합니다.",
            ephemeral=True
        )

        return


    # -----------------------------------------
    # 대상 검사
    # -----------------------------------------

    member = 유저


    if member == interaction.user:

        await interaction.response.send_message(
            "자기 자신에게 타임아웃을 걸 수 없습니다.",
            ephemeral=True
        )

        return


    if member.top_role >= interaction.user.top_role:

        await interaction.response.send_message(
            "자신과 같거나 높은 역할의 멤버에게 "
            "타임아웃을 걸 수 없습니다.",
            ephemeral=True
        )

        return


    if (
        interaction.guild.me
        and member.top_role >= interaction.guild.me.top_role
    ):

        await interaction.response.send_message(
            "봇보다 높거나 같은 역할의 멤버에게 "
            "타임아웃을 걸 수 없습니다.",
            ephemeral=True
        )

        return


    # -----------------------------------------
    # 타임아웃 실행
    # -----------------------------------------

    try:

        await member.timeout(
            timedelta(
                minutes=total_minutes
            ),
            reason=사유
        )


        # -------------------------------------
        # DM
        # -------------------------------------

        await send_action_dm(
            member,
            interaction.guild,
            "timeout",
            사유,
            display_time
        )


        # -------------------------------------
        # 처벌 로그
        # -------------------------------------

        await send_punishment_log(
            interaction.guild,
            "timeout",
            member.display_name,
            member.id,
            interaction.user,
            사유,
            display_time
        )


        # -------------------------------------
        # 완료 메시지
        # -------------------------------------

        embed = discord.Embed(
            title="타임아웃 처리 완료",
            description=(
                f"{member.mention}님에게 "
                f"타임아웃이 적용되었습니다."
            ),
            timestamp=discord.utils.utcnow()
        )


        embed.add_field(
            name="시간",
            value=f"**{display_time}**",
            inline=True
        )


        embed.add_field(
            name="처리자",
            value=interaction.user.mention,
            inline=True
        )


        embed.add_field(
            name="사유",
            value=사유,
            inline=False
        )


        embed.set_footer(
            text="Punishment System"
        )


        await interaction.response.send_message(
            embed=embed
        )


    except discord.Forbidden:

        await interaction.response.send_message(
            "봇에게 타임아웃 권한이 없습니다.",
            ephemeral=True
        )


    except discord.HTTPException as e:

        await interaction.response.send_message(
            "타임아웃 처리 중 오류가 발생했습니다.",
            ephemeral=True
        )

        print(
            f"[타임아웃 오류] {e}"
        )


# =========================================================
# /경고조회
# =========================================================

@bot.tree.command(
    name="경고조회",
    description="멤버의 경고 기록을 확인합니다."
)
@app_commands.describe(
    유저="조회할 멤버"
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def warning_view(
    interaction,
    유저: discord.Member
):

    warnings = get_warnings(
        interaction.guild.id,
        유저.id
    )


    count = len(warnings)


    limit = get_warning_limit(
        interaction.guild.id
    )


    if not warnings:

        await interaction.response.send_message(
            f"{유저.mention}님의 경고 기록이 없습니다.\n"
            f"현재 경고: **0/{limit}**"
        )

        return


    embed = discord.Embed(
        title="경고 기록",
        description=(
            f"{유저.mention}\n"
            f"현재 경고: **{count}/{limit}**"
        ),
        timestamp=discord.utils.utcnow()
    )


    for (
        warning_id,
        moderator_id,
        reason,
        created_at
    ) in warnings[:10]:

        moderator = interaction.guild.get_member(
            moderator_id
        )


        moderator_text = (
            moderator.mention
            if moderator
            else f"`{moderator_id}`"
        )


        embed.add_field(
            name=f"경고 #{warning_id}",
            value=(
                f"사유: {reason}\n"
                f"처리자: {moderator_text}\n"
                f"`{created_at}`"
            ),
            inline=False
        )


    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# /경고제한
# =========================================================

@bot.tree.command(
    name="경고제한",
    description="경고 자동 차단 기준을 설정합니다."
)
@app_commands.describe(
    횟수="자동 차단 기준"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def warning_limit(
    interaction,
    횟수: app_commands.Range[int, 1, 100]
):

    set_warning_limit(
        interaction.guild.id,
        횟수
    )


    await interaction.response.send_message(
        f"경고 자동 차단 기준을 "
        f"**{횟수}회**로 설정했습니다."
    )


# =========================================================
# /처벌로그설정
# =========================================================

@bot.tree.command(
    name="처벌로그설정",
    description="처벌 로그 채널을 설정합니다."
)
@app_commands.describe(
    채널="처벌 로그를 남길 채널"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def punishment_log_setting(
    interaction,
    채널: discord.TextChannel
):

    set_log_channel(
        interaction.guild.id,
        채널.id
    )


    await interaction.response.send_message(
        f"처벌 로그 채널을 "
        f"{채널.mention}으로 설정했습니다."
    )


# =========================================================
# /ping
# =========================================================

@bot.tree.command(
    name="ping",
    description="봇의 응답 속도를 확인합니다."
)
async def ping(
    interaction
):

    latency = round(
        bot.latency * 1000
    )


    await interaction.response.send_message(
        f"Pong! `{latency}ms`"
    )


# =========================================================
# 슬래시 명령어 오류
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    if isinstance(
        error,
        app_commands.MissingPermissions
    ):

        message = (
            "이 명령어를 사용할 권한이 없습니다."
        )

    else:

        print(
            f"[슬래시 명령어 오류] {error}"
        )

        message = (
            "명령어 실행 중 오류가 발생했습니다."
        )


    if interaction.response.is_done():

        await interaction.followup.send(
            message,
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            message,
            ephemeral=True
        )


# =========================================================
# 봇 시작
# =========================================================

@bot.event
async def on_ready():

    print(
        f"로그인 완료: {bot.user}"
    )


    try:

        synced = await bot.tree.sync()


        print(
            f"슬래시 명령어 "
            f"{len(synced)}개 동기화 완료"
        )


        for command in synced:

            print(
                f"  /{command.name}"
            )


    except Exception as e:

        print(
            f"슬래시 명령어 동기화 실패: {e}"
        )


# =========================================================
# 실행
# =========================================================

bot.run(TOKEN)