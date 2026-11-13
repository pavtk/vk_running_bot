from app.bot.handlers.registration import (
    _categories_for_sport,
    _sports_from_categories,
)


def test_registration_lists_each_event_sport_once():
    event_categories = [
        {"sport_id": 2, "sport_title": "Плавание", "category_title": "Взрослые"},
        {"sport_id": 1, "sport_title": "Бег", "category_title": "Юниоры"},
        {"sport_id": 1, "sport_title": "Бег", "category_title": "Взрослые"},
    ]

    assert _sports_from_categories(event_categories) == [
        {"id": 1, "title": "Бег"},
        {"id": 2, "title": "Плавание"},
    ]


def test_registration_categories_are_filtered_by_selected_sport():
    event_categories = [
        {
            "sport_id": 2,
            "sport_title": "Плавание",
            "category_title": "Взрослые",
        },
        {
            "sport_id": 1,
            "sport_title": "Бег",
            "category_title": "Юниоры",
        },
        {
            "sport_id": 1,
            "sport_title": "Бег",
            "category_title": "Взрослые",
        },
    ]

    categories = _categories_for_sport(event_categories, sport_id=1)

    assert [category["category_title"] for category in categories] == [
        "Взрослые",
        "Юниоры",
    ]
    assert all(category["sport_id"] == 1 for category in categories)
