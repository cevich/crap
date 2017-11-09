#!/bin/bash

set -e

usage() {
    echo "This script requires the following (or equivilent) packages are needed:"
    echo
    echo "python2-virtualenv gcc openssl-devel redhat-rpm-config libffi-devel"
    echo "python-devel libselinux-python rsync yum-utils python3-pycurl python-simplejson"
    echo
    echo "It is intended to be executed as an argument to venv-cmd.sh"
    exit 1
}

ALINT="$(type -P ansible-lint)"
APB="$(type -P ansible-playbook)"

[ -n "$ALINT" ] || usage
[ -n "$APB" ] || usage

set -e

(cd tests && python3 -m unittest --failfast --buffer --verbose)

$ALINT main.yml

$APB --check --verbose main.yml
