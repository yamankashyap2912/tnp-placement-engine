PY ?= python3

.PHONY: install all setup load check match train report serve test demo benchmark er clean-models

install:      ; $(PY) -m pip install -r requirements.txt
all:          ; $(PY) run.py all
setup:        ; $(PY) run.py setup-db
load:         ; $(PY) run.py load-data
check:        ; $(PY) run.py check
match:        ; $(PY) run.py match
train:        ; $(PY) run.py train
report:       ; $(PY) run.py report
serve:        ; $(PY) run.py serve
demo:         ; $(PY) run.py demo
benchmark:    ; $(PY) run.py benchmark
er:           ; $(PY) run.py er-diagram
test:         ; $(PY) -m pytest tests -q
clean-models: ; rm -f models/*.joblib
