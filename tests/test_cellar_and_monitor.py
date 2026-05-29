from regradar.agents.monitor.monitor import SeenStore, SourceMonitor
from regradar.data.sources.cellar import (
    classify_in_scope,
    extract_celex,
    parse_atom,
)

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>DORA: ICT risk management framework updated</title>
    <link href="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R2554"/>
    <updated>2026-01-15T09:00:00Z</updated>
    <summary>Digital operational resilience for the financial sector.</summary>
  </entry>
  <entry>
    <title>Commission Regulation on agricultural subsidies for olive groves</title>
    <link href="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1234"/>
    <updated>2026-01-16T09:00:00Z</updated>
    <summary>Rules on olive oil production aid.</summary>
  </entry>
</feed>"""


def test_extract_celex():
    assert extract_celex("...uri=CELEX:32022R2554") == "32022R2554"
    assert extract_celex("no celex here") is None


def test_classify_in_scope():
    ok, reason = classify_in_scope("DORA digital operational resilience", "")
    assert ok and "matched in-scope keyword" in reason
    assert not classify_in_scope("olive oil subsidies", "")[0]


def test_parse_atom_extracts_events():
    events = parse_atom(ATOM)
    assert len(events) == 2
    dora = next(e for e in events if e.celex == "32022R2554")
    assert dora.in_scope
    olive = next(e for e in events if e.celex == "32024R1234")
    assert not olive.in_scope


def test_monitor_filters_and_dedups(tmp_path):
    seen = SeenStore(path=tmp_path / "seen.json")

    class FakeClient:
        def fetch_feed(self, feed_url=None):
            return parse_atom(ATOM)

    mon = SourceMonitor(client=FakeClient(), seen=seen)
    first = mon.poll()
    assert [e.celex for e in first] == ["32022R2554"]  # olive dropped (out of scope)

    second = mon.poll()  # DORA already seen -> deduped
    assert second == []
