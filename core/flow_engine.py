from typing import Any, Dict, Optional, Tuple

from core.memory_engine import get_user_profile


VAGUE_INPUTS = {"idk", "i dont know", "not sure", "whatever", "anything"}


def filter_options_for_profile(options: list[str], session: Dict[str, Any]) -> list[str]:
    profile = get_user_profile(session)
    filtered_options = []

    for option in options:
        blocked = False
        lowered_option = option.lower()

        for allergy in profile.get("allergies", []):
            if allergy in lowered_option:
                blocked = True

        for dislike in profile.get("dislikes", {}).keys():
            if dislike in lowered_option:
                blocked = True

        if profile.get("diet") == "vegan":
            if any(
                word in lowered_option
                for word in [
                    "chicken",
                    "beef",
                    "shrimp",
                    "cheese",
                    "butter",
                    "wings",
                    "burger",
                    "steak",
                    "pork",
                    "bacon",
                    "fish",
                    "turkey",
                ]
            ):
                blocked = True

        if not blocked:
            filtered_options.append(option)

    return filtered_options


def handle_vague_input(lowered: str, session: Dict[str, Any]) -> Optional[str]:
    if lowered in VAGUE_INPUTS:
        session["stage"] = "choose_mode"
        return "Aight 😏 you tryna cook or you tryna order?"
    return None


def handle_choose_mode(lowered: str, session: Dict[str, Any]) -> Optional[str]:
    if lowered == "cook":
        session["stage"] = "cook_size"
        return "Bet 😏 this for just you or you feeding folks?"
    if lowered == "order":
        session["stage"] = "ask_location"
        return "Say less 😏 where you at? Drop a city or zip"
    return None


def handle_cook_size(lowered: str, session: Dict[str, Any]) -> Optional[str]:
    if session.get("stage") != "cook_size":
        return None

    if "just me" in lowered or lowered == "me":
        session["stage"] = "cook_speed"
        return "Say less 😏 you want quick & easy or you got time to cook?"
    if "folks" in lowered or "family" in lowered or "people" in lowered:
        session["stage"] = "cook_speed"
        return "Bet 😏 we feeding folks. You want quick or you got time to go all out?"
    return None


def handle_cook_speed(lowered: str, session: Dict[str, Any]) -> Optional[Tuple[str, list[str]]]:
    if session.get("stage") != "cook_speed":
        return None

    if "quick" in lowered:
        options = ["garlic butter chicken", "shrimp pasta", "loaded quesadilla"]
        filtered_options = filter_options_for_profile(options, session)
        session["stage"] = "choose_food"
        session["food_options"] = filtered_options
        if not filtered_options:
            return ("I got you 😏 but based on your preferences, let me find better options...", [])
        return ("😂 I got you, no struggle meals. Pick one 👇", filtered_options)

    if "time" in lowered or "full" in lowered:
        options = ["baked ziti", "fried chicken dinner", "steak & potatoes"]
        filtered_options = filter_options_for_profile(options, session)
        session["stage"] = "choose_food"
        session["food_options"] = filtered_options
        if not filtered_options:
            return ("I got you 😏 but based on your preferences, let me find better options...", [])
        return ("Say less 😏 we cooking for real. Pick one 👇", filtered_options)

    return None


def handle_food_choice(lowered: str, session: Dict[str, Any]) -> Optional[str]:
    if session.get("stage") != "choose_food":
        return None

    options = session.get("food_options", [])
    match = next((opt for opt in options if lowered in opt.lower()), None)

    if match:
        session["selected_food"] = match
        session["stage"] = "cook_details"
        return f"Bet 😏 {match} it is. I got ingredients and the recipe ready for you 👇"
    return None


def handle_order_location(lowered: str, session: Dict[str, Any]) -> Optional[str]:
    if session.get("stage") != "ask_location":
        return None

    session["user_location"] = lowered
    session["stage"] = "order_results"
    return f"Say less 😏 here’s some spots near {lowered} 👇"
