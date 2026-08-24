#!/usr/bin/env bash
# Ruft die GitHub-CLI mit dem Konto DomCim auf.
#
# Hintergrund: auf diesem Rechner sind zwei GitHub-Konten in `gh`
# angemeldet. Aktiv ist das Arbeitskonto (dominik-dill_Cimatron), das auf
# DomCim/rechnungsblatt nur Leserechte hat — `gh pr create` scheitert damit
# oder legt den PR unter dem falschen Konto an. Dieses Skript schiebt für
# den einen Aufruf das DomCim-Token unter, ohne das aktive Konto global
# umzustellen (das würde die Arbeit an den Cimatron-Repos stören).
#
# Aufruf:  scripts/gh-domcim.sh pr create --base develop --fill
#          scripts/gh-domcim.sh pr list
set -euo pipefail

GH="${GH_BIN:-/c/Program Files/GitHub CLI/gh.exe}"
[ -x "$GH" ] || { echo "gh nicht gefunden: $GH (GH_BIN setzen)" >&2; exit 1; }

if ! TOKEN="$("$GH" auth token -u DomCim 2>/dev/null)" || [ -z "$TOKEN" ]; then
    echo "Kein Token für DomCim. Anmelden mit: gh auth login" >&2
    exit 1
fi

GH_TOKEN="$TOKEN" exec "$GH" "$@"
