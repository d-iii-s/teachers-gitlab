Structuring your GitLab projects
================================

The following structure of students (and ours) repositories works for us
so feel free to use it as an inspiration.

The whole structure is teacher-centric: the students see their project rather
deeply nested but they can always pin the project to their dashboard and it
does not require any synchronization between teachers of different courses.

The projects are first divided by courses, each course has its own subgroup
under `/teaching/course-unique-code`.

Each semester then has its own group, we often name it by year only.

Our repositories (with slides, for example) are usually grouped under
infrastructure subgroup that is not part of any semestral group as these
repositories usually work across multiple years.

The important part is to have unique naming for student repositories.
We use their login into the Central system to get the unique name, basing
the repository on their real name is possible but can lead to conflicts.

We usually have an extra repository with examples that we also place into
the group for a particular semester.

The student repositories with their submissions can start as empty projects
(the script does not support that directly yet) but we often publish
assignments through changes in a base repository that the students need to
merge into their own projects. Therefore we usually create a common parent
project and *fork* student repositories from that one.

A GitLab limitation when forking a project is that the forked project cannot
be in the same group (namespace) as the target. So it is not possible to fork
from `/teaching/nswi177/base` to `/teaching/nswi177/student-john-doe`.

So in the end the structure for each of our courses looks like this.

``/teaching/COURSE``
   Top level group for each course.

   We keep this group usually public.

``/teaching/COURSE/20XX``
   Group for a particular semester.

   We usually have this group public too.

``/teaching/COURSE/20XX/student-LOGIN``
   Main project for each student.

   If there are multiple projects for each student, we usually prefix them
   with task name, such as `t1-LOGIN` or `t2-LOGIN`.

   These projects are private and hence not visible to anybody who is not
   explicitly assigned to them.

``/teaching/COURSE/20XX/common``
   A namespace with shared repositories visible for all students.

``/teaching/COURSE/20XX/common/student``
   The base project that we fork for each student.

   We often keep this project public (or visible for any logged in user) as
   the students might need to merge from it. Adding all students to it is also
   possible.

   Note that forking a public project creates a public fork
   (see `project-settings` command to change that).

``/teaching/COURSE/20XX/common/examples``
   Whatever other project we need is placed into the ``common`` namespace.

``/teaching/COURSE/infra/``
   A common namespace for our repositories, visible only to the teachers.

If your teaching assistants prefer to organize the projects differently, the
setup of ``/teaching/COURSE/20XX/TEACHER/student-LOGIN`` is also possible
and easy to do with our scripts.
