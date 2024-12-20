from json import loads as json_loads
from logging import getLogger
from threading import Lock

from requests import Session

from conf import CONFIG

from .redis import REDIS


class IBHosted:
    def __init__(self):
        self._session = Session()
        self._session.auth = "", CONFIG["HOSTED_API_KEY"]
        self.log = getLogger("IBHosted")

    def get(self, ep, **params):
        self.log.debug(f'get("{ep}", {params})')
        r = self._session.get(
            f"https://info-beamer.com/api/v1/{ep}", params=params, timeout=5
        )
        self.log.debug(r.text)
        r.raise_for_status()
        return r

    def post(self, ep, **data):
        self.log.debug(f'post("{ep}")')
        r = self._session.post(
            f"https://info-beamer.com/api/v1/{ep}", data=data, timeout=5
        )
        self.log.debug(r.text)
        r.raise_for_status()
        return r

    def delete(self, ep, **data):
        self.log.debug(f'delete("{ep}")')
        r = self._session.delete(
            f"https://info-beamer.com/api/v1/{ep}", data=data, timeout=5
        )
        self.log.debug(r.text)
        r.raise_for_status()
        return r


class IBHostedCached:
    def __init__(self):
        self.ib = IBHosted()
        self.lock_access_lock = Lock()
        self.locks = {}

    def get(self, ep, cached=False, **params):
        with self.lock_access_lock:
            if not self.locks.get(ep):
                self.locks[ep] = Lock()

        cached_result = REDIS.get(f"ibh:{ep}")
        if cached_result is not None and cached:
            return json_loads(cached_result)

        # make sure we only ever run one get() per endpoint at the same
        # time to avoid doing too many requests.
        with self.locks[ep]:
            result = self.ib.get(ep, **params)
            # store result into redis database, set it to expire after 60 seconds
            REDIS.set(f"ibh:{ep}", result.text, ex=60)
            return result.json()

    def post(self, ep, **params):
        return self.ib.post(ep, **params).json()

    def delete(self, ep, **params):
        return self.ib.delete(ep, **params).json()


ib = IBHostedCached()
