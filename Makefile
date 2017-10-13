venv = venv
pip = $(venv)/bin/pip
# raise non-zero exit codes in pipes
SHELL=/bin/bash -o pipefail

.PHONY: venv
venv: venv-create install-requirements

.PHONY: venv-create
venv-create:
	@if [ ! -d $(venv) ]; then \
		echo "Creating venv" && python3 -m venv $(venv); fi

.PHONY: install-requirements
install-requirements: venv-create
	@echo "Installing requirements"
	@$(pip) install -q --requirement requirements.txt
	@echo "Done"

.PHONY: update-requirements
update-requirements: venv-create
	@echo "Updating requirements"
	@$(pip) install -q --requirement requirements.txt --upgrade
	@echo "Done"

.PHONY: venv-dev
venv-dev: venv
	@echo "Upgrading Dev requirements"
	@$(pip) install -q --requirement requirements-dev.txt --upgrade
	@echo "Done"

.PHONY: lint
lint:
	@if [ ! -d $(venv)/lib/*/site-packages/pylint ]; then make -s venv-dev; fi
	@echo "Lint: started"
	@$(venv)/bin/pylint -s no -j 4 hangupsbot | sed -r 's/(\*{13})/\n\1/g'
	@echo "Lint: no errors found"

.PHONY: test-only
test-only:
	@if [ ! -d $(venv)/lib/*/site-packages/_pytest ]; then make -s venv-dev; fi
	@echo "Tests: started"
	@$(venv)/bin/py.test -q tests
	@echo "Tests: all completed"

.PHONY: test
test: lint test-only

.PHONY: clean
clean:
	@echo "Remove compiled Python files"
	@rm -rf `find . -name __pycache__`
