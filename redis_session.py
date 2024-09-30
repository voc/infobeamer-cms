import pickle

from flask import sessions
from redis import Redis

from helper import get_random


class RedisSession(sessions.CallbackDict, sessions.SessionMixin):
    def __init__(self, sid=None, initial=None):
        def on_update(self):
            self.modified = True

        sessions.CallbackDict.__init__(self, initial, on_update)
        self.modified = False
        self.new_sid = not sid
        self.sid = sid or get_random(32)


class RedisSessionStore(sessions.SessionInterface):
    def __init__(self, host):
        self.redis = Redis(host=host)

    def open_session(self, app, request):
        sid = request.cookies.get(app.config["SESSION_COOKIE_NAME"])
        if not sid:
            return RedisSession()
        data = self.redis.get(f"sid:{sid}")
        if data is None:
            return RedisSession()
        return RedisSession(sid, pickle.loads(data))

    def save_session(self, app, session, response):
        if not session.modified:
            return
        state = dict(session)
        if state:
            self.redis.setex(f"sid:{session.sid}", 86400, pickle.dumps(state, 2))
        else:
            self.redis.delete(f"sid:{session.sid}")
        if session.new_sid:
            response.set_cookie(
                app.session_cookie_name,
                session.sid,
                httponly=True,
                secure=True,
                samesite="Lax",
            )
