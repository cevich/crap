#!/bin/bash

# This wrapper-script reduces the number of dependencies needed on the control-machine
# and always executes from a fixed-version / verified environment.  In addition to
# the requirements for whichever ``cloud_group`` is used (docker by default), this
# script requires:
#
#    python2-virtualenv gcc openssl-devel redhat-rpm-config libffi-devel
#    python-devel libselinux-python rsync
#
# Example usage
#   $ ./venv-cmd ansible-playbook \
#               --check \
#               /path/to/crap/main.yml

# All errors are fatal
set -e

SCRIPT_NAME=$(basename "$0")
SCRIPT_DIR=$(dirname "$0")
[ -n "$WORKSPACE" ] || export WORKSPACE=$(realpath "$SCRIPT_DIR")
REQUIREMENTS="$WORKSPACE/requirements.txt"

echo

if ! type -P virtualenv &> /dev/null
then
    echo "Could not find required 'virtualenv' binary installed on system."
    exit 1
fi

if [ ! -d "$WORKSPACE" ] || [ ! -w "$WORKSPACE" ]
then
    echo "Not a directory or not writeable by current user ($USER): $WORKSPACE"
    exit 5
fi

if [ "$#" -lt "1" ]
then
    echo "No executable and command-line options specified."
    echo "usage: $0 <COMMAND> -i whatever --private-key=something --extra-vars foo=bar"
    exit 2
fi

# Confine this w/in the workspace
export PIPCACHE="$WORKSPACE/.cache/pip"
mkdir -p "$PIPCACHE"
# Don't recycle cache, it may become polluted between runs
trap 'rm -rf "$PIPCACHE"' EXIT

export ARTIFACTS="$WORKSPACE/artifacts"
mkdir -p "$ARTIFACTS"
[ -d "$ARTIFACTS" ] || exit 4

export LOGFP="$ARTIFACTS/$SCRIPT_NAME.log"

# All command failures from now on are fatal
set -e
echo "Bootstrapping trusted virtual environment, this may take a few minutes, depending on networking."
echo
echo "-----> Logs and output artifacts found under: \"$ARTIFACTS\")"
echo

(
    set -x
    cd "$WORKSPACE"
    # When running more than once, make it fast by skipping the bootstrap
    if [ ! -d "./.venv" ] || [ ! -r "./.venv/.complete" ]; then
        # N/B: local system's virtualenv binary - uncontrolled version fixed below
        virtualenv --no-site-packages --python=python2.7 ./.venvbootstrap
        # Set up paths to install/operate out of $WORKSPACE/.venvbootstrap
        source ./.venvbootstrap/bin/activate
        # N/B: local system's pip binary - uncontrolled version fixed below
        # pip may not support --cache-dir, force it's location into $WORKSPACE the ugly-way
        OLD_HOME="$HOME"
        export HOME="$WORKSPACE"
        pip install --force-reinstall --upgrade pip==9.0.1
        # Undo --cache-dir workaround
        export HOME="$OLD_HOME"
        # Install fixed, trusted, hashed versions of all requirements (including pip and virtualenv)
        pip --cache-dir="$PIPCACHE" install --force-reinstall --require-hashes \
            --requirement "$SCRIPT_DIR/requirements.txt"

        # Setup trusted virtualenv using hashed binary from requirements.txt
        ./.venvbootstrap/bin/virtualenv --no-site-packages --python=python2.7 ./.venv
        # Exit untrusted virtualenv
        deactivate
        # Remove temporary bootstrap virtualenv
        rm -rf ./.venvbootstrap
    fi
    # Enter trusted virtualenv
    source ./.venv/bin/activate
    # Upgrade stock-pip to support hashes
    ./.venv/bin/pip install --force-reinstall --cache-dir="$PIPCACHE" --upgrade pip==9.0.1
    # Re-install from cache but validate all hashes (including on pip itself)
    ./.venv/bin/pip --cache-dir="$PIPCACHE" install --require-hashes \
        --requirement "$SCRIPT_DIR/requirements.txt"
    [ -r "./.venv/.complete" ] || echo "Setup by: $@" > "./.venv/.complete"
) &>> "$LOGFP";

echo "Executing $@"
echo

# Enter trusted virtualenv in this shell
source $WORKSPACE/.venv/bin/activate
"$@"
deactivate  # just in case
