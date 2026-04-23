import os
import re
from urllib.parse import quote_plus

from flask import Flask, render_template, request, session
from core.ai_engine import get_ai_reply
from core.flow_engine import (
    filter_options_for_profile,
    handle_choose_mode,
    handle_cook_size,
    handle_cook_speed,
    handle_food_choice,
    handle_order_location,
    handle_vague_input,
)
from core.memory_engine import (
    format_behavior_for_ai,
    format_profile_for_ai,
    get_user_profile,
    infer_preferences,
    track_rejection,
    track_user_choice,
    update_user_profile,
)
from utils.helpers import normalize
from utils.logger import log_event

FOOD_ADS = {
    "pizza": [
        {"name": "Pizza Hut", "url": "https://www.pizzahut.com"},
        {"name": "Domino's", "url": "https://www.dominos.com"},
        {"name": "Papa John's", "url": "https://www.papajohns.com"},
    ],
    "tacos": [
        {"name": "Taco Bell", "url": "https://www.tacobell.com"},
        {"name": "Chipotle", "url": "https://www.chipotle.com"},
        {"name": "Local Taqueria", "url": "https://www.google.com/search?q=local+taqueria"},
    ],
    "burger": [
        {"name": "McDonald's", "url": "https://www.mcdonalds.com"},
        {"name": "Five Guys", "url": "https://www.fiveguys.com"},
        {"name": "Burger King", "url": "https://www.bk.com"},
    ],
    "wings": [
        {"name": "Wingstop", "url": "https://www.wingstop.com"},
        {"name": "Buffalo Wild Wings", "url": "https://www.buffalowildwings.com"},
        {"name": "Local Spot", "url": "https://www.google.com/search?q=chicken+wings+near+me"},
    ],
    "fries": [
        {"name": "McDonald's", "url": "https://www.mcdonalds.com"},
        {"name": "Checkers", "url": "https://www.checkers.com"},
        {"name": "Shake Shack", "url": "https://www.shakeshack.com"},
    ],
    "chicken": [
        {"name": "Chick-fil-A", "url": "https://www.chick-fil-a.com"},
        {"name": "Raising Cane's", "url": "https://www.raisingcanes.com"},
        {"name": "Popeyes", "url": "https://www.popeyes.com"},
    ],
}


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "tastebuds-dev-secret")


def debug_log(label, value):
    safe_text = str(value).encode("ascii", "backslashreplace").decode("ascii")
    print(f"{label}: {safe_text}")


def suggestion_footer():
    return "Pick one or say 'show more' 👀\nYou tryna cook or order? 😏"


def format_suggestions(options, intro="Say less 😏 you might be in the mood for"):
    return (
        f"{intro} {options[0]}, {options[1]}, or {options[2]}.\n\n"
        f"{suggestion_footer()}"
    )


def natural_suggestion_options(show_more=False):
    if show_more:
        return ["hot honey pizza", "loaded nachos", "crispy chicken sandwich"]
    return ["wings", "fries", "burger"]


def parse_suggestion_options(text):
    options = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*\d+[\).\-\:]*\s*", "", line).strip()
        cleaned = cleaned.lstrip("-* ").strip()
        if cleaned and "pick one or say" not in cleaned.lower():
            options.append(cleaned)

    if len(options) >= 3:
        return options[:3]

    compact = re.sub(r"\s+", " ", text).strip()
    compact = re.sub(r"(?i)^.*?you might be in the mood for\s+", "", compact)
    compact = compact.split("Pick one or say")[0].strip(" .")
    parts = [part.strip(" .") for part in re.split(r",| or ", compact) if part.strip()]
    if len(parts) >= 3:
        return parts[:3]

    return []


def build_suggestions_prompt(taste, show_more=False):
    prefix = "3 different" if show_more else "3"
    return (
        "You are TasteBuds, a casual funny food assistant. "
        f"The user's taste preference is {taste}. "
        f"Give {prefix} food options that fit that vibe. "
        "Keep it short, casual, and natural. "
        "Use a simple 1, 2, 3 list with just the food names."
    )


def build_recipe_prompt(food):
    return (
        "You are TasteBuds, a casual funny food assistant. "
        f"The selected food is {food}. "
        "Return a tiny cooking plan. "
        "Format exactly like this:\n"
        "Intro: one short casual line\n"
        "Ingredients:\n"
        "- item\n"
        "- item\n"
        "- item\n"
        "Recipe:\n"
        "1. step\n"
        "2. step\n"
        "3. step\n"
        "4. step\n"
        "Keep it easy and friendly."
    )


def fallback_cook_plan(food):
    return {
        "intro": f"Say less 😏 here's a quick way to make {food}.",
        "ingredients": [food, "oil or butter", "salt and pepper"],
        "steps": [
            f"Prep your {food} and get everything ready.",
            "Season it up and heat your pan, oven, or air fryer.",
            "Cook till it looks golden and smells amazing.",
            "Finish strong, plate it up, and dig in.",
        ],
    }


def parse_cook_plan(text, food):
    intro = ""
    ingredients = []
    steps = []
    section = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("intro:"):
            intro = line.split(":", 1)[1].strip()
            continue
        if lower.startswith("ingredients:"):
            section = "ingredients"
            continue
        if lower.startswith("recipe:"):
            section = "steps"
            continue

        if section == "ingredients":
            cleaned = re.sub(r"^[-*]\s*", "", line).strip()
            if cleaned:
                ingredients.append(cleaned)
        elif section == "steps":
            cleaned = re.sub(r"^\d+[\).\s-]*", "", line).strip()
            if cleaned:
                steps.append(cleaned)
        elif not intro:
            intro = line

    if not intro or len(ingredients) < 2 or len(steps) < 3:
        return fallback_cook_plan(food)

    return {
        "intro": intro,
        "ingredients": ingredients[:6],
        "steps": steps[:5],
    }


def get_cook_plan(food):
    raw_plan = get_ai_reply(
        food,
        session,
        fallback="",
        prompt=build_recipe_prompt(food),
    )
    return parse_cook_plan(raw_plan, food)


def get_location_restaurants(food, location):
    return (
        f"Bet 😏 here’s some spots in {location} for {food}:\n\n"
        f"1. {food.title()} Spot\n"
        f"2. Local {food.title()} Kitchen\n"
        f"3. {location} {food.title()} House\n\n"
        "You tryna cook or pull up? 😏"
    )


def get_ads_for_options(options):
    ads = []
    for option in options:
        key = option.lower()
        for food, brands in FOOD_ADS.items():
            if food in key:
                ads.append({
                    "food": option,
                    "brands": brands,
                })
    return ads


def get_suggestion_options(taste, show_more=False):
    profile = get_user_profile(session)
    fallback_options = natural_suggestion_options(show_more=show_more)
    fallback_reply = format_suggestions(fallback_options)
    suggestions = get_ai_reply(
        taste,
        session,
        fallback=fallback_reply,
        prompt=f"{format_profile_for_ai(profile)}\n{build_suggestions_prompt(taste, show_more=show_more)}",
    )
    parsed_options = parse_suggestion_options(suggestions)
    if len(parsed_options) < 3:
        parsed_options = fallback_options
    return filter_options_for_profile(parsed_options, session)


def get_suggestions_reply(taste, show_more=False):
    parsed_options = get_suggestion_options(taste, show_more=show_more)
    if len(parsed_options) < 3:
        session["food_options"] = parsed_options
        session["last_suggestion"] = parsed_options[0] if parsed_options else ""
        session["ads"] = []
        session["selected_food"] = ""
        session["ingredients"] = []
        session["user_location"] = ""
        session["grocery_list"] = []
        session["recipe_steps"] = []
        return "I got you 😏 but based on your preferences, let me find better options..."
    suggestions = format_suggestions(parsed_options)

    session["food_options"] = parsed_options
    session["last_suggestion"] = parsed_options[0] if parsed_options else ""
    session["ads"] = get_ads_for_options(parsed_options)
    session["selected_food"] = ""
    session["ingredients"] = []
    session["user_location"] = ""
    session["grocery_list"] = []
    session["recipe_steps"] = []
    return suggestions


def build_cook_options(seed):
    options = get_suggestion_options(f"easy home-cooked {seed}", show_more=False)
    session["food_options"] = options[:3]
    session["last_suggestion"] = session["food_options"][0] if session["food_options"] else ""
    session["option_mode"] = "cook"
    session["selected_food"] = ""
    session["ingredients"] = []
    session["recipe_steps"] = []
    session["show_recipe"] = False
    return session["food_options"]


def build_order_options(seed, location, show_more=False):
    options = get_suggestion_options(f"takeout {seed} in {location}", show_more=show_more)
    cards = []
    for option in options[:3]:
        cards.append({
            "food": option,
            "url": f"https://www.google.com/search?q={quote_plus(f'{option} delivery near {location}')}",
            "local_url": f"https://www.google.com/search?q={quote_plus(f'{option} near {location}')}",
        })

    session["order_options"] = cards
    session["last_suggestion"] = cards[0]["food"] if cards else ""
    session["option_mode"] = "order"
    session["food_options"] = []
    return cards


def render_app(show_results=True):
    return render_template(
        "index.html",
        response=session.get("history", []),
        show_results=show_results,
        ingredients=session.get("ingredients", []),
        recipe_steps=session.get("recipe_steps", []),
        grocery_list=session.get("grocery_list", []),
        ads=session.get("ads", []),
        food_options=session.get("food_options", []),
        option_mode=session.get("option_mode", ""),
        order_options=session.get("order_options", []),
        show_recipe=session.get("show_recipe", False),
        local_spots_url=session.get("local_spots_url", ""),
        selected_food=session.get("selected_food", ""),
    )


def append_history(role, content):
    history = session.get("history", [])
    history.append({"role": role, "content": content})
    session["history"] = history


def log_request_state(user_input, session, profile_changed=None):
    log_event("user_input", user_input)
    log_event("stage", session.get("stage", ""))
    log_event("selected_food", session.get("selected_food", ""))
    if profile_changed is not None:
        log_event("profile_changed", profile_changed)


def build_personalization_prefix(profile):
    if profile.get("likes", {}).get("seafood", 0) >= 2:
        return "You been on seafood lately 😏\n\n"
    if profile.get("diet"):
        return f"Still keeping it {profile['diet']} right? 😏\n\n"
    return ""


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        session.setdefault("history", [])
        return render_template(
            "index.html",
            response=None,
            show_results=False,
            ads=[],
            ingredients=[],
            recipe_steps=[],
            grocery_list=session.get("grocery_list", []),
            food_options=[],
            option_mode="",
            order_options=[],
            show_recipe=False,
            local_spots_url="",
            selected_food="",
        )

    action = request.form.get("action", "").strip()
    user_message = (request.form.get("message") or request.form.get("user_input", "")).strip()
    lowered = normalize(user_message)
    session.setdefault("history", [])
    assistant_reply = ""

    if action not in {"add_grocery", "show_recipe"}:
        session["ingredients"] = []
        session["recipe_steps"] = []
        session["show_recipe"] = False

    if not action:
        session["local_spots_url"] = ""

    if action == "pick_cook_food":
        food = request.form.get("food", "").strip()
        if food:
            session["selected_food"] = food
            track_user_choice(food, session)
            infer_preferences(session)
            session["option_mode"] = "cook"
            cook_plan = get_cook_plan(food)
            session["ingredients"] = cook_plan["ingredients"]
            session["recipe_steps"] = cook_plan["steps"]
            session["show_recipe"] = False
            assistant_reply = f"Bet 😏 let's make {food}."
    elif action == "add_grocery":
        selected_items = request.form.getlist("selected_ingredients")
        grocery_list = session.get("grocery_list", [])
        for item in selected_items:
            if item and item not in grocery_list:
                grocery_list.append(item)
        session["grocery_list"] = grocery_list
        assistant_reply = "Added to your grocery list 😏"
    elif action == "show_recipe":
        session["show_recipe"] = True
        assistant_reply = f"Say less 😏 here's the recipe for {session.get('selected_food', 'that')}."
    elif action == "see_more":
        food = request.form.get("food", "").strip()
        location = session.get("user_location", "")
        session["selected_food"] = food
        if food and location:
            session["local_spots_url"] = (
                f"https://www.google.com/search?q={quote_plus(f'{food} near {location}')}"
            )
        assistant_reply = f"Bet 😏 peep local spots for {food}."

    if assistant_reply:
        append_history("assistant", assistant_reply)
        log_request_state(f"[action] {action}", session)
        debug_log("user_input", f"[action] {action}")
        debug_log("assistant_reply", assistant_reply)
        return render_app()

    if not user_message:
        assistant_reply = "Tell me what you craving 😏"
        append_history("assistant", assistant_reply)
        log_request_state(user_message, session)
        debug_log("user_input", user_message)
        debug_log("assistant_reply", assistant_reply)
        return render_app()

    append_history("user", user_message)
    current_stage = session.get("stage", "")

    if any(word in lowered for word in ["nah", "no", "not that", "something else"]):
        session["last_rejected"] = True
        track_rejection(session)
    else:
        session["last_rejected"] = False

    guided_reply = handle_vague_input(lowered, session)
    if guided_reply:
        append_history("assistant", guided_reply)
        log_request_state(user_message, session)
        debug_log("user_input", user_message)
        debug_log("assistant_reply", guided_reply)
        return render_app()

    if current_stage == "choose_mode":
        guided_reply = handle_choose_mode(lowered, session)
        if guided_reply:
            if lowered == "order":
                session["option_mode"] = "order"
                session["order_options"] = []
                session["food_options"] = []
            append_history("assistant", guided_reply)
            log_request_state(user_message, session)
            debug_log("user_input", user_message)
            debug_log("assistant_reply", guided_reply)
            return render_app()

    guided_reply = handle_cook_size(lowered, session)
    if guided_reply:
        append_history("assistant", guided_reply)
        log_request_state(user_message, session)
        debug_log("user_input", user_message)
        debug_log("assistant_reply", guided_reply)
        return render_app()

    cook_speed_result = handle_cook_speed(lowered, session)
    if cook_speed_result:
        guided_reply, options = cook_speed_result
        if options:
            session["food_options"] = options
            session["last_suggestion"] = options[0] if options else ""
            session["option_mode"] = "cook"
            session["selected_food"] = ""
            session["ingredients"] = []
            session["recipe_steps"] = []
            session["show_recipe"] = False
        else:
            profile = get_user_profile(session)
            guided_reply = get_ai_reply(
                f"{format_profile_for_ai(profile)}\nUser message: find better cook options for {user_message}",
                session,
                fallback=guided_reply,
            )
        append_history("assistant", guided_reply)
        log_request_state(user_message, session)
        debug_log("user_input", user_message)
        debug_log("assistant_reply", guided_reply)
        return render_app()

    food_choice_reply = handle_food_choice(lowered, session)
    if food_choice_reply:
        food = session.get("selected_food", user_message)
        track_user_choice(food, session)
        infer_preferences(session)
        cook_plan = get_cook_plan(food)
        session["option_mode"] = "cook"
        session["ingredients"] = cook_plan["ingredients"]
        session["recipe_steps"] = cook_plan["steps"]
        session["show_recipe"] = False
        append_history("assistant", food_choice_reply)
        log_request_state(user_message, session)
        debug_log("user_input", user_message)
        debug_log("assistant_reply", food_choice_reply)
        return render_app()

    if lowered == "cook":
        guided_reply = handle_choose_mode(lowered, session)
        if guided_reply:
            append_history("assistant", guided_reply)
            log_request_state(user_message, session)
            debug_log("user_input", user_message)
            debug_log("assistant_reply", guided_reply)
            return render_app()

    if lowered == "order":
        guided_reply = handle_choose_mode(lowered, session)
        if guided_reply:
            session["option_mode"] = "order"
            session["order_options"] = []
            session["food_options"] = []
            append_history("assistant", guided_reply)
            log_request_state(user_message, session)
            debug_log("user_input", user_message)
            debug_log("assistant_reply", guided_reply)
            return render_app()

    order_location_reply = handle_order_location(lowered, session)
    if order_location_reply:
        seed = session.get("taste_preference") or session.get("selected_food") or "something good"
        build_order_options(seed, user_message)
        append_history("assistant", order_location_reply)
        log_request_state(user_message, session)
        debug_log("user_input", user_message)
        debug_log("assistant_reply", order_location_reply)
        return render_app()

    if current_stage in ["choose_food", "cook_size", "cook_speed", "ask_location"]:
        assistant_reply = "Say that again for me 😏 I got you"
        append_history("assistant", assistant_reply)
        log_request_state(user_message, session)
        debug_log("user_input", user_message)
        debug_log("assistant_reply", assistant_reply)
        return render_app()

    previous_profile = dict(get_user_profile(session))
    profile = update_user_profile(user_message, session)
    profile_changed = profile != previous_profile
    full_context = f"""
{format_profile_for_ai(profile)}

{format_behavior_for_ai(profile)}

User message: {user_message}
"""

    assistant_reply = get_ai_reply(full_context, session)
    if not assistant_reply or assistant_reply.strip() == "":
        assistant_reply = "Say that again for me 😏 I got you"
    prefix = build_personalization_prefix(profile)
    if prefix and not assistant_reply.startswith(prefix.strip()):
        assistant_reply = prefix + assistant_reply
    session["taste_preference"] = user_message

    if "show more" in lowered or "ideas" in lowered or "what should i eat" in lowered:
        suggestions = get_suggestions_reply(user_message)
        assistant_reply += "\n\n" + suggestions

    if not assistant_reply or assistant_reply.strip() == "":
        assistant_reply = "Aight 😏 let’s reset—what you craving?"
    append_history("assistant", assistant_reply)
    log_request_state(user_message, session, profile_changed=profile_changed)
    debug_log("user_input", user_message)
    debug_log("assistant_reply", assistant_reply)
    return render_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
