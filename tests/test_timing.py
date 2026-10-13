from quran_video.api.models import VerseTiming
from quran_video.core.timing import ALL, Seg, State, build_clips, clean_segments, cut_range, state_at


def vt(key, a, b, segs):
    return VerseTiming(key, a, b, tuple(tuple(s) for s in segs))


def test_clean_drops_malformed_and_clamps():
    # shape seen in Afasy 1:2/1:3: starts before the verse window, truncated [1]/[2] entries, floats
    t = vt("1:3", 11680, 16300, [[1, 11615, 12855], [1], [2, 12855.0, 16180.0], [2], [5, 5205]])
    assert clean_segments(t, 2) == [Seg(1, 11680, 12855), Seg(2, 12855, 16180)]


def test_clean_drops_out_of_range_positions_and_empty():
    t = vt("x:1", 0, 1000, [[1, 0, 500], [9, 500, 900], [2, 950, 950]])
    assert clean_segments(t, 2) == [Seg(1, 0, 500)]


def test_cut_range_and_offset():
    ts = [vt("18:2", 11180, 20000, [[1, 11180, 12000]]), vt("18:3", 20000, 25000, [[1, 20100, 21000]])]
    assert cut_range(ts) == (11180, 25000)
    clips = build_clips(ts, [1, 1], 11180)
    assert (clips[0].start, clips[0].end, clips[0].segs) == (0, 8820, (Seg(1, 0, 820),))
    assert (clips[1].start, clips[1].segs) == (8820, (Seg(1, 8920, 9820),))


def test_state_at_highlight_gaps_and_repeats():
    # reciter repeats words 2..3 (like reciter 161 on 18:31)
    ts = [vt("a:1", 0, 1000, [[1, 100, 300], [2, 300, 500], [3, 500, 700], [2, 700, 800], [3, 800, 900]]),
          vt("a:2", 1000, 2000, [])]
    clips = build_clips(ts, [3, 3], 0)
    assert state_at(clips, 50) == State(0, None, 0)  # before first word
    assert state_at(clips, 350) == State(0, 2, 2)
    assert state_at(clips, 750) == State(0, 2, 3)  # repeat re-lights word 2; word 3 stays revealed
    assert state_at(clips, 950) == State(0, 3, 3)  # gap after last word keeps it lit
    assert state_at(clips, 1500) == State(1, ALL, ALL)  # no segments -> whole verse
    assert state_at(clips, 99999) == State(1, ALL, ALL)  # past the end stays on last verse


def test_translation_markup_is_stripped():
    from quran_video.api.client import clean_translation
    raw = "Who believe in the unseen, establish prayer,<sup foot_note=195938>1</sup> and spend out of what We<sup foot_note=195937>2</sup> have"
    assert clean_translation(raw) == "Who believe in the unseen, establish prayer, and spend out of what We have"


def test_split_translation_follows_arabic_parts_at_punctuation():
    from quran_video.core.translation import split_translation
    t = "Allah - there is no deity except Him, the Ever-Living, the Sustainer of existence. Neither drowsiness overtakes Him nor sleep."
    a, b = split_translation(t, [30, 30])
    assert a.endswith("existence.") or a.endswith("Ever-Living,")  # cut at punctuation near the middle
    assert f"{a} {b}" == t
    assert split_translation(t, [1]) == [t]
    assert "".join(split_translation("阿拉，除他之外绝无应受崇拜的。他是永生的，自存的。", [1, 1, 1])) == "阿拉，除他之外绝无应受崇拜的。他是永生的，自存的。"
    assert all(split_translation("one two three", [1, 1, 1]))  # never an empty piece when words allow
