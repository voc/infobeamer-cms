from conf import CONFIG
from util.sso.c3hub import get_c3hub_userid, get_c3hub_username
from util.sso.c3voc import (
    check_c3voc_allowed_login,
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

SSO_CONFIG = {
    "c3hub": {
        "display_name": "38C3 Hub",
        "authorize_url": "https://events.ccc.de/congress/2024/hub/sso/authorize",
        "token_url": "https://events.ccc.de/congress/2024/hub/sso/token",
        "scopes": ["38c3_attendee"],
        "userinfo_url": "https://api.events.ccc.de/congress/2024/me",
        "challenge_instead_of_state": True,
        "functions": {
            "is_admin": lambda json: False,
            "login_allowed": lambda json: True,
            "no_limit": lambda json: False,
            "userid": get_c3hub_userid,
            "username": get_c3hub_username,
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
            "login_allowed": check_c3voc_allowed_login,
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
}


for provider in CONFIG["oauth2_providers"]:
    if provider not in SSO_CONFIG:
        raise RuntimeError(
            f"SSO provider {provider} found in config, but not configured."
        )
