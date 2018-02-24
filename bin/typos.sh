#!/bin/bash

set -e

source "$(dirname $0)/ci_lib.sh"

REMOTE="$(git remote show | grep upstream || echo 'origin')"

TYPOS='ec-oh | ro-el | FI-XME | ansi-bel | fix-up | skip- ci'
if [ "${TRAVIS_BRANCH:-master}" == "master" ]; then
    TYPOS="${TYPOS} | fix-up! | s-qua-sh!"
fi
TYPOS=$(echo "$TYPOS" | tr -d ' -')
ANCESTOR=$(git merge-base ${REMOTE}/master HEAD)
if [ $ANCESTOR == $(git rev-parse HEAD) ]; then
    ANCESTOR=HEAD^
fi
echo "Checking against ${ANCESTOR} for conflict and whitespace problems:"
git diff --check ${ANCESTOR}..HEAD  # Silent unless problem detected
git log -p ${ANCESTOR}..HEAD -- . &> "$WORKSPACE/commits_with_diffs"
LINES=$(wc -l < "$WORKSPACE/commits_with_diffs")
if (( $LINES == 0 ))
then
    echo "FATAL: no changes found since ${ANCESTOR}"
    exit 3
fi
echo "Examining $LINES change lines for typos:"
set +e
egrep -a -i -2 --color=always "$TYPOS" "$WORKSPACE/commits_with_diffs" && exit 3
exit 0
