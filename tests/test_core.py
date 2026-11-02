import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()

from ytblocks import adguard, yt
from ytblocks.filters import Filters
from ytblocks.config import JsonStore, SETTINGS_DEFAULT, Library

GV = "https://rr3---sn-abc.googlevideo.com/videoplayback?id=1&itag=137"


def vr(vid, title, **kw):
    d = {"videoId": vid, "title": {"runs": [{"text": title}]},
         "longBylineText": {"runs": [{"text": "Chan", "navigationEndpoint": {"browseEndpoint": {"browseId": "UC1"}}}]},
         "viewCountText": {"simpleText": "1.2M views"}, "publishedTimeText": {"simpleText": "3 years ago"},
         "lengthText": {"simpleText": "1:02:03"}}
    d.update(kw)
    return d


class AdGuard(unittest.TestCase):
    def test_urls(self):
        self.assertTrue(adguard.media_url_ok(GV))
        self.assertFalse(adguard.media_url_ok("https://googleads.g.doubleclick.net/pagead/x"))
        self.assertFalse(adguard.media_url_ok("http://rr3---sn-abc.googlevideo.com/videoplayback"))
        self.assertFalse(adguard.media_url_ok("https://evil.example/googlevideo.com"))
        self.assertFalse(adguard.media_url_ok(GV + "&adformat=15_2"))
        with self.assertRaises(adguard.AdBlocked):
            adguard.assert_clean("https://www.youtube.com/api/stats/ads")

    def test_search_payload_drops_ads(self):
        data = {"contents": [
            {"videoRenderer": vr("AAAAAAAAAAA", "organic")},
            {"adSlotRenderer": {"x": {"videoRenderer": vr("BBBBBBBBBBB", "ad slot")}}},
            {"videoRenderer": vr("CCCCCCCCCCC", "badged",
                                 badges=[{"metadataBadgeRenderer": {"label": "Ad"}}])},
            {"promotedSponsorRenderer": {"videoId": "DDDDDDDDDDD"}},
            {"continuationItemRenderer": {"continuationEndpoint": {"continuationCommand": {"token": "TOK"}}}},
        ]}
        items, tok = yt.parse_payload(data)
        self.assertEqual([i.id for i in items], ["AAAAAAAAAAA"])
        self.assertEqual(tok, "TOK")


class Parse(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(yt.parse_count("1.2M views"), 1200000)
        self.assertEqual(yt.parse_count("1,234 views"), 1234)
        self.assertEqual(yt.parse_count("No views"), 0)
        self.assertEqual(yt.parse_duration("1:02:03"), 3723)
        self.assertIsNone(yt.parse_duration("LIVE"))
        self.assertEqual(yt.parse_rel_date("Streamed 2 days ago"), 172800)

    def test_video_fields_and_sp(self):
        it = yt.parse_items({"a": {"videoRenderer": vr("AAAAAAAAAAA", "T")}})[0]
        self.assertEqual((it.kind, it.channel, it.channel_id, it.views, it.duration),
                         ("video", "Chan", "UC1", 1200000, 3723))
        self.assertEqual(yt.build_sp("date"), "CAI=")
        self.assertEqual(yt.build_sp("relevance", "video"), "EgIQAQ==")

    def test_shorts_by_url(self):
        r = vr("SSSSSSSSSSS", "short", navigationEndpoint={"commandMetadata": {"webCommandMetadata": {"url": "/shorts/SSSSSSSSSSS"}}})
        self.assertEqual(yt.parse_items([{"videoRenderer": r}])[0].kind, "short")


class Mixes(unittest.TestCase):
    def test_mix_uses_watch_url(self):
        r = {"playlistId": "RDEM-YwEhrnX0PALr_YCPaGPrQ", "title": {"simpleText": "Mix"},
             "navigationEndpoint": {"watchEndpoint": {"videoId": "SEEDSEEDSEE"}}}
        it = yt.parse_items([{"playlistRenderer": r}])[0]
        self.assertEqual(it.seed, "SEEDSEEDSEE")
        self.assertEqual(yt.playlist_url(it), "https://www.youtube.com/watch?v=SEEDSEEDSEE&list=RDEM-YwEhrnX0PALr_YCPaGPrQ")
        it.seed = ""
        with self.assertRaises(RuntimeError):
            yt.playlist_url(it)
        self.assertTrue(yt.playlist_url(yt.Item("playlist", "PL123", "x")).endswith("list=PL123"))


class Streams(unittest.TestCase):
    def info(self):
        return {"formats": [
            {"url": GV + "&a=1", "protocol": "https", "vcodec": "avc1", "acodec": "none", "height": 1080, "tbr": 3000},
            {"url": GV + "&a=2", "protocol": "https", "vcodec": "avc1", "acodec": "none", "height": 720, "tbr": 1500},
            {"url": GV + "&a=3", "protocol": "https", "vcodec": "none", "acodec": "opus", "abr": 130},
            {"url": "https://manifest.googlevideo.com/x.m3u8", "protocol": "m3u8_native", "vcodec": "avc1", "acodec": "aac", "height": 2160},
            {"url": "https://cdn.example.com/v.mp4", "protocol": "https", "vcodec": "avc1", "acodec": "aac", "height": 4320},
        ]}

    def test_pick(self):
        s = yt.pick_streams(self.info())
        self.assertEqual((s.height, bool(s.audio_url)), (1080, True))
        self.assertEqual(yt.pick_streams(self.info(), 720).height, 720)
        self.assertEqual(yt.pick_streams(self.info(), 144).height, 720)   # nothing <=144: lowest available
        self.assertEqual(yt.heights(self.info()), [1080, 720])

    def test_live_refused(self):
        i = self.info(); i["is_live"] = True
        with self.assertRaises(adguard.AdBlocked):
            yt.pick_streams(i)


class FiltersAndConfig(unittest.TestCase):
    def test_filters(self):
        f = Filters()
        mk = lambda **k: yt.Item(**{"kind": "video", "id": "x", "title": "t", **k})
        self.assertFalse(f.accept(mk(kind="short"), set()))        # shorts off by default
        self.assertTrue(f.accept(mk(), set()))
        f.min_len = 10
        self.assertFalse(f.accept(mk(duration=300), set()))
        self.assertFalse(f.accept(mk(duration=None), set()))
        f.min_len, f.seen = 0, "unseen"
        self.assertFalse(f.accept(mk(), {"x"}))
        self.assertEqual(Filters(types={"video": False, "channel": True, "playlist": False, "short": False}).server_type(), "channel")

    def test_bad_types_ignored(self):
        from ytblocks.config import _merge
        m = _merge(SETTINGS_DEFAULT, {"window": 5, "sidebar_width": "x", "ui_font": 3, "player_pct": 55.0, "colors": []})
        self.assertEqual(m["window"], {"w": 1280, "h": 720})
        self.assertEqual((m["sidebar_width"], m["ui_font"], m["player_pct"]), (200, "", 55.0))

    def test_persistence(self):
        s = JsonStore("settings.json", SETTINGS_DEFAULT)
        s.data["sidebar_width"] = 321; s.data["colors"]["red"] = "#ff0000"; s.save()
        s2 = JsonStore("settings.json", SETTINGS_DEFAULT)
        self.assertEqual((s2.data["sidebar_width"], s2.data["colors"]["red"], s2.data["colors"]["blue"]), (321, "#ff0000", ""))
        lib = Library(); lib.add_playlist("p"); lib.add_to_playlist("p", {"id": "1"}); lib.add_to_playlist("p", {"id": "1"})
        self.assertEqual(len(Library().playlist("p")["items"]), 1)


if __name__ == "__main__":
    unittest.main()
