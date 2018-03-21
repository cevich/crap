==========================================
CRAP: It's crass, ridiculous, and profound
==========================================

C'mon, it's an open-source project, you weren't looking for documentation were you?

This repo. contains a starting-point for learning the power of the force^H^H^H^HAnsible.

It was created for a workshop targed at Red Hat Quality-assurance engineering. `The
slide-deck <https://github.com/cevich/crap/raw/master/CRAP.pdf>`_ is intended for
those already moderately familiar with Ansible.  Otherwise if you're
a total noob, the following minimum prerequisites are recommended:

*  Watch from 3:24 - 10:33 - https://www.ansible.com/quick-start-video?wvideo=qrqfj371b6
*  Grok - http://docs.ansible.com/ansible/latest/playbooks_reuse_roles.html
*  Skim - http://docs.ansible.com/ansible/latest/playbooks_variables.html#variables
*  Skim - http://docs.ansible.com/ansible/latest/playbooks_templating.html#templating-jinja2

Note:
    If you wish to actually understand most of the crap here, you'll probably want
    to grok all of those instead of skim.  Beyond that, playtime will be the best
    teacher:  Attempt the exercises at the end of
    `the slides <https://github.com/cevich/crap/raw/master/CRAP.pdf>`_.

-------------
Overview
-------------

With the above committed to memory, and an understanding that playbooks and
inventory are the primary *inputs*. You'll understand the included roles and
example playbook interactions with inventory state.  These are the most important
concepts:

* ``inventory/invcache.py`` - Simple script that manages **a** static inventory state.
  Does not preclude or assume existence of any other inventory files or scripts.
  Does not interfere or modify any other inventory state.  Properly handles
  concurrent access with proper read/write locking.

* ``action_plugins/ic_{add,delete,update,reset}.py`` - Ansible modules that allow safe,
  **declarative** specification of inventory state (by ``invcache.py``).
  Usage is optional, but required to support the next two items.

* ``*bin/*`` - Any simple executables/scripts that provision and/or teardown
  playbook subject hosts.  The only requirement is they emit a ``JSON`` dictionary
  on stdout, containing Ansible variables for the host (e.g. ``ansible_connection``,
  ``ansible_host``, etc.).

* ``inventory/*`` - Static inventory entries which specify any of four optional facts
  (directly, or by group-membership) for a subject host:

    * ``creation_command``: Input parameters to the Ansible ``shell`` module.  Target
      command is expected to support the ``*bin/*`` interface - item above.

    * ``destruction_command``: Same as the above, opposite in purpose.

    * ``creation_destruction_environment``: Optional map of environment variables to set for
      the above two items (optional).

    * ``creation_destruction_asserts``: Optional list of Ansible assertion strings, to
      help verify all the above adhere to explicit expectations.


------------------
Functional Basics
------------------

Acting on the four variables mentioned above, several roles are needed to support
the two most common "styles" of subject host management:

* **Singular**:  The simplest, "run a command, get a host".  For example, ``qemu-kvm``.
  This style cooresponds to the ``created`` and ``destroyed`` roles.

* **Plural**: Basically a repeated application of **singular**, "run a command, get a list of
  hosts".  For example ``linchpin up`` (http://linchpin.readthedocs.io/en/develop/index.html).
  The ``collective_created`` and ``collective_destroyed`` roles support this style.

-----------------
Play Requirements
-----------------

This one's easy.  Any inventory and host declarations must be separate from other
subject plays.  For example, see the two plays in the ``creation.yml`` playbook:
The first one establishes the inventory, second one starts managing the hosts.  Do
not cross those two streams, don't do it!

Explanation:  It's bad to tangle the two, for (non-obvious) Ansible-implementation,
"gotcha" reasons:

* The ``add_host`` module cannot run in parallel across multiple hosts because of
  a hack which allows it to behave impericly.  In other words, it's there to support
  an **anti-pattern** of the normal declarative-style Ansible instructions.  It's evil,
  don't use it!

* Inventory, facts, and variables, 'conditions' and 'loops' are all tied-at-the-waste
  to the complete set of a play's tasks.  This means if any of those change (internal)
  state part-way through a play's tasks, you're likely trying to shoe-horn imperitive-style
  programming, into Ansible's declarative syntax.  Ansible + Imperitives == Only Pain.


CI Status: |ci_status|

.. |ci_status| image:: https://travis-ci.org/cevich/crap.svg?branch=master
               :target: https://travis-ci.org/cevich/crap
