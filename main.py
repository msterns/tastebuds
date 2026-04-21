import os
import re

import requests
from flask import Flask, render_template, request, session

FOOD_ADS = {
    "pizza": ["Pizza Hut", "Domino's", "Papa John's"],
    "tacos": ["Taco Bell", "Chipotle", "Local Taqueria"],
    "burger": ["McDonald's", "Five Guys", "Burger King"],
    "wings": ["Wingstop", "Buffalo Wild Wings", "Local Spot"],
    "fries": ["McDonald's", "Checkers", "Shake Shack"],
    "chicken": ["Chick-fil-A", "Raising Cane's", "Popeyes"]
}


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "tastebuds-dev-secret")
API_KEY = os.getenv("OPENAI_API_KEY")


def generate_reply(prompt):
    if not API_KEY:
        return ""

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    print(response.json())
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def safe_generate_reply(prompt, fallback):
    try:
        reply = generate_reply(prompt)
        return reply or fallback
    except requests.RequestException:
        return fallback
    except (KeyError, IndexError, TypeError, ValueError):
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
        suggestions = f"{suggestions}\n\n{suggestion_footer()}"

    session["food_options"] = parsed_options
    session["ads"] = get_ads_for_options(parsed_options)
    session["selected_food"] = ""
    session["ingredients"] = []
    session["grocery_list"] = []
    session["recipe_steps"] = []
    session["stage"] = "choose_food"
    return suggestions


def normalize_choice(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


@app.route("/", methods=["GET", "POST"])
def index():
    assistant_reply = session.get("assistant_reply", "")

    if request.method == "POST":
        user_message = request.form.get("message", "").strip()
        lowered = user_message.lower()
        stage = session.get("stage", "start")
        saved_taste = session.get("taste_preference", "")
        selected_food = session.get("selected_food", "")
        food_options = session.get("food_options", [])

        if lowered != "cook":
            session["ingredients"] = []
            session["grocery_list"] = []
            session["recipe_steps"] = []

        if not user_message:
            assistant_reply = "Say a craving and I got you."
        elif lowered == "show more":
            if saved_taste:
                assistant_reply = get_suggestions_reply(saved_taste, show_more=True)
            else:
                assistant_reply = (
                    "What your taste buds saying tho? Sweet, salty, spicy, comfort?"
                )
                session["stage"] = "ask_taste"
        elif stage == "start":
            assistant_reply = (
                "What your taste buds saying tho? Sweet, salty, spicy, comfort?"
            )
            session["stage"] = "ask_taste"
        elif stage == "ask_taste":
            session["taste_preference"] = user_message
            assistant_reply = get_suggestions_reply(user_message)
        elif lowered == "cook":
            if selected_food:
                cook_plan = get_cook_plan(selected_food)

                assistant_reply = cook_plan["intro"]

                # Store recipe data
                session["ingredients"] = cook_plan["ingredients"]
                session["recipe_steps"] = cook_plan["steps"]

                # NEW: grocery list (same as ingredients for now)
                session["grocery_list"] = cook_plan["ingredients"]

                session["stage"] = "done"
            else:
                assistant_reply = "Pick one first or say 'show more' 👀"
                session["stage"] = "choose_food"
        elif lowered == "order":
            if selected_food:
                assistant_reply = safe_generate_reply(
                    build_order_prompt(selected_food),
                    (
                        f"For {selected_food}, hit up casual spots, diners, pubs, "
                        "or comfort food joints."
                    ),
                )
                session["stage"] = "done"
            else:
                assistant_reply = "Pick one first or say 'show more' 👀"
                session["stage"] = "choose_food"
        elif stage == "choose_food":
            normalized_message = normalize_choice(user_message)
            matched_option = next(
                (
                    option
                    for option in food_options
                    if normalize_choice(option) == normalized_message
                ),
                "",
            )
            if matched_option:
                session["selected_food"] = matched_option
                assistant_reply = "Bet 😏 you tryna cook or order?"
                session["stage"] = "choose_mode"
            else:
                assistant_reply = "Pick one from the list or say 'show more' 👀"
        elif stage == "choose_mode":
            assistant_reply = "Say 'cook' or 'order' 😏"
        else:
            assistant_reply = (
                "If you want another round, throw me a new craving and we can run it back."
            )
            session["stage"] = "ask_taste"

        session["assistant_reply"] = assistant_reply

    return render_template(
        "index.html",
        assistant_reply=assistant_reply,
        ingredients=session.get("ingredients", []),
        recipe_steps=session.get("recipe_steps", []),
        grocery_list=session.get("grocery_list", []),
        ads=session.get("ads", []),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
