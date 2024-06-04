from __future__ import annotations
import json
from tarfile import TarFile
from requests.auth import HTTPBasicAuth
import shutil
from tempfile import TemporaryDirectory
import requests
from typing import Any, List
import os
from result import Result, Err, Ok, is_err, is_ok
from attrs import define, field
from enum import Enum
from typing import Optional
import git
from git import Repo
from dvc.api import DVCFileSystem
from dvc import repo as dvc_repo

from mlcore_utils.model.common import MLCore_Secret, Secret_Getter
from mlcore_utils.model.file import Tarball
from mlcore_utils.model.common import Http_Method


class GitHub_Organization(str, Enum):
    PCDST = "pcdst"
    PROGRESSIVE = "progressive"


@define
class GitHub_Auth(object):
    username: str = field()
    secret: MLCore_Secret = field()

    @classmethod
    def get_from_username_and_secretstr(
        cls, username: str, secret_as_str: str
    ) -> GitHub_Auth:
        return GitHub_Auth(username, MLCore_Secret(secret_as_str))

    @classmethod
    def get_from_username_and_secret_getter(
        cls, username: str, secret_getter: Secret_Getter
    ) -> GitHub_Auth:
        secret_result = secret_getter.get_secret()
        if is_ok(secret_result):
            return GitHub_Auth(username, secret_result.ok_value)
        elif is_err(secret_result):
            raise Exception(
                "Could not instantiate an object of GitHub. Error while getting the secret "
                + secret_result.err_value
            )
        else:
            raise Exception(
                "Could not instantiate an object of GitHub. Unknown Error while getting the secret"
            )


@define
class GitHub_Repo(object):
    git_repo_url: str = field()
    git_repo_name: str = field()
    git_repo_branch: str = field()
    git_repo_path: Optional[str] = field()
    commit_sha: Optional[str] = field()
    tag: Optional[str] = field()
    github_auth: Optional[GitHub_Auth] = field(default=None)
    github_organization: GitHub_Organization = field(default=GitHub_Organization.PCDST)
    local_path_to_clone_into: str = field(default="/tmp")
    repo_url_with_auth: Result[MLCore_Secret, str] = field(init=False)
    obtained_repo: Optional[Repo] = field(default=None)

    def __attrs_post_init__(self):
        if self.tag and self.commit_sha:
            raise Exception("Provide either a commit sha or a tag; but not both")
        if self.github_auth:
            self.repo_url_with_auth = Ok(self.get_url_with_auth())
        else:
            self.repo_url_with_auth = Err("No GitHUb Auth is provided")
        if os.path.exists(self.get_local_repo_folder()):
            shutil.rmtree(self.get_local_repo_folder())

    def get_local_repo_folder(self) -> str:
        return os.path.join(self.local_path_to_clone_into, self.git_repo_name)

    def get_url_with_auth(self) -> MLCore_Secret:
        if self.github_auth:
            url_comps = self.git_repo_url.split("/")
            url_with_auth = (
                f"https://{self.github_auth.username}:{self.github_auth.secret.get_secret_value()}@"
                + "/".join(url_comps[2:5])
            )
            return MLCore_Secret(url_with_auth)
        else:
            raise Exception("No Auth Values are Supplied to GitHub_Repo")

    def clone_repo(self) -> Result[Repo, str]:
        to_path = os.path.join(self.get_local_repo_folder())
        if is_ok(self.repo_url_with_auth):
            try:
                return Ok(
                    Repo.clone_from(
                        (self.repo_url_with_auth.ok_value.get_secret_value()),
                        to_path,
                    )
                )
            except Exception as e:
                return Err("Repo Clone action failed with error " + str(e))
        elif is_err(self.repo_url_with_auth):
            return Err(self.repo_url_with_auth.err_value)
        else:
            return Err("Repo Clone action failed with unknown error")

    def clone_repo_and_checkout(self, branch: Optional[str] = None):
        br = branch if branch else self.git_repo_branch
        clone_result = self.clone_repo()
        if is_ok(clone_result):
            repo = clone_result.ok_value
            if br.lower() != repo.active_branch.name.lower():
                try:
                    repo.git.fetch("--all")
                    repo.git.checkout("remotes/origin/" + br)
                    # g = git.Git(self.get_local_repo_folder())
                    g = git.Git(
                        os.path.join(self.local_path_to_clone_into, self.git_repo_name)
                    )
                    g.pull(repo.remotes[0].name, self.git_repo_branch)
                except Exception as e:
                    raise e
        elif is_err(clone_result):
            raise Exception(clone_result.err_value)
        else:
            raise Exception("Cloning repo failed with unknown error")

    def check_if_repo_is_dvc_repo(self) -> bool:
        fs = DVCFileSystem(self.get_local_repo_folder())
        return len(fs.find("/", detail=False, dvc_only=True)) > 0

    def get_dvc_files(self):
        fs = DVCFileSystem(self.get_local_repo_folder())
        dvc_files = fs.find("/", detail=False, dvc_only=True)
        if len(dvc_files) > 0:
            r = dvc_repo.Repo(fs.repo.root_dir)
            r.pull()

    def produce_tar_ball(self) -> Result[TarFile, str]:
        repo_dir = self.get_local_repo_folder()
        tarball = Tarball(
            source_directory=repo_dir, name="pipeline", destination_directory="/tmp"
        )
        return tarball.create()

    def _call_github_api(
        self, http_method: Http_Method, endpoint: str
    ) -> requests.Response:
        if http_method == Http_Method.GET:
            if self.github_auth:
                try:
                    r = requests.get(
                        endpoint,
                        auth=HTTPBasicAuth(
                            self.github_auth.username,
                            self.github_auth.secret.get_secret_value(),
                        ),
                        verify="/etc/pki/tls/certs/ca-bundle.crt",
                        timeout=2,
                    )
                except OSError:
                    r = requests.get(
                        endpoint,
                        auth=HTTPBasicAuth(
                            self.github_auth.username,
                            self.github_auth.secret.get_secret_value(),
                        ),
                        timeout=2,
                    )
                return r
            else:
                raise Exception(
                    "No Gitrhub Auth is provided to call the end point " + endpoint
                )

        else:
            raise Exception(
                f"{http_method.value} is Not yet implemented for Git Http actions"
            )

    def _get_commit_sha_from_tag(self) -> Result[str, str]:
        endpoint = f"https://api.github.com/repos/{self.github_organization.value}/{self.git_repo_name}/commits/tags/{self.tag}"
        response = self._call_github_api(Http_Method.GET, endpoint)
        print(response.json())
        if response.status_code == 200:
            return Ok(response.json()["sha"])
        else:
            return Err(
                f"error getting commit sha for repo {self.git_repo_name} and tag {self.tag}. Error: {response.json()['message']}"
            )

    def _get_commit_sha_from_branch(self) -> Result[str, str]:
        owner = self.github_organization.value
        repo = self.git_repo_name
        branch = self.git_repo_branch

        endpoint = f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}"
        response = self._call_github_api(Http_Method.GET, endpoint)
        if response.status_code == 200:
            return Ok(response.json()["commit"]["sha"])
        else:
            return Err(
                f"error getting commit sha for repo {self.git_repo_name} and branch {self.git_repo_branch}. Error: {response.json()['message']}"
            )

    def get_commit_sha(self) -> Result[str, str]:
        if self.commit_sha:
            return Ok(self.commit_sha)
        elif self.tag:
            return self._get_commit_sha_from_tag()
        else:
            return self._get_commit_sha_from_branch()

    @classmethod
    def get_from_inputs(
        cls,
        git_repo_url: str,
        git_repo_branch: Optional[str] = None,
        git_repo_path: Optional[str] = None,
        commit_sha: Optional[str] = None,
        tag: Optional[str] = None,
        github_auth: Optional[GitHub_Auth] = None,
    ) -> GitHub_Repo:
        url_components = git_repo_url.split("/")
        org = url_components[3].lower()
        if org not in ["pcdst", "progressive"]:
            raise ValueError("GitHub Org has to be PCDST")
        if org == "progressive":
            raise ValueError(
                "Models in 'progressive' org are not yet handled by Blacklodge"
            )
        repo_name = url_components[4]
        branch = url_components[6] if len(url_components) >= 6 else git_repo_branch
        if not branch:
            raise ValueError(
                "Repo branch cannot be empty. Specify it either in the git_repo_url or as git_repo_branch in the config file"
            )
        path = git_repo_path if len(url_components) < 8 else url_components[7]

        instance = GitHub_Repo(
            git_repo_url=git_repo_url,
            git_repo_name=repo_name,
            git_repo_branch=branch,
            git_repo_path=path,
            commit_sha=commit_sha,
            tag=tag,
            github_auth=github_auth,
            github_organization=GitHub_Organization(org),
        )
        return instance


@define
class GitHub_Interactor(object):
    # github_client_credential: Any = field()
    # github_service_account: str = field()
    # github_service_pat: Any = field()

    def check_if_dvc_repo(self, repo_dir: str) -> bool:
        """
        Checks if the passed Github repo is a DVC (Data Version Control) repo
        DVC repo will be configured in case when you want to store large sized files greater than 100mb.
        Git LFS wasn't used in such scenarios because S3 bucket used by Git LFS is blocked by PGR.
        DVC lets you configure the remote storage backend to use for large file storage.

        Returns
        -------
        boolean
            if the repo is a DVC repo. This result is later used to do post processing.
        """
        for file in os.listdir(repo_dir):
            if file.endswith(".dvc"):
                return True
        return False

    def clone_repo(
        self, git_repo: GitHub_Repo, parent_folder: str
    ) -> Result[Repo, str]:
        to_path = os.path.join(parent_folder, git_repo.git_repo_name)
        if is_ok(git_repo.repo_url_with_auth):
            try:
                return Ok(
                    Repo.clone_from(
                        (git_repo.repo_url_with_auth.ok_value.get_secret_value()),
                        to_path,
                    )
                )
            except Exception as e:
                return Err("Repo Clone action failed with error " + str(e))
        elif is_err(git_repo.repo_url_with_auth):
            return Err(git_repo.repo_url_with_auth.err_value)
        else:
            return Err("Repo Clone action failed with unknown error")

    def get_tarball(
        self, local_folder: str, git_repo: GitHub_Repo, branch: Optional[str] = None
    ):
        if branch:
            br = branch
        else:
            br = git_repo.git_repo_branch

        if is_ok(git_repo.repo_url_with_auth):
            url = f"{git_repo.repo_url_with_auth.ok_value.get_secret_value()}/archive/{br}.tar.gz"
        else:
            raise Exception("error")

        local_path = os.path.join(
            local_folder, f"{git_repo.git_repo_name}-{git_repo.git_repo_branch}.tar.gz"
        )
        with requests.get(url=url) as response:
            response.raise_for_status()
            print(response.status_code)
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
