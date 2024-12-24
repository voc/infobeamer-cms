def get_c3hub_userid(userinfo_json):
    return "c3hub:{}".format(userinfo_json["username"])


def get_c3hub_username(userinfo_json):
    return "{} (38C3)".format(userinfo_json["username"])
