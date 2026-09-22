from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

from db import Activity, upsert_activity
from external_metrics import ExternalMetric


@dataclass(frozen=True)
class BlueskyPost:
    id: str
    text: str
    link: str
    published_at: datetime


@dataclass(frozen=True)
class SocialSnapshot:
    latest_post_at: datetime | None
    latest_post_link: str = ""
    days_since_latest_post: int | None = None
    post_count: int = 0
    reminder_due: bool = False
    stale: bool = False
    status: str = "OK"


def _clean_text(value: str | None) -> str:
    text = html.unescape(value or "").replace("\xa0", " ")
    return " ".join(text.split())


def _parse_pub_date(value: str) -> datetime:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_bluesky_rss(xml_text: str) -> list[BlueskyPost]:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Bluesky RSS channel not found")
    posts: list[BlueskyPost] = []
    for item in channel.findall("item"):
        text = _clean_text(item.findtext("description", default=""))
        guid = _clean_text(item.findtext("guid", default=""))
        published = _clean_text(item.findtext("pubDate", default=""))
        if not text or not guid or not published:
            continue
        posts.append(
            BlueskyPost(
                id=guid,
                text=text,
                link=_clean_text(item.findtext("link", default="")),
                published_at=_parse_pub_date(published),
            )
        )
    posts.sort(key=lambda post: post.published_at, reverse=True)
    return posts


def fetch_bluesky_posts(*, url: str, timeout: int) -> list[BlueskyPost]:
    response = requests.get(
        url,
        headers={"Accept": "application/rss+xml, application/xml, text/xml"},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_bluesky_rss(response.text)


def sync_bluesky_posts(
    conn,
    *,
    url: str,
    today: date,
    tz: ZoneInfo,
    reminder_after_days: int = 4,
    post_points: float = 1000.0,
    timeout: int = 10,
    dry_run: bool = False,
) -> SocialSnapshot:
    try:
        posts = fetch_bluesky_posts(url=url, timeout=timeout)
    except Exception as exc:
        return SocialSnapshot(latest_post_at=None, stale=True, status=str(exc))

    if not dry_run:
        for post in posts:
            upsert_activity(
                conn,
                Activity(
                    source="social",
                    external_id=post.id,
                    timestamp=post.published_at,
                    activity_type="bluesky_post",
                    duration_minutes=0,
                    points=post_points,
                    notes="Bluesky post",
                    raw_payload={
                        "text": post.text,
                        "link": post.link,
                        "published_at": post.published_at.isoformat(),
                    },
                ),
                tz=tz,
            )

    if not posts:
        return SocialSnapshot(latest_post_at=None, post_count=0, reminder_due=True, status="NO POSTS")

    latest = posts[0]
    latest_day = latest.published_at.astimezone(tz).date()
    days_since = max(0, (today - latest_day).days)
    return SocialSnapshot(
        latest_post_at=latest.published_at,
        latest_post_link=latest.link,
        days_since_latest_post=days_since,
        post_count=len(posts),
        reminder_due=days_since >= reminder_after_days,
    )


def social_snapshot_metric(snapshot: SocialSnapshot) -> ExternalMetric | None:
    if snapshot.stale:
        return ExternalMetric("SOCIAL POST", "--", "STALE", True, "negative")
    if snapshot.days_since_latest_post is None:
        return ExternalMetric("SOCIAL POST", "NONE", snapshot.status, True, "negative")
    days = snapshot.days_since_latest_post
    value = "TODAY" if days == 0 else f"{days}D AGO"
    status = "REMINDER" if snapshot.reminder_due else "OK"
    polarity = "negative" if snapshot.reminder_due else "positive"
    return ExternalMetric("SOCIAL POST", value, status, snapshot.reminder_due, polarity)
