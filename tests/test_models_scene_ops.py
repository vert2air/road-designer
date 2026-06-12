"""Scene の ID 振り直し・マージ・effective_set の単体テスト。

仕様（仕様書 2.8 / 基本設計書 3.3 / 詳細設計書 1.14・1.15）に基づく。
実装の走査順をなぞるのではなく、「ID 一意性」「参照の維持」
「ニックネームの追従」という保証されるべき性質を検証する。
"""
import pytest

from models import (
    Vec2,
    Line,
    Segment,
    Circle,
    Arc,
    Clothoid,
    Scene,
    TwoLineOffsetConstraint,
    effective_set,
)


def _all_ids(scene):
    """Scene 内の全図形 ID をリストで返す（重複検出用）。"""
    ids = []
    for ln in scene.lines:
        ids.append(ln.id)
        ids.extend(s.id for s in ln.segments)
    for ci in scene.circles:
        ids.append(ci.id)
        ids.extend(a.id for a in ci.arcs)
    ids.extend(c.id for c in scene.clothoids)
    ids.extend(o.id for o in scene.offset_constraints)
    ids.extend(o.id for o in scene.two_line_offset_constraints)
    return ids


def _make_scene_with_invalid_clothoid():
    """直線が円の中心を通る（d=0 < R → クロソイド無効）シーンを作る。

    クロソイドが無効だと compute() が線分の自動分割を行わないため、
    構造を変えずに ID・参照だけをテストできる。
    """
    sc = Scene()
    ln = Line(Vec2(0, 0), Vec2(100, 0))
    seg = Segment(ln, 0.0, 1.0)
    ln.segments.append(seg)
    sc.add_line(ln)
    ci = Circle(Vec2(50, 0), 10.0)   # 中心が直線上 → d=0
    arc = Arc(ci, 0.0, 1.0)
    ci.arcs.append(arc)
    sc.add_circle(ci)
    clo = Clothoid(ln, ci)
    sc.add_clothoid(clo)
    assert clo.is_valid is False     # 前提の確認
    return sc, ln, seg, ci, arc, clo


class TestRenumberIds:
    """Scene.renumber_ids（仕様書 2.8「ID の振り直し」）。"""

    def test_ids_become_sequential_from_one(self):
        sc, *_ = _make_scene_with_invalid_clothoid()
        sc.renumber_ids()
        ids = _all_ids(sc)
        assert sorted(ids) == list(range(1, len(ids) + 1))

    def test_nicknames_follow_objects(self):
        """ニックネームは「同じ図形」に付き続ける（ID には付かない）。"""
        sc, ln, seg, ci, _, _ = _make_scene_with_invalid_clothoid()
        sc.set_nickname(ln.id, "my_line")
        sc.set_nickname(ci.id, "my_circle")
        sc.renumber_ids()
        assert sc.get_nickname(ln.id) == "my_line"
        assert sc.get_nickname(ci.id) == "my_circle"
        assert sc.get_nickname(seg.id) is None

    def test_clothoid_integer_refs_follow(self):
        """Segment/Arc の clothoid_start/end 整数参照が新 ID に追従する。"""
        sc, ln, seg, ci, arc, clo = _make_scene_with_invalid_clothoid()
        seg.clothoid_end = clo.id
        arc.clothoid_start = clo.id
        sc.renumber_ids()
        assert seg.clothoid_end == clo.id
        assert arc.clothoid_start == clo.id

    def test_new_objects_do_not_collide_after_renumber(self):
        """振り直し後に生成した図形の ID が既存と衝突しない。"""
        sc, *_ = _make_scene_with_invalid_clothoid()
        sc.renumber_ids()
        existing = set(_all_ids(sc))
        new_line = Line(Vec2(0, 10), Vec2(10, 10))
        assert new_line.id not in existing

    def test_empty_scene_is_noop(self):
        sc = Scene()
        sc.renumber_ids()   # 例外を投げない
        assert _all_ids(sc) == []


class TestMergeFromDict:
    """Scene.merge_from_dict（仕様書 2.8「追加読み込み」）。"""

    @staticmethod
    def _source_dict():
        """マージ元データ: 直線 + 円 + 無効クロソイド + ニックネーム。"""
        src = Scene()
        ln = Line(Vec2(0, 100), Vec2(100, 100))
        ln.segments.append(Segment(ln, 0.0, 1.0))
        src.add_line(ln)
        ci = Circle(Vec2(50, 100), 10.0)   # 中心が直線上 → 無効クロソイド
        src.add_circle(ci)
        src.add_clothoid(Clothoid(ln, ci))
        src.set_nickname(ln.id, "merged_line")
        return src.to_dict()

    def test_added_objects_returned_and_appended(self):
        sc = Scene()
        base = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(base)
        added = sc.merge_from_dict(self._source_dict())
        assert len(added) == 3   # Line + Circle + Clothoid
        assert len(sc.lines) == 2
        assert len(sc.circles) == 1
        assert len(sc.clothoids) == 1

    def test_id_collision_resolved(self):
        """マージ元と同じ ID が既存にあっても全 ID が一意になる。"""
        d = self._source_dict()
        sc = Scene()
        # 既存シーンにマージ元と同じ ID の直線を作る
        clash = Line(Vec2(0, 0), Vec2(10, 0),
                     line_id=d["lines"][0]["id"])
        sc.add_line(clash)
        sc.merge_from_dict(d)
        ids = _all_ids(sc)
        assert len(ids) == len(set(ids))

    def test_clothoid_reference_survives_id_remap(self):
        """ID が振り直されてもクロソイドはマージで追加された直線・円を
        参照する（既存図形を誤参照しない）。"""
        d = self._source_dict()
        sc = Scene()
        clash = Line(Vec2(0, 0), Vec2(10, 0),
                     line_id=d["lines"][0]["id"])
        sc.add_line(clash)
        sc.merge_from_dict(d)
        clo = sc.clothoids[0]
        assert clo.line is not clash
        assert clo.line in sc.lines
        assert clo.circle in sc.circles

    @pytest.mark.xfail(
        strict=True,
        reason="既知バグ: merge_from_dict は _extract_nick を "
               "_resolve_id より先に呼ぶため、ID 衝突時にニックネームが"
               "元 ID のまま登録され、既存の無関係な図形に付け替わる。"
               "マージされた図形自身はニックネームを失う。")
    def test_nickname_transferred_to_new_id(self):
        d = self._source_dict()
        sc = Scene()
        clash = Line(Vec2(0, 0), Vec2(10, 0),
                     line_id=d["lines"][0]["id"])
        sc.add_line(clash)
        sc.merge_from_dict(d)
        merged_line = [ln for ln in sc.lines if ln is not clash][0]
        assert sc.get_nickname(merged_line.id) == "merged_line"
        # 既存図形にニックネームが移ってしまわないこと
        assert sc.get_nickname(clash.id) is None

    def test_existing_geometry_untouched(self):
        sc = Scene()
        base = Line(Vec2(1, 2), Vec2(3, 4))
        sc.add_line(base)
        sc.merge_from_dict(self._source_dict())
        assert (base.ref_start.x, base.ref_start.y) == (1, 2)
        assert (base.ref_end.x, base.ref_end.y) == (3, 4)

    def test_two_line_constraint_merged_with_refs(self):
        """マージ元の 2直線-1円拘束が参照解決されて追加される。"""
        src = Scene()
        la = Line(Vec2(0, 0), Vec2(10, 0))
        lb = Line(Vec2(0, 0), Vec2(0, 10))
        ci = Circle(Vec2(13, 12), 10.0)
        src.add_line(la)
        src.add_line(lb)
        src.add_circle(ci)
        oc = TwoLineOffsetConstraint()
        oc.line_a, oc.line_b, oc.circle = la, lb, ci
        oc.calc_offsets_from_current()
        src.two_line_offset_constraints.append(oc)

        sc = Scene()
        sc.merge_from_dict(src.to_dict())
        assert len(sc.two_line_offset_constraints) == 1
        oc2 = sc.two_line_offset_constraints[0]
        assert oc2.line_a in sc.lines
        assert oc2.line_b in sc.lines
        assert oc2.circle in sc.circles
        assert oc2.off_a == pytest.approx(2.0)
        assert oc2.off_b == pytest.approx(3.0)


class TestEffectiveSet:
    """effective_set（詳細設計書 1.15）。"""

    def test_segment_promotes_to_parent_line(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        assert effective_set([seg]) == [ln]

    def test_two_segments_same_line_dedupe(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        s1 = Segment(ln, 0.0, 0.5)
        s2 = Segment(ln, 0.5, 1.0)
        ln.segments.extend([s1, s2])
        assert effective_set([s1, s2]) == [ln]

    def test_arc_promotes_to_parent_circle(self):
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, 1.0)
        ci.arcs.append(arc)
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        result = effective_set([arc, ln])
        assert result == [ci, ln]   # 順序保持

    def test_parent_and_child_mixed_dedupe(self):
        """ラバーバンド選択は子と親を両方含む — 重複しないこと。"""
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        assert effective_set([seg, ln]) == [ln]

    def test_clothoid_passthrough(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 0), 10.0)
        clo = Clothoid(ln, ci)
        assert effective_set([clo]) == [clo]

    def test_empty(self):
        assert effective_set([]) == []


class TestClothoidRefSerialization:
    """Segment/Arc の clothoid_start/end が保存・復元されること。"""

    def test_segment_refs_roundtrip(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        seg.clothoid_start = 41
        seg.clothoid_end = 42
        ln.segments.append(seg)
        sc.add_line(ln)
        sc2 = Scene.from_dict(sc.to_dict())
        seg2 = sc2.lines[0].segments[0]
        assert seg2.clothoid_start == 41
        assert seg2.clothoid_end == 42

    def test_arc_refs_roundtrip(self):
        sc = Scene()
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, 1.0)
        arc.clothoid_end = 99
        ci.arcs.append(arc)
        sc.add_circle(ci)
        sc2 = Scene.from_dict(sc.to_dict())
        arc2 = sc2.circles[0].arcs[0]
        assert arc2.clothoid_end == 99
        assert arc2.clothoid_start is None

    def test_unset_refs_stay_none(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ln.segments.append(Segment(ln, 0.0, 1.0))
        sc.add_line(ln)
        sc2 = Scene.from_dict(sc.to_dict())
        seg2 = sc2.lines[0].segments[0]
        assert seg2.clothoid_start is None
        assert seg2.clothoid_end is None
