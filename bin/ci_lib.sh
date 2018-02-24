

# Intended for use by various CI testing scripts, should not be used otherwise.

if [[ -z "$WORKSPACE" ]] || [[ ! -d "$WORKSPACE" ]]
then
    WORKSPACE="$(mktemp -p '' -d $(basename $0)_XXXXXXXX)"
    trap 'sudo rm -rf "'$WORKSPACE'"' EXIT
fi
