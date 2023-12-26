import hmac
import random
from datetime import datetime

from flask import g, jsonify

from conf import CONFIG
from ib_hosted import ib


def error(msg):
    return jsonify(error=msg), 400


def get_user_assets():
    assets = ib.get("asset/list")["assets"]
    return [
        {
            "id": asset["id"],
            "filetype": asset["filetype"],
            "thumb": asset["thumb"],
            "state": asset["userdata"].get("state", "new"),
            "starts": asset["userdata"].get("starts"),
            "ends": asset["userdata"].get("ends"),
        }
        for asset in assets
        if asset["userdata"].get("user") == g.user
        and asset["userdata"].get("state") != "deleted"
    ]


def get_all_live_assets(no_time_filter=False):
    now = int(datetime.utcnow().timestamp())
    assets = ib.get("asset/list")["assets"]
    return [
        asset
        for asset in assets
        if asset["userdata"].get("state") in ("confirmed",)
        and asset["userdata"].get("user") is not None
        and (
            no_time_filter
            or (
                (asset["userdata"].get("starts") or now) <= now
                and (asset["userdata"].get("ends") or now) >= now
            )
        )
    ]


def login_disabled_for_user(user=None):
    if user and user.lower() in CONFIG.get("ADMIN_USERS", set()):
        return False

    now = datetime.utcnow().timestamp()
    return not (CONFIG["TIME_MIN"] < now < CONFIG["TIME_MAX"])


def get_random(size=16):
    return "".join("%02x" % random.getrandbits(8) for i in range(size))


def mk_sig(value):
    return hmac.new(
        CONFIG["URL_KEY"].encode(), str(value).encode(), digestmod="sha256"
    ).hexdigest()
