import enum
import os
import random
import shutil
import tempfile
from datetime import datetime, timezone
from functools import wraps
from typing import NamedTuple, Optional

import requests
from flask import abort, current_app, g, jsonify, redirect, request, session, url_for

from conf import CONFIG

from .ib_hosted import ib

DEFAULT_SSO_PROVIDER = CONFIG.get(
    "DEFAULT_SSO_PROVIDER", list(CONFIG["oauth2_providers"].keys())[0]
)
DEFAULT_ADMIN_SSO_PROVIDER = CONFIG.get(
    "DEFAULT_ADMIN_SSO_PROVIDER", list(CONFIG["oauth2_providers"].keys())[0]
)


def error(msg):
    return jsonify(error=msg), 400


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.userid:
            session["redirect_after_login"] = request.url
            return redirect(url_for("login", provider=DEFAULT_SSO_PROVIDER))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.userid:
            session["redirect_after_login"] = request.url
            return redirect(url_for("login", provider=DEFAULT_ADMIN_SSO_PROVIDER))
        if not g.user_is_admin:
            abort(401)
        return f(*args, **kwargs)

    return decorated_function


class State(enum.StrEnum):
    NEW = "new"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    DELETED = "deleted"
    REVIEW = "review"


class Asset(NamedTuple):
    id: str
    filetype: str
    thumb: str
    state: State
    user: str
    starts: Optional[int] = None
    ends: Optional[int] = None
    moderate_url: Optional[str] = None
    moderated_by: Optional[str] = None

    def to_dict(self, user_data=False, mod_data=False):
        result = {
            "id": self.id,
            "user": self.user,
            "filetype": self.filetype,
            "thumb": self.thumb,
            "url": url_for("static", filename=cached_asset_name(self)),
        }

        if user_data or mod_data:
            result.update(
                {
                    "state": self.state,
                    "starts": self.starts,
                    "ends": self.ends,
                }
            )

        if mod_data:
            result.update(
                {
                    "moderate_url": url_for(
                        "content_moderate", asset_id=self.id, _external=True
                    ),
                    "moderated_by": self.moderated_by,
                }
            )

        return result


def to_int(num):
    return (
        num
        if isinstance(num, int)
        else int(num) if (isinstance(num, str) and num.isdigit()) else None
    )


def parse_asset(asset):
    return Asset(
        id=asset["id"],
        filetype=asset["filetype"],
        thumb=asset["thumb"],
        user=asset["userdata"]["user"],
        state=State(asset["userdata"].get("state", "new")),
        starts=to_int(asset["userdata"].get("starts")),
        ends=to_int(asset["userdata"].get("ends")),
        moderated_by=asset["userdata"].get("moderated_by"),
    )


def get_asset(id):
    return parse_asset(ib.get(f"asset/{id}"))


def get_assets(cached=False):
    assets = ib.get("asset/list", cached=cached)["assets"]
    return [
        parse_asset(asset)
        for asset in assets
        if asset["userdata"].get("user") is not None
    ]


def get_user_assets():
    return [a for a in get_assets() if a.user == g.userid and a.state != State.DELETED]


def get_assets_awaiting_moderation():
    return [asset for asset in get_assets() if asset.state == State.REVIEW]


def get_all_live_assets(no_time_filter=False):
    now = int(datetime.now().timestamp())
    return [
        asset
        for asset in get_assets(cached=True)
        if asset.state in (State.CONFIRMED,)
        and (
            no_time_filter
            or ((asset.starts or now) <= now and (asset.ends or now) >= now)
        )
    ]


def is_within_timeframe():
    now = datetime.now(timezone.utc).timestamp()
    return not (CONFIG["TIME_MIN"] < now < CONFIG["TIME_MAX"])


def get_random(size=16):
    return "".join("%02x" % random.getrandbits(8) for i in range(size))


def cached_asset_name(asset: Asset):
    asset_id = asset.id
    filename = "asset-{}.{}".format(
        asset_id,
        "jpg" if asset.filetype == "image" else "mp4",
    )
    cache_name = os.path.join(CONFIG.get("STATIC_PATH", "static"), filename)

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
