Getting list of students
========================

.. warning::
   The following works only for schools using SIS such as Charles University.

A list of students including their logins (which are good unique identifiers)
can be generated from `SIS <https://is.cuni.cz/studium/>`_
using the query *Studenti předběžně zapsaní na předmět* from
*Statistical reports* (*Studijní sestavy*) module
(there are multiple versions, we recommend post processing the CSV
to fit into your other tools).

The CSV has the following format (and it is a truly valid CSV unlike several
others produced by SIS).

.. code-block:: text

    ukco,family_name,given_name,email,branch,year,enroll_type,completed,login,schedule
    123456,John,Doe,john@example.com,IPA,1,final,no,doejo,23bNSWI177p2:23bNSWI177x01
    123457,Jane,Doe,jane@example.com,IPP,1,final,no,doeja,23bNSWI177p2:23bNSWI177x01

Note that `teachers-gitlab` expects the file in native encoding of your OS.
For GNU/Linux it will be typically UTF-8, on Windows it might be some of the WIN-12XX.
