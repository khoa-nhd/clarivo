"""The axis convention the browser must decode head pose into.

The browser derives head pose from MediaPipe's 4x4 facial transformation
matrix. It was using the ZYX convention, which names a different axis "yaw".
Checked against rotations with known angles, it reported:

    a 30 degree head turn  -> 30 degrees of PITCH
    a 20 degree nod        -> 20 degrees of ROLL
    a 15 degree tilt       -> -15 degrees of YAW

Every axis shifted by one. The scorer treats them very differently - turning to
a slide is judged against gaze_sustain_seconds and head_turn_yaw_deg, nodding
against head_turn_pitch_deg, tilting is used to cancel camera tilt in the
posture stage - so every head movement in every browser-analysed recording was
graded against the rules for a different movement.

There was a test for the decomposition and it passed, because it built its
input matrices with the same mistaken convention the decomposition used; the
two errors cancelled. This file builds rotations from real axis geometry
instead, which is the only way the mistake shows up.

Python mirrors the JavaScript here because that is where this project's test
suite runs. The two must agree, which the shared cases below make checkable by
reading them side by side with services/visionTimeline.js.
"""

import math

import pytest

DEG = 180.0 / math.pi


def rot_y(degrees: float):
    """Turning the head to one side."""
    r = math.radians(degrees)
    c, s = math.cos(r), math.sin(r)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def rot_x(degrees: float):
    """Nodding."""
    r = math.radians(degrees)
    c, s = math.cos(r), math.sin(r)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rot_z(degrees: float):
    """Tilting towards a shoulder."""
    r = math.radians(degrees)
    c, s = math.cos(r), math.sin(r)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def column_major(r):
    """Lay a rotation out the way MediaPipe hands it over."""
    m = [0.0] * 16
    m[15] = 1.0
    for col in range(3):
        for row in range(3):
            m[col * 4 + row] = r[row][col]
    return m


def head_pose_from_matrix(m):
    """The decomposition services/visionTimeline.js performs."""
    if not m or len(m) < 16:
        return None
    at = lambda row, col: m[col * 4 + row]  # noqa: E731
    r02, r12, r22 = at(0, 2), at(1, 2), at(2, 2)
    r10, r11 = at(1, 0), at(1, 1)
    cos_pitch = math.hypot(r02, r22)
    if cos_pitch < 1e-6:
        return None
    return (
        math.atan2(r02, r22) * DEG,
        math.atan2(-r12, cos_pitch) * DEG,
        -math.atan2(r10, r11) * DEG,
    )


@pytest.mark.parametrize(("name", "rotation", "expected"), [
    ("turn_right_30", rot_y(30), (30.0, 0.0, 0.0)),
    ("turn_left_30", rot_y(-30), (-30.0, 0.0, 0.0)),
    ("turn_slight_8", rot_y(8), (8.0, 0.0, 0.0)),
    ("nod_down_20", rot_x(20), (0.0, 20.0, 0.0)),
    ("nod_up_20", rot_x(-20), (0.0, -20.0, 0.0)),
    ("tilt_15", rot_z(15), (0.0, 0.0, -15.0)),
    ("level", [[1, 0, 0], [0, 1, 0], [0, 0, 1]], (0.0, 0.0, 0.0)),
])
def test_each_axis_is_read_as_itself(name, rotation, expected):
    got = head_pose_from_matrix(column_major(rotation))
    assert got == pytest.approx(expected, abs=0.01)


def test_a_turn_combined_with_a_nod_keeps_them_separate():
    """The case that matters: looking down at notes while half-turned away."""
    got = head_pose_from_matrix(column_major(matmul(rot_y(25), rot_x(10))))
    assert got == pytest.approx((25.0, 10.0, 0.0), abs=0.01)


def test_a_turn_is_never_reported_as_a_nod():
    """The specific defect: the scorer judges the two against different rules."""
    yaw, pitch, _ = head_pose_from_matrix(column_major(rot_y(40)))
    assert abs(yaw) > 35.0
    assert abs(pitch) < 1.0


def test_a_nod_is_never_reported_as_a_tilt():
    _, pitch, roll = head_pose_from_matrix(column_major(rot_x(25)))
    assert abs(pitch) > 20.0
    assert abs(roll) < 1.0


def test_roll_runs_the_same_way_as_the_openvino_path():
    """Roll cancels camera tilt in the posture stage; backwards it would add it.

    MediaPipe's matrix runs the opposite way to the convention the scorer was
    built against, so the browser negates it.
    """
    _, _, roll = head_pose_from_matrix(column_major(rot_z(15)))
    assert roll < 0


def test_a_degenerate_matrix_is_refused_rather_than_decoded():
    assert head_pose_from_matrix([0.0] * 16) is None


def test_a_short_array_is_refused():
    assert head_pose_from_matrix([1.0, 2.0, 3.0]) is None


def test_nothing_is_refused():
    assert head_pose_from_matrix(None) is None
