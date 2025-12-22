from conf import CONFIG
from util.sso.c3hub import (
    c3hub_badge_after_confirm,
    check_c3hub_no_limit,
    get_c3hub_userid,
    get_c3hub_username,
)
from util.sso.c3voc import (
    check_c3voc_is_admin,
    check_c3voc_no_limit,
    get_c3voc_userid,
    get_c3voc_username,
)
from util.sso.github import (
    check_github_allowed_login,
    check_github_is_admin,
    check_github_no_limit,
    get_github_userid,
    get_github_username,
)
from util.sso.google import (
    check_google_is_admin,
    check_google_no_limit,
    get_google_userid,
    get_google_username,
)

SSO_CONFIG = {
    "c3hub": {
        "display_name": "39C3 Hub",
        "authorize_url": "https://events.ccc.de/congress/2025/hub/sso/authorize/",
        "token_url": "https://events.ccc.de/congress/2025/hub/sso/token/",
        "scopes": ["39c3_attendee"],
        "userinfo_url": "https://api.events.ccc.de/congress/2025/me",
        "challenge_instead_of_state": True,
        "functions": {
            "is_admin": lambda json: False,
            "login_allowed": lambda json: True,
            "no_limit": check_c3hub_no_limit,
            "userid": get_c3hub_userid,
            "username": get_c3hub_username,
            "after_confirm_action": c3hub_badge_after_confirm,
        },
    },
    "c3voc": {
        "display_name": "C3VOC",
        "authorize_url": "https://sso.c3voc.de/application/o/authorize/",
        "token_url": "https://sso.c3voc.de/application/o/token/",
        "scopes": ["openid", "profile", "groups"],
        "userinfo_url": "https://sso.c3voc.de/application/o/userinfo/",
        "challenge_instead_of_state": False,
        "functions": {
            "is_admin": check_c3voc_is_admin,
            "login_allowed": lambda json: True,
            "no_limit": check_c3voc_no_limit,
            "userid": get_c3voc_userid,
            "username": get_c3voc_username,
        },
    },
    "github": {
        "display_name": "GitHub",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": [],
        "userinfo_url": "https://api.github.com/user",
        "challenge_instead_of_state": False,
        "functions": {
            "is_admin": check_github_is_admin,
            "login_allowed": check_github_allowed_login,
            "no_limit": check_github_no_limit,
            "userid": get_github_userid,
            "username": get_github_username,
        },
    },
    "google": {
        "display_name": "Google",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": " https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
        "userinfo_url": "https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
        "challenge_instead_of_state": False,
        "functions": {
            "is_admin": check_google_is_admin,
            "login_allowed": lambda json: True,
            "no_limit": check_google_no_limit,
            "userid": get_google_userid,
            "username": get_google_username,
        },
    },
}


for provider in CONFIG["oauth2_providers"]:
    if provider not in SSO_CONFIG:
        raise RuntimeError(f"SSO provider {provider} found in config, but not known.")


DEFAULT_SSO_PROVIDER = CONFIG.get(
    "DEFAULT_SSO_PROVIDER", list(CONFIG["oauth2_providers"].keys())[0]
)
DEFAULT_ADMIN_SSO_PROVIDER = CONFIG.get(
    "DEFAULT_ADMIN_SSO_PROVIDER", list(CONFIG["oauth2_providers"].keys())[0]
)

assert (
    DEFAULT_SSO_PROVIDER in CONFIG["oauth2_providers"]
), f"SSO provider {DEFAULT_SSO_PROVIDER} set as default, but not configured."
assert (
    DEFAULT_ADMIN_SSO_PROVIDER in CONFIG["oauth2_providers"]
), f"SSO provider {DEFAULT_ADMIN_SSO_PROVIDER} set as default, but not configured."
