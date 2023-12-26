try:
    # python 3.11
    from tomllib import loads as toml_load
except ImportError:
    from rtoml import load as toml_load

from os import environ

with open(environ["SETTINGS"]) as f:
    CONFIG = toml_load(f.read())
