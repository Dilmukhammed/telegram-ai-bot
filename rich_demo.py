"""Rich multi-block reply POC — Telegram Bot API 10.1 showcase."""

from __future__ import annotations

# Public HTTPS URLs only (Telegram requirement for rich media blocks).
_TG_PHOTO = "https://telegram.org/example/photo.jpg"
_TG_VIDEO = "https://telegram.org/example/video.mp4"
_TG_GIF = "https://telegram.org/example/animation.gif"

_RICH_BLOCKS_DEMO_CORE = r"""# Rich Multi-Block POC

Один `sendRichMessage` — чередующиеся **текстовые** и **media** блоки (Bot API 10.1).

Форматирование: **bold**, *italic*, ~~strike~~, `code`, ==marked==, ||spoiler||, <u>underline</u>, H<sub>2</sub>O, x<sup>2</sup>.

Inline math $a^2+b^2=c^2$ и [ссылка](https://core.telegram.org/bots/api#rich-message-formatting-options).

---

## 1 · Текст → фото → текст

Типичный паттерн для агента: абзац, иллюстрация, продолжение.

![]({tg_photo} "Подпись под фото — Telegram example")

После картинки — ещё абзац. Второй media block ниже (другой URL).

![]({picsum_640} "picsum.photos — отдельный photo block")

---

## 2 · Video, GIF, audio

![]({tg_video} "Video block (mp4)")

![]({tg_gif} "Animation / GIF block")

---

## 3 · Таблица, списки, цитата

| Block type | Status |
|:-----------|:------:|
| RichBlockPhoto | ✅ |
| RichBlockTable | ✅ |
| RichBlockDetails | ✅ |
| Collage / Slideshow | ✅ |

- [x] task done
- [ ] task open

1. ordered one
2. ordered two

> Blockquote на нескольких строках —
> продолжение на второй строке.

---

## 4 · Math & footnotes

$$\\sum_{{i=1}}^{{n}} i = \\frac{{n(n+1)}}{{2}}$$

Текст со сноской[^demo].

[^demo]: До **50** media attachments и **500** blocks на сообщение.

---

## 5 · Details (expandable)

<details>
<summary>Разверни — <b>summary</b> с markdown</summary>

### Внутри details
- _italic_ и **bold**
- ||spoiler внутри||
- `inline code`

</details>

---

## 6 · Collage & slideshow

**Коллаж** — два фото в одном блоке:

<tg-collage>
![]({picsum_320_a})
![]({picsum_320_b})
</tg-collage>

**Слайдшоу** — листай вправо:

<tg-slideshow>
![]({picsum_slide1})
![]({picsum_slide2})
![]({picsum_slide3})
</tg-slideshow>

---

## 7 · Pull quote & footer

<blockquote cite="Hermes Agent">Multi-block = один ответ, много типов блоков. Media только отдельными блоками, не inline в тексте.</blockquote>

<footer>POC · команда /demo_rich · draft-only: &lt;tg-thinking&gt;</footer>
{static_map_section}
"""


def _optional_static_map_section() -> str:
    try:
        from config import get_settings, google_maps_configured
        from tools.builtins.google.maps_misc import static_map

        if not google_maps_configured():
            return ""
        settings = get_settings()
        lat = settings.google_maps_default_lat
        lng = settings.google_maps_default_lng
        result = static_map(
            lat=lat,
            lng=lng,
            zoom=13,
            markers=[{"lat": lat, "lng": lng, "color": "red", "label": "P"}],
        )
        map_url = result["map_url"]
        return (
            f"\n---\n\n## 8 · Real Static Map (Google API)\n\n"
            f"Тот же URL, что от `google.maps.static_map`:\n\n"
            f"![]({map_url})\n"
        )
    except Exception:
        return ""


def build_rich_blocks_demo_markdown() -> str:
    """Full multi-block markdown for /demo_rich."""
    return _RICH_BLOCKS_DEMO_CORE.format(
        tg_photo=_TG_PHOTO,
        tg_video=_TG_VIDEO,
        tg_gif=_TG_GIF,
        picsum_640="https://picsum.photos/seed/hermes640/640/360",
        picsum_320_a="https://picsum.photos/seed/hermesa/320/240",
        picsum_320_b="https://picsum.photos/seed/hermesb/320/240",
        picsum_slide1="https://picsum.photos/seed/slide1/640/400",
        picsum_slide2="https://picsum.photos/seed/slide2/640/400",
        picsum_slide3="https://picsum.photos/seed/slide3/640/400",
        static_map_section=_optional_static_map_section(),
    )
