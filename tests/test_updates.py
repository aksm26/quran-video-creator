"""The update check: version order, and what GitHub's answer turns into."""

from quran_video.api.updates import newer_release, parse


class Session:
    def __init__(self, tag):
        self.tag = tag

    def get(self, url, **kw):
        tag = self.tag

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"tag_name": tag, "html_url": f"https://github.com/x/releases/tag/{tag}"}
        return R()


def test_versions_compare_as_numbers():
    assert parse("v1.10.0") > parse("1.9.2") and parse("v1.0.0-beta") == (1, 0, 0)


def test_only_a_newer_release_is_reported():
    assert newer_release(Session("v1.1.0"), "1.0.0") == ("1.1.0", "https://github.com/x/releases/tag/v1.1.0")
    assert newer_release(Session("v1.0.0"), "1.0.0") is None
    assert newer_release(Session("v0.9.0"), "1.0.0") is None
