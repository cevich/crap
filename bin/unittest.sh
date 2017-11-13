#!/bin/bash

set -e

usage() {
    echo "This script is intended to be executed by .travis.sh"
    exit 1
}

ALINT="$(type -P ansible-lint)"
APB="$(type -P ansible-playbook)"

[ -n "$ARTIFACTS" ] || usage
[ -n "$ALINT" ] || usage
[ -n "$APB" ] || usage

set -e

echo "Running Python Unittests"
(cd tests && python3 -m unittest --failfast --buffer --verbose)

# TODO: Doesn't support action plugins?
#echo "Running Ansible Linter"
#$ALINT -v -x ANSIBLE0013,ANSIBLE0014 main.yml

echo "Running InvCache test playbook"
$APB -v .ic_action_test.yml

echo "Running Check-mode on main playbook"
$APB -v --check --verbose main.yml
