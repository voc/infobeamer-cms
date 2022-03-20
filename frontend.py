import hmac
import json
import logging
import os
import pickle
import random
import shutil
import socket
import tempfile
import time
from datetime import datetime
from logging import basicConfig, getLogger
from secrets import token_hex

import iso8601
import paho.mqtt.client as mqtt
import redis
import requests
from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    sessions,
    url_for,
)
from flask.sessions import SessionInterface
from flask_github import GitHub
from toml import load as toml_load
from werkzeug.middleware.proxy_fix import ProxyFix

basicConfig(
    format="[%(levelname)s %(name)s] %(message)s",
    level=logging.INFO,
)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)
app.config.from_file(os.environ["SETTINGS"], load=toml_load)

socket.setdefaulttimeout(3)  # for mqtt

r = redis.Redis()

github = GitHub(app)


class IBHosted(object):
    def __init__(self):
        self._session = requests.Session()
        self._session.auth = "", app.config["HOSTED_API_KEY"]
        self.log = getLogger("IBHosted")

    def get(self, ep, **params):
        self.log.debug(f'get("{ep}", {params})')
        r = self._session.get(
            f"https://info-beamer.com/api/v1/{ep}", params=params, timeout=5
        )
        self.log.debug(r.text)
        r.raise_for_status()
        return r.json()

    def post(self, ep, **data):
        self.log.debug(f'post("{ep}")')
        r = self._session.post(
            f"https://info-beamer.com/api/v1/{ep}", data=data, timeout=5
        )
        self.log.debug(r.text)
        r.raise_for_status()
        return r.json()

    def delete(self, ep, **data):
        self.log.debug(f'delete("{ep}")')
        r = self._session.delete(
            f"https://info-beamer.com/api/v1/{ep}", data=data, timeout=5
        )
        self.log.debug(r.text)
        r.raise_for_status()
        return r.json()


ib = IBHosted()


def tojson(v):
    return json.dumps(v, separators=(",", ":"))


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
    now = int(time.time())
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


def get_scoped_api_key(statements, expire=60, uses=16):
    return ib.post(
        "adhoc/create",
        expire=expire,
        uses=uses,
        policy=tojson(
            {
                "Version": 1,
                "Statements": statements,
            }
        ),
    )["api_key"]


def update_asset_userdata(asset, **kw):
    userdata = asset["userdata"]
    userdata.update(kw)
    ib.post("asset/{}".format(asset["id"]), userdata=tojson(userdata))


def cached_asset_name(asset):
    asset_id = asset["id"]
    filename = "asset-{}.{}".format(
        asset_id,
        "jpg" if asset["filetype"] == "image" else "mp4",
    )
    cache_name = f"static/{filename}"

    if not os.path.exists(cache_name):
        app.logger.info(f"fetching {asset_id} to {cache_name}")
        dl = ib.get(f"asset/{asset_id}/download")
        r = requests.get(dl["download_url"], stream=True, timeout=5)
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            shutil.copyfileobj(r.raw, f)
            shutil.move(f.name, cache_name)
            os.chmod(cache_name, 0o664)
        del r

    return filename


def get_random(size=16):
    return "".join("%02x" % random.getrandbits(8) for i in range(size))


def mk_sig(value):
    app.logger.debug(f'mk_sig("{value}")')
    return hmac.new(
        app.config["URL_KEY"].encode(), str(value).encode(), digestmod="sha256"
    ).hexdigest()


def error(msg):
    return jsonify(error=msg), 400


class RedisSession(sessions.CallbackDict, sessions.SessionMixin):
    def __init__(self, sid=None, initial=None):
        def on_update(self):
            self.modified = True

        sessions.CallbackDict.__init__(self, initial, on_update)
        self.modified = False
        self.new_sid = not sid
        self.sid = sid or get_random(32)


class RedisSessionStore(SessionInterface):
    def open_session(self, app, request):
        sid = request.cookies.get(app.session_cookie_name)
        if not sid:
            return RedisSession()
        data = r.get(f"sid:{sid}")
        if data is None:
            return RedisSession()
        return RedisSession(sid, pickle.loads(data))

    def save_session(self, app, session, response):
        if not session.modified:
            return
        state = dict(session)
        if state:
            r.setex(f"sid:{session.sid}", 86400, pickle.dumps(state, 2))
        else:
            r.delete(f"sid:{session.sid}")
        if session.new_sid:
            response.set_cookie(
                app.session_cookie_name,
                session.sid,
                httponly=True,
                secure=True,
                samesite="Lax",
            )


app.session_interface = RedisSessionStore()


@app.before_request
def before_request():
    user = session.get("gh_login")
    g.now = datetime.utcnow().timestamp()

    if (
        user
        and user.lower() not in app.config.get("ADMIN_USERS", set())
        and (g.now > app.config["TIME_MAX"] or g.now < app.config["TIME_MIN"])
    ):
        session.clear()
        g.user = None
        g.avatar = None
        return

    g.user = user
    g.avatar = session.get("gh_avatar")


@app.route("/github-callback")
@github.authorized_handler
def authorized(access_token):
    if g.now > app.config["TIME_MAX"]:
        abort(403)

    if access_token is None:
        return redirect(url_for("index"))

    state = request.args.get("state")
    if state is None or state != session.get("state"):
        return redirect(url_for("index"))
    session.pop("state")

    github_user = github.get("user", access_token=access_token)
    if github_user["type"] != "User":
        return redirect(url_for("faq", _anchor="signup"))

    # app.logger.debug(github_user)

    age = datetime.utcnow() - iso8601.parse_date(github_user["created_at"]).replace(
        tzinfo=None
    )

    app.logger.info(f"user is {age.days} days old")
    if age.days < 31:
        return redirect(url_for("faq", _anchor="signup"))

    app.logger.info("user has {} followers".format(github_user["followers"]))
    if github_user["followers"] < 5:
        return redirect(url_for("faq", _anchor="signup"))

    session["gh_login"] = github_user["login"]
    return redirect(url_for("dashboard"))


@app.route("/login")
def login():
    if g.now > app.config["TIME_MAX"]:
        abort(403)

    if g.user:
        return redirect(url_for("dashboard"))
    session["state"] = state = get_random()
    return github.authorize(state=state)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/")
def index():
    return render_template("index.jinja")


@app.route("/last")
def last():
    return render_template("last.jinja")


@app.route("/faq")
def faq():
    return render_template("faq.jinja")


# @app.route('/interrupt')
# def saal():
#    interrupt_key = get_scoped_api_key([{
#        "Action": "device:node-message",
#        "Condition": {
#            "StringEquals": {
#                "message:path": "root/remote/trigger"
#            }
#        },
#        "Effect": "allow",
#    }], expire=300, uses=20)
#    return render_template('interrupt.jinja',
#        interrupt_key = interrupt_key,
#    )


@app.route("/dashboard")
def dashboard():
    if not g.user:
        return redirect(url_for("index"))
    return render_template("dashboard.jinja")


@app.route("/sync")
def sync():
    log = getLogger("sync")

    log.info("Starting sync")

    def asset_to_tiles(asset):
        log.debug("adding {} to Page".format(asset["id"]))

        tiles = []
        if asset["filetype"] == "video":
            tiles.append(
                {
                    "type": "rawvideo",
                    "asset": asset["id"],
                    "x1": 0,
                    "y1": 0,
                    "x2": 1920,
                    "y2": 1080,
                    "config": {
                        "layer": -5,
                        "looped": True,
                    },
                }
            )
        else:
            tiles.append(
                {
                    "type": "image",
                    "asset": asset["id"],
                    "x1": 0,
                    "y1": 0,
                    "x2": 1920,
                    "y2": 1080,
                }
            )
        tiles.append(
            {
                "type": "flat",
                "asset": "flat.png",
                "x1": 0,
                "y1": 1040,
                "x2": 1920,
                "y2": 1080,
                "config": {"color": "#000000", "alpha": 230, "fade_time": 0},
            }
        )
        tiles.append(
            {
                "type": "markup",
                "asset": "default-font.ttf",
                "x1": 150,
                "y1": 1048,
                "x2": 1900,
                "y2": 1080,
                "config": {
                    "font_size": 25,
                    "fade_time": 0.5,
                    "text": "Project by @{user} - visit {url} to share your own.".format(
                        user=asset["userdata"]["user"],
                        url=url_for(
                            "index",
                            _external=True,
                        ),
                    ),
                    "color": "#dddddd",
                },
            }
        )
        if "EXTRA_ASSETS" in app.config:
            tiles.extend(app.config["EXTRA_ASSETS"])
        return tiles

    pages = []
    for asset in get_all_live_assets():
        pages.append(
            {
                "tiles": asset_to_tiles(asset),
                "interaction": {"key": ""},
                "layout_id": -1,  # Use first layout
                "overlap": 0,
                "auto_duration": 10,
                "duration": 10,
            }
        )

    log.info("There are currently {} pages visible".format(len(pages)))

    for setup_id in app.config["SETUP_IDS"]:
        config = ib.get(f"setup/{setup_id}")["config"][""]

        for schedule in config["schedules"]:
            if schedule["name"] == "User Content":
                log.info('Found schedule "User Content" in setup {}'.format(setup_id))

                schedule["pages"] = pages

        ib.post(
            f"setup/{setup_id}",
            config=tojson({"": config}),
            mode="update",
        )

    r.set("last-sync", int(time.time()))
    log.info("updated everything")

    return "ok"


@app.route("/content/list")
def content_list():
    if not g.user:
        return error("Needs login")
    assets = get_user_assets()
    random.shuffle(assets)
    return jsonify(
        assets=assets,
    )


@app.route("/content/upload", methods=["POST"])
def content_upload():
    if not g.user:
        return error("Needs login")

    max_uploads = r.get(f"max_uploads:{g.user}")
    if max_uploads is not None:
        max_uploads = int(max_uploads)
    if not max_uploads:
        max_uploads = app.config["MAX_UPLOADS"]
    if len(get_user_assets()) >= max_uploads:
        return error("You have reached your upload limit")

    filetype = request.values.get("filetype")
    if filetype not in ("image", "video"):
        return error("Invalid/missing filetype")
    extension = "jpg" if filetype == "image" else "mp4"

    filename = "user/{}/{}_{}.{}".format(
        g.user, datetime.utcnow().strftime("%Y-%d-%m %H:%M:%S"), token_hex(8), extension
    )
    condition = {
        "StringEquals": {
            "asset:filename": filename,
            "asset:filetype": filetype,
            "userdata:user": g.user,
        },
        "NotExists": {
            "userdata:state": True,
        },
        "Boolean": {
            "asset:exists": False,
        },
    }
    if filetype == "image":
        condition.setdefault("NumericEquals", {}).update(
            {
                "asset:metadata:width": 1920,
                "asset:metadata:height": 1080,
            }
        )
        condition.setdefault("StringEquals", {}).update(
            {
                "asset:metadata:format": "jpeg",
            }
        )
    else:
        condition.setdefault("NumericLess", {}).update(
            {
                "asset:metadata:duration": 11,
            }
        )
        condition.setdefault("StringEquals", {}).update(
            {
                "asset:metadata:format": "h264",
            }
        )
    return jsonify(
        filename=filename,
        user=g.user,
        upload_key=get_scoped_api_key(
            [{"Action": "asset:upload", "Condition": condition, "Effect": "allow"}],
            uses=1,
        ),
    )


@app.route("/content/review/<int:asset_id>", methods=["POST"])
def content_request_review(asset_id):
    if not g.user:
        return error("Needs login")

    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    if asset["userdata"].get("user") != g.user:
        return error("Cannot review")

    if "state" in asset["userdata"]:  # not in new state?
        return error("Cannot review")

    moderation_url = url_for(
        "content_moderate", asset_id=asset_id, sig=mk_sig(asset_id), _external=True
    )

    client = mqtt.Client()
    if app.config.get("MQTT_USERNAME") and app.config.get("MQTT_PASSWORD"):
        client.username_pw_set(app.config["MQTT_USERNAME"], app.config["MQTT_PASSWORD"])
    client.connect(app.config["MQTT_SERVER"])
    result = client.publish(
        app.config["MQTT_TOPIC"],
        app.config["MQTT_MESSAGE"].format(
            user=g.user,
            asset=asset["filetype"].capitalize(),
            url=moderation_url,
        ),
    )
    client.disconnect()
    assert result[0] == 0

    app.logger.info("moderation url for {} is {}".format(asset["id"], moderation_url))

    update_asset_userdata(asset, state="review")
    return jsonify(ok=True)


@app.route("/content/moderate/<int:asset_id>-<sig>")
def content_moderate(asset_id, sig):
    if sig != mk_sig(asset_id):
        abort(404)

    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    state = asset["userdata"].get("state", "new")
    if state == "deleted":
        abort(404)

    return render_template(
        "moderate.jinja",
        asset={
            "id": asset["id"],
            "user": asset["userdata"]["user"],
            "filetype": asset["filetype"],
            "url": url_for("static", filename=cached_asset_name(asset)),
            "state": state,
        },
        sig=mk_sig(asset_id),
    )


@app.route(
    "/content/moderate/<int:asset_id>-<sig>/<any(confirm,reject):result>",
    methods=["POST"],
)
def content_moderate_result(asset_id, sig, result):
    if sig != mk_sig(asset_id):
        abort(404)

    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    if result == "confirm":
        app.logger.info("Asset {} was confirmed".format(asset["id"]))
        update_asset_userdata(asset, state="confirmed")
    else:
        app.logger.info("Asset {} was rejected".format(asset["id"]))
        update_asset_userdata(asset, state="rejected")

    return jsonify(ok=True)


@app.route("/content/<int:asset_id>", methods=["POST"])
def content_update(asset_id):
    if not g.user:
        return error("Needs login")

    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    starts = request.values.get("starts", type=int)
    ends = request.values.get("ends", type=int)

    if asset["userdata"].get("user") != g.user:
        return error("Cannot update")

    try:
        update_asset_userdata(asset, starts=starts, ends=ends)
    except Exception as e:
        app.logger.error(f"content_update({asset_id}) {repr(e)}")
        return error("Cannot update")

    return jsonify(ok=True)


@app.route("/content/<int:asset_id>", methods=["DELETE"])
def content_delete(asset_id):
    if not g.user:
        return error("Needs login")

    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    if asset["userdata"].get("user") != g.user:
        return error("Cannot delete")

    try:
        update_asset_userdata(asset, state="deleted")
    except Exception as e:
        app.logger.error(f"content_delete({asset_id}) {repr(e)}")
        return error("Cannot delete")

    return jsonify(ok=True)


@app.route("/content/live")
def content_live():
    no_time_filter = request.values.get("all")
    assets = get_all_live_assets(no_time_filter=no_time_filter)
    random.shuffle(assets)
    resp = jsonify(
        assets=[
            {
                "user": asset["userdata"]["user"],
                "filetype": asset["filetype"],
                "thumb": asset["thumb"],
                "url": url_for("static", filename=cached_asset_name(asset)),
            }
            for asset in assets
        ]
    )
    resp.headers["Cache-Control"] = "public, max-age=30"
    return resp


@app.route("/content/last")
def content_last():
    assets = get_all_live_assets()
    asset_by_id = dict((asset["id"], asset) for asset in assets)

    last = {}

    for room in app.config["ROOMS"]:
        proofs = [
            json.loads(data)
            for data in r.zrange("last:{}".format(room["device_id"]), 0, -1)
        ]

        last[room["name"]] = room_last = []
        for proof in reversed(proofs):
            asset = asset_by_id.get(proof["asset_id"])
            if asset is None:
                continue
            room_last.append(
                {
                    "id": proof["id"],
                    "user": asset["userdata"]["user"],
                    "filetype": asset["filetype"],
                    "shown": int(proof["ts"]),
                    "thumb": asset["thumb"],
                    "url": url_for("static", filename=cached_asset_name(asset)),
                }
            )
            if len(room_last) > 10:
                break

    resp = jsonify(
        last=[
            [room["name"], last.get(room["name"], [])] for room in app.config["ROOMS"]
        ]
    )
    resp.headers["Cache-Control"] = "public, max-age=5"
    return resp


@app.route("/check/sync")
def check_sync():
    if time.time() > int(r.get("last-sync")) + 1200:
        abort(503)
    return "ok"


@app.route("/check/twitter")
def check_twitter():
    if time.time() > int(r.get("last-twitter")) + 1200:
        abort(503)
    return "ok"


@app.route("/proof", methods=["POST"])
def proof():
    proofs = [(json.loads(row), row) for row in request.stream.read().split("\n")]
    device_ids = set()
    p = r.pipeline()
    for proof, row in proofs:
        p.zadd("last:{}".format(proof["device_id"]), row, proof["ts"])
        device_ids.add(proof["device_id"])
    for device_id in device_ids:
        p.zremrangebyscore(f"last:{device_id}", 0, time.time() - 1200)
    p.execute()
    return "ok"


@app.route("/robots.txt")
def robots_txt():
    return "User-Agent: *\nDisallow: /\n"


if __name__ == "__main__":
    app.run(port=8080)
