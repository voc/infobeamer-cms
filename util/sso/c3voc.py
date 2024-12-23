from datetime import datetime, timezone
from logging import getLogger

from conf import CONFIG

LOG = getLogger("SSO-C3VOC")

def get_c3voc_userid(userinfo_json):
    return "c3voc:{}".format(userinfo_json["preferred_username"])


def get_c3voc_username(userinfo_json):
    return "{} (C3VOC)".format(userinfo_json["preferred_username"])


def check_c3voc_allowed_login(userinfo_json):
    return True


def check_c3voc_is_admin(userinfo_json):
    return "signage-admin" in userinfo_json["groups"]


def check_c3voc_no_limit(userinfo_json):
    return "signage-no-limit" in userinfo_json["groups"]
