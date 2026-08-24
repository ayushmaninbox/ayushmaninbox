import datetime
from dateutil import relativedelta
import requests
import os
import sys
import subprocess
from lxml import etree
import time
import hashlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
import build_contrib

# Prefers a personal access token, falls back to the workflow's built-in GITHUB_TOKEN
# so a fresh clone runs with no secrets configured at all. The difference is coverage:
# GITHUB_TOKEN only sees public repositories, so commits and lines of code come out
# lower. For the full picture add an ACCESS_TOKEN secret -- a fine-grained token with
# All Repositories access and these read permissions:
#   Account:    Followers, Starring
#   Repository: Commit statuses, Contents, Metadata
TOKEN = os.environ.get('ACCESS_TOKEN') or os.environ.get('GITHUB_TOKEN')
if not TOKEN:
    raise SystemExit('Set ACCESS_TOKEN (or run inside Actions, which provides GITHUB_TOKEN)')
HEADERS = {'authorization': 'token ' + TOKEN}
USER_NAME = os.environ.get('USER_NAME') or os.environ.get('GITHUB_REPOSITORY_OWNER')
if not USER_NAME:
    raise SystemExit('Set USER_NAME to your GitHub login')
BIRTHDAY = datetime.datetime(2005, 9, 8)
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0,
               'recursive_loc': 0, 'graph_commits': 0, 'loc_query': 0,
               'repos_contributed_to': 0, 'contribution_calendar': 0}


def daily_readme(birthday):
    """
    Returns the length of time since I was born
    e.g. 'XX years, XX months, XX days'
    """
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return '{} {}, {} {}, {} {}{}'.format(
        diff.years, 'year' + format_plural(diff.years),
        diff.months, 'month' + format_plural(diff.months),
        diff.days, 'day' + format_plural(diff.days),
        ' 🎂' if (diff.months == 0 and diff.days == 0) else '')


def format_plural(unit):
    """
    Returns a properly formatted number
    e.g. 'day' + format_plural(diff.days) == 5 >>> '5 days'
    """
    return 's' if unit != 1 else ''


def simple_request(func_name, query, variables):
    """
    Returns a request, or raises an Exception if the response does not succeed.
    """
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=HEADERS)
    if request.status_code == 200:
        return request
    raise Exception(func_name, ' has failed with a', request.status_code, request.text, QUERY_COUNT)


def graph_commits(start_date, end_date):
    """
    Uses GitHub's GraphQL v4 API to return my total commit count
    """
    query_count('graph_commits')
    query = '''
    query($start_date: DateTime!, $end_date: DateTime!, $login: String!) {
        user(login: $login) {
            contributionsCollection(from: $start_date, to: $end_date) {
                contributionCalendar {
                    totalContributions
                }
            }
        }
    }'''
    variables = {'start_date': start_date, 'end_date': end_date, 'login': USER_NAME}
    request = simple_request(graph_commits.__name__, query, variables)
    return int(request.json()['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions'])


def graph_repos_stars(count_type, owner_affiliation, cursor=None, total_stars=0):
    """
    Uses GitHub's GraphQL v4 API to return my total repository or star count.
    Stars are paginated, because the star total is summed from the repository nodes
    themselves and a single page only carries the first 100 of them.
    """
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    page = request.json()['data']['user']['repositories']
    if count_type == 'repos':
        return page['totalCount']
    total_stars += stars_counter(page['edges'])
    if page['pageInfo']['hasNextPage']:
        return graph_repos_stars(count_type, owner_affiliation, page['pageInfo']['endCursor'], total_stars)
    return total_stars


def contribution_calendar():
    """
    Uses GitHub's GraphQL v4 API to return the last year of daily contribution counts,
    in the same week/weekday shape as GitHub's own contribution graph.
    """
    query_count('contribution_calendar')
    query = '''
    query($login: String!) {
        user(login: $login) {
            contributionsCollection {
                contributionCalendar {
                    weeks {
                        contributionDays {
                            date
                            contributionCount
                            weekday
                        }
                    }
                }
            }
        }
    }'''
    request = simple_request(contribution_calendar.__name__, query, {'login': USER_NAME})
    calendar = request.json()['data']['user']['contributionsCollection']['contributionCalendar']
    return calendar['weeks']


def repos_contributed_to():
    """
    Uses GitHub's GraphQL v4 API to return the number of repositories I have actually
    contributed to -- commits, pull requests, reviews, or having created the repo.

    This is deliberately not a count of repositories I merely have access to. Being
    added to an organisation grants affiliation with every repository it owns, so an
    affiliation count says how many repos I *could* push to, not how many I worked on.
    """
    query_count('repos_contributed_to')
    query = '''
    query($login: String!) {
        user(login: $login) {
            repositoriesContributedTo(
                first: 1,
                includeUserRepositories: true,
                contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW]
            ) {
                totalCount
            }
        }
    }'''
    request = simple_request(repos_contributed_to.__name__, query, {'login': USER_NAME})
    return int(request.json()['data']['user']['repositoriesContributedTo']['totalCount'])


def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    """
    Uses GitHub's GraphQL v4 API and cursor pagination to fetch 100 commits from a repository at a time
    """
    query_count('recursive_loc')
    query = '''
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }'''
    variables = {'repo_name': repo_name, 'owner': owner, 'cursor': cursor}
    # not simple_request(), because the cache file must be saved before raising
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=HEADERS)
    if request.status_code == 200:
        if request.json()['data']['repository']['defaultBranchRef'] != None:  # only count commits if repo isn't empty
            return loc_counter_one_repo(owner, repo_name, data, cache_comment, request.json()['data']['repository']['defaultBranchRef']['target']['history'], addition_total, deletion_total, my_commits)
        else:
            return 0
    force_close_file(data, cache_comment)  # saves what is currently in the file before this program crashes
    if request.status_code == 403:
        raise Exception('Too many requests in a short amount of time!\nYou\'ve hit the non-documented anti-abuse limit!')
    raise Exception('recursive_loc() has failed with a', request.status_code, request.text, QUERY_COUNT)


def loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits):
    """
    Recursively call recursive_loc (since GraphQL can only search 100 commits at a time)
    only adds the LOC value of commits authored by me
    """
    for node in history['edges']:
        if node['node']['author']['user'] == OWNER_ID:
            my_commits += 1
            addition_total += node['node']['additions']
            deletion_total += node['node']['deletions']

    if history['edges'] == [] or not history['pageInfo']['hasNextPage']:
        return addition_total, deletion_total, my_commits
    else:
        return recursive_loc(owner, repo_name, data, cache_comment, addition_total, deletion_total, my_commits, history['pageInfo']['endCursor'])


def loc_query(owner_affiliation, cursor=None, edges=None):
    """
    Uses GitHub's GraphQL v4 API to query all the repositories I have access to (with respect to owner_affiliation)
    Queries 60 repos at a time, because larger queries give a 502 timeout error and smaller queries send too many
    requests and also give a 502 error.
    Returns the list of repository edges the token can actually see.

    The default branch head OID comes back with each repo so that repositories holding
    the same history under two names can be collapsed later -- see dedupe_edges().
    """
    edges = [] if edges is None else edges
    query_count('loc_query')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges {
                node {
                    ... on Repository {
                        nameWithOwner
                        isFork
                        parent {
                            nameWithOwner
                        }
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    oid
                                    history {
                                        totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(loc_query.__name__, query, variables)
    page = request.json()['data']['user']['repositories']
    edges += visible_edges(page['edges'])
    if page['pageInfo']['hasNextPage']:                    # If repository data has another page
        return loc_query(owner_affiliation, page['pageInfo']['endCursor'], edges)
    return edges


def head_oid(node):
    """
    Returns the commit at the tip of a repository's default branch, or None if the
    repository is empty.
    """
    branch = node['defaultBranchRef']
    return branch['target']['oid'] if branch else None


def dedupe_edges(edges):
    """
    Collapses repositories that hold the same history under two different names.

    A fork that is level with its parent, or a repo that was pushed to a second remote,
    reports an identical default branch head from both sides. Walking both would count
    every one of those commits -- and every line they touched -- twice, so only one copy
    of each history is kept. The source repository wins over a fork of it, and ties fall
    back to the name that sorts first, so the choice does not flip between runs.

    Returns the surviving edges and a note for every history that was collapsed.
    """
    keep, notes = {}, []
    for edge in edges:
        node = edge['node']
        # an empty repo has no head to collide on, so key it by name and keep it as-is
        key = head_oid(node) or ('empty', node['nameWithOwner'])
        rival = keep.get(key)
        if rival is None:
            keep[key] = edge
            continue
        loser, winner = (rival, edge) if outranks(node, rival['node']) else (edge, rival)
        keep[key] = winner
        notes.append('deduped: {} holds the same history as {}, counted once'.format(
            loser['node']['nameWithOwner'], winner['node']['nameWithOwner']))
    return list(keep.values()), notes


def outranks(node, rival):
    """
    Decides which of two repositories sharing a history is the one worth keeping.
    A source repository beats a fork of it; otherwise the earlier name wins.
    """
    if node['isFork'] != rival['isFork']:
        return rival['isFork']
    return node['nameWithOwner'] < rival['nameWithOwner']


def warn_diverged_forks(edges):
    """
    Warns when a fork and its parent both survive deduplication.

    Their heads differ, so they are genuinely separate tips, but everything before the
    point they diverged is shared history that is now counted on both sides. There is no
    way to net that out without walking every commit id, so it is reported instead of
    silently folded into the totals.
    """
    names = {edge['node']['nameWithOwner'] for edge in edges}
    return ['warning: {} has diverged from {}, so commits they still share are counted twice'.format(
                edge['node']['nameWithOwner'], edge['node']['parent']['nameWithOwner'])
            for edge in edges
            if edge['node']['parent'] and edge['node']['parent']['nameWithOwner'] in names]


def visibility_guard(repo_count):
    """
    Refuses to publish numbers built from fewer repositories than a previous run saw.

    Every total on the card is only as complete as the token that gathered it. A token
    without access to an organisation does not error -- those repositories are simply
    absent from the response -- so the card would quietly redraw itself with a smaller,
    wrong commit count. Comparing against the high water mark turns that silent
    downgrade into a failed build. Set ALLOW_PARTIAL_DATA=1 to accept the lower number,
    which is the right call when repositories were genuinely deleted.
    """
    filename = 'cache/repo_baseline.txt'
    try:
        with open(filename, 'r') as f:
            baseline = int(f.read().split()[0])
    except (FileNotFoundError, IndexError, ValueError):
        baseline = 0
    if repo_count < baseline and not os.environ.get('ALLOW_PARTIAL_DATA'):
        raise SystemExit(
            f'\nThis run can see {repo_count} repositories, but an earlier run saw {baseline}.\n'
            f'The token is missing access to {baseline - repo_count} of them, so every total below\n'
            'would be undercounted. Give ACCESS_TOKEN access to the missing repositories, or set\n'
            'ALLOW_PARTIAL_DATA=1 if they were deleted on purpose.')
    if repo_count > baseline:
        with open(filename, 'w') as f:
            f.write(f'{repo_count}\n')


def cache_builder(edges, comment_size, force_cache=False, loc_add=0, loc_del=0):
    """
    Checks each repository in edges to see if it has been updated since the last time it was cached
    If it has, run recursive_loc on that repository to update the LOC count

    Cached rows are looked up by repository hash rather than by position, so a repository
    appearing, disappearing or simply coming back in a different order from the API can
    no longer shift every later row onto the wrong repository's numbers. Rows are then
    rewritten in the order the API returned, and any row whose repository is gone -- a
    duplicate history that was deduped away, or a repo that was deleted -- is dropped
    instead of being left behind to inflate the totals.
    """
    cached = True  # Assume all repositories are cached
    filename = 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.txt'  # Create a unique filename for each user
    try:
        with open(filename, 'r') as f:
            data = f.readlines()
    except FileNotFoundError:  # If the cache file doesn't exist, create it
        data = []
        if comment_size > 0:
            for _ in range(comment_size):
                data.append('This line is a comment block. Write whatever you want here.\n')
        with open(filename, 'w') as f:
            f.writelines(data)

    cache_comment = data[:comment_size]  # save the comment block
    cached_rows = {line.split()[0]: line for line in data[comment_size:] if line.split()}

    rows = []
    for edge in edges:
        node = edge['node']
        repo_hash = hashlib.sha256(node['nameWithOwner'].encode('utf-8')).hexdigest()
        if node['defaultBranchRef'] is None:  # If the repo is empty
            rows.append(repo_hash + ' 0 0 0 0\n')
            continue
        commit_count = node['defaultBranchRef']['target']['history']['totalCount']
        row = cached_rows.get(repo_hash)
        if row is not None and not force_cache and int(row.split()[1]) == commit_count:
            rows.append(row)  # commit count is unchanged, so the cached LOC still holds
            continue
        cached = False
        owner, repo_name = node['nameWithOwner'].split('/')
        loc = recursive_loc(owner, repo_name, rows, cache_comment)
        rows.append(f'{repo_hash} {commit_count} {loc[2]} {loc[0]} {loc[1]}\n')

    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(rows)
    for line in rows:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, cached]


def force_close_file(data, cache_comment):
    """
    Forces the file to close, preserving whatever data was written to it
    This is needed because if this function is called, the program would've crashed before the file is properly saved and closed
    """
    filename = 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.txt'
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)
    print('There was an error while writing to the cache file. The file,', filename, 'has had the partial data saved and closed.')


def visible_edges(edges):
    """
    Drop edges whose node came back null.
    The API does this for repositories the token cannot see (any private repo when
    running on GITHUB_TOKEN) and for ones deleted since the query was built.
    """
    return [edge for edge in edges if edge and edge.get('node')]


def stars_counter(data):
    """
    Count total stars in repositories owned by me
    """
    total_stars = 0
    for node in visible_edges(data):
        total_stars += node['node']['stargazers']['totalCount']
    return total_stars


def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, loc_data,
                   weeks):
    """
    Parse SVG files and update elements with my age, commits, stars, repositories, and lines written
    """
    tree = etree.parse(filename)
    root = tree.getroot()
    justify_format(root, 'age_data', age_data, 53)
    justify_format(root, 'commit_data', commit_data, 25)
    justify_format(root, 'star_data', star_data, 15)
    justify_format(root, 'repo_data', repo_data, 10)
    justify_format(root, 'contrib_data', contrib_data)
    justify_format(root, 'follower_data', follower_data, 12)
    justify_format(root, 'loc_data', loc_data[2], 11)
    justify_format(root, 'loc_add', loc_data[0])
    justify_format(root, 'loc_del', loc_data[1], 7)
    widget_overwrite(root, filename, weeks)
    tree.write(filename, encoding='utf-8', xml_declaration=True)


def working_tree_dirty():
    """
    True if committing right now would actually produce a commit. Used to decide
    whether to count today's not-yet-made commit in the contribution widget below --
    the calendar is fetched before that commit exists, so without this the widget is
    permanently one contribution behind on any run that changes something.
    """
    return subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--']).returncode != 0


def widget_overwrite(root, filename, weeks):
    """
    Rebuilds the activity widget (isometric contribution chart + streak stats) from
    scratch each run -- unlike the text fields above, its geometry depends on live
    data, so it can't be patched in place the same way.
    """
    target = root.find(".//*[@id='activity_widget']")
    if target is None:
        return
    for child in list(target):
        target.remove(child)
    card_width = float(root.get('width').replace('px', ''))
    theme = build_contrib.WIDGET_THEMES[filename]
    fragment = build_contrib.render_widget(theme, card_width, weeks)
    target.append(etree.fromstring(fragment))


def justify_format(root, element_id, new_text, length=0):
    """
    Updates and formats the text of the element, and modifes the amount of dots in the previous element to justify the new text on the svg
    """
    if isinstance(new_text, int):
        new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_map = {0: '', 1: ' ', 2: '. '}
        dot_string = dot_map[just_len]
    else:
        dot_string = ' ' + ('.' * just_len) + ' '
    find_and_replace(root, f"{element_id}_dots", dot_string)


def find_and_replace(root, element_id, new_text):
    """
    Finds the element in the SVG file and replaces its text with a new value
    """
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def commit_counter(comment_size):
    """
    Counts up my total commits, using the cache file created by cache_builder.
    """
    total_commits = 0
    filename = 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.txt'
    with open(filename, 'r') as f:
        data = f.readlines()
    cache_comment = data[:comment_size]  # save the comment block
    data = data[comment_size:]  # remove those lines
    for line in data:
        total_commits += int(line.split()[2])
    return total_commits


def user_getter(username):
    """
    Returns the account ID and creation time of the user
    """
    query_count('user_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            id
            createdAt
        }
    }'''
    variables = {'login': username}
    request = simple_request(user_getter.__name__, query, variables)
    return {'id': request.json()['data']['user']['id']}, request.json()['data']['user']['createdAt']


def follower_getter(username):
    """
    Returns the number of followers of the user
    """
    query_count('follower_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }'''
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])


def query_count(funct_id):
    """
    Counts how many times the GitHub GraphQL API is called
    """
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    """
    Calculates the time it takes for a function to run
    """
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def formatter(query_type, difference, funct_return=False, whitespace=0):
    """
    Prints a formatted time differential
    """
    print('{:<23}'.format('   ' + query_type + ':'), sep='', end='')
    print('{:>12}'.format('%.4f' % difference + ' s ')) if difference > 1 else print('{:>12}'.format('%.4f' % (difference * 1000) + ' ms'))
    if whitespace:
        return f"{'{:,}'.format(funct_return): <{whitespace}}"
    return funct_return


if __name__ == '__main__':
    print('Calculation times:')
    # define global variable for owner ID and calculate user's creation date
    user_data, user_time = perf_counter(user_getter, USER_NAME)
    OWNER_ID, acc_date = user_data
    formatter('account data', user_time)
    age_data, age_time = perf_counter(daily_readme, BIRTHDAY)
    formatter('age calculation', age_time)
    edges, edge_time = perf_counter(loc_query, ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    formatter('repository list', edge_time)
    visibility_guard(len(edges))
    edges, notes = dedupe_edges(edges)
    notes += warn_diverged_forks(edges)
    total_loc, loc_time = perf_counter(cache_builder, edges, 7)
    formatter('LOC (cached)', loc_time) if total_loc[-1] else formatter('LOC (no cache)', loc_time)
    commit_data, commit_time = perf_counter(commit_counter, 7)
    star_data, star_time = perf_counter(graph_repos_stars, 'stars', ['OWNER'])
    repo_data, repo_time = perf_counter(graph_repos_stars, 'repos', ['OWNER'])
    contrib_data, contrib_time = perf_counter(repos_contributed_to)
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)
    weeks, weeks_time = perf_counter(contribution_calendar)

    for index in range(len(total_loc) - 1):
        total_loc[index] = '{:,}'.format(total_loc[index])  # format added, deleted, and total LOC

    svg_overwrite('dark_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1], weeks)
    svg_overwrite('light_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1], weeks)

    # The commit above hasn't happened yet when contribution_calendar() ran, so if this
    # run is about to make one, it's a contribution the widget just rendered without --
    # count it and re-render so the totals are accurate the moment the commit lands.
    if working_tree_dirty():
        weeks[-1]['contributionDays'][-1]['contributionCount'] += 1
        svg_overwrite('dark_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1], weeks)
        svg_overwrite('light_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1], weeks)

    print('\033[F\033[F\033[F\033[F\033[F\033[F\033[F\033[F',
          '{:<21}'.format('Total function time:'), '{:>11}'.format('%.4f' % (user_time + age_time + edge_time + loc_time + commit_time + star_time + repo_time + contrib_time)),
          ' s \033[E\033[E\033[E\033[E\033[E\033[E\033[E\033[E', sep='')

    print('Total GitHub GraphQL API calls:', '{:>3}'.format(sum(QUERY_COUNT.values())))
    print('Repositories:', '{:>19}'.format(f'{len(edges)} counted'))
    for note in notes:
        print('  ', note)
