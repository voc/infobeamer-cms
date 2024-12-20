from json import dumps as json_dumps

from util.ib_hosted import IBHostedCached

ib = IBHostedCached()


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
