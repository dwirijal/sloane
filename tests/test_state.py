import psycopg
from sloane.store.state import get_state, set_state, add_seen
from shared.config import pg_dsn

DSN = pg_dsn()
S, K = "test-samehadaku", "seen_feed_urls"


def _clear():
    with psycopg.connect(DSN) as c, c.cursor() as cur:
        cur.execute("DELETE FROM ingest_state WHERE source=%s AND key=%s", (S, K))
        c.commit()


def test_set_get_roundtrip():
    _clear()
    set_state(DSN, S, K, ["a", "b"])
    assert get_state(DSN, S, K, default=[]) == ["a", "b"]
    _clear()


def test_get_default_when_missing():
    _clear()
    assert get_state(DSN, S, K, default=["x"]) == ["x"]
    _clear()


def test_add_seen_appends_and_dedups():
    _clear()
    set_state(DSN, S, K, ["a"])
    add_seen(DSN, S, K, ["a", "b", "c"])
    assert sorted(get_state(DSN, S, K, default=[])) == ["a", "b", "c"]
    # adding existing again does not duplicate
    add_seen(DSN, S, K, ["a"])
    assert sorted(get_state(DSN, S, K, default=[])) == ["a", "b", "c"]
    _clear()
