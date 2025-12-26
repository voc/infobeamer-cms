from datetime import datetime, timezone
from logging import getLogger

from conf import CONFIG

LOG = getLogger("SSO-Github")


def get_github_userid(userinfo_json):
    return "github:{}".format(userinfo_json["login"])


def get_github_username(userinfo_json):
    return "{} on GitHub".format(userinfo_json["login"])


def check_github_allowed_login(userinfo_json):
    if userinfo_json["type"] != "User":
        return False

    age = datetime.now(timezone.utc) - datetime.fromisoformat(
        userinfo_json["created_at"]
    )
    LOG.info(f"user is {age.days} days old")
    LOG.info("user has {} followers".format(userinfo_json["followers"]))
    if age.days < 31 and userinfo_json["followers"] < 10:
        return False
    return True


def check_github_is_admin(userinfo_json):
    return f"github:{userinfo_json['login'].lower()}" in CONFIG["ADMIN_USERS"]


def check_github_no_limit(userinfo_json):
    return f"github:{userinfo_json['login'].lower()}" in CONFIG["NO_LIMIT_USERS"]
