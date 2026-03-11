Teachers GitLab
===============

A Python utility to help you manage multiple repositories at once.

Our target users are teachers that need to manage separate repository for
each student and massively fork, clone or upload files in all projects
at once.

The project is developed at the
`Department of Distributed and Dependable Systems <https://d3s.mff.cuni.cz>`_
at Charles University in Prague.

.. warning::
   This documentation is still work-in-progress and some information is
   available only in the main README.md file.

Our typical scenario
--------------------

The following scenario is something we have faced in many of our courses.

For each student we needed to create their own Git project (repository) where
they will submit their assignments for a particular course.
Usually, we needed to setup the repository to our needs and
perform other configuration steps for each student.

For a few students, it was relatively easy to do so manually. But with tens
(or even hundreds) of students some kind of automation was needed.

That is where this utility comes in handy.

We start with the following CSV (call it ``students.csv``) file with the
basic information.

.. code-block:: text

    name,login,group
    Harry,harry,gryff
    Hermiona,herm,gryff
    Draco,draco,slyth
    ...

Then we can execute the following to fork our base project (that may
contain assignment description and project configuration with some tests,
for example) for all students.

.. code-block:: shell

    teachers-gitlab \
        fork \
        --entries students.csv \
        --from 'courses/software-magic/base' \
        --to 'courses/software-magic/students/{group}/{login}' \

Once this program finishes, there will be forked projects ``gryff/harry``,
``gryff/herm`` and ``slyth/draco``.

Typically we will then assign students to their projects and we are ready
to go.

.. code-block:: shell

    teachers-gitlab \
        add-member \
        --entries students.csv \
        --project 'courses/software-magic/students/{group}/{login}' \
        --access-level devel

A new student enrolled? We simply run the above commands again:
existing projects will be skipped and only new members will be added.

Need help?
----------

Please, open an issue or start a discussion at our
`GitHub repository <https://github.com/d-iii-s/teachers-gitlab>`_.
Matfyz members can create issues on
`our GitLab as well <https://gitlab.mff.cuni.cz/teaching/utils/teachers-gitlab>`_.

We also welcome suggestions for new functions. Patches and merge requests
with new functions are welcomed even more :-).


Further reading
---------------

.. toctree::
   :maxdepth: 2

   install
   first-steps
   commands/index
   how-to/index
   development
