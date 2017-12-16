venv = venv
python=python3
pip = $(venv)/bin/pip
# raise non-zero exit codes in pipes
SHELL=/bin/bash -o pipefail

.PHONY: venv
venv: install-requirements

.PHONY: venv-create
venv-create:
	@if [ ! -d $(venv) ]; then \
		echo "Creating venv" && ${python} -m venv $(venv); fi

.PHONY: .gen-requirements
.gen-requirements: venv-create
	@if [ ! -d $(venv)/lib/*/site-packages/piptools ]; then \
		echo "Installing pip-tools" && $(pip) install -q pip-tools \
		echo "Done"; fi
	@if [ ! -d .cache ]; then mkdir .cache; fi

# the output is cached and extra requirements can be added - e.g. git-targets
# NOTE: adding URLs/git-targets into the final file breaks pip-compile
# pip-compile prints everything to stdout as well, direct it to /dev/null
.PHONY: gen-requirements
gen-requirements: .gen-requirements
	@echo "Gathering requirements"
	@cat `find hangupsbot -name requirements.extra` \
		| sed -r 's/(.+)#egg=(.+)==(.+)-(.+)/-e \1#egg=\2==\4\n/' \
		> .cache/.requirements.extra
	@$(venv)/bin/pip-compile --upgrade --output-file .cache/.requirements.tmp \
		.cache/.requirements.extra `find hangupsbot -name requirements.in` \
		> /dev/null
	@echo -e "#\n# This file is autogenerated by pip-compile\n# To update, \
	run:\n#\n#   make gen-requirements\n#\n" \
		> requirements.txt
	@cat .cache/.requirements.tmp \
		|sed -r 's/^-e (.+)#egg=(.+)==(.+)/\1#egg=\2==\2-\3/' \
		| sed '/^\s*#/d;s/\s#.*//g;s/[ \t]*//g' \
		>> requirements.txt
	@echo "Done"

# gather requirements from ./hangupsbot and ./tests
.PHONY: gen-dev-requirements
gen-dev-requirements: .gen-requirements
	@echo "Gathering development requirements"
	@cat `find hangupsbot tests -name requirements.extra` \
		| sed -r 's/(.+)#egg=(.+)==(.+)-(.+)/-e \1#egg=\2==\4\n/' \
		> .cache/.requirements-dev.extra
	@$(venv)/bin/pip-compile --upgrade \
		--output-file .cache/.requirements-dev.tmp \
		`find hangupsbot tests -name requirements.in` \
		.cache/.requirements-dev.extra > /dev/null
	@echo -e "#\n# This file is autogenerated by pip-compile\n# To update, \
	run:\n#\n#   make gen-dev-requirements\n#\n" \
		> requirements-dev.txt
	@cat .cache/.requirements-dev.tmp \
		|sed -r 's/^-e (.+)#egg=(.+)==(.+)/\1#egg=\2==\2-\3/' \
		| sed '/^\s*#/d;s/\s#.*//g;s/[ \t]*//g' \
		>> requirements-dev.txt
	@echo "Done"

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
venv-dev: venv-create
	@echo "Installing Dev requirements"
	@$(pip) install -q --requirement requirements-dev.txt
	@echo "Done"

.PHONY: install
install: venv-create
	@echo "Install: started"
	@rm -rf `find hangupsbot -name __pycache__`
	@$(pip) install -q . --process-dependency-links --upgrade
	@echo "Install: finished"

.PHONY: localization
localization:
	@make -s --directory hangupsbot/locale

.PHONY: lint
lint: venv-dev
	@echo "Lint: started"
	@$(venv)/bin/pylint -s no -j 4 hangupsbot | sed -r 's/(\*{13})/\n\1/g'
	@echo "Lint: no errors found"

.PHONY: clean
clean:
	@echo "Remove local cache and compiled Python files"
	@rm -rf .cache `find hangupsbot tests examples -name __pycache__`
