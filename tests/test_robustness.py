import json

import pytest
import requests

from quran_video.api.client import ApiError, QuranClient
from quran_video.api.models import VerseTiming
from quran_video.core.timing import DataError, basmala_available, check_timings


def vt(key, a, b):
    return VerseTiming(key, a, b, ())


def test_basmala_rule():
    assert basmala_available(18, 1)
    assert not basmala_available(18, 2)  # must start at verse 1
    assert not basmala_available(1, 1)  # Al-Fatihah: the Basmala is verse 1 itself
    assert not basmala_available(9, 1)  # At-Tawbah has none


def test_unusable_timing_is_rejected_with_a_clear_message():
    with pytest.raises(DataError, match="Pick another reciter"):
        check_timings([vt("1:1", 80, 80)], "Mishari al-Afasy")  # reciter 173, Al-Fatihah
    check_timings([vt("1:1", 0, 6090)], "ok")


class FakeSession:
    def __init__(self, fail_urls=()):
        self.calls, self.fail = [], fail_urls

    def get(self, url, timeout=None):
        self.calls.append(url)
        if any(f in url for f in self.fail):
            raise requests.ConnectionError("down")
        r = requests.Response()
        r.status_code = 200
        r._content = json.dumps({
            "chapters": [{"id": 1, "name_arabic": "x", "name_simple": "Al-Fatihah", "verses_count": 7,
                          "bismillah_pre": False}],
            "reciters": [{"id": 7, "name": "A", "style": {"name": "Murattal"}}, {"id": 158, "name": "J"}],
        }).encode()
        return r


def client(tmp_path, **kw):
    c = QuranClient(tmp_path, base="https://proxy.test")
    c.session = FakeSession(**kw)
    return c


def test_second_run_is_served_from_cache(tmp_path):
    c = client(tmp_path)
    c.chapters()
    assert len(c.session.calls) == 1
    c2 = QuranClient(tmp_path, base="https://proxy.test")
    c2.session = FakeSession()
    assert c2.chapters()[0].verses_count == 7
    assert c2.session.calls == []  # no network


def test_reciter_style_may_be_a_name_an_object_or_missing():
    from quran_video.api.client import _style
    from quran_video.api.models import Reciter
    assert _style({"style": {"name": "Murattal"}}) == _style({"style": "Murattal"}) == "Murattal"
    assert _style({}) == _style({"style": None}) == ""
    assert Reciter(1, "A", "").label == "A" and Reciter(1, "A", "Murattal", "x").label == "A (Murattal, x)"


def test_no_proxy_configured_is_a_clear_error(tmp_path):
    with pytest.raises(ApiError, match="QVC_API_BASE"):
        QuranClient(tmp_path, base="").chapters()  # an emptied QVC_API_BASE must not fall back silently


def test_cache_older_than_a_week_is_never_used(tmp_path):
    import os
    c = client(tmp_path)
    c.reciters()
    for f in (tmp_path / "api").glob("*.json"):
        os.utime(f, (0, 0))  # make the cached copy ancient
    c.session = FakeSession(fail_urls=("reciters",))  # network down
    with pytest.raises(ApiError):  # QF terms: nothing older than a week may be used
        c.reciters()
    c.session = FakeSession()
    c.reciters()
    assert c.session.calls  # the expired copy is fetched again


def test_error_when_nothing_cached_and_network_down(tmp_path):
    with pytest.raises(ApiError):
        client(tmp_path, fail_urls=("chapters",)).chapters()


def test_retry_policy_retries_server_errors_but_not_rate_limits(tmp_path):
    retry = QuranClient(tmp_path).session.get_adapter("https://proxy.test").max_retries
    assert {500, 502, 503, 504} <= set(retry.status_forcelist) and retry.total >= 3 and retry.backoff_factor > 0
    assert 429 not in retry.status_forcelist  # the proxy's limit is per minute: quick retries only add load


def test_reciter_with_wrong_timing_data_is_hidden(tmp_path):
    assert [r.id for r in client(tmp_path).reciters()] == [7]  # 158 gets another reciter's timings from QF


def test_files_older_than_a_week_are_deleted_at_start(tmp_path):
    import os
    import time
    old, fresh = tmp_path / "audio" / "7_2.mp3", tmp_path / "api" / "x.json"
    for f in (old, fresh):
        f.parent.mkdir(exist_ok=True)
        f.write_text("x")
    eight_days_ago = time.time() - 8 * 86400
    os.utime(old, (eight_days_ago, eight_days_ago))
    QuranClient(tmp_path)
    assert not old.exists() and fresh.exists()  # QF terms: not kept on disk longer than a week, used or not


class FakeDownload:
    headers = {"Content-Length": "6"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield b"abc"
        yield b"def"


class DownloadSession:
    def get(self, url, stream=False, timeout=None):
        return FakeDownload()


def test_audio_download_reports_progress_and_can_be_stopped(tmp_path):
    c = QuranClient(tmp_path, base="https://proxy.test")
    c.session = DownloadSession()
    seen = []
    path = c.audio(7, 1, "https://audio.test/1.mp3", lambda done, total: seen.append((done, total)))
    assert seen == [(3, 6), (6, 6)] and path.read_bytes() == b"abcdef"

    class Stop(Exception):
        pass

    def stop(done, total):
        raise Stop  # what a Cancel press does during an export

    with pytest.raises(Stop):
        c.audio(7, 2, "https://audio.test/2.mp3", stop)
    assert not (tmp_path / "audio" / "7_2.mp3").exists() and not list((tmp_path / "audio").glob("*.part"))
