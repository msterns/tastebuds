from utils.helpers import normalize


def get_user_profile(session):
    if "user_profile" not in session:
        session["user_profile"] = {
            "diet": "",
            "likes": {},
            "dislikes": {},
            "allergies": [],
            "history": [],
        }
    profile = session["user_profile"]

    if isinstance(profile.get("likes"), list):
        profile["likes"] = {item: 1 for item in profile["likes"]}
    if isinstance(profile.get("dislikes"), list):
        profile["dislikes"] = {item: 1 for item in profile["dislikes"]}
    if "history" not in profile:
        profile["history"] = []

    session["user_profile"] = profile
    return profile


def update_user_profile(user_message, session):
    profile = get_user_profile(session)
    lowered = normalize(user_message)

    if "vegan" in lowered:
        profile["diet"] = "vegan"
    elif "keto" in lowered:
        profile["diet"] = "keto"

    if "dont like" in lowered or "don't like" in lowered:
        words = lowered.split("like")
        if len(words) > 1:
            item = words[-1].strip()
            if item:
                profile["dislikes"][item] = profile["dislikes"].get(item, 0) + 1

    if "allergic" in lowered:
        words = lowered.split("to")
        if len(words) > 1:
            item = words[-1].strip()
            if item and item not in profile["allergies"]:
                profile["allergies"].append(item)

    session["user_profile"] = profile
    return profile


def format_profile_for_ai(profile):
    return f"""
User Preferences:
Diet: {profile.get("diet")}
Likes: {profile.get("likes")}
Dislikes: {profile.get("dislikes")}
Allergies: {profile.get("allergies")}
"""


def format_behavior_for_ai(profile):
    likes = profile.get("likes", {})
    history = profile.get("history", [])

    return f"""
Behavior Insights:
Frequent Choices: {history[-5:]}
Inferred Likes: {likes}
"""


def track_user_choice(food, session):
    profile = get_user_profile(session)

    if "history" not in profile:
        profile["history"] = []

    profile["history"].append(food.lower())
    key = food.lower()
    profile["likes"][key] = profile["likes"].get(key, 0) + 1

    session["user_profile"] = profile


def infer_preferences(session):
    profile = get_user_profile(session)

    history = profile.get("history", [])

    seafood_keywords = ["shrimp", "salmon", "fish"]
    chicken_keywords = ["chicken", "wings"]

    seafood_count = sum(any(k in item for k in seafood_keywords) for item in history)
    chicken_count = sum(any(k in item for k in chicken_keywords) for item in history)

    if seafood_count >= 2:
        profile["likes"]["seafood"] = max(profile["likes"].get("seafood", 0), seafood_count)

    if chicken_count >= 2:
        profile["likes"]["chicken"] = max(profile["likes"].get("chicken", 0), chicken_count)

    session["user_profile"] = profile


def track_rejection(session):
    profile = get_user_profile(session)
    last = session.get("last_suggestion")

    if last:
        key = last.lower()

        if "dislikes" not in profile:
            profile["dislikes"] = {}

        profile["dislikes"][key] = profile["dislikes"].get(key, 0) + 1

    session["user_profile"] = profile


def get_user_familiarity(session):
    profile = get_user_profile(session)

    history = profile.get("history", [])
    total_interactions = len(history)

    return total_interactions
