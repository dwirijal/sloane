#!/usr/bin/env python3
"""
Mock data generator for sloane API testing.
Generates sample content matching the database schema without requiring a real PostgreSQL connection.
"""
import json
import random
from datetime import datetime, timedelta

# Sample data pools
TITLES_ANIME = [
    "Attack on Titan", "Demon Slayer", "Jujutsu Kaisen", "One Piece", "Naruto",
    "Death Note", "Fullmetal Alchemist", "My Hero Academia", "Tokyo Ghoul", "Bleach"
]
TITLES_MANGA = [
    "Berserk", "One Punch Man", "Chainsaw Man", "Spy x Family", "Blue Lock",
    "Vinland Saga", "Vagabond", "Monster", "Kingdom", "Hunter x Hunter"
]
TITLES_DONGHUA = [
    "Mo Dao Zu Shi", "Heaven Official's Blessing", "Scissor Seven", "Link Click", "Fog Hill of Five Elements"
]
TITLES_COMIC = [
    "Tower of God", "Solo Leveling", "The Beginning After The End", "Omniscient Reader", "Eleceed"
]
TITLES_NOVEL = [
    "Mushoku Tensei", "Re:Zero", "Overlord", "Konosuba", "That Time I Got Reincarnated as a Slime"
]
TITLES_MOVIE = [
    "Your Name", "Weathering with You", "A Silent Voice", "Spirited Away", "Princess Mononoke"
]

COVER_URLS = [
    "https://picsum.photos/seed/anime1/400/600",
    "https://picsum.photos/seed/manga1/400/600",
    "https://picsum.photos/seed/donghua1/400/600",
    "https://picsum.photos/seed/comic1/400/600",
    "https://picsum.photos/seed/novel1/400/600",
    "https://picsum.photos/seed/movie1/400/600"
]

STATUSES = ["ongoing", "completed", "hiatus", "upcoming"]
GENRES = ["action", "adventure", "comedy", "drama", "fantasy", "romance", "sci-fi", "thriller"]

def generate_content(content_type: str, count: int) -> list:
    """Generate mock content items for a specific type."""
    titles = {
        "anime": TITLES_ANIME,
        "manga": TITLES_MANGA,
        "donghua": TITLES_DONGHUA,
        "comic": TITLES_COMIC,
        "novel": TITLES_NOVEL,
        "movie": TITLES_MOVIE
    }.get(content_type, TITLES_ANIME)

    items = []
    for i in range(count):
        title = titles[i % len(titles)] + (f" {i+1}" if i >= len(titles) else "")
        scraped_at = (datetime.now() - timedelta(days=random.randint(0, 30))).isoformat()

        item = {
            "id": i + 1,
            "title": title,
            "content_type": content_type,
            "cover_url": random.choice(COVER_URLS),
            "description": f"This is a mock description for {title}. It contains a brief synopsis of the content.",
            "episode_count": random.randint(12, 24) if content_type in ["anime", "donghua", "movie"] else None,
            "chapter_count": random.randint(50, 200) if content_type in ["manga", "comic", "novel"] else None,
            "status": random.choice(STATUSES),
            "genres": ",".join(random.sample(GENRES, random.randint(1, 3))),
            "year": random.randint(2010, 2026),
            "rating": round(random.uniform(6.0, 9.5), 1),
            "scraped_at": scraped_at,
            "last_scraped_at": scraped_at
        }
        items.append(item)
    return items

def generate_streams(content_id: int, count: int = 3) -> list:
    """Generate mock stream URLs for a content item."""
    return [
        {
            "id": i + 1,
            "content_id": content_id,
            "episode": i + 1,
            "url": f"https://example.com/stream/{content_id}/ep{i+1}",
            "quality": random.choice(["1080p", "720p", "480p"])
        }
        for i in range(count)
    ]

def generate_pages(content_id: int, chapter: int, count: int = 10) -> list:
    """Generate mock page URLs for a manga/comic/novel."""
    return [
        {
            "id": i + 1,
            "content_id": content_id,
            "chapter": chapter,
            "page_number": i + 1,
            "url": f"https://example.com/pages/{content_id}/ch{chapter}/p{i+1}.jpg"
        }
        for i in range(count)
    ]

def main():
    """Generate and save mock data to JSON files."""
    print("Generating mock data...")

    # Generate content for each type
    mock_data = {
        "anime": generate_content("anime", 10),
        "manga": generate_content("manga", 10),
        "donghua": generate_content("donghua", 5),
        "comic": generate_content("comic", 5),
        "novel": generate_content("novel", 5),
        "movie": generate_content("movie", 5)
    }

    # Generate related media
    streams = {}
    pages = {}
    for ctype, items in mock_data.items():
        for item in items:
            if ctype in ["anime", "donghua", "movie"]:
                streams[item["id"]] = generate_streams(item["id"], random.randint(1, 3))
            elif ctype in ["manga", "comic", "novel"]:
                pages[item["id"]] = generate_pages(item["id"], chapter=1, count=random.randint(5, 15))

    # Save to files
    with open("mock_contents.json", "w") as f:
        json.dump(mock_data, f, indent=2)

    with open("mock_streams.json", "w") as f:
        json.dump(streams, f, indent=2)

    with open("mock_pages.json", "w") as f:
        json.dump(pages, f, indent=2)

    print("Mock data generated successfully!")
    print("  - mock_contents.json")
    print("  - mock_streams.json")
    print("  - mock_pages.json")

if __name__ == "__main__":
    main()