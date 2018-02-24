#!/bin/bash

set -e

echo "Running InvCache test playbook"
ansible-playbook --verbose ./.ic_action_test.yml

echo "Running Check-mode on main playbook"
ansible-playbook --check --verbose ./main.yml
