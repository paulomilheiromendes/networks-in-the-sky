# Convenience targets. Every target is also written out as plain commands in README.md.

NS3_IMAGE ?= sky-ns3:3.42
PY_IMAGE  ?= sky-py:1.0
PYTHON    ?= python3

.PHONY: images ns3-image py-image venv lab run nix-lab nix-run check

## Docker track ------------------------------------------------------------

images: ns3-image py-image            ## build both simulation images

ns3-image:                            ## build the ns-3 image (first time: 20-40 min)
	docker build -t $(NS3_IMAGE) -f docker/ns3.Dockerfile .

py-image:                             ## build the Python simulation image
	docker build -t $(PY_IMAGE) -f docker/py.Dockerfile .

venv:                                 ## create .venv with Jupyter + analysis packages
	$(PYTHON) -m venv .venv && .venv/bin/pip install -r requirements.txt

lab:                                  ## start Jupyter (Docker track)
	.venv/bin/jupyter lab

run:                                  ## execute the whole notebook, saving outputs in place
	.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebook.ipynb

## NixNet track ------------------------------------------------------------

nix-lab:                              ## start Jupyter from the pinned Nix environment
	nix develop -c jupyter lab

nix-run:                              ## execute the whole notebook in the Nix environment
	nix develop -c jupyter nbconvert --to notebook --execute --inplace notebook.ipynb

## Before submitting -------------------------------------------------------

check:                                ## fresh clone of the last commit, then run the notebook
	rm -rf .check && git clone -q . .check
	@if [ -f flake.lock ] && command -v nix >/dev/null && [ "$(TRACK)" = nixnet ]; then \
	  cd .check && $(MAKE) -s nix-run; \
	else \
	  cd .check && $(MAKE) -s venv run; \
	fi
	@echo "OK: the committed repository runs from a fresh clone (.check/notebook.ipynb)."
