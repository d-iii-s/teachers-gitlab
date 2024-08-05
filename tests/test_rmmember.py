import logging

import teachers_gitlab.main as tg

def test_remove_member(mock_gitlab):
    entries = [
        {'login': 'alpha'},
    ]

    mock_gitlab.register_project(42, 'student/alpha', members =
    [
    {
        "id": 2157753,
        "username": "mario",
        "name": "xxx",
        "state": "active",
        "web_url": "https://gitlab.com/mario",
        "access_level": 50,
        "membership_state": "active"
    },
    {
        "id": 834534,
        "username": "sonic",
        "name": "xxx",
        "state": "active",
        "web_url": "https://gitlab.com/sonic",
        "access_level": 50,
        "membership_state": "active"
    }
])

    tg.action_remove_member(
        mock_gitlab.get_python_gitlab(),
        logging.getLogger("removemember"),
        tg.ActionEntries(entries),
        1,
        True,
        'student/{login}',
    )
