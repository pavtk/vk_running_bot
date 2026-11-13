from vkbottle.bot import Message

from app.bot.labelers import event_show_labeler
from app.service import render_active_events
from app.bot.utils import require_private_message


@event_show_labeler.message(text="/events")
async def show_active_events(message: Message):
    if not await require_private_message(message):
        return

    events = await render_active_events(event_show_labeler, message.from_id)

    if not events:
        await message.answer("📭 Сейчас нет активных событий.")
        return

    parts = ["🗓 Активные события:\n"]

    for i, event in enumerate(events, start=1):
        starts = event["starts_on"]
        ends = event["ends_on"]
        if hasattr(starts, "strftime"):
            starts = starts.strftime("%d.%m.%Y %H:%M")
        if hasattr(ends, "strftime"):
            ends = ends.strftime("%d.%m.%Y %H:%M")

        lines = [
            f"\n{i}. {event['title']}",
            f"   🕒 {starts} — {ends}",
        ]

        categories = event.get("event_categories") or []
        if categories:
            lines.append("   🏅 Виды спорта и категории:")
            for cat in categories:
                title = cat.get("category_title") or "—"
                sport = cat.get("sport_title") or "—"
                distance_km = cat.get("distance_km")
                if distance_km is not None:
                    lines.append(f"      • {sport} — {title}: {distance_km} км")
                else:
                    lines.append(f"      • {sport} — {title}")

        parts.append("\n".join(lines))

    text = "\n".join(parts)

    # VK ограничивает длину сообщения (~4096 символов) — при необходимости режем
    if len(text) > 4000:
        text = text[:3990] + "\n…"

    await message.answer(text, disable_mention=True)
