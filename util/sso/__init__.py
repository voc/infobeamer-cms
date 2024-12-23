from util.sso.github import (
    check_github_allowed_login,
    check_github_is_admin,
    check_github_no_limit,
    get_github_username,
)

SSO_CONFIG = {
    "github": {
        "display_name": "GitHub",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["user:email"],
        "userinfo_url": "https://api.github.com/user",
        "functions": {
            "is_admin": check_github_is_admin,
            "login_allowed": check_github_allowed_login,
            "no_limit": check_github_no_limit,
            "username": get_github_username,
        },
    },
}