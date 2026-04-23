import os
import re

import requests
from flask import Flask, render_template, request, session

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
API_KEY = os.getenv("OPENAI_API_KEY")
SYSTEM_PROMPT = """You are a food assistant that adapts to the user's tone.

playful -> casual, slightly AAVE, friendly
neutral -> clear and helpful
direct -> concise

Never use profanity.
Never force slang.
Keep responses natural.
"""


def detect_vibe(message):
    lowered = message.lower().strip()
    playful_markers = [
        "tryna", "tho", "fr", "ngl", "lol", "lmao", "ima", "finna",
        "bruh", "lowkey", "highkey", "idk", "yall", "ain't", "wanna",
    ]
    direct_markers = {"cook", "order", "hungry", "spicy", "salty", "sweet", "show more"}

    if any(marker in lowered for marker in playful_markers):
        return "playful"
    if len(lowered.split()) <= 2 or lowered in direct_markers:
        return "direct"
    return "neutral"


def build_tone_prompt(prompt, vibe):
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"User vibe: {vibe}.\n"
        f"User message: {prompt}"
    )


def masked_api_key():
    if not API_KEY:
        return ""
    if len(API_KEY) <= 8:
        return "*" * len(API_KEY)
    return f"{API_KEY[:7]}...{API_KEY[-4:]}"


def generate_reply(prompt):
    debug_log("API KEY", masked_api_key())
    debug_log("CALLING OPENAI", prompt)

    if not API_KEY:
        return ""

    vibe = detect_vibe(prompt)

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_tone_prompt(prompt, vibe)},
            ],
        },
        timeout=30,
    )
    debug_log("OPENAI RESPONSE", response.json())
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def safe_generate_reply(prompt, fallback):
    try:
        reply = generate_reply(prompt)
        return reply or fallback
    except requests.RequestException as exc:
        debug_log("OPENAI ERROR", exc)
        return fallback
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        debug_log("OPENAI PARSE ERROR", exc)
        return fallback


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


def build_order_prompt(food):
    return (
        "You are TasteBuds, a casual funny food assistant. "
        f"The selected food is {food}. "
        "Give a short, casual reply naming the types of restaurants or spots that usually serve it well. "
        "Keep it natural and concise."
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
    raw_plan = safe_generate_reply(
        build_recipe_prompt(food),
        "",
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
                    "brands": brands
                })

    return ads


def get_suggestions_reply(taste, show_more=False):
    fallback_options = natural_suggestion_options(show_more=show_more)
    fallback_reply = format_suggestions(fallback_options)
    suggestions = safe_generate_reply(
        build_suggestions_prompt(taste, show_more=show_more),
        fallback_reply,
    )
    parsed_options = parse_suggestion_options(suggestions)
    if len(parsed_options) < 3:
        parsed_options = fallback_options
        suggestions = format_suggestions(parsed_options)
    else:
        footer = suggestion_footer()
        if footer not in suggestions:
            suggestions = f"{suggestions}\n\n{footer}"

    session["food_options"] = parsed_options
    session["ads"] = get_ads_for_options(parsed_options)
    session["selected_food"] = ""
    session["ingredients"] = []
    session["user_location"] = ""
    session["grocery_list"] = []
    session["recipe_steps"] = []
    return suggestions


def normalize_choice(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def debug_log(label, value):
    safe_text = str(value).encode("ascii", "backslashreplace").decode("ascii")
    print(f"{label}: {safe_text}")


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template(
            "index.html",
            response=None,
            show_results=False,
            ads=[],
            ingredients=[],
            recipe_steps=[],
            grocery_list=[],
        )

    assistant_reply = ""
    user_message = request.form.get("message") or request.form.get("user_input", "")
    user_message = user_message.strip()
    lowered = user_message.lower()

    if "history" not in session:
        session["history"] = []

    history = session.get("history", [])
    food_options = session.get("food_options", [])
    matched_option = next(
        (
            option
            for option in food_options
            if normalize_choice(option) == normalize_choice(user_message)
        ),
        "",
    )
    if matched_option:
        session["selected_food"] = matched_option

    if "cook" not in lowered:
        session["ingredients"] = []
        session["recipe_steps"] = []
        session["grocery_list"] = []

    if not any(keyword in lowered for keyword in ["show more", "ideas", "what should i eat"]):
        session["ads"] = []

    if not user_message:
        assistant_reply = "Tell me what you craving 😏"
    else:
        history.append({
            "role": "user",
            "content": user_message
        })

        current_stage = session.get("stage", "")

        if lowered in ["idk", "i dont know", "not sure", "whatever", "anything"]:
            assistant_reply = "Aight 😏 you tryna cook or you tryna order?"
            session["stage"] = "choose_mode"
        elif lowered == "cook":
            assistant_reply = "Bet 😏 this for just you or you feeding folks?"
            session["stage"] = "cook_size"
        elif lowered == "order":
            assistant_reply = "Say less 😏 where you at? Drop a city or zip"
            session["stage"] = "ask_location"
        elif current_stage == "cook_size":
            if "me" in lowered or "just me" in lowered:
                assistant_reply = "Say less 😏 you want quick & easy or you got time to cook?"
                session["stage"] = "cook_speed"
            else:
                assistant_reply = "Bet 😏 is it quick & easy or you got time to cook?"
        elif current_stage == "cook_speed":
            if "quick" in lowered:
                assistant_reply = (
                    "😂 I got you, no struggle meals.\n\n"
                    "Try:\n"
                    "- garlic butter chicken\n"
                    "- shrimp pasta\n"
                    "- loaded quesadilla"
                )
                session["stage"] = "done"
            else:
                assistant_reply = "Say less 😏 you want comfort food, spicy, or something light?"
        elif current_stage == "ask_location":
            session["user_location"] = user_message
            assistant_reply = get_location_restaurants(
                session.get("selected_food", ""),
                user_message
            )
            session["stage"] = ""

        if assistant_reply:
            history.append({
                "role": "assistant",
                "content": assistant_reply
            })
            session["history"] = history

            debug_log("user_input", user_message)
            debug_log("assistant_reply", assistant_reply)

            return render_template(
                "index.html",
                response=session.get("history", []),
                show_results=True,
                ingredients=session.get("ingredients", []),
                recipe_steps=session.get("recipe_steps", []),
                grocery_list=session.get("grocery_list", []),
                ads=session.get("ads", []),
            )

        ai_reply = safe_generate_reply(
            user_message,
            "Tell me what you craving 😏"
        )

        assistant_reply = ai_reply
        session["taste_preference"] = user_message

        if "show more" in lowered or "ideas" in lowered or "what should i eat" in lowered:
            suggestions = get_suggestions_reply(user_message)
            assistant_reply += "\n\n" + suggestions
        elif "cook" in lowered:
            selected_food = session.get("selected_food", user_message)
            cook_plan = get_cook_plan(selected_food)

            assistant_reply += "\n\n" + cook_plan["intro"]

            session["ingredients"] = cook_plan["ingredients"]
            session["recipe_steps"] = cook_plan["steps"]
            session["grocery_list"] = cook_plan["ingredients"]
        elif "order" in lowered:
            selected_food = session.get("selected_food", user_message)

            if not session.get("user_location"):
                assistant_reply += "\n\nWhere you at? Drop a city or zip 😏"
                session["stage"] = "ask_location"
            else:
                assistant_reply += "\n\n" + get_location_restaurants(
                    selected_food,
                    session.get("user_location")
                )
        elif session.get("stage") == "ask_location":
            session["user_location"] = user_message
            assistant_reply += "\n\n" + get_location_restaurants(
                session.get("selected_food", ""),
                user_message
            )
            session["stage"] = ""

        history.append({
            "role": "assistant",
            "content": assistant_reply
        })
        session["history"] = history

    debug_log("user_input", user_message)
    debug_log("assistant_reply", assistant_reply)

    return render_template(
        "index.html",
        response=session.get("history", []),
        show_results=True,
        ingredients=session.get("ingredients", []),
        recipe_steps=session.get("recipe_steps", []),
        grocery_list=session.get("grocery_list", []),
        ads=session.get("ads", []),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
