from requests import get as get

from conf import CONFIG


def get_c3hub_userid(userinfo_json):
    return "c3hub:{}".format(userinfo_json["username"])


def get_c3hub_username(userinfo_json):
    return "{} (38C3)".format(userinfo_json["username"])


def check_c3hub_no_limit(userinfo_json):
    return f"c3hub:{userinfo_json['username'].lower()}" in CONFIG["NO_LIMIT_USERS"]


def c3hub_badge_after_confirm(asset):
    if "badge_claim_url" not in CONFIG["oauth2_providers"]["c3voc"]:
        return

    username = asset.userid[len("c3hub:") :]
    try:
        r = get(
            CONFIG["oauth2_providers"]["c3voc"]["badge_claim_url"].format(
                username=username
            ),
            timeout=5,
        )
        r.raise_for_status()
    except Exception as e:
        app.logger.error(f"Failed to get badge for user {username}: {e!r}")
