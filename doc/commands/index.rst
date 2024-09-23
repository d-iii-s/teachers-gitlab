Command reference manual
========================

Following commands are available (the list might be incomplete, run
``teachers-gitlab help`` for a full list of commands).

Templated parameters
--------------------

Some command line parameters accept a template value that is
really a Python format string. Where applicable, these template
arguments are evaluated for each user record, providing some
usage flexibility, especially when it comes to mass operations.

For example, using `--project student-{login}` in an action such
as **add-member** will perform the operation on multiple projects
corresponding to user login names.


``fork``
--------

Fork repository for all users given in a CSV file.

.. code-block:: shell

  teachers-gitlab fork \
    --config-file config.ini \
    --users students.csv \
    --from teaching/course/upstream/template \
    --to "teaching/course/student-{number}-{login}" \
    --hide-fork


will fork the `teaching/course/upstream/template` into
repositories `teaching/course/student-1-student1`
and `teaching/course/student-2-student2`, removing the
fork relationship.


``protect``
-----------

Create a protected branch (or pattern).

Assuming the same input files as in `fork`, the following command
protects `master` branch for all repositories from the previous
step but allows developers to push and merge

.. code-block:: shell

    teachers-gitlab protect \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
        --branch master \
        --merge-access-level developer \
        --push-access-level developer



``unprotect``
-------------

Remove a protected branch (or pattern).

Typically needed for the `master` branch in simple setups.

Assuming the same input files as in `fork`, the following command
unprotects `master` branch for all repositories from the previous
step.

.. code-block:: shell

    teachers-gitlab unprotect \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
        --branch master



``protect-tag``
---------------

Create a protected tag (or pattern).

Typically used for automatically created checkpoint tags.

.. code-block:: shell

    teachers-gitlab protect-tag \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi004/2022/student-{login}" \
        --tag 'checkpoint/*' \
        --create-access-level maintainer


``unprotect-tag``
-----------------

Remove a protected tag (or pattern).

.. code-block:: shell

    teachers-gitlab unprotect-tag \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi004/2022/student-{login}" \
        --tag 'checkpoint/*'



``add-member``
--------------

Add member(s) to project(s). Typically called after `fork` (see
above), but also to add students to shared projects.

Adding students to their course projects can be done with

.. code-block:: shell

    teachers-gitlab add-member \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
        --access-level developer


Adding students to a common project can be done with

.. code-block:: shell

    teachers-gitlab add-member \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi004/upstream/forum" \
        --access-level reporter


``remove-member``
-----------------

Remove member(s) from project(s). Typically used to remove
students from past course runs or students who have dropped out.

Removing students from a common project can be done with

.. code-block:: shell

    teachers-gitlab remove-member \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi004/2022/upstream/forum"


Removing students from their course projects can be done with

.. code-block:: shell

    teachers-gitlab remove-member \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi004/2022/student-{login}"



``clone``
---------

Clone project to local disk. It is possible to specify a deadline to
checkout to a specific commit (last before given deadline).

.. code-block:: shell

    teachers-gitlab clone \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
        --to "solutions/01-{number}-{login}" \
        --deadline '2020-01-01T00:00:00Z'



``deadline-commit``
-------------------

Get last commits before a given deadline.

By default, it generates a CSV with logins and commit ids.

.. code-block:: shell

    teachers-gitlab deadline-commit \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
        --deadline '2020-01-01T00:00:00Z' \
        --output commits_01.csv \
        --first-line 'login,number,commit' \
        --format '{login},{number},{commit.id}'


``get-file``
------------

Get specific file before a given deadline.

.. code-block:: shell

    teachers-gitlab get-file \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
        --deadline '2020-01-01T00:00:00Z' \
        --remote-file "quiz-01.json" \
        --local-file "quiz-01-{login}.json"



``get-last-pipeline``
---------------------

Get status of last pipeline as JSON.

.. code-block:: shell

    teachers-gitlab get-file \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2020-summer/solution-{number}-{login}"


.. code-block:: shell

    teachers-gitlab get-file \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
        --summary-only



``get-pipeline-at-commit``
--------------------------

Get status of the first non-skipped pipeline at or prior to specified commit as JSON.

.. code-block:: shell

    teachers-gitlab get-pipeline-at-commit \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2021-summer/student-{login}" \
        --commits "grading/results/commits.13.csv"



``commit-stats``
----------------

Overview of all commits, including line statistics, as JSON.

.. code-block:: shell

    teachers-gitlab commit-stats \
        --config-file config.ini \
        --users students.csv \
        --project "teaching/nswi177/2020-summer/solution-{number}-{login}"



``create-group``
----------------

Create a new group.

For example, if we assume our ``students.csv`` also contains information
about teachers, we can create a group for each teacher.

code-block:: text

    ukco,family_name,given_name,email,login,teacher_name,teacher_login
    123456,John,Doe,john@example.com,doejo,Alice,ta1
    123457,Jane,Doe,jane@example.com,doeja,Bob,ta2

Then the following will create groups ``courses/sw-eng/2024/ta1/``
(with name ``Alice``) and ``courses/sw-eng/2024/ta2/`` (named ``Bob``).

.. code-block:: shell

    teachers-gitlab create-group \
        --config-file config.ini \
        --users students.csv \
        --path "courses/sw-eng/2024/{teacher_login}" \
        --name "{teacher_name}"
