from stats import median


def test_odd():
    assert median([3, 1, 2]) == 2


def test_even_takes_lower_middle():
    # 本题约定：偶数长度取**较小**的那个中间值（不是平均）
    assert median([1, 2, 3, 4]) == 2
    assert median([10, 20, 30, 40]) == 20
