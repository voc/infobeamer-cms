from json import dumps as json_dumps
from logging import getLogger

from requests import Session

from conf import CONFIG


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


def get_scoped_api_key(statements, expire=60, uses=16):
    return ib.post(
        "adhoc/create",
        expire=expire,
        uses=uses,
        policy=json_dumps(
            {
                "Version": 1,
                "Statements": statements,
            }
        ),
    )["api_key"]


def update_asset_userdata(asset, **kw):
    userdata = asset["userdata"]
    userdata.update(kw)
    ib.post("asset/{}".format(asset["id"]), userdata=json_dumps(userdata))
