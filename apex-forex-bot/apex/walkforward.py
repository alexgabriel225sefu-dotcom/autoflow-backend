"""Walk-forward validation — the difference between a real edge and a fitted one.

A single backtest over all available history answers the wrong question. Any
strategy with tunable parameters can be made to look good on data you already
have; the number that matters is how it does on data it has never seen.

Walk-forward answers that. The history is cut into consecutive blocks:

    |--- train ---|- validate -|- test -|
              |--- train ---|- validate -|- test -|
                        |--- train ---|- validate -|- test -|

Parameters are chosen on train, the choice is confirmed on validate, and the
result is recorded on test — which was never looked at while choosing. Rolling
the window forward gives a sequence of out-of-sample results instead of one
number, and that sequence is what tells you whether an edge persists or whether
one lucky month carried the whole backtest.

Splits are chronological, never shuffled. Shuffling leaks the future into the
past and is the single most common way a backtest lies.

Nothing here knows about any particular strategy: callers pass an `evaluate`
function, which keeps this honest and testable. Pure Python — the deploy image
has no numpy.
"""

from apex import ev


def splits(n, train, validate, test, step=None):
    """Chronological (train, validate, test) index ranges, oldest first.

    Yields nothing rather than raising when the history is too short for even
    one window — a caller should report "not enough data", not crash.
    """
    if min(train, validate, test) <= 0:
        raise ValueError("train, validate and test must all be positive")
    step = step or test
    if step <= 0:
        raise ValueError("step must be positive")
    start = 0
    while start + train + validate + test <= n:
        a = start
        b = start + train
        c = b + validate
        d = c + test
        yield (range(a, b), range(b, c), range(c, d))
        start += step


def _summary(r_multiples):
    m = ev.metrics(r_multiples)
    m["total_R"] = round(sum(r_multiples), 4) if r_multiples else 0.0
    return m


def run(bars, evaluate, train=4000, validate=1000, test=1000, step=None,
        param_grid=None):
    """Walk `bars` forward, selecting parameters in-sample and scoring out.

    `evaluate(bars_slice, params) -> list[float]` returns the R-multiple of
    each trade the strategy took over that slice. Returning [] (no trades) is
    a valid answer and is recorded as such.

    `param_grid` is a list of parameter dicts to choose between. With None or a
    single entry there is no selection happening, and the run reduces to plain
    rolling out-of-sample testing — still far more informative than one
    backtest over everything.

    Returns per-window results plus an aggregate over the concatenated test
    windows. The aggregate is the honest headline number: every trade in it was
    taken on data the parameters had never seen.
    """
    grid = param_grid or [{}]
    windows = []
    all_test_r = []

    for i, (tr, va, te) in enumerate(splits(len(bars), train, validate, test, step)):
        # Choose on train, confirm on validate. Selecting on the combination
        # rather than train alone resists a parameter that happens to suit one
        # block; the test block stays untouched either way.
        best, best_score = None, None
        for params in grid:
            r_tr = evaluate([bars[j] for j in tr], params)
            r_va = evaluate([bars[j] for j in va], params)
            if not r_va:
                continue                      # took no trades — cannot rank it
            score = _summary(r_tr)["expectancy_R"] * 0.3 + \
                _summary(r_va)["expectancy_R"] * 0.7
            if best_score is None or score > best_score:
                best, best_score = params, score

        if best is None:
            windows.append({"window": i, "selected": None,
                            "reason": "no parameter set traded in validation"})
            continue

        r_te = evaluate([bars[j] for j in te], best)
        all_test_r.extend(r_te)
        windows.append({
            "window": i,
            "selected": best,
            "in_sample_score": round(best_score, 4),
            "test": _summary(r_te),
        })

    scored = [w for w in windows if "test" in w]
    profitable = [w for w in scored if w["test"]["expectancy_R"] > 0]

    return {
        "windows": windows,
        "windows_scored": len(scored),
        "windows_profitable": len(profitable),
        "consistency": (round(len(profitable) / len(scored), 3)
                        if scored else 0.0),
        "out_of_sample": _summary(all_test_r),
        "monte_carlo": ev.monte_carlo_r_paths(all_test_r, simulations=2000, seed=7),
    }


def concentration(r_multiples, top_n=5):
    """How much of the total return came from the few best trades.

    A strategy whose profit is one outlier is not an edge you can rely on —
    remove that trade and the account is flat. Reported as the share of total
    profit contributed by the `top_n` largest winners.
    """
    r = sorted((float(x) for x in r_multiples or []), reverse=True)
    if not r:
        return {"top_share": 0.0, "total_R": 0.0, "trades": 0}
    total = sum(r)
    top = sum(r[:top_n])
    return {
        "top_share": round(top / total, 3) if total > 0 else 0.0,
        "top_R": round(top, 3),
        "total_R": round(total, 3),
        "trades": len(r),
    }


def verdict(result, min_windows=3, min_consistency=0.6, min_expectancy=0.02):
    """A plain pass/fail on the out-of-sample evidence.

    Deliberately strict and deliberately blunt. The failure mode this guards
    against is reading a backtest hopefully — so the thresholds are stated up
    front and the answer is a sentence, not a number to interpret.
    """
    scored = result.get("windows_scored", 0)
    if scored < min_windows:
        return (False, f"only {scored} out-of-sample window(s) — not enough "
                       f"history to judge; need at least {min_windows}")

    oos = result["out_of_sample"]
    if oos["trades"] == 0:
        return False, "the strategy took no trades out of sample"
    if oos["expectancy_R"] <= 0:
        return (False, f"negative out-of-sample expectancy "
                       f"({oos['expectancy_R']:+.4f}R over {oos['trades']} trades)")
    if oos["expectancy_R"] < min_expectancy:
        return (False, f"expectancy {oos['expectancy_R']:+.4f}R is inside the "
                       f"noise floor — below the {min_expectancy}R minimum")
    if result["consistency"] < min_consistency:
        return (False, f"only {result['windows_profitable']}/{scored} windows "
                       f"profitable — the edge does not persist")
    if result["monte_carlo"]["prob_negative"] > 0.25:
        return (False, f"{result['monte_carlo']['prob_negative']:.0%} of "
                       f"reshuffled orderings end negative — the result depends "
                       f"on the sequence, not the edge")

    return (True, f"{oos['expectancy_R']:+.4f}R per trade over {oos['trades']} "
                  f"out-of-sample trades, profitable in "
                  f"{result['windows_profitable']}/{scored} windows")
