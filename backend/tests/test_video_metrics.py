"""FB／IG 影片觀看指標：合併成一次 insights 呼叫，被拒時退回只讀平均觀看時長。"""

from app.services.workers.metrics import retention_curve, video_insights


def lifetime(data, name):
    row = next((r for r in data.get("data", []) if r.get("name") == name), {})
    return (row.get("values") or [{}])[0].get("value")


def run(platform, responses):
    calls, metric, extra = [], {}, dict(unavailable={}, metric_names={})

    def graph(path, query):
        calls.append(query["metric"])
        return responses[len(calls) - 1]

    video_insights(platform, {"external_id": "1_2"}, graph, metric, extra, lifetime)
    return calls, metric, extra


def test_instagram_reels_one_call():
    body = {"data": [
        {"name": "ig_reels_avg_watch_time", "values": [{"value": 5400}]},
        {"name": "ig_reels_video_view_total_time", "values": [{"value": 7_200_000}]},
        {"name": "reels_skip_rate", "values": [{"value": 37.5}]},
    ]}
    calls, metric, extra = run("instagram", [body])
    assert calls == ["ig_reels_avg_watch_time,ig_reels_video_view_total_time,reels_skip_rate"]
    assert metric["avg_watch_time"] == 5400
    assert extra["watch_hours"] == 2 and extra["skip_rate"] == 37.5
    assert extra["unavailable"] == {}
    assert extra["metric_units"] == {"avg_watch_time": "milliseconds"}


def test_rejected_batch_falls_back_to_average_only():
    only = {"data": [{"name": "post_video_avg_time_watched", "values": [{"value": 1890}]}]}
    calls, metric, extra = run("facebook", [{"unavailable": True, "code": 100}, only])
    assert calls == [
        "post_video_avg_time_watched,post_video_view_time,post_video_retention_graph",
        "post_video_avg_time_watched",
    ]
    assert metric["avg_watch_time"] == 1890
    assert extra["watch_hours"] is None and extra["retention"] is None
    assert extra["unavailable"] == {"watch_hours": "not_returned", "retention": "not_returned"}


def test_retention_curve_is_ordered_percent():
    assert retention_curve({"10": 0.2, "0": 1, "2": 0.5}) == [100, 50.0, 20.0]
    assert retention_curve({"0": 100, "1": 64.25}) == [100, 64.2]
    bad_curves = (None, {"0": 1}, {"0": 1, "x": 0.5}, {"0": 1, "1": -1}, {"0": 1, "1": 250})
    for bad in (*bad_curves, [1, 0.5]):
        assert retention_curve(bad) is None
