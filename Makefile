# Labo 00 : outils de vérification du rendu.
#
# Ces cibles sont utilisées par le CI (.github/workflows/grading.yml) et
# peuvent être lancées localement depuis Ubuntu :
#
#   make          compile rendu/hello.c dans build/hello
#   make test     lance les tests de conformité (nécessite pytest)
#   make prepare  extrait le rapport Word et l'inventaire du dépôt dans build/
#   make clean    supprime build/ et les caches

CC     = gcc
CFLAGS = -std=c17 -Wall -Wextra -pedantic
BUILD  = build

.PHONY: all test prepare clean

all: $(BUILD)/hello

$(BUILD)/hello: rendu/hello.c | $(BUILD)
	$(CC) $(CFLAGS) $< -o $@

$(BUILD):
	mkdir -p $@

test:
	pytest -vv

# Ne doit jamais échouer : le CI l'exécute avant les tests.
prepare:
	python3 scripts/prepare_review.py || true

clean:
	$(RM) -r $(BUILD) .pytest_cache tests/__pycache__ scripts/__pycache__
