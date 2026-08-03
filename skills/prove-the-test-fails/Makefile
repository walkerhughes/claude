.PHONY: check evals

# Packaging, wiring, and the fixture's honesty. No API key, no cost.
check:
	python3 evals/check_wiring.py
	./evals/check_fixture.sh

# Behavioural eval. Needs Claude Code on PATH and working credentials.
evals:
	./evals/run_eval.sh
