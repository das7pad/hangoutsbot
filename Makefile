venv = venv
python=python3

pip = $(venv)/bin/pip
pip_min_version = 18.1

pip_min_version_guard_base = $(venv)/pip-version
pip_min_version_guard = $(pip_min_version_guard_base)-$(pip_min_version)

# raise non-zero exit codes in pipes
SHELL=/bin/bash -o pipefail

# create a venv for running the hangupsbot
.PHONY: venv
venv: install-requirements

# create a venv for running the hangupsbot
.PHONY: install-requirements
install-requirements: venv-create
	$(pip) install --requirement requirements/requirements.txt

# install the hangupsbot package into a venv
.PHONY: install
install: venv-create
	rm -rf `find hangupsbot -name __pycache__`
	$(pip) install . --upgrade

# update or reinstall all packages
.PHONY: update-requirements
update-requirements: venv-create
	$(pip) install --requirement requirements/requirements.txt --upgrade

# check the venv and run pylint
.PHONY: lint
lint: venv-dev .lint

# check the venv and run the test-suite
.PHONY: test-only
test-only: venv-dev .test-only

# check the venv, run pylint and run the test-suite
.PHONY: test
test: venv-dev .test

# remove the local cache and compiled python files from local directories
.PHONY: clean
clean:
	rm -rf \
		.cache \
		venv \
		`find hangupsbot tests examples -name __pycache__`


### internal, house keeping and debugging targets ###

# house keeping: update the Jenkinsfile
Jenkinsfile: tools/gen_Jenkinsfile.py
	$(python) tools/gen_Jenkinsfile.py

# house keeping: update the localization
.PHONY: localization
localization:
	make --directory hangupsbot/locale

# internal: ensure an existing venv
.PHONY: venv-create
venv-create: $(pip)
venv-create: $(venv)/bin/wheel

$(venv)/bin/python:
	$(python) -m venv $(venv)

$(pip): $(pip_min_version_guard)
	touch $(pip)

$(pip_min_version_guard): $(venv)/bin/python
	$(pip) install --upgrade 'pip>=$(pip_min_version)'
	rm -f $(pip_min_version_guard_base)*
	touch $(pip_min_version_guard)

$(venv)/bin/wheel: $(pip)
	$(pip) install --upgrade wheel
	touch $(venv)/bin/wheel

# house keeping: update the requirements.in file
requirements/requirements.in: $(shell find hangupsbot -type d)
requirements/requirements.in: tools/gen_requirements.in.sh
	tools/gen_requirements.in.sh

# house keeping: update the requirements-dev.in file
requirements/requirements-dev.in: requirements/requirements.in
requirements/requirements-dev.in: $(shell find tests -type d)
requirements/requirements-dev.in: tools/gen_requirements-dev.in.sh
	tools/gen_requirements-dev.in.sh

# internal: check for `pip-compile` and ensure an existing cache directory
.PHONY: .gen-requirements
.gen-requirements: $(venv)/pip-tools
$(venv)/pip-tools: $(pip)
	$(pip) install pip-tools
	touch $(venv)/pip-tools

# house keeping: update `requirements.txt`:
# pip-compile prints everything to stdout as well, direct it to /dev/null
.PHONY: gen-requirements
gen-requirements: .gen-requirements requirements/requirements.in
	CUSTOM_COMPILE_COMMAND="make gen-requirements" \
		$(venv)/bin/pip-compile \
			--upgrade \
			--no-annotate \
			--no-index \
			--no-emit-trusted-host \
			--output-file requirements/requirements.txt \
			requirements/requirements.in \
		> /dev/null

# house keeping: update `requirements-dev.txt`:
# gather requirements from ./hangupsbot and ./tests
.PHONY: gen-dev-requirements
gen-dev-requirements: .gen-requirements requirements/requirements-dev.in
	CUSTOM_COMPILE_COMMAND="make gen-dev-requirements" \
		$(venv)/bin/pip-compile \
			--upgrade \
			--no-annotate \
			--no-index \
			--no-emit-trusted-host \
			--output-file requirements/requirements-dev.txt \
			requirements/requirements-dev.in \
		> /dev/null

# internal: ensure a venv with dev requirements
.PHONY: venv-dev
venv-dev: $(venv)/dev
$(venv)/dev: $(pip)
$(venv)/dev: $(venv)/bin/wheel
$(venv)/dev: requirements/requirements-dev.txt
	$(pip) install --requirement requirements/requirements-dev.txt
	touch $(venv)/dev

# internal: run pylint, prepend extra blank lines for each module
.PHONY: .lint
.lint:
	$(venv)/bin/pylint -s no -j 1 hangupsbot

# internal: run the test-suite
.PHONY: .test-only
.test-only:
	$(venv)/bin/py.test -v tests

# internal: run pylint and the test-suite
.PHONY: .test
.test: .lint .test-only

# debugging: run the test suite verbose
.PHONY: test-only-verbose
test-only-verbose:
	$(venv)/bin/py.test -vvv tests
