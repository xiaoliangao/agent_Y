from rounding import round_to_int


def test_round_half_up():
    # 本题约定：0.5 一律向上进（round-half-up），不是 Python 内置 round 的银行家舍入
    assert round_to_int(0.5) == 1
    assert round_to_int(1.5) == 2
    assert round_to_int(2.5) == 3
    assert round_to_int(2.4) == 2
