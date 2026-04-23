import os

import requests
from core.memory_engine import get_user_familiarity


API_KEY = os.getenv("OPENAI_API_KEY")
SYSTEM_PROMPT = """You are TastyBot 😏, a casual, smart food assistant.

RULES:

* Keep responses under 3 sentences unless necessary
* Never list more than 3 food options unless asked
* Always guide the user (ask follow-up questions when unsure)
* Never sound like a recipe blog
* Never dump long paragraphs
* Speak naturally, like texting a friend

playful -> casual, slightly AAVE, friendly
neutral -> clear and helpful
direct -> concise

Never use profanity.
Never force slang.
Keep responses natural.
"""


def debug_log(label, value):
    safe_text = str(value).encode("ascii", "backslashreplace").decode("ascii")
    print(f"{label}: {safe_text}")


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


def clean_response(text):
    lines = text.split("\n")
    if len(lines) > 6:
        text = "\n".join(lines[:6])
    return text.strip()


def get_ai_reply(user_message, session, fallback="Tell me what you craving 😏", prompt=None):
    familiarity = get_user_familiarity(session)

    if familiarity < 3:
        tone_instruction = "User is new. Keep tone welcoming and simple."
    elif familiarity < 8:
        tone_instruction = "User is returning. Be slightly familiar and relaxed."
    else:
        tone_instruction = "User is a regular. Be more playful, confident, and familiar."

    base_prompt = prompt or user_message
    target_prompt = f"""
{SYSTEM_PROMPT}

{tone_instruction}

{base_prompt}
"""
    reply = safe_generate_reply(
        target_prompt,
        fallback
    )
    return clean_response(reply)
