#!/bin/sh
# Save clipboard to <name>.txt only if it is the expected Légifrance decision text.
t=$(LANG=en_US.UTF-8 pbpaste)
case "$t" in
  "Cour de cassation"*"$2"*) printf '%s\n' "$t" > "$1.txt"; echo "saved $1.txt $(printf '%s' "$t" | wc -c) chars";;
  *) echo "NOT SAVED: clipboard is not decision $2";;
esac
