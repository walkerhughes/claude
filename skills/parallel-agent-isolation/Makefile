.PHONY: check evals

# Packaging and wiring. No API key, no cost.
check:
	python3 evals/check_wiring.py

# Behavioural eval. Needs Claude Code on PATH and working credentials.
evals:
	python3 evals/run_evals.py
