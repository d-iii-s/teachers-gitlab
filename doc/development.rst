Development manual
==================

For development we recommend to work in a virtual environment and install
pinned versions of the dependencies.

.. code-block:: shell

    python3 -m venv venv
    . ./venv/bin/activate
    pip install -r requirements.txt
    pip install -e .


Writing unit tests
------------------

Most tests are currently written in Pytest and they mock GitLab API responses.
Thus the ``python-gitlab`` library believes it is talking to a real server
while the test mock only the responses to requests we expect.

Writing a test is a bit of trial-and-error to determine what API is actually
needed to mock but then the mock setup is rather straightforward.

Let us examine how to implement a test for the ``add-member`` subcommand.

In the test we need to call the following function

.. code-block:: python

    action_add_member(
        gitlab_instance,
        logger,
        entries_iterable,
        name_of_login_column,
        dry_run,
        project_name_template,
        access_level
    )

This function is heavily annotated so that we can build the command-line
parser automatically but for writing test we call it as any other function.

We start the test with the following code. The ``mock_gitlab`` fixture is
provided in ``conftest.py`` and simplifies mocking of the GitLab API
(it is a thin wrapper on top of ``responses`` library that we use).

.. code-block:: python

    def test_add_member(mock_gitlab):
        mock_gitlab.report_unknown()

        teachers_gitlab.main.action_add_member(
            mock_gitlab.get_python_gitlab(),
            logging.getLogger("add-member"),
            teachers_gitlab.main.ActionEntries([
                {'login': 'alpha'},
            ]),
            'login',
            False,
            'base/{login}',
            gitlab.const.AccessLevel.DEVELOPER
        )

The call to ``report_unknown`` registers a catch-all callback that will report
any calls to GitLab API that are not mocked by the test. At this moment, this
will report *all* calls (that is fine for now).

Note that the tests will fail if you do not call ``report_unknown`` by yourself
explicitly -- otherwise unknown calls would be silently ignored and the test
would not be testing anything (unfortunately, the API does allow us to call
``report_unknown`` only *after* all callbacks are registered and hence we
need to add the call manually everywhere).

And then we call the actual function that we want to test. We try to add user
``alpha`` to project ``base/alpha`` with access level *developer*.

When we run it the test fails with the following:

.. code-block:: text

    Exception: Following URLs were not mocked: GET http://localhost/api/v4/projects/base%2Falpha

At this point we need to consult
`GitLab API documentation <https://docs.gitlab.com/ee/api/rest>`_ to see what
API was actually called.

In this case it is easy: the utility first needs to determine that the project
exist and it also converts the project path to project (numerical) id.

These calls are very common and hence our fixture contains the following
API to respond to such calls.

.. code-block:: python

    # Project 'base/alpha' has id 452 and it is a normal project
    # (normal: it exists and we can access it)
    mock_gitlab.register_project(452, 'base/alpha')

    mock_gitlab.report_unknown()

    ...

We can now run the test again. Not surprisingly, it fails again because
another URL is not mocked.

.. code-block:: text

    Exception: Following URLs were not mocked: GET http://localhost/api/v4/users?username=alpha

This means that before adding the user the library needs to determine if the
user is actually valid. No surprise.

We need to mock this call too.

For this the fixture does not have any special call but it provides the
function ``on_api_get`` to specify a JSON response for a particular HTTP
request.

.. warning::
   The URLs are compared as plain strings without any kind of normalization.
   Therefore, URLs ``project/42`` and ``project//42`` are different even if
   they would be treated as the same by a real GitLab server.


.. code-block:: python

    mock_gitlab.on_api_get(
        'users?username=alpha',
        response_json=[
            {
                'id': 5,
                'username': 'alpha',
            }
        ]
    )

The returned JSON is actually a very simplified structure that actual GitLab
would return. But that is completely okay for the tests as we will not need
other items anyway. The important bit is the numerical id of the user.

Running the test again will fail with the following exception:

.. code-block:: text

    Exception: Following URLs were not mocked: GET http://localhost/api/v4/projects/452/members/5, POST http://localhost/api/v4/projects/452/members.

Even without consulting the online documentation we can conclude that the
library is trying to get a list of (existing) project members and then
the ``POST`` call is updating the list.

We need to mock these calls too.

...

Note that the test we have written is not robust against changes in the
underlying library (``python-gitlab``) and relies on many implementation
details of the application. That is balanced by the fact that creating the
test is relatively easy and that the execution of the test is superfast.
The only other option is to setup a whole GitLab instance and test against
it (i.e. reset the database, create the users and projects, call our
application and then through other means check that the users can access
the projects etc.). That is extremely complex to automate and is also very
resource heavy.
