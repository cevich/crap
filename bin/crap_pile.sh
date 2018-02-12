#!/bin/bash

set -e

echo "PILES: $PILES PWD: $PWD WORKSPACE: $WORKSPACE ARTIFACTS: $ARTIFACTS" > /dev/stderr

ERRMSG="Error, this script is intended to be called by $(dirname $0)/pile.py"
if [[ -z $PILES ]]
then
    echo "$ERRMSG"
    exit 125
elif [[ ! -d "$WORKSPACE" ]]
then
    echo "$ERRMSG"
    exit 123
elif [[ ! -d "$ARTIFACTS" ]]
then
    echo "$ERRMSG"
    exit 122
fi

# Only do this once for $WORKSPACE
((PILES)) && echo "$(basename $0) not re-initializing workspace (\$PILES > 0)"
((PILES)) || /usr/bin/rsync --recursive --links \
                --delay-updates --whole-file --exclude='.venv' \
                --exclude='.pile.*' --exclude='.cache' \
                --safe-links --perms --times --checksum ./ "${WORKSPACE}/"
