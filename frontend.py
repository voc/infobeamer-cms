import random
import socket
from collections import defaultdict
from datetime import datetime, timezone
from secrets import token_hex
from typing import Iterable
from urllib.parse import urlencode

import requests
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from prometheus_client import generate_latest
from prometheus_client.core import REGISTRY, GaugeMetricFamily
from prometheus_client.metrics_core import Metric
from prometheus_client.registry import Collector
from werkzeug.middleware.proxy_fix import ProxyFix

from conf import CONFIG
from ib_hosted import get_scoped_api_key, ib, update_asset_userdata
from notifier import Notifier
from redis_session import RedisSessionStore
from util import (
    State,
    admin_required,
    error,
    get_all_live_assets,
    get_asset,
    get_assets,
    get_assets_awaiting_moderation,
    get_random,
    get_user_assets,
    is_within_timeframe,
    login_required,
)
from util.redis import REDIS
from util.sso import SSO_CONFIG

app = Flask(
    __name__,
    static_folder=CONFIG.get("STATIC_PATH", "static"),
)
app.secret_key = CONFIG.get("URL_KEY")
app.wsgi_app = ProxyFix(app.wsgi_app)

for copy_key in (
    "MAX_UPLOADS",
    "ROOMS",
    "TIME_MAX",
    "TIME_MIN",
):
    app.config[copy_key] = CONFIG[copy_key]

socket.setdefaulttimeout(3)  # for mqtt

APP_STARTUP_TIME = int(datetime.now().timestamp())


class SubmissionsCollector(Collector):
    def collect(self) -> Iterable[Metric]:
        counts = defaultdict(int)
        for a in get_assets():
            counts[a.state] += 1
        g = GaugeMetricFamily(
            "submissions", "Counts of content submissions", labels=["state"]
        )
        for state in State:
            # Add any states that we know about but have 0 assets in them
            if state.value not in counts.keys():
                counts[state.value] = 0
        for s, c in counts.items():
            g.add_metric([s], c)
        yield g


class InfobeamerCollector(Collector):
    """Prometheus collector for general infobeamer metrics available from the hosted API."""

    def collect(self) -> Iterable[Metric]:
        # IBHostedCached will cache this for us
        devices = ib.get("device/list", cached=True)["devices"]
        yield GaugeMetricFamily("devices", "Infobeamer devices", len(devices))
        yield GaugeMetricFamily(
            "devices_online",
            "Infobeamer devices online",
            len([d for d in devices if d["is_online"]]),
        )
        m = GaugeMetricFamily(
            "device_model", "Infobeamer device models", labels=["model"]
        )
        counts = defaultdict(int)
        for d in devices:
            if d.get("hw"):
                counts[d["hw"]["model"]] += 1
            else:
                counts["unknown"] += 1
        for model, count in counts.items():
            m.add_metric([model], count)
        yield m


REGISTRY.register(SubmissionsCollector())
REGISTRY.register(InfobeamerCollector())

app.session_interface = RedisSessionStore()


@app.before_request
def before_request():
    provider = session.get("oauth2_provider")
    userinfo = session.get("oauth2_userinfo")

    g.user_is_admin = False
    g.user_without_limits = False
    g.userid = ""
    g.username = ""

    if not provider or not userinfo:
        return

    userid = SSO_CONFIG[provider]["functions"]["userid"](userinfo)
    username = SSO_CONFIG[provider]["functions"]["username"](userinfo)
    user_is_admin = SSO_CONFIG[provider]["functions"]["is_admin"](userinfo)
    user_without_limits = SSO_CONFIG[provider]["functions"]["no_limit"](userinfo)

    if not (user_is_admin or user_without_limits or is_within_timeframe()):
        return

    g.user_is_admin = user_is_admin
    g.user_without_limits = user_without_limits
    g.userid = userid
    g.username = username


@app.context_processor
def login_providers():
    result = {}

    for provider, config in CONFIG["oauth2_providers"].items():
        result[provider] = SSO_CONFIG[provider]["display_name"]

    return {"login_providers": result}


@app.context_processor
def start_time_alert():
    # if g.user is set, the user was successfully logged in (see above)
    if g.userid:
        return {"start_time": None}

    start_time = datetime.fromtimestamp(CONFIG["TIME_MIN"], timezone.utc)

    if start_time < datetime.now(timezone.utc):
        return {"start_time": None}

    return {"start_time": start_time.strftime("%F %T")}


@app.route("/login/<provider>")
def login(provider):
    if g.userid:
        return redirect(url_for("dashboard"))

    provider_config = CONFIG["oauth2_providers"].get(provider, {})
    if not provider_config or provider not in SSO_CONFIG:
        abort(404)

    session["oauth2_state"] = state = get_random()

    qs = urlencode(
        {
            "client_id": provider_config["client_id"],
            "redirect_uri": url_for(
                "oauth2_callback", provider=provider, _external=True
            ),
            "response_type": "code",
            "scope": " ".join(SSO_CONFIG[provider]["scopes"]),
            "state": state,
        }
    )
    return redirect("{}?{}".format(SSO_CONFIG[provider]["authorize_url"], qs))


@app.route("/login/callback/<provider>")
def oauth2_callback(provider):
    if g.userid:
        return redirect(url_for("dashboard"))

    provider_config = CONFIG["oauth2_providers"].get(provider, {})
    if not provider_config or provider not in SSO_CONFIG:
        abort(404)

    if "error" in request.args:
        for k, v in request.args.items():
            if k.startswith("error"):
                flash(f"{k}: {v}", "danger")
        return redirect(url_for("index"))

    if request.args["state"] != session.get("oauth2_state"):
        abort(401)

    if "code" not in request.args:
        abort(400)

    r = requests.post(
        SSO_CONFIG[provider]["token_url"],
        data={
            "client_id": provider_config["client_id"],
            "client_secret": provider_config["client_secret"],
            "code": request.args["code"],
            "grant_type": "authorization_code",
            "redirect_uri": url_for(
                "oauth2_callback", provider=provider, _external=True
            ),
        },
        headers={"Accept": "application/json"},
    )
    if r.status_code != 200:
        abort(400)
    oauth2_token = r.json().get("access_token")

    r = requests.get(
        SSO_CONFIG[provider]["userinfo_url"],
        headers={
            "Authorization": f"Bearer {oauth2_token}",
            "Accept": "application/json",
        },
    )
    userinfo_json = r.json()

    if not SSO_CONFIG[provider]["functions"]["login_allowed"](userinfo_json):
        flash("You are not allowed to log in at this time.", "warning")
        return redirect(url_for("faq", _anchor="signup"))

    session["oauth2_provider"] = provider
    session["oauth2_userinfo"] = userinfo_json

    user_is_admin = SSO_CONFIG[provider]["functions"]["is_admin"](userinfo)
    REDIS.set(f"admin:{userid}", "1" if user_is_admin else "0")

    if "redirect_after_login" in session:
        return redirect(session["redirect_after_login"])
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out", "info")
    return redirect(url_for("index"))


@app.route("/")
def index():
    return render_template("index.jinja")


@app.route("/last")
def last():
    return render_template("last.jinja")


@app.route("/faq")
def faq():
    return render_template("faq.jinja", **CONFIG["FAQ"])


@app.route("/interrupt")
def saal():
    auth = CONFIG.get("INTERRUPT_KEY")
    if not auth:
        abort(404)
    if not g.user_is_admin and request.args.get("auth") != auth:
        abort(401)

    interrupt_key = get_scoped_api_key(
        [
            {
                "Action": "device:node-message",
                "Condition": {"StringEquals": {"message:path": "root/remote/trigger"}},
                "Effect": "allow",
            }
        ],
        expire=900,
        uses=20,
    )
    return render_template(
        "interrupt.jinja",
        interrupt_key=interrupt_key,
    )


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.jinja")


@app.route("/content/list")
@login_required
def content_list():
    assets = [a.to_dict(user_data=True) for a in get_user_assets()]
    random.shuffle(assets)
    resp = jsonify(assets=assets)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/content/awaiting_moderation")
@admin_required
def content_awaiting_moderation():
    resp = jsonify([a.to_dict(mod_data=True) for a in get_assets_awaiting_moderation()])
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/content/upload", methods=["POST"])
@login_required
def content_upload():
    if not g.user_is_admin and not g.user_without_limits:
        max_uploads = CONFIG["MAX_UPLOADS"]
        if len(get_user_assets()) >= max_uploads:
            return error("You have reached your upload limit")

    filetype = request.values.get("filetype")
    if filetype not in ("image", "video"):
        return error("Invalid/missing filetype")
    extension = "jpg" if filetype == "image" else "mp4"

    filename = "user/{}/{}_{}.{}".format(
        g.userid,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        token_hex(8),
        extension,
    )
    condition = {
        "StringEquals": {
            "asset:filename": filename,
            "asset:filetype": filetype,
            "userdata:userid": g.userid,
            "userdata:username": g.username,
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
        userid=g.userid,
        username=g.username,
        upload_key=get_scoped_api_key(
            [{"Action": "asset:upload", "Condition": condition, "Effect": "allow"}],
            uses=1,
        ),
    )


@app.route("/content/review/<int:asset_id>", methods=["POST"])
@login_required
def content_request_review(asset_id):
    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    if asset["userdata"].get("userid") != g.userid:
        return error("Cannot review")

    if "state" in asset["userdata"]:  # not in new state?
        return error("Cannot review")

    moderation_message = "{asset} uploaded by {user}. ".format(
        user=g.username,
        asset=asset["filetype"].capitalize(),
    )

    if g.user_is_admin:
        update_asset_userdata(asset, state=State.CONFIRMED, moderated_by=g.username)
        app.logger.warn(
            "auto-confirming {} because it was uploaded by admin {}".format(
                asset["id"], g.username
            )
        )
        moderation_message += "It was automatically confirmed because user is an admin."
    elif g.user_without_limits:
        update_asset_userdata(asset, state=State.CONFIRMED, moderated_by=g.username)
        app.logger.warn(
            "auto-confirming {} because it was uploaded by no-limits user {}".format(
                asset["id"], g.username
            )
        )
        moderation_message += (
            "It was automatically confirmed because user is on the no-limits list."
        )
    else:
        moderation_url = url_for("content_moderate", asset_id=asset_id, _external=True)
        app.logger.info(
            "moderation url for {} is {}".format(asset["id"], moderation_url)
        )
        update_asset_userdata(asset, state=State.REVIEW)
        moderation_message += f"Check it at {moderation_url}"

    n = Notifier()
    n.message(moderation_message)

    return jsonify(ok=True)


@app.route("/content/moderate/<int:asset_id>")
@admin_required
def content_moderate(asset_id):
    try:
        asset = get_asset(asset_id)
    except Exception:
        app.logger.info(
            f"request to moderate asset {asset_id} failed because asset does not exist"
        )
        abort(404)

    if asset.state == State.DELETED:
        app.logger.info(
            f"request to moderate asset {asset_id} failed because asset was deleted by user"
        )
        abort(404)

    return render_template("moderate.jinja", asset=asset.to_dict(mod_data=True))


@app.route(
    "/content/moderate/<int:asset_id>/<any(confirm,reject):result>",
    methods=["POST"],
)
@admin_required
def content_moderate_result(asset_id, result):
    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        app.logger.info(
            f"request to moderate asset {asset_id} failed because asset does not exist"
        )
        abort(404)

    state = asset["userdata"].get("state", "new")
    if state == State.DELETED:
        app.logger.info(
            f"request to moderate asset {asset_id} failed because asset was deleted by user"
        )
        abort(404)

    if result == "confirm":
        app.logger.info("Asset {} was confirmed".format(asset["id"]))
        update_asset_userdata(asset, state=State.CONFIRMED, moderated_by=g.username)
    else:
        app.logger.info("Asset {} was rejected".format(asset["id"]))
        update_asset_userdata(asset, state=State.REJECTED, moderated_by=g.username)

    return jsonify(ok=True)


@app.route("/content/<int:asset_id>", methods=["POST"])
@login_required
def content_update(asset_id):
    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    starts = request.values.get("starts", type=int)
    ends = request.values.get("ends", type=int)

    if asset["userdata"].get("userid") != g.userid:
        return error("Cannot update")

    try:
        update_asset_userdata(asset, starts=starts, ends=ends)
    except Exception as e:
        app.logger.error(f"content_update({asset_id}) {repr(e)}")
        return error("Cannot update")

    return jsonify(ok=True)


@app.route("/content/<int:asset_id>", methods=["DELETE"])
@login_required
def content_delete(asset_id):
    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    if asset["userdata"].get("userid") != g.userid:
        return error("Cannot delete")

    try:
        update_asset_userdata(asset, state=State.DELETED)
    except Exception as e:
        app.logger.error(f"content_delete({asset_id}) {repr(e)}")
        return error("Cannot delete")

    return jsonify(ok=True)


@app.route("/content/live")
def content_live():
    no_time_filter = request.values.get("all")
    assets = get_all_live_assets(no_time_filter=no_time_filter)
    random.shuffle(assets)
    resp = jsonify([a.to_dict(mod_data=g.user_is_admin) for a in assets])
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/metrics")
def metrics():
    return generate_latest()


@app.route("/slideshow")
def slideshow():
    return render_template("slideshow.jinja", APP_STARTUP_TIME=APP_STARTUP_TIME)


@app.route("/api/slideshow/content")
def api_slideshow_content():
    assets = [a.to_dict() for a in get_all_live_assets()]
    resp = jsonify(
        {
            a["id"]: {
                "url": a["url"],
                "type": a["filetype"],
            }
            for a in assets
        }
    )
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/api/startup")
def app_startup_time():
    return str(APP_STARTUP_TIME)


# @app.route("/content/last")
# def content_last():
#    assets = get_all_live_assets()
#    asset_by_id = dict((asset["id"], asset) for asset in assets)
#
#    last = {}
#
#    for room in CONFIG["ROOMS"]:
#        proofs = [
#            json.loads(data)
#            for data in r.zrange("last:{}".format(room["device_id"]), 0, -1)
#        ]
#
#        last[room["name"]] = room_last = []
#        for proof in reversed(proofs):
#            asset = asset_by_id.get(proof["asset_id"])
#            if asset is None:
#                continue
#            room_last.append(
#                {
#                    "id": proof["id"],
#                    "user": asset["userdata"]["user"],
#                    "filetype": asset["filetype"],
#                    "shown": int(proof["ts"]),
#                    "thumb": asset["thumb"],
#                    "url": url_for("static", filename=cached_asset_name(asset)),
#                }
#            )
#            if len(room_last) > 10:
#                break
#
#    resp = jsonify(
#        last=[[room["name"], last.get(room["name"], [])] for room in CONFIG["ROOMS"]]
#    )
#    resp.headers["Cache-Control"] = "no-cache"
#    return resp
#
#
# @app.route("/proof", methods=["POST"])
# def proof():
#    proofs = [(json.loads(row), row) for row in request.stream.read().split("\n")]
#    device_ids = set()
#    p = r.pipeline()
#    for proof, row in proofs:
#        p.zadd("last:{}".format(proof["device_id"]), row, proof["ts"])
#        device_ids.add(proof["device_id"])
#    for device_id in device_ids:
#        p.zremrangebyscore(f"last:{device_id}", 0, time.time() - 1200)
#    p.execute()
#    return "ok"


@app.route("/robots.txt")
def robots_txt():
    return "User-Agent: *\nDisallow: /\n"


if __name__ == "__main__":
    app.run(port=8080)
