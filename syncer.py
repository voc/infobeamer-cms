from json import dumps as json_dumps
from logging import getLogger

from flask import url_for

from conf import CONFIG
from frontend import app
from helper import get_all_live_assets
from ib_hosted import ib

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
                    "fade_time": 0.5,
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
                "config": {"fade_time": 0.5},
            }
        )
    if asset["userdata"]["user"].lower() not in CONFIG.get("ADMIN_USERS", set()):
        tiles.append(
            {
                "type": "flat",
                "asset": "flat.png",
                "x1": 0,
                "y1": 1040,
                "x2": 1920,
                "y2": 1080,
                "config": {"color": "#000000", "alpha": 230, "fade_time": 0.5},
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
            "auto_duration": 10,
            "duration": 10,
            "interaction": {"key": ""},
            "layout_id": -1,  # Use first layout
            "overlap": 0,
            "tiles": asset_to_tiles(asset),
        }
    )
    assets_visible.add(asset["id"])

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
        log.info("Config has not changed, skipping update")

log.info("updated everything")
