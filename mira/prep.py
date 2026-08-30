from __future__ import annotations

from datetime import date, timedelta

from mira.models import PrepItem, PrepWeek

START = date(2026, 8, 31)
TRACKS = ("dsa", "fundamentals", "design", "practice", "review")

# Five outcome blocks per week. Minutes total exactly 240 focused hours.
WEEKS = [
    ("Foundations: execution workflow", (480,420,120,120,60),
     ("8 Easy: arrays, strings and hashing", "Counting and probability foundations", "Requirements, architecture and API design", "SQL fundamentals and NumPy shapes", "Unseen Easy assessment and error log"), None),
    ("Probability and linear structures", (480,420,120,120,60),
     ("10: stacks, queues, linked lists and two pointers", "Conditional probability, total probability and Bayes", "Prediction-service API design", "SQL joins, CASE and conditional aggregation", "Re-solve assisted problems"), None),
    ("Trees and random variables", (480,360,180,120,60),
     ("10: recursion, trees, DFS, BFS and BST", "PMF, PDF, CDF and joint random variables", "Caching, CDNs and invalidation", "Implement variance, covariance and normalization", "Tree-pattern recall check"), None),
    ("Windows, expectation and checkpoint one", (480,300,180,120,120),
     ("10: binary search, windows, pointers and prefix sums", "Expectation, variance, covariance and distributions", "Load balancing, consistent hashing and rate limiting", "Distribution and metric exercises", "Checkpoint: coding, probability and mini-design"), "Checkpoint 1"),
    ("Graphs and sampling", (420,300,240,120,120),
     ("10: graph traversal, grids and components", "Sampling distributions, CLT and sample variance", "SQL, NoSQL, replication, sharding and CAP", "Window functions and analytical SQL", "Graph and statistics revision"), None),
    ("Heaps, backtracking and estimation", (420,300,240,120,120),
     ("10: heaps, intervals and backtracking", "Point estimation, bias and confidence intervals", "Queues, async workflows, MapReduce and TinyURL", "Implement splits, cross-validation and metrics", "Timed mixed set and estimator recall"), None),
    ("Dynamic programming and experiments", (420,240,240,180,120),
     ("10: DP, knapsack and LCS", "Hypothesis tests, power and A/B experimentation", "ML design framework and spam/abuse system", "Experiment SQL and metric implementation", "DP transitions and experiment review"), None),
    ("Linear models and checkpoint two", (420,240,240,180,120),
     ("8 hidden-topic Medium problems", "Linear/logistic regression, regularization and bias-variance", "Rate limiter and TinyURL full designs", "Implement linear and logistic regression", "Checkpoint: coding, ML fundamentals and design"), "Checkpoint 2"),
    ("Classical ML and recommendations", (360,240,300,180,120),
     ("8: trie, union-find, topo sort and shortest paths", "Trees, ensembles, SVM, KNN, clustering and evaluation", "Recommendation-system design", "Ranking metrics, funnel and retention SQL", "Mixed coding and model-selection review"), None),
    ("Linear algebra, neural nets and ranking", (300,240,300,180,180),
     ("6 timed mixed Medium problems", "Projection, eigendecomposition, SVD and neural networks", "Search, ads or feed-ranking design", "Dense layer, softmax, loss and backprop coding", "Coding and ML mock interviews"), None),
    ("PCA, optimization and production ML", (300,240,300,120,240),
     ("5 new problems plus equal-time revision", "PCA, gradients, Jacobians and Hessians", "Production ML, drift, serving and fraud design", "Matrix-calculus and PCA exercises", "Three full mocks and targeted repair"), None),
    ("Interview simulation and consolidation", (240,180,240,120,420),
     ("5 diagnostics and two coding mocks", "Rapid oral ML and mathematics review", "General and ML full-system designs", "Final SQL and ML-coding assessment", "Final mocks, error-log closure and readiness audit"), "Final readiness audit"),
]

GUIDANCE = {
    "dsa": "Record attempts, hints, complexity and failure pattern. New problems exclude re-solves.",
    "fundamentals": "Use curated lessons, then close notes and explain the topic from memory.",
    "design": "Produce a diagram and discuss requirements, scale, trade-offs and failure modes.",
    "practice": "Write executable code or SQL. Reading a solution does not complete this block.",
    "review": "Use the error log and spaced repetition; repair weaknesses instead of adding content.",
}

def canonical_weeks() -> list[PrepWeek]:
    result = []
    for number, (theme, minutes, titles, checkpoint) in enumerate(WEEKS, 1):
        starts = START + timedelta(days=(number - 1) * 7)
        result.append(PrepWeek(
            number=number, starts_on=starts.isoformat(),
            ends_on=(starts + timedelta(days=6)).isoformat(),
            theme=theme, checkpoint=checkpoint,
            items=[PrepItem(
                id=f"prep-w{number:02d}-{track}", week=number, track=track,
                title=title, description=GUIDANCE[track], planned_minutes=duration,
            ) for track, duration, title in zip(TRACKS, minutes, titles)],
        ))
    return result

def active_week(today: date | None = None) -> int:
    day = today or date.today()
    return max(1, min(12, ((day - START).days // 7) + 1))
