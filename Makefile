.PHONY: run test-post

run:
	python scripts/run_daily.py --profiles cs,tam,se --us_only --min_alert_score 85

test-post:
	python scripts/run_daily.py --test_post
