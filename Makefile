VERIFY_BOOTSTRAP ?= python3

.PHONY: verify verify-fast
verify:
	$(VERIFY_BOOTSTRAP) scripts/verify.py --profile full

verify-fast:
	$(VERIFY_BOOTSTRAP) scripts/verify.py --profile fast
