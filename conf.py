try:
    # python 3.11
    from tomllib import loads as toml_load
except ImportError:
    from rtoml import load as toml_load

import logging
from os import environ

with open(environ["SETTINGS"]) as f:
    CONFIG = toml_load(f.read())

logging.basicConfig(
    format="[%(levelname)s %(name)s] %(message)s",
    level=logging.INFO,
)
