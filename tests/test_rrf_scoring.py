import unittest


def compute_rrf_score(ranks: list[int], k: int = 60) -> float:
    """Reciprocal Rank Fusion formula: sum(1 / (k + rank))."""
    return sum(1.0 / (k + r) for r in ranks)


class TestRRFScoring(unittest.TestCase):
    def test_single_rank_computation(self):
        # Rank 1 with k=60 -> 1 / 61
        score = compute_rrf_score([1], k=60)
        self.assertAlmostEqual(score, 1.0 / 61.0, places=6)

    def test_combined_ranks_higher_than_isolated(self):
        # Document ranked #2 in both vector and keyword should outscore #1 in only one
        both_rank_2 = compute_rrf_score([2, 2], k=60)      # 1/62 + 1/62 = 0.032258
        vector_only_1 = compute_rrf_score([1], k=60)        # 1/61 = 0.016393
        self.assertGreater(both_rank_2, vector_only_1)

    def test_monotonic_decay(self):
        score_1 = compute_rrf_score([1], k=60)
        score_2 = compute_rrf_score([2], k=60)
        score_10 = compute_rrf_score([10], k=60)
        self.assertGreater(score_1, score_2)
        self.assertGreater(score_2, score_10)


if __name__ == "__main__":
    unittest.main()
