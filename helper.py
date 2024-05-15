import os
import random
from datetime import datetime
from functools import wraps
import shutil
import tempfile

from flask import abort, current_app, g, jsonify, url_for
import requests

from conf import CONFIG
from ib_hosted import ib


def error(msg):
    return jsonify(error=msg), 400

def user_is_admin(user) -> bool:
    return user is not None and user.lower() in CONFIG.get("ADMIN_USERS", set())

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user_is_admin:
            abort(401)
        return f(*args, **kwargs)
    return decorated_function

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

def get_assets_awaiting_moderation():
    assets = ib.get("asset/list")["assets"]
    return [
        asset
        for asset in assets
        if asset["userdata"].get("user") and asset["userdata"].get("state") == None
    ]


def get_all_live_assets(no_time_filter=False):
    now = int(datetime.now().timestamp())
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
    if user_is_admin(user):
        return False

    now = datetime.now().timestamp()
    return not (CONFIG["TIME_MIN"] < now < CONFIG["TIME_MAX"])


def get_random(size=16):
    return "".join("%02x" % random.getrandbits(8) for i in range(size))


def make_asset_json(assets, mod_data=False):
    return jsonify(
        assets=[
            {
                "user": asset["userdata"]["user"],
                "filetype": asset["filetype"],
                "thumb": asset["thumb"],
                "url": url_for("static", filename=cached_asset_name(asset)),
            } | ({
                "moderate_url": url_for(
                    "content_moderate", asset_id=asset["id"], _external=True
                ),
                "moderated_by": asset["userdata"].get("moderated_by"),
            } if mod_data else {})
            for asset in assets
        ]
    )


def cached_asset_name(asset):
    asset_id = asset["id"]
    filename = "asset-{}.{}".format(
        asset_id,
        "jpg" if asset["filetype"] == "image" else "mp4",
    )
    cache_name = os.path.join(CONFIG.get('STATIC_PATH', 'static'), filename)

    if not os.path.exists(cache_name):
        current_app.logger.info(f"fetching {asset_id} to {cache_name}")
        dl = ib.get(f"asset/{asset_id}/download")
        r = requests.get(dl["download_url"], stream=True, timeout=5)
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            shutil.copyfileobj(r.raw, f)
            shutil.move(f.name, cache_name)
            os.chmod(cache_name, 0o664)
        del r

    return filename