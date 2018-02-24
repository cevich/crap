#!/bin/bash

set -e

if [[ "${DEBUG:-true}" == "true" ]]
then
    DEBUG=0
else
    DEBUG=1
fi

((DEBUG)) && echo "PILES: $PILES PWD: $PWD WORKSPACE: $WORKSPACE ARTIFACTS: $ARTIFACTS" > /dev/stderr

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
if ((PILES))
then
    ((DEBUG)) && echo "$(basename $0) not re-initializing workspace (\$PILES > 0)"
    exit 0
fi

((DEBUG)) && echo "Transfering $PWD/ to "${WORKSPACE}/""
/usr/bin/rsync --recursive --links \
               --delay-updates --whole-file --exclude='.venv' \
               --exclude='.pile.*' --exclude='.cache' \
               --safe-links --perms --times --checksum ./ "${WORKSPACE}/"

if ((DEBUG))
then
    echo "$WORKSPACE Contents: "
    ls -la "$WORKSPACE"
fi
