import pytest
from result import is_ok, is_err

from mlcore_utils.model.common import MLCore_Secret
from mlcore_utils.model.gh import (
    GitHub_Organization,
    GitHub_Repo,
    GitHub_Auth,
)


@pytest.fixture
def a123662_testpipeline_git_repo():
    github_auth = GitHub_Auth(
        "sam-kolli-pgr", MLCore_Secret("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")
    )
    repo = GitHub_Repo.get_from_inputs(
        # git_repo_url="https://github.com/PCDST/bl_bertpipeline_dvc",
        git_repo_url="https://github.com/PCDST/a123662_testpipeline",
        git_repo_branch="master",
        github_auth=github_auth,
    )
    return repo


"""
@pytest.mark.gitactions
def test_get_auth_url(a123662_testpipeline_git_repo: GitHub_Repo):
    if is_ok(git_repo.repo_url_with_auth):
        actual = git_repo.repo_url_with_auth.ok_value.get_secret_value()
        expected = (
            "https://sam-kolli-pgr:github-pat@github.com/PCDST/a123662_testpipeline"
        )
        assert actual == expected
    else:
        print(git_repo.repo_url_with_auth.err_value)
        assert False
"""


@pytest.mark.gitactions
def test_clone_from_gh(a123662_testpipeline_git_repo: GitHub_Repo):
    sha = a123662_testpipeline_git_repo.get_commit_sha()
    if is_ok(sha):
        print(sha.ok_value)
    elif is_err(sha):
        print(sha.err_value)
    else:
        print("unknown")
    # git_repo.clone_repo_and_checkout()
    # git_repo.get_dvc_files()
    # git_repo.produce_tar_ball()
    # interactor = GitHub_Interactor()
    # interactor.clone_repo(git_repo, "/tmp/mlcore")
    ##interactor.get_tarball("/tmp/mlcore", git_repo)
    #
    # from mlcore_utils.model.file import Tarball
    # tarball = Tarball("/tmp/mlcore/" + git_repo.git_repo_name, "abc", "/tmp")
    # tarball.create()

    assert False
