from regradar.agents.state import Manifestation
from regradar.data.bronze.store import BronzeStore, content_hash


def test_put_pins_by_hash_and_is_idempotent(tmp_path):
    store = BronzeStore(root=tmp_path)
    raw = b"<ACT>Regulation text</ACT>"
    kw = dict(celex="32022R2554", manifestation=Manifestation.FORMEX,
              language="en", source_uri="http://example/celex")

    rec1 = store.put(raw=raw, **kw)
    rec2 = store.put(raw=raw, **kw)  # identical bytes -> no-op

    assert rec1.content_hash == content_hash(raw)
    assert rec1.content_path == rec2.content_path
    assert len(store.list_records()) == 1  # not duplicated
    assert store.get_bytes(rec1) == raw


def test_changed_bytes_create_new_record(tmp_path):
    store = BronzeStore(root=tmp_path)
    kw = dict(celex="32022R2554", manifestation=Manifestation.FORMEX,
              language="en", source_uri="http://example/celex")
    store.put(raw=b"v1", **kw)
    store.put(raw=b"v2 amended", **kw)
    assert len(store.list_records()) == 2


def test_exists_check(tmp_path):
    store = BronzeStore(root=tmp_path)
    raw = b"content"
    h = content_hash(raw)
    assert not store.exists("C", Manifestation.XHTML, "en", h)
    store.put(celex="C", manifestation=Manifestation.XHTML, language="en",
              source_uri="u", raw=raw)
    assert store.exists("C", Manifestation.XHTML, "en", h)
