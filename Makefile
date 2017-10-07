venv = venv
pip = $(venv)/bin/pip

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

.PHONY: clean
clean:
	@echo "Remove compiled Python files"
	@rm -rf `find . -name __pycache__`
