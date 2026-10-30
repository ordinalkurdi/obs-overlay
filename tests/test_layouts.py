"""Run: python -m unittest discover -s tests -v   (pure logic, no Qt needed)"""
import copy, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import layouts as L
from core.config import DEFAULTS, Settings
from pathlib import Path
import tempfile


def widget(i, x=10, y=10, **kw):
    d = dict(id=i, kind="stats", name=f"W{i}", x=x, y=y, w=200, h=100, opacity=0.9, pinned=False,
             click_through=False, visible=True, metrics=["fps"])
    d.update(kw); return d


class Cfg(dict):
    def __init__(self): super().__init__(layout_presets=[], active_preset=""); self.saves = 0
    def save(self): self.saves += 1


class SnapshotTests(unittest.TestCase):
    def test_snapshot_is_deep_copy(self):
        ws = [widget("a")]; snap = L.snapshot(ws)
        ws[0]["metrics"].append("cpu"); ws[0]["x"] = 999
        self.assertEqual(snap["widgets"][0]["metrics"], ["fps"]); self.assertEqual(snap["widgets"][0]["x"], 10)

    def test_snapshot_drops_unknown_keys(self):
        w = widget("a"); w["secret"] = 1
        self.assertNotIn("secret", L.snapshot([w])["widgets"][0])

    def test_sanitize_rejects_garbage(self):
        self.assertIsNone(L.sanitize_layout(None)); self.assertIsNone(L.sanitize_layout({"widgets": "x"}))
        out = L.sanitize_layout({"widgets": [widget("a"), {"id": 5}, "junk", widget("a")]})
        self.assertEqual([w["id"] for w in out["widgets"]], ["a"])

    def test_sanitize_drops_web_dock_without_url(self):
        out = L.sanitize_layout({"widgets": [widget("a", kind="web"), widget("b", kind="web", url="https://x.test"),
                                             widget("c", kind="web", url="javascript:alert(1)")]})
        self.assertEqual([w["id"] for w in out["widgets"]], ["b"])

    def test_sanitize_clamps_values(self):
        out = L.sanitize_layout({"widgets": [widget("a", w=1, opacity=7)]})["widgets"][0]
        self.assertGreaterEqual(out["w"], 40); self.assertEqual(out["opacity"], 1.0)

    def test_layouts_equal_ignores_order(self):
        a = L.snapshot([widget("a"), widget("b")]); b = L.snapshot([widget("b"), widget("a")])
        self.assertTrue(L.layouts_equal(a, b))
        b["widgets"][0]["x"] = 11
        self.assertFalse(L.layouts_equal(a, b))


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Cfg(); self.st = L.PresetStore(self.cfg)
        self.lay = L.snapshot([widget("a", 1, 2), widget("b", 30, 40)])

    def test_create_and_activate(self):
        p = self.st.create("  My   Layout ", self.lay)
        self.assertEqual(p["name"], "My Layout"); self.assertEqual(self.cfg["active_preset"], p["id"])
        self.assertTrue(L.layouts_equal(p["layout"], self.lay)); self.assertGreater(self.cfg.saves, 0)

    def test_empty_and_duplicate_names(self):
        for bad in ("", "   "):
            with self.assertRaises(L.PresetError): self.st.create(bad, self.lay)
        self.st.create("Alpha", self.lay)
        with self.assertRaises(L.PresetError): self.st.create("alpha ", self.lay)
        with self.assertRaises(L.PresetError): self.st.create("x" * 41, self.lay)

    def test_create_stores_copy(self):
        lay = copy.deepcopy(self.lay); p = self.st.create("A", lay); lay["widgets"][0]["x"] = 500
        self.assertEqual(p["layout"]["widgets"][0]["x"], 1)

    def test_rename_keeps_layout_and_allows_own_name(self):
        p = self.st.create("A", self.lay); before = copy.deepcopy(p["layout"])
        self.st.rename(p["id"], "A")                       # same name, own preset: fine (e.g. only case change)
        self.st.rename(p["id"], "Renamed")
        self.assertEqual(self.st.get(p["id"])["name"], "Renamed"); self.assertEqual(p["layout"], before)

    def test_rename_conflict(self):
        self.st.create("A", self.lay); b = self.st.create("B", self.lay)
        with self.assertRaises(L.PresetError): self.st.rename(b["id"], "a")

    def test_overwrite_only_touches_target(self):
        a = self.st.create("A", self.lay); b = self.st.create("B", self.lay)
        new = L.snapshot([widget("z", 5, 5)])
        self.st.overwrite(a["id"], new)
        self.assertEqual([w["id"] for w in self.st.get(a["id"])["layout"]["widgets"]], ["z"])
        self.assertEqual(len(self.st.get(b["id"])["layout"]["widgets"]), 2)
        self.assertEqual(self.st.get(a["id"])["name"], "A")

    def test_delete_clears_active_only_when_active(self):
        a = self.st.create("A", self.lay); b = self.st.create("B", self.lay)     # B is active
        self.st.delete(a["id"]); self.assertEqual(self.cfg["active_preset"], b["id"])
        self.st.delete(b["id"]); self.assertEqual(self.cfg["active_preset"], ""); self.assertEqual(self.st.presets, [])

    def test_modified_detection(self):
        p = self.st.create("A", self.lay)
        self.assertFalse(self.st.is_modified(self.lay))
        moved = copy.deepcopy(self.lay); moved["widgets"][0]["x"] += 5
        self.assertTrue(self.st.is_modified(moved))
        self.st.clear_active(); self.assertFalse(self.st.is_modified(moved))

    def test_set_active_unknown(self):
        with self.assertRaises(L.PresetError): self.st.set_active("nope")

    def test_sanitize_on_load_repairs_bad_data(self):
        good = {"id": "1", "name": "Same", "layout": self.lay}
        cfg = Cfg(); cfg["layout_presets"] = [good, dict(good, id="2"), {"id": "3", "name": "", "layout": self.lay},
                                              {"id": "4", "name": "Bad", "layout": "nope"}, "junk", dict(good, id="1")]
        cfg["active_preset"] = "ghost"
        st = L.PresetStore(cfg)
        self.assertEqual([p["name"] for p in st.presets], ["Same", "Same (2)"]); self.assertEqual(cfg["active_preset"], "")


class PersistenceTests(unittest.TestCase):
    def test_presets_survive_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            s1 = Settings(path); st = L.PresetStore(s1)
            p = st.create("Streaming", L.snapshot([widget("a", 7, 8)]))
            s2 = Settings(path); st2 = L.PresetStore(s2)                       # "restart"
            self.assertEqual([x["name"] for x in st2.presets], ["Streaming"])
            self.assertEqual(s2["active_preset"], p["id"])
            self.assertEqual(st2.active["layout"]["widgets"][0]["x"], 7)

    def test_defaults_present(self):
        self.assertEqual(DEFAULTS["layout_presets"], []); self.assertEqual(DEFAULTS["active_preset"], "")
        self.assertIn("layout_edit", DEFAULTS["hotkeys"])


class GeometryTests(unittest.TestCase):
    B = (0, 0, 1920, 1080)

    def test_snaps_to_screen_edge(self):
        dx, dy, g = L.snap_rect((6, 300, 200, 100), [], self.B)
        self.assertEqual((dx, g[0]), (-6, ("v", 0)))

    def test_no_snap_when_far(self):
        dx, dy, g = L.snap_rect((100, 300, 200, 100), [], self.B)
        self.assertEqual((dx, dy, g), (0, 0, []))

    def test_snaps_beside_other_widget_with_gap(self):
        dx, dy, g = L.snap_rect((413, 502, 200, 100), [(100, 500, 300, 100)], self.B, gap=8)
        self.assertEqual((413 + dx, 502 + dy), (408, 500))

    def test_snaps_to_centre(self):
        dx, dy, g = L.snap_rect((864, 10, 200, 100), [], self.B)
        self.assertEqual(864 + dx, 860)

    def test_clamp_keeps_widget_reachable(self):
        x, y = L.clamp_to((5000, -300, 200, 100), self.B)
        self.assertEqual((x, y), (1860, 0))

    def test_default_positions_stack_and_wrap(self):
        pos = L.default_positions([(200, 300)] * 4, (0, 0, 1000, 700), gap=10)
        self.assertEqual(pos[0], (790, 10)); self.assertEqual(pos[1], (790, 320))
        self.assertEqual(pos[2][1], 10); self.assertLess(pos[2][0], pos[0][0])        # wrapped to a new column on the left
        self.assertEqual(len(pos), 4)

    def test_default_positions_oversized_widget_still_placed(self):
        pos = L.default_positions([(300, 2000)], (0, 0, 1000, 700)); self.assertEqual(len(pos), 1)


if __name__ == "__main__":
    unittest.main()
