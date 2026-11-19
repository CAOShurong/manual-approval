"""Drive only the synthetic issues created by this QA workflow attempt."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from time import monotonic, sleep
from urllib.request import Request, urlopen


REPOSITORY = os.environ['GITHUB_REPOSITORY']
assert REPOSITORY == 'CAOShurong/manual-approval'
RUN_ID = int(os.environ['GITHUB_RUN_ID'])
RUN_ATTEMPT = int(os.environ['GITHUB_RUN_ATTEMPT'])
RUN_URL = f'https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}'
BASE = f'https://api.github.com/repos/{REPOSITORY}/issues'
BOT = 'github-actions[bot]'
TOKEN = os.environ['QA_TOKEN']


def api(suffix='', payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(BASE + suffix, data=data, headers={
        'Authorization': f'Bearer {TOKEN}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'manual-approval-234-qa',
    })
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def wait_for_issue(title):
    deadline = monotonic() + 360
    while monotonic() < deadline:
        issues = api('?state=open&sort=created&direction=desc&per_page=100')
        matches = [
            i for i in issues if i['title'] == title and i['user']['login'] == BOT
            and RUN_URL in (i['body'] or '') and 'pull_request' not in i
        ]
        if matches:
            assert len(matches) == 1, f'duplicate QA issue title: {title}'
            return matches[0]['number']
        sleep(5)
    raise TimeoutError(f'QA issue did not appear: {title}')


def drive_case(case):
    reason_mode, decision = case
    title = f'MA-234 QA {RUN_ID}/{RUN_ATTEMPT} reasons-{reason_mode}-{decision}'
    number = wait_for_issue(title)
    path = f'/{number}'
    word = 'approved' if decision == 'approval' else 'denied'
    other = 'denied' if word == 'approved' else 'approved'
    # The second line deliberately contains the opposite keyword.
    comment = api(path + '/comments', {'body': f'{word}\n{other}'})
    assert comment['user']['login'] == BOT
    if reason_mode == 'disabled':
        sleep(22)
        assert api(path)['state'] == 'open', f'{title}: multiline comment closed the issue'
        comment = api(path + '/comments', {'body': word})
        assert comment['user']['login'] == BOT
    deadline = monotonic() + 60
    while monotonic() < deadline:
        issue = api(path)
        if issue['state'] == 'closed':
            terminal = ('has been met' if word == 'approved' else 'Request denied.')
            comments = api(path + '/comments?per_page=100')
            assert any(c['user']['login'] == BOT and terminal in c['body']
                       for c in comments), f'{title}: terminal comment missing'
            print(json.dumps({'case': title, 'issue': issue['html_url'],
                              'multiline_ignored': reason_mode == 'disabled',
                              'terminal_state': word}), flush=True)
            return
        sleep(3)
    raise TimeoutError(f'{title}: expected issue closure')


if __name__ == '__main__':
    cases = [(mode, decision) for mode in ('enabled', 'disabled')
             for decision in ('approval', 'denial')]
    with ThreadPoolExecutor(max_workers=len(cases)) as executor:
        list(executor.map(drive_case, cases))
