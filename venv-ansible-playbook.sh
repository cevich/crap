#!/bin/bash

# This wrapper-script reduces the number of dependencies needed on the control-machine
# and always executes from a fixed-version / verified environment.  In addition to
# the requirements for whichever ``cloud_group`` is used (docker by default), this
# script only requires:
#
#    python2-virtualenv gcc openssl-devel redhat-rpm-config
#
# Example usage
#   $ ./venv-ansible-playbook.sh \
#               --check \
#               /path/to/crap/main.yml

# All errors are fatal
set -e

SCRIPT_NAME=$(basename "$0")
WORKSPACE=`realpath $(dirname "$0")`
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
    echo "No ansible-playbook command-line options specified."
    echo "usage: $0 -i whatever --private-key=something --extra-vars foo=bar playbook.yml"
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
    if [ ! -d "./.venv" ] || [ ! -e "./.venv/bin/pip" ]; then
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
        pip --cache-dir="$PIPCACHE" install --require-hashes \
            --requirement "$WORKSPACE/requirements.txt"

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
        --requirement "$WORKSPACE/requirements.txt"
) &> "$LOGFP";

echo "Executing \"$WORKSPACE/.venv/bin/ansible-playbook $@\""
echo

# Enter trusted virtualenv in this shell
source $WORKSPACE/.venv/bin/activate
ansible-playbook $@
deactivate  # just in case
