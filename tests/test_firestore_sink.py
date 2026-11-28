"""FirestoreSink against a tiny in-memory stand-in for the Firestore client."""

from auction_tracker.models import Listing
from auction_tracker.storage.firestore import FirestoreSink, chunk_by_size


def deep_merge(old, new):
    out = dict(old)
    for k, v in new.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class FakeDoc:
    def __init__(self, store, col, doc_id):
        self.store, self.col, self.id = store, col, doc_id
        self.reference = self

    @property
    def exists(self):
        return self.id in self.store.setdefault(self.col, {})

    def to_dict(self):
        return self.store[self.col].get(self.id)

    def get(self):
        return self

    def set(self, data, merge=False):
        col = self.store.setdefault(self.col, {})
        col[self.id] = deep_merge(col.get(self.id, {}), data) if merge else dict(data)

    def delete(self):
        self.store.get(self.col, {}).pop(self.id, None)

    def collection(self, name):
        return FakeCollection(self.store, f"{self.col}/{self.id}/{name}")


class FakeQuery:
    def __init__(self, store, col, field, value):
        self.store, self.col, self.field, self.value = store, col, field, value

    def stream(self):
        for k, v in list(self.store.get(self.col, {}).items()):
            if v.get(self.field) == self.value:
                yield FakeDoc(self.store, self.col, k)


class FakeCollection:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def document(self, doc_id):
        return FakeDoc(self.store, self.name, doc_id)

    def stream(self):
        for k in list(self.store.get(self.name, {})):
            yield FakeDoc(self.store, self.name, k)

    def where(self, filter):
        field = getattr(filter, "field_path", None) or filter[0]
        op = getattr(filter, "op_string", None) or filter[1]
        value = getattr(filter, "value", None) if hasattr(filter, "value") else filter[2]
        assert op == "=="
        return FakeQuery(self.store, self.name, field, value)


class FakeBatch:
    def __init__(self):
        self.ops = []

    def set(self, ref, data, merge=False):
        self.ops.append(lambda: ref.set(data, merge=merge))

    def delete(self, ref):
        self.ops.append(ref.delete)

    def commit(self):
        assert len(self.ops) <= 500, "Firestore batches hold at most 500 writes"
        for op in self.ops:
            op()


class FakeClient:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return FakeCollection(self.store, name)

    def batch(self):
        return FakeBatch()


def mk(n, source="zuk"):
    return [
        Listing(source=source, source_id=str(i), url=f"https://x/{i}", title=f"Casa {i}", current_price=100_000.0 + i)
        for i in range(n)
    ]


def test_writes_summary_and_listings():
    fc = FakeClient()
    FirestoreSink(client=fc).write("zuk", mk(3))
    s = fc.store["summaries"]["zuk-1"]
    assert s["source"] == "zuk" and s["parts"] == 1 and len(s["items"]) == 3
    assert set(fc.store["listings"]) == {"zuk:0", "zuk:1", "zuk:2"}


def test_listings_without_a_real_price_are_not_published():
    fc = FakeClient()
    xs = mk(3)
    xs[1].current_price = None          # "recebendo propostas"
    xs[2].current_price = 0.01          # placeholder ("lote sustado")
    FirestoreSink(client=fc).write("zuk", xs)
    assert [i["id"] for i in fc.store["summaries"]["zuk-1"]["items"]] == ["zuk:0"]


def test_first_seen_survives_reruns():
    fc = FakeClient()
    sink = FirestoreSink(client=fc)
    sink.write("zuk", mk(2))
    fc.store["summaries"]["zuk-1"]["items"][0]["first_seen"] = "2026-01-01T00:00:00+00:00"
    sink.write("zuk", mk(3))
    items = {i["id"]: i for i in fc.store["summaries"]["zuk-1"]["items"]}
    assert items["zuk:0"]["first_seen"] == "2026-01-01T00:00:00+00:00"
    assert items["zuk:2"]["first_seen"] != "2026-01-01T00:00:00+00:00"


def test_large_site_is_split_and_stale_parts_removed(monkeypatch):
    import auction_tracker.storage.firestore as mod

    monkeypatch.setattr(mod, "MAX_DOC_BYTES", 2_000)
    fc = FakeClient()
    sink = FirestoreSink(client=fc)
    sink.write("superbid", mk(60, "superbid"))
    parts = [k for k in fc.store["summaries"] if k.startswith("superbid-")]
    assert len(parts) > 1
    assert sum(len(fc.store["summaries"][p]["items"]) for p in parts) == 60
    sink.write("superbid", mk(5, "superbid"))  # site shrank
    assert [k for k in fc.store["summaries"] if k.startswith("superbid-")] == ["superbid-1"]


def test_chunk_by_size():
    items = [{"x": "a" * 100}] * 10
    parts = chunk_by_size(items, 350)
    assert sum(len(p) for p in parts) == 10 and all(len(p) <= 3 for p in parts)


def test_meta_marks_the_data_version():
    fc = FakeClient()
    FirestoreSink(client=fc).write_meta("20260101T000000Z")
    m = fc.store["meta"]["latest"]
    assert m["run_id"] == "20260101T000000Z" and m["updated_at"]


def test_daily_snapshots_accumulate():
    fc = FakeClient()
    sink = FirestoreSink(client=fc)
    sink.write("zuk", mk(1))
    d = fc.store["listings"]["zuk:0"]
    (day,) = d["snap"]
    # a second day: add its key next to the first one
    d["snap"] = {"20200101": {"p": 1, "b": 0, "s": "x"}, **d["snap"]}
    sink.write("zuk", mk(1))
    assert set(fc.store["listings"]["zuk:0"]["snap"]) == {"20200101", day}
    assert fc.store["listings"]["zuk:0"]["snap"][day]["p"] == 100_000.0


def test_lots_that_leave_the_site_get_an_outcome():
    fc = FakeClient()
    sink = FirestoreSink(client=fc)
    xs = mk(3)
    xs[1].status = "Arrematado"
    sink.write("zuk", xs, complete=True)
    sink.write("zuk", [xs[0]], complete=True)  # lots 1 and 2 are gone
    L = fc.store["listings"]
    assert L["zuk:1"]["outcome"] == "sold" and L["zuk:1"]["final_price"] == 100_001.0
    assert L["zuk:2"]["outcome"] == "gone" and L["zuk:2"]["ended_at"]
    assert L["zuk:0"]["ended_at"] is None


def test_an_incomplete_run_never_ends_lots():
    fc = FakeClient()
    sink = FirestoreSink(client=fc)
    sink.write("zuk", mk(3), complete=True)
    sink.write("zuk", mk(1), complete=False)  # e.g. a page cap or a WARN run
    assert all(fc.store["listings"][f"zuk:{i}"]["ended_at"] is None for i in range(3))


def test_rerunning_the_same_scrape_never_duplicates():
    """Each lot has a fixed id (site + the site's lot number): a re-run
    updates the same documents and rebuilds the site's summary."""
    fc = FakeClient()
    sink = FirestoreSink(client=fc)
    for _ in range(3):
        sink.write("zuk", mk(5), complete=True)
    assert len(fc.store["listings"]) == 5
    items = [i for d in fc.store["summaries"].values() for i in d["items"]]
    assert sorted(i["id"] for i in items) == [f"zuk:{i}" for i in range(5)]


def test_min_price_matches_the_web_app():
    import re
    from pathlib import Path

    from auction_tracker.summary import MIN_PRICE
    html = (Path(__file__).parent.parent / "web" / "index.html").read_text(encoding="utf-8")
    assert int(re.search(r"const MIN_PRICE = (\d+);", html).group(1)) == MIN_PRICE


def test_lots_under_the_minimum_are_not_published():
    fc = FakeClient()
    xs = mk(2)
    xs[1].current_price = 39_999.0
    FirestoreSink(client=fc).write("zuk", xs)
    assert [i["id"] for i in fc.store["summaries"]["zuk-1"]["items"]] == ["zuk:0"]
