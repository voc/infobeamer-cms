from conf import CONFIG


def get_google_userid(userinfo_json):
    return "google:{}".format(userinfo_json["email"])


def get_google_username(userinfo_json):
    return userinfo_json["name"]


def check_google_is_admin(userinfo_json):
    return f"google:{userinfo_json['email'].lower()}" in CONFIG["ADMIN_USERS"]


def check_google_no_limit(userinfo_json):
    return f"google:{userinfo_json['email'].lower()}" in CONFIG["NO_LIMIT_USERS"]
