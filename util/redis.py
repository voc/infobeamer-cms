from redis import Redis

from conf import CONFIG

REDIS = Redis(host=CONFIG["REDIS_HOST"])
