from datetime import datetime
from json import dumps as json_dumps
from logging import getLogger

from conf import CONFIG
from helper import Asset, State, get_all_live_assets, user_is_admin
from ib_hosted import ib
from voc_mqtt import send_message

FADE_TIME = 0.5
SLIDE_TIME = 10
log = getLogger("Syncer")

log.info("Starting sync")

if datetime.now().minute == 7:
    log.info("Time is :00, broadcasting state")
    asset_states = {}
    for asset in ib.get("asset/list")["assets"]:
        if asset["userdata"].get("user") is not None and asset["userdata"].get(
            "state"
        ) not in (State.CONFIRMED, State.REJECTED, State.DELETED):
            state = asset["userdata"]["state"]
            if state not in asset_states:
                asset_states[state] = 0
            asset_states[state] += 1
            log.info(
                "asset {} is in state {}, uploaded by {}".format(
                    asset["id"], state, asset["userdata"]["user"]
                )
            )

    msg = []
    for state, count in sorted(asset_states.items()):
        msg.append("{} assets in state {}.".format(count, state))

    if msg:
        msg.append("Check the logs for more information")
        send_message(
            " ".join(msg),
            level="WARN",
        )


def asset_to_tiles(asset: Asset):
    log.debug("adding {} to Page".format(asset.id))

    tiles = []
    if asset.filetype == "video":
        tiles.append(
            {
                "type": "rawvideo",
                "asset": asset.id,
                "x1": 0,
                "y1": 0,
                "x2": 1920,
                "y2": 1080,
                "config": {
                    "fade_time": FADE_TIME,
                    "layer": -5,
                    "looped": True,
                },
            }
        )
    else:
        tiles.append(
            {
                "type": "image",
                "asset": asset.id,
                "x1": 0,
                "y1": 0,
                "x2": 1920,
                "y2": 1080,
                "config": {"fade_time": FADE_TIME},
            }
        )
    if not user_is_admin(asset.user):
        tiles.append(
            {
                "type": "flat",
                "asset": "flat.png",
                "x1": 0,
                "y1": 1040,
                "x2": 1920,
                "y2": 1080,
                "config": {"color": "#000000", "alpha": 230, "fade_time": FADE_TIME},
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
                    "fade_time": FADE_TIME,
                    "text": "Project by @{user} - visit {url} to share your own.".format(
                        user=asset.user,
                        url=CONFIG["DOMAIN"],
                    ),
                    "color": "#dddddd",
                },
            }
        )
    if "EXTRA_ASSETS" in CONFIG:
        tiles.extend(CONFIG["EXTRA_ASSETS"])
    return tiles


pages = []
assets_visible = set()
for asset in get_all_live_assets():
    pages.append(
        {
            "auto_duration": SLIDE_TIME,
            "duration": SLIDE_TIME - (FADE_TIME*2), # Because it seems like the fade time is exclusive of the 10 sec, so videos play for 11 secs.
            "interaction": {"key": ""},
            "layout_id": -1,  # Use first layout
            "overlap": 0,
            "tiles": asset_to_tiles(asset),
        }
    )
    assets_visible.add(asset.id)

log.info(
    "There are currently {} pages visible with asset ids: {}".format(
        len(pages), ", ".join([str(i) for i in sorted(assets_visible)])
    )
)

for setup_id in CONFIG["SETUP_IDS"]:
    slog = getLogger(f"Setup {setup_id}")
    slog.info("Getting old config")
    config = ib.get(f"setup/{setup_id}")["config"][""]
    setup_changed = False

    for schedule in config["schedules"]:
        if schedule["name"] == "User Content":
            slog.info('Found schedule "User Content"')
            assets_shown = set()

            for page in schedule["pages"]:
                for tile in page["tiles"]:
                    if tile["type"] in ("image", "rawvideo"):
                        assets_shown.add(tile["asset"])

            slog.info(
                "schedule shows assets: {}".format(
                    ", ".join([str(i) for i in sorted(assets_shown)])
                )
            )
            if assets_visible != assets_shown:
                schedule["pages"] = pages
                setup_changed = True

    if setup_changed:
        slog.warning("Config has changed, updating")
        ib.post(
            f"setup/{setup_id}",
            config=json_dumps({"": config}),
            mode="update",
        )
    else:
        slog.info("Config has not changed, skipping update")

log.info("updated everything")
