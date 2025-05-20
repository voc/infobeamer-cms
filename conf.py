try:
    # python 3.11
    from tomllib import loads as toml_load
except ImportError:
    from rtoml import load as toml_load

import logging
from json import load
from os import environ

with open(environ["SETTINGS"]) as f:
    CONFIG = toml_load(f.read())

for i in ("ADMIN_USERS", "NO_LIMIT_USERS"):
    if i not in CONFIG and f"{i}_JSON" in CONFIG:
        with open(CONFIG[f"{i}_JSON"]) as f:
            CONFIG[i] = load(f)

# set a bunch of defaults to make the remaining code more readable
for i in ("ADMIN_USERS", "NO_LIMIT_USERS", "SETUP_IDS"):
    if i not in CONFIG:
        CONFIG[i] = []

if "NOTIFIER" not in CONFIG:
    CONFIG["notifier"] = {}

logging.basicConfig(
    format="[%(levelname)s %(name)s] %(message)s",
    level=logging.INFO,
)
