"""Cache (Part 11.6): a hit must avoid the provider chain entirely, so re-running
the same regulation never re-spends quota."""
import regradar.models.cache as cache_mod
from regradar.models.cache import ResponseCache
from regradar.models.router import Router


def test_cache_round_trip(tmp_path):
    c = ResponseCache(root=tmp_path, enabled=True)
    assert c.get("prompt", 0.0) is None
    c.put("prompt", 0.0, {"text": "hello", "model": "m", "tokens": 5})
    assert c.get("prompt", 0.0)["text"] == "hello"
    assert c.get("prompt", 0.5) is None  # temperature is part of the key


def test_disabled_cache_is_noop(tmp_path):
    c = ResponseCache(root=tmp_path, enabled=False)
    c.put("p", 0.0, {"text": "x"})
    assert c.get("p", 0.0) is None


def test_router_hits_cache_without_providers(tmp_path, monkeypatch):
    # Pre-seed the cache; an empty provider chain would otherwise hit the mock floor.
    seeded = ResponseCache(root=tmp_path, enabled=True)
    seeded.put("the prompt", 0.0, {"text": '{"ok": true}', "model": "groq/x", "tokens": 7})
    monkeypatch.setattr(cache_mod, "cache", seeded)

    r = Router(chain=())
    res = r.complete("the prompt", temperature=0.0)
    assert res.provider == "cache" and not res.is_mock
    assert res.text == '{"ok": true}'
