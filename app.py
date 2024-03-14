from logging.config import dictConfig

import datetime
import os
from typing import Dict, TypedDict

from dotenv import load_dotenv
from flask import Flask, request, abort

from github import Auth, GithubIntegration, UnknownObjectException

# CONFIGURE THE ENVIRONMENT

# Load all env variables
load_dotenv()

# Configure logging
log_level = os.getenv('LOG_LEVEL', 'INFO')
dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://flask.logging.wsgi_errors_stream',
        'formatter': 'default'
    }},
    'root': {
        'level': log_level,
        'handlers': ['wsgi']
    }
})

# Load application configs
github_app_id = os.getenv("GH_APP_ID")
github_app_private_key = os.getenv("GH_APP_PRIVATE_KEY")
endpoint_secret = os.getenv("INCOMING_SECRET")
debug_mode = os.getenv("DEBUG_MODE", "False").lower() == "true"

github_commit_branch_tpl = os.getenv("GH_COMMIT_BRANCH_TEMPLATE", "%timestamp%_%vocabulary_name%")
github_commit_message_tpl = os.getenv("GH_COMMIT_MESSAGE_TEMPLATE", "Commit into %vocabulary_name% vocabulary")
github_pr_title_tpl = os.getenv("GH_PULL_REQUEST_TITLE_TEMPLATE", "Release: %date% - %vocabulary_name%")
github_pr_desc_tpl = os.getenv("GH_PULL_REQUEST_DESCRIPTION_TEMPLATE", "Description of the release")

# CONFIGURE THE APPLICATION

app = Flask(__name__)

if not (github_app_id and github_app_private_key and endpoint_secret):
    raise ValueError("Missing configurations. "
                     "Make sure to set GH_APP_ID, GH_APP_PRIVATE_KEY, and INCOMING_SECRET as "
                     "environment variables.")


class UploadFileResponse(TypedDict):
    success: bool
    original_filename: str
    repo_full_name: str
    pull_request_branch: str
    pushed_filename: str
    pull_request_url: str
    msg: str


def create_response(filename, gh_filename, repo, branch, pull_request_url) -> UploadFileResponse:
    """
    Creates the UploadFileResponse to be returned by upload_file
    :param filename: The name of the file sent with request
    :param gh_filename: The name of the file created on github
    :param repo: The full name of the repository used for PR
    :param branch: The branch created for the PR in github
    :param pull_request_url: The URL of the pull request on github
    :return:
    """
    return {
        'success': True,
        'original_filename': filename,
        'repo_full_name': repo,
        'pull_request_branch': branch,
        'pushed_filename': gh_filename,
        'pull_request_url': pull_request_url,
        'msg': (f'{filename} is correctly committed as {gh_filename} to github repository on branch {branch}. '
                f'See PR at {pull_request_url}')
    }


@app.route('/upload', methods=['POST'])
def upload_file() -> UploadFileResponse:
    """
    Uploads a vocabulary file to GitHub. Only POST requests are accepted.

    Authorization:
    - Bearer authorization token as configured into env variables

    Query parameters:
    - vocabulary_name: the name of the vocabulary
    - repo_full_name: the full name of the GitHub repo where the vocabulary will be published

    :rtype: str
    :return:
    """
    date = datetime.datetime.now()

    tid = date.strftime('[%s] ')
    app.logger.info(tid + "Requested file upload")

    app.logger.debug(tid + "The request content type is: " + request.content_type)
    app.logger.debug(tid + "The request contains the following headers: " + str(list(request.headers.keys())))
    app.logger.debug(tid + "The request contains the following args: " + str(list(request.args.keys())))
    app.logger.debug(tid + "The request contains the following files: " + str(list(request.files.keys())))

    # Authenticate using the provided token
    provided_secret = request.headers.get('Authorization')
    if not provided_secret or provided_secret != f"Bearer {endpoint_secret}":
        app.logger.error(tid + "Aborted 401 - Invalid authorization token")
        abort(401, 'Invalid authorization token.')

    args = request.args

    vocabulary_name = args.get('vocabulary_name')
    if vocabulary_name is None:
        app.logger.error(tid + "Aborted 400 - \'vocabulary_name\' query parameter not found")
        abort(400, 'Please provide \'vocabulary_name\' query parameter.')

    repo_full_name = args.get('repo_full_name')
    if vocabulary_name is None:
        app.logger.error(tid + "Aborted 400 - \'repo_full_name\' query parameter not found")
        abort(400, 'Please provide \'repo_full_name\' query parameter.')

    # Receive the file from the client as a stream
    if 'file' in request.files:
        app.logger.info(tid + "Read RDF\\XML from file content")
        file_stream = request.files['file'].stream
        file_name = request.files['file'].filename
        if not file_stream:
            app.logger.error(tid + "Aborted 400 - \'file\' attachment not a filestream")
            abort(400, 'Please provide a valid \'file\' attachment in RDF\\XML format.')
    else:
        app.logger.info(tid + "Read RDF\\XML from body stream")
        file_stream = request.stream
        file_name = vocabulary_name+".rdf"

    app.logger.info(tid + f"{file_name} will be pushed into {repo_full_name} for vocabulary {vocabulary_name}")

    # Commit the file to GitHub
    res = publish_file_to_github(file_stream, file_name, vocabulary_name, repo_full_name, date)

    gh_filename = res['filename']
    gh_repo = res['repository']
    gh_branch = res['branch']
    gh_pull_request_url = res['pr_url']

    success_msg: UploadFileResponse = create_response(file_name, gh_filename, gh_repo, gh_branch, gh_pull_request_url)
    app.logger.info(tid + success_msg['msg'])

    return success_msg


def publish_file_to_github(file_stream, file_name, vocabulary_name, repo_full_name, date) -> Dict[str, str]:
    """
    Publish a file_stream to GitHub
    :param file_stream: the file_stream of file to be published
    :param file_name: the file name on GitHub
    :param vocabulary_name: the vocabulary name
    :param repo_full_name: the full name of the repository
    :param date: the date of POST request
    :return:
    """
    res = {}

    tid = date.strftime('[%s] ')
    app.logger.info(tid + f"Processing publication of {file_name} for {vocabulary_name} into {repo_full_name}")

    try:

        res['repository'] = repo_full_name
        res['filename'] = file_name
        res['branch'] = github_commit_branch_tpl
        res['commit_msg'] = github_commit_message_tpl
        res['pr_title'] = github_pr_title_tpl
        res['pr_description'] = github_pr_desc_tpl
        res['pr_url'] = ""

        for x in res:
            res[x] = (res[x].replace('%vocabulary_name%', vocabulary_name)
                      .replace('%timestamp%', date.strftime('%Y%m%d%H%M'))
                      .replace('%datetime%', date.strftime('%d/%m/%Y %H:%M'))
                      .replace('%date%', date.strftime('%d/%m/%Y')))

        app.logger.info(tid + "Getting connection to github app")
        auth = Auth.AppAuth(github_app_id, github_app_private_key)
        github_integration = GithubIntegration(auth=auth)

        app.logger.info(tid + "Searching the correct repository")
        repo = None
        for installation in github_integration.get_installations():
            for repo in installation.get_repos():
                if repo.full_name == res['repository']:
                    repo = repo

        if repo is None:
            app.logger.error(tid + f"Aborted 401 - Not found authorization for repository: {res['repository']}")
            abort(401, "Not authorized to requested repository")
        # github_connection = github_installation.get_github_for_installation()
        # repo = github_connection.get_repo(res['repository'])

        app.logger.info(tid + f"Create new branch {res['branch']} from branch main. Repository: {repo}")
        sb = repo.get_branch('main')
        repo.create_git_ref('refs/heads/' + res['branch'], sha=sb.commit.sha)

        app.logger.info(tid + "Uploading the file to github")
        content = file_stream.read()
        try:
            old_file = repo.get_contents(file_name)
            repo.update_file(file_name, res['commit_msg'], content, old_file.sha, branch=res['branch'])
        except UnknownObjectException:
            repo.create_file(file_name, res['commit_msg'], content, branch=res['branch'])

        app.logger.info(tid + "Creating the pull request")
        pr = repo.create_pull(base='main',
                              head=res['branch'],
                              title=res['pr_title'],
                              body=res['pr_description'])

        res['pr_url'] = pr.html_url
        app.logger.info(tid + f"Pull request created with url {res['pr_url']}")

    except Exception as e:
        app.logger.error(tid + f"Exception happened: ", e)
        abort(500, e)

    return res


if __name__ == '__main__':
    app.run(debug=debug_mode)
