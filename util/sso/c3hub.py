def get_c3hub_userid(userinfo_json):
    return "c3hub:{}".format(userinfo_json["username"])


def get_c3hub_username(userinfo_json):
    return "{} (38C3)".format(userinfo_json["username"])


def check_c3hub_no_limit(userinfo_json):
    return f"c3hub:{userinfo_json['username'].lower()}" in CONFIG["NO_LIMIT_USERS"]
