from collections import defaultdict
import random
import socket
from datetime import datetime
from secrets import token_hex
from typing import Iterable

import iso8601
from prometheus_client.metrics_core import Metric
from prometheus_client.core import GaugeMetricFamily, REGISTRY
from prometheus_client.registry import Collector
from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_github import GitHub
from prometheus_client import generate_latest
from werkzeug.middleware.proxy_fix import ProxyFix

from conf import CONFIG
from helper import (
    State,
    admin_required,
    cached_asset_name,
    error,
    get_all_live_assets,
    get_asset,
    get_assets,
    get_assets_awaiting_moderation,
    get_random,
    get_user_assets,
    login_disabled_for_user,
    user_is_admin,
)
from ib_hosted import get_scoped_api_key, ib, update_asset_userdata
from redis_session import RedisSessionStore

app = Flask(
    __name__,
    static_folder=CONFIG.get('STATIC_PATH', 'static'),
)
app.secret_key = CONFIG.get('URL_KEY')
app.wsgi_app = ProxyFix(app.wsgi_app)

for copy_key in (
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "MAX_UPLOADS",
    "ROOMS",
    "TIME_MAX",
    "TIME_MIN",
):
    app.config[copy_key] = CONFIG[copy_key]

socket.setdefaulttimeout(3)  # for mqtt


class SubmissionsCollector(Collector):
    def collect(self) -> Iterable[Metric]:
        counts = defaultdict(int)
        for a in get_assets():
            counts[a.state] += 1
        g = GaugeMetricFamily("submissions", "Counts of content submissions", labels=["state"])
        for state in State:
            # Add any states that we know about but have 0 assets in them
            if state.value not in counts.keys():
                counts[state.value] = 0
        for s, c in counts.items():
            g.add_metric([s], c)
        yield g

class InfobeamerCollector(Collector):
    """Prometheus collector for general infobeamer metrics available from the hosted API."""
    last_got = 0
    devices = []
    def collect(self) -> Iterable[Metric]:
        if (self.last_got + 10) < datetime.now().timestamp():
            self.devices = ib.get("device/list")["devices"]
            self.last_got = datetime.now().timestamp()
        yield GaugeMetricFamily("devices", "Infobeamer devices", len(self.devices))
        yield GaugeMetricFamily("devices_online", "Infobeamer devices online", len([d for d in self.devices if d["is_online"]]))
        m = GaugeMetricFamily("device_model", "Infobeamer device models", labels=["model"])
        counts = defaultdict(int)
        for d in self.devices:
            if d.get("hw"):
                counts[d["hw"]["model"]] += 1
            else:
                counts["unknown"] += 1
        for model, count in counts.items():
            m.add_metric([model], count)
        yield m


REGISTRY.register(SubmissionsCollector())
REGISTRY.register(InfobeamerCollector())

github = GitHub(app)

if CONFIG.get("REDIS_HOST"):
    app.session_interface = RedisSessionStore(host=CONFIG.get("REDIS_HOST"))


@app.before_request
def before_request():
    user = session.get("gh_login")
    g.user_is_admin = user_is_admin(user)

    if login_disabled_for_user(user):
        g.user = None
        g.avatar = None
        return

    g.user = user
    g.avatar = session.get("gh_avatar")


@app.route("/github-callback")
@github.authorized_handler
def authorized(access_token):
    if access_token is None:
        return redirect(url_for("index"))

    state = request.args.get("state")
    if state is None or state != session.get("state"):
        return redirect(url_for("index"))
    session.pop("state")

    github_user = github.get("user", access_token=access_token)
    if github_user["type"] != "User":
        return redirect(url_for("faq", _anchor="signup"))

    if login_disabled_for_user(github_user["login"]):
        return render_template("time_error.jinja")

    age = datetime.utcnow() - iso8601.parse_date(github_user["created_at"]).replace(
        tzinfo=None
    )

    app.logger.info(f"user is {age.days} days old")
    app.logger.info("user has {} followers".format(github_user["followers"]))
    if age.days < 31 and github_user["followers"] < 10:
        return redirect(url_for("faq", _anchor="signup"))

    session["gh_login"] = github_user["login"]
    if "redirect_after_login" in session:
        return redirect(session["redirect_after_login"])
    return redirect(url_for("dashboard"))


@app.route("/login")
def login():
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


if "INTERRUPT_KEY" in CONFIG:

    @app.route("/interrupt/{}".format(CONFIG["INTERRUPT_KEY"]))
    def saal():
        interrupt_key = get_scoped_api_key(
            [
                {
                    "Action": "device:node-message",
                    "Condition": {
                        "StringEquals": {"message:path": "root/remote/trigger"}
                    },
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
def dashboard():
    if not g.user:
        return redirect(url_for("index"))
    return render_template("dashboard.jinja")


@app.route("/content/list")
def content_list():
    if not g.user:
        session["redirect_after_login"] = request.url
        return redirect(url_for("login"))
    assets = [a._asdict() for a in get_user_assets()]
    random.shuffle(assets)
    return jsonify(
        assets=assets,
    )

@app.route("/content/awaiting_moderation")
@admin_required
def content_awaiting_moderation():
    return jsonify([a.to_dict(mod_data=True) for a in get_assets_awaiting_moderation()])


@app.route("/content/upload", methods=["POST"])
def content_upload():
    if not g.user:
        session["redirect_after_login"] = request.url
        return redirect(url_for("login"))

    if not g.user_is_admin:
        max_uploads = CONFIG["MAX_UPLOADS"]
        if len(get_user_assets()) >= max_uploads:
            return error("You have reached your upload limit")

    filetype = request.values.get("filetype")
    if filetype not in ("image", "video"):
        return error("Invalid/missing filetype")
    extension = "jpg" if filetype == "image" else "mp4"

    filename = "user/{}/{}_{}.{}".format(
        g.user, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), token_hex(8), extension
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
        session["redirect_after_login"] = request.url
        return redirect(url_for("login"))

    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    if asset["userdata"].get("user") != g.user:
        return error("Cannot review")

    if "state" in asset["userdata"]:  # not in new state?
        return error("Cannot review")

    if g.user_is_admin:
        update_asset_userdata(asset, state=State.CONFIRMED)
        app.logger.warn(
            "auto-confirming {} because it was uploaded by admin {}".format(
                asset["id"], g.user
            )
        )
        return jsonify(ok=True)

    moderation_url = url_for(
        "content_moderate", asset_id=asset_id, _external=True
    )

    app.logger.info("moderation url for {} is {}".format(asset["id"], moderation_url))

    update_asset_userdata(asset, state="review")
    return jsonify(ok=True)


@app.route("/content/moderate/<int:asset_id>")
@admin_required
def content_moderate(asset_id):
    if not g.user:
        session["redirect_after_login"] = request.url
        return redirect(url_for("login"))
    elif not g.user_is_admin:
        app.logger.warning(f"request to moderate {asset_id} by non-admin user {g.user}")
        abort(401)

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

    return render_template(
        "moderate.jinja",
        asset=asset.to_dict(mod_data=True)
    )


@app.route(
    "/content/moderate/<int:asset_id>/<any(confirm,reject):result>",
    methods=["POST"],
)
@admin_required
def content_moderate_result(asset_id, result):
    if not g.user:
        session["redirect_after_login"] = request.url
        return redirect(url_for("login"))
    elif not g.user_is_admin:
        app.logger.warning(f"request to moderate {asset_id} by non-admin user {g.user}")
        abort(401)

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
        update_asset_userdata(asset, state=State.CONFIRMED, moderated_by=g.user)
    else:
        app.logger.info("Asset {} was rejected".format(asset["id"]))
        update_asset_userdata(asset, state=State.REJECTED, moderated_by=g.user)

    return jsonify(ok=True)


@app.route("/content/<int:asset_id>", methods=["POST"])
def content_update(asset_id):
    if not g.user:
        session["redirect_after_login"] = request.url
        return redirect(url_for("login"))

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
        session["redirect_after_login"] = request.url
        return redirect(url_for("login"))

    try:
        asset = ib.get(f"asset/{asset_id}")
    except Exception:
        abort(404)

    if asset["userdata"].get("user") != g.user:
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
    resp.headers["Cache-Control"] = "public, max-age=30"
    return resp


@app.route("/metrics")
def metrics():
    return generate_latest()


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
#    resp.headers["Cache-Control"] = "public, max-age=5"
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
