import os
import random
from datetime import datetime
from functools import wraps
import shutil
import tempfile
from typing import Iterable, NamedTuple, Optional

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

class Asset(NamedTuple):
    id: str
    filetype: str
    thumb: str
    state: str
    user: str
    starts: Optional[str]
    ends: Optional[str]
    moderate_url: Optional[str] = None
    moderated_by: Optional[str] = None

def get_assets():
    assets = ib.get("asset/list")["assets"]
    return [
        Asset(
            id=asset["id"],
            filetype=asset["filetype"],
            thumb=asset["thumb"],
            user=asset["userdata"]["user"],
            state=asset["userdata"].get("state", "new"),
            starts=asset["userdata"].get("starts"),
            ends=asset["userdata"].get("ends"),
        ) for asset in assets if asset["userdata"].get("user") != None
    ]

def get_user_assets():
    return [
        a for a in get_assets()
        if a.user == g.user and a.state != "deleted"
    ]

def get_assets_awaiting_moderation():
    return [
        asset
        for asset in get_assets()
        if asset.state == "new"
    ]


def get_all_live_assets(no_time_filter=False):
    now = int(datetime.now().timestamp())
    return [
        asset
        for asset in get_assets()
        if asset.state in ("confirmed",)
        and (
            no_time_filter
            or (
                (asset.starts or now) <= now
                and (asset.ends or now) >= now
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


def make_asset_json(assets: Iterable[Asset], mod_data=False):
    return jsonify(
        assets=[
            {
                "user": asset.user,
                "filetype": asset.filetype,
                "thumb": asset.thumb,
                "url": url_for("static", filename=cached_asset_name(asset)),
            } | ({
                "moderate_url": url_for(
                    "content_moderate", asset_id=asset.id, _external=True
                ),
                "moderated_by": asset.moderated_by,
            } if mod_data else {})
            for asset in assets
        ]
    )


def cached_asset_name(asset: Asset):
    asset_id = asset.id
    filename = "asset-{}.{}".format(
        asset_id,
        "jpg" if asset.filetype == "image" else "mp4",
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